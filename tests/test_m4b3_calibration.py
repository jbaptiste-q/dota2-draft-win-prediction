"""Focused tests for group-safe Draft AI calibration utilities."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.draft_ai_modeling.calibration import (
    CALIBRATION_METHODS,
    CalibrationError,
    cross_fitted_calibration_predictions,
    paired_method_bootstrap_comparison,
)


def calibration_frame() -> pd.DataFrame:
    """Return twenty balanced two-game source-match groups."""

    rows: list[dict[str, object]] = []
    for group_index in range(20):
        for target in (0, 1):
            probability = (
                0.25 + 0.01 * (group_index % 4)
                if target == 0
                else 0.70 + 0.01 * (group_index % 4)
            )
            rows.append(
                {
                    "sample_id": f"sample-{group_index:02d}-{target}",
                    "source_match_id": f"match-{group_index:02d}",
                    "radiant_win": target,
                    "raw_probability": probability,
                }
            )
    return pd.DataFrame(rows)


def method_frame(
    predictions: pd.DataFrame,
    method: str,
) -> pd.DataFrame:
    return predictions[
        predictions["calibration_method"] == method
    ][
        [
            "sample_id",
            "source_match_id",
            "radiant_win",
            "radiant_win_probability",
        ]
    ].reset_index(drop=True)


def test_cross_fitted_predictions_are_complete_grouped_and_aligned() -> None:
    result = cross_fitted_calibration_predictions(calibration_frame())

    assert result.audit["rows"] == 40
    assert result.audit["source_matches"] == 20
    assert result.audit["prediction_rows"] == 120
    assert result.audit["prediction_rows_per_method"] == 40
    assert result.audit["methods"] == list(CALIBRATION_METHODS)
    assert result.audit["n_splits"] == 5
    assert result.audit["group_crossings"] == 0
    assert len(result.audit["fold_assignment_sha256"]) == 64
    assert len(result.fold_assignments) == 40
    assert result.fold_assignments["sample_id"].is_unique
    assert (
        result.fold_assignments.groupby("source_match_id")[
            "calibration_fold"
        ].nunique()
        == 1
    ).all()
    assert set(result.predictions["calibration_method"]) == set(
        CALIBRATION_METHODS
    )
    assert result.predictions["radiant_win_probability"].notna().all()
    assert result.predictions["radiant_win_probability"].between(0, 1).all()

    raw = method_frame(result.predictions, "raw").sort_values(
        "sample_id"
    )
    expected = calibration_frame().sort_values("sample_id")
    assert raw["sample_id"].tolist() == expected["sample_id"].tolist()
    assert raw["radiant_win_probability"].tolist() == (
        expected["raw_probability"].tolist()
    )
    assert all(
        fold["group_overlap"] == 0
        and fold["fit_positive_rows"] > 0
        and fold["fit_negative_rows"] > 0
        for fold in result.audit["folds"]
    )


def test_cross_fitting_is_deterministic_and_input_order_invariant() -> None:
    first = cross_fitted_calibration_predictions(calibration_frame())
    second = cross_fitted_calibration_predictions(
        calibration_frame().sample(frac=1, random_state=91)
    )

    pd.testing.assert_frame_equal(first.predictions, second.predictions)
    pd.testing.assert_frame_equal(
        first.fold_assignments,
        second.fold_assignments,
    )
    assert first.audit == second.audit


@pytest.mark.parametrize(
    ("column", "value", "message"),
    [
        ("radiant_win", 2, "binary"),
        ("raw_probability", 0.0, r"\(0, 1\)"),
        ("raw_probability", 1.0, r"\(0, 1\)"),
        ("raw_probability", np.nan, r"\(0, 1\)"),
        ("source_match_id", "", "empty"),
    ],
)
def test_cross_fitting_rejects_invalid_inputs(
    column: str,
    value: object,
    message: str,
) -> None:
    frame = calibration_frame()
    frame.loc[0, column] = value

    with pytest.raises(CalibrationError, match=message):
        cross_fitted_calibration_predictions(frame)


def test_cross_fitting_requires_unique_samples() -> None:
    frame = calibration_frame()
    frame.loc[1, "sample_id"] = frame.loc[0, "sample_id"]

    with pytest.raises(CalibrationError, match="duplicate sample_id"):
        cross_fitted_calibration_predictions(frame)


def test_every_calibrator_fit_requires_both_target_classes() -> None:
    rows: list[dict[str, object]] = []
    for group_index in range(5):
        target = int(group_index == 0)
        rows.append(
            {
                "sample_id": f"sample-{group_index}",
                "source_match_id": f"match-{group_index}",
                "radiant_win": target,
                "raw_probability": 0.7 if target else 0.3,
            }
        )

    with pytest.raises(CalibrationError, match="lack both classes"):
        cross_fitted_calibration_predictions(pd.DataFrame(rows))


def uneven_method_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    reference_rows: list[dict[str, object]] = []
    candidate_rows: list[dict[str, object]] = []
    cursor = 0
    for group_index, size in enumerate((1, 2, 3, 4)):
        for row_index in range(size):
            target = (group_index + row_index) % 2
            shared = {
                "sample_id": f"sample-{cursor}",
                "source_match_id": f"match-{group_index}",
                "radiant_win": target,
            }
            reference_rows.append(
                {
                    **shared,
                    "radiant_win_probability": 0.5,
                }
            )
            candidate_rows.append(
                {
                    **shared,
                    "radiant_win_probability": 0.75 if target else 0.25,
                }
            )
            cursor += 1
    return pd.DataFrame(reference_rows), pd.DataFrame(candidate_rows)


def test_paired_method_bootstrap_is_deterministic_and_group_based() -> None:
    reference, candidate = uneven_method_frames()
    first = paired_method_bootstrap_comparison(
        reference,
        candidate.sample(frac=1, random_state=5),
        n_resamples=100,
        random_state=7,
    )
    second = paired_method_bootstrap_comparison(
        reference,
        candidate,
        n_resamples=100,
        random_state=7,
    )

    assert first == second
    assert first["metrics"]["log_loss"]["point_estimate"] < 0
    assert first["metrics"]["brier_score"]["point_estimate"] < 0
    assert first["audit"]["rows"] == 10
    assert first["audit"]["source_matches"] == 4
    assert first["audit"]["group_draws_per_resample"] == 4
    assert first["audit"]["total_group_draws"] == 400
    assert first["audit"]["group_multiplicity_preserved"] is True
    assert first["audit"]["minimum_rows_per_resample"] < (
        first["audit"]["maximum_rows_per_resample"]
    )


def test_cross_fitted_methods_can_be_compared_directly() -> None:
    result = cross_fitted_calibration_predictions(calibration_frame())
    raw = method_frame(result.predictions, "raw")
    sigmoid = method_frame(result.predictions, "sigmoid")

    comparison = paired_method_bootstrap_comparison(
        raw,
        sigmoid,
        n_resamples=10,
    )

    assert comparison["audit"]["rows"] == 40
    assert comparison["audit"]["source_matches"] == 20
    assert set(comparison["metrics"]) == {"log_loss", "brier_score"}


def test_paired_comparison_requires_exact_alignment_and_valid_values() -> None:
    reference, candidate = uneven_method_frames()
    with pytest.raises(CalibrationError, match="sample alignment"):
        paired_method_bootstrap_comparison(
            reference,
            candidate.iloc[1:],
            n_resamples=5,
        )

    candidate = candidate.copy()
    candidate.loc[0, "source_match_id"] = "different"
    with pytest.raises(CalibrationError, match="source_match_id"):
        paired_method_bootstrap_comparison(
            reference,
            candidate,
            n_resamples=5,
        )

    candidate = uneven_method_frames()[1]
    candidate.loc[0, "radiant_win_probability"] = 1.1
    with pytest.raises(CalibrationError, match=r"\[0, 1\]"):
        paired_method_bootstrap_comparison(
            reference,
            candidate,
            n_resamples=5,
        )
