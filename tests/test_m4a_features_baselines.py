"""Offline tests for Milestone 4A features and unfitted baselines."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from scipy.sparse import csr_matrix
from sklearn.dummy import DummyClassifier
from sklearn.exceptions import NotFittedError
from sklearn.linear_model import LogisticRegression
from sklearn.utils.validation import check_is_fitted

from src.draft_ai_modeling.baselines import (
    BASELINE_FEATURE_VARIANTS,
    BASELINE_SPECS,
    BaselineId,
    baseline_fingerprint,
    create_unfitted_estimator,
    get_baseline_spec,
)
from src.draft_ai_modeling.features import (
    EXCLUDED_MODEL_COLUMNS,
    FeatureVariant,
    DraftFeatureTransformer,
)


def draft_row(prefix: str, *, radiant_win: bool) -> dict[str, object]:
    """Create one complete canonical supervised row with unique hero keys."""

    row: dict[str, object] = {
        "sample_id": f"{prefix}-sample",
        "game_key": f"{prefix}-game",
        "source_game_id": f"{prefix}-source-game",
        "game_index": 1,
        "source_match_id": f"{prefix}-match",
        "match_start_utc": pd.Timestamp("2025-01-01", tz="UTC"),
        "patch": "7.38",
        "liquipedia_tier": "1",
        "tournament": "Synthetic Cup",
        "series": "Group Stage",
        "radiant_team_key": "radiant-team",
        "dire_team_key": "dire-team",
        "radiant_win": radiant_win,
        "duration_seconds": 1800,
        "winner_team_slot": 1 if radiant_win else 2,
    }
    for side in ("radiant", "dire"):
        for slot in range(1, 6):
            row[f"{side}_pick_slot_{slot}"] = f"{prefix}-{side}-pick-{slot}"
        for slot in range(1, 8):
            row[f"{side}_ban_slot_{slot}"] = f"{prefix}-{side}-ban-{slot}"
    return row


def training_frame() -> pd.DataFrame:
    """Return two rows whose vocabularies are intentionally distinct."""

    return pd.DataFrame(
        [
            draft_row("alpha", radiant_win=True),
            draft_row("beta", radiant_win=False),
        ]
    )


def feature_position(
    transformer: DraftFeatureTransformer,
    name: str,
) -> int:
    return transformer.get_feature_names_out().tolist().index(name)


def test_b1_vocabulary_is_training_only_and_unknown_is_explicit() -> None:
    train = training_frame()
    transformer = DraftFeatureTransformer(
        FeatureVariant.B1_PICK_PRESENCE
    ).fit(train)
    future = pd.DataFrame([draft_row("future", radiant_win=True)])
    future.loc[0, "radiant_pick_slot_1"] = "alpha-radiant-pick-1"

    matrix = transformer.transform(future)
    names = transformer.get_feature_names_out().tolist()

    assert isinstance(matrix, csr_matrix)
    assert "future-radiant-pick-2" not in transformer.hero_vocabulary_
    assert (
        matrix[
            0,
            feature_position(
                transformer,
                "presence::radiant_pick::hero::alpha-radiant-pick-1",
            ),
        ]
        == 1
    )
    assert (
        matrix[
            0,
            feature_position(
                transformer,
                "presence::radiant_pick::hero::__UNKNOWN__",
            ),
        ]
        == 4
    )
    assert (
        matrix[
            0,
            feature_position(
                transformer,
                "presence::dire_pick::hero::__UNKNOWN__",
            ),
        ]
        == 5
    )
    assert not EXCLUDED_MODEL_COLUMNS.intersection(names)


def test_b2_tracks_unknown_picks_and_bans_in_separate_groups() -> None:
    transformer = DraftFeatureTransformer(
        FeatureVariant.B2_PICK_BAN_PRESENCE
    ).fit(training_frame())
    future = pd.DataFrame([draft_row("future", radiant_win=False)])

    matrix = transformer.transform(future)

    for group, expected_count in (
        ("radiant_pick", 5),
        ("dire_pick", 5),
        ("radiant_ban", 7),
        ("dire_ban", 7),
    ):
        position = feature_position(
            transformer,
            f"presence::{group}::hero::__UNKNOWN__",
        )
        assert matrix[0, position] == expected_count


def test_b3_preserves_per_team_slots_without_global_order_inference() -> None:
    train = training_frame()
    transformer = DraftFeatureTransformer(
        FeatureVariant.B3_SLOT_AWARE
    ).fit(train)
    first = draft_row("alpha", radiant_win=True)
    swapped = dict(first)
    swapped["radiant_pick_slot_1"] = first["radiant_pick_slot_2"]
    swapped["radiant_pick_slot_2"] = first["radiant_pick_slot_1"]

    matrix = transformer.transform(pd.DataFrame([first, swapped]))
    hero_one = "alpha-radiant-pick-1"
    slot_one = feature_position(
        transformer,
        f"slot::radiant_pick_slot_1::hero::{hero_one}",
    )
    slot_two = feature_position(
        transformer,
        f"slot::radiant_pick_slot_2::hero::{hero_one}",
    )

    assert matrix.shape[0] == 2
    assert np.diff(matrix.indptr).tolist() == [24, 24]
    assert matrix[0, slot_one] == 1
    assert matrix[0, slot_two] == 0
    assert matrix[1, slot_one] == 0
    assert matrix[1, slot_two] == 1
    assert not any(
        "global" in name or "first_pick" in name
        for name in transformer.get_feature_names_out()
    )


def test_b3_uses_a_distinct_unknown_feature_for_each_slot() -> None:
    transformer = DraftFeatureTransformer(
        FeatureVariant.B3_SLOT_AWARE
    ).fit(training_frame())
    future = draft_row("alpha", radiant_win=True)
    future["dire_ban_slot_7"] = "newly-added-hero"

    matrix = transformer.transform(pd.DataFrame([future]))
    unknown_position = feature_position(
        transformer,
        "slot::dire_ban_slot_7::hero::__UNKNOWN__",
    )

    assert matrix[0, unknown_position] == 1
    assert np.diff(matrix.indptr).tolist() == [24]


@pytest.mark.parametrize("variant", list(FeatureVariant))
def test_feature_contract_is_deterministic_and_ignores_row_order(
    variant: FeatureVariant,
) -> None:
    frame = training_frame()
    first = DraftFeatureTransformer(variant).fit(frame)
    second = DraftFeatureTransformer(variant).fit(
        frame.iloc[::-1].reset_index(drop=True)
    )

    assert first.hero_vocabulary_ == second.hero_vocabulary_
    assert first.get_feature_names_out().tolist() == (
        second.get_feature_names_out().tolist()
    )
    assert first.feature_contract() == second.feature_contract()
    assert first.fingerprint == second.fingerprint


@pytest.mark.parametrize("variant", list(FeatureVariant))
def test_target_identifiers_context_and_postgame_fields_never_enter_features(
    variant: FeatureVariant,
) -> None:
    frame = training_frame()
    transformer = DraftFeatureTransformer(variant).fit(frame)
    original = transformer.transform(frame)
    changed = frame.copy()
    changed["radiant_win"] = ~changed["radiant_win"]
    changed["duration_seconds"] = [1, 2]
    changed["winner_team_slot"] = [2, 1]
    changed["patch"] = ["unknown-a", "unknown-b"]
    changed["source_match_id"] = ["changed-a", "changed-b"]
    transformed = transformer.transform(changed)

    assert (original != transformed).nnz == 0
    assert not EXCLUDED_MODEL_COLUMNS.intersection(
        transformer.get_feature_names_out()
    )


def test_unfitted_baseline_factories_match_the_declared_feature_contracts() -> None:
    assert set(BASELINE_SPECS) == set(BaselineId)
    assert BASELINE_FEATURE_VARIANTS[BaselineId.B0_EMPIRICAL_PRIOR] is None
    assert BASELINE_FEATURE_VARIANTS[BaselineId.B1_PICK_PRESENCE] == (
        FeatureVariant.B1_PICK_PRESENCE
    )
    assert BASELINE_FEATURE_VARIANTS[BaselineId.B2_PICK_BAN_PRESENCE] == (
        FeatureVariant.B2_PICK_BAN_PRESENCE
    )
    assert BASELINE_FEATURE_VARIANTS[BaselineId.B3_SLOT_AWARE] == (
        FeatureVariant.B3_SLOT_AWARE
    )
    assert get_baseline_spec("B0").feature_profile == "none"

    estimators = {
        baseline_id: create_unfitted_estimator(baseline_id)
        for baseline_id in BaselineId
    }
    assert isinstance(estimators[BaselineId.B0_EMPIRICAL_PRIOR], DummyClassifier)
    assert all(
        isinstance(estimators[baseline_id], LogisticRegression)
        for baseline_id in (
            BaselineId.B1_PICK_PRESENCE,
            BaselineId.B2_PICK_BAN_PRESENCE,
            BaselineId.B3_SLOT_AWARE,
        )
    )
    for estimator in estimators.values():
        with pytest.raises(NotFittedError):
            check_is_fitted(estimator)


def test_estimator_and_feature_fingerprints_are_stable() -> None:
    first_estimator = create_unfitted_estimator("B1", random_state=7)
    second_estimator = create_unfitted_estimator("B1", random_state=7)

    assert first_estimator is not second_estimator
    assert first_estimator.get_params() == second_estimator.get_params()
    assert baseline_fingerprint("B1") == (
        baseline_fingerprint(BaselineId.B1_PICK_PRESENCE)
    )
    assert baseline_fingerprint("B1", random_state=7) != (
        baseline_fingerprint("B1", random_state=8)
    )
