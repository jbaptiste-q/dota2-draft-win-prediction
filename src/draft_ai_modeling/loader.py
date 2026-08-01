"""Verified, deterministic loading for the Milestone 4A working corpus.

Only credential-free supervised artifacts are accepted.  This module has no
dependency on acquisition, parsing, or normalization implementations.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from src.draft_training_dataset.schema import (
    SCHEMA_VERSION,
    TRAINING_COLUMNS,
    schema_payload,
)

from .contracts import CURRENT_WORKING_CORPUS


CONFIG_SCHEMA_VERSION = "draft-ai-working-corpus-v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SORT_COLUMNS = ("match_start_utc", "source_match_id", "game_index")
_STRING_COLUMNS = tuple(
    column
    for column in TRAINING_COLUMNS
    if column not in {"game_index", "match_start_utc", "radiant_win"}
)


class CorpusValidationError(ValueError):
    """Raised when a corpus input differs from its pinned contract."""


@dataclass(frozen=True, slots=True)
class TimeScope:
    """One half-open UTC interval."""

    start_utc: datetime
    end_utc: datetime


@dataclass(frozen=True, slots=True)
class CorpusComponent:
    """One immutable canonical-supervised input."""

    component_id: str
    scope: TimeScope
    manifest_path: Path
    manifest_sha256: str
    build_fingerprint: str
    training_path: Path
    training_sha256: str
    training_rows: int
    excluded_rows: int


@dataclass(frozen=True, slots=True)
class AggregateExpectations:
    """Reconciled identity for the concatenated corpus."""

    scope: TimeScope
    training_rows: int
    excluded_rows: int
    source_match_groups: int
    radiant_win_true: int
    radiant_win_false: int
    minimum_match_start_utc: datetime
    maximum_match_start_utc: datetime
    null_counts: tuple[tuple[str, int], ...]
    year_row_counts: tuple[tuple[int, int], ...]
    unique_sample_ids: int
    unique_game_keys: int
    duplicate_match_source_game_pairs: int
    duplicate_match_game_index_pairs: int
    cross_component_match_groups: int
    multi_patch_match_groups: int
    side_assignment_change_match_groups: int


@dataclass(frozen=True, slots=True)
class WorkingCorpusConfig:
    """Resolved path manifest and aggregate contract."""

    config_path: Path
    repository_root: Path
    corpus_id: str
    schema_sha256: str
    components: tuple[CorpusComponent, ...]
    expected: AggregateExpectations


@dataclass(frozen=True, slots=True)
class LoadedWorkingCorpus:
    """Verified deterministic rows and their immutable configuration."""

    config: WorkingCorpusConfig
    frame: pd.DataFrame
    verified_component_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LoadedCorpusPrefix:
    """Verified whole-component prefix ending at an exact UTC boundary."""

    config: WorkingCorpusConfig
    scope: TimeScope
    frame: pd.DataFrame
    verified_component_ids: tuple[str, ...]
    expected_training_rows: int


def sha256_file(path: Path) -> str:
    """Return the streaming SHA-256 checksum of a local file."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise CorpusValidationError("Corpus timestamps must include an offset.")
    return parsed.astimezone(UTC)


def _scope(payload: dict[str, Any]) -> TimeScope:
    scope = TimeScope(
        start_utc=_utc(payload["start_utc_inclusive"]),
        end_utc=_utc(payload["end_utc_exclusive"]),
    )
    if scope.start_utc >= scope.end_utc:
        raise CorpusValidationError("Corpus scopes must be non-empty.")
    return scope


