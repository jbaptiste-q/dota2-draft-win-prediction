"""Offline validation gate for one completed Milestone 3.6 partition.

The validator deliberately delegates acquisition finalization, partition
evidence verification, normalized checksum validation, and supervised dataset
construction to the existing Milestones 2 and 3 implementations.  It adds only
the completion-specific scope, quality-threshold, and exclusion-contract gates.
It never imports or calls the authenticated API client.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from src.draft_training_dataset.builder import (
    REQUIRED_NORMALIZED_TABLES,
    TrainingDatasetConfig,
    build_training_dataset,
)
from src.draft_training_dataset.schema import (
    SCHEMA_VERSION as SUPERVISED_SCHEMA_VERSION,
    TRAINING_COLUMNS,
    schema_payload,
)
from src.liquipedia_pipeline.dataset import (
    SCHEMA_VERSION as NORMALIZED_SCHEMA_VERSION,
)

from .config import BackfillConfig
from .finalize import finalize_completed_run
from .publication import (
    PublicationMode,
    PartitionRun,
    VerifiedPartition,
    sha256_file,
    verify_partition,
    verify_partition_sequence,
)
from .publication import (
    _verify_normalized_build as verify_normalized_build,
)
from .publication import (
    _verify_supervised_build as verify_supervised_build,
)
from .reports import read_parquet


MIN_ELIGIBILITY_PERCENTAGE = 70.0
MIN_PATCH_COVERAGE_PERCENTAGE = 95.0
MIN_WINNER_COVERAGE_PERCENTAGE = 80.0
MIN_SIDE_COVERAGE_PERCENTAGE = 80.0
FULL_CAMPAIGN_PARTITION_COUNT = 19

ALLOWED_EXCLUSION_REASONS = frozenset(
    {
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
)


class PartitionValidationError(ValueError):
    """Raised when a completed partition is unsafe for campaign continuation."""


@dataclass(frozen=True, slots=True)
class PartitionValidationMetrics:
    """Credential-free, path-independent evidence from a successful gate."""

    partition_id: str
    run_id: str
    sequence_mode: str
    completed_prefix_partitions: tuple[str, ...]
    scope_start_utc: str
    scope_end_utc: str
    request_count: int
    cache_hit_count: int
    raw_response_sha256: tuple[str, ...]
    acquisition_fingerprint: str
    assembly_fingerprint: str
    normalized_build_fingerprint: str
    normalized_manifest_sha256: str
    normalized_schema_version: str
    supervised_build_fingerprint: str
    supervised_manifest_sha256: str
    supervised_schema_version: str
    accepted_matches: int
    accepted_games: int
    normalized_matches: int
    normalized_games: int
    eligible_games: int
    excluded_games: int
    eligibility_percentage: float
    patch_coverage_percentage: float
    winner_coverage_percentage: float
    side_coverage_percentage: float
    target_class_counts: tuple[tuple[str, int], ...]
    exclusion_counts: tuple[tuple[str, int], ...]
    hero_vocabulary_size: int
    duplicate_matches: int
    duplicate_games: int
    quarantined_records: int

    def payload(self) -> dict[str, object]:
        """Return the public payload expected by campaign coordination."""
        return self.to_payload()

    def to_payload(self) -> dict[str, object]:
        """Return deterministic JSON-compatible public validation evidence."""
        return {
            "status": "passed",
            "partition_id": self.partition_id,
            "run_id": self.run_id,
            "sequence_mode": self.sequence_mode,
            "completed_prefix_partitions": list(
                self.completed_prefix_partitions
            ),
            "scope": {
                "start_utc_inclusive": self.scope_start_utc,
                "end_utc_exclusive": self.scope_end_utc,
            },
            "acquisition": {
                "request_count": self.request_count,
                "cache_hit_count": self.cache_hit_count,
                "raw_response_sha256": list(self.raw_response_sha256),
                "fingerprint": self.acquisition_fingerprint,
            },
            "assembly": {
                "fingerprint": self.assembly_fingerprint,
                "accepted_matches": self.accepted_matches,
                "accepted_games": self.accepted_games,
                "duplicate_matches": self.duplicate_matches,
                "duplicate_games": self.duplicate_games,
                "quarantined_records": self.quarantined_records,
            },
            "normalized": {
                "schema_version": self.normalized_schema_version,
                "build_fingerprint": self.normalized_build_fingerprint,
                "manifest_sha256": self.normalized_manifest_sha256,
                "matches": self.normalized_matches,
                "games": self.normalized_games,
            },
            "supervised": {
                "schema_version": self.supervised_schema_version,
                "build_fingerprint": self.supervised_build_fingerprint,
                "manifest_sha256": self.supervised_manifest_sha256,
                "eligible_games": self.eligible_games,
                "excluded_games": self.excluded_games,
                "hero_vocabulary_size": self.hero_vocabulary_size,
                "target_class_counts": dict(self.target_class_counts),
                "exclusion_counts": dict(self.exclusion_counts),
            },
            "coverage_percentages": {
                "eligibility": self.eligibility_percentage,
                "patch": self.patch_coverage_percentage,
                "winner": self.winner_coverage_percentage,
                "sides": self.side_coverage_percentage,
            },
        }


def _json_object(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise PartitionValidationError(f"{label} not found: {path.name}.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PartitionValidationError(
            f"{label} is not valid JSON: {path.name}."
        ) from error
    if not isinstance(payload, dict):
        raise PartitionValidationError(f"{label} must be a JSON object.")
    return payload


def _mapping(value: object, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PartitionValidationError(f"{label} must be an object.")
    return value


def _integer(value: object, *, label: str) -> int:
    if isinstance(value, bool):
        raise PartitionValidationError(f"{label} must be an integer.")
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise PartitionValidationError(f"{label} must be an integer.") from error


def _percentage(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator * 100, 6)


def _require_minimum(
    value: float,
    minimum: float,
    *,
    label: str,
) -> None:
    if value < minimum:
        raise PartitionValidationError(
            f"{label} is {value:.6f}%; required minimum is {minimum:.6f}%."
        )


def _resolve_output_root(repository_root: Path, path: Path) -> Path:
    if path.is_absolute():
        return path.resolve()
    return (repository_root.resolve() / path).resolve()


def _verify_current_selection(
    *,
    partition_id: str,
    config: BackfillConfig,
    completed_prefix: Sequence[PartitionRun | tuple[str, str]],
) -> tuple[PartitionRun, tuple[PartitionRun, ...], PublicationMode]:
    try:
        selections = tuple(
            value
            if isinstance(value, PartitionRun)
            else PartitionRun(
                partition_id=value[0],
                run_id=value[1],
            )
            for value in completed_prefix
        )
    except (IndexError, TypeError, ValueError) as error:
        raise PartitionValidationError(
            "Completed-prefix selections must be PartitionRun values or "
            "(partition_id, run_id) pairs."
        ) from error
    if not selections:
        raise PartitionValidationError(
            "Completed-prefix selections must not be empty."
        )
    current = PartitionRun(partition_id=partition_id, run_id=config.run_id)
    if selections[-1] != current:
        raise PartitionValidationError(
            "The validated partition must be the final completed-prefix "
            "selection."
        )
    mode = (
        PublicationMode.FULL_WINDOW
        if len(selections) == FULL_CAMPAIGN_PARTITION_COUNT
        else PublicationMode.PROVISIONAL_PREFIX
    )
    return current, selections, mode


def _verify_partition_scope(
    matches: pd.DataFrame,
    games: pd.DataFrame,
    *,
    config: BackfillConfig,
) -> None:
    required_match_columns = {
        "source_match_id",
        "start_time_utc",
        "liquipedia_tier",
        "finished",
    }
    missing = required_match_columns.difference(matches.columns)
    if missing:
        raise PartitionValidationError(
            "Normalized matches lack scope columns: "
            + ", ".join(sorted(missing))
            + "."
        )
    if matches.empty:
        raise PartitionValidationError(
            "A completed partition must contain at least one normalized match."
        )
    if games.empty:
        raise PartitionValidationError(
            "A completed partition must contain at least one normalized game."
        )
    if set(config.tiers) != {"1", "2"}:
        raise PartitionValidationError(
            "Milestone 3.6 partitions must request exactly Tier 1 and Tier 2."
        )

    tiers = matches["liquipedia_tier"].astype("string")
    if tiers.isna().any() or not tiers.isin(("1", "2")).all():
        observed = sorted(
            {
                str(value)
                for value in tiers.dropna().tolist()
                if str(value) not in {"1", "2"}
            }
        )
        detail = ", ".join(observed[:5]) if observed else "<missing>"
        raise PartitionValidationError(
            "Normalized matches fall outside Tier 1/2 scope: " + detail + "."
        )

    finished = matches["finished"].astype("boolean")
    if finished.isna().any() or not finished.fillna(False).all():
        raise PartitionValidationError(
            "Normalized matches include unfinished or unknown match status."
        )

    timestamps = pd.to_datetime(
        matches["start_time_utc"],
        utc=True,
        errors="coerce",
    )
    if timestamps.isna().any():
        raise PartitionValidationError(
            "Normalized matches include missing or invalid start timestamps."
        )
    in_scope = (timestamps >= config.start_utc) & (
        timestamps < config.end_utc
    )
    if not in_scope.all():
        raise PartitionValidationError(
            "Normalized match timestamps violate the approved half-open "
            "partition scope."
        )

    match_ids = set(matches["source_match_id"].astype(str))
    if "source_match_id" not in games.columns:
        raise PartitionValidationError(
            "Normalized games lack source_match_id lineage."
        )
    game_match_ids = set(games["source_match_id"].astype(str))
    if not game_match_ids.issubset(match_ids):
        raise PartitionValidationError(
            "Normalized games reference matches outside the partition."
        )


def _reason_counts(frame: pd.DataFrame) -> tuple[tuple[str, int], ...]:
    if "exclusion_reason" not in frame.columns:
        raise PartitionValidationError(
            "Eligibility output lacks exclusion_reason."
        )
    values = frame["exclusion_reason"].dropna().astype(str)
    unknown = sorted(set(values).difference(ALLOWED_EXCLUSION_REASONS))
    if unknown:
        raise PartitionValidationError(
            "Unsupported supervised exclusion reason(s): "
            + ", ".join(unknown)
            + "."
        )
    counts = Counter(values.tolist())
    return tuple(sorted((reason, int(count)) for reason, count in counts.items()))


def _verify_eligibility_contract(
    normalized_games: pd.DataFrame,
    exclusions: pd.DataFrame,
) -> tuple[tuple[str, int], ...]:
    if "is_trainable_draft" not in normalized_games.columns:
        raise PartitionValidationError(
            "Normalized games lack is_trainable_draft."
        )
    normalized_counts = _reason_counts(normalized_games)
    excluded_counts = _reason_counts(exclusions)
    trainable = (
        normalized_games["is_trainable_draft"]
        .fillna(False)
        .astype(bool)
    )
    reasons = normalized_games["exclusion_reason"]
    if reasons[trainable].notna().any():
        raise PartitionValidationError(
            "Trainable normalized games must not have an exclusion reason."
        )
    if reasons[~trainable].isna().any():
        raise PartitionValidationError(
            "Every ineligible normalized game must have an exclusion reason."
        )
    if normalized_counts != excluded_counts:
        raise PartitionValidationError(
            "Normalized and supervised exclusion counts do not reconcile."
        )
    return excluded_counts


def _verify_target_classes(
    training: pd.DataFrame,
) -> tuple[tuple[str, int], ...]:
    if "radiant_win" not in training.columns:
        raise PartitionValidationError(
            "Supervised training data lacks radiant_win."
        )
    target = training["radiant_win"].astype("boolean")
    if target.isna().any():
        raise PartitionValidationError(
            "Supervised target contains missing values."
        )
    counts = {
        "false": int(target.eq(False).sum()),
        "true": int(target.eq(True).sum()),
    }
    if any(count == 0 for count in counts.values()):
        raise PartitionValidationError(
            "Supervised partition must contain both radiant_win classes."
        )
    return tuple(sorted(counts.items()))


def _verify_quality_reconciliation(
    *,
    coverage: Mapping[str, Any],
    quality: Mapping[str, Any],
    normalized_matches: int,
    normalized_games: int,
    eligible_games: int,
    excluded_games: int,
    hero_vocabulary_size: int,
    target_class_counts: tuple[tuple[str, int], ...],
    exclusion_counts: tuple[tuple[str, int], ...],
) -> tuple[float, float, float, float]:
    expected_counts = {
        "match_count": normalized_matches,
        "game_count": normalized_games,
        "trainable_game_count": eligible_games,
    }
    for key, expected in expected_counts.items():
        if _integer(coverage.get(key), label=f"coverage {key}") != expected:
            raise PartitionValidationError(
                f"Coverage {key} does not reconcile with normalized data."
            )
    if eligible_games + excluded_games != normalized_games:
        raise PartitionValidationError(
            "Normalized games do not equal eligible plus excluded games."
        )

    if _integer(quality.get("training_rows"), label="quality training_rows") != (
        eligible_games
    ):
        raise PartitionValidationError(
            "Quality report training count does not reconcile."
        )
    if _integer(quality.get("excluded_rows"), label="quality excluded_rows") != (
        excluded_games
    ):
        raise PartitionValidationError(
            "Quality report exclusion count does not reconcile."
        )
    if _integer(
        quality.get("hero_vocabulary_size"),
        label="quality hero_vocabulary_size",
    ) != hero_vocabulary_size:
        raise PartitionValidationError(
            "Quality report vocabulary count does not reconcile."
        )

    quality_target_counts = {
        str(key).casefold(): _integer(
            value,
            label=f"quality target count {key}",
        )
        for key, value in _mapping(
            quality.get("target_class_counts"),
            label="quality target_class_counts",
        ).items()
    }
    if quality_target_counts != dict(target_class_counts):
        raise PartitionValidationError(
            "Quality report target counts do not reconcile."
        )
    quality_exclusion_counts = {
        str(key): _integer(
            value,
            label=f"quality exclusion count {key}",
        )
        for key, value in _mapping(
            quality.get("exclusion_counts"),
            label="quality exclusion_counts",
        ).items()
    }
    if quality_exclusion_counts != dict(exclusion_counts):
        raise PartitionValidationError(
            "Quality report exclusion counts do not reconcile."
        )

    coverage_outcomes = {
        str(key): _integer(
            value,
            label=f"coverage eligibility count {key}",
        )
        for key, value in _mapping(
            coverage.get("eligibility_failures"),
            label="coverage eligibility_failures",
        ).items()
    }
    expected_outcomes = dict(exclusion_counts)
    expected_outcomes["<trainable>"] = eligible_games
    if coverage_outcomes != expected_outcomes:
        raise PartitionValidationError(
            "Coverage eligibility outcomes do not reconcile."
        )

    coverage_numerators = {
        "eligibility": eligible_games,
        "patch": _integer(
            coverage.get("patch_known_count"),
            label="coverage patch_known_count",
        ),
        "winner": _integer(
            coverage.get("winner_known_count"),
            label="coverage winner_known_count",
        ),
        "sides": _integer(
            coverage.get("sides_known_count"),
            label="coverage sides_known_count",
        ),
    }
    if any(
        value < 0 or value > normalized_games
        for value in coverage_numerators.values()
    ):
        raise PartitionValidationError(
            "Coverage counts fall outside the normalized game count."
        )
    percentages = {
        name: _percentage(value, normalized_games)
        for name, value in coverage_numerators.items()
    }
    _require_minimum(
        percentages["eligibility"],
        MIN_ELIGIBILITY_PERCENTAGE,
        label="Supervised eligibility",
    )
    _require_minimum(
        percentages["patch"],
        MIN_PATCH_COVERAGE_PERCENTAGE,
        label="Patch coverage",
    )
    _require_minimum(
        percentages["winner"],
        MIN_WINNER_COVERAGE_PERCENTAGE,
        label="Winner coverage",
    )
    _require_minimum(
        percentages["sides"],
        MIN_SIDE_COVERAGE_PERCENTAGE,
        label="Side coverage",
    )
    return (
        percentages["eligibility"],
        percentages["patch"],
        percentages["winner"],
        percentages["sides"],
    )


def validate_completed_partition(
    partition_id: str,
    config: BackfillConfig,
    completed_prefix: Sequence[PartitionRun | tuple[str, str]],
    repository_root: Path,
    training_output_root: Path = Path(
        "data/training/dota_draft_supervised"
    ),
) -> PartitionValidationMetrics:
    """Finalize and validate one partition entirely from accepted local data."""
    current, selections, mode = _verify_current_selection(
        partition_id=partition_id,
        config=config,
        completed_prefix=completed_prefix,
    )

    finalization = finalize_completed_run(config)
    if finalization.assembly.quarantined_matches != 0:
        raise PartitionValidationError(
            "Partition assembly contains quarantined records."
        )

    verified_prefix: list[VerifiedPartition] = []
    verified_current: VerifiedPartition | None = None
    for selection in selections:
        verified = verify_partition(selection, run_root=config.run_root)
        verified_prefix.append(verified)
        if selection == current:
            verified_current = verified
    if verified_current is None:
        raise PartitionValidationError(
            "Current partition is absent from the verified prefix."
        )
    verify_partition_sequence(
        tuple(verified_prefix),
        mode=mode,
        repository_root=repository_root,
    )
    if verified_current.config_hash != config.config_hash:
        raise PartitionValidationError(
            "Validated partition config hash does not match the supplied config."
        )
    if (
        verified_current.start_utc != config.start_utc
        or verified_current.end_utc != config.end_utc
    ):
        raise PartitionValidationError(
            "Validated partition scope does not match the supplied config."
        )
    if verified_current.acquisition_fingerprint != (
        finalization.acquisition_fingerprint
    ):
        raise PartitionValidationError(
            "Finalized acquisition fingerprint does not reconcile."
        )
    if verified_current.assembly_fingerprint != (
        finalization.assembly.build_fingerprint
    ):
        raise PartitionValidationError(
            "Finalized assembly fingerprint does not reconcile."
        )

    normalized_manifest, normalized_evidence, normalized_game_count = (
        verify_normalized_build(
            finalization.normalized,
            expected_matches=verified_current.accepted_matches,
            expected_games=verified_current.accepted_games,
        )
    )
    normalized_root = finalization.normalized.export.output_directory
    matches = read_parquet(normalized_root / "matches.parquet")
    games = read_parquet(normalized_root / "games.parquet")
    _verify_partition_scope(matches, games, config=config)
    if normalized_game_count != len(games):
        raise PartitionValidationError(
            "Normalized game evidence does not reconcile."
        )

    run_manifest = _json_object(
        finalization.manifest_path,
        label="partition finalization manifest",
    )
    run_normalized = _mapping(
        run_manifest.get("normalized"),
        label="partition finalization normalized lineage",
    )
    if (
        run_manifest.get("acquisition_fingerprint")
        != finalization.acquisition_fingerprint
        or run_normalized.get("build_fingerprint")
        != finalization.normalized.export.build_fingerprint
        or run_normalized.get("schema_version")
        != NORMALIZED_SCHEMA_VERSION
    ):
        raise PartitionValidationError(
            "Partition finalization lineage does not reconcile."
        )

    supervised = build_training_dataset(
        TrainingDatasetConfig(
            normalized_build=normalized_root,
            output_root=_resolve_output_root(
                repository_root,
                training_output_root,
            ),
        )
    )
    supervised_manifest, supervised_evidence = verify_supervised_build(
        supervised,
        normalized_result=finalization.normalized,
    )
    normalized_source = _mapping(
        supervised_manifest.get("normalized_source"),
        label="supervised normalized_source",
    )
    if normalized_source.get("schema_version") != NORMALIZED_SCHEMA_VERSION:
        raise PartitionValidationError(
            "Supervised source schema does not match normalized schema."
        )
    if supervised_manifest.get("filters") != {
        "start_utc": None,
        "end_utc": None,
        "tiers": [],
        "patches": [],
        "tournaments": [],
    }:
        raise PartitionValidationError(
            "Per-partition supervised build must not apply row filters."
        )
    if supervised_manifest.get("training_columns") != list(TRAINING_COLUMNS):
        raise PartitionValidationError(
            "Supervised training-column contract changed."
        )
    schema = _json_object(supervised.schema_path, label="supervised schema")
    if schema != schema_payload():
        raise PartitionValidationError(
            "Supervised schema artifact does not match the canonical contract."
        )

    normalized_entries = {
        str(entry.get("name")): entry
        for entry in normalized_manifest.get("tables", [])
        if isinstance(entry, Mapping)
    }
    verified_source_hashes = _mapping(
        normalized_source.get("verified_table_sha256"),
        label="supervised verified_table_sha256",
    )
    if set(verified_source_hashes) != set(REQUIRED_NORMALIZED_TABLES):
        raise PartitionValidationError(
            "Supervised normalized-table checksum lineage is incomplete."
        )
    expected_source_hashes = {
        name: str(normalized_entries[name]["parquet_sha256"])
        for name in REQUIRED_NORMALIZED_TABLES
        if name in normalized_entries
    }
    if (
        len(expected_source_hashes) != len(verified_source_hashes)
        or dict(verified_source_hashes) != expected_source_hashes
    ):
        raise PartitionValidationError(
            "Supervised normalized-table checksum lineage changed."
        )

    training = read_parquet(supervised.training_path)
    exclusions = read_parquet(supervised.exclusions_path)
    vocabulary = read_parquet(supervised.vocabulary_path)
    if training.empty:
        raise PartitionValidationError(
            "A completed partition must contain eligible supervised games."
        )
    exclusion_counts = _verify_eligibility_contract(games, exclusions)
    target_class_counts = _verify_target_classes(training)

    quality = _json_object(
        supervised.quality_report_path,
        label="supervised quality report",
    )
    if supervised_manifest.get("quality_report") != quality:
        raise PartitionValidationError(
            "Supervised quality artifact and manifest disagree."
        )
    coverage = _json_object(
        finalization.reports_directory / "coverage_summary.json",
        label="partition coverage summary",
    )
    (
        eligibility_percentage,
        patch_coverage_percentage,
        winner_coverage_percentage,
        side_coverage_percentage,
    ) = _verify_quality_reconciliation(
        coverage=coverage,
        quality=quality,
        normalized_matches=len(matches),
        normalized_games=len(games),
        eligible_games=len(training),
        excluded_games=len(exclusions),
        hero_vocabulary_size=len(vocabulary),
        target_class_counts=target_class_counts,
        exclusion_counts=exclusion_counts,
    )

    supervised_counts = _mapping(
        supervised_evidence,
        label="supervised verification evidence",
    )
    if (
        _integer(
            supervised_counts.get("normalized_games"),
            label="verified normalized games",
        )
        != len(games)
        or _integer(
            supervised_counts.get("eligible_games"),
            label="verified eligible games",
        )
        != len(training)
        or _integer(
            supervised_counts.get("excluded_games"),
            label="verified excluded games",
        )
        != len(exclusions)
    ):
        raise PartitionValidationError(
            "Supervised verification evidence does not reconcile."
        )

    return PartitionValidationMetrics(
        partition_id=partition_id,
        run_id=config.run_id,
        sequence_mode=mode.value,
        completed_prefix_partitions=tuple(
            selection.partition_id for selection in selections
        ),
        scope_start_utc=config.start_utc.isoformat(),
        scope_end_utc=config.end_utc.isoformat(),
        request_count=verified_current.request_count,
        cache_hit_count=verified_current.cache_hit_count,
        raw_response_sha256=verified_current.raw_response_sha256,
        acquisition_fingerprint=verified_current.acquisition_fingerprint,
        assembly_fingerprint=verified_current.assembly_fingerprint,
        normalized_build_fingerprint=(
            finalization.normalized.export.build_fingerprint
        ),
        normalized_manifest_sha256=str(
            normalized_evidence["manifest_sha256"]
        ),
        normalized_schema_version=NORMALIZED_SCHEMA_VERSION,
        supervised_build_fingerprint=supervised.build_fingerprint,
        supervised_manifest_sha256=sha256_file(supervised.manifest_path),
        supervised_schema_version=SUPERVISED_SCHEMA_VERSION,
        accepted_matches=verified_current.accepted_matches,
        accepted_games=verified_current.accepted_games,
        normalized_matches=len(matches),
        normalized_games=len(games),
        eligible_games=len(training),
        excluded_games=len(exclusions),
        eligibility_percentage=eligibility_percentage,
        patch_coverage_percentage=patch_coverage_percentage,
        winner_coverage_percentage=winner_coverage_percentage,
        side_coverage_percentage=side_coverage_percentage,
        target_class_counts=target_class_counts,
        exclusion_counts=exclusion_counts,
        hero_vocabulary_size=len(vocabulary),
        duplicate_matches=verified_current.duplicate_matches,
        duplicate_games=verified_current.duplicate_games,
        quarantined_records=0,
    )
