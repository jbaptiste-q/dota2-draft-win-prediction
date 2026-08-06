"""Deterministic ranking and readiness gates for the GBDT baseline experiment.

This module consumes aligned, already-generated probabilities. It cannot fit
models or read the sealed 2026-Q1 window. The fold-based selection stage
ranks pre-registered candidates using only 2025-Q1 through 2025-Q3; the Q4
readiness gate is a separate function with a separate exact-fold contract,
mirroring the M4B.5 development/Q4 split.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, log_loss

from .calibration import CalibrationError, paired_method_bootstrap_comparison
from .gbdt_config import GbdtBaselineConfig


_REQUIRED_FOLD_COLUMNS = (
    "candidate_id",
    "fold_id",
    "sample_id",
    "source_match_id",
    "radiant_win",
    "candidate_probability",
    "frozen_b1_probability",
    "canonical_b0_probability",
)
_REQUIRED_Q4_COLUMNS = (
    "sample_id",
    "source_match_id",
    "radiant_win",
    "candidate_probability",
    "frozen_b1_probability",
    "canonical_b0_probability",
)
_PROBABILITY_COLUMNS = (
    "candidate_probability",
    "frozen_b1_probability",
    "canonical_b0_probability",
)
_REFERENCE_COLUMNS = {
    "canonical_b0": "canonical_b0_probability",
    "frozen_b1": "frozen_b1_probability",
}
_SELECTION_METRICS = ("log_loss", "brier_score")


class GbdtSelectionError(ValueError):
    """Raised when GBDT prediction evidence violates its frozen contract."""


def _validated_frame(
    frame: pd.DataFrame,
    *,
    required_columns: tuple[str, ...],
    context: str,
) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame):
        raise TypeError(f"{context} must be a pandas DataFrame.")
    if frame.columns.duplicated().any():
        raise GbdtSelectionError(f"{context} contains duplicate column names.")
    missing = sorted(set(required_columns).difference(frame.columns))
    if missing:
        raise GbdtSelectionError(
            f"{context} is missing columns: " + ", ".join(missing)
        )
    if frame.empty:
        raise GbdtSelectionError(f"{context} cannot be empty.")

    result = frame.loc[:, list(required_columns)].copy()
    for column in ("sample_id", "source_match_id"):
        if result[column].isna().any():
            raise GbdtSelectionError(f"{context} contains missing {column}.")
        result[column] = result[column].astype("string").str.strip()
        if result[column].eq("").any():
            raise GbdtSelectionError(f"{context} contains empty {column}.")
    if "candidate_id" in result.columns:
        result["candidate_id"] = result["candidate_id"].astype("string")
    if "fold_id" in result.columns:
        result["fold_id"] = result["fold_id"].astype("string")

    targets = pd.to_numeric(result["radiant_win"], errors="coerce")
    if targets.isna().any() or not set(targets.unique()).issubset({0, 1}):
        raise GbdtSelectionError(f"{context} radiant_win values must be binary.")
    result["radiant_win"] = targets.astype("int8")

    for column in _PROBABILITY_COLUMNS:
        values = pd.to_numeric(result[column], errors="coerce").to_numpy(
            dtype=np.float64
        )
        if not np.isfinite(values).all() or ((values < 0) | (values > 1)).any():
            raise GbdtSelectionError(
                f"{column} must contain finite probabilities in [0, 1]."
            )
        result[column] = values
    return result


def _probability_metrics(
    targets: np.ndarray,
    probabilities: np.ndarray,
) -> dict[str, float]:
    return {
        "log_loss": float(log_loss(targets, probabilities, labels=[0, 1])),
        "brier_score": float(brier_score_loss(targets, probabilities)),
    }


def _scope_metrics(rows: pd.DataFrame) -> dict[str, Any]:
    targets = rows["radiant_win"].to_numpy(dtype=np.int8)
    models = {
        "candidate": _probability_metrics(
            targets, rows["candidate_probability"].to_numpy(dtype=np.float64)
        ),
        "frozen_b1": _probability_metrics(
            targets, rows["frozen_b1_probability"].to_numpy(dtype=np.float64)
        ),
        "canonical_b0": _probability_metrics(
            targets, rows["canonical_b0_probability"].to_numpy(dtype=np.float64)
        ),
    }
    differences = {
        f"candidate_minus_{reference}": {
            metric: models["candidate"][metric] - models[reference][metric]
            for metric in _SELECTION_METRICS
        }
        for reference in ("frozen_b1", "canonical_b0")
    }
    return {
        "rows": len(rows),
        "source_matches": int(rows["source_match_id"].nunique()),
        **models,
        **differences,
    }


def evaluate_gbdt_selection(
    fold_predictions: pd.DataFrame,
    *,
    config: GbdtBaselineConfig,
) -> dict[str, Any]:
    """Rank the pre-registered candidates without ever reading Q4 or later."""

    if config.selection.ranking_metric != "pooled_log_loss_recent_folds":
        raise GbdtSelectionError(
            "This module only implements the pooled_log_loss_recent_folds "
            "ranking metric declared in the pre-registration."
        )
    if config.selection.ranking_direction != "minimize":
        raise GbdtSelectionError(
            "This module only implements a minimize ranking direction."
        )
    if config.selection.ranking_scope != "recent_fold_ids_only":
        raise GbdtSelectionError(
            "This module only implements the recent_fold_ids_only ranking "
            "scope."
        )
    if config.selection.tie_break != "lowest_candidate_id_lexicographic":
        raise GbdtSelectionError(
            "This module only implements the lowest_candidate_id_lexicographic "
            "tie-break."
        )

    rows = _validated_frame(
        fold_predictions,
        required_columns=_REQUIRED_FOLD_COLUMNS,
        context="GBDT fold selection",
    )
    expected_candidate_ids = {c.candidate_id for c in config.candidates}
    expected_fold_ids = {fold.fold_id for fold in config.folds}
    if set(rows["candidate_id"].tolist()) != expected_candidate_ids:
        raise GbdtSelectionError(
            "GBDT fold selection predictions must cover exactly the "
            "pre-registered candidate grid."
        )
    if set(rows["fold_id"].tolist()) != expected_fold_ids:
        raise GbdtSelectionError(
            "GBDT fold selection predictions must cover exactly the "
            "pre-registered folds."
        )
    duplicated = rows.duplicated(["candidate_id", "sample_id"], keep=False)
    if duplicated.any():
        raise GbdtSelectionError(
            "GBDT fold selection predictions contain a duplicate "
            "(candidate_id, sample_id) pair."
        )
    crossing = rows.groupby("source_match_id", sort=False)["fold_id"].nunique()
    if (crossing != 1).any():
        raise GbdtSelectionError(
            "A source match crosses fold boundaries in the fold predictions."
        )

    recent_fold_ids = set(config.selection.recent_fold_ids)
    per_candidate_folds: dict[str, dict[str, Any]] = {}
    per_candidate_recent_pooled: dict[str, Any] = {}
    for candidate in config.candidates:
        candidate_rows = rows[rows["candidate_id"] == candidate.candidate_id]
        per_candidate_folds[candidate.candidate_id] = {
            fold_id: _scope_metrics(
                candidate_rows[candidate_rows["fold_id"] == fold_id]
            )
            for fold_id in sorted(expected_fold_ids)
        }
        recent_rows = candidate_rows[
            candidate_rows["fold_id"].isin(recent_fold_ids)
        ]
        per_candidate_recent_pooled[candidate.candidate_id] = _scope_metrics(
            recent_rows
        )

    ranking = sorted(
        config.candidates,
        key=lambda candidate: (
            per_candidate_recent_pooled[candidate.candidate_id]["candidate"][
                "log_loss"
            ],
            candidate.candidate_id,
        ),
    )
    selected_candidate_id = ranking[0].candidate_id

    return {
        "decision_scope": "selection_recent_folds_only",
        "selected_candidate_id": selected_candidate_id,
        "ranking": [
            {
                "candidate_id": candidate.candidate_id,
                "num_leaves": candidate.num_leaves,
                "learning_rate": candidate.learning_rate,
                "recent_pooled_log_loss": per_candidate_recent_pooled[
                    candidate.candidate_id
                ]["candidate"]["log_loss"],
            }
            for candidate in ranking
        ],
        "metrics": {
            "folds": per_candidate_folds,
            "recent_pooled": per_candidate_recent_pooled,
        },
        "policy": {
            "recent_fold_ids": list(config.selection.recent_fold_ids),
            "ranking_metric": config.selection.ranking_metric,
            "ranking_direction": config.selection.ranking_direction,
            "ranking_scope": config.selection.ranking_scope,
            "tie_break": config.selection.tie_break,
        },
        "audit": {
            "rows": len(rows),
            "candidates": len(config.candidates),
            "folds": len(config.folds),
            "q4_rows_used": 0,
            "locked_test_rows_used": 0,
        },
    }


def evaluate_gbdt_q4_readiness(
    q4_predictions: pd.DataFrame,
    *,
    config: GbdtBaselineConfig,
) -> dict[str, Any]:
    """Apply the pre-registered paired-bootstrap Q4 readiness gate."""

    bootstrap = config.evaluation
    rows = _validated_frame(
        q4_predictions,
        required_columns=_REQUIRED_Q4_COLUMNS,
        context="GBDT Q4 readiness",
    )
    unknown_references = set(config.q4_readiness.references).difference(
        _REFERENCE_COLUMNS
    )
    if unknown_references:
        raise GbdtSelectionError(
            "GBDT Q4 readiness references an unsupported comparison: "
            + ", ".join(sorted(unknown_references))
        )
    unknown_metrics = set(config.q4_readiness.metrics).difference(
        _SELECTION_METRICS
    )
    if unknown_metrics:
        raise GbdtSelectionError(
            "GBDT Q4 readiness declares an unsupported metric: "
            + ", ".join(sorted(unknown_metrics))
        )

    metrics = _scope_metrics(rows)
    comparisons: dict[str, Any] = {}
    for reference in config.q4_readiness.references:
        column = _REFERENCE_COLUMNS[reference]
        reference_frame = rows[
            ["sample_id", "source_match_id", "radiant_win"]
        ].copy()
        reference_frame["radiant_win_probability"] = rows[column]
        candidate_frame = rows[
            ["sample_id", "source_match_id", "radiant_win"]
        ].copy()
        candidate_frame["radiant_win_probability"] = rows[
            "candidate_probability"
        ]
        try:
            comparisons[reference] = paired_method_bootstrap_comparison(
                reference_frame,
                candidate_frame,
                n_resamples=bootstrap.bootstrap_replicates,
                random_state=bootstrap.bootstrap_random_seed,
                confidence_level=bootstrap.bootstrap_confidence_level,
            )
        except CalibrationError as error:
            raise GbdtSelectionError(
                f"GBDT Q4 paired comparison against {reference} failed: "
                + str(error)
            ) from error

    gates: dict[str, Any] = {}
    for reference in config.q4_readiness.references:
        reference_gates: dict[str, bool] = {}
        for metric in config.q4_readiness.metrics:
            evidence = comparisons[reference]["metrics"][metric]
            reference_gates[f"{metric}_point_below_threshold"] = bool(
                float(evidence["point_estimate"])
                < config.q4_readiness.require_point_below
            )
            reference_gates[f"{metric}_upper_below_threshold"] = bool(
                float(evidence["upper"])
                < config.q4_readiness.require_upper_bound_below
            )
        gates[reference] = reference_gates
    gates["all"] = all(
        passed
        for reference in config.q4_readiness.references
        for passed in gates[reference].values()
    )
    passed = bool(gates["all"])

    return {
        "decision_scope": "readiness_2025_q4_only",
        "qualified": passed,
        "passed": passed,
        "metrics": metrics,
        "comparisons": comparisons,
        "gates": gates,
        "policy": {
            "references": list(config.q4_readiness.references),
            "required_metrics": list(config.q4_readiness.metrics),
            "require_point_below": config.q4_readiness.require_point_below,
            "require_upper_bound_below": (
                config.q4_readiness.require_upper_bound_below
            ),
        },
        "audit": {
            "rows": len(rows),
            "source_matches": int(rows["source_match_id"].nunique()),
            "bootstrap_resamples_per_comparison": bootstrap.bootstrap_replicates,
            "bootstrap_random_state": bootstrap.bootstrap_random_seed,
            "bootstrap_confidence_level": bootstrap.bootstrap_confidence_level,
            "locked_test_rows_used": 0,
        },
    }


__all__ = [
    "GbdtSelectionError",
    "evaluate_gbdt_q4_readiness",
    "evaluate_gbdt_selection",
]
