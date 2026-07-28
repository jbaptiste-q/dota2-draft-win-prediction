"""Offline tests for verified Milestone 3.5 aggregate publication."""

from __future__ import annotations

import ast
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.liquipedia_backfill.client import HttpResponse
from src.liquipedia_backfill.campaign import (
    CampaignConfig,
    create_campaign_plan,
)
from src.liquipedia_backfill.config import BackfillConfig
from src.liquipedia_backfill.finalize import finalize_completed_run
from src.liquipedia_backfill.publication import (
    PublicationConfig,
    PublicationError,
    PublicationMode,
    PartitionRun,
    parse_partition_mapping,
    publish_historical_dataset,
    verify_partition,
    verify_partition_sequence,
)
from src.liquipedia_backfill.runner import BackfillRunner


class FakeClock:
    """Deterministic test clock with non-blocking rate-limit waits."""

    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += timedelta(seconds=seconds)


def complete_draft() -> dict[str, str]:
    """Return a valid source-shaped draft with unique picked heroes."""
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
    match_id: str,
    match_date: datetime,
) -> dict[str, object]:
    """Return one complete and supervised-eligible official response record."""
    date_text = match_date.strftime("%Y-%m-%d %H:%M:%S")
    return {
        "match2id": match_id,
        "date": date_text,
        "extradata": {
            "timestamp": int(match_date.timestamp()),
            "timezoneoffset": "+00:00",
        },
        "patch": "7.31",
        "liquipediatier": "1",
        "tournament": "Offline Publication Test",
        "series": "Group Stage",
        "bestof": 1,
        "finished": 1,
        "winner": 1,
        "match2opponents": [
            {
                "id": 1,
                "name": "Team One",
                "template": "TeamOne",
                "score": 1,
                "match2players": [],
            },
            {
                "id": 2,
                "name": "Team Two",
                "template": "TeamTwo",
                "score": 0,
                "match2players": [],
            },
        ],
        "match2games": [
            {
                "match2gameid": f"{match_id}_game_1",
                "date": date_text,
                "patch": "7.31",
                "length": "30m00s",
                "winner": 1,
                "extradata": complete_draft(),
            }
        ],
    }


