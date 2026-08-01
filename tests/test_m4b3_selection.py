"""Tests for the fixed M4B.3 calibration selection hierarchy."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.draft_ai_modeling.calibration import CalibrationError
from src.draft_ai_modeling.calibration_selection import (
    evaluate_calibration_methods,
    select_calibration_method,
)


def _comparison(
    *,
    log_difference: float,
    brier_difference: float,
    log_upper: float = -0.0001,
    brier_upper: float = -0.0001,
) -> dict[str, object]:
    return {
        "metrics": {
            "log_loss": {
                "point_estimate": log_difference,
                "upper": log_upper,
            },
            "brier_score": {
                "point_estimate": brier_difference,
                "upper": brier_upper,
            },
        }
    }


def _evaluation(
    *,
    isotonic_fold_regression: float = 0.0,
) -> dict[str, object]:
    pooled = {
        method: {"metrics": {"log_loss": 0.68, "brier_score": 0.24}}
        for method in ("raw", "sigmoid", "isotonic")
    }
    folds = []
    for fold_id in range(5):
        folds.extend(
            [
                {
                    "calibration_method": "raw",
                    "calibration_fold": fold_id,
                    "metrics": {"log_loss": 0.69},
                },
                {
                    "calibration_method": "sigmoid",
                    "calibration_fold": fold_id,
                    "metrics": {"log_loss": 0.68},
                },
                {
                    "calibration_method": "isotonic",
                    "calibration_fold": fold_id,
                    "metrics": {
                        "log_loss": (
                            0.68 + isotonic_fold_regression
                            if fold_id == 0
                            else 0.67
                        )
                    },
                },
            ]
        )
    return {"pooled": pooled, "folds": folds}


def test_raw_is_fallback_for_small_or_uncertain_improvements() -> None:
    comparisons = {
        "sigmoid_vs_raw": _comparison(
            log_difference=-0.001,
            brier_difference=-0.001,
        ),
        "isotonic_vs_raw": _comparison(
            log_difference=-0.003,
            brier_difference=-0.001,
            log_upper=0.001,
        ),
        "isotonic_vs_sigmoid": _comparison(
            log_difference=-0.003,
            brier_difference=-0.001,
        ),
    }

    result = select_calibration_method(_evaluation(), comparisons)

    assert result["selected_method"] == "raw"
    assert result["sigmoid"]["qualified_vs_raw"] is False
    assert result["isotonic"]["qualified"] is False


def test_sigmoid_replaces_raw_only_after_every_gate_passes() -> None:
    comparisons = {
        "sigmoid_vs_raw": _comparison(
            log_difference=-0.003,
            brier_difference=-0.001,
        ),
        "isotonic_vs_raw": _comparison(
            log_difference=-0.001,
            brier_difference=-0.001,
        ),
        "isotonic_vs_sigmoid": _comparison(
            log_difference=0.001,
            brier_difference=0.0001,
            log_upper=0.002,
            brier_upper=0.001,
        ),
    }

    result = select_calibration_method(_evaluation(), comparisons)

    assert result["selected_method"] == "sigmoid"
    assert result["sigmoid"]["qualified_vs_raw"] is True
    assert result["isotonic"]["qualified"] is False


def test_isotonic_requires_clear_stable_advantage_over_both() -> None:
    passing = {
        "sigmoid_vs_raw": _comparison(
            log_difference=-0.003,
            brier_difference=-0.001,
        ),
        "isotonic_vs_raw": _comparison(
            log_difference=-0.006,
            brier_difference=-0.003,
        ),
        "isotonic_vs_sigmoid": _comparison(
            log_difference=-0.003,
            brier_difference=-0.002,
        ),
    }

    result = select_calibration_method(_evaluation(), passing)
    unstable = select_calibration_method(
        _evaluation(isotonic_fold_regression=0.006),
        passing,
    )

    assert result["selected_method"] == "isotonic"
    assert result["isotonic"]["qualified"] is True
    assert unstable["selected_method"] == "sigmoid"
    assert unstable["isotonic"]["fold_stability_gate"] is False


def test_probability_evaluation_reconciles_aligned_methods() -> None:
    rows = []
    for method_index, method in enumerate(("raw", "sigmoid", "isotonic")):
        for index in range(20):
            target = index % 2
            rows.append(
                {
                    "calibration_method": method,
                    "calibration_fold": index % 5,
                    "sample_id": f"sample-{index:02d}",
                    "source_match_id": f"match-{index // 2:02d}",
                    "radiant_win": target,
                    "radiant_win_probability": (
                        0.65 + 0.01 * method_index
                        if target
                        else 0.35 - 0.01 * method_index
                    ),
                }
            )
    evaluation = evaluate_calibration_methods(pd.DataFrame(rows))

    assert set(evaluation["pooled"]) == {"raw", "sigmoid", "isotonic"}
    assert len(evaluation["folds"]) == 15
    assert all(
        sum(
            bin_record["count"]
            for bin_record in evaluation["pooled"][method][
                "reliability_bins"
            ]
        )
        == 20
        for method in evaluation["pooled"]
    )


def test_probability_evaluation_rejects_method_misalignment() -> None:
    rows = []
    for method in ("raw", "sigmoid", "isotonic"):
        for index in range(10):
            rows.append(
                {
                    "calibration_method": method,
                    "calibration_fold": index % 5,
                    "sample_id": f"sample-{index}",
                    "source_match_id": f"match-{index}",
                    "radiant_win": index % 2,
                    "radiant_win_probability": 0.6 if index % 2 else 0.4,
                }
            )
    frame = pd.DataFrame(rows)
    frame.loc[
        (frame["calibration_method"] == "sigmoid")
        & (frame["sample_id"] == "sample-0"),
        "source_match_id",
    ] = "different"

    with pytest.raises(CalibrationError, match="not aligned"):
        evaluate_calibration_methods(frame)


def test_selection_rejects_missing_comparison() -> None:
    with pytest.raises(CalibrationError, match="frozen policy"):
        select_calibration_method(
            _evaluation(),
            {
                "sigmoid_vs_raw": _comparison(
                    log_difference=-0.003,
                    brier_difference=-0.001,
                )
            },
        )
