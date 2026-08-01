"""Leakage-safe, train-fitted feature transforms for Draft AI baselines.

The transformers in this module consume only the canonical supervised draft
columns. They deliberately ignore identifiers, context, time, and target
columns, and they never learn a vocabulary from validation or test rows.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from enum import StrEnum
from urllib.parse import quote

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.utils.validation import check_is_fitted

from .contracts import (
    CURRENT_FEATURE_CONTRACT,
    FEATURE_CONTRACT_VERSION,
    UNKNOWN_CATEGORY_TOKEN,
)


UNKNOWN_HERO_TOKEN = UNKNOWN_CATEGORY_TOKEN

RADIANT_PICK_COLUMNS = CURRENT_FEATURE_CONTRACT.radiant_pick_columns
DIRE_PICK_COLUMNS = CURRENT_FEATURE_CONTRACT.dire_pick_columns
RADIANT_BAN_COLUMNS = CURRENT_FEATURE_CONTRACT.radiant_ban_columns
DIRE_BAN_COLUMNS = CURRENT_FEATURE_CONTRACT.dire_ban_columns


class FeatureVariant(StrEnum):
    """Supported deterministic feature contracts for the first baselines."""

    B1_PICK_PRESENCE = "b1-pick-presence"
    B2_PICK_BAN_PRESENCE = "b2-pick-ban-presence"
    B3_SLOT_AWARE = "b3-slot-aware"


PICK_PRESENCE_GROUPS = (
    ("radiant_pick", RADIANT_PICK_COLUMNS),
    ("dire_pick", DIRE_PICK_COLUMNS),
)
PICK_BAN_PRESENCE_GROUPS = (
    *PICK_PRESENCE_GROUPS,
    ("radiant_ban", RADIANT_BAN_COLUMNS),
    ("dire_ban", DIRE_BAN_COLUMNS),
)
SLOT_COLUMNS = (
    *RADIANT_PICK_COLUMNS,
    *DIRE_PICK_COLUMNS,
    *RADIANT_BAN_COLUMNS,
    *DIRE_BAN_COLUMNS,
)

EXCLUDED_MODEL_COLUMNS = frozenset(
    {
        *CURRENT_FEATURE_CONTRACT.leakage_columns,
        *CURRENT_FEATURE_CONTRACT.context_ablation_columns,
    }
)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _encoded_hero_name(hero_key: str) -> str:
    """Return an unambiguous, deterministic hero-key component."""

    return quote(hero_key, safe="._-")


def _presence_groups(
    variant: FeatureVariant,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if variant == FeatureVariant.B1_PICK_PRESENCE:
        return PICK_PRESENCE_GROUPS
    if variant == FeatureVariant.B2_PICK_BAN_PRESENCE:
        return PICK_BAN_PRESENCE_GROUPS
    raise ValueError(f"{variant.value} is not a presence feature variant.")


def required_columns(variant: FeatureVariant | str) -> tuple[str, ...]:
    """Return the exact canonical draft columns consumed by a variant."""

    resolved = FeatureVariant(variant)
    selected = (
        SLOT_COLUMNS
        if resolved == FeatureVariant.B3_SLOT_AWARE
        else tuple(
            column
            for _, columns in _presence_groups(resolved)
            for column in columns
        )
    )
    return CURRENT_FEATURE_CONTRACT.validate_source_feature_columns(
        selected
    )


def _validate_frame(
    frame: pd.DataFrame,
    columns: Sequence[str],
    *,
    context: str,
    allow_empty: bool,
) -> None:
    if not isinstance(frame, pd.DataFrame):
        raise TypeError(f"{context} must be a pandas DataFrame.")
    if frame.columns.duplicated().any():
        raise ValueError(f"{context} contains duplicate column names.")
    missing = sorted(set(columns).difference(frame.columns))
    if missing:
        raise ValueError(
            f"{context} is missing required draft columns: "
            + ", ".join(missing)
        )
    if not allow_empty and frame.empty:
        raise ValueError(f"{context} must contain at least one row.")
    if frame.loc[:, list(columns)].isna().any().any():
        raise ValueError(f"{context} contains missing draft hero keys.")
    for column in columns:
        invalid = frame[column].map(
            lambda value: not isinstance(value, str) or not value
        )
        if invalid.any():
            raise ValueError(
                f"{context} contains an invalid hero key in {column}."
            )


def _feature_names(
    variant: FeatureVariant,
    vocabulary: Sequence[str],
) -> tuple[str, ...]:
    encoded = tuple(_encoded_hero_name(value) for value in vocabulary)
    if variant == FeatureVariant.B3_SLOT_AWARE:
        names: list[str] = []
        for column in SLOT_COLUMNS:
            names.extend(
                f"slot::{column}::hero::{hero_key}"
                for hero_key in encoded
            )
            names.append(f"slot::{column}::hero::{UNKNOWN_HERO_TOKEN}")
        return tuple(names)

    names = []
    for group, _ in _presence_groups(variant):
        names.extend(
            f"presence::{group}::hero::{hero_key}"
            for hero_key in encoded
        )
        names.append(f"presence::{group}::hero::{UNKNOWN_HERO_TOKEN}")
    return tuple(names)


def validate_feature_matrix(
    matrix: csr_matrix,
    feature_names: Sequence[str],
    *,
    expected_rows: int,
) -> None:
    """Fail on malformed, non-finite, duplicated, or leaked feature output."""

    if not isinstance(matrix, csr_matrix):
        raise TypeError("Draft feature output must be a CSR sparse matrix.")
    if matrix.shape != (expected_rows, len(feature_names)):
        raise ValueError("Draft feature matrix shape does not match its names.")
    if len(feature_names) != len(set(feature_names)):
        raise ValueError("Draft feature names must be unique.")
    if EXCLUDED_MODEL_COLUMNS.intersection(feature_names):
        raise ValueError("Draft feature names contain a forbidden model column.")
    if matrix.data.size and not np.isfinite(matrix.data).all():
        raise ValueError("Draft feature matrix contains a non-finite value.")
    if matrix.data.size and (matrix.data < 0).any():
        raise ValueError("Draft feature matrix contains a negative value.")


class DraftFeatureTransformer(
    TransformerMixin,
    BaseEstimator,
):
    """Fit a hero vocabulary on training rows and create sparse draft features."""

    def __init__(self, variant: FeatureVariant | str):
        self.variant = variant

    def fit(
        self,
        frame: pd.DataFrame,
        y: object = None,
    ) -> "DraftFeatureTransformer":
        """Learn a sorted hero vocabulary from this training frame only."""

        del y
        variant = FeatureVariant(self.variant)
        source_columns = required_columns(variant)
        _validate_frame(
            frame,
            source_columns,
            context="Draft feature training frame",
            allow_empty=False,
        )
        vocabulary = tuple(
            sorted(
                {
                    value
                    for column in source_columns
                    for value in frame[column].tolist()
                }
            )
        )
        if UNKNOWN_HERO_TOKEN in vocabulary:
            raise ValueError(
                f"{UNKNOWN_HERO_TOKEN!r} is reserved for unseen heroes."
            )

        feature_names = _feature_names(variant, vocabulary)
        payload = {
            "contract_version": FEATURE_CONTRACT_VERSION,
            "source_contract_profile": (
                CURRENT_FEATURE_CONTRACT.default_profile
            ),
            "variant": variant.value,
            "source_columns": list(source_columns),
            "hero_vocabulary": list(vocabulary),
            "unknown_hero_token": UNKNOWN_HERO_TOKEN,
            "unknown_policy": (
                "count per side-and-action group"
                if variant != FeatureVariant.B3_SLOT_AWARE
                else "one explicit token per canonical per-team slot"
            ),
            "feature_names": list(feature_names),
            "output": {
                "format": "scipy.csr_matrix",
                "dtype": "int8",
            },
        }

        self.variant_ = variant
        self.source_columns_ = source_columns
        self.hero_vocabulary_ = vocabulary
        self.hero_to_position_ = {
            hero_key: position
            for position, hero_key in enumerate(vocabulary)
        }
        self.feature_names_ = feature_names
        self.feature_contract_ = payload
        self.feature_fingerprint_ = hashlib.sha256(
            _canonical_json(payload).encode("utf-8")
        ).hexdigest()
        self.n_features_in_ = len(source_columns)
        self.feature_names_in_ = np.asarray(source_columns, dtype=object)

        if EXCLUDED_MODEL_COLUMNS.intersection(source_columns):
            raise ValueError("Feature source columns include forbidden metadata.")
        validate_feature_matrix(
            self._transform_validated(frame),
            feature_names,
            expected_rows=len(frame),
        )
        return self

    def transform(self, frame: pd.DataFrame) -> csr_matrix:
        """Transform rows without modifying the training-fitted vocabulary."""

        check_is_fitted(
            self,
            (
                "variant_",
                "source_columns_",
                "hero_vocabulary_",
                "feature_names_",
                "feature_fingerprint_",
            ),
        )
        _validate_frame(
            frame,
            self.source_columns_,
            context="Draft feature transform frame",
            allow_empty=True,
        )
        matrix = self._transform_validated(frame)
        validate_feature_matrix(
            matrix,
            self.feature_names_,
            expected_rows=len(frame),
        )
        return matrix

    def _transform_validated(self, frame: pd.DataFrame) -> csr_matrix:
        if self.variant_ == FeatureVariant.B3_SLOT_AWARE:
            return self._transform_slots(frame)
        return self._transform_presence(frame)

    def _transform_presence(self, frame: pd.DataFrame) -> csr_matrix:
        vocabulary_size = len(self.hero_vocabulary_)
        group_width = vocabulary_size + 1
        row_positions: list[int] = []
        column_positions: list[int] = []
        values: list[int] = []

        for row_position, (_, row) in enumerate(frame.iterrows()):
            for group_position, (_, columns) in enumerate(
                _presence_groups(self.variant_)
            ):
                base = group_position * group_width
                known_positions: set[int] = set()
                unknown_count = 0
                for column in columns:
                    position = self.hero_to_position_.get(row[column])
                    if position is None:
                        unknown_count += 1
                    else:
                        known_positions.add(position)
                for position in sorted(known_positions):
                    row_positions.append(row_position)
                    column_positions.append(base + position)
                    values.append(1)
                if unknown_count:
                    row_positions.append(row_position)
                    column_positions.append(base + vocabulary_size)
                    values.append(unknown_count)

        matrix = csr_matrix(
            (np.asarray(values, dtype=np.int8), (
                np.asarray(row_positions, dtype=np.int64),
                np.asarray(column_positions, dtype=np.int64),
            )),
            shape=(len(frame), len(self.feature_names_)),
            dtype=np.int8,
        )
        matrix.sort_indices()
        return matrix

    def _transform_slots(self, frame: pd.DataFrame) -> csr_matrix:
        vocabulary_size = len(self.hero_vocabulary_)
        slot_width = vocabulary_size + 1
        row_positions: list[int] = []
        column_positions: list[int] = []

        for row_position, (_, row) in enumerate(frame.iterrows()):
            for slot_position, column in enumerate(SLOT_COLUMNS):
                hero_position = self.hero_to_position_.get(
                    row[column],
                    vocabulary_size,
                )
                row_positions.append(row_position)
                column_positions.append(
                    slot_position * slot_width + hero_position
                )

        matrix = csr_matrix(
            (
                np.ones(len(row_positions), dtype=np.int8),
                (
                    np.asarray(row_positions, dtype=np.int64),
                    np.asarray(column_positions, dtype=np.int64),
                ),
            ),
            shape=(len(frame), len(self.feature_names_)),
            dtype=np.int8,
        )
        matrix.sort_indices()
        return matrix

    def get_feature_names_out(
        self,
        input_features: object = None,
    ) -> np.ndarray:
        """Return stable output names in sparse-matrix column order."""

        del input_features
        check_is_fitted(self, ("feature_names_",))
        return np.asarray(self.feature_names_, dtype=object)

    def feature_contract(self) -> dict[str, object]:
        """Return a detached machine-readable fitted feature contract."""

        check_is_fitted(self, ("feature_contract_",))
        return json.loads(_canonical_json(self.feature_contract_))

    @property
    def fingerprint(self) -> str:
        """Return the content fingerprint of the fitted feature contract."""

        check_is_fitted(self, ("feature_fingerprint_",))
        return self.feature_fingerprint_
