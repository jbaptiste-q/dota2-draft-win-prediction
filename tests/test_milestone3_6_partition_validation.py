"""Focused offline tests for the Milestone 3.6 partition validation gate."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from src.liquipedia_backfill import completion_validation
from src.liquipedia_backfill.client import HttpResponse
from src.liquipedia_backfill.config import BackfillConfig
from src.liquipedia_backfill.publication import PartitionRun
from src.liquipedia_backfill.runner import BackfillRunner


class FakeClock:
    """Deterministic clock whose waits never block the test process."""

    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += timedelta(seconds=seconds)


def complete_draft() -> dict[str, str]:
    """Return an exact, source-shaped two-team draft."""
    draft = {
        "team1side": "radiant",
        "team2side": "dire",
    }
    draft.update(
        {
            f"team1hero{slot}": f"Radiant Hero {slot}"
            for slot in range(1, 6)
        }
    )
    draft.update(
        {
            f"team2hero{slot}": f"Dire Hero {slot}"
            for slot in range(1, 6)
        }
    )
    draft.update(
        {
            f"team1ban{slot}": f"Radiant Ban {slot}"
            for slot in range(1, 8)
        }
    )
    draft.update(
        {
            f"team2ban{slot}": f"Dire Ban {slot}"
            for slot in range(1, 8)
        }
    )
    return draft


def source_record(
    *,
    index: int,
    match_date: datetime,
    winner: int,
    duration: str | None = "30m00s",
    tier: str = "1",
    finished: bool = True,
) -> dict[str, object]:
    """Return one official-response-shaped match with one game."""
    match_id = f"m36_validation_match_{index}"
    date_text = match_date.strftime("%Y-%m-%d %H:%M:%S")
    game: dict[str, object] = {
        "match2gameid": f"{match_id}_game_1",
        "date": date_text,
        "patch": "7.31",
        "winner": winner,
        "extradata": complete_draft(),
    }
    if duration is not None:
        game["length"] = duration
    return {
        "match2id": match_id,
        "date": date_text,
        "extradata": {
            "timestamp": int(match_date.timestamp()),
            "timezoneoffset": "+00:00",
        },
        "patch": "7.31",
        "liquipediatier": tier,
        "tournament": "M3.6 Offline Validation",
        "series": "Group Stage",
        "bestof": 1,
        "finished": int(finished),
        "winner": winner,
        "match2opponents": [
            {
                "id": 1,
                "name": "Team One",
                "template": "TeamOne",
                "score": int(winner == 1),
                "match2players": [],
            },
            {
                "id": 2,
                "name": "Team Two",
                "template": "TeamTwo",
                "score": int(winner == 2),
                "match2players": [],
            },
        ],
        "match2games": [game],
    }


def completed_q1(
    tmp_path: Path,
    records: list[dict[str, object]],
) -> tuple[BackfillConfig, PartitionRun]:
    """Acquire one synthetic page through the real resumable runner."""
    config = BackfillConfig(
        start_utc=datetime(2022, 1, 1, tzinfo=UTC),
        end_utc=datetime(2022, 4, 1, tzinfo=UTC),
        tiers=("1", "2"),
        page_size=100,
        max_requests=8,
        raw_root=tmp_path / "raw",
        run_root=tmp_path / "runs",
        normalized_output_root=tmp_path / "normalized",
    )
    body = (
        json.dumps(
            {"result": records, "error": []},
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")

    def fetch(spec, api_key, timeout):
        del spec, api_key, timeout
        return HttpResponse(
            body=body,
            status=200,
            content_type="application/json",
            content_encoding="",
        )

    clock = FakeClock(datetime(2026, 7, 29, 12, 0, tzinfo=UTC))
    result = BackfillRunner(
        fetcher=fetch,
        clock=clock,
        sleeper=clock.sleep,
    ).run(config, api_key="offline-test-key")
    assert result.status == "complete"
    return config, PartitionRun(
        partition_id="2022-Q1",
        run_id=config.run_id,
    )


def balanced_records(
    *,
    excluded: int = 0,
) -> list[dict[str, object]]:
    """Return three eligible games across both target classes plus exclusions."""
    base = datetime(2022, 2, 1, 12, 0, tzinfo=UTC)
    records = [
        source_record(index=1, match_date=base, winner=1),
        source_record(
            index=2,
            match_date=base + timedelta(days=1),
            winner=2,
        ),
        source_record(
            index=3,
            match_date=base + timedelta(days=2),
            winner=1,
        ),
    ]
    records.extend(
        source_record(
            index=4 + offset,
            match_date=base + timedelta(days=3 + offset),
            winner=1,
            duration=None,
        )
        for offset in range(excluded)
    )
    return records


def test_completed_partition_reuses_existing_layers_and_returns_public_metrics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, selection = completed_q1(
        tmp_path,
        balanced_records(excluded=1),
    )
    calls = {
        "finalize": 0,
        "verify_partition": 0,
        "verify_sequence": 0,
        "build_training": 0,
    }
    original_finalize = completion_validation.finalize_completed_run
    original_verify_partition = completion_validation.verify_partition
    original_verify_sequence = completion_validation.verify_partition_sequence
    original_build_training = completion_validation.build_training_dataset

    def finalize_spy(value):
        calls["finalize"] += 1
        return original_finalize(value)

    def partition_spy(value, *, run_root):
        calls["verify_partition"] += 1
        return original_verify_partition(value, run_root=run_root)

    def sequence_spy(values, *, mode, repository_root):
        calls["verify_sequence"] += 1
        return original_verify_sequence(
            values,
            mode=mode,
            repository_root=repository_root,
        )

    def training_spy(value):
        calls["build_training"] += 1
        assert value.normalized_build.name.startswith("build_")
        assert value.filter_payload() == {
            "start_utc": None,
            "end_utc": None,
            "tiers": [],
            "patches": [],
            "tournaments": [],
        }
        return original_build_training(value)

    monkeypatch.setattr(
        completion_validation,
        "finalize_completed_run",
        finalize_spy,
    )
    monkeypatch.setattr(
        completion_validation,
        "verify_partition",
        partition_spy,
    )
    monkeypatch.setattr(
        completion_validation,
        "verify_partition_sequence",
        sequence_spy,
    )
    monkeypatch.setattr(
        completion_validation,
        "build_training_dataset",
        training_spy,
    )

    metrics = completion_validation.validate_completed_partition(
        "2022-Q1",
        config,
        ((selection.partition_id, selection.run_id),),
        tmp_path,
    )

    assert calls == {
        "finalize": 1,
        "verify_partition": 1,
        "verify_sequence": 1,
        "build_training": 1,
    }
    assert metrics.sequence_mode == "provisional-prefix"
    assert metrics.accepted_matches == 4
    assert metrics.normalized_games == 4
    assert metrics.eligible_games == 3
    assert metrics.excluded_games == 1
    assert metrics.eligibility_percentage == 75.0
    assert dict(metrics.target_class_counts) == {"false": 1, "true": 2}
    assert dict(metrics.exclusion_counts) == {"missing_game_duration": 1}
    assert metrics.quarantined_records == 0

    assert metrics.payload() == metrics.to_payload()
    public_text = json.dumps(metrics.payload(), sort_keys=True)
    assert str(tmp_path) not in public_text
    assert "offline-test-key" not in public_text
    assert metrics.normalized_schema_version == "liquipedia-dota-draft-v1"
    assert metrics.supervised_schema_version == "dota-draft-supervised-v1"


@pytest.mark.parametrize(
    "scope_violation",
    ["tier", "finished", "timestamp"],
)
def test_partition_scope_fails_closed(
    tmp_path: Path,
    scope_violation: str,
) -> None:
    records = balanced_records()
    if scope_violation == "tier":
        records[0]["liquipediatier"] = "3"
        expected = "Tier 1/2 scope"
    elif scope_violation == "finished":
        records[0]["finished"] = 0
        expected = "unfinished or unknown"
    else:
        outside = datetime(2021, 12, 31, 12, 0, tzinfo=UTC)
        records[0]["date"] = outside.strftime("%Y-%m-%d %H:%M:%S")
        records[0]["extradata"]["timestamp"] = int(outside.timestamp())
        records[0]["match2games"][0]["date"] = records[0]["date"]
        expected = "half-open partition scope"
    config, selection = completed_q1(tmp_path, records)

    with pytest.raises(
        completion_validation.PartitionValidationError,
        match=expected,
    ):
        completion_validation.validate_completed_partition(
            "2022-Q1",
            config,
            (selection,),
            tmp_path,
            tmp_path / "training",
        )


def test_partition_rejects_eligibility_below_seventy_percent(
    tmp_path: Path,
) -> None:
    records = balanced_records()
    records[2]["match2games"][0].pop("length")
    config, selection = completed_q1(tmp_path, records)

    with pytest.raises(
        completion_validation.PartitionValidationError,
        match="Supervised eligibility",
    ):
        completion_validation.validate_completed_partition(
            "2022-Q1",
            config,
            (selection,),
            tmp_path,
            tmp_path / "training",
        )


def test_partition_requires_both_supervised_target_classes(
    tmp_path: Path,
) -> None:
    base = datetime(2022, 2, 1, 12, 0, tzinfo=UTC)
    records = [
        source_record(
            index=index,
            match_date=base + timedelta(days=index),
            winner=1,
        )
        for index in range(1, 4)
    ]
    config, selection = completed_q1(tmp_path, records)

    with pytest.raises(
        completion_validation.PartitionValidationError,
        match="both radiant_win classes",
    ):
        completion_validation.validate_completed_partition(
            "2022-Q1",
            config,
            (selection,),
            tmp_path,
            tmp_path / "training",
        )


def test_exclusion_contract_is_exact_and_rejects_unknown_values() -> None:
    assert completion_validation.ALLOWED_EXCLUSION_REASONS == {
        "invalid_series_result",
        "match_not_finished",
        "invalid_game_result",
        "missing_game_winner",
        "missing_or_invalid_sides",
        "incomplete_team1_picks",
        "incomplete_team2_picks",
        "incomplete_team1_bans",
        "incomplete_team2_bans",
        "duplicate_picked_hero",
        "missing_game_duration",
    }
    frame = pd.DataFrame(
        {"exclusion_reason": ["new_unreviewed_reason"]}
    )

    with pytest.raises(
        completion_validation.PartitionValidationError,
        match="Unsupported supervised exclusion",
    ):
        completion_validation._reason_counts(frame)


def test_supervised_lineage_tampering_stops_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, selection = completed_q1(tmp_path, balanced_records())
    original = completion_validation.build_training_dataset

    def tampered_build(value):
        result = original(value)
        manifest = json.loads(
            result.manifest_path.read_text(encoding="utf-8")
        )
        manifest["normalized_source"]["build_fingerprint"] = "0" * 64
        result.manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return result

    monkeypatch.setattr(
        completion_validation,
        "build_training_dataset",
        tampered_build,
    )

    with pytest.raises(ValueError, match="lineage"):
        completion_validation.validate_completed_partition(
            "2022-Q1",
            config,
            (selection,),
            tmp_path,
            tmp_path / "training",
        )


def test_current_partition_must_end_the_completed_prefix(
    tmp_path: Path,
) -> None:
    config = BackfillConfig(
        start_utc=datetime(2022, 1, 1, tzinfo=UTC),
        end_utc=datetime(2022, 4, 1, tzinfo=UTC),
    )
    wrong = PartitionRun(
        partition_id="2022-Q1",
        run_id="different-safe-run",
    )

    with pytest.raises(
        completion_validation.PartitionValidationError,
        match="final completed-prefix",
    ):
        completion_validation.validate_completed_partition(
            "2022-Q1",
            config,
            (wrong,),
            tmp_path,
            tmp_path / "training",
        )
