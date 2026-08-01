"""Tests for the bounded M4B.4 interaction-candidate selection gate."""

from __future__ import annotations

import json
import math

import pandas as pd
import pytest

from src.draft_ai_modeling.interaction_selection import (
    DEVELOPMENT_FOLDS,
    InteractionSelectionError,
    select_interaction_candidate,
)


CANDIDATES = {
    "c1_pick_interactions_c0p001": 0.001,
    "c1_pick_interactions_c0p01": 0.01,
}
RECENT_FOLDS = ("2025-Q1", "2025-Q2", "2025-Q3")


def _radiant_probability(target: int, correct_probability: float) -> float:
    return correct_probability if target else 1 - correct_probability


def interaction_predictions(
    *,
    correct_probabilities: dict[str, float] | None = None,
) -> pd.DataFrame:
    candidate_probabilities = correct_probabilities or {
        "c1_pick_interactions_c0p001": 0.7500,
        "c1_pick_interactions_c0p01": 0.7505,
    }
    rows: list[dict[str, object]] = []
    for candidate_id, c_value in CANDIDATES.items():
        for fold_index, fold in enumerate(DEVELOPMENT_FOLDS):
            for game_index in range(8):
                target = (fold_index + game_index) % 2
                rows.append(
                    {
                        "candidate_id": candidate_id,
                        "C": c_value,
                        "evaluation_id": fold,
                        "sample_id": f"{fold}-sample-{game_index}",
                        "source_match_id": (
                            f"{fold}-match-{game_index // 2}"
                        ),
                        "radiant_win": target,
                        "candidate_probability": _radiant_probability(
                            target,
                            candidate_probabilities[candidate_id],
                        ),
                        "frozen_b1_probability": _radiant_probability(
                            target,
                            0.70,
                        ),
                        "canonical_b0_probability": 0.5,
                    }
                )
    return pd.DataFrame(rows)


def _candidate_result(
    result: dict[str, object],
    candidate_id: str,
) -> dict[str, object]:
    return next(
        item
        for item in result["candidates"]
        if item["candidate_id"] == candidate_id
    )


def test_selects_lower_c_within_practical_recent_log_loss_tie() -> None:
    predictions = interaction_predictions().sample(
        frac=1,
        random_state=17,
    )

    first = select_interaction_candidate(
        predictions,
        n_resamples=50,
        random_state=7,
    )
    second = select_interaction_candidate(
        predictions,
        n_resamples=50,
        random_state=7,
    )

    assert first == second
    assert first["selection_status"] == (
        "interaction_development_candidate_selected"
    )
    assert first["selected_candidate_id"] == (
        "c1_pick_interactions_c0p001"
    )
    assert first["q4_or_locked_test_used"] is False
    assert first["stop_model_expansion_if_no_candidate_qualifies"] is True
    assert first["audit"]["candidate_count"] == 2
    assert first["audit"]["rows_per_candidate"] == 56
    assert first["audit"]["fold_rows_per_candidate"] == {
        fold: 8 for fold in DEVELOPMENT_FOLDS
    }
    assert first["audit"]["calibration_rows_used"] == 0
    assert first["audit"]["locked_test_rows_used"] == 0
    assert first["policy"]["evaluation_fold_ids"] == list(DEVELOPMENT_FOLDS)
    assert first["policy"]["selection_fold_ids"] == list(RECENT_FOLDS)

    selected = _candidate_result(
        first,
        "c1_pick_interactions_c0p001",
    )
    assert selected["qualifies_as_development_candidate"] is True
    assert selected["selection_rank"] == 1
    assert selected["gate_results"]["all_recent_per_fold_gates"] is True
    assert selected["gate_results"]["all_pooled_recent_gates"] is True
    assert selected["gate_results"][
        "all_paired_frozen_b1_gates"
    ] is True
    assert selected["gate_results"]["all_seven_fold_gates"] is True

    lower_loss = _candidate_result(
        first,
        "c1_pick_interactions_c0p01",
    )["evaluations"]["recent_pooled"]["candidate"]["log_loss"]
    selected_loss = selected["evaluations"]["recent_pooled"][
        "candidate"
    ]["log_loss"]
    assert selected_loss > lower_loss
    assert selected_loss - lower_loss < 0.002
    json.dumps(first, sort_keys=True)


