"""Offline publication of a verified historical Liquipedia dataset corpus.

This module is intentionally an orchestration layer. It verifies completed
partition evidence and delegates all data work to the existing normalization,
coverage-report, and supervised-dataset implementations.
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import duckdb

from src.draft_training_dataset.builder import (
    TrainingBuildResult,
    TrainingDatasetConfig,
    build_training_dataset,
)
from src.draft_training_dataset.schema import (
    SCHEMA_VERSION as SUPERVISED_SCHEMA_VERSION,
)
from src.liquipedia_pipeline.dataset import (
    SCHEMA_VERSION as NORMALIZED_SCHEMA_VERSION,
)
from src.liquipedia_pipeline.pipeline import PipelineResult, run_pipeline

from .campaign import CampaignConfig, create_campaign_plan
from .config import canonical_json, parse_utc_datetime
from .reports import generate_coverage_reports


PUBLICATION_VERSION = "1.0.0"
RELEASE_SCHEMA_VERSION = "dota-draft-historical-release-v1"
ALIAS_SCHEMA_VERSION = "dota-draft-historical-alias-v1"
SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class PublicationError(ValueError):
    """Raised when partition evidence cannot support a safe publication."""


class PublicationMode(StrEnum):
    """Supported historical-release scopes."""

    FULL_WINDOW = "full-window"
    PROVISIONAL_PREFIX = "provisional-prefix"


@dataclass(frozen=True, slots=True)
class PartitionRun:
    """One ordered logical-partition to completed-run mapping."""

    partition_id: str
    run_id: str

    def __post_init__(self) -> None:
        for label, value in (
            ("partition ID", self.partition_id),
            ("run ID", self.run_id),
        ):
            if not SAFE_IDENTIFIER.fullmatch(value):
                raise PublicationError(f"Unsafe {label}: {value!r}.")


@dataclass(frozen=True, slots=True)
class PublicationConfig:
    """Filesystem locations and release policy for one offline publication."""

    repository_root: Path
    partition_runs: tuple[PartitionRun, ...]
    mode: PublicationMode
    alias: str | None = None
    run_root: Path = Path("data/backfill/runs")
    normalized_output_root: Path = Path("data/processed/liquipedia")
    training_output_root: Path = Path(
        "data/training/dota_draft_supervised"
    )
    release_root: Path = Path("data/releases/dota_draft_historical")

    def __post_init__(self) -> None:
        if not self.partition_runs:
            raise PublicationError(
                "At least one ordered partition mapping is required."
            )
        mode = (
            self.mode
            if isinstance(self.mode, PublicationMode)
            else PublicationMode(self.mode)
        )
        object.__setattr__(self, "mode", mode)
        if self.alias is not None and not SAFE_IDENTIFIER.fullmatch(self.alias):
            raise PublicationError(f"Unsafe release alias: {self.alias!r}.")
        if (
            mode == PublicationMode.PROVISIONAL_PREFIX
            and self.alias is not None
            and "provisional" not in self.alias.lower()
        ):
            raise PublicationError(
                "A provisional publication alias must include 'provisional'."
            )

        partition_ids = [
            selection.partition_id for selection in self.partition_runs
        ]
        run_ids = [selection.run_id for selection in self.partition_runs]
        if len(partition_ids) != len(set(partition_ids)):
            raise PublicationError("Partition mappings contain duplicate IDs.")
        if len(run_ids) != len(set(run_ids)):
            raise PublicationError("Partition mappings contain duplicate runs.")

    def resolve(self, path: Path) -> Path:
        """Resolve one configurable artifact root under the repository."""
        if path.is_absolute():
            return path.resolve()
        return (self.repository_root.resolve() / path).resolve()


@dataclass(frozen=True, slots=True)
class VerifiedPartition:
    """Verified immutable evidence for one completed acquisition partition."""

    partition_id: str
    run_id: str
    run_directory: Path
    start_utc: datetime
    end_utc: datetime
    scope: dict[str, object]
    config_hash: str
    acquisition_fingerprint: str
    request_count: int
    cache_hit_count: int
    raw_response_sha256: tuple[str, ...]
    run_manifest_sha256: str
    checkpoint_sha256: str
    assembly_fingerprint: str
    assembly_manifest_sha256: str
    snapshot_path: Path
    snapshot_sha256: str
    record_index_sha256: str
    game_index_sha256: str
    accepted_matches: int
    accepted_games: int
    duplicate_matches: int
    duplicate_games: int
    match_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PublicationResult:
    """Identity and local artifacts of one verified aggregate release."""

    release_fingerprint: str
    release_status: str
    release_directory: Path
    release_manifest_path: Path
    alias: str
    alias_path: Path
    normalized_build: Path
    normalized_fingerprint: str
    supervised_build: Path
    supervised_fingerprint: str
    normalized_games: int
    eligible_games: int
    excluded_games: int


def sha256_file(path: Path) -> str:
    """Calculate a streaming SHA-256 checksum."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def publication_source_sha256() -> str:
    """Hash the publisher implementation for release provenance."""
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def parse_partition_mapping(value: str) -> PartitionRun:
    """Parse one exact ``PARTITION_ID=RUN_ID`` CLI value."""
    partition_id, separator, run_id = value.partition("=")
    if not separator or not partition_id or not run_id or "=" in run_id:
        raise PublicationError(
            "Partition mappings must use PARTITION_ID=RUN_ID."
        )
    return PartitionRun(partition_id=partition_id, run_id=run_id)