def complete_partition(
    tmp_path: Path,
    *,
    start_utc: datetime,
    end_utc: datetime,
    match_id: str,
    match_date: datetime,
) -> PartitionRun:
    """Create a completed and finalized partition through existing code."""
    config = BackfillConfig(
        start_utc=start_utc,
        end_utc=end_utc,
        tiers=("1", "2"),
        page_size=100,
        max_requests=8,
        raw_root=tmp_path / "raw",
        run_root=tmp_path / "runs",
        normalized_output_root=tmp_path / "partition-normalized",
    )
    body = (
        json.dumps(
            {
                "result": [
                    source_record(match_id=match_id, match_date=match_date)
                ],
                "error": [],
            },
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")

    def fetch(spec, api_key, timeout):
        return HttpResponse(
            body=body,
            status=200,
            content_type="application/json",
            content_encoding="",
        )

    clock = FakeClock(datetime(2026, 7, 28, 12, 0, tzinfo=UTC))
    acquired = BackfillRunner(
        fetcher=fetch,
        clock=clock,
        sleeper=clock.sleep,
    ).run(config, api_key="offline-test-key")
    assert acquired.status == "complete"
    finalize_completed_run(config)
    quarter = ((start_utc.month - 1) // 3) + 1
    return PartitionRun(
        partition_id=f"{start_utc.year}-Q{quarter}",
        run_id=config.run_id,
    )


def prepared_prefix(
    tmp_path: Path,
    *,
    duplicate_match_id: bool = False,
) -> tuple[PartitionRun, PartitionRun]:
    """Create two ordered completed historical quarters."""
    first = complete_partition(
        tmp_path,
        start_utc=datetime(2022, 1, 1, tzinfo=UTC),
        end_utc=datetime(2022, 4, 1, tzinfo=UTC),
        match_id="publication_match_q1",
        match_date=datetime(2022, 2, 1, 12, 0, tzinfo=UTC),
    )
    second = complete_partition(
        tmp_path,
        start_utc=datetime(2022, 4, 1, tzinfo=UTC),
        end_utc=datetime(2022, 7, 1, tzinfo=UTC),
        match_id=(
            "publication_match_q1"
            if duplicate_match_id
            else "publication_match_q2"
        ),
        match_date=datetime(2022, 5, 1, 12, 0, tzinfo=UTC),
    )
    return first, second


def publication_config(
    tmp_path: Path,
    partitions: tuple[PartitionRun, ...],
    *,
    mode: PublicationMode = PublicationMode.PROVISIONAL_PREFIX,
) -> PublicationConfig:
    """Return one isolated publisher configuration."""
    return PublicationConfig(
        repository_root=tmp_path,
        partition_runs=partitions,
        mode=mode,
        run_root=tmp_path / "runs",
        normalized_output_root=tmp_path / "normalized",
        training_output_root=tmp_path / "training",
        release_root=tmp_path / "releases",
    )


def test_provisional_prefix_publication_is_reconciled_and_idempotent(
    tmp_path: Path,
) -> None:
    partitions = prepared_prefix(tmp_path)
    config = publication_config(tmp_path, partitions)

    first = publish_historical_dataset(config)
    second = publish_historical_dataset(config)

    assert first.release_status == "provisional_contiguous_prefix"
    assert first.release_fingerprint == second.release_fingerprint
    assert first.release_directory == second.release_directory
    assert first.normalized_games == 2
    assert first.eligible_games == 2
    assert first.excluded_games == 0
    assert first.normalized_games == first.eligible_games + first.excluded_games
    assert "provisional" in first.alias

    manifest_text = first.release_manifest_path.read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    alias = json.loads(first.alias_path.read_text(encoding="utf-8"))
    assert str(tmp_path) not in manifest_text
    assert manifest["scope"]["partition_ids"] == ["2022-Q1", "2022-Q2"]
    assert manifest["scope"]["start_utc"] == "2022-01-01T00:00:00+00:00"
    assert manifest["scope"]["end_utc"] == "2022-07-01T00:00:00+00:00"
    assert manifest["reconciliation"] == {
        "duplicate_stable_identifiers": 0,
        "eligible_games": 2,
        "excluded_games": 0,
        "normalized_equals_eligible_plus_excluded": True,
        "normalized_games": 2,
        "quarantined_records": 0,
    }
    assert manifest["supervised"]["schema_version"] == (
        "dota-draft-supervised-v1"
    )
    assert alias["release_fingerprint"] == first.release_fingerprint
    assert not Path(alias["release_manifest"]["relative_path"]).is_absolute()
    assert set(manifest["coverage"]["artifacts"]) >= {
        "coverage_summary.json",
        "coverage_summary.md",
        "coverage_by_year.parquet",
    }


def test_full_window_mode_rejects_an_incomplete_prefix(tmp_path: Path) -> None:
    partitions = prepared_prefix(tmp_path)
    verified = tuple(
        verify_partition(item, run_root=tmp_path / "runs")
        for item in partitions
    )

    with pytest.raises(PublicationError, match="all 19"):
        verify_partition_sequence(
            verified,
            mode=PublicationMode.FULL_WINDOW,
            repository_root=tmp_path,
        )


def test_full_window_mode_accepts_the_exact_19_partition_contract(
    tmp_path: Path,
) -> None:
    first = prepared_prefix(tmp_path)[0]
    template = verify_partition(first, run_root=tmp_path / "runs")
    plan = create_campaign_plan(CampaignConfig(repository_root=tmp_path))
    synthetic = tuple(
        replace(
            template,
            partition_id=partition.partition_id,
            run_id=f"synthetic-{partition.ordinal}",
            start_utc=partition.config.start_utc,
            end_utc=partition.config.end_utc,
            scope=partition.config.scope_payload(),
            match_ids=(f"synthetic-match-{partition.ordinal}",),
        )
        for partition in plan.partitions
    )

    verify_partition_sequence(
        synthetic,
        mode=PublicationMode.FULL_WINDOW,
        repository_root=tmp_path,
    )


def test_pilot_cannot_be_appended_after_a_historical_gap(
    tmp_path: Path,
) -> None:
    partitions = prepared_prefix(tmp_path)
    verified = tuple(
        verify_partition(item, run_root=tmp_path / "runs")
        for item in partitions
    )
    invalid = (
        verified[0],
        replace(verified[1], partition_id="2026-07-pilot"),
    )

    with pytest.raises(PublicationError, match="pilot cannot be included"):
        verify_partition_sequence(
            invalid,
            mode=PublicationMode.PROVISIONAL_PREFIX,
            repository_root=tmp_path,
        )


def test_publication_rejects_duplicate_match_ids_across_partitions(
    tmp_path: Path,
) -> None:
    partitions = prepared_prefix(tmp_path, duplicate_match_id=True)

    with pytest.raises(PublicationError, match="Duplicate match2id"):
        publish_historical_dataset(publication_config(tmp_path, partitions))


def test_partition_verification_rejects_nonempty_quarantine(
    tmp_path: Path,
) -> None:
    partition = prepared_prefix(tmp_path)[0]
    run_directory = tmp_path / "runs" / partition.run_id
    run_manifest = json.loads(
        (run_directory / "manifest.json").read_text(encoding="utf-8")
    )
    assembly = (
        run_directory
        / "assembly"
        / f"build_{run_manifest['assembly']['fingerprint'][:16]}"
    )
    (assembly / "quarantine.jsonl").write_text(
        '{"reason":"test-conflict"}\n',
        encoding="utf-8",
    )

    with pytest.raises(PublicationError, match="quarantine is not empty"):
        verify_partition(partition, run_root=tmp_path / "runs")


def test_partition_verification_rejects_snapshot_tampering(
    tmp_path: Path,
) -> None:
    partition = prepared_prefix(tmp_path)[0]
    run_directory = tmp_path / "runs" / partition.run_id
    run_manifest = json.loads(
        (run_directory / "manifest.json").read_text(encoding="utf-8")
    )
    snapshot = (
        run_directory
        / "assembly"
        / f"build_{run_manifest['assembly']['fingerprint'][:16]}"
        / "snapshot.json"
    )
    snapshot.write_text('{"result":[],"error":[]}\n', encoding="utf-8")

    with pytest.raises(PublicationError, match="checksum mismatch"):
        verify_partition(partition, run_root=tmp_path / "runs")


def test_partition_verification_requires_complete_checkpoint(
    tmp_path: Path,
) -> None:
    partition = prepared_prefix(tmp_path)[0]
    checkpoint_path = (
        tmp_path / "runs" / partition.run_id / "checkpoint.json"
    )
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    checkpoint["run"]["status"] = "budget_exhausted"
    checkpoint_path.write_text(
        json.dumps(checkpoint, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(PublicationError, match="not complete"):
        verify_partition(partition, run_root=tmp_path / "runs")


def test_alias_is_immutable(tmp_path: Path) -> None:
    partitions = prepared_prefix(tmp_path)
    config = publication_config(tmp_path, partitions)
    first = publish_historical_dataset(config)
    alias = json.loads(first.alias_path.read_text(encoding="utf-8"))
    alias["release_fingerprint"] = "0" * 64
    first.alias_path.write_text(
        json.dumps(alias, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(PublicationError, match="already points elsewhere"):
        publish_historical_dataset(config)


def test_explicit_provisional_alias_must_be_clearly_labeled(
    tmp_path: Path,
) -> None:
    with pytest.raises(PublicationError, match="must include 'provisional'"):
        PublicationConfig(
            repository_root=tmp_path,
            partition_runs=(PartitionRun("2022-Q1", "m3_test"),),
            mode=PublicationMode.PROVISIONAL_PREFIX,
            alias="m3.5-tier1-tier2-2022-2026-v1",
        )


def test_cli_mapping_is_exact_and_publisher_has_no_http_dependency() -> None:
    parsed = parse_partition_mapping("2022-Q1=m3_valid_run")
    assert parsed == PartitionRun("2022-Q1", "m3_valid_run")
    with pytest.raises(PublicationError, match="PARTITION_ID=RUN_ID"):
        parse_partition_mapping("2022-Q1")

    root = Path(__file__).resolve().parents[1]
    paths = (
        root / "src" / "liquipedia_backfill" / "publication.py",
        root / "scripts" / "publish_historical_dataset.py",
    )
    forbidden = (
        "src.liquipedia_backfill.client",
        "src.liquipedia_backfill.runner",
        "requests",
        "urllib",
        "httpx",
    )
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        assert not any(
            name == prefix or name.startswith(prefix + ".")
            for name in imports
            for prefix in forbidden
        ), (path, imports)
