"""Offline tests for Milestone 3 acquisition and supervised datasets."""

from __future__ import annotations

import ast
import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from src.draft_training_dataset import (
    TrainingDatasetConfig,
    build_training_dataset,
)
from src.draft_training_dataset.builder import (
    TrainingDatasetError,
    validate_required_gameplay_metadata,
)
from src.draft_training_dataset.schema import (
    DRAFT_FEATURE_COLUMNS,
    FORBIDDEN_COLUMNS,
    SCHEMA_VERSION,
    TRAINING_COLUMNS,
)
from src.liquipedia_backfill.assembly import assemble_snapshot
from src.liquipedia_backfill.cache import CacheError, CacheStore, sha256_bytes
from src.liquipedia_backfill.client import HttpResponse
from src.liquipedia_backfill.config import BackfillConfig
from src.liquipedia_backfill.finalize import finalize_completed_run
from src.liquipedia_backfill.planner import create_plan, request_spec
from src.liquipedia_backfill.runner import (
    BackfillRunner,
    ResponseEnvelopeError,
)


class FakeClock:
    """Deterministic clock whose sleeper advances without wall-clock delay."""

    def __init__(self):
        self.value = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
        self.sleeps: list[float] = []

    def __call__(self) -> datetime:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.value += timedelta(seconds=seconds)


def test_supervised_builder_rejects_stale_trainable_missing_duration() -> None:
    games = pd.DataFrame(
        [
            {
                "game_key": "eligible-with-duration",
                "is_trainable_draft": True,
                "duration_seconds": 2400,
            },
            {
                "game_key": "already-excluded",
                "is_trainable_draft": False,
                "duration_seconds": pd.NA,
            },
            {
                "game_key": "stale-trainable-row",
                "is_trainable_draft": True,
                "duration_seconds": pd.NA,
            },
        ]
    )

    with pytest.raises(
        TrainingDatasetError,
        match="stale-trainable-row",
    ):
        validate_required_gameplay_metadata(games)


def config(
    tmp_path: Path,
    *,
    page_size: int = 100,
    max_requests: int = 4,
) -> BackfillConfig:
    """Create one isolated approved-scope configuration."""
    return BackfillConfig(
        start_utc=datetime(2026, 7, 1, tzinfo=UTC),
        end_utc=datetime(2026, 7, 27, tzinfo=UTC),
        tiers=("2", "1", "2"),
        patches=("7.39e",),
        page_size=page_size,
        max_requests=max_requests,
        raw_root=tmp_path / "raw",
        run_root=tmp_path / "runs",
        normalized_output_root=tmp_path / "normalized",
    )


