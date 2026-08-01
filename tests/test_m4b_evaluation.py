"""Tests for deterministic Draft AI probability evaluation."""

from __future__ import annotations

import numpy as np
import pytest
from scipy.sparse import csr_matrix
from sklearn.linear_model import LogisticRegression

from src.draft_ai_modeling.evaluation import (
    EvaluationError,
    evaluate_probabilities,
    global_logistic_coefficient_explanations,
    grouped_bootstrap_confidence_intervals,
    reliability_bins,
)


def test_probability_metrics_and_reliability_reconcile() -> None:
    targets = [0, 0, 1, 1]
    probabilities = [0.1, 0.4, 0.6, 0.9]

    result = evaluate_probabilities(targets, probabilities, n_bins=5)

    assert result["rows"] == 4
    assert result["metrics"]["log_loss"] < 0.5
    assert result["metrics"]["brier_score"] == pytest.approx(0.085)
    assert result["metrics"]["roc_auc"] == 1.0
    assert result["metrics"]["accuracy"] == 1.0
    assert sum(item["count"] for item in result["reliability_bins"]) == 4
    assert sum(
        item["ece_contribution"] for item in result["reliability_bins"]
    ) == pytest.approx(
        result["metrics"]["expected_calibration_error"]
    )


def test_empirical_prior_has_no_identifiable_calibration_slope() -> None:
    result = evaluate_probabilities(
        [0, 1, 0, 1],
        [0.5, 0.5, 0.5, 0.5],
    )

    assert result["metrics"]["calibration_slope"] is None
    assert result["metrics"]["calibration_in_the_large"] == pytest.approx(0)


def test_probability_validation_rejects_bad_inputs() -> None:
    with pytest.raises(EvaluationError):
        evaluate_probabilities([], [])
    with pytest.raises(EvaluationError):
        evaluate_probabilities([0, 1], [0.2])
    with pytest.raises(EvaluationError):
        evaluate_probabilities([0, 2], [0.2, 0.8])
    with pytest.raises(EvaluationError):
        reliability_bins([0, 1], [0.2, 1.2])


def test_grouped_bootstrap_is_deterministic_and_group_based() -> None:
    targets = [0, 1, 0, 1, 1, 0]
    probabilities = [0.2, 0.8, 0.3, 0.7, 0.6, 0.4]
    groups = ["a", "a", "b", "b", "c", "c"]

    first = grouped_bootstrap_confidence_intervals(
        targets,
        probabilities,
        groups,
        n_resamples=50,
        random_state=7,
    )
    second = grouped_bootstrap_confidence_intervals(
        targets,
        probabilities,
        groups,
        n_resamples=50,
        random_state=7,
    )

    assert first == second
    assert first["unique_groups"] == 3
    assert first["successful_resamples"] == 50
    assert first["metrics"]["log_loss"]["lower"] <= (
        first["metrics"]["log_loss"]["point_estimate"]
    ) <= first["metrics"]["log_loss"]["upper"]


def test_coefficient_explanations_match_sparse_features() -> None:
    matrix = csr_matrix(
        np.asarray(
            [
                [1, 0, 1],
                [1, 1, 0],
                [0, 1, 1],
                [0, 0, 1],
            ],
            dtype=np.int8,
        )
    )
    targets = np.asarray([1, 1, 0, 0])
    estimator = LogisticRegression(
        solver="liblinear",
        random_state=42,
    ).fit(matrix, targets)

    result = global_logistic_coefficient_explanations(
        estimator,
        matrix,
        [
            "presence::radiant_pick::hero::a",
            "presence::dire_pick::hero::b",
            "presence::radiant_pick::hero::c",
        ],
        top_k=2,
    )

    assert result["kind"] == "exact_linear_log_odds"
    assert result["feature_count"] == 3
    assert len(result["coefficient_vector_sha256"]) == 64
    assert len(result["top_positive"]) == 2
    assert len(result["top_negative"]) == 2
    assert all(
        item["training_row_support"] > 0
        for item in (*result["top_positive"], *result["top_negative"])
    )


def test_coefficient_explanations_reject_shape_mismatch() -> None:
    estimator = LogisticRegression(solver="liblinear").fit(
        [[0], [1]],
        [0, 1],
    )
    with pytest.raises(EvaluationError):
        global_logistic_coefficient_explanations(
            estimator,
            csr_matrix([[0], [1]]),
            ["one", "two"],
        )
