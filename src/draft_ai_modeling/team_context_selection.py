"""Deterministic gates for the bounded M4B.5 team-context experiment.

This module consumes aligned, already-generated probabilities.  It cannot fit
models, construct team ratings, or read the locked test period.  Development
selection uses exactly 2024-Q1 through 2025-Q3; Q4 readiness is evaluated by a
separate function with a separate exact-fold contract.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, log_loss

from .calibration import (
    CalibrationError,
    paired_method_bootstrap_comparison,
)


DEVELOPMENT_FOLDS = (
    "2024-Q1",
    "2024-Q2",
    "2024-Q3",
    "2024-Q4",
    "2025-Q1",
    "2025-Q2",
    "2025-Q3",
)
RECENT_DEVELOPMENT_FOLDS = (
    "2025-Q1",
    "2025-Q2",
    "2025-Q3",
)
Q4_READINESS_FOLD = "2025-Q4"
DEFAULT_BOOTSTRAP_RESAMPLES = 1_000
DEFAULT_BOOTSTRAP_RANDOM_STATE = 42
DEFAULT_CONFIDENCE_LEVEL = 0.95
MINIMUM_RECENT_LOG_LOSS_IMPROVEMENT = 0.002
MAXIMUM_SINGLE_FOLD_LOG_LOSS_REGRESSION = 0.01

_REQUIRED_COLUMNS = (
    "evaluation_id",
    "sample_id",
    "source_match_id",
    "radiant_win",
    "joint_probability",
    "team_only_probability",
    "frozen_b1_probability",
    "canonical_b0_probability",
)
_PROBABILITY_COLUMNS = (
    "joint_probability",
    "team_only_probability",
    "frozen_b1_probability",
    "canonical_b0_probability",
)
_REFERENCE_COLUMNS = {
    "canonical_b0": "canonical_b0_probability",
    "frozen_b1": "frozen_b1_probability",
    "team_only": "team_only_probability",
}
_SELECTION_METRICS = ("log_loss", "brier_score")


class TeamContextSelectionError(ValueError):
    """Raised when M4B.5 prediction evidence violates its frozen contract."""


def _validate_policy_parameters(
    *,
    n_resamples: int,
    random_state: int,
    confidence_level: float,
) -> None:
    if isinstance(n_resamples, bool) or not isinstance(
        n_resamples, (int, np.integer)
    ):
        raise TeamContextSelectionError(
            "Bootstrap resamples must be a positive integer."
        )
    if n_resamples < 1:
        raise TeamContextSelectionError(
            "Bootstrap resamples must be a positive integer."
        )
    if isinstance(random_state, bool) or not isinstance(
        random_state, (int, np.integer)
    ):
        raise TeamContextSelectionError(
            "Bootstrap random state must be an integer."
        )
    if not np.isfinite(confidence_level) or not 0 < confidence_level < 1:
        raise TeamContextSelectionError(
            "Bootstrap confidence level must be in (0, 1)."
        )


def _validated_predictions(
    predictions: pd.DataFrame,
    *,
    expected_folds: tuple[str, ...],
    context: str,
) -> pd.DataFrame:
    if not isinstance(predictions, pd.DataFrame):
        raise TypeError(f"{context} predictions must be a DataFrame.")
    if predictions.columns.duplicated().any():
        raise TeamContextSelectionError(
            f"{context} predictions contain duplicate column names."
        )
    missing = sorted(set(_REQUIRED_COLUMNS).difference(predictions.columns))
    if missing:
        raise TeamContextSelectionError(
            f"{context} predictions are missing columns: "
            + ", ".join(missing)
        )
    if predictions.empty:
        raise TeamContextSelectionError(
            f"{context} predictions cannot be empty."
        )

    result = predictions.loc[:, list(_REQUIRED_COLUMNS)].copy()
    for column in ("evaluation_id", "sample_id", "source_match_id"):
        if result[column].isna().any():
            raise TeamContextSelectionError(
                f"{context} predictions contain missing {column} values."
            )
        result[column] = result[column].astype("string").str.strip()
        if result[column].eq("").any():
            raise TeamContextSelectionError(
                f"{context} predictions contain empty {column} values."
            )

    targets = pd.to_numeric(result["radiant_win"], errors="coerce")
    if targets.isna().any() or not set(targets.unique()).issubset({0, 1}):
        raise TeamContextSelectionError("radiant_win values must be binary.")
    result["radiant_win"] = targets.astype("int8")

    for column in _PROBABILITY_COLUMNS:
        values = pd.to_numeric(result[column], errors="coerce").to_numpy(
            dtype=np.float64
        )
        if not np.isfinite(values).all() or (
            (values < 0) | (values > 1)
        ).any():
            raise TeamContextSelectionError(
                f"{column} must contain finite probabilities in [0, 1]."
            )
        result[column] = values

    if result["sample_id"].duplicated().any():
        duplicate = result.loc[
            result["sample_id"].duplicated(keep=False),
            "sample_id",
        ].iloc[0]
        raise TeamContextSelectionError(
            f"{context} predictions contain duplicate sample_id: {duplicate}"
        )

    observed_folds = set(result["evaluation_id"].tolist())
    if observed_folds != set(expected_folds):
        expected = ", ".join(expected_folds)
        raise TeamContextSelectionError(
            f"{context} predictions must contain exactly these folds: "
            f"{expected}."
        )

    crossing = result.groupby(
        "source_match_id",
        sort=False,
    )["evaluation_id"].nunique()
    crossing = crossing[crossing != 1]
    if not crossing.empty:
        raise TeamContextSelectionError(
            f"{context} has a source match crossing folds: "
            + str(crossing.index[0])
        )

    for fold in expected_folds:
        fold_targets = result.loc[
            result["evaluation_id"] == fold,
            "radiant_win",
        ]
        if set(fold_targets.unique()) != {0, 1}:
            raise TeamContextSelectionError(
                f"{context} fold {fold} must contain both target classes."
            )

    return result.sort_values(
        ["evaluation_id", "sample_id"],
        kind="stable",
    ).reset_index(drop=True)


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
        "joint": _probability_metrics(
            targets,
            rows["joint_probability"].to_numpy(dtype=np.float64),
        ),
        "team_only": _probability_metrics(
            targets,
            rows["team_only_probability"].to_numpy(dtype=np.float64),
        ),
        "frozen_b1": _probability_metrics(
            targets,
            rows["frozen_b1_probability"].to_numpy(dtype=np.float64),
        ),
        "canonical_b0": _probability_metrics(
            targets,
            rows["canonical_b0_probability"].to_numpy(dtype=np.float64),
        ),
    }
    differences = {
        f"joint_minus_{reference}": {
            metric: models["joint"][metric] - models[reference][metric]
            for metric in _SELECTION_METRICS
        }
        for reference in _REFERENCE_COLUMNS
    }
    return {
        "rows": len(rows),
        "source_matches": int(rows["source_match_id"].nunique()),
        **models,
        **differences,
    }


def _paired_frame(
    rows: pd.DataFrame,
    probability_column: str,
) -> pd.DataFrame:
    result = rows[
        ["sample_id", "source_match_id", "radiant_win"]
    ].copy()
    result["radiant_win_probability"] = rows[
        probability_column
    ].to_numpy(dtype=np.float64)
    return result


def _paired_comparison(
    rows: pd.DataFrame,
    *,
    reference_column: str,
    n_resamples: int,
    random_state: int,
    confidence_level: float,
) -> dict[str, Any]:
    try:
        return paired_method_bootstrap_comparison(
            _paired_frame(rows, reference_column),
            _paired_frame(rows, "joint_probability"),
            n_resamples=n_resamples,
            random_state=random_state,
            confidence_level=confidence_level,
        )
    except CalibrationError as error:
        raise TeamContextSelectionError(
            "Team-context paired comparison failed: " + str(error)
        ) from error


def _paired_upper_gates(
    comparison: dict[str, Any],
) -> dict[str, bool]:
    return {
        f"{metric}_upper_below_zero": bool(
            float(comparison["metrics"][metric]["upper"]) < 0
        )
        for metric in _SELECTION_METRICS
    }


def _point_and_upper_gates(
    comparison: dict[str, Any],
) -> dict[str, bool]:
    result: dict[str, bool] = {}
    for metric in _SELECTION_METRICS:
        evidence = comparison["metrics"][metric]
        result[f"{metric}_point_below_zero"] = bool(
            float(evidence["point_estimate"]) < 0
        )
        result[f"{metric}_upper_below_zero"] = bool(
            float(evidence["upper"]) < 0
        )
    return result


def evaluate_team_context_development(
    predictions: pd.DataFrame,
    *,
    n_resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES,
    random_state: int = DEFAULT_BOOTSTRAP_RANDOM_STATE,
    confidence_level: float = DEFAULT_CONFIDENCE_LEVEL,
    minimum_recent_log_loss_improvement: float = (
        MINIMUM_RECENT_LOG_LOSS_IMPROVEMENT
    ),
    maximum_single_fold_log_loss_regression: float = (
        MAXIMUM_SINGLE_FOLD_LOG_LOSS_REGRESSION
    ),
) -> dict[str, Any]:
    """Apply the fixed seven-fold M4B.5 development and attribution gates."""

    _validate_policy_parameters(
        n_resamples=n_resamples,
        random_state=random_state,
        confidence_level=confidence_level,
    )
    if (
        not np.isfinite(minimum_recent_log_loss_improvement)
        or minimum_recent_log_loss_improvement < 0
    ):
        raise TeamContextSelectionError(
            "Minimum recent log-loss improvement cannot be negative."
        )
    if (
        not np.isfinite(maximum_single_fold_log_loss_regression)
        or maximum_single_fold_log_loss_regression < 0
    ):
        raise TeamContextSelectionError(
            "Maximum single-fold log-loss regression cannot be negative."
        )

    rows = _validated_predictions(
        predictions,
        expected_folds=DEVELOPMENT_FOLDS,
        context="Development",
    )
    folds = {
        fold: _scope_metrics(rows[rows["evaluation_id"] == fold])
        for fold in DEVELOPMENT_FOLDS
    }
    recent_rows = rows[
        rows["evaluation_id"].isin(RECENT_DEVELOPMENT_FOLDS)
    ]
    recent_pooled = _scope_metrics(recent_rows)

    comparisons = {
        "recent_joint_vs_frozen_b1": _paired_comparison(
            recent_rows,
            reference_column="frozen_b1_probability",
            n_resamples=n_resamples,
            random_state=random_state,
            confidence_level=confidence_level,
        ),
        "recent_joint_vs_team_only": _paired_comparison(
            recent_rows,
            reference_column="team_only_probability",
            n_resamples=n_resamples,
            random_state=random_state,
            confidence_level=confidence_level,
        ),
    }

    recent_per_fold = {
        fold: {
            "joint_log_loss_below_frozen_b1": bool(
                folds[fold]["joint"]["log_loss"]
                < folds[fold]["frozen_b1"]["log_loss"]
            ),
            "joint_brier_below_frozen_b1": bool(
                folds[fold]["joint"]["brier_score"]
                < folds[fold]["frozen_b1"]["brier_score"]
            ),
            "joint_log_loss_below_canonical_b0": bool(
                folds[fold]["joint"]["log_loss"]
                < folds[fold]["canonical_b0"]["log_loss"]
            ),
            "joint_brier_below_canonical_b0": bool(
                folds[fold]["joint"]["brier_score"]
                < folds[fold]["canonical_b0"]["brier_score"]
            ),
        }
        for fold in RECENT_DEVELOPMENT_FOLDS
    }
    pooled_recent = {
        "minimum_log_loss_improvement_vs_frozen_b1": bool(
            (
                recent_pooled["frozen_b1"]["log_loss"]
                - recent_pooled["joint"]["log_loss"]
            )
            >= minimum_recent_log_loss_improvement
        ),
        "joint_brier_below_frozen_b1": bool(
            recent_pooled["joint"]["brier_score"]
            < recent_pooled["frozen_b1"]["brier_score"]
        ),
    }
    paired_frozen_b1 = _paired_upper_gates(
        comparisons["recent_joint_vs_frozen_b1"]
    )

    joint_fold_log_losses = [
        folds[fold]["joint"]["log_loss"] for fold in DEVELOPMENT_FOLDS
    ]
    b1_fold_log_losses = [
        folds[fold]["frozen_b1"]["log_loss"]
        for fold in DEVELOPMENT_FOLDS
    ]
    fold_regressions = {
        fold: (
            folds[fold]["joint"]["log_loss"]
            - folds[fold]["frozen_b1"]["log_loss"]
        )
        for fold in DEVELOPMENT_FOLDS
    }
    seven_fold = {
        "mean_joint_log_loss_no_worse_than_frozen_b1": bool(
            float(np.mean(joint_fold_log_losses))
            <= float(np.mean(b1_fold_log_losses))
        ),
        "maximum_single_fold_log_loss_regression_within_limit": bool(
            max(fold_regressions.values())
            <= maximum_single_fold_log_loss_regression
        ),
    }

    product_attribution = {
        "pooled_joint_log_loss_below_team_only": bool(
            recent_pooled["joint"]["log_loss"]
            < recent_pooled["team_only"]["log_loss"]
        ),
        "pooled_joint_brier_below_team_only": bool(
            recent_pooled["joint"]["brier_score"]
            < recent_pooled["team_only"]["brier_score"]
        ),
        **_paired_upper_gates(
            comparisons["recent_joint_vs_team_only"]
        ),
    }

    gates: dict[str, Any] = {
        "recent_per_fold": recent_per_fold,
        "all_recent_per_fold": all(
            passed
            for fold_gates in recent_per_fold.values()
            for passed in fold_gates.values()
        ),
        "pooled_recent": pooled_recent,
        "all_pooled_recent": all(pooled_recent.values()),
        "paired_frozen_b1": paired_frozen_b1,
        "all_paired_frozen_b1": all(paired_frozen_b1.values()),
        "seven_fold": seven_fold,
        "all_seven_fold": all(seven_fold.values()),
        "product_attribution": product_attribution,
        "all_product_attribution": all(product_attribution.values()),
    }
    qualified = bool(
        gates["all_recent_per_fold"]
        and gates["all_pooled_recent"]
        and gates["all_paired_frozen_b1"]
        and gates["all_seven_fold"]
        and gates["all_product_attribution"]
    )

    return {
        "decision_scope": "development_only_2024_q1_2025_q3",
        "qualified": qualified,
        "passed": qualified,
        "metrics": {
            "folds": folds,
            "recent_pooled": recent_pooled,
            "seven_fold_mean_log_loss": {
                "joint": float(np.mean(joint_fold_log_losses)),
                "frozen_b1": float(np.mean(b1_fold_log_losses)),
                "joint_minus_frozen_b1": float(
                    np.mean(joint_fold_log_losses)
                    - np.mean(b1_fold_log_losses)
                ),
            },
            "single_fold_log_loss_regressions_vs_frozen_b1": (
                fold_regressions
            ),
            "maximum_single_fold_log_loss_regression_vs_frozen_b1": (
                max(fold_regressions.values())
            ),
        },
        "comparisons": comparisons,
        "gates": gates,
        "policy": {
            "development_folds": list(DEVELOPMENT_FOLDS),
            "recent_selection_folds": list(RECENT_DEVELOPMENT_FOLDS),
            "minimum_recent_log_loss_improvement_vs_frozen_b1": (
                minimum_recent_log_loss_improvement
            ),
            "maximum_single_fold_log_loss_regression_vs_frozen_b1": (
                maximum_single_fold_log_loss_regression
            ),
            "paired_difference_direction": "joint_minus_reference",
            "paired_gate": (
                "upper confidence bound below zero for log loss and Brier"
            ),
            "product_attribution_reference": "team_only",
        },
        "audit": {
            "rows": len(rows),
            "source_matches": int(rows["source_match_id"].nunique()),
            "fold_rows": {
                fold: int((rows["evaluation_id"] == fold).sum())
                for fold in DEVELOPMENT_FOLDS
            },
            "bootstrap_resamples_per_comparison": int(n_resamples),
            "bootstrap_random_state": int(random_state),
            "bootstrap_confidence_level": float(confidence_level),
            "q4_rows_used": 0,
            "locked_test_rows_used": 0,
        },
    }


def evaluate_team_context_q4_readiness(
    predictions: pd.DataFrame,
    *,
    n_resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES,
    random_state: int = DEFAULT_BOOTSTRAP_RANDOM_STATE,
    confidence_level: float = DEFAULT_CONFIDENCE_LEVEL,
) -> dict[str, Any]:
    """Require clear Q4 superiority over B0, B1, and team-only references."""

    _validate_policy_parameters(
        n_resamples=n_resamples,
        random_state=random_state,
        confidence_level=confidence_level,
    )
    rows = _validated_predictions(
        predictions,
        expected_folds=(Q4_READINESS_FOLD,),
        context="Q4 readiness",
    )
    metrics = _scope_metrics(rows)
    comparisons = {
        f"joint_vs_{reference}": _paired_comparison(
            rows,
            reference_column=column,
            n_resamples=n_resamples,
            random_state=random_state,
            confidence_level=confidence_level,
        )
        for reference, column in _REFERENCE_COLUMNS.items()
    }
    gates = {
        reference: _point_and_upper_gates(
            comparisons[f"joint_vs_{reference}"]
        )
        for reference in _REFERENCE_COLUMNS
    }
    gates["all"] = all(
        passed
        for reference in _REFERENCE_COLUMNS
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
            "evaluation_fold": Q4_READINESS_FOLD,
            "references": list(_REFERENCE_COLUMNS),
            "required_metrics": list(_SELECTION_METRICS),
            "point_gate": "candidate minus reference below zero",
            "paired_gate": (
                "upper confidence bound below zero for log loss and Brier"
            ),
        },
        "audit": {
            "rows": len(rows),
            "source_matches": int(rows["source_match_id"].nunique()),
            "bootstrap_resamples_per_comparison": int(n_resamples),
            "bootstrap_random_state": int(random_state),
            "bootstrap_confidence_level": float(confidence_level),
            "locked_test_rows_used": 0,
        },
    }


__all__ = [
    "DEFAULT_BOOTSTRAP_RANDOM_STATE",
    "DEFAULT_BOOTSTRAP_RESAMPLES",
    "DEFAULT_CONFIDENCE_LEVEL",
    "DEVELOPMENT_FOLDS",
    "MAXIMUM_SINGLE_FOLD_LOG_LOSS_REGRESSION",
    "MINIMUM_RECENT_LOG_LOSS_IMPROVEMENT",
    "Q4_READINESS_FOLD",
    "RECENT_DEVELOPMENT_FOLDS",
    "TeamContextSelectionError",
    "evaluate_team_context_development",
    "evaluate_team_context_q4_readiness",
]
