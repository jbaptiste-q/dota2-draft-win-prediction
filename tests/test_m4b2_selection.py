"""Tests for bounded Draft AI recency-candidate selection."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from src.draft_ai_modeling.recency_selection import (
    RecencySelectionError,
    select_recency_candidate,
)


POLICIES = ("full_uniform", "full_exp180", "trailing365_uniform")
C_VALUES = (0.01, 0.1, 1.0)
FOLDS = ("2025-Q1", "2025-Q2", "2025-Q3")


def candidate_probability(
    history_policy: str,
    c_value: float,
) -> float:
    """Return correct-class probability with intentional practical ties."""

    values = {
        ("full_uniform", 0.01): 0.7490,
        ("full_uniform", 0.1): 0.7495,
        ("full_uniform", 1.0): 0.72,
        ("full_exp180", 0.01): 0.7485,
        ("full_exp180", 0.1): 0.73,
        ("full_exp180", 1.0): 0.71,
        ("trailing365_uniform", 0.01): 0.7500,
        ("trailing365_uniform", 0.1): 0.72,
        ("trailing365_uniform", 1.0): 0.70,
    }
    return values[(history_policy, c_value)]


def nine_candidate_predictions() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for history_policy in POLICIES:
        for c_value in C_VALUES:
            candidate_id = f"{history_policy}-c{c_value}"
            correct_probability = candidate_probability(
                history_policy,
                c_value,
            )
            for fold_index, fold in enumerate(FOLDS):
                for game_index in range(8):
                    target = (fold_index + game_index) % 2
                    rows.append(
                        {
                            "candidate_id": candidate_id,
                            "history_policy_id": history_policy,
                            "C": c_value,
                            "evaluation_id": fold,
                            "sample_id": f"{fold}-sample-{game_index}",
                            "source_match_id": (
                                f"{fold}-match-{game_index // 2}"
                            ),
                            "radiant_win": target,
                            "candidate_probability": (
                                correct_probability
                                if target
                                else 1 - correct_probability
                            ),
                            "policy_matched_b0_probability": 0.5,
                            "canonical_b0_probability": 0.5,
                        }
                    )
    return pd.DataFrame(rows)


def candidate_result(
    result: dict[str, object],
    candidate_id: str,
) -> dict[str, object]:
    return next(
        item
        for item in result["candidates"]
        if item["candidate_id"] == candidate_id
    )


def test_selects_by_practical_tie_preferences_after_all_gates() -> None:
    predictions = nine_candidate_predictions().sample(
        frac=1,
        random_state=11,
    )

    first = select_recency_candidate(
        predictions,
        n_resamples=50,
        random_state=7,
    )
    second = select_recency_candidate(
        predictions,
        n_resamples=50,
        random_state=7,
    )

    assert first == second
    assert first["selection_status"] == "development_candidate_selected"
    assert first["selected_candidate_id"] == "full_uniform-c0.01"
    assert first["not_a_final_champion"] is True
    assert first["calibration_or_locked_test_used"] is False
    assert first["audit"]["candidate_count"] == 9
    assert first["audit"]["rows_per_candidate"] == 24
    assert first["audit"]["fold_rows_per_candidate"] == {
        "2025-Q1": 8,
        "2025-Q2": 8,
        "2025-Q3": 8,
    }
    selected = candidate_result(first, "full_uniform-c0.01")
    assert selected["qualifies_as_development_candidate"] is True
    assert selected["selection_rank"] == 1
    assert all(selected["gate_results"].values())

    raw_best_loss = -math.log(0.75)
    selected_loss = selected["evaluations"]["pooled"]["candidate"][
        "log_loss"
    ]
    assert selected_loss > raw_best_loss
    assert selected_loss - raw_best_loss < 0.002


def test_candidate_must_beat_both_references_in_every_fold() -> None:
    predictions = nine_candidate_predictions()
    candidate_id = "full_uniform-c0.01"
    mask = (
        (predictions["candidate_id"] == candidate_id)
        & (predictions["evaluation_id"] == "2025-Q2")
    )
    predictions.loc[mask, "candidate_probability"] = predictions.loc[
        mask,
        "canonical_b0_probability",
    ]

    result = select_recency_candidate(
        predictions,
        n_resamples=20,
    )
    candidate = candidate_result(result, candidate_id)

    assert candidate["qualifies_as_development_candidate"] is False
    assert candidate["evaluations"]["2025-Q2"][
        "passes_all_strict_improvement_gates"
    ] is False


def test_no_candidate_passes_when_predictions_equal_references() -> None:
    predictions = nine_candidate_predictions()
    predictions["candidate_probability"] = predictions[
        "policy_matched_b0_probability"
    ]

    result = select_recency_candidate(
        predictions,
        n_resamples=20,
    )

    assert result["selection_status"] == (
        "no_candidate_passed_all_development_gates"
    )
    assert result["selected_candidate_id"] is None
    assert result["qualifying_ranking"] == []
    assert result["audit"]["qualifying_candidate_count"] == 0


def test_requires_exact_approved_candidate_grid() -> None:
    predictions = nine_candidate_predictions()
    predictions = predictions[
        predictions["candidate_id"] != "full_uniform-c0.01"
    ]

    with pytest.raises(RecencySelectionError, match="exactly 9"):
        select_recency_candidate(predictions, n_resamples=5)

    predictions = nine_candidate_predictions()
    predictions.loc[
        predictions["candidate_id"] == "full_uniform-c0.01",
        "history_policy_id",
    ] = "full_exp180"
    with pytest.raises(RecencySelectionError, match="approved grid"):
        select_recency_candidate(predictions, n_resamples=5)


@pytest.mark.parametrize(
    ("column", "value", "message"),
    [
        ("radiant_win", 2, "radiant_win"),
        ("candidate_probability", 1.1, "candidate_probability"),
        ("canonical_b0_probability", -0.1, "canonical_b0_probability"),
    ],
)
def test_rejects_invalid_targets_and_probabilities(
    column: str,
    value: object,
    message: str,
) -> None:
    predictions = nine_candidate_predictions()
    predictions.loc[0, column] = value

    with pytest.raises(RecencySelectionError, match=message):
        select_recency_candidate(predictions, n_resamples=5)


def test_requires_exact_sample_and_reference_alignment() -> None:
    predictions = nine_candidate_predictions()
    predictions.loc[
        predictions["candidate_id"] == "full_uniform-c0.01",
        "sample_id",
    ] = predictions.loc[
        predictions["candidate_id"] == "full_uniform-c0.01",
        "sample_id",
    ] + "-changed"

    with pytest.raises(RecencySelectionError, match="sample alignment"):
        select_recency_candidate(predictions, n_resamples=5)

    predictions = nine_candidate_predictions()
    predictions.loc[
        predictions["candidate_id"] == "full_uniform-c0.1",
        "canonical_b0_probability",
    ] = 0.49
    with pytest.raises(RecencySelectionError, match="canonical_b0"):
        select_recency_candidate(predictions, n_resamples=5)


def test_policy_matched_reference_is_constant_within_policy() -> None:
    predictions = nine_candidate_predictions()
    predictions.loc[
        predictions["candidate_id"] == "full_exp180-c0.1",
        "policy_matched_b0_probability",
    ] = 0.49

    with pytest.raises(RecencySelectionError, match="Policy-matched B0"):
        select_recency_candidate(predictions, n_resamples=5)
