"""Tests for the fixed M4B.5 team-context selection and readiness gates."""

from __future__ import annotations

import json
import math

import pandas as pd
import pytest

from src.draft_ai_modeling.team_context_selection import (
    DEVELOPMENT_FOLDS,
    Q4_READINESS_FOLD,
    TeamContextSelectionError,
    evaluate_team_context_development,
    evaluate_team_context_q4_readiness,
)


def _radiant_probability(target: int, correct_probability: float) -> float:
    return correct_probability if target else 1 - correct_probability


def _prediction_rows(
    folds: tuple[str, ...],
    *,
    joint_correct: float = 0.75,
    team_only_correct: float = 0.65,
    frozen_b1_correct: float = 0.60,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for fold_index, fold in enumerate(folds):
        for game_index in range(12):
            target = (fold_index + game_index) % 2
            rows.append(
                {
                    "evaluation_id": fold,
                    "sample_id": f"{fold}-sample-{game_index:02d}",
                    "source_match_id": (
                        f"{fold}-match-{game_index // 2:02d}"
                    ),
                    "radiant_win": target,
                    "joint_probability": _radiant_probability(
                        target,
                        joint_correct,
                    ),
                    "team_only_probability": _radiant_probability(
                        target,
                        team_only_correct,
                    ),
                    "frozen_b1_probability": _radiant_probability(
                        target,
                        frozen_b1_correct,
                    ),
                    "canonical_b0_probability": 0.5,
                }
            )
    return pd.DataFrame(rows)


def development_predictions(**kwargs: float) -> pd.DataFrame:
    return _prediction_rows(DEVELOPMENT_FOLDS, **kwargs)


def q4_predictions(**kwargs: float) -> pd.DataFrame:
    return _prediction_rows((Q4_READINESS_FOLD,), **kwargs)


def test_development_gate_passes_deterministically() -> None:
    predictions = development_predictions().sample(
        frac=1,
        random_state=17,
    )

    first = evaluate_team_context_development(
        predictions,
        n_resamples=40,
        random_state=7,
    )
    second = evaluate_team_context_development(
        predictions,
        n_resamples=40,
        random_state=7,
    )

    assert first == second
    assert first["qualified"] is True
    assert first["passed"] is True
    assert first["decision_scope"] == (
        "development_only_2024_q1_2025_q3"
    )
    assert first["gates"]["all_recent_per_fold"] is True
    assert first["gates"]["all_pooled_recent"] is True
    assert first["gates"]["all_paired_frozen_b1"] is True
    assert first["gates"]["all_seven_fold"] is True
    assert first["gates"]["all_product_attribution"] is True
    assert first["audit"]["rows"] == 84
    assert first["audit"]["source_matches"] == 42
    assert first["audit"]["q4_rows_used"] == 0
    assert first["audit"]["locked_test_rows_used"] == 0
    assert first["audit"]["fold_rows"] == {
        fold: 12 for fold in DEVELOPMENT_FOLDS
    }
    assert set(first["comparisons"]) == {
        "recent_joint_vs_frozen_b1",
        "recent_joint_vs_team_only",
    }
    json.dumps(first, sort_keys=True)


def test_every_recent_fold_must_beat_b1_and_b0_on_both_losses() -> None:
    predictions = development_predictions()
    mask = predictions["evaluation_id"] == "2025-Q2"
    predictions.loc[mask, "joint_probability"] = predictions.loc[
        mask,
        "frozen_b1_probability",
    ]

    result = evaluate_team_context_development(
        predictions,
        n_resamples=20,
    )

    assert result["qualified"] is False
    fold_gates = result["gates"]["recent_per_fold"]["2025-Q2"]
    assert fold_gates["joint_log_loss_below_frozen_b1"] is False
    assert fold_gates["joint_brier_below_frozen_b1"] is False
    assert result["gates"]["all_recent_per_fold"] is False

    predictions = development_predictions()
    predictions.loc[mask, "canonical_b0_probability"] = predictions.loc[
        mask,
        "joint_probability",
    ]
    result = evaluate_team_context_development(
        predictions,
        n_resamples=20,
    )
    fold_gates = result["gates"]["recent_per_fold"]["2025-Q2"]
    assert fold_gates["joint_log_loss_below_canonical_b0"] is False
    assert fold_gates["joint_brier_below_canonical_b0"] is False
    assert result["qualified"] is False


def test_pooled_recent_requires_minimum_log_loss_improvement() -> None:
    frozen_loss = -math.log(0.70)
    slight_improvement = math.exp(-(frozen_loss - 0.001))
    predictions = development_predictions(
        joint_correct=slight_improvement,
        team_only_correct=0.69,
        frozen_b1_correct=0.70,
    )

    result = evaluate_team_context_development(
        predictions,
        n_resamples=20,
    )

    assert result["gates"]["all_recent_per_fold"] is True
    assert result["gates"]["pooled_recent"][
        "minimum_log_loss_improvement_vs_frozen_b1"
    ] is False
    assert result["gates"]["pooled_recent"][
        "joint_brier_below_frozen_b1"
    ] is True
    assert result["qualified"] is False


def test_seven_fold_mean_and_maximum_regression_are_gating() -> None:
    predictions = development_predictions(
        joint_correct=0.72,
        team_only_correct=0.65,
        frozen_b1_correct=0.70,
    )
    early = predictions["evaluation_id"] == "2024-Q1"
    predictions.loc[early, "joint_probability"] = [
        _radiant_probability(target, 0.68)
        for target in predictions.loc[early, "radiant_win"]
    ]

    result = evaluate_team_context_development(
        predictions,
        n_resamples=20,
    )

    assert result["gates"]["all_recent_per_fold"] is True
    assert result["gates"]["seven_fold"][
        "maximum_single_fold_log_loss_regression_within_limit"
    ] is False
    assert result["qualified"] is False

    predictions = development_predictions(
        joint_correct=0.703,
        team_only_correct=0.69,
        frozen_b1_correct=0.70,
    )
    early_folds = {"2024-Q1", "2024-Q2", "2024-Q3", "2024-Q4"}
    early = predictions["evaluation_id"].isin(early_folds)
    predictions.loc[early, "joint_probability"] = [
        _radiant_probability(target, 0.695)
        for target in predictions.loc[early, "radiant_win"]
    ]
    result = evaluate_team_context_development(
        predictions,
        n_resamples=20,
        minimum_recent_log_loss_improvement=0.0,
    )
    assert result["gates"]["seven_fold"][
        "mean_joint_log_loss_no_worse_than_frozen_b1"
    ] is False
    assert result["qualified"] is False


def test_product_attribution_requires_joint_to_beat_team_only() -> None:
    predictions = development_predictions()
    predictions["team_only_probability"] = predictions[
        "joint_probability"
    ]

    result = evaluate_team_context_development(
        predictions,
        n_resamples=20,
    )

    attribution = result["gates"]["product_attribution"]
    assert attribution["pooled_joint_log_loss_below_team_only"] is False
    assert attribution["pooled_joint_brier_below_team_only"] is False
    assert attribution["log_loss_upper_below_zero"] is False
    assert attribution["brier_score_upper_below_zero"] is False
    assert result["gates"]["all_product_attribution"] is False
    assert result["qualified"] is False


def test_q4_readiness_requires_point_and_paired_evidence_vs_all_references() -> None:
    passing = evaluate_team_context_q4_readiness(
        q4_predictions(),
        n_resamples=40,
        random_state=7,
    )

    assert passing["qualified"] is True
    assert passing["passed"] is True
    assert passing["gates"]["all"] is True
    assert set(passing["comparisons"]) == {
        "joint_vs_canonical_b0",
        "joint_vs_frozen_b1",
        "joint_vs_team_only",
    }
    for reference in ("canonical_b0", "frozen_b1", "team_only"):
        assert all(passing["gates"][reference].values())

    predictions = q4_predictions()
    predictions["team_only_probability"] = predictions[
        "joint_probability"
    ]
    failing = evaluate_team_context_q4_readiness(
        predictions,
        n_resamples=20,
    )
    assert failing["gates"]["team_only"] == {
        "log_loss_point_below_zero": False,
        "log_loss_upper_below_zero": False,
        "brier_score_point_below_zero": False,
        "brier_score_upper_below_zero": False,
    }
    assert failing["qualified"] is False


def test_strictly_validates_folds_samples_groups_and_values() -> None:
    missing_fold = development_predictions()
    missing_fold = missing_fold[
        missing_fold["evaluation_id"] != "2024-Q2"
    ]
    with pytest.raises(
        TeamContextSelectionError,
        match="exactly these folds",
    ):
        evaluate_team_context_development(missing_fold, n_resamples=5)

    duplicate = development_predictions()
    duplicate.loc[1, "sample_id"] = duplicate.loc[0, "sample_id"]
    with pytest.raises(
        TeamContextSelectionError,
        match="duplicate sample_id",
    ):
        evaluate_team_context_development(duplicate, n_resamples=5)

    crossing = development_predictions()
    crossing.loc[
        crossing["evaluation_id"] == "2024-Q2",
        "source_match_id",
    ] = "2024-Q1-match-00"
    with pytest.raises(
        TeamContextSelectionError,
        match="crossing folds",
    ):
        evaluate_team_context_development(crossing, n_resamples=5)

    invalid = development_predictions()
    invalid.loc[0, "joint_probability"] = 1.01
    with pytest.raises(
        TeamContextSelectionError,
        match="joint_probability",
    ):
        evaluate_team_context_development(invalid, n_resamples=5)

    invalid = development_predictions()
    invalid.loc[0, "radiant_win"] = 2
    with pytest.raises(
        TeamContextSelectionError,
        match="radiant_win",
    ):
        evaluate_team_context_development(invalid, n_resamples=5)


def test_q4_readiness_rejects_non_q4_rows_and_invalid_policy() -> None:
    with pytest.raises(
        TeamContextSelectionError,
        match="exactly these folds",
    ):
        evaluate_team_context_q4_readiness(
            _prediction_rows(("2025-Q3",)),
            n_resamples=5,
        )

    with pytest.raises(
        TeamContextSelectionError,
        match="positive integer",
    ):
        evaluate_team_context_development(
            development_predictions(),
            n_resamples=0,
        )

    with pytest.raises(
        TeamContextSelectionError,
        match="confidence level",
    ):
        evaluate_team_context_q4_readiness(
            q4_predictions(),
            n_resamples=5,
            confidence_level=1.0,
        )
