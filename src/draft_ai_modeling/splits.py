"""Deterministic chronological splitting for the Draft AI working corpus."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import pandas as pd

from .contracts import (
    CURRENT_TEMPORAL_SPLIT,
    SPLIT_ROLE_CALIBRATION,
    SPLIT_ROLE_LOCKED_TEST,
    SPLIT_ROLE_TRAIN,
    SPLIT_ROLE_TUNING,
    SplitIntervalContract,
    TemporalSplitContract,
)


class SplitContractError(ValueError):
    """Raised when rows violate the deterministic temporal split contract."""


@dataclass(frozen=True, slots=True)
class SplitManifestResult:
    """In-memory split assignments, fingerprint, and reconciliation report."""

    manifest: pd.DataFrame
    fingerprint: str
    report: dict[str, Any]


def canonical_json(value: object) -> str:
    """Return a deterministic JSON representation."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _iso_utc(value: object) -> str:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.isoformat().replace("+00:00", "Z")


def split_contract_payload(
    contract: TemporalSplitContract = CURRENT_TEMPORAL_SPLIT,
) -> dict[str, object]:
    """Return the path-independent machine representation of a split contract."""
    return {
        "contract_version": contract.contract_version,
        "corpus_id": contract.corpus_id,
        "sample_id_column": contract.sample_id_column,
        "group_column": contract.group_column,
        "time_column": contract.time_column,
        "target_column": contract.target_column,
        "timezone": contract.timezone,
        "interval_semantics": contract.interval_semantics,
        "intervals": [
            {
                "interval_id": interval.interval_id,
                "primary_split": interval.primary_split,
                "role": interval.role,
                "start_utc": interval.start_utc.isoformat(),
                "end_utc": interval.end_utc.isoformat(),
                "expected_rows": interval.expected_rows,
                "expected_source_matches": interval.expected_source_matches,
                "expected_radiant_wins": interval.expected_radiant_wins,
                "expected_radiant_losses": interval.expected_radiant_losses,
            }
            for interval in contract.intervals
        ],
    }


def _required_columns(contract: TemporalSplitContract) -> tuple[str, ...]:
    return (
        contract.sample_id_column,
        contract.group_column,
        contract.time_column,
        contract.target_column,
    )


def _normalized_identifiers(
    values: pd.Series,
    *,
    column: str,
) -> pd.Series:
    if values.isna().any():
        raise SplitContractError(f"{column} cannot contain missing values.")
    normalized = values.astype("string").str.strip()
    if normalized.eq("").any():
        raise SplitContractError(f"{column} cannot contain empty values.")
    return normalized


def _assign_intervals(
    rows: pd.DataFrame,
    contract: TemporalSplitContract,
) -> pd.DataFrame:
    result = rows.copy()
    result["primary_split"] = pd.Series(
        pd.NA,
        index=result.index,
        dtype="string",
    )
    result["split_role"] = pd.Series(
        pd.NA,
        index=result.index,
        dtype="string",
    )
    result["split_interval_id"] = pd.Series(
        pd.NA,
        index=result.index,
        dtype="string",
    )

    time_column = contract.time_column
    for interval in contract.intervals:
        mask = (
            (result[time_column] >= interval.start_utc)
            & (result[time_column] < interval.end_utc)
        )
        if result.loc[mask, "split_interval_id"].notna().any():
            raise SplitContractError(
                "Temporal intervals overlap; a row received multiple roles."
            )
        result.loc[mask, "primary_split"] = interval.primary_split
        result.loc[mask, "split_role"] = interval.role
        result.loc[mask, "split_interval_id"] = interval.interval_id

    outside = result["split_interval_id"].isna()
    if outside.any():
        examples = ", ".join(
            result.loc[outside, contract.sample_id_column].head(5).tolist()
        )
        raise SplitContractError(
            "Rows fall outside the approved half-open corpus interval: "
            + examples
        )
    return result


def _validate_group_integrity(
    manifest: pd.DataFrame,
    contract: TemporalSplitContract,
) -> None:
    group_roles = manifest.groupby(
        contract.group_column,
        dropna=False,
    )["split_interval_id"].nunique()
    crossing = group_roles[group_roles != 1]
    if not crossing.empty:
        examples = ", ".join(crossing.index.astype(str).tolist()[:5])
        raise SplitContractError(
            "source_match_id groups cross temporal split roles: " + examples
        )


