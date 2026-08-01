"""Train-fitted, explainable pick interactions for the Draft AI.

This transformer extends the existing B1 side-relative pick-presence matrix.
It uses only the ten canonical pick columns and learns interaction support
from the supplied training rows.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from itertools import combinations
from urllib.parse import quote

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix, hstack
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.utils.validation import check_is_fitted

from .features import (
    DIRE_PICK_COLUMNS,
    RADIANT_PICK_COLUMNS,
    DraftFeatureTransformer,
    FeatureVariant,
    validate_feature_matrix,
)


INTERACTION_CONTRACT_VERSION = "dota-draft-pick-interactions-v1"
MIN_INTERACTION_ROW_SUPPORT = 50
PICK_COLUMNS = (*RADIANT_PICK_COLUMNS, *DIRE_PICK_COLUMNS)

HeroPair = tuple[str, str]


@dataclass(frozen=True, slots=True)
class InteractionTransformResult:
    """One sparse transform and its unsupported-interaction audit."""

    matrix: csr_matrix
    audit: dict[str, int]


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _encoded(value: str) -> str:
    return quote(value, safe="._-")


def _unordered_pairs(values: tuple[str, ...]) -> set[HeroPair]:
    return {
        tuple(sorted((first, second)))
        for first, second in combinations(set(values), 2)
    }


def _ordered_counter_pairs(
    radiant: tuple[str, ...],
    dire: tuple[str, ...],
) -> set[HeroPair]:
    return {
        (radiant_hero, dire_hero)
        for radiant_hero in set(radiant)
        for dire_hero in set(dire)
    }


def _row_picks(row: pd.Series) -> tuple[tuple[str, ...], tuple[str, ...]]:
    return (
        tuple(str(row[column]) for column in RADIANT_PICK_COLUMNS),
        tuple(str(row[column]) for column in DIRE_PICK_COLUMNS),
    )


def _validate_pick_frame(
    frame: pd.DataFrame,
    *,
    context: str,
    allow_empty: bool,
) -> None:
    if not isinstance(frame, pd.DataFrame):
        raise TypeError(f"{context} must be a pandas DataFrame.")
    if frame.columns.duplicated().any():
        raise ValueError(f"{context} contains duplicate column names.")
    missing = sorted(set(PICK_COLUMNS).difference(frame.columns))
    if missing:
        raise ValueError(
            f"{context} is missing pick columns: " + ", ".join(missing)
        )
    if not allow_empty and frame.empty:
        raise ValueError(f"{context} cannot be empty.")
    for column in PICK_COLUMNS:
        invalid = frame[column].map(
            lambda value: not isinstance(value, str) or not value
        )
        if invalid.any():
            raise ValueError(
                f"{context} contains an invalid hero key in {column}."
            )


def _same_side_feature_name(side: str, pair: HeroPair) -> str:
    return (
        f"interaction::{side}_synergy::hero::{_encoded(pair[0])}"
        f"::hero::{_encoded(pair[1])}"
    )


def _counter_feature_name(pair: HeroPair) -> str:
    return (
        f"interaction::counter::radiant_hero::{_encoded(pair[0])}"
        f"::dire_hero::{_encoded(pair[1])}"
    )


class PickInteractionTransformer(TransformerMixin, BaseEstimator):
    """Append frequent train-only pick synergies and counters to B1."""

    def __init__(self) -> None:
        pass

    def fit(
        self,
        frame: pd.DataFrame,
        y: object = None,
    ) -> "PickInteractionTransformer":
        """Fit B1 vocabulary and fixed-support interaction vocabularies."""

        del y
        _validate_pick_frame(
            frame,
            context="Pick-interaction training frame",
            allow_empty=False,
        )
        main_transformer = DraftFeatureTransformer(
            FeatureVariant.B1_PICK_PRESENCE
        ).fit(frame)
        same_side_support: Counter[HeroPair] = Counter()
        counter_support: Counter[HeroPair] = Counter()

        for _, row in frame.iterrows():
            radiant, dire = _row_picks(row)
            combined_same_side_pairs = (
                _unordered_pairs(radiant) | _unordered_pairs(dire)
            )
            same_side_support.update(combined_same_side_pairs)
            counter_support.update(_ordered_counter_pairs(radiant, dire))

        same_side_pairs = tuple(
            sorted(
                pair
                for pair, support in same_side_support.items()
                if support >= MIN_INTERACTION_ROW_SUPPORT
            )
        )
        counter_pairs = tuple(
            sorted(
                pair
                for pair, support in counter_support.items()
                if support >= MIN_INTERACTION_ROW_SUPPORT
            )
        )
        main_names = tuple(
            str(value)
            for value in main_transformer.get_feature_names_out()
        )
        interaction_names = (
            *(
                _same_side_feature_name("radiant", pair)
                for pair in same_side_pairs
            ),
            *(
                _same_side_feature_name("dire", pair)
                for pair in same_side_pairs
            ),
            *(_counter_feature_name(pair) for pair in counter_pairs),
        )
        feature_names = (*main_names, *interaction_names)
        payload = {
            "contract_version": INTERACTION_CONTRACT_VERSION,
            "base_feature_variant": FeatureVariant.B1_PICK_PRESENCE.value,
            "base_feature_fingerprint": main_transformer.fingerprint,
            "source_columns": list(PICK_COLUMNS),
            "minimum_row_support": MIN_INTERACTION_ROW_SUPPORT,
            "same_side_support_policy": (
                "unordered pair row support combined across radiant and dire"
            ),
            "same_side_output_groups": [
                "radiant_synergy",
                "dire_synergy",
            ],
            "counter_support_policy": (
                "ordered radiant-hero versus dire-hero row support"
            ),
            "same_side_pairs": [
                {
                    "heroes": list(pair),
                    "training_row_support": same_side_support[pair],
                }
                for pair in same_side_pairs
            ],
            "counter_pairs": [
                {
                    "radiant_hero": pair[0],
                    "dire_hero": pair[1],
                    "training_row_support": counter_support[pair],
                }
                for pair in counter_pairs
            ],
            "feature_names": list(feature_names),
            "unsupported_interaction_policy": "ignore_and_audit",
            "output": {
                "format": "scipy.csr_matrix",
                "dtype": "int8",
                "column_order": (
                    "b1_main_then_radiant_synergy_then_dire_synergy"
                    "_then_oriented_counter"
                ),
            },
        }

        self.main_transformer_ = main_transformer
        self.hero_vocabulary_ = main_transformer.hero_vocabulary_
        self.same_side_pairs_ = same_side_pairs
        self.counter_pairs_ = counter_pairs
        self.same_side_pair_to_position_ = {
            pair: position
            for position, pair in enumerate(same_side_pairs)
        }
        self.counter_pair_to_position_ = {
            pair: position
            for position, pair in enumerate(counter_pairs)
        }
        self.same_side_support_ = {
            pair: int(same_side_support[pair])
            for pair in same_side_pairs
        }
        self.counter_support_ = {
            pair: int(counter_support[pair])
            for pair in counter_pairs
        }
        self.main_feature_count_ = len(main_names)
        self.feature_names_ = feature_names
        self.feature_contract_ = payload
        self.feature_fingerprint_ = hashlib.sha256(
            _canonical_json(payload).encode("utf-8")
        ).hexdigest()
        self.n_features_in_ = len(PICK_COLUMNS)
        self.feature_names_in_ = np.asarray(PICK_COLUMNS, dtype=object)

        fitted = self.transform_with_audit(frame)
        validate_feature_matrix(
            fitted.matrix,
            feature_names,
            expected_rows=len(frame),
        )
        return self

    def _interaction_matrix_and_audit(
        self,
        frame: pd.DataFrame,
    ) -> tuple[csr_matrix, dict[str, int]]:
        same_side_count = len(self.same_side_pairs_)
        interaction_count = same_side_count * 2 + len(self.counter_pairs_)
        row_positions: list[int] = []
        column_positions: list[int] = []
        vocabulary = set(self.hero_vocabulary_)
        audit = {
            "rows": len(frame),
            "candidate_same_side_activations": 0,
            "emitted_same_side_activations": 0,
            "ignored_unseen_same_side_activations": 0,
            "ignored_unsupported_same_side_activations": 0,
            "candidate_counter_activations": 0,
            "emitted_counter_activations": 0,
            "ignored_unseen_counter_activations": 0,
            "ignored_unsupported_counter_activations": 0,
        }

        for row_position, (_, row) in enumerate(frame.iterrows()):
            radiant, dire = _row_picks(row)
            for side_position, picks in enumerate((radiant, dire)):
                for pair in sorted(_unordered_pairs(picks)):
                    audit["candidate_same_side_activations"] += 1
                    position = self.same_side_pair_to_position_.get(pair)
                    if position is not None:
                        row_positions.append(row_position)
                        column_positions.append(
                            side_position * same_side_count + position
                        )
                        audit["emitted_same_side_activations"] += 1
                    elif not set(pair).issubset(vocabulary):
                        audit[
                            "ignored_unseen_same_side_activations"
                        ] += 1
                    else:
                        audit[
                            "ignored_unsupported_same_side_activations"
                        ] += 1

            for pair in sorted(_ordered_counter_pairs(radiant, dire)):
                audit["candidate_counter_activations"] += 1
                position = self.counter_pair_to_position_.get(pair)
                if position is not None:
                    row_positions.append(row_position)
                    column_positions.append(
                        same_side_count * 2 + position
                    )
                    audit["emitted_counter_activations"] += 1
                elif not set(pair).issubset(vocabulary):
                    audit["ignored_unseen_counter_activations"] += 1
                else:
                    audit[
                        "ignored_unsupported_counter_activations"
                    ] += 1

        interaction_matrix = csr_matrix(
            (
                np.ones(len(row_positions), dtype=np.int8),
                (
                    np.asarray(row_positions, dtype=np.int64),
                    np.asarray(column_positions, dtype=np.int64),
                ),
            ),
            shape=(len(frame), interaction_count),
            dtype=np.int8,
        )
        interaction_matrix.sort_indices()
        audit["interaction_feature_columns"] = interaction_count
        audit["emitted_interaction_activations"] = (
            audit["emitted_same_side_activations"]
            + audit["emitted_counter_activations"]
        )
        audit["ignored_unseen_interaction_activations"] = (
            audit["ignored_unseen_same_side_activations"]
            + audit["ignored_unseen_counter_activations"]
        )
        audit["ignored_unsupported_interaction_activations"] = (
            audit["ignored_unsupported_same_side_activations"]
            + audit["ignored_unsupported_counter_activations"]
        )
        return interaction_matrix, audit

    def transform_with_audit(
        self,
        frame: pd.DataFrame,
    ) -> InteractionTransformResult:
        """Return the complete sparse matrix plus ignored-pair counts."""

        check_is_fitted(
            self,
            (
                "main_transformer_",
                "hero_vocabulary_",
                "same_side_pairs_",
                "counter_pairs_",
                "feature_names_",
            ),
        )
        _validate_pick_frame(
            frame,
            context="Pick-interaction transform frame",
            allow_empty=True,
        )
        main = self.main_transformer_.transform(frame)
        interactions, audit = self._interaction_matrix_and_audit(frame)
        matrix = hstack((main, interactions), format="csr", dtype=np.int8)
        matrix.sort_indices()
        validate_feature_matrix(
            matrix,
            self.feature_names_,
            expected_rows=len(frame),
        )
        audit["main_feature_columns"] = self.main_feature_count_
        audit["total_feature_columns"] = len(self.feature_names_)
        audit["main_nonzero_values"] = int(main.nnz)
        audit["interaction_nonzero_values"] = int(interactions.nnz)
        audit["total_nonzero_values"] = int(matrix.nnz)
        return InteractionTransformResult(matrix=matrix, audit=audit)

    def transform(self, frame: pd.DataFrame) -> csr_matrix:
        """Return B1 main effects followed by supported interactions."""

        return self.transform_with_audit(frame).matrix

    def get_feature_names_out(
        self,
        input_features: object = None,
    ) -> np.ndarray:
        """Return stable sparse-column names."""

        del input_features
        check_is_fitted(self, ("feature_names_",))
        return np.asarray(self.feature_names_, dtype=object)

    def feature_contract(self) -> dict[str, object]:
        """Return a detached deterministic fitted contract."""

        check_is_fitted(self, ("feature_contract_",))
        return json.loads(_canonical_json(self.feature_contract_))

    @property
    def fingerprint(self) -> str:
        """Return the content fingerprint of the fitted contract."""

        check_is_fitted(self, ("feature_fingerprint_",))
        return self.feature_fingerprint_


__all__ = [
    "INTERACTION_CONTRACT_VERSION",
    "InteractionTransformResult",
    "MIN_INTERACTION_ROW_SUPPORT",
    "PICK_COLUMNS",
    "PickInteractionTransformer",
]