def _json_object(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise PublicationError(f"{label} not found: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PublicationError(f"{label} is not valid JSON: {path}") from error
    if not isinstance(value, dict):
        raise PublicationError(f"{label} must contain a JSON object: {path}")
    return value


def _mapping(value: object, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PublicationError(f"{label} must be an object.")
    return value


def _integer(value: object, *, label: str) -> int:
    if isinstance(value, bool):
        raise PublicationError(f"{label} must be an integer.")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise PublicationError(f"{label} must be an integer.") from error
    return parsed


def _safe_artifact(directory: Path, filename: object, *, label: str) -> Path:
    if not isinstance(filename, str) or Path(filename).name != filename:
        raise PublicationError(f"{label} must be a local artifact filename.")
    path = directory / filename
    if not path.is_file():
        raise PublicationError(f"{label} not found: {path}")
    return path


def _parse_scope_timestamp(scope: Mapping[str, Any], key: str) -> datetime:
    value = scope.get(key)
    if not isinstance(value, str):
        raise PublicationError(f"Partition scope {key} must be a timestamp.")
    try:
        return parse_utc_datetime(value)
    except ValueError as error:
        raise PublicationError(f"Invalid partition scope {key}: {value!r}.") from error


def _verify_checkpoint(
    checkpoint: Mapping[str, Any],
    *,
    selection: PartitionRun,
    scope: Mapping[str, Any],
    config_hash: str,
    request_count: int,
    cache_hit_count: int,
) -> tuple[tuple[str, ...], int]:
    run = _mapping(checkpoint.get("run"), label="checkpoint.run")
    if run.get("run_id") != selection.run_id:
        raise PublicationError(
            f"{selection.partition_id}: checkpoint run ID mismatch."
        )
    if run.get("status") != "complete":
        raise PublicationError(
            f"{selection.partition_id}: checkpoint is not complete."
        )
    if run.get("config_hash") != config_hash:
        raise PublicationError(
            f"{selection.partition_id}: checkpoint config hash mismatch."
        )
    if _integer(run.get("request_count"), label="checkpoint request_count") != (
        request_count
    ):
        raise PublicationError(
            f"{selection.partition_id}: checkpoint request count mismatch."
        )
    if _integer(
        run.get("cache_hit_count"),
        label="checkpoint cache_hit_count",
    ) != cache_hit_count:
        raise PublicationError(
            f"{selection.partition_id}: checkpoint cache-hit count mismatch."
        )
    checkpoint_scope = _mapping(
        checkpoint.get("scope"),
        label="checkpoint.scope",
    )
    if dict(checkpoint_scope) != dict(scope):
        raise PublicationError(
            f"{selection.partition_id}: checkpoint scope mismatch."
        )
    try:
        config_json = json.loads(str(run["config_json"]))
    except (KeyError, json.JSONDecodeError) as error:
        raise PublicationError(
            f"{selection.partition_id}: invalid checkpoint config_json."
        ) from error
    if config_json != dict(scope):
        raise PublicationError(
            f"{selection.partition_id}: checkpoint config_json mismatch."
        )

    pages = checkpoint.get("pages")
    requests = checkpoint.get("requests")
    if not isinstance(pages, list) or not pages:
        raise PublicationError(
            f"{selection.partition_id}: completed checkpoint has no pages."
        )
    if not isinstance(requests, list) or len(requests) != request_count:
        raise PublicationError(
            f"{selection.partition_id}: checkpoint request ledger mismatch."
        )
    ordered = sorted(
        pages,
        key=lambda item: _integer(
            _mapping(item, label="checkpoint page").get("sequence"),
            label="checkpoint page sequence",
        ),
    )
    sequences = [
        _integer(
            _mapping(page, label="checkpoint page").get("sequence"),
            label="checkpoint page sequence",
        )
        for page in ordered
    ]
    if sequences != list(range(1, len(ordered) + 1)):
        raise PublicationError(
            f"{selection.partition_id}: checkpoint pages are not contiguous."
        )
    terminal_flags = [
        bool(_mapping(page, label="checkpoint page").get("is_final_page"))
        for page in ordered
    ]
    if terminal_flags != [False] * (len(ordered) - 1) + [True]:
        raise PublicationError(
            f"{selection.partition_id}: checkpoint terminal-page state is invalid."
        )
    records_seen = sum(
        _integer(
            _mapping(page, label="checkpoint page").get("record_count"),
            label="checkpoint page record_count",
        )
        for page in ordered
    )
    if records_seen != _integer(
        run.get("records_seen"),
        label="checkpoint records_seen",
    ):
        raise PublicationError(
            f"{selection.partition_id}: checkpoint record count mismatch."
        )
    raw_hashes = tuple(
        sorted(
            str(
                _mapping(page, label="checkpoint page").get(
                    "response_sha256"
                )
            )
            for page in ordered
        )
    )
    if any(not SHA256_PATTERN.fullmatch(value) for value in raw_hashes):
        raise PublicationError(
            f"{selection.partition_id}: invalid raw-response hash."
        )
    return raw_hashes, records_seen


def verify_partition(
    selection: PartitionRun,
    *,
    run_root: Path,
) -> VerifiedPartition:
    """Verify one completed run from checkpoint through assembly snapshot."""
    run_directory = run_root / selection.run_id
    run_manifest_path = run_directory / "manifest.json"
    checkpoint_path = run_directory / "checkpoint.json"
    run_manifest = _json_object(
        run_manifest_path,
        label=f"{selection.partition_id} run manifest",
    )
    checkpoint = _json_object(
        checkpoint_path,
        label=f"{selection.partition_id} checkpoint",
    )
    if run_manifest.get("run_id") != selection.run_id:
        raise PublicationError(
            f"{selection.partition_id}: run manifest ID mismatch."
        )
    scope = dict(
        _mapping(run_manifest.get("scope"), label="run manifest scope")
    )
    config_hash = str(run_manifest.get("config_hash", ""))
    if not SHA256_PATTERN.fullmatch(config_hash):
        raise PublicationError(
            f"{selection.partition_id}: invalid config hash."
        )
    request_count = _integer(
        run_manifest.get("request_count"),
        label="run manifest request_count",
    )
    cache_hit_count = _integer(
        run_manifest.get("cache_hit_count"),
        label="run manifest cache_hit_count",
    )
    raw_hashes, records_seen = _verify_checkpoint(
        checkpoint,
        selection=selection,
        scope=scope,
        config_hash=config_hash,
        request_count=request_count,
        cache_hit_count=cache_hit_count,
    )
    declared_raw_hashes = tuple(
        sorted(str(value) for value in run_manifest.get("raw_response_sha256", []))
    )
    if declared_raw_hashes != raw_hashes:
        raise PublicationError(
            f"{selection.partition_id}: run-manifest raw hashes mismatch."
        )

    assembly_reference = _mapping(
        run_manifest.get("assembly"),
        label="run manifest assembly",
    )
    assembly_fingerprint = str(assembly_reference.get("fingerprint", ""))
    if not SHA256_PATTERN.fullmatch(assembly_fingerprint):
        raise PublicationError(
            f"{selection.partition_id}: invalid assembly fingerprint."
        )
    assembly_directory = (
        run_directory
        / "assembly"
        / f"build_{assembly_fingerprint[:16]}"
    )
    assembly_manifest_path = assembly_directory / "manifest.json"
    assembly_manifest = _json_object(
        assembly_manifest_path,
        label=f"{selection.partition_id} assembly manifest",
    )
    if assembly_manifest.get("build_fingerprint") != assembly_fingerprint:
        raise PublicationError(
            f"{selection.partition_id}: assembly fingerprint mismatch."
        )
    if assembly_manifest.get("config_hash") != config_hash:
        raise PublicationError(
            f"{selection.partition_id}: assembly config hash mismatch."
        )
    if _integer(
        assembly_manifest.get("request_count"),
        label="assembly request_count",
    ) != request_count:
        raise PublicationError(
            f"{selection.partition_id}: assembly request count mismatch."
        )
    if _integer(
        assembly_manifest.get("cache_hit_count"),
        label="assembly cache_hit_count",
    ) != cache_hit_count:
        raise PublicationError(
            f"{selection.partition_id}: assembly cache-hit count mismatch."
        )
    if tuple(
        sorted(
            str(value)
            for value in assembly_manifest.get("raw_response_sha256", [])
        )
    ) != raw_hashes:
        raise PublicationError(
            f"{selection.partition_id}: assembly raw hashes mismatch."
        )

    snapshot_path = _safe_artifact(
        assembly_directory,
        assembly_manifest.get("snapshot_file"),
        label="assembly snapshot",
    )
    snapshot_sha256 = sha256_file(snapshot_path)
    if snapshot_sha256 != assembly_manifest.get("snapshot_sha256"):
        raise PublicationError(
            f"{selection.partition_id}: assembly snapshot checksum mismatch."
        )
    if snapshot_sha256 != assembly_reference.get("snapshot_sha256"):
        raise PublicationError(
            f"{selection.partition_id}: run-manifest snapshot checksum mismatch."
        )
    record_index_path = _safe_artifact(
        assembly_directory,
        assembly_manifest.get("record_index_file"),
        label="assembly record index",
    )
    game_index_path = _safe_artifact(
        assembly_directory,
        assembly_manifest.get("game_index_file"),
        label="assembly game index",
    )
    quarantine_path = _safe_artifact(
        assembly_directory,
        assembly_manifest.get("quarantine_file"),
        label="assembly quarantine file",
    )
    counts = _mapping(
        assembly_manifest.get("counts"),
        label="assembly counts",
    )
    quarantined = _integer(
        counts.get("quarantined_records"),
        label="assembly quarantined_records",
    )
    if quarantined != 0 or quarantine_path.read_text(encoding="utf-8").strip():
        raise PublicationError(
            f"{selection.partition_id}: assembly quarantine is not empty."
        )
    if _integer(
        counts.get("record_occurrences"),
        label="assembly record_occurrences",
    ) != records_seen:
        raise PublicationError(
            f"{selection.partition_id}: assembly occurrence count mismatch."
        )

    snapshot = _json_object(
        snapshot_path,
        label=f"{selection.partition_id} assembly snapshot",
    )
    if snapshot.get("error") != []:
        raise PublicationError(
            f"{selection.partition_id}: assembly snapshot contains errors."
        )
    records = snapshot.get("result")
    if not isinstance(records, list) or any(
        not isinstance(record, dict) for record in records
    ):
        raise PublicationError(
            f"{selection.partition_id}: snapshot result must be object rows."
        )
    match_ids: list[str] = []
    accepted_games = 0
    for record in records:
        match_id = str(record.get("match2id", "")).strip()
        if not match_id:
            raise PublicationError(
                f"{selection.partition_id}: snapshot record lacks match2id."
            )
        match_ids.append(match_id)
        games = record.get("match2games", [])
        if games in (None, ""):
            games = []
        if not isinstance(games, list):
            raise PublicationError(
                f"{selection.partition_id}: snapshot match2games is not a list."
            )
        accepted_games += len(games)
    if len(match_ids) != len(set(match_ids)):
        raise PublicationError(
            f"{selection.partition_id}: duplicate match2id in snapshot."
        )
    accepted_matches = _integer(
        counts.get("accepted_matches"),
        label="assembly accepted_matches",
    )
    declared_games = _integer(
        counts.get("accepted_games"),
        label="assembly accepted_games",
    )
    if accepted_matches != len(records) or declared_games != accepted_games:
        raise PublicationError(
            f"{selection.partition_id}: assembly accepted counts mismatch."
        )

    start_utc = _parse_scope_timestamp(scope, "start_utc")
    end_utc = _parse_scope_timestamp(scope, "end_utc")
    if start_utc >= end_utc:
        raise PublicationError(
            f"{selection.partition_id}: partition scope is not half-open."
        )
    acquisition_fingerprint = str(
        run_manifest.get("acquisition_fingerprint", "")
    )
    if not SHA256_PATTERN.fullmatch(acquisition_fingerprint):
        raise PublicationError(
            f"{selection.partition_id}: invalid acquisition fingerprint."
        )
    return VerifiedPartition(
        partition_id=selection.partition_id,
        run_id=selection.run_id,
        run_directory=run_directory,
        start_utc=start_utc,
        end_utc=end_utc,
        scope=scope,
        config_hash=config_hash,
        acquisition_fingerprint=acquisition_fingerprint,
        request_count=request_count,
        cache_hit_count=cache_hit_count,
        raw_response_sha256=raw_hashes,
        run_manifest_sha256=sha256_file(run_manifest_path),
        checkpoint_sha256=sha256_file(checkpoint_path),
        assembly_fingerprint=assembly_fingerprint,
        assembly_manifest_sha256=sha256_file(assembly_manifest_path),
        snapshot_path=snapshot_path,
        snapshot_sha256=snapshot_sha256,
        record_index_sha256=sha256_file(record_index_path),
        game_index_sha256=sha256_file(game_index_path),
        accepted_matches=accepted_matches,
        accepted_games=declared_games,
        duplicate_matches=_integer(
            counts.get("duplicate_matches"),
            label="assembly duplicate_matches",
        ),
        duplicate_games=_integer(
            counts.get("duplicate_games"),
            label="assembly duplicate_games",
        ),
        match_ids=tuple(sorted(match_ids)),
    )


def verify_partition_sequence(
    partitions: Sequence[VerifiedPartition],
    *,
    mode: PublicationMode,
    repository_root: Path,
) -> None:
    """Require an exact contiguous prefix of the approved fixed campaign."""
    campaign = create_campaign_plan(
        CampaignConfig(repository_root=repository_root.resolve())
    )
    expected = campaign.partitions
    actual_ids = [partition.partition_id for partition in partitions]
    expected_prefix = [
        partition.partition_id
        for partition in expected[: len(partitions)]
    ]
    if actual_ids != expected_prefix:
        if "2026-07-pilot" in actual_ids:
            raise PublicationError(
                "The cached pilot cannot be included after a historical gap."
            )
        raise PublicationError(
            "Publication mappings must be an ordered contiguous campaign prefix."
        )
    if mode == PublicationMode.FULL_WINDOW and len(partitions) != len(expected):
        raise PublicationError(
            "Full-window publication requires all 19 logical partitions."
        )
    if (
        mode == PublicationMode.PROVISIONAL_PREFIX
        and len(partitions) >= len(expected)
    ):
        raise PublicationError(
            "A complete campaign must use full-window publication mode."
        )

    compatibility_keys = (
        "acquisition_version",
        "tiers",
        "patches",
        "patch_filter_stage",
        "page_size",
        "hourly_request_limit",
        "request_interval_seconds",
        "projection",
    )
    for actual, planned in zip(
        partitions,
        expected[: len(partitions)],
        strict=True,
    ):
        planned_scope = planned.config.scope_payload()
        if (
            actual.start_utc != planned.config.start_utc
            or actual.end_utc != planned.config.end_utc
        ):
            raise PublicationError(
                f"{actual.partition_id}: scope does not match its logical partition."
            )
        for key in compatibility_keys:
            if actual.scope.get(key) != planned_scope.get(key):
                raise PublicationError(
                    f"{actual.partition_id}: acquisition policy mismatch for {key}."
                )
        max_requests = _integer(
            actual.scope.get("max_requests"),
            label=f"{actual.partition_id} max_requests",
        )
        if max_requests < actual.request_count:
            raise PublicationError(
                f"{actual.partition_id}: request count exceeds partition budget."
            )
    for left, right in zip(partitions, partitions[1:], strict=False):
        if left.end_utc != right.start_utc:
            raise PublicationError(
                f"Partition gap or overlap: {left.partition_id} → "
                f"{right.partition_id}."
            )

    seen: set[str] = set()
    for partition in partitions:
        overlap = seen.intersection(partition.match_ids)
        if overlap:
            preview = ", ".join(sorted(overlap)[:5])
            raise PublicationError(
                "Duplicate match2id across partition snapshots: " + preview
            )
        seen.update(partition.match_ids)


def _read_parquet(path: Path):
    with duckdb.connect() as connection:
        return connection.execute(
            "SELECT * FROM read_parquet(?)",
            [str(path.resolve())],
        ).fetchdf()


def _verify_unique(
    frame,
    columns: tuple[str, ...],
    *,
    table_name: str,
) -> None:
    if any(column not in frame.columns for column in columns):
        raise PublicationError(
            f"Normalized table {table_name} lacks its stable identifier."
        )
    if frame[list(columns)].isna().any().any():
        raise PublicationError(
            f"Normalized table {table_name} has a null stable identifier."
        )
    if frame.duplicated(list(columns)).any():
        raise PublicationError(
            f"Normalized table {table_name} has duplicate stable identifiers."
        )


def _verify_normalized_build(
    result: PipelineResult,
    *,
    expected_matches: int,
    expected_games: int,
) -> tuple[dict[str, Any], dict[str, Any], int]:
    root = result.export.output_directory
    manifest = _json_object(
        result.export.manifest_path,
        label="aggregate normalized manifest",
    )
    if manifest.get("build_fingerprint") != result.export.build_fingerprint:
        raise PublicationError("Aggregate normalized fingerprint mismatch.")
    if manifest.get("schema_version") != NORMALIZED_SCHEMA_VERSION:
        raise PublicationError("Unexpected normalized dataset schema.")
    entries = {
        str(entry.get("name")): _mapping(
            entry,
            label="normalized table manifest",
        )
        for entry in manifest.get("tables", [])
        if isinstance(entry, Mapping)
    }
    expected_names = {
        "matches",
        "match_teams",
        "match_players",
        "games",
        "heroes",
        "draft_picks",
        "draft_bans",
        "ml_draft_games",
    }
    if set(entries) != expected_names:
        raise PublicationError("Aggregate normalized table set is incomplete.")

    frames: dict[str, Any] = {}
    table_evidence: dict[str, Any] = {}
    for name in sorted(entries):
        entry = entries[name]
        path = _safe_artifact(
            root,
            entry.get("parquet_file"),
            label=f"normalized {name} table",
        )
        actual_hash = sha256_file(path)
        if actual_hash != entry.get("parquet_sha256"):
            raise PublicationError(
                f"Normalized table checksum mismatch: {name}."
            )
        frame = _read_parquet(path)
        rows = _integer(entry.get("rows"), label=f"{name} row count")
        if len(frame) != rows:
            raise PublicationError(
                f"Normalized table row-count mismatch: {name}."
            )
        frames[name] = frame
        table_evidence[name] = {
            "file": path.name,
            "rows": rows,
            "sha256": actual_hash,
        }

    unique_keys = {
        "matches": ("source_match_id",),
        "match_teams": ("source_match_id", "team_slot"),
        "match_players": ("source_match_id", "team_slot", "player_slot"),
        "games": ("game_key",),
        "heroes": ("hero_key",),
        "draft_picks": ("game_key", "team_slot", "slot"),
        "draft_bans": ("game_key", "team_slot", "slot"),
        "ml_draft_games": ("game_key",),
    }
    for name, columns in unique_keys.items():
        _verify_unique(frames[name], columns, table_name=name)
    if len(frames["matches"]) != expected_matches:
        raise PublicationError(
            "Aggregate normalized match count does not reconcile with assemblies."
        )
    if len(frames["games"]) != expected_games:
        raise PublicationError(
            "Aggregate normalized game count does not reconcile with assemblies."
        )
    for name in ("matches", "games"):
        if "schema_version" not in frames[name].columns:
            raise PublicationError(
                f"Normalized table {name} lacks schema_version."
            )
        values = set(frames[name]["schema_version"].dropna().astype(str))
        if values != {NORMALIZED_SCHEMA_VERSION}:
            raise PublicationError(
                f"Normalized row schema mismatch in {name}."
            )
    return manifest, {
        "tables": table_evidence,
        "manifest_sha256": sha256_file(result.export.manifest_path),
    }, len(frames["games"])


def _verify_supervised_build(
    result: TrainingBuildResult,
    *,
    normalized_result: PipelineResult,
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = _json_object(
        result.manifest_path,
        label="aggregate supervised manifest",
    )
    if manifest.get("build_fingerprint") != result.build_fingerprint:
        raise PublicationError("Aggregate supervised fingerprint mismatch.")
    if manifest.get("schema_version") != SUPERVISED_SCHEMA_VERSION:
        raise PublicationError("Unexpected supervised dataset schema.")
    normalized_source = _mapping(
        manifest.get("normalized_source"),
        label="supervised normalized_source",
    )
    if normalized_source.get("build_fingerprint") != (
        normalized_result.export.build_fingerprint
    ):
        raise PublicationError("Supervised normalized lineage mismatch.")
    schema = _json_object(result.schema_path, label="supervised schema")
    if schema.get("schema_version") != SUPERVISED_SCHEMA_VERSION:
        raise PublicationError("Supervised schema artifact mismatch.")

    artifacts = _mapping(
        manifest.get("artifacts"),
        label="supervised artifacts",
    )
    artifact_evidence: dict[str, Any] = {}
    for name, raw_entry in sorted(artifacts.items()):
        entry = _mapping(raw_entry, label=f"supervised artifact {name}")
        path = _safe_artifact(
            result.output_directory,
            entry.get("file"),
            label=f"supervised artifact {name}",
        )
        actual_hash = sha256_file(path)
        if actual_hash != entry.get("sha256"):
            raise PublicationError(
                f"Supervised artifact checksum mismatch: {name}."
            )
        artifact_evidence[str(name)] = {
            "file": path.name,
            "sha256": actual_hash,
            "bytes": path.stat().st_size,
        }

    normalized_games = _read_parquet(
        normalized_result.export.output_directory / "games.parquet"
    )
    training = _read_parquet(result.training_path)
    exclusions = _read_parquet(result.exclusions_path)
    if "is_trainable_draft" not in normalized_games.columns:
        raise PublicationError(
            "Normalized games table lacks is_trainable_draft."
        )
    _verify_unique(training, ("sample_id",), table_name="draft_training_games")
    _verify_unique(training, ("game_key",), table_name="draft_training_games")
    _verify_unique(exclusions, ("game_key",), table_name="excluded_games")
    if not training.empty and not (
        training["sample_id"].astype(str) == training["game_key"].astype(str)
    ).all():
        raise PublicationError("Supervised sample_id must equal game_key.")

    normalized_keys = set(normalized_games["game_key"].astype(str))
    eligible_keys = set(training["game_key"].astype(str))
    excluded_keys = set(exclusions["game_key"].astype(str))
    if eligible_keys.intersection(excluded_keys):
        raise PublicationError("Eligible and excluded game IDs overlap.")
    if normalized_keys != eligible_keys.union(excluded_keys):
        raise PublicationError(
            "Normalized games do not reconcile with supervised outcomes."
        )
    expected_eligible = set(
        normalized_games.loc[
            normalized_games["is_trainable_draft"].fillna(False).astype(bool),
            "game_key",
        ].astype(str)
    )
    expected_excluded = normalized_keys - expected_eligible
    if eligible_keys != expected_eligible or excluded_keys != expected_excluded:
        raise PublicationError(
            "Supervised eligibility disagrees with normalized eligibility."
        )
    if len(normalized_games) != len(training) + len(exclusions):
        raise PublicationError(
            "normalized games != eligible games + excluded games."
        )
    row_counts = _mapping(
        manifest.get("row_counts"),
        label="supervised row_counts",
    )
    if (
        _integer(row_counts.get("training"), label="training row count")
        != len(training)
        or _integer(row_counts.get("excluded"), label="excluded row count")
        != len(exclusions)
    ):
        raise PublicationError("Supervised manifest row counts mismatch.")
    return manifest, {
        "manifest_sha256": sha256_file(result.manifest_path),
        "artifacts": artifact_evidence,
        "normalized_games": len(normalized_games),
        "eligible_games": len(training),
        "excluded_games": len(exclusions),
    }


def _partition_evidence(partition: VerifiedPartition) -> dict[str, object]:
    return {
        "partition_id": partition.partition_id,
        "run_id": partition.run_id,
        "scope": {
            "start_utc": partition.start_utc.isoformat(),
            "end_utc": partition.end_utc.isoformat(),
        },
        "config_hash": partition.config_hash,
        "acquisition_fingerprint": partition.acquisition_fingerprint,
        "request_count": partition.request_count,
        "cache_hit_count": partition.cache_hit_count,
        "raw_response_sha256": list(partition.raw_response_sha256),
        "run_manifest_sha256": partition.run_manifest_sha256,
        "checkpoint_sha256": partition.checkpoint_sha256,
        "assembly": {
            "build_fingerprint": partition.assembly_fingerprint,
            "manifest_sha256": partition.assembly_manifest_sha256,
            "snapshot_sha256": partition.snapshot_sha256,
            "record_index_sha256": partition.record_index_sha256,
            "game_index_sha256": partition.game_index_sha256,
            "accepted_matches": partition.accepted_matches,
            "accepted_games": partition.accepted_games,
            "duplicate_matches": partition.duplicate_matches,
            "duplicate_games": partition.duplicate_games,
            "quarantined_records": 0,
        },
    }


def _default_alias(
    mode: PublicationMode,
    partitions: Sequence[VerifiedPartition],
) -> str:
    if mode == PublicationMode.FULL_WINDOW:
        return "m3.5-tier1-tier2-2022-2026-v1"
    return (
        "m3.5-tier1-tier2-2022-through-"
        f"{partitions[-1].partition_id}-provisional-v1"
    )


def _write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(
        payload,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    ) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix=f".{path.name}.",
        dir=path.parent,
        delete=False,
    ) as destination:
        destination.write(encoded)
        temporary = Path(destination.name)
    temporary.replace(path)


def _write_alias(
    *,
    release_root: Path,
    alias: str,
    release_status: str,
    release_fingerprint: str,
    release_directory: Path,
    release_manifest_path: Path,
    normalized_result: PipelineResult,
    supervised_result: TrainingBuildResult,
) -> Path:
    alias_path = release_root / "aliases" / f"{alias}.json"
    payload = {
        "alias_schema_version": ALIAS_SCHEMA_VERSION,
        "alias": alias,
        "release_status": release_status,
        "release_fingerprint": release_fingerprint,
        "release_manifest": {
            "relative_path": (
                f"{release_directory.name}/{release_manifest_path.name}"
            ),
            "sha256": sha256_file(release_manifest_path),
        },
        "normalized_build": {
            "directory_name": normalized_result.export.output_directory.name,
            "build_fingerprint": normalized_result.export.build_fingerprint,
        },
        "supervised_build": {
            "directory_name": supervised_result.output_directory.name,
            "build_fingerprint": supervised_result.build_fingerprint,
            "schema_version": SUPERVISED_SCHEMA_VERSION,
        },
    }
    if alias_path.is_file():
        existing = _json_object(alias_path, label="release alias")
        if existing != payload:
            raise PublicationError(
                f"Release alias already points elsewhere: {alias}."
            )
        return alias_path
    _write_json_atomic(alias_path, payload)
    return alias_path


def _verify_existing_release(
    target: Path,
    *,
    release_fingerprint: str,
    release_identity: Mapping[str, Any],
) -> dict[str, Any] | None:
    manifest_path = target / "manifest.json"
    if not manifest_path.is_file():
        return None
    manifest = _json_object(manifest_path, label="release manifest")
    if manifest.get("release_fingerprint") != release_fingerprint:
        raise PublicationError(f"Existing release manifest mismatch: {target}")
    for key, expected in release_identity.items():
        if manifest.get(key) != expected:
            raise PublicationError(
                f"Existing release identity mismatch for {key}: {target}"
            )
    coverage = _mapping(
        manifest.get("coverage"),
        label="release coverage",
    )
    artifacts = _mapping(
        coverage.get("artifacts"),
        label="release coverage artifacts",
    )
    coverage_directory = target / "coverage"
    for name, raw_entry in artifacts.items():
        entry = _mapping(raw_entry, label=f"coverage artifact {name}")
        path = _safe_artifact(
            coverage_directory,
            entry.get("file"),
            label=f"coverage artifact {name}",
        )
        if sha256_file(path) != entry.get("sha256"):
            raise PublicationError(
                f"Existing coverage artifact checksum mismatch: {name}."
            )
    return manifest


def publish_historical_dataset(
    config: PublicationConfig,
) -> PublicationResult:
    """Verify, build, reconcile, and atomically publish one aggregate corpus."""
    run_root = config.resolve(config.run_root)
    verified = tuple(
        verify_partition(selection, run_root=run_root)
        for selection in config.partition_runs
    )
    verify_partition_sequence(
        verified,
        mode=config.mode,
        repository_root=config.repository_root,
    )

    normalized_result = run_pipeline(
        [partition.snapshot_path for partition in verified],
        output_root=config.resolve(config.normalized_output_root),
    )
    normalized_manifest, normalized_evidence, normalized_games = (
        _verify_normalized_build(
            normalized_result,
            expected_matches=sum(
                partition.accepted_matches for partition in verified
            ),
            expected_games=sum(
                partition.accepted_games for partition in verified
            ),
        )
    )
    supervised_result = build_training_dataset(
        TrainingDatasetConfig(
            normalized_build=normalized_result.export.output_directory,
            output_root=config.resolve(config.training_output_root),
        )
    )
    supervised_manifest, supervised_evidence = _verify_supervised_build(
        supervised_result,
        normalized_result=normalized_result,
    )

    release_status = (
        "canonical_full_window"
        if config.mode == PublicationMode.FULL_WINDOW
        else "provisional_contiguous_prefix"
    )
    partition_payload = [
        _partition_evidence(partition) for partition in verified
    ]
    release_identity = {
        "publication_version": PUBLICATION_VERSION,
        "release_schema_version": RELEASE_SCHEMA_VERSION,
        "publisher_source_sha256": publication_source_sha256(),
        "release_status": release_status,
        "partitions": partition_payload,
        "normalized_build_fingerprint": (
            normalized_result.export.build_fingerprint
        ),
        "supervised_build_fingerprint": supervised_result.build_fingerprint,
    }
    release_fingerprint = hashlib.sha256(
        canonical_json(release_identity).encode("utf-8")
    ).hexdigest()
    release_root = config.resolve(config.release_root)
    target = release_root / f"build_{release_fingerprint[:16]}"
    existing = _verify_existing_release(
        target,
        release_fingerprint=release_fingerprint,
        release_identity=release_identity,
    )
    if existing is None:
        release_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".historical-release-",
            dir=release_root,
        ) as temporary:
            staging = Path(temporary)
            coverage_directory = staging / "coverage"
            coverage_summary = dict(
                generate_coverage_reports(
                    normalized_result.export.output_directory,
                    output_directory=coverage_directory,
                )
            )
            # The existing report intentionally records a local absolute path.
            # Publication evidence replaces only that location with the
            # content-addressed directory name so the release is credential-free.
            coverage_summary["normalized_build"] = (
                normalized_result.export.output_directory.name
            )
            _write_json_atomic(
                coverage_directory / "coverage_summary.json",
                coverage_summary,
            )
            coverage_artifacts = {
                path.name: {
                    "file": path.name,
                    "sha256": sha256_file(path),
                    "bytes": path.stat().st_size,
                }
                for path in sorted(coverage_directory.iterdir())
                if path.is_file()
            }
            release_manifest = {
                **release_identity,
                "release_fingerprint": release_fingerprint,
                "scope": {
                    "interval": "half-open",
                    "start_utc": verified[0].start_utc.isoformat(),
                    "end_utc": verified[-1].end_utc.isoformat(),
                    "partition_count": len(verified),
                    "partition_ids": [
                        partition.partition_id for partition in verified
                    ],
                    "tiers": ["1", "2"],
                },
                "limitations": (
                    []
                    if config.mode == PublicationMode.FULL_WINDOW
                    else [
                        "This is a provisional contiguous historical prefix.",
                        "Later historical partitions and the cached July 2026 "
                        "pilot are intentionally excluded.",
                    ]
                ),
                "request_accounting": {
                    "http_attempts": sum(
                        partition.request_count for partition in verified
                    ),
                    "cache_hits": sum(
                        partition.cache_hit_count for partition in verified
                    ),
                },
                "normalized": {
                    "directory_name": (
                        normalized_result.export.output_directory.name
                    ),
                    "build_fingerprint": (
                        normalized_result.export.build_fingerprint
                    ),
                    "schema_version": normalized_manifest["schema_version"],
                    **normalized_evidence,
                },
                "supervised": {
                    "directory_name": supervised_result.output_directory.name,
                    "build_fingerprint": supervised_result.build_fingerprint,
                    "schema_version": supervised_manifest["schema_version"],
                    **supervised_evidence,
                },
                "reconciliation": {
                    "normalized_games": normalized_games,
                    "eligible_games": supervised_result.training_rows,
                    "excluded_games": supervised_result.excluded_rows,
                    "normalized_equals_eligible_plus_excluded": True,
                    "duplicate_stable_identifiers": 0,
                    "quarantined_records": 0,
                },
                "coverage": {
                    "summary": coverage_summary,
                    "artifacts": coverage_artifacts,
                },
                "source_attribution": {
                    "source": "Liquipedia",
                    "license": "CC-BY-SA 3.0",
                    "terms": "https://liquipedia.net/api-terms-of-use",
                },
            }
            (staging / "manifest.json").write_text(
                json.dumps(
                    release_manifest,
                    indent=2,
                    sort_keys=True,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            staging.rename(target)

    release_manifest_path = target / "manifest.json"
    alias = config.alias or _default_alias(config.mode, verified)
    alias_path = _write_alias(
        release_root=release_root,
        alias=alias,
        release_status=release_status,
        release_fingerprint=release_fingerprint,
        release_directory=target,
        release_manifest_path=release_manifest_path,
        normalized_result=normalized_result,
        supervised_result=supervised_result,
    )
    return PublicationResult(
        release_fingerprint=release_fingerprint,
        release_status=release_status,
        release_directory=target,
        release_manifest_path=release_manifest_path,
        alias=alias,
        alias_path=alias_path,
        normalized_build=normalized_result.export.output_directory,
        normalized_fingerprint=normalized_result.export.build_fingerprint,
        supervised_build=supervised_result.output_directory,
        supervised_fingerprint=supervised_result.build_fingerprint,
        normalized_games=normalized_games,
        eligible_games=supervised_result.training_rows,
        excluded_games=supervised_result.excluded_rows,
    )