def _repository_path(root: Path, value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise CorpusValidationError(
            "Corpus artifact paths must be repository-relative."
        )
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise CorpusValidationError(
            "A corpus artifact path escapes the repository."
        ) from error
    return resolved


def _repository_root(config_path: Path) -> Path:
    for candidate in config_path.parents:
        if (
            candidate
            / "src"
            / "draft_training_dataset"
            / "schema.py"
        ).is_file():
            return candidate.resolve()
    raise CorpusValidationError("Could not discover the repository root.")


def _require_sha256(value: str, *, label: str) -> str:
    if _SHA256.fullmatch(value) is None:
        raise CorpusValidationError(f"{label} is not a valid SHA-256 value.")
    return value


def _parse_component(
    payload: dict[str, Any],
    *,
    root: Path,
) -> CorpusComponent:
    artifact = payload["training_artifact"]
    counts = payload["expected"]
    component = CorpusComponent(
        component_id=str(payload["component_id"]),
        scope=_scope(payload["scope"]),
        manifest_path=_repository_path(root, payload["manifest_path"]),
        manifest_sha256=_require_sha256(
            payload["manifest_sha256"],
            label="manifest_sha256",
        ),
        build_fingerprint=_require_sha256(
            payload["build_fingerprint"],
            label="build_fingerprint",
        ),
        training_path=_repository_path(root, artifact["path"]),
        training_sha256=_require_sha256(
            artifact["sha256"],
            label="training artifact sha256",
        ),
        training_rows=int(counts["training_rows"]),
        excluded_rows=int(counts["excluded_rows"]),
    )
    if (
        not component.component_id
        or component.training_rows < 0
        or component.excluded_rows < 0
    ):
        raise CorpusValidationError("Invalid corpus component metadata.")
    return component


def _parse_expected(payload: dict[str, Any]) -> AggregateExpectations:
    identity = payload["identity"]
    grouping = payload["grouping"]
    return AggregateExpectations(
        scope=_scope(payload["scope"]),
        training_rows=int(payload["training_rows"]),
        excluded_rows=int(payload["excluded_rows"]),
        source_match_groups=int(payload["source_match_groups"]),
        radiant_win_true=int(payload["radiant_win_true"]),
        radiant_win_false=int(payload["radiant_win_false"]),
        minimum_match_start_utc=_utc(payload["minimum_match_start_utc"]),
        maximum_match_start_utc=_utc(payload["maximum_match_start_utc"]),
        null_counts=tuple(
            sorted((str(key), int(value)) for key, value in payload[
                "null_counts"
            ].items())
        ),
        year_row_counts=tuple(
            sorted(
                (int(key), int(value))
                for key, value in payload["year_row_counts"].items()
            )
        ),
        unique_sample_ids=int(identity["unique_sample_ids"]),
        unique_game_keys=int(identity["unique_game_keys"]),
        duplicate_match_source_game_pairs=int(
            identity["duplicate_match_source_game_pairs"]
        ),
        duplicate_match_game_index_pairs=int(
            identity["duplicate_match_game_index_pairs"]
        ),
        cross_component_match_groups=int(
            grouping["cross_component_match_groups"]
        ),
        multi_patch_match_groups=int(grouping["multi_patch_match_groups"]),
        side_assignment_change_match_groups=int(
            grouping["side_assignment_change_match_groups"]
        ),
    )


def _validate_config(config: WorkingCorpusConfig) -> None:
    components = config.components
    expected = config.expected
    if not components or len({item.component_id for item in components}) != len(
        components
    ):
        raise CorpusValidationError("Corpus component IDs must be non-empty and unique.")
    if components[0].scope.start_utc != expected.scope.start_utc:
        raise CorpusValidationError("The first component boundary is invalid.")
    if components[-1].scope.end_utc != expected.scope.end_utc:
        raise CorpusValidationError("The final component boundary is invalid.")
    if any(
        previous.scope.end_utc != current.scope.start_utc
        for previous, current in zip(components, components[1:], strict=False)
    ):
        raise CorpusValidationError(
            "Components must form one ordered contiguous time range."
        )
    if sum(item.training_rows for item in components) != expected.training_rows:
        raise CorpusValidationError("Component training rows do not reconcile.")
    if sum(item.excluded_rows for item in components) != expected.excluded_rows:
        raise CorpusValidationError("Component excluded rows do not reconcile.")
    if expected.radiant_win_true + expected.radiant_win_false != (
        expected.training_rows
    ):
        raise CorpusValidationError("Target classes do not reconcile.")

    contract = CURRENT_WORKING_CORPUS
    if config.corpus_id != contract.corpus_id:
        return
    aggregate = (
        expected.scope.start_utc,
        expected.scope.end_utc,
        expected.training_rows,
        expected.source_match_groups,
        expected.radiant_win_true,
        expected.radiant_win_false,
    )
    declared = (
        contract.start_utc,
        contract.end_utc,
        contract.expected_rows,
        contract.expected_source_matches,
        contract.expected_radiant_wins,
        contract.expected_radiant_losses,
    )
    component_identity = tuple(
        (
            item.component_id,
            item.scope.start_utc,
            item.scope.end_utc,
            item.build_fingerprint,
            item.training_rows,
        )
        for item in components
    )
    declared_components = tuple(
        (
            item.component_id,
            item.start_utc,
            item.end_utc,
            item.supervised_build_fingerprint,
            item.expected_rows,
        )
        for item in contract.components
    )
    if aggregate != declared or component_identity != declared_components:
        raise CorpusValidationError(
            "The path manifest diverges from CURRENT_WORKING_CORPUS."
        )


def load_corpus_config(
    config_path: Path,
    *,
    repository_root: Path | None = None,
) -> WorkingCorpusConfig:
    """Parse the credential-free working-corpus path manifest."""
    path = config_path.resolve()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload["config_schema_version"] != CONFIG_SCHEMA_VERSION:
            raise CorpusValidationError("Unsupported corpus config version.")
        supervised = payload["supervised_schema"]
        if (
            supervised["schema_version"] != SCHEMA_VERSION
            or tuple(supervised["columns"]) != TRAINING_COLUMNS
            or tuple(payload["sort_columns"]) != _SORT_COLUMNS
            or payload["group_column"] != "source_match_id"
            or payload["target_column"] != "radiant_win"
        ):
            raise CorpusValidationError("The supervised corpus contract changed.")
        root = (
            repository_root.resolve()
            if repository_root is not None
            else _repository_root(path)
        )
        config = WorkingCorpusConfig(
            config_path=path,
            repository_root=root,
            corpus_id=str(payload["corpus_id"]),
            schema_sha256=_require_sha256(
                supervised["schema_sha256"],
                label="schema_sha256",
            ),
            components=tuple(
                _parse_component(component, root=root)
                for component in payload["components"]
            ),
            expected=_parse_expected(payload["expected_aggregate"]),
        )
    except CorpusValidationError:
        raise
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise CorpusValidationError("Malformed working-corpus config.") from error
    _validate_config(config)
    return config


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CorpusValidationError(f"Invalid {label}: {path}.") from error
    if not isinstance(payload, dict):
        raise CorpusValidationError(f"{label} must be a JSON object.")
    return payload


def _verify_component(
    config: WorkingCorpusConfig,
    component: CorpusComponent,
) -> None:
    if sha256_file(component.manifest_path) != component.manifest_sha256:
        raise CorpusValidationError(
            f"Manifest checksum mismatch for {component.component_id}."
        )
    manifest = _read_json(component.manifest_path, label="component manifest")
    if (
        manifest.get("build_fingerprint") != component.build_fingerprint
        or manifest.get("schema_version") != SCHEMA_VERSION
        or tuple(manifest.get("training_columns", ())) != TRAINING_COLUMNS
        or manifest.get("row_counts", {}).get("training")
        != component.training_rows
        or manifest.get("row_counts", {}).get("excluded")
        != component.excluded_rows
    ):
        raise CorpusValidationError(
            f"Manifest contract mismatch for {component.component_id}."
        )

    artifacts = manifest.get("artifacts", {})
    training = artifacts.get("draft_training_games", {})
    schema = artifacts.get("schema", {})
    training_path = (
        component.manifest_path.parent / training.get("file", "")
    ).resolve()
    schema_path = (
        component.manifest_path.parent / schema.get("file", "")
    ).resolve()
    if (
        training_path != component.training_path
        or training.get("sha256") != component.training_sha256
        or sha256_file(component.training_path) != component.training_sha256
    ):
        raise CorpusValidationError(
            f"Training artifact checksum mismatch for {component.component_id}."
        )
    if (
        schema.get("sha256") != config.schema_sha256
        or sha256_file(schema_path) != config.schema_sha256
        or _read_json(schema_path, label="supervised schema") != schema_payload()
    ):
        raise CorpusValidationError(
            f"Schema artifact mismatch for {component.component_id}."
        )


def verify_working_corpus(config: WorkingCorpusConfig) -> tuple[str, ...]:
    """Verify all component manifests and artifacts without loading rows."""
    for component in config.components:
        _verify_component(config, component)
    return tuple(item.component_id for item in config.components)


def _quoted(column: str) -> str:
    return '"' + column.replace('"', '""') + '"'


def _read_frame(component: CorpusComponent) -> pd.DataFrame:
    expected_types = {
        column: (
            "BIGINT"
            if column == "game_index"
            else (
                "TIMESTAMP WITH TIME ZONE"
                if column == "match_start_utc"
                else ("BOOLEAN" if column == "radiant_win" else "VARCHAR")
            )
        )
        for column in TRAINING_COLUMNS
    }
    with duckdb.connect() as connection:
        description = connection.execute(
            "DESCRIBE SELECT * FROM read_parquet(?)",
            [str(component.training_path)],
        ).fetchall()
        if tuple(row[0] for row in description) != TRAINING_COLUMNS:
            raise CorpusValidationError(
                f"Physical columns changed for {component.component_id}."
            )
        if {row[0]: row[1] for row in description} != expected_types:
            raise CorpusValidationError(
                f"Physical types changed for {component.component_id}."
            )
        connection.execute("SET TimeZone='UTC'")
        projection = ", ".join(
            (
                f"CAST({_quoted(column)} AS VARCHAR) AS {_quoted(column)}"
                if column == "match_start_utc"
                else _quoted(column)
            )
            for column in TRAINING_COLUMNS
        )
        frame = connection.execute(
            f"SELECT {projection} FROM read_parquet(?)",
            [str(component.training_path)],
        ).fetchdf()

    frame[list(_STRING_COLUMNS)] = frame[list(_STRING_COLUMNS)].astype("string")
    frame["game_index"] = frame["game_index"].astype("Int64")
    frame["match_start_utc"] = pd.to_datetime(
        frame["match_start_utc"],
        utc=True,
        errors="raise",
    ).astype("datetime64[us, UTC]")
    frame["radiant_win"] = frame["radiant_win"].astype("boolean")
    if len(frame) != component.training_rows:
        raise CorpusValidationError(
            f"Loaded row count changed for {component.component_id}."
        )
    timestamps = frame["match_start_utc"]
    if (
        timestamps.lt(pd.Timestamp(component.scope.start_utc)).any()
        or timestamps.ge(pd.Timestamp(component.scope.end_utc)).any()
    ):
        raise CorpusValidationError(
            f"Rows escape the scope for {component.component_id}."
        )
    frame["__component_id"] = component.component_id
    return frame


def _nonzero_null_counts(frame: pd.DataFrame) -> dict[str, int]:
    return {
        column: count
        for column in TRAINING_COLUMNS
        if (count := int(frame[column].isna().sum()))
    }


def _duplicate_pair_rows(
    frame: pd.DataFrame,
    columns: list[str],
) -> int:
    return int(frame.duplicated(columns, keep=False).sum())


def _validate_rows(frame: pd.DataFrame, config: WorkingCorpusConfig) -> None:
    expected = config.expected
    for column in ("sample_id", "game_key", "source_game_id", "source_match_id"):
        values = frame[column].astype("string")
        if values.isna().any() or values.str.len().eq(0).any():
            raise CorpusValidationError(f"{column} contains a missing identifier.")
    if (
        frame["game_index"].isna().any()
        or frame["match_start_utc"].isna().any()
        or frame["radiant_win"].isna().any()
    ):
        raise CorpusValidationError("Required typed columns contain nulls.")
    if frame["sample_id"].ne(frame["game_key"]).any():
        raise CorpusValidationError("sample_id and game_key diverge.")

    grouped = frame.groupby("source_match_id", sort=False, dropna=False)
    frame["__team_pair"] = [
        "\0".join(sorted((str(radiant), str(dire))))
        for radiant, dire in zip(
            frame["radiant_team_key"],
            frame["dire_team_key"],
            strict=True,
        )
    ]
    cross_component = int(
        grouped["__component_id"].nunique(dropna=False).gt(1).sum()
    )
    if cross_component != expected.cross_component_match_groups:
        raise CorpusValidationError(
            "Cross-component match group count changed."
        )
    stable_columns = (
        "match_start_utc",
        "liquipedia_tier",
        "tournament",
        "series",
        "__team_pair",
    )
    unstable = {
        column: int(grouped[column].nunique(dropna=False).gt(1).sum())
        for column in stable_columns
    }
    if any(unstable.values()):
        raise CorpusValidationError(
            f"Source-match grouping context changed: {unstable}."
        )

    observed = {
        "training_rows": len(frame),
        "source_match_groups": grouped.ngroups,
        "radiant_win_true": int(frame["radiant_win"].sum()),
        "radiant_win_false": len(frame) - int(frame["radiant_win"].sum()),
        "minimum_match_start_utc": (
            frame["match_start_utc"].min().to_pydatetime()
        ),
        "maximum_match_start_utc": (
            frame["match_start_utc"].max().to_pydatetime()
        ),
        "null_counts": _nonzero_null_counts(frame),
        "year_row_counts": {
            int(year): int(count)
            for year, count in (
                frame["match_start_utc"].dt.year.value_counts().items()
            )
        },
        "unique_sample_ids": int(frame["sample_id"].nunique(dropna=False)),
        "unique_game_keys": int(frame["game_key"].nunique(dropna=False)),
        "duplicate_match_source_game_pairs": _duplicate_pair_rows(
            frame,
            ["source_match_id", "source_game_id"],
        ),
        "duplicate_match_game_index_pairs": _duplicate_pair_rows(
            frame,
            ["source_match_id", "game_index"],
        ),
        "cross_component_match_groups": cross_component,
        "multi_patch_match_groups": int(
            grouped["patch"].nunique(dropna=True).gt(1).sum()
        ),
        "side_assignment_change_match_groups": int(
            grouped["radiant_team_key"].nunique(dropna=False).gt(1).sum()
        ),
    }
    expected_values = {
        "training_rows": expected.training_rows,
        "source_match_groups": expected.source_match_groups,
        "radiant_win_true": expected.radiant_win_true,
        "radiant_win_false": expected.radiant_win_false,
        "minimum_match_start_utc": expected.minimum_match_start_utc,
        "maximum_match_start_utc": expected.maximum_match_start_utc,
        "null_counts": dict(expected.null_counts),
        "year_row_counts": dict(expected.year_row_counts),
        "unique_sample_ids": expected.unique_sample_ids,
        "unique_game_keys": expected.unique_game_keys,
        "duplicate_match_source_game_pairs": (
            expected.duplicate_match_source_game_pairs
        ),
        "duplicate_match_game_index_pairs": (
            expected.duplicate_match_game_index_pairs
        ),
        "cross_component_match_groups": (
            expected.cross_component_match_groups
        ),
        "multi_patch_match_groups": expected.multi_patch_match_groups,
        "side_assignment_change_match_groups": (
            expected.side_assignment_change_match_groups
        ),
    }
    mismatches = {
        key: {"expected": expected_values[key], "observed": value}
        for key, value in observed.items()
        if value != expected_values[key]
    }
    if mismatches:
        raise CorpusValidationError(f"Corpus invariants changed: {mismatches}.")


def _validate_prefix_rows(
    frame: pd.DataFrame,
    *,
    components: tuple[CorpusComponent, ...],
    scope: TimeScope,
) -> None:
    expected_rows = sum(component.training_rows for component in components)
    if len(frame) != expected_rows:
        raise CorpusValidationError(
            "Loaded prefix row count does not reconcile with its components."
        )
    expected_columns = (*TRAINING_COLUMNS, "__component_id")
    if tuple(frame.columns) != expected_columns:
        raise CorpusValidationError("Loaded prefix schema changed.")
    if not isinstance(frame.index, pd.RangeIndex) or frame.index.start != 0:
        raise CorpusValidationError("Loaded prefix index is not deterministic.")
    sorted_index = frame.sort_values(
        list(_SORT_COLUMNS),
        kind="mergesort",
    ).index
    if not sorted_index.equals(frame.index):
        raise CorpusValidationError("Loaded prefix rows are not sorted.")

    timestamps = frame["match_start_utc"]
    if (
        timestamps.isna().any()
        or timestamps.lt(pd.Timestamp(scope.start_utc)).any()
        or timestamps.ge(pd.Timestamp(scope.end_utc)).any()
    ):
        raise CorpusValidationError("Loaded prefix rows escape its exact scope.")

    for column in ("sample_id", "game_key", "source_game_id", "source_match_id"):
        values = frame[column].astype("string")
        if values.isna().any() or values.str.len().eq(0).any():
            raise CorpusValidationError(
                f"{column} contains a missing identifier."
            )
    if frame["game_index"].isna().any() or frame["radiant_win"].isna().any():
        raise CorpusValidationError("Required typed columns contain nulls.")
    if frame["sample_id"].ne(frame["game_key"]).any():
        raise CorpusValidationError("sample_id and game_key diverge.")
    if (
        frame["sample_id"].duplicated(keep=False).any()
        or frame["game_key"].duplicated(keep=False).any()
        or frame.duplicated(
            ["source_match_id", "source_game_id"],
            keep=False,
        ).any()
        or frame.duplicated(
            ["source_match_id", "game_index"],
            keep=False,
        ).any()
    ):
        raise CorpusValidationError("Loaded prefix contains duplicate identities.")
    if (
        frame.groupby("source_match_id", sort=False, dropna=False)[
            "__component_id"
        ]
        .nunique(dropna=False)
        .gt(1)
        .any()
    ):
        raise CorpusValidationError(
            "A source-match group crosses prefix components."
        )


def load_working_corpus_prefix(
    config_or_path: WorkingCorpusConfig | Path,
    *,
    end_utc: datetime,
    repository_root: Path | None = None,
) -> LoadedCorpusPrefix:
    """Load only whole components ending at an exact timezone-aware boundary.

    Components after ``end_utc`` are represented only by the credential-free
    config metadata: their manifests and Parquet artifacts are neither verified
    nor read.
    """
    if end_utc.tzinfo is None or end_utc.utcoffset() is None:
        raise CorpusValidationError("Prefix end_utc must be timezone-aware.")
    boundary = end_utc.astimezone(UTC)
    config = (
        config_or_path
        if isinstance(config_or_path, WorkingCorpusConfig)
        else load_corpus_config(
            config_or_path,
            repository_root=repository_root,
        )
    )
    boundary_indexes = tuple(
        index
        for index, component in enumerate(config.components)
        if component.scope.end_utc == boundary
    )
    if len(boundary_indexes) != 1:
        raise CorpusValidationError(
            "Prefix end_utc must equal one exact component boundary."
        )
    components = config.components[: boundary_indexes[0] + 1]
    if not components:
        raise CorpusValidationError("A corpus prefix must contain a component.")

    verified_ids: list[str] = []
    frames: list[pd.DataFrame] = []
    for component in components:
        _verify_component(config, component)
        verified_ids.append(component.component_id)
        frames.append(_read_frame(component))
    frame = pd.concat(frames, ignore_index=True).sort_values(
        list(_SORT_COLUMNS),
        kind="mergesort",
    ).reset_index(drop=True)
    scope = TimeScope(
        start_utc=components[0].scope.start_utc,
        end_utc=boundary,
    )
    _validate_prefix_rows(frame, components=components, scope=scope)
    frame = frame.drop(columns=["__component_id"])
    return LoadedCorpusPrefix(
        config=config,
        scope=scope,
        frame=frame,
        verified_component_ids=tuple(verified_ids),
        expected_training_rows=sum(
            component.training_rows for component in components
        ),
    )


def load_working_corpus(
    config_or_path: WorkingCorpusConfig | Path,
    *,
    repository_root: Path | None = None,
) -> LoadedWorkingCorpus:
    """Verify, concatenate, type, and deterministically sort the corpus."""
    config = (
        config_or_path
        if isinstance(config_or_path, WorkingCorpusConfig)
        else load_corpus_config(
            config_or_path,
            repository_root=repository_root,
        )
    )
    verified_ids = verify_working_corpus(config)
    frame = pd.concat(
        [_read_frame(component) for component in config.components],
        ignore_index=True,
    ).sort_values(
        list(_SORT_COLUMNS),
        kind="mergesort",
    ).reset_index(drop=True)
    _validate_rows(frame, config)
    frame = frame.drop(columns=["__component_id", "__team_pair"])
    return LoadedWorkingCorpus(
        config=config,
        frame=frame,
        verified_component_ids=verified_ids,
    )
