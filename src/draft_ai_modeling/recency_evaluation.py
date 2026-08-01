"""Paired development-only evaluation for Draft AI recency experiments.

This module compares already-generated prediction vectors.  It does not fit
estimators, calibrators, feature transformers, or acquisition components.
The comparison scope is deliberately fixed to the three recent development
quarters that precede the reserved calibration period.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score


RECENT_DEVELOPMENT_FOLDS = ("2025-Q1", "2025-Q2", "2025-Q3")
DEFAULT_BOOTSTRAP_RESAMPLES = 1_000
DEFAULT_BOOTSTRAP_RANDOM_STATE = 42
DEFAULT_CONFIDENCE_LEVEL = 0.95
MINIMUM_PATCH_GROUP_SIZE = 100

_PREDICTION_COLUMNS = (
    "sample_id",
    "source_match_id",
    "evaluation_id",
    "radiant_win",
    "radiant_win_probability",
)
_MISSING_PATCH = "__MISSING__"


class RecencyEvaluationError(ValueError):
    """Raised when paired predictions violate the development contract."""


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _validate_prediction_frame(
    frame: pd.DataFrame,
    *,
    context: str,
    required_columns: Sequence[str] = _PREDICTION_COLUMNS,
) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame):
        raise TypeError(f"{context} must be a pandas DataFrame.")
    if frame.columns.duplicated().any():
        raise RecencyEvaluationError(
            f"{context} contains duplicate column names."
        )
    missing = sorted(set(required_columns).difference(frame.columns))
    if missing:
        raise RecencyEvaluationError(
            f"{context} is missing required columns: " + ", ".join(missing)
        )
    if frame.empty:
        raise RecencyEvaluationError(f"{context} cannot be empty.")

    result = frame.loc[:, list(required_columns)].copy()
    for column in ("sample_id", "source_match_id", "evaluation_id"):
        if result[column].isna().any():
            raise RecencyEvaluationError(
                f"{context} contains missing {column} values."
            )
        result[column] = result[column].astype("string").str.strip()
        if result[column].eq("").any():
            raise RecencyEvaluationError(
                f"{context} contains empty {column} values."
            )

    if result["sample_id"].duplicated().any():
        duplicate = result.loc[
            result["sample_id"].duplicated(keep=False),
            "sample_id",
        ].iloc[0]
        raise RecencyEvaluationError(
            f"{context} contains duplicate sample_id: {duplicate}"
        )

    raw_targets = result["radiant_win"]
    if raw_targets.isna().any():
        raise RecencyEvaluationError(
            f"{context} contains missing radiant_win values."
        )
    numeric_targets = pd.to_numeric(raw_targets, errors="coerce")
    if (
        numeric_targets.isna().any()
        or not set(numeric_targets.unique()).issubset({0, 1})
    ):
        raise RecencyEvaluationError(
            f"{context} radiant_win values must be binary."
        )
    result["radiant_win"] = numeric_targets.astype("int8")

    probabilities = pd.to_numeric(
        result["radiant_win_probability"],
        errors="coerce",
    ).to_numpy(dtype=np.float64)
    if not np.isfinite(probabilities).all() or (
        (probabilities < 0) | (probabilities > 1)
    ).any():
        raise RecencyEvaluationError(
            f"{context} probabilities must be finite values in [0, 1]."
        )
    result["radiant_win_probability"] = probabilities
    return result


def _recent_development_rows(
    frame: pd.DataFrame,
    *,
    context: str,
) -> pd.DataFrame:
    validated = _validate_prediction_frame(frame, context=context)
    selected = validated[
        validated["evaluation_id"].isin(RECENT_DEVELOPMENT_FOLDS)
    ].copy()
    observed = set(selected["evaluation_id"].tolist())
    missing_folds = sorted(set(RECENT_DEVELOPMENT_FOLDS).difference(observed))
    if missing_folds:
        raise RecencyEvaluationError(
            f"{context} does not cover recent development folds: "
            + ", ".join(missing_folds)
        )

    group_folds = selected.groupby(
        "source_match_id",
        sort=False,
    )["evaluation_id"].nunique()
    crossing = group_folds[group_folds != 1]
    if not crossing.empty:
        raise RecencyEvaluationError(
            f"{context} source_match_id crosses evaluation folds: "
            + str(crossing.index[0])
        )
    return selected.sort_values("sample_id", kind="stable").reset_index(
        drop=True
    )


def _aligned_recent_predictions(
    reference: pd.DataFrame,
    candidate: pd.DataFrame,
) -> pd.DataFrame:
    reference_rows = _recent_development_rows(
        reference,
        context="Reference predictions",
    )
    candidate_rows = _recent_development_rows(
        candidate,
        context="Candidate predictions",
    )
    if reference_rows["sample_id"].tolist() != (
        candidate_rows["sample_id"].tolist()
    ):
        reference_samples = set(reference_rows["sample_id"])
        candidate_samples = set(candidate_rows["sample_id"])
        missing = sorted(reference_samples.difference(candidate_samples))
        extra = sorted(candidate_samples.difference(reference_samples))
        details = []
        if missing:
            details.append("missing candidate sample " + missing[0])
        if extra:
            details.append("unexpected candidate sample " + extra[0])
        raise RecencyEvaluationError(
            "Reference and candidate sample alignment differs"
            + (": " + "; ".join(details) if details else ".")
        )

    alignment_columns = (
        "source_match_id",
        "evaluation_id",
        "radiant_win",
    )
    for column in alignment_columns:
        left = reference_rows[column].to_numpy()
        right = candidate_rows[column].to_numpy()
        if not np.array_equal(left, right):
            mismatch = int(np.flatnonzero(left != right)[0])
            sample_id = reference_rows.iloc[mismatch]["sample_id"]
            raise RecencyEvaluationError(
                f"Reference and candidate {column} differ for {sample_id}."
            )

    paired = reference_rows.rename(
        columns={
            "radiant_win_probability": "reference_probability",
        }
    )
    paired["candidate_probability"] = candidate_rows[
        "radiant_win_probability"
    ].to_numpy(dtype=np.float64)
    return paired


def _per_row_losses(
    targets: np.ndarray,
    probabilities: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    clipped = np.clip(
        probabilities,
        np.finfo(np.float64).eps,
        1 - np.finfo(np.float64).eps,
    )
    log_losses = -(
        targets * np.log(clipped)
        + (1 - targets) * np.log1p(-clipped)
    )
    brier_losses = np.square(targets - probabilities)
    return log_losses, brier_losses


def _metric_interval(
    *,
    reference_losses: np.ndarray,
    candidate_losses: np.ndarray,
    bootstrap_differences: np.ndarray,
    confidence_level: float,
) -> dict[str, object]:
    tail = (1 - confidence_level) / 2
    point = float(np.mean(candidate_losses - reference_losses))
    return {
        "difference_direction": "candidate_minus_reference",
        "reference_point_estimate": float(reference_losses.mean()),
        "candidate_point_estimate": float(candidate_losses.mean()),
        "point_estimate": point,
        "lower": float(np.quantile(bootstrap_differences, tail)),
        "upper": float(
            np.quantile(bootstrap_differences, 1 - tail)
        ),
    }


def paired_recent_development_comparison(
    reference_predictions: pd.DataFrame,
    candidate_predictions: pd.DataFrame,
    *,
    n_resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES,
    random_state: int = DEFAULT_BOOTSTRAP_RANDOM_STATE,
    confidence_level: float = DEFAULT_CONFIDENCE_LEVEL,
) -> dict[str, Any]:
    """Compare aligned recent predictions with a paired group bootstrap.

    Each bootstrap replicate draws ``source_match_id`` values with replacement.
    Every game from each selected match is appended to the replicate, and a
    match drawn more than once contributes all of its games more than once.
    """

    if n_resamples < 1:
        raise RecencyEvaluationError(
            "Bootstrap resample count must be positive."
        )
    if not 0 < confidence_level < 1:
        raise RecencyEvaluationError(
            "Bootstrap confidence level must be in (0, 1)."
        )

    paired = _aligned_recent_predictions(
        reference_predictions,
        candidate_predictions,
    )
    targets = paired["radiant_win"].to_numpy(dtype=np.float64)
    reference_probabilities = paired[
        "reference_probability"
    ].to_numpy(dtype=np.float64)
    candidate_probabilities = paired[
        "candidate_probability"
    ].to_numpy(dtype=np.float64)
    reference_log, reference_brier = _per_row_losses(
        targets,
        reference_probabilities,
    )
    candidate_log, candidate_brier = _per_row_losses(
        targets,
        candidate_probabilities,
    )

    groups = paired["source_match_id"].astype(str).to_numpy(dtype=object)
    unique_groups = np.asarray(sorted(set(groups.tolist())), dtype=object)
    rows_by_group = {
        group: np.flatnonzero(groups == group)
        for group in unique_groups
    }
    rng = np.random.default_rng(random_state)
    log_differences = np.empty(n_resamples, dtype=np.float64)
    brier_differences = np.empty(n_resamples, dtype=np.float64)
    resampled_rows = np.empty(n_resamples, dtype=np.int64)

    for index in range(n_resamples):
        selected_groups = rng.choice(
            unique_groups,
            size=len(unique_groups),
            replace=True,
        )
        positions = np.concatenate(
            [rows_by_group[group] for group in selected_groups]
        )
        resampled_rows[index] = len(positions)
        log_differences[index] = float(
            np.mean(candidate_log[positions] - reference_log[positions])
        )
        brier_differences[index] = float(
            np.mean(
                candidate_brier[positions] - reference_brier[positions]
            )
        )

    fold_counts = {
        fold: int(
            (paired["evaluation_id"] == fold).sum()
        )
        for fold in RECENT_DEVELOPMENT_FOLDS
    }
    alignment_payload = paired[
        [
            "sample_id",
            "source_match_id",
            "evaluation_id",
            "radiant_win",
        ]
    ].to_dict(orient="records")
    return {
        "scope": "pooled_2025_q1_q3_development_only",
        "selection_use": "candidate_selection",
        "difference_direction": "candidate_minus_reference",
        "metrics": {
            "log_loss": _metric_interval(
                reference_losses=reference_log,
                candidate_losses=candidate_log,
                bootstrap_differences=log_differences,
                confidence_level=confidence_level,
            ),
            "brier_score": _metric_interval(
                reference_losses=reference_brier,
                candidate_losses=candidate_brier,
                bootstrap_differences=brier_differences,
                confidence_level=confidence_level,
            ),
        },
        "audit": {
            "rows": len(paired),
            "positive_rows": int(targets.sum()),
            "negative_rows": int(len(targets) - targets.sum()),
            "source_matches": len(unique_groups),
            "fold_rows": fold_counts,
            "bootstrap_method": "paired_source_match_percentile",
            "confidence_level": confidence_level,
            "random_state": random_state,
            "requested_resamples": n_resamples,
            "successful_resamples": n_resamples,
            "group_draws_per_resample": len(unique_groups),
            "total_group_draws": n_resamples * len(unique_groups),
            "minimum_rows_per_resample": int(resampled_rows.min()),
            "maximum_rows_per_resample": int(resampled_rows.max()),
            "group_multiplicity_preserved": True,
            "alignment_sha256": hashlib.sha256(
                _canonical_json(alignment_payload).encode("utf-8")
            ).hexdigest(),
        },
    }


def patch_group_descriptive_metrics(
    predictions: pd.DataFrame,
    *,
    minimum_group_size: int = MINIMUM_PATCH_GROUP_SIZE,
) -> dict[str, Any]:
    """Return non-selective patch diagnostics for one prediction vector."""

    if minimum_group_size < MINIMUM_PATCH_GROUP_SIZE:
        raise RecencyEvaluationError(
            "Patch reporting requires at least 100 rows per group."
        )
    required = (*_PREDICTION_COLUMNS, "patch")
    validated = _validate_prediction_frame(
        predictions,
        context="Patch predictions",
        required_columns=required,
    )
    patch_values = validated["patch"].astype("string").str.strip()
    patch_values = patch_values.fillna(_MISSING_PATCH).replace(
        "",
        _MISSING_PATCH,
    )
    validated["patch"] = patch_values

    records: list[dict[str, Any]] = []
    for patch, rows in validated.groupby("patch", sort=True, dropna=False):
        count = len(rows)
        reportable = count >= minimum_group_size
        targets = rows["radiant_win"].to_numpy(dtype=np.int8)
        probabilities = rows["radiant_win_probability"].to_numpy(
            dtype=np.float64
        )
        metrics: dict[str, float | None] | None = None
        if reportable:
            metrics = {
                "log_loss": float(
                    log_loss(targets, probabilities, labels=[0, 1])
                ),
                "brier_score": float(
                    brier_score_loss(targets, probabilities)
                ),
                "roc_auc": (
                    float(roc_auc_score(targets, probabilities))
                    if len(np.unique(targets)) == 2
                    else None
                ),
                "observed_win_rate": float(targets.mean()),
                "mean_probability": float(probabilities.mean()),
            }
        records.append(
            {
                "patch": str(patch),
                "rows": count,
                "source_matches": int(
                    rows["source_match_id"].nunique()
                ),
                "reportable": reportable,
                "used_for_selection": False,
                "metrics": metrics,
            }
        )

    return {
        "kind": "patch_group_descriptive_metrics",
        "selection_use": "descriptive_only",
        "used_for_selection": False,
        "minimum_group_size": minimum_group_size,
        "rows": len(validated),
        "groups": len(records),
        "reported_groups": sum(
            bool(record["reportable"]) for record in records
        ),
        "suppressed_groups": sum(
            not bool(record["reportable"]) for record in records
        ),
        "patches": records,
    }


__all__ = [
    "DEFAULT_BOOTSTRAP_RANDOM_STATE",
    "DEFAULT_BOOTSTRAP_RESAMPLES",
    "DEFAULT_CONFIDENCE_LEVEL",
    "MINIMUM_PATCH_GROUP_SIZE",
    "RECENT_DEVELOPMENT_FOLDS",
    "RecencyEvaluationError",
    "paired_recent_development_comparison",
    "patch_group_descriptive_metrics",
]