def test_every_recent_fold_must_beat_both_frozen_references() -> None:
    predictions = interaction_predictions()
    candidate_id = "c1_pick_interactions_c0p001"
    mask = (
        (predictions["candidate_id"] == candidate_id)
        & (predictions["evaluation_id"] == "2025-Q2")
    )
    predictions.loc[mask, "candidate_probability"] = predictions.loc[
        mask,
        "frozen_b1_probability",
    ]

    result = select_interaction_candidate(
        predictions,
        n_resamples=20,
    )
    candidate = _candidate_result(result, candidate_id)

    assert candidate["qualifies_as_development_candidate"] is False
    fold_gates = candidate["gate_results"]["recent_per_fold"]["2025-Q2"]
    assert fold_gates["log_loss_below_frozen_b1"] is False
    assert fold_gates["brier_below_frozen_b1"] is False
    assert result["selected_candidate_id"] == "c1_pick_interactions_c0p01"


def test_pooled_recent_log_loss_requires_practical_improvement() -> None:
    frozen_loss = -math.log(0.70)
    slightly_better = math.exp(-(frozen_loss - 0.001))
    predictions = interaction_predictions(
        correct_probabilities={
            candidate_id: slightly_better
            for candidate_id in CANDIDATES
        }
    )

    result = select_interaction_candidate(
        predictions,
        n_resamples=20,
    )

    assert result["selected_candidate_id"] is None
    for candidate in result["candidates"]:
        gates = candidate["gate_results"]
        assert gates["all_recent_per_fold_gates"] is True
        assert gates["all_paired_frozen_b1_gates"] is True
        assert gates["pooled_recent"][
            "minimum_log_loss_improvement_vs_frozen_b1"
        ] is False
        assert candidate["qualifies_as_development_candidate"] is False


def test_earlier_folds_enforce_mean_and_maximum_regression_gates() -> None:
    predictions = interaction_predictions()
    frozen_loss = -math.log(0.70)
    early_probability = math.exp(-(frozen_loss + 0.005))
    recent_probability = math.exp(-(frozen_loss - 0.003))
    for candidate_id in CANDIDATES:
        candidate_rows = predictions["candidate_id"] == candidate_id
        for fold in DEVELOPMENT_FOLDS:
            fold_rows = candidate_rows & (
                predictions["evaluation_id"] == fold
            )
            correct_probability = (
                recent_probability
                if fold in RECENT_FOLDS
                else early_probability
            )
            predictions.loc[
                fold_rows,
                "candidate_probability",
            ] = [
                _radiant_probability(target, correct_probability)
                for target in predictions.loc[
                    fold_rows,
                    "radiant_win",
                ]
            ]

    result = select_interaction_candidate(
        predictions,
        n_resamples=20,
    )

    assert result["selected_candidate_id"] is None
    for candidate in result["candidates"]:
        gates = candidate["gate_results"]
        assert gates["all_recent_per_fold_gates"] is True
        assert gates["all_pooled_recent_gates"] is True
        assert gates["all_paired_frozen_b1_gates"] is True
        assert gates["seven_fold"][
            "maximum_single_fold_log_loss_regression_within_limit"
        ] is True
        assert gates["seven_fold"][
            "mean_log_loss_no_worse_than_frozen_b1"
        ] is False

    predictions = interaction_predictions()
    mask = (
        (predictions["candidate_id"] == "c1_pick_interactions_c0p001")
        & (predictions["evaluation_id"] == "2024-Q1")
    )
    predictions.loc[mask, "candidate_probability"] = [
        _radiant_probability(target, 0.68)
        for target in predictions.loc[mask, "radiant_win"]
    ]
    result = select_interaction_candidate(predictions, n_resamples=20)
    candidate = _candidate_result(
        result,
        "c1_pick_interactions_c0p001",
    )
    assert candidate["gate_results"]["seven_fold"][
        "maximum_single_fold_log_loss_regression_within_limit"
    ] is False


