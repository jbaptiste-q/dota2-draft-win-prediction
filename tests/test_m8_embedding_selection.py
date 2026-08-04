"""Offline unit tests for the M8 dual-reference selection gate.

These tests exercise ``select_embedding_candidate`` directly with crafted
synthetic prediction frames, independent of any real model fit, to verify
qualification, tie-break ranking, and malformed-input rejection.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.draft_ai_modeling.embedding_config import (
    load_embedding_experiment_config,
)
from src.draft_ai_modeling.embedding_experiment import (
    EmbeddingExperimentError,
    select_embedding_candidate,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "modeling" / "m8_embeddings.json"
SELECTION_FOLDS = ("2025-Q1", "2025-Q2", "2025-Q3")
GAMES_PER_FOLD = 40


def _config():
    config = load_embedding_experiment_config(
        CONFIG,
        repository_root=ROOT,
        verify_local_artifacts=False,
    )
    config.selection_policy["paired_group_bootstrap"]["replicates"] = 200
    return config


def _candidate_predictions(
    candidate_id: str,
    embedding_dim: int,
    l2: float,
    *,
    accuracy_margin: float,
) -> pd.DataFrame:
    """Build one candidate's synthetic predictions across the selection folds.

    ``accuracy_margin`` controls how far the candidate's probability sits
    from the uninformative 0.5 references toward the true label: 0.0
    reproduces the references exactly (never qualifies), while a large
    positive margin makes the candidate strictly and robustly better.
    """

    rows = []
    game = 0
    for fold in SELECTION_FOLDS:
        for index in range(GAMES_PER_FOLD):
            label = index % 2
            candidate_probability = float(
                np.clip(
                    0.5 + accuracy_margin * (1 if label else -1),
                    1e-6,
                    1 - 1e-6,
                )
            )
            rows.append(
                {
                    "candidate_id": candidate_id,
                    "embedding_dim": embedding_dim,
                    "l2": l2,
                    "evaluation_id": fold,
                    "sample_id": f"{candidate_id}-{game}",
                    "source_match_id": f"match-{game}",
                    "radiant_win": label,
                    "candidate_probability": candidate_probability,
                    "frozen_b1_probability": 0.5,
                    "canonical_b0_probability": 0.5,
                }
            )
            game += 1
    return pd.DataFrame(rows)


def _full_matrix_predictions(
    config,
    *,
    margins: dict[str, float],
) -> pd.DataFrame:
    frames = [
        _candidate_predictions(
            candidate.candidate_id,
            candidate.embedding_dim,
            candidate.l2,
            accuracy_margin=margins[candidate.candidate_id],
        )
        for candidate in config.candidates
    ]
    return pd.concat(frames, ignore_index=True)


def test_no_candidate_qualifies_when_all_match_the_references() -> None:
    config = _config()
    margins = {candidate.candidate_id: 0.0 for candidate in config.candidates}
    predictions = _full_matrix_predictions(config, margins=margins)

    selection = select_embedding_candidate(predictions, config)

    assert selection["selection_status"] == (
        "no_candidate_passed_all_development_gates"
    )
    assert selection["selected_candidate_id"] is None
    assert selection["qualifying_ranking"] == []
    assert selection["audit"]["qualifying_candidate_count"] == 0
    assert selection["not_a_final_champion"] is True
    assert selection["calibration_or_locked_test_used"] is False


def test_exactly_one_strong_candidate_qualifies_and_is_selected() -> None:
    config = _config()
    margins = {candidate.candidate_id: 0.0 for candidate in config.candidates}
    winner = config.candidates[0].candidate_id
    margins[winner] = 0.45
    predictions = _full_matrix_predictions(config, margins=margins)

    selection = select_embedding_candidate(predictions, config)

    assert selection["selected_candidate_id"] == winner
    assert selection["selection_status"] == (
        "development_candidate_selected"
    )
    winning_record = next(
        item
        for item in selection["candidates"]
        if item["candidate_id"] == winner
    )
    assert winning_record["qualifies_as_development_candidate"] is True
    assert winning_record["selection_rank"] == 1
    gates = winning_record["gate_results"]
    assert gates["all_fold_and_pooled_strict_improvements"] is True
    assert gates["paired_canonical_b0_log_loss_upper_below_zero"] is True
    assert gates["paired_frozen_b1_log_loss_upper_below_zero"] is True
    for other in config.candidates:
        if other.candidate_id == winner:
            continue
        loser = next(
            item
            for item in selection["candidates"]
            if item["candidate_id"] == other.candidate_id
        )
        assert loser["qualifies_as_development_candidate"] is False
        assert loser["selection_rank"] is None


def test_tie_break_prefers_smaller_embedding_dim_then_larger_l2() -> None:
    config = _config()
    margins = {candidate.candidate_id: 0.0 for candidate in config.candidates}
    tied_ids = [
        candidate.candidate_id
        for candidate in config.candidates
        if candidate.l2 == 0.01
    ]
    assert len(tied_ids) == 3
    for candidate_id in tied_ids:
        margins[candidate_id] = 0.45
    predictions = _full_matrix_predictions(config, margins=margins)

    selection = select_embedding_candidate(predictions, config)

    assert set(selection["qualifying_ranking"]) == set(tied_ids)
    assert selection["selected_candidate_id"] == "emb_d4_l2_0p01"
    assert selection["qualifying_ranking"][0] == "emb_d4_l2_0p01"


def test_rejects_predictions_missing_a_candidate() -> None:
    config = _config()
    margins = {candidate.candidate_id: 0.0 for candidate in config.candidates}
    predictions = _full_matrix_predictions(config, margins=margins)
    trimmed = predictions[
        predictions["candidate_id"] != config.candidates[0].candidate_id
    ]

    with pytest.raises(EmbeddingExperimentError, match="nine approved"):
        select_embedding_candidate(trimmed, config)


def test_rejects_predictions_with_wrong_candidate_matrix() -> None:
    config = _config()
    margins = {candidate.candidate_id: 0.0 for candidate in config.candidates}
    predictions = _full_matrix_predictions(config, margins=margins)
    mutated = predictions.copy()
    mutated.loc[
        mutated["candidate_id"] == config.candidates[0].candidate_id,
        "l2",
    ] = 0.02

    with pytest.raises(EmbeddingExperimentError, match="nine approved"):
        select_embedding_candidate(mutated, config)
