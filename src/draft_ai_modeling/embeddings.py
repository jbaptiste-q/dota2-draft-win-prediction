"""Draft-frame adapter for the M8 low-rank hero-embedding model.

This module connects the canonical supervised draft columns to the pure
numpy/scipy model in ``hero_embeddings``.  It reuses the M4A feature
policy: a sorted hero vocabulary fitted only on training rows, with every
unseen hero mapped to one explicit ``__UNKNOWN__`` index.  The unknown
index starts at exactly zero, never occurs in training, and therefore
keeps an exactly zero main effect and embedding, so unknown heroes
contribute zero log-odds at evaluation time.

The core model and its hand-derived gradients live in
``hero_embeddings`` and are re-exported here.  No data loading, split
access, or acquisition dependency exists in either module.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .features import (
    UNKNOWN_HERO_TOKEN,
    FeatureVariant,
    required_columns,
)
from .hero_embeddings import (
    HERO_EMBEDDING_MODEL_VERSION,
    PICKS_PER_SIDE,
    HeroEmbeddingConfig,
    HeroEmbeddingError,
    HeroEmbeddingFitResult,
    HeroEmbeddingParameters,
    compute_objective_and_gradients,
    fit_hero_embedding_model,
    initialize_parameters,
    predict_log_odds,
    predict_probabilities,
)


DRAFT_EMBEDDING_CONTRACT_VERSION = "draft-ai-hero-embedding-features-v1"
PICK_SOURCE_COLUMNS = required_columns(FeatureVariant.B1_PICK_PRESENCE)
RADIANT_SOURCE_COLUMNS = PICK_SOURCE_COLUMNS[:PICKS_PER_SIDE]
DIRE_SOURCE_COLUMNS = PICK_SOURCE_COLUMNS[PICKS_PER_SIDE:]


class DraftEmbeddingError(ValueError):
    """Raised when draft rows violate the hero-embedding feature contract."""


@dataclass(frozen=True, slots=True)
class HeroVocabulary:
    """A train-fitted sorted hero vocabulary with one explicit unknown index."""

    heroes: tuple[str, ...]
    unknown_index: int
    fingerprint: str

    @property
    def hero_count(self) -> int:
        """Total model indices: every known hero plus the unknown index."""

        return len(self.heroes) + 1


@dataclass(frozen=True, slots=True)
class DraftIndexArrays:
    """Model-ready per-side hero indices for one validated draft frame."""

    radiant: np.ndarray
    dire: np.ndarray
    unknown_activations: int


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _validate_draft_frame(frame: pd.DataFrame, *, context: str) -> None:
    if not isinstance(frame, pd.DataFrame):
        raise DraftEmbeddingError(f"{context} must be a pandas DataFrame.")
    missing = sorted(set(PICK_SOURCE_COLUMNS).difference(frame.columns))
    if missing:
        raise DraftEmbeddingError(
            f"{context} is missing required pick columns: "
            + ", ".join(missing)
        )
    selected = frame.loc[:, list(PICK_SOURCE_COLUMNS)]
    if selected.isna().any().any():
        raise DraftEmbeddingError(f"{context} contains missing hero keys.")
    for column in PICK_SOURCE_COLUMNS:
        invalid = frame[column].map(
            lambda value: not isinstance(value, str) or not value
        )
        if invalid.any():
            raise DraftEmbeddingError(
                f"{context} contains an invalid hero key in {column}."
            )


def fit_hero_vocabulary(frame: pd.DataFrame) -> HeroVocabulary:
    """Learn a sorted pick-hero vocabulary from these training rows only."""

    _validate_draft_frame(frame, context="Hero vocabulary training frame")
    if frame.empty:
        raise DraftEmbeddingError(
            "Hero vocabulary training frame must contain at least one row."
        )
    heroes = tuple(
        sorted(
            {
                value
                for column in PICK_SOURCE_COLUMNS
                for value in frame[column].tolist()
            }
        )
    )
    if UNKNOWN_HERO_TOKEN in heroes:
        raise DraftEmbeddingError(
            f"{UNKNOWN_HERO_TOKEN!r} is reserved for unseen heroes."
        )
    payload = {
        "contract_version": DRAFT_EMBEDDING_CONTRACT_VERSION,
        "model_version": HERO_EMBEDDING_MODEL_VERSION,
        "source_columns": list(PICK_SOURCE_COLUMNS),
        "hero_vocabulary": list(heroes),
        "unknown_hero_token": UNKNOWN_HERO_TOKEN,
        "unknown_policy": (
            "single shared trailing unknown index with an exactly zero"
            " main effect and embedding"
        ),
    }
    return HeroVocabulary(
        heroes=heroes,
        unknown_index=len(heroes),
        fingerprint=hashlib.sha256(
            _canonical_json(payload).encode("utf-8")
        ).hexdigest(),
    )


def draft_index_arrays(
    vocabulary: HeroVocabulary,
    frame: pd.DataFrame,
    *,
    context: str,
) -> DraftIndexArrays:
    """Map validated pick columns onto model hero indices."""

    _validate_draft_frame(frame, context=context)
    position = {hero: index for index, hero in enumerate(vocabulary.heroes)}

    def side(columns: tuple[str, ...]) -> np.ndarray:
        stacked = np.column_stack(
            [
                frame[column]
                .map(lambda value: position.get(value, vocabulary.unknown_index))
                .to_numpy(dtype=np.int64)
                for column in columns
            ]
        )
        return stacked

    radiant = side(RADIANT_SOURCE_COLUMNS)
    dire = side(DIRE_SOURCE_COLUMNS)
    unknown_activations = int(
        (radiant == vocabulary.unknown_index).sum()
        + (dire == vocabulary.unknown_index).sum()
    )
    return DraftIndexArrays(
        radiant=radiant,
        dire=dire,
        unknown_activations=unknown_activations,
    )


def fit_draft_embedding_model(
    vocabulary: HeroVocabulary,
    training: DraftIndexArrays,
    targets: np.ndarray,
    *,
    embedding_dim: int,
    l2: float,
    learning_rate: float,
    max_iterations: int,
    gradient_tolerance: float,
    seed: int,
    init_scale: float,
) -> HeroEmbeddingFitResult:
    """Fit one candidate on training indices that contain no unknown heroes.

    The single L2 strength applies to both the main effects and the
    embeddings.  The unknown index is zero-initialized and must remain
    exactly zero after fitting; both conditions are enforced here.
    """

    if training.unknown_activations != 0:
        raise DraftEmbeddingError(
            "Training rows must not activate the unknown hero index."
        )
    config = HeroEmbeddingConfig(
        hero_count=vocabulary.hero_count,
        embedding_dim=embedding_dim,
        l2_main=l2,
        l2_embedding=l2,
        learning_rate=learning_rate,
        max_iterations=max_iterations,
        gradient_tolerance=gradient_tolerance,
        seed=seed,
        init_scale=init_scale,
    )
    result = fit_hero_embedding_model(
        config,
        training.radiant,
        training.dire,
        targets,
        zero_init_hero_indices=(vocabulary.unknown_index,),
    )
    unknown_main = result.parameters.main_effects[vocabulary.unknown_index]
    unknown_embedding = result.parameters.embeddings[vocabulary.unknown_index]
    if unknown_main != 0.0 or (unknown_embedding != 0.0).any():
        raise DraftEmbeddingError(
            "The unknown hero index moved during fitting."
        )
    return result


def predict_draft_probabilities(
    parameters: HeroEmbeddingParameters,
    vocabulary: HeroVocabulary,
    indices: DraftIndexArrays,
) -> np.ndarray:
    """Radiant-win probabilities, permitting repeated unknown indices."""

    return predict_probabilities(
        parameters,
        indices.radiant,
        indices.dire,
        unknown_index=vocabulary.unknown_index,
    )


__all__ = [
    "DRAFT_EMBEDDING_CONTRACT_VERSION",
    "DraftEmbeddingError",
    "DraftIndexArrays",
    "HERO_EMBEDDING_MODEL_VERSION",
    "HeroEmbeddingConfig",
    "HeroEmbeddingError",
    "HeroEmbeddingFitResult",
    "HeroEmbeddingParameters",
    "HeroVocabulary",
    "compute_objective_and_gradients",
    "draft_index_arrays",
    "fit_draft_embedding_model",
    "fit_hero_embedding_model",
    "fit_hero_vocabulary",
    "initialize_parameters",
    "predict_draft_probabilities",
    "predict_log_odds",
    "predict_probabilities",
]