def test_no_candidate_qualifies_when_equal_to_frozen_b1() -> None:
    predictions = interaction_predictions()
    predictions["candidate_probability"] = predictions[
        "frozen_b1_probability"
    ]

    result = select_interaction_candidate(
        predictions,
        n_resamples=20,
    )

    assert result["selection_status"] == (
        "no_interaction_candidate_passed_all_development_gates"
    )
    assert result["selected_candidate_id"] is None
    assert result["qualifying_ranking"] == []
    assert all(
        candidate["selection_rank"] is None
        for candidate in result["candidates"]
    )


def test_requires_exact_candidates_configuration_and_folds() -> None:
    predictions = interaction_predictions()
    predictions = predictions[
        predictions["candidate_id"] != "c1_pick_interactions_c0p001"
    ]
    with pytest.raises(
        InteractionSelectionError,
        match="exactly the two approved",
    ):
        select_interaction_candidate(predictions, n_resamples=5)

    predictions = interaction_predictions()
    predictions.loc[
        predictions["candidate_id"] == "c1_pick_interactions_c0p001",
        "C",
    ] = 0.01
    with pytest.raises(InteractionSelectionError, match="C=0.001"):
        select_interaction_candidate(predictions, n_resamples=5)

    predictions = interaction_predictions()
    predictions = predictions[
        predictions["evaluation_id"] != "2024-Q2"
    ]
    with pytest.raises(
        InteractionSelectionError,
        match="exactly 2024-Q1 through 2025-Q3",
    ):
        select_interaction_candidate(predictions, n_resamples=5)


def test_requires_exact_sample_target_and_reference_alignment() -> None:
    predictions = interaction_predictions()
    row = predictions[
        predictions["candidate_id"] == "c1_pick_interactions_c0p01"
    ].index[0]
    predictions.loc[row, "source_match_id"] = "different-match"
    with pytest.raises(
        InteractionSelectionError,
        match="source_match_id alignment",
    ):
        select_interaction_candidate(predictions, n_resamples=5)

    predictions = interaction_predictions()
    row = predictions[
        predictions["candidate_id"] == "c1_pick_interactions_c0p01"
    ].index[0]
    predictions.loc[row, "frozen_b1_probability"] = 0.51
    with pytest.raises(
        InteractionSelectionError,
        match="frozen_b1_probability alignment",
    ):
        select_interaction_candidate(predictions, n_resamples=5)

    predictions = interaction_predictions()
    row = predictions[
        predictions["candidate_id"] == "c1_pick_interactions_c0p01"
    ].index[0]
    predictions.loc[row, "sample_id"] = "changed-sample"
    with pytest.raises(
        InteractionSelectionError,
        match="sample alignment",
    ):
        select_interaction_candidate(predictions, n_resamples=5)


@pytest.mark.parametrize(
    ("column", "value", "message"),
    [
        ("radiant_win", 2, "radiant_win"),
        ("candidate_probability", 1.01, "candidate_probability"),
        ("frozen_b1_probability", -0.01, "frozen_b1_probability"),
        ("canonical_b0_probability", float("nan"), "canonical_b0_probability"),
    ],
)
def test_rejects_invalid_targets_and_probabilities(
    column: str,
    value: object,
    message: str,
) -> None:
    predictions = interaction_predictions()
    predictions.loc[0, column] = value

    with pytest.raises(InteractionSelectionError, match=message):
        select_interaction_candidate(predictions, n_resamples=5)


@pytest.mark.parametrize(
    ("parameter", "value", "message"),
    [
        (
            "minimum_recent_log_loss_improvement",
            -0.001,
            "improvement",
        ),
        ("practical_log_loss_tie", -0.001, "tie"),
        (
            "maximum_single_fold_log_loss_regression",
            -0.001,
            "regression",
        ),
    ],
)
def test_rejects_negative_policy_thresholds(
    parameter: str,
    value: float,
    message: str,
) -> None:
    with pytest.raises(InteractionSelectionError, match=message):
        select_interaction_candidate(
            interaction_predictions(),
            n_resamples=5,
            **{parameter: value},
        )
