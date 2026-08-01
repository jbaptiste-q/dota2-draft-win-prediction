"""Tests for paired development-only Draft AI recency evaluation."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.draft_ai_modeling.recency_evaluation import (
    RecencyEvaluationError,
    paired_recent_development_comparison,
    patch_group_descriptive_metrics,
)


def prediction_frame(
    *,
    candidate: bool,
) -> pd.DataFrame:
    """Return paired rows with differently sized source-match groups."""

    rows: list[dict[str, object]] = []
    probabilities = (
        (0.2, 0.8, 0.3, 0.7, 0.25, 0.75, 0.4, 0.6, 0.35)
        if candidate
        else (0.45, 0.55, 0.45, 0.55, 0.45, 0.55, 0.45, 0.55, 0.45)
    )
    targets = (0, 1, 0, 1, 0, 1, 0, 1, 0)
    cursor = 0
    for fold_index, fold in enumerate(("2025-Q1", "2025-Q2", "2025-Q3")):
        group_sizes = (1, 2) if fold_index != 1 else (2, 1)
        for group_index, group_size in enumerate(group_sizes):
            group_id = f"{fold}-match-{group_index}"
            for _ in range(group_size):
                rows.append(
                    {
                        "sample_id": f"sample-{cursor}",
                        "source_match_id": group_id,
                        "evaluation_id": fold,
                        "radiant_win": targets[cursor],
                        "radiant_win_probability": probabilities[cursor],
                    }
                )
                cursor += 1
    return pd.DataFrame(rows)


def test_paired_recent_comparison_is_deterministic_and_improves() -> None:
    reference = prediction_frame(candidate=False)
    candidate = prediction_frame(candidate=True).sample(
        frac=1,
        random_state=9,
    )

    first = paired_recent_development_comparison(
        reference,
        candidate,
        n_resamples=100,
        random_state=7,
    )
    second = paired_recent_development_comparison(
        reference,
        candidate,
        n_resamples=100,
        random_state=7,
    )

    assert first == second
    assert first["metrics"]["log_loss"]["point_estimate"] < 0
    assert first["metrics"]["brier_score"]["point_estimate"] < 0
    assert first["audit"]["rows"] == 9
    assert first["audit"]["source_matches"] == 6
    assert first["audit"]["fold_rows"] == {
        "2025-Q1": 3,
        "2025-Q2": 3,
        "2025-Q3": 3,
    }
    assert first["audit"]["group_draws_per_resample"] == 6
    assert first["audit"]["total_group_draws"] == 600
    assert first["audit"]["group_multiplicity_preserved"] is True
    assert first["audit"]["minimum_rows_per_resample"] < (
        first["audit"]["maximum_rows_per_resample"]
    )


def test_point_differences_match_direct_pooled_losses() -> None:
    reference = prediction_frame(candidate=False)
    candidate = prediction_frame(candidate=True)
    result = paired_recent_development_comparison(
        reference,
        candidate,
        n_resamples=10,
    )
    targets = reference["radiant_win"].to_numpy(dtype=float)
    reference_probability = reference[
        "radiant_win_probability"
    ].to_numpy()
    candidate_probability = candidate[
        "radiant_win_probability"
    ].to_numpy()
    expected_brier = np.mean(
        np.square(targets - candidate_probability)
        - np.square(targets - reference_probability)
    )
    expected_log = np.mean(
        -targets * np.log(candidate_probability)
        - (1 - targets) * np.log1p(-candidate_probability)
        - (
            -targets * np.log(reference_probability)
            - (1 - targets) * np.log1p(-reference_probability)
        )
    )

    assert result["metrics"]["brier_score"]["point_estimate"] == (
        pytest.approx(expected_brier)
    )
    assert result["metrics"]["log_loss"]["point_estimate"] == (
        pytest.approx(expected_log)
    )


@pytest.mark.parametrize(
    ("column", "replacement", "message"),
    [
        ("source_match_id", "different-match", "source_match_id"),
        ("evaluation_id", "2025-Q2", "evaluation_id"),
        ("radiant_win", 1, "radiant_win"),
    ],
)
def test_pair_alignment_must_match_exactly(
    column: str,
    replacement: object,
    message: str,
) -> None:
    reference = prediction_frame(candidate=False)
    candidate = prediction_frame(candidate=True)
    candidate.loc[0, column] = replacement

    with pytest.raises(RecencyEvaluationError, match=message):
        paired_recent_development_comparison(reference, candidate)


def test_pair_alignment_rejects_missing_and_invalid_predictions() -> None:
    reference = prediction_frame(candidate=False)
    candidate = prediction_frame(candidate=True).iloc[1:].copy()
    with pytest.raises(RecencyEvaluationError, match="sample alignment"):
        paired_recent_development_comparison(reference, candidate)

    candidate = prediction_frame(candidate=True)
    candidate.loc[0, "radiant_win_probability"] = 1.1
    with pytest.raises(RecencyEvaluationError, match="probabilities"):
        paired_recent_development_comparison(reference, candidate)


def test_pair_scope_requires_all_three_recent_folds() -> None:
    reference = prediction_frame(candidate=False)
    candidate = prediction_frame(candidate=True)
    reference = reference[reference["evaluation_id"] != "2025-Q2"]
    candidate = candidate[candidate["evaluation_id"] != "2025-Q2"]

    with pytest.raises(RecencyEvaluationError, match="2025-Q2"):
        paired_recent_development_comparison(reference, candidate)


def test_patch_metrics_are_descriptive_and_suppress_small_groups() -> None:
    rows: list[dict[str, object]] = []
    for index in range(199):
        patch = "7.39" if index < 100 else "7.40"
        target = index % 2
        rows.append(
            {
                "sample_id": f"sample-{index}",
                "source_match_id": f"match-{index // 2}",
                "evaluation_id": "2025-Q3",
                "radiant_win": target,
                "radiant_win_probability": 0.7 if target else 0.3,
                "patch": patch,
            }
        )
    result = patch_group_descriptive_metrics(pd.DataFrame(rows))
    patches = {item["patch"]: item for item in result["patches"]}

    assert result["used_for_selection"] is False
    assert result["selection_use"] == "descriptive_only"
    assert result["minimum_group_size"] == 100
    assert result["reported_groups"] == 1
    assert result["suppressed_groups"] == 1
    assert patches["7.39"]["reportable"] is True
    assert patches["7.39"]["metrics"]["log_loss"] < 0.4
    assert patches["7.40"]["reportable"] is False
    assert patches["7.40"]["metrics"] is None
    assert all(
        item["used_for_selection"] is False
        for item in result["patches"]
    )


def test_patch_metrics_do_not_allow_a_smaller_reporting_threshold() -> None:
    frame = prediction_frame(candidate=True)
    frame["patch"] = "7.39"

    with pytest.raises(RecencyEvaluationError, match="at least 100"):
        patch_group_descriptive_metrics(
            frame,
            minimum_group_size=99,
        )