def response_body(records: list[dict]) -> bytes:
    """Encode one deterministic successful API envelope."""
    return (
        json.dumps(
            {"result": records, "error": []},
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def complete_draft() -> dict[str, str | int]:
    """Return a complete source-shaped per-team draft."""
    fields: dict[str, str | int] = {
        "team1side": "dire",
        "team2side": "radiant",
        "timestamp": 1710000000,
    }
    fields.update(
        {
            f"team1hero{slot}": f"Dire Pick {slot}"
            for slot in range(1, 6)
        }
    )
    fields.update(
        {
            f"team2hero{slot}": f"Radiant Pick {slot}"
            for slot in range(1, 6)
        }
    )
    fields.update(
        {
            f"team1ban{slot}": f"Dire Ban {slot}"
            for slot in range(1, 8)
        }
    )
    fields.update(
        {
            f"team2ban{slot}": f"Radiant Ban {slot}"
            for slot in range(1, 8)
        }
    )
    return fields


def opponent(slot: int, name: str) -> dict:
    """Return one compact series opponent."""
    return {
        "id": slot,
        "name": name,
        "template": name.replace(" ", ""),
        "score": 1,
        "match2players": [],
    }


def historical_fixture() -> dict:
    """Return complete, incomplete, and upcoming match shapes."""
    full = {
        "match2id": "Full_0001",
        "date": "2024-03-09 16:00:00",
        "extradata": {"timestamp": 1710000000, "timezoneoffset": "+00:00"},
        "patch": "7.35c",
        "liquipediatier": "1",
        "tournament": "Test Invitational",
        "series": "Final",
        "bestof": 3,
        "finished": 1,
        "winner": 2,
        "match2opponents": [
            opponent(1, "Team Alpha"),
            opponent(2, "Team Beta"),
        ],
        "match2games": [
            {
                "match2gameid": "Full_0001_m2g_001",
                "date": "2024-03-09 16:00:00",
                "patch": "7.35c",
                "length": "41m05s",
                "winner": 2,
                "extradata": complete_draft(),
            }
        ],
    }
    incomplete = {
        "match2id": "Legacy_0001",
        "date": "2018-01-01 12:00:00",
        "extradata": {"timestamp": 1514808000, "timezoneoffset": "+00:00"},
        "patch": "7.07",
        "liquipediatier": "2",
        "tournament": "Legacy Cup",
        "bestof": 1,
        "finished": 1,
        "winner": 1,
        "match2opponents": [
            opponent(1, "Old One"),
            opponent(2, "Old Two"),
        ],
        "match2games": [
            {
                "match2gameid": "Legacy_0001_m2g_001",
                "length": "38:12",
                "winner": 1,
                "extradata": {
                    "team1side": "radiant",
                    "team2side": "dire",
                    **{
                        f"team1hero{slot}": f"Legacy One {slot}"
                        for slot in range(1, 6)
                    },
                    **{
                        f"team2hero{slot}": f"Legacy Two {slot}"
                        for slot in range(1, 6)
                    },
                },
            }
        ],
    }
    upcoming = {
        "match2id": "Upcoming_0001",
        "date": "2030-01-01 18:00:00",
        "extradata": {"timezoneoffset": "+00:00"},
        "liquipediatier": "2",
        "tournament": "Future Cup",
        "bestof": 3,
        "finished": 0,
        "winner": 0,
        "match2opponents": [
            opponent(1, "Future One"),
            opponent(2, "Future Two"),
        ],
        "match2games": [
            {
                "match2gameid": "Upcoming_0001_m2g_001",
                "winner": 0,
                "extradata": {},
            }
        ],
    }
    return {"result": [upcoming, full, incomplete], "error": []}


def test_plan_is_exact_bounded_and_secret_free(tmp_path: Path) -> None:
    pilot = config(tmp_path)
    plan = create_plan(pilot)
    payload = plan.payload(pilot)
    first = payload["requests"][0]

    assert pilot.tiers == ("1", "2")
    assert len(plan.requests) == 4
    assert payload["expected_request_count"]["hard_maximum"] == 4
    assert first["parameters"]["offset"] == 0
    assert first["parameters"]["limit"] == 100
    assert first["parameters"]["order"] == "date ASC, match2id ASC"
    assert "[[finished::1]]" in first["parameters"]["conditions"]
    assert "[[liquipediatier::1]]" in first["parameters"]["conditions"]
    assert "[[liquipediatier::2]]" in first["parameters"]["conditions"]
    assert "[[patch::" not in first["parameters"]["conditions"]
    assert "Authorization" not in first["url_without_credentials"]
    assert "api_key" not in json.dumps(payload).casefold()
    assert [request.offset for request in plan.requests] == [0, 100, 200, 300]


def test_runner_checkpoints_resumes_and_reuses_cache(tmp_path: Path) -> None:
    pilot = config(tmp_path, page_size=2, max_requests=4)
    clock = FakeClock()
    calls: list[int] = []

    def fetch(spec, api_key, timeout):
        assert api_key == "test-key"
        assert "test-key" not in spec.url
        calls.append(spec.sequence)
        records = (
            [{"match2id": "A"}, {"match2id": "B"}]
            if spec.sequence == 1
            else [{"match2id": "C"}]
        )
        return HttpResponse(
            body=response_body(records),
            status=200,
            content_type="application/json",
            content_encoding="gzip",
        )

    runner = BackfillRunner(
        fetcher=fetch,
        clock=clock,
        sleeper=clock.sleep,
    )
    first = runner.run(pilot, api_key="test-key")
    second = runner.run(pilot, api_key="test-key")

    assert first.status == "complete"
    assert first.request_count == 2
    assert first.records_seen == 3
    assert calls == [1, 2]
    assert clock.sleeps == [pytest.approx(67.0)]
    assert second.status == "complete"
    assert calls == [1, 2]
    checkpoint = json.loads(first.checkpoint_path.read_text())
    assert checkpoint["run"]["status"] == "complete"
    assert len(checkpoint["pages"]) == 2

    reuse_config = config(tmp_path, page_size=2, max_requests=5)
    reused = runner.run(reuse_config, api_key="test-key")
    assert reused.status == "complete"
    assert reused.request_count == 0
    assert reused.cache_hit_count == 2
    assert calls == [1, 2]


def test_full_pages_stop_at_hard_request_budget(tmp_path: Path) -> None:
    pilot = config(tmp_path, page_size=1, max_requests=2)
    clock = FakeClock()

    def fetch(spec, api_key, timeout):
        return HttpResponse(
            body=response_body([{"match2id": f"M{spec.sequence}"}]),
            status=200,
            content_type="application/json",
            content_encoding="",
        )

    result = BackfillRunner(
        fetcher=fetch,
        clock=clock,
        sleeper=clock.sleep,
    ).run(pilot, api_key="test-key")

    assert result.status == "budget_exhausted"
    assert result.request_count == 2
    assert result.accepted_page_count == 2


def test_cache_detects_tampering(tmp_path: Path) -> None:
    pilot = config(tmp_path)
    spec = request_spec(pilot, 1)
    store = CacheStore(pilot.cache_directory)
    cached = store.put_success(
        spec,
        body=response_body([]),
        record_count=0,
        response_metadata={"status": 200},
        acquired_at_utc="2026-07-27T12:00:00+00:00",
    )
    cached.response_path.write_text('{"result":[{"match2id":"tampered"}]}')

    with pytest.raises(CacheError, match="checksum mismatch"):
        store.get(spec)


def test_invalid_response_is_preserved_but_not_cached(tmp_path: Path) -> None:
    pilot = config(tmp_path)
    clock = FakeClock()
    invalid_body = b'{"result":{"not":"an-array"}}\n'

    def fetch(spec, api_key, timeout):
        return HttpResponse(
            body=invalid_body,
            status=200,
            content_type="application/json",
            content_encoding="",
        )

    with pytest.raises(ResponseEnvelopeError, match="result must be an array"):
        BackfillRunner(
            fetcher=fetch,
            clock=clock,
            sleeper=clock.sleep,
        ).run(pilot, api_key="test-key")

    failed = list(
        (pilot.run_directory / "failed_responses").glob("*.json")
    )
    assert len(failed) == 1
    assert failed[0].read_bytes() == invalid_body
    assert CacheStore(pilot.cache_directory).get(
        request_spec(pilot, 1)
    ) is None
    checkpoint = json.loads(
        (pilot.run_directory / "checkpoint.json").read_text()
    )
    assert checkpoint["run"]["status"] == "failed"
    assert checkpoint["run"]["request_count"] == 1
    assert checkpoint["requests"][0]["outcome"] == "invalid_response"


def test_assembly_deduplicates_and_quarantines_conflicts(
    tmp_path: Path,
) -> None:
    duplicate_game = {"match2gameid": "A_game_1", "winner": 1}
    match_a = {
        "match2id": "A",
        "match2games": [duplicate_game, duplicate_game],
    }
    match_b1 = {"match2id": "B", "winner": 1, "match2games": []}
    match_b2 = {"match2id": "B", "winner": 2, "match2games": []}
    page1 = response_body([match_a, match_b1, {"winner": 1}])
    page2 = response_body([match_a, match_b2])
    path1 = tmp_path / "page1.json"
    path2 = tmp_path / "page2.json"
    path1.write_bytes(page1)
    path2.write_bytes(page2)
    pages = [
        {
            "sequence": 1,
            "response_path": str(path1),
            "response_sha256": sha256_bytes(page1),
        },
        {
            "sequence": 2,
            "response_path": str(path2),
            "response_sha256": sha256_bytes(page2),
        },
    ]

    result = assemble_snapshot(
        pages,
        config_hash="config-hash",
        output_root=tmp_path / "assembly",
        request_count=2,
        cache_hit_count=0,
    )
    snapshot = json.loads(result.snapshot_path.read_text())

    assert [record["match2id"] for record in snapshot["result"]] == ["A"]
    assert len(snapshot["result"][0]["match2games"]) == 1
    assert result.accepted_matches == 1
    assert result.accepted_games == 1
    assert result.duplicate_matches == 1
    assert result.duplicate_games == 1
    quarantine = [
        json.loads(line)
        for line in result.quarantine_path.read_text().splitlines()
    ]
    assert {item["reason"] for item in quarantine} == {
        "missing_match2id",
        "conflicting_match_versions",
    }


def test_offline_end_to_end_handoff_and_canonical_training_dataset(
    tmp_path: Path,
) -> None:
    pilot = config(tmp_path, page_size=100, max_requests=4)
    clock = FakeClock()
    payload_bytes = (
        json.dumps(historical_fixture(), sort_keys=True) + "\n"
    ).encode("utf-8")

    def fetch(spec, api_key, timeout):
        return HttpResponse(
            body=payload_bytes,
            status=200,
            content_type="application/json",
            content_encoding="gzip",
        )

    acquisition = BackfillRunner(
        fetcher=fetch,
        clock=clock,
        sleeper=clock.sleep,
    ).run(pilot, api_key="test-key")
    assert acquisition.status == "complete"
    finalized = finalize_completed_run(pilot)

    assert finalized.assembly.accepted_matches == 3
    assert finalized.normalized.export.output_directory.is_dir()
    assert (finalized.reports_directory / "coverage_by_year.parquet").is_file()
    assert (
        finalized.reports_directory / "eligibility_failures.parquet"
    ).is_file()

    training_config = TrainingDatasetConfig(
        normalized_build=finalized.normalized.export.output_directory,
        output_root=tmp_path / "training",
    )
    first = build_training_dataset(training_config)
    second = build_training_dataset(training_config)
    assert first.output_directory == second.output_directory
    assert first.training_rows == 1
    assert first.excluded_rows == 2

    with duckdb.connect() as connection:
        training = connection.execute(
            "SELECT * FROM read_parquet(?)",
            [str(first.training_path)],
        ).fetchdf()
        exclusions = connection.execute(
            "SELECT * FROM read_parquet(?)",
            [str(first.exclusions_path)],
        ).fetchdf()

    assert tuple(training.columns) == TRAINING_COLUMNS
    assert training.loc[0, "sample_id"] == training.loc[0, "game_key"]
    assert training.loc[0, "radiant_pick_slot_1"] == "radiant-pick-1"
    assert training.loc[0, "dire_pick_slot_1"] == "dire-pick-1"
    assert bool(training.loc[0, "radiant_win"])
    assert not FORBIDDEN_COLUMNS.intersection(training.columns)
    assert "team1_pick_slot_1_hero_key" not in training.columns
    assert not {"split", "first_pick", "global_draft_order"}.intersection(
        training.columns
    )
    assert set(exclusions["exclusion_reason"]) == {
        "incomplete_team1_bans",
        "match_not_finished",
    }

    schema = json.loads(first.schema_path.read_text())
    assert schema["schema_version"] == SCHEMA_VERSION
    assert all(
        schema["roles"][column] == "draft_feature"
        for column in DRAFT_FEATURE_COLUMNS
    )
    assert schema["roles"]["source_match_id"] == "group_identifier"
    assert schema["roles"]["radiant_win"] == "target"

    manifest = json.loads(first.manifest_path.read_text())
    assert manifest["normalized_source"]["build_fingerprint"] == (
        finalized.normalized.export.build_fingerprint
    )
    assert manifest["row_counts"]["training"] == 1
    assert manifest["quality_report"]["target_class_counts"] == {"True": 1}


def test_training_filters_and_input_checksum_validation(tmp_path: Path) -> None:
    pilot = config(tmp_path)
    clock = FakeClock()
    payload_bytes = (
        json.dumps(historical_fixture(), sort_keys=True) + "\n"
    ).encode("utf-8")

    def fetch(spec, api_key, timeout):
        return HttpResponse(
            body=payload_bytes,
            status=200,
            content_type="application/json",
            content_encoding="",
        )

    BackfillRunner(
        fetcher=fetch,
        clock=clock,
        sleeper=clock.sleep,
    ).run(pilot, api_key="test-key")
    normalized = finalize_completed_run(
        pilot
    ).normalized.export.output_directory
    filtered = build_training_dataset(
        TrainingDatasetConfig(
            normalized_build=normalized,
            output_root=tmp_path / "filtered",
            tiers=("1",),
            patches=("7.35c",),
            tournaments=("Test Invitational",),
            start_utc=datetime(2024, 1, 1, tzinfo=UTC),
            end_utc=datetime(2025, 1, 1, tzinfo=UTC),
        )
    )
    assert filtered.training_rows == 1
    assert filtered.excluded_rows == 0

    copied = tmp_path / "normalized-copy"
    shutil.copytree(normalized, copied)
    games_path = copied / "games.parquet"
    original = games_path.read_bytes()
    games_path.write_bytes(original + b"tamper")
    with pytest.raises(TrainingDatasetError, match="checksum mismatch"):
        build_training_dataset(
            TrainingDatasetConfig(
                normalized_build=copied,
                output_root=tmp_path / "tampered-output",
            )
        )


def test_supervised_package_has_no_upstream_layer_imports() -> None:
    package = Path(__file__).resolve().parents[1] / "src" / "draft_training_dataset"
    forbidden_prefixes = (
        "src.liquipedia_backfill",
        "src.liquipedia_pipeline",
        "scripts",
    )
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        assert not any(
            name.startswith(forbidden_prefixes)
            for name in imported
        ), (path, imported)
