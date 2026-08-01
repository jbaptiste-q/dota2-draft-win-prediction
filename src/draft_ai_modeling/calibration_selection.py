"""Fixed probability-calibration comparison and selection for M4B.3."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .calibration import (
    CALIBRATION_METHODS,
    CalibrationError,
    paired_method_bootstrap_comparison,
)
from .evaluation import evaluate_probabilities


MINIMUM_LOG_LOSS_IMPROVEMENT = 0.002
MAXIMUM_ISOTONIC_FOLD_REGRESSION = 0.005


def method_prediction_frame(
    predictions: pd.DataFrame,
    method: str,
) -> pd.DataFrame:
    """Return one aligned method vector in the paired-comparison contract."""

    if method not in CALIBRATION_METHODS:
        raise CalibrationError(f"Unknown calibration method: {method!r}.")
    required = {
        "calibration_method",
        "calibration_fold",
        "sample_id",
        "source_match_id",
        "radiant_win",
        "radiant_win_probability",
    }
    missing = sorted(required.difference(predictions.columns))
    if missing:
        raise CalibrationError(
            "Calibration predictions are missing columns: "
            + ", ".join(missing)
        )
    selected = predictions[
        predictions["calibration_method"] == method
    ].copy()
    if selected.empty or selected["sample_id"].duplicated().any():
        raise CalibrationError(
            f"{method} predictions must cover each sample exactly once."
        )
    return selected.sort_values("sample_id", kind="stable").reset_index(
        drop=True
    )


def evaluate_calibration_methods(
    predictions: pd.DataFrame,
    *,
    reliability_bins: int = 10,
) -> dict[str, Any]:
    """Evaluate pooled and per-fold aligned calibration predictions."""

    pooled: dict[str, Any] = {}
    folds: list[dict[str, Any]] = []
    expected_samples: list[str] | None = None
    expected_targets: np.ndarray | None = None
    expected_groups: np.ndarray | None = None
    for method in CALIBRATION_METHODS:
        frame = method_prediction_frame(predictions, method)
        samples = frame["sample_id"].astype(str).tolist()
        targets = frame["radiant_win"].to_numpy(dtype=np.int8)
        groups = frame["source_match_id"].astype(str).to_numpy(dtype=object)
        if expected_samples is None:
            expected_samples = samples
            expected_targets = targets
            expected_groups = groups
        elif (
            samples != expected_samples
            or not np.array_equal(targets, expected_targets)
            or not np.array_equal(groups, expected_groups)
        ):
            raise CalibrationError(
                "Calibration method prediction vectors are not aligned."
            )
        evaluated = evaluate_probabilities(
            targets,
            frame["radiant_win_probability"].to_numpy(dtype=np.float64),
            n_bins=reliability_bins,
        )
        if sum(
            int(item["count"])
            for item in evaluated["reliability_bins"]
        ) != len(frame):
            raise CalibrationError(
                f"{method} reliability bins do not reconcile."
            )
        pooled[method] = evaluated
        for fold_id, fold in frame.groupby(
            "calibration_fold",
            sort=True,
        ):
            fold_evaluated = evaluate_probabilities(
                fold["radiant_win"].to_numpy(dtype=np.int8),
                fold["radiant_win_probability"].to_numpy(dtype=np.float64),
                n_bins=reliability_bins,
            )
            folds.append(
                {
                    "calibration_method": method,
                    "calibration_fold": int(fold_id),
                    "rows": len(fold),
                    "source_matches": int(
                        fold["source_match_id"].nunique()
                    ),
                    "metrics": fold_evaluated["metrics"],
                }
            )
    return {
        "pooled": pooled,
        "folds": folds,
        "selection_metrics": ["log_loss", "brier_score"],
        "diagnostic_only_metrics": [
            "roc_auc",
            "accuracy",
            "balanced_accuracy",
            "calibration_in_the_large",
            "calibration_slope",
            "calibration_intercept",
            "expected_calibration_error",
        ],
    }


def build_pairwise_comparisons(
    predictions: pd.DataFrame,
    *,
    n_resamples: int = 1_000,
    random_state: int = 42,
    confidence_level: float = 0.95,
) -> dict[str, Any]:
    """Build all predeclared candidate-minus-reference comparisons."""

    pairs = (
        ("raw", "sigmoid"),
        ("raw", "isotonic"),
        ("sigmoid", "isotonic"),
    )
    return {
        f"{candidate}_vs_{reference}": paired_method_bootstrap_comparison(
            method_prediction_frame(predictions, reference),
            method_prediction_frame(predictions, candidate),
            n_resamples=n_resamples,
            random_state=random_state,
            confidence_level=confidence_level,
        )
        for reference, candidate in pairs
    }


def _qualifies(
    comparison: dict[str, Any],
    *,
    minimum_log_loss_improvement: float,
) -> tuple[bool, dict[str, bool]]:
    log_loss = comparison["metrics"]["log_loss"]
    brier = comparison["metrics"]["brier_score"]
    gates = {
        "minimum_log_loss_improvement": (
            float(log_loss["point_estimate"])
            <= -minimum_log_loss_improvement
        ),
        "lower_brier_score": float(brier["point_estimate"]) < 0,
        "log_loss_paired_upper_below_zero": float(log_loss["upper"]) < 0,
        "brier_paired_upper_below_zero": float(brier["upper"]) < 0,
    }
    return all(gates.values()), gates


def select_calibration_method(
    evaluation: dict[str, Any],
    comparisons: dict[str, Any],
) -> dict[str, Any]:
    """Apply the frozen raw -> sigmoid -> isotonic complexity hierarchy."""

    required_comparisons = {
        "sigmoid_vs_raw",
        "isotonic_vs_raw",
        "isotonic_vs_sigmoid",
    }
    if set(comparisons) != required_comparisons:
        raise CalibrationError(
            "Calibration comparisons do not match the frozen policy."
        )
    pooled = evaluation.get("pooled", {})
    if set(pooled) != set(CALIBRATION_METHODS):
        raise CalibrationError(
            "Calibration metrics do not cover all frozen methods."
        )

    sigmoid_qualified, sigmoid_gates = _qualifies(
        comparisons["sigmoid_vs_raw"],
        minimum_log_loss_improvement=MINIMUM_LOG_LOSS_IMPROVEMENT,
    )
    isotonic_raw_qualified, isotonic_raw_gates = _qualifies(
        comparisons["isotonic_vs_raw"],
        minimum_log_loss_improvement=MINIMUM_LOG_LOSS_IMPROVEMENT,
    )
    isotonic_sigmoid_qualified, isotonic_sigmoid_gates = _qualifies(
        comparisons["isotonic_vs_sigmoid"],
        minimum_log_loss_improvement=MINIMUM_LOG_LOSS_IMPROVEMENT,
    )

    fold_records = evaluation.get("folds", [])
    fold_log_loss = {
        (str(item["calibration_method"]), int(item["calibration_fold"])): float(
            item["metrics"]["log_loss"]
        )
        for item in fold_records
    }
    fold_ids = sorted(
        fold_id
        for method, fold_id in fold_log_loss
        if method == "raw"
    )
    if fold_ids != list(range(5)) or any(
        (method, fold_id) not in fold_log_loss
        for method in CALIBRATION_METHODS
        for fold_id in fold_ids
    ):
        raise CalibrationError(
            "Per-fold calibration metrics do not cover five aligned folds."
        )
    isotonic_fold_differences = [
        fold_log_loss[("isotonic", fold_id)]
        - fold_log_loss[("sigmoid", fold_id)]
        for fold_id in fold_ids
    ]
    isotonic_stability_gate = (
        max(isotonic_fold_differences)
        <= MAXIMUM_ISOTONIC_FOLD_REGRESSION
    )
    isotonic_qualified = (
        isotonic_raw_qualified
        and isotonic_sigmoid_qualified
        and isotonic_stability_gate
    )

    selected = "raw"
    if sigmoid_qualified:
        selected = "sigmoid"
    if isotonic_qualified:
        selected = "isotonic"
    return {
        "selected_method": selected,
        "decision_scope": "cross_fitted_2025_q4_only",
        "complexity_order": list(CALIBRATION_METHODS),
        "unrounded_metrics_used": True,
        "minimum_log_loss_improvement": (
            MINIMUM_LOG_LOSS_IMPROVEMENT
        ),
        "sigmoid": {
            "qualified_vs_raw": sigmoid_qualified,
            "gates_vs_raw": sigmoid_gates,
        },
        "isotonic": {
            "qualified_vs_raw": isotonic_raw_qualified,
            "gates_vs_raw": isotonic_raw_gates,
            "qualified_vs_sigmoid": isotonic_sigmoid_qualified,
            "gates_vs_sigmoid": isotonic_sigmoid_gates,
            "maximum_observed_fold_log_loss_regression_vs_sigmoid": max(
                isotonic_fold_differences
            ),
            "maximum_allowed_fold_log_loss_regression_vs_sigmoid": (
                MAXIMUM_ISOTONIC_FOLD_REGRESSION
            ),
            "fold_stability_gate": isotonic_stability_gate,
            "qualified": isotonic_qualified,
        },
        "selection_metrics": ["log_loss", "brier_score"],
        "diagnostic_metrics_used_for_selection": [],
    }


__all__ = [
    "MAXIMUM_ISOTONIC_FOLD_REGRESSION",
    "MINIMUM_LOG_LOSS_IMPROVEMENT",
    "build_pairwise_comparisons",
    "evaluate_calibration_methods",
    "method_prediction_frame",
    "select_calibration_method",
]
