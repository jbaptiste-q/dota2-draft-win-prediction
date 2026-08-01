"""Focused tests for train-only Draft AI pick interactions."""

from __future__ import annotations

import pandas as pd
import pytest
from scipy.sparse import csr_matrix

from src.draft_ai_modeling.features import FeatureVariant
from src.draft_ai_modeling.interaction_features import (
    MIN_INTERACTION_ROW_SUPPORT,
    PickInteractionTransformer,
)


def pick_row(
    radiant: tuple[str, str, str, str, str],
    dire: tuple[str, str, str, str, str],
) -> dict[str, object]:
    row: dict[str, object] = {
        "sample_id": "ignored",
        "radiant_win": True,
        "patch": "ignored",
    }
    for slot, hero in enumerate(radiant, start=1):
        row[f"radiant_pick_slot_{slot}"] = hero
    for slot, hero in enumerate(dire, start=1):
        row[f"dire_pick_slot_{slot}"] = hero
    for side in ("radiant", "dire"):
        for slot in range(1, 8):
            row[f"{side}_ban_slot_{slot}"] = f"ignored-{side}-{slot}"
    return row


def repeated_training_frame(rows: int = 50) -> pd.DataFrame:
    return pd.DataFrame(
        [
            pick_row(
                ("a", "b", "c", "d", "e"),
                ("f", "g", "h", "i", "j"),
            )
            for _ in range(rows)
        ]
    )


def test_extends_b1_with_stable_supported_interactions() -> None:
    frame = repeated_training_frame()
    transformer = PickInteractionTransformer().fit(frame)
    result = transformer.transform_with_audit(frame.iloc[:1])
    names = transformer.get_feature_names_out().tolist()
    main_names = transformer.main_transformer_.get_feature_names_out().tolist()

    assert isinstance(result.matrix, csr_matrix)
    assert names[: len(main_names)] == main_names
    assert transformer.main_transformer_.variant_ == (
        FeatureVariant.B1_PICK_PRESENCE
    )
    assert len(transformer.same_side_pairs_) == 20
    assert len(transformer.counter_pairs_) == 25
    assert result.matrix.shape == (
        1,
        len(main_names) + 20 * 2 + 25,
    )
    assert result.audit["emitted_same_side_activations"] == 20
    assert result.audit["emitted_counter_activations"] == 25
    assert result.audit["ignored_unseen_interaction_activations"] == 0
    assert result.audit["ignored_unsupported_interaction_activations"] == 0
    assert all(
        "ban" not in name
        and "slot" not in name
        and "radiant_win" not in name
        and "patch" not in name
        for name in names
    )


def test_same_side_support_is_combined_but_output_groups_are_separate() -> None:
    rows: list[dict[str, object]] = []
    for _ in range(25):
        rows.append(
            pick_row(
                ("x", "y", "a", "b", "c"),
                ("d", "e", "f", "g", "h"),
            )
        )
    for _ in range(25):
        rows.append(
            pick_row(
                ("a", "b", "c", "d", "e"),
                ("x", "y", "f", "g", "h"),
            )
        )
    transformer = PickInteractionTransformer().fit(pd.DataFrame(rows))
    names = transformer.get_feature_names_out().tolist()

    assert transformer.same_side_support_[("x", "y")] == 50
    assert "interaction::radiant_synergy::hero::x::hero::y" in names
    assert "interaction::dire_synergy::hero::x::hero::y" in names


def test_counter_support_is_exactly_oriented() -> None:
    rows: list[dict[str, object]] = []
    for _ in range(30):
        rows.append(
            pick_row(
                ("x", "a", "b", "c", "d"),
                ("z", "e", "f", "g", "h"),
            )
        )
    for _ in range(30):
        rows.append(
            pick_row(
                ("z", "a", "b", "c", "d"),
                ("x", "e", "f", "g", "h"),
            )
        )
    transformer = PickInteractionTransformer().fit(pd.DataFrame(rows))

    assert ("x", "z") not in transformer.counter_pairs_
    assert ("z", "x") not in transformer.counter_pairs_


def test_support_threshold_is_fixed_at_fifty_rows() -> None:
    exact = PickInteractionTransformer().fit(repeated_training_frame(50))
    below = PickInteractionTransformer().fit(repeated_training_frame(49))

    assert MIN_INTERACTION_ROW_SUPPORT == 50
    assert ("a", "b") in exact.same_side_pairs_
    assert ("a", "f") in exact.counter_pairs_
    assert below.same_side_pairs_ == ()
    assert below.counter_pairs_ == ()


def test_contract_and_fingerprint_ignore_training_row_order() -> None:
    frame = repeated_training_frame()
    first = PickInteractionTransformer().fit(frame)
    second = PickInteractionTransformer().fit(
        frame.sample(frac=1, random_state=17)
    )

    assert first.fingerprint == second.fingerprint
    assert first.feature_contract() == second.feature_contract()
    assert first.get_feature_names_out().tolist() == (
        second.get_feature_names_out().tolist()
    )


def test_unseen_and_known_unsupported_interactions_are_ignored_and_audited() -> None:
    transformer = PickInteractionTransformer().fit(
        repeated_training_frame()
    )
    future = pd.DataFrame(
        [
            pick_row(
                ("new-hero", "b", "c", "d", "e"),
                ("a", "g", "h", "i", "j"),
            )
        ]
    )
    result = transformer.transform_with_audit(future)

    assert result.audit["ignored_unseen_same_side_activations"] == 4
    assert result.audit["ignored_unseen_counter_activations"] == 5
    assert result.audit["ignored_unsupported_interaction_activations"] > 0
    assert result.audit["interaction_nonzero_values"] == (
        result.audit["emitted_interaction_activations"]
    )
    assert result.matrix.shape[1] == len(
        transformer.get_feature_names_out()
    )


def test_training_only_support_does_not_expand_on_transform() -> None:
    transformer = PickInteractionTransformer().fit(
        repeated_training_frame()
    )
    fingerprint = transformer.fingerprint
    names = transformer.get_feature_names_out().tolist()
    unsupported = pd.DataFrame(
        [
            pick_row(
                ("a", "f", "b", "g", "c"),
                ("d", "h", "e", "i", "j"),
            )
            for _ in range(100)
        ]
    )

    transformer.transform(unsupported)

    assert transformer.fingerprint == fingerprint
    assert transformer.get_feature_names_out().tolist() == names


def test_only_pick_columns_are_required_and_validated() -> None:
    frame = repeated_training_frame()
    picks_only = frame[
        [
            column
            for column in frame.columns
            if "_pick_slot_" in column
        ]
    ]
    transformer = PickInteractionTransformer().fit(picks_only)
    assert transformer.transform(picks_only).shape[0] == len(picks_only)

    with pytest.raises(ValueError, match="missing pick columns"):
        transformer.transform(
            picks_only.drop(columns=["dire_pick_slot_5"])
        )