def assign_temporal_splits(
    frame: pd.DataFrame,
    contract: TemporalSplitContract = CURRENT_TEMPORAL_SPLIT,
) -> pd.DataFrame:
    """Assign every row to exactly one half-open UTC role.

    The returned manifest contains no target.  It is ordered by event time,
    source match, and sample ID and is safe to persist as a split assignment.
    """
    missing = sorted(set(_required_columns(contract)).difference(frame.columns))
    if missing:
        raise SplitContractError(
            "Supervised frame is missing split columns: " + ", ".join(missing)
        )

    sample_column = contract.sample_id_column
    group_column = contract.group_column
    time_column = contract.time_column
    target_column = contract.target_column
    rows = frame[
        [sample_column, group_column, time_column, target_column]
    ].copy()
    rows[sample_column] = _normalized_identifiers(
        rows[sample_column],
        column=sample_column,
    )
    rows[group_column] = _normalized_identifiers(
        rows[group_column],
        column=group_column,
    )
    if rows[sample_column].duplicated().any():
        duplicated = rows.loc[
            rows[sample_column].duplicated(keep=False),
            sample_column,
        ].iloc[0]
        raise SplitContractError(f"Duplicate sample_id in corpus: {duplicated}")

    rows[time_column] = pd.to_datetime(
        rows[time_column],
        utc=True,
        errors="coerce",
        format="mixed",
    )
    if rows[time_column].isna().any():
        raise SplitContractError(
            "match_start_utc must be a valid non-missing UTC timestamp."
        )
    rows[target_column] = rows[target_column].astype("boolean")
    if rows[target_column].isna().any():
        raise SplitContractError("radiant_win cannot be missing.")

    assigned = _assign_intervals(rows, contract)
    _validate_group_integrity(assigned, contract)
    manifest = assigned[
        [
            sample_column,
            group_column,
            time_column,
            "primary_split",
            "split_role",
            "split_interval_id",
        ]
    ].sort_values(
        [time_column, group_column, sample_column],
        kind="mergesort",
    )
    return manifest.reset_index(drop=True)


