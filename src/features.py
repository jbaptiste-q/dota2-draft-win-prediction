"""Leakage-aware feature engineering for Dota 2 draft data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
import pandas as pd


SPLIT_ORDER = ("train", "validation", "test")
TRAIN_CUTOFF = pd.Timestamp("2022-11-11 00:00:00")
VALIDATION_CUTOFF = pd.Timestamp("2023-11-19 08:14:29")
TARGET_COLUMN = "radiant_win"
DATE_COLUMN = "match_start_date_time"
PATCH_COLUMN = "game_version_id"

HERO_ID_COLUMNS = tuple(
    f"{side}_player_{slot}_hero_id"
    for side in ("radiant", "dire")
    for slot in range(1, 6)
)

FORBIDDEN_FEATURE_COLUMNS = frozenset(
    {
        "match_id",
        DATE_COLUMN,
        "split",
        TARGET_COLUMN,
        "winner_id",
    }
)


@dataclass(frozen=True)
class PreparedFeatures:
    """Container returned by the complete feature preparation workflow."""

    frame: pd.DataFrame
    features: pd.DataFrame
    target: pd.Series
    builder: "DraftFeatureBuilder"


def require_columns(
    frame: pd.DataFrame,
    required_columns: Sequence[str],
    context: str,
) -> None:
    """Raise a clear error when required input columns are missing."""

    missing_columns = sorted(set(required_columns).difference(frame.columns))
    if missing_columns:
        missing_text = ", ".join(missing_columns)
        raise ValueError(f"{context} is missing required columns: {missing_text}")


def add_chronological_split(
    frame: pd.DataFrame,
    train_cutoff: pd.Timestamp = TRAIN_CUTOFF,
    validation_cutoff: pd.Timestamp = VALIDATION_CUTOFF,
) -> pd.DataFrame:
    """Return a copy with train, validation, and test labels based on time."""

    require_columns(frame, [DATE_COLUMN], "Input data")
    train_cutoff = pd.Timestamp(train_cutoff)
    validation_cutoff = pd.Timestamp(validation_cutoff)

    if train_cutoff >= validation_cutoff:
        raise ValueError("The train cutoff must be earlier than the validation cutoff.")

    result = frame.copy()
    result[DATE_COLUMN] = pd.to_datetime(result[DATE_COLUMN], errors="raise")

    if result[DATE_COLUMN].isna().any():
        raise ValueError(f"{DATE_COLUMN} contains missing values.")

    result["split"] = np.select(
        [
            result[DATE_COLUMN] <= train_cutoff,
            result[DATE_COLUMN] <= validation_cutoff,
        ],
        ["train", "validation"],
        default="test",
    )
    return result


class DraftFeatureBuilder:
    """Learn train-only vocabularies and create side-aware draft features."""

    def __init__(self) -> None:
        self.hero_vocabulary_: tuple[int, ...] | None = None
        self.patch_vocabulary_: tuple[int, ...] | None = None
        self.feature_names_: tuple[str, ...] | None = None

    def fit(self, frame: pd.DataFrame) -> "DraftFeatureBuilder":
        """Learn hero and patch vocabularies from training rows only."""

        self._validate_input(frame)
        if frame.empty:
            raise ValueError("DraftFeatureBuilder cannot fit an empty data frame.")

        hero_values = frame.loc[:, HERO_ID_COLUMNS].to_numpy().ravel()
        if pd.isna(hero_values).any():
            raise ValueError("Hero ID columns contain missing values.")

        patch_values = frame[PATCH_COLUMN]
        if patch_values.isna().any():
            raise ValueError(f"{PATCH_COLUMN} contains missing values.")

        self.hero_vocabulary_ = tuple(
            sorted(int(hero_id) for hero_id in pd.unique(hero_values))
        )
        self.patch_vocabulary_ = tuple(
            sorted(int(patch_id) for patch_id in patch_values.unique())
        )

        hero_feature_names = tuple(
            f"hero_{hero_id}" for hero_id in self.hero_vocabulary_
        )
        unknown_hero_names = (
            "unknown_radiant_hero_count",
            "unknown_dire_hero_count",
        )
        patch_feature_names = tuple(
            f"patch_{patch_id}" for patch_id in self.patch_vocabulary_
        ) + ("patch_unknown",)
        self.feature_names_ = (
            hero_feature_names + unknown_hero_names + patch_feature_names
        )
        return self

    def transform(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Transform matches using the vocabularies learned during fit."""

        self._require_fitted()
        self._validate_input(frame)

        hero_features, unknown_hero_features = self._build_hero_features(frame)
        patch_features = self._build_patch_features(frame)
        features = pd.concat(
            [hero_features, unknown_hero_features, patch_features],
            axis=1,
        ).astype(np.int8)

        return features.reindex(columns=self.feature_names_, fill_value=0)

    def fit_transform(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Fit the vocabularies and transform the same rows."""

        return self.fit(frame).transform(frame)

    def get_feature_names_out(self) -> np.ndarray:
        """Return feature names in the exact transform output order."""

        self._require_fitted()
        return np.asarray(self.feature_names_, dtype=object)

    def _build_hero_features(
        self,
        frame: pd.DataFrame,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        vocabulary = pd.Index(self.hero_vocabulary_, dtype="int64")
        matrix = np.zeros((len(frame), len(vocabulary)), dtype=np.int8)
        row_positions = np.arange(len(frame))
        unknown_counts = {
            "unknown_radiant_hero_count": np.zeros(len(frame), dtype=np.int8),
            "unknown_dire_hero_count": np.zeros(len(frame), dtype=np.int8),
        }

        for side, side_value in (("radiant", 1), ("dire", -1)):
            unknown_column = f"unknown_{side}_hero_count"
            for slot in range(1, 6):
                source_column = f"{side}_player_{slot}_hero_id"
                hero_values = frame[source_column].to_numpy(dtype="int64")
                vocabulary_positions = vocabulary.get_indexer(hero_values)
                known_mask = vocabulary_positions >= 0
                matrix[
                    row_positions[known_mask],
                    vocabulary_positions[known_mask],
                ] = side_value
                unknown_counts[unknown_column] += (~known_mask).astype(np.int8)

        hero_features = pd.DataFrame(
            matrix,
            index=frame.index,
            columns=[f"hero_{hero_id}" for hero_id in vocabulary],
        )
        unknown_features = pd.DataFrame(unknown_counts, index=frame.index)
        return hero_features, unknown_features

    def _build_patch_features(self, frame: pd.DataFrame) -> pd.DataFrame:
        known_patch_mask = frame[PATCH_COLUMN].isin(self.patch_vocabulary_)
        known_patch_values = frame[PATCH_COLUMN].where(known_patch_mask)
        categorical = pd.Categorical(
            known_patch_values,
            categories=self.patch_vocabulary_,
        )
        patch_features = pd.get_dummies(
            categorical,
            prefix="patch",
            dtype=np.int8,
        )
        patch_features.index = frame.index
        patch_features["patch_unknown"] = (~known_patch_mask).astype(np.int8)
        return patch_features

    def _validate_input(self, frame: pd.DataFrame) -> None:
        require_columns(
            frame,
            [*HERO_ID_COLUMNS, PATCH_COLUMN],
            "Draft feature input",
        )

    def _require_fitted(self) -> None:
        if (
            self.hero_vocabulary_ is None
            or self.patch_vocabulary_ is None
            or self.feature_names_ is None
        ):
            raise RuntimeError("DraftFeatureBuilder must be fitted before transform.")


def build_target(frame: pd.DataFrame) -> pd.Series:
    """Return the binary Radiant-win target as int8."""

    require_columns(frame, [TARGET_COLUMN], "Target input")
    target = frame[TARGET_COLUMN]

    if target.isna().any():
        raise ValueError(f"{TARGET_COLUMN} contains missing values.")

    unique_values = set(target.unique().tolist())
    if not unique_values.issubset({0, 1, False, True}):
        raise ValueError(f"{TARGET_COLUMN} must contain only binary values.")

    return target.astype(np.int8).rename(TARGET_COLUMN)


def validate_feature_matrix(
    features: pd.DataFrame,
    builder: DraftFeatureBuilder,
) -> None:
    """Validate the structural assumptions used by the baseline model."""

    expected_columns = builder.get_feature_names_out().tolist()
    if features.columns.tolist() != expected_columns:
        raise ValueError("Feature columns do not match the fitted builder.")
    if features.isna().any().any():
        raise ValueError("The feature matrix contains missing values.")
    if features.columns.duplicated().any():
        raise ValueError("The feature matrix contains duplicate columns.")
    if not FORBIDDEN_FEATURE_COLUMNS.isdisjoint(features.columns):
        raise ValueError("The feature matrix contains a forbidden leakage column.")

    hero_columns = [f"hero_{hero_id}" for hero_id in builder.hero_vocabulary_]
    hero_values = set(np.unique(features[hero_columns].to_numpy()).tolist())
    if not hero_values.issubset({-1, 0, 1}):
        raise ValueError("Hero features must contain only -1, 0, or 1.")

    known_hero_counts = features[hero_columns].ne(0).sum(axis=1)
    unknown_hero_counts = features[
        ["unknown_radiant_hero_count", "unknown_dire_hero_count"]
    ].sum(axis=1)
    if not (known_hero_counts + unknown_hero_counts).eq(10).all():
        raise ValueError("Every match must account for exactly ten hero picks.")

    patch_columns = [
        f"patch_{patch_id}" for patch_id in builder.patch_vocabulary_
    ] + ["patch_unknown"]
    if not features[patch_columns].sum(axis=1).eq(1).all():
        raise ValueError("Every match must activate exactly one patch feature.")


def prepare_features(
    frame: pd.DataFrame,
    train_cutoff: pd.Timestamp = TRAIN_CUTOFF,
    validation_cutoff: pd.Timestamp = VALIDATION_CUTOFF,
) -> PreparedFeatures:
    """Run chronological splitting and train-only feature preparation."""

    split_frame = add_chronological_split(
        frame,
        train_cutoff=train_cutoff,
        validation_cutoff=validation_cutoff,
    )
    train_frame = split_frame.loc[split_frame["split"].eq("train")]
    if train_frame.empty:
        raise ValueError("The chronological split produced an empty training set.")

    builder = DraftFeatureBuilder().fit(train_frame)
    features = builder.transform(split_frame)
    target = build_target(split_frame)
    validate_feature_matrix(features, builder)

    if not features.index.equals(target.index):
        raise ValueError("Feature and target indexes do not align.")

    return PreparedFeatures(
        frame=split_frame,
        features=features,
        target=target,
        builder=builder,
    )