def split_manifest_fingerprint(
    manifest: pd.DataFrame,
    contract: TemporalSplitContract = CURRENT_TEMPORAL_SPLIT,
) -> str:
    """Hash the contract and sorted semantic split assignments."""
    required = {
        contract.sample_id_column,
        contract.group_column,
        contract.time_column,
        "primary_split",
        "split_role",
        "split_interval_id",
    }
    missing = sorted(required.difference(manifest.columns))
    if missing:
        raise SplitContractError(
            "Split manifest is missing fingerprint columns: "
            + ", ".join(missing)
        )
    ordered = manifest.sort_values(
        contract.sample_id_column,
        kind="mergesort",
    )
    assignments = [
        {
            "sample_id": str(row[contract.sample_id_column]),
            "source_match_id": str(row[contract.group_column]),
            "match_start_utc": _iso_utc(row[contract.time_column]),
            "primary_split": str(row["primary_split"]),
            "split_role": str(row["split_role"]),
            "split_interval_id": str(row["split_interval_id"]),
        }
        for row in ordered.to_dict(orient="records")
    ]
    payload = {
        "contract": split_contract_payload(contract),
        "assignments": assignments,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _interval_counts(
    assigned_with_target: pd.DataFrame,
    interval: SplitIntervalContract,
    contract: TemporalSplitContract,
) -> dict[str, object]:
    selected = assigned_with_target[
        assigned_with_target["split_interval_id"] == interval.interval_id
    ]
    rows = len(selected)
    matches = selected[contract.group_column].nunique()
    wins = int(selected[contract.target_column].sum())
    losses = rows - wins
    return {
        "interval_id": interval.interval_id,
        "primary_split": interval.primary_split,
        "role": interval.role,
        "start_utc": interval.start_utc.isoformat(),
        "end_utc": interval.end_utc.isoformat(),
        "rows": rows,
        "source_matches": int(matches),
        "radiant_wins": wins,
        "radiant_losses": losses,
        "radiant_win_rate": wins / rows if rows else None,
    }


def _assert_expected_counts(
    interval: SplitIntervalContract,
    observed: dict[str, object],
) -> None:
    comparisons = {
        "rows": interval.expected_rows,
        "source_matches": interval.expected_source_matches,
        "radiant_wins": interval.expected_radiant_wins,
        "radiant_losses": interval.expected_radiant_losses,
    }
    mismatches = [
        f"{name}: expected {expected}, observed {observed[name]}"
        for name, expected in comparisons.items()
        if expected is not None and observed[name] != expected
    ]
    if mismatches:
        raise SplitContractError(
            f"Split reconciliation failed for {interval.interval_id}: "
            + "; ".join(mismatches)
        )


def build_split_report(
    frame: pd.DataFrame,
    manifest: pd.DataFrame,
    fingerprint: str,
    contract: TemporalSplitContract = CURRENT_TEMPORAL_SPLIT,
    *,
    verify_expected: bool = True,
) -> dict[str, Any]:
    """Reconcile target and group counts without putting labels in the manifest."""
    targets = frame[
        [contract.sample_id_column, contract.target_column]
    ].copy()
    targets[contract.sample_id_column] = _normalized_identifiers(
        targets[contract.sample_id_column],
        column=contract.sample_id_column,
    )
    targets[contract.target_column] = targets[contract.target_column].astype(
        "boolean"
    )
    assigned = manifest.merge(
        targets,
        on=contract.sample_id_column,
        how="left",
        validate="one_to_one",
    )
    if assigned[contract.target_column].isna().any():
        raise SplitContractError("Split report could not reconcile target rows.")

    by_role = [
        _interval_counts(assigned, interval, contract)
        for interval in contract.intervals
    ]
    if verify_expected:
        for interval, observed in zip(
            contract.intervals,
            by_role,
            strict=True,
        ):
            _assert_expected_counts(interval, observed)

    primary: list[dict[str, object]] = []
    for primary_split in ("train", "validation", "test"):
        selected = assigned[assigned["primary_split"] == primary_split]
        rows = len(selected)
        wins = int(selected[contract.target_column].sum())
        primary.append(
            {
                "primary_split": primary_split,
                "rows": rows,
                "source_matches": int(
                    selected[contract.group_column].nunique()
                ),
                "radiant_wins": wins,
                "radiant_losses": rows - wins,
                "radiant_win_rate": wins / rows if rows else None,
            }
        )

    return {
        "split_contract_version": contract.contract_version,
        "corpus_id": contract.corpus_id,
        "split_manifest_fingerprint": fingerprint,
        "interval_semantics": contract.interval_semantics,
        "timezone": contract.timezone,
        "rows": len(manifest),
        "unique_samples": int(manifest[contract.sample_id_column].nunique()),
        "source_matches": int(manifest[contract.group_column].nunique()),
        "minimum_match_start_utc": _iso_utc(
            manifest[contract.time_column].min()
        ),
        "maximum_match_start_utc": _iso_utc(
            manifest[contract.time_column].max()
        ),
        "group_crossings": 0,
        "by_role": by_role,
        "by_primary_split": primary,
    }


def build_split_manifest(
    frame: pd.DataFrame,
    contract: TemporalSplitContract = CURRENT_TEMPORAL_SPLIT,
    *,
    verify_expected: bool = True,
) -> SplitManifestResult:
    """Assign, fingerprint, and reconcile one supervised working corpus."""
    manifest = assign_temporal_splits(frame, contract)
    fingerprint = split_manifest_fingerprint(manifest, contract)
    report = build_split_report(
        frame,
        manifest,
        fingerprint,
        contract,
        verify_expected=verify_expected,
    )
    return SplitManifestResult(
        manifest=manifest,
        fingerprint=fingerprint,
        report=report,
    )


def render_split_report_markdown(report: dict[str, Any]) -> str:
    """Render a compact human-readable split reconciliation report."""
    lines = [
        "# Draft AI Temporal Split Report",
        "",
        f"- Corpus: `{report['corpus_id']}`",
        f"- Split contract: `{report['split_contract_version']}`",
        f"- Manifest fingerprint: `{report['split_manifest_fingerprint']}`",
        f"- Rows: `{report['rows']}`",
        f"- Source matches: `{report['source_matches']}`",
        f"- Group crossings: `{report['group_crossings']}`",
        "",
        "| Role | Interval | Rows | Matches | Wins | Losses | Win rate |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in report["by_role"]:
        win_rate = row["radiant_win_rate"]
        formatted_rate = "n/a" if win_rate is None else f"{win_rate:.6%}"
        lines.append(
            "| {role} | `{start}` → `{end}` | {rows} | {matches} | "
            "{wins} | {losses} | {rate} |".format(
                role=row["role"],
                start=row["start_utc"],
                end=row["end_utc"],
                rows=row["rows"],
                matches=row["source_matches"],
                wins=row["radiant_wins"],
                losses=row["radiant_losses"],
                rate=formatted_rate,
            )
        )
    return "\n".join(lines) + "\n"


__all__ = [
    "SPLIT_ROLE_CALIBRATION",
    "SPLIT_ROLE_LOCKED_TEST",
    "SPLIT_ROLE_TRAIN",
    "SPLIT_ROLE_TUNING",
    "SplitContractError",
    "SplitManifestResult",
    "assign_temporal_splits",
    "build_split_manifest",
    "build_split_report",
    "canonical_json",
    "render_split_report_markdown",
    "split_contract_payload",
    "split_manifest_fingerprint",
]
