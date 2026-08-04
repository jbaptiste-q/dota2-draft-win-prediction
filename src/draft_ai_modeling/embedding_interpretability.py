"""Milestone 8 Phase 4: interpretability artifacts for the hero-embedding model.

Part A exports the pre-registered best candidate's main effects and
documents, with concrete numerical evidence, why every pre-registered
candidate's embeddings collapse to exactly zero (Milestone 8 Phase 3
found no candidate passed the frozen-B1 development gates, and every
candidate's fitted embedding norm was effectively zero).

Part B is an explicitly out-of-band, descriptive-only refit at one
deliberately weaker L2, chosen so the embeddings do not collapse, used
only to produce human-interpretable projection, neighbour, and pair
artifacts. Part B never influences model selection, is not presented as
a qualifying candidate, and every Part B artifact and manifest entry
carries ``descriptive_only = true``.

Embeddings are identifiable only up to an orthogonal rotation: any
rotation ``v[h] -> Q @ v[h]`` for orthogonal ``Q`` leaves every pairwise
dot product, and therefore every prediction, unchanged. Individual axis
values and signs carry no fixed meaning; only pairwise dot products
(synergy/counter strength) and relative geometry (nearest neighbours,
PCA projection) are rotation-invariant and therefore interpretable.

This module reuses the M4A train-fitted vocabulary policy, the frozen
M8 rolling-origin fold boundaries, and the same hash-verified upstream
lineage checks as embedding_experiment.py. Calibration and locked-test
rows are never read; 2025-Q4 stays reserved and 2026-Q1 stays sealed.
"""

from __future__ import annotations

import json
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import scipy
import sklearn

from .contracts import (
    SPLIT_ROLE_CALIBRATION,
    SPLIT_ROLE_LOCKED_TEST,
)
from .embedding_config import (
    EmbeddingCandidate,
    HeroEmbeddingExperimentConfig,
    load_embedding_experiment_config,
)
from .embedding_experiment import run_embedding_experiment
from .embeddings import (
    HeroVocabulary,
    draft_index_arrays,
    fit_draft_embedding_model,
    fit_hero_vocabulary,
    predict_draft_probabilities,
)
from .loader import load_working_corpus, sha256_file
from .splits import build_split_manifest


INTERPRETABILITY_SCHEMA_VERSION = "draft-ai-hero-embedding-interpretability-v1"
_FORBIDDEN_ROLES = frozenset(
    {SPLIT_ROLE_CALIBRATION, SPLIT_ROLE_LOCKED_TEST}
)
_FINAL_FOLD_ID = "2025-Q3"
_SELECTION_FOLD_IDS = ("2025-Q1", "2025-Q2", "2025-Q3")
_HERO_CATALOG_PATH = (
    Path(__file__).resolve().parents[1]
    / "draft_ai_assistant"
    / "resources"
    / "development_candidate_v0.json"
)
_DESCRIPTIVE_L2_SWEEP_EXPONENTS = (-2.0, -2.5, -3.0, -3.5, -4.0)
_DESCRIPTIVE_COLLAPSE_NORM_THRESHOLD = 0.05
_TOP_NEIGHBOURS = 20
_TOP_PAIRS = 30
_EXTENDED_REFIT_MAX_ITERATIONS = 20_000
_EXTENDED_REFIT_GRADIENT_TOLERANCE = 1e-9


class EmbeddingInterpretabilityError(ValueError):
    """Raised when the M8 interpretability contract is violated."""


@dataclass(frozen=True, slots=True)
class InterpretabilityResult:
    """Paths to every Phase 4 artifact, written inside the parent M8 build."""

    output_directory: Path
    manifest_path: Path
    hero_main_effects_path: Path
    collapse_analysis_path: Path
    descriptive_hero_embeddings_path: Path
    descriptive_hero_projection_2d_path: Path
    descriptive_hero_neighbours_path: Path
    descriptive_learned_pairs_path: Path


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _write_parquet(frame: pd.DataFrame, path: Path) -> None:
    with duckdb.connect() as connection:
        connection.register("artifact_frame", frame)
        escaped = path.resolve().as_posix().replace("'", "''")
        connection.execute(
            "COPY (SELECT * FROM artifact_frame) "
            f"TO '{escaped}' (FORMAT PARQUET, COMPRESSION ZSTD)"
        )


def _artifact(path: Path) -> dict[str, object]:
    return {
        "file": path.name,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def load_hero_display_names() -> dict[str, str]:
    """Read the frozen, git-tracked product catalog as a display-name lookup.

    This is a read-only reference lookup over the reviewed Draft Lab
    snapshot resource; it is not part of the modeling or acquisition
    pipeline and issues no request of any kind. Two hero keys observed in
    the working corpus (newer heroes added after the snapshot was frozen)
    are absent from this catalog; callers fall back to the raw hero key.
    """

    payload = json.loads(_HERO_CATALOG_PATH.read_text(encoding="utf-8"))
    return {
        str(hero["hero_key"]): str(hero["display_name"])
        for hero in payload["heroes"]
    }


def _source_name(hero_key: str, display_names: dict[str, str]) -> str:
    return display_names.get(hero_key, hero_key)


def _masked_development_frame(
    corpus_frame: pd.DataFrame,
    split_manifest: pd.DataFrame,
) -> pd.DataFrame:
    """Join split roles and mask reserved targets, mirroring embedding_experiment.

    Duplicated here (rather than imported) so this module can be exercised
    and reasoned about independently; the masking policy is identical to
    ``embedding_experiment._joined_development_frame``.
    """

    roles = split_manifest[["sample_id", "split_role"]]
    joined = corpus_frame.merge(
        roles,
        on="sample_id",
        how="left",
        validate="one_to_one",
    )
    if joined["split_role"].isna().any():
        raise EmbeddingInterpretabilityError(
            "Split roles do not cover the corpus."
        )
    reserved = joined["split_role"].isin(_FORBIDDEN_ROLES)
    joined.loc[reserved, "radiant_win"] = pd.NA
    if not joined.loc[reserved, "radiant_win"].isna().all():
        raise EmbeddingInterpretabilityError(
            "Reserved targets were not masked."
        )
    return joined


def _fold_window(
    joined: pd.DataFrame,
    fold: object,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    timestamps = joined["match_start_utc"]
    training = joined[
        timestamps.ge(fold.train_start_utc)
        & timestamps.lt(fold.train_end_utc)
    ].copy()
    evaluation = joined[
        timestamps.ge(fold.evaluation_start_utc)
        & timestamps.lt(fold.evaluation_end_utc)
    ].copy()
    if training.empty or evaluation.empty:
        raise EmbeddingInterpretabilityError(
            f"{fold.fold_id} contains an empty role."
        )
    forbidden_training = set(training["split_role"]) & _FORBIDDEN_ROLES
    forbidden_evaluation = set(evaluation["split_role"]) & _FORBIDDEN_ROLES
    if forbidden_training or forbidden_evaluation:
        raise EmbeddingInterpretabilityError(
            f"{fold.fold_id} reads a reserved calibration or locked-test row."
        )
    if training["radiant_win"].isna().any() or evaluation[
        "radiant_win"
    ].isna().any():
        raise EmbeddingInterpretabilityError(
            f"{fold.fold_id} has an unavailable label."
        )
    overlap = set(training["source_match_id"]).intersection(
        evaluation["source_match_id"]
    )
    if overlap:
        raise EmbeddingInterpretabilityError(
            f"{fold.fold_id} crosses source-match groups."
        )
    return training, evaluation


def _fold_by_id(
    config: HeroEmbeddingExperimentConfig,
    fold_id: str,
) -> object:
    for fold in config.rolling_origin_folds:
        if fold.fold_id == fold_id:
            return fold
    raise EmbeddingInterpretabilityError(f"Unknown fold: {fold_id!r}.")


def _select_primary_candidate(
    selection_payload: dict[str, Any],
    config: HeroEmbeddingExperimentConfig,
) -> EmbeddingCandidate:
    """Re-derive the pre-registered best candidate from the verified selection.

    Applies the exact declared tie-break (pooled log loss, then the
    embedding-dimension and L2 preference order) to all nine candidates,
    independent of whether any candidate qualified against the frozen B1
    gate. This is descriptive re-ranking for interpretability purposes
    only; it does not change Phase 3's selection outcome.
    """

    practical_tie = float(
        config.selection_policy["practical_log_loss_tie"]
    )
    dim_preference = tuple(
        config.selection_policy["embedding_dim_preference"]
    )
    l2_preference = tuple(config.selection_policy["l2_preference"])
    dim_rank = {value: index for index, value in enumerate(dim_preference)}
    l2_rank = {value: index for index, value in enumerate(l2_preference)}

    records = [
        {
            "candidate_id": item["candidate_id"],
            "embedding_dim": item["embedding_dim"],
            "l2": item["l2"],
            "pooled_log_loss": item["evaluations"]["pooled"]["candidate"][
                "log_loss"
            ],
        }
        for item in selection_payload["candidates"]
    ]
    if len(records) != len(config.candidates):
        raise EmbeddingInterpretabilityError(
            "The verified selection payload does not cover all candidates."
        )
    best_log_loss = min(record["pooled_log_loss"] for record in records)
    tied = [
        record
        for record in records
        if record["pooled_log_loss"] <= best_log_loss + practical_tie
    ]
    tied.sort(
        key=lambda record: (
            dim_rank[record["embedding_dim"]],
            l2_rank[record["l2"]],
            record["candidate_id"],
        )
    )
    primary_id = tied[0]["candidate_id"]
    for candidate in config.candidates:
        if candidate.candidate_id == primary_id:
            return candidate
    raise EmbeddingInterpretabilityError(
        f"Primary candidate {primary_id!r} is not a declared candidate."
    )


def _fit_candidate_on_fold(
    vocabulary: HeroVocabulary,
    training_indices: object,
    targets: np.ndarray,
    *,
    embedding_dim: int,
    l2: float,
    config: HeroEmbeddingExperimentConfig,
    max_iterations: int | None = None,
    gradient_tolerance: float | None = None,
):
    return fit_draft_embedding_model(
        vocabulary,
        training_indices,
        targets,
        embedding_dim=embedding_dim,
        l2=l2,
        learning_rate=config.estimator.learning_rate,
        max_iterations=(
            max_iterations
            if max_iterations is not None
            else config.estimator.max_iterations
        ),
        gradient_tolerance=(
            gradient_tolerance
            if gradient_tolerance is not None
            else config.estimator.gradient_tolerance
        ),
        seed=config.estimator.random_seed,
        init_scale=config.estimator.init_scale,
    )


def _hero_main_effects_frame(
    vocabulary: HeroVocabulary,
    main_effects: np.ndarray,
    training_indices: object,
    *,
    candidate: EmbeddingCandidate,
    fold_id: str,
    display_names: dict[str, str],
) -> pd.DataFrame:
    real = main_effects[: len(vocabulary.heroes)]
    centered = real - real.mean()
    support = np.bincount(
        training_indices.radiant.ravel(),
        minlength=vocabulary.hero_count,
    ) + np.bincount(
        training_indices.dire.ravel(),
        minlength=vocabulary.hero_count,
    )
    support = support[: len(vocabulary.heroes)]
    order = np.argsort(-np.abs(centered))
    rank = np.empty_like(order)
    rank[order] = np.arange(1, len(order) + 1)
    frame = pd.DataFrame(
        {
            "hero_key": list(vocabulary.heroes),
            "source_name": [
                _source_name(hero, display_names)
                for hero in vocabulary.heroes
            ],
            "main_effect_raw": real,
            "main_effect_centered": centered,
            "abs_magnitude_rank": rank,
            "training_row_support": support,
        }
    )
    frame.insert(0, "fold_id", fold_id)
    frame.insert(0, "l2", candidate.l2)
    frame.insert(0, "embedding_dim", candidate.embedding_dim)
    frame.insert(0, "candidate_id", candidate.candidate_id)
    frame.insert(0, "vocabulary_fingerprint", vocabulary.fingerprint)
    return frame.sort_values(
        "abs_magnitude_rank",
        kind="mergesort",
    ).reset_index(drop=True)


def _collapse_analysis(
    *,
    primary_candidate: EmbeddingCandidate,
    fold_id: str,
    fold: object,
    vocabulary: HeroVocabulary,
    training_indices: object,
    targets: np.ndarray,
    config: HeroEmbeddingExperimentConfig,
    primary_fit_result: object,
) -> dict[str, object]:
    primary_norms = np.linalg.norm(
        primary_fit_result.parameters.embeddings[: len(vocabulary.heroes)],
        axis=1,
    )

    extended = _fit_candidate_on_fold(
        vocabulary,
        training_indices,
        targets,
        embedding_dim=primary_candidate.embedding_dim,
        l2=primary_candidate.l2,
        config=config,
        max_iterations=_EXTENDED_REFIT_MAX_ITERATIONS,
        gradient_tolerance=_EXTENDED_REFIT_GRADIENT_TOLERANCE,
    )
    extended_norms = np.linalg.norm(
        extended.parameters.embeddings[: len(vocabulary.heroes)],
        axis=1,
    )

    zero_dim = _fit_candidate_on_fold(
        vocabulary,
        training_indices,
        targets,
        embedding_dim=0,
        l2=primary_candidate.l2,
        config=config,
    )

    per_candidate: list[dict[str, object]] = []
    for candidate in config.candidates:
        if candidate.embedding_dim == primary_candidate.embedding_dim and (
            candidate.l2 == primary_candidate.l2
        ):
            fit_result = primary_fit_result
        else:
            fit_result = _fit_candidate_on_fold(
                vocabulary,
                training_indices,
                targets,
                embedding_dim=candidate.embedding_dim,
                l2=candidate.l2,
                config=config,
            )
        norms = np.linalg.norm(
            fit_result.parameters.embeddings[: len(vocabulary.heroes)],
            axis=1,
        )
        per_candidate.append(
            {
                "candidate_id": candidate.candidate_id,
                "embedding_dim": candidate.embedding_dim,
                "l2": candidate.l2,
                "max_embedding_norm": float(norms.max(initial=0.0)),
                "mean_embedding_norm": float(norms.mean()) if norms.size else 0.0,
                "iterations_run": fit_result.iterations_run,
                "converged": fit_result.converged,
                "final_objective": fit_result.final_objective,
            }
        )

    return {
        "kind": "hero_embedding_collapse_analysis",
        "descriptive_only": False,
        "primary_candidate_id": primary_candidate.candidate_id,
        "fold_id": fold_id,
        "training_interval": {
            "start_utc": fold.train_start_utc.isoformat(),
            "end_utc_exclusive": fold.train_end_utc.isoformat(),
        },
        "training_rows": len(targets),
        "stationary_point_argument": {
            "claim": (
                "v = 0 is a stationary point of the penalized objective for"
                " every embedding dimension and every L2 >= 0, regardless"
                " of the data."
            ),
            "derivation": (
                "At v = 0 every per-game embedding sum (s_R, s_D) is the"
                " zero vector, so the data gradient d/dv[h] = mean(g * ("
                "linear combination of s_R, s_D, v[h])) is identically zero"
                " because every term it multiplies is zero. The L2 gradient"
                " 2 * l2_embedding * v[h] is also zero at v[h] = 0. Both"
                " gradient components vanish simultaneously, so v = 0 is"
                " always a critical point; deterministic Adam initialized"
                " near zero (init_scale = "
                f"{config.estimator.init_scale}) moves only if the"
                " surrounding curvature pulls it away."
            ),
            "stability_condition": (
                "v = 0 is additionally a strict local minimum (an"
                " attracting basin, not just a saddle) whenever the local"
                " curvature of the mean cross-entropy loss along every"
                " interaction direction is smaller than 2 * l2_embedding."
                " Every one of the nine pre-registered L2 values"
                " (0.01, 0.1, 1.0) satisfies this on this corpus, so all"
                " nine candidates converge back to v = 0 regardless of"
                " embedding dimension; Part B deliberately lowers L2 below"
                " this threshold to escape the basin for visualization."
            ),
        },
        "extended_refit": {
            "purpose": (
                "Rule out premature stopping under the pre-registered"
                " gradient tolerance by running far past it."
            ),
            "candidate_id": primary_candidate.candidate_id,
            "max_iterations": _EXTENDED_REFIT_MAX_ITERATIONS,
            "gradient_tolerance": _EXTENDED_REFIT_GRADIENT_TOLERANCE,
            "iterations_run": extended.iterations_run,
            "converged": extended.converged,
            "final_gradient_infinity_norm": (
                extended.final_gradient_infinity_norm
            ),
            "final_objective": extended.final_objective,
            "max_embedding_norm": float(extended_norms.max(initial=0.0)),
            "mean_embedding_norm": (
                float(extended_norms.mean()) if extended_norms.size else 0.0
            ),
        },
        "zero_dim_equivalence": {
            "purpose": (
                "Confirm the collapsed model is numerically indistinguishable"
                " from the exact additive B1-style reduction at d = 0."
            ),
            "l2": primary_candidate.l2,
            "d_equal_primary_final_objective": (
                primary_fit_result.final_objective
            ),
            "d_equal_zero_final_objective": zero_dim.final_objective,
            "absolute_difference": abs(
                primary_fit_result.final_objective
                - zero_dim.final_objective
            ),
        },
        "per_candidate_max_embedding_norms": per_candidate,
        "primary_candidate_embedding_norms": {
            "max": float(primary_norms.max(initial=0.0)),
            "mean": float(primary_norms.mean()) if primary_norms.size else 0.0,
        },
        "identifiability_note": (
            "Embeddings are identifiable only up to an orthogonal rotation:"
            " for any orthogonal Q, v[h] -> Q @ v[h] leaves every pairwise"
            " dot product and every prediction unchanged. Individual axis"
            " values carry no fixed meaning."
        ),
    }


def _choose_descriptive_l2(
    vocabulary: HeroVocabulary,
    training_indices: object,
    targets: np.ndarray,
    *,
    embedding_dim: int,
    config: HeroEmbeddingExperimentConfig,
) -> tuple[float, list[dict[str, object]]]:
    """Sweep decreasing L2 and stop at the first value that escapes collapse.

    The sweep is a fixed geometric sequence in log10 space
    (10^-2.0 down to 10^-4.0 in half-decade steps). The first value
    (taken in decreasing-penalty order) whose maximum fitted embedding
    norm exceeds a fixed threshold, well above the ~1e-5 numerical noise
    floor observed at collapse, is selected. This selection uses only
    training-role rows and is reported in full for auditability.
    """

    sweep: list[dict[str, object]] = []
    chosen: float | None = None
    for exponent in _DESCRIPTIVE_L2_SWEEP_EXPONENTS:
        l2 = 10.0**exponent
        result = _fit_candidate_on_fold(
            vocabulary,
            training_indices,
            targets,
            embedding_dim=embedding_dim,
            l2=l2,
            config=config,
        )
        norms = np.linalg.norm(
            result.parameters.embeddings[: len(vocabulary.heroes)],
            axis=1,
        )
        max_norm = float(norms.max(initial=0.0))
        escaped = max_norm > _DESCRIPTIVE_COLLAPSE_NORM_THRESHOLD
        sweep.append(
            {
                "l2": l2,
                "log10_l2": exponent,
                "iterations_run": result.iterations_run,
                "converged": result.converged,
                "max_embedding_norm": max_norm,
                "escaped_collapse": escaped,
            }
        )
        if escaped and chosen is None:
            chosen = l2
    if chosen is None:
        raise EmbeddingInterpretabilityError(
            "No swept L2 value escaped embedding collapse."
        )
    return chosen, sweep


def _cosine_similarity_matrix(embeddings: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    if (norms <= 0.0).any():
        raise EmbeddingInterpretabilityError(
            "A hero has a degenerate zero-norm descriptive embedding."
        )
    unit = embeddings / norms
    return unit @ unit.T


def _descriptive_neighbours(
    vocabulary: HeroVocabulary,
    embeddings: np.ndarray,
    *,
    display_names: dict[str, str],
    candidate_id: str,
    fold_id: str,
) -> dict[str, object]:
    heroes = vocabulary.heroes
    similarity = _cosine_similarity_matrix(embeddings)
    entries = []
    for index, hero in enumerate(heroes):
        ranked = sorted(
            (
                other
                for other in range(len(heroes))
                if other != index
            ),
            key=lambda other: (-similarity[index, other], heroes[other]),
        )[:_TOP_NEIGHBOURS]
        entries.append(
            {
                "hero_key": hero,
                "source_name": _source_name(hero, display_names),
                "neighbours": [
                    {
                        "hero_key": heroes[other],
                        "source_name": _source_name(
                            heroes[other], display_names
                        ),
                        "cosine_similarity": float(similarity[index, other]),
                    }
                    for other in ranked
                ],
            }
        )
    return {
        "kind": "descriptive_hero_neighbours",
        "descriptive_only": True,
        "candidate_id": candidate_id,
        "fold_id": fold_id,
        "similarity_metric": "cosine",
        "top_k": _TOP_NEIGHBOURS,
        "identifiability_note": (
            "Embeddings are identifiable only up to an orthogonal rotation;"
            " cosine similarity between two hero vectors is rotation"
            " invariant and therefore meaningful even though individual"
            " axis values are not."
        ),
        "heroes": entries,
    }


def _pair_support_counts(
    training_indices: object,
) -> dict[tuple[int, int], dict[str, int]]:
    counts: dict[tuple[int, int], dict[str, int]] = {}

    def bump(a: int, b: int, key: str) -> None:
        pair = (a, b) if a < b else (b, a)
        record = counts.setdefault(
            pair, {"same_side_training_games": 0, "opposing_side_training_games": 0}
        )
        record[key] += 1

    for row_radiant, row_dire in zip(
        training_indices.radiant,
        training_indices.dire,
    ):
        for i in range(len(row_radiant)):
            for j in range(i + 1, len(row_radiant)):
                bump(
                    int(row_radiant[i]),
                    int(row_radiant[j]),
                    "same_side_training_games",
                )
        for i in range(len(row_dire)):
            for j in range(i + 1, len(row_dire)):
                bump(
                    int(row_dire[i]),
                    int(row_dire[j]),
                    "same_side_training_games",
                )
        for radiant_hero in row_radiant:
            for dire_hero in row_dire:
                bump(
                    int(radiant_hero),
                    int(dire_hero),
                    "opposing_side_training_games",
                )
    return counts


def _descriptive_learned_pairs(
    vocabulary: HeroVocabulary,
    embeddings: np.ndarray,
    training_indices: object,
    *,
    display_names: dict[str, str],
    candidate_id: str,
    fold_id: str,
) -> dict[str, object]:
    heroes = vocabulary.heroes
    real_embeddings = embeddings[: len(heroes)]
    dot_products = real_embeddings @ real_embeddings.T
    support = _pair_support_counts(training_indices)

    pairs = [
        (i, j, float(dot_products[i, j]))
        for i in range(len(heroes))
        for j in range(i + 1, len(heroes))
    ]

    def record(i: int, j: int, value: float) -> dict[str, object]:
        counts = support.get(
            (i, j), {"same_side_training_games": 0, "opposing_side_training_games": 0}
        )
        return {
            "hero_a": heroes[i],
            "hero_a_source_name": _source_name(heroes[i], display_names),
            "hero_b": heroes[j],
            "hero_b_source_name": _source_name(heroes[j], display_names),
            "dot_product": value,
            "same_side_training_games": counts["same_side_training_games"],
            "opposing_side_training_games": (
                counts["opposing_side_training_games"]
            ),
        }

    synergy = sorted(pairs, key=lambda item: (-item[2], item[0], item[1]))[
        :_TOP_PAIRS
    ]
    counter = sorted(pairs, key=lambda item: (item[2], item[0], item[1]))[
        :_TOP_PAIRS
    ]
    return {
        "kind": "descriptive_learned_pairs",
        "descriptive_only": True,
        "candidate_id": candidate_id,
        "fold_id": fold_id,
        "top_k": _TOP_PAIRS,
        "interpretation": (
            "A high positive dot product favors the pair on the same team"
            " (synergy) and disfavors it split across teams (weak"
            " counter). A strongly negative dot product favors the pair"
            " split across teams (counter) and disfavors it stacked on"
            " one team."
        ),
        "identifiability_note": (
            "Pairwise dot products are rotation invariant and therefore"
            " meaningful even though individual embedding axes are not."
        ),
        "top_synergy_pairs": [
            record(i, j, value) for i, j, value in synergy
        ],
        "top_counter_pairs": [
            record(i, j, value) for i, j, value in counter
        ],
    }


def _descriptive_projection_2d(
    vocabulary: HeroVocabulary,
    embeddings: np.ndarray,
    *,
    display_names: dict[str, str],
    candidate_id: str,
    embedding_dim: int,
    l2: float,
    fold_id: str,
) -> tuple[pd.DataFrame, dict[str, float]]:
    real_embeddings = embeddings[: len(vocabulary.heroes)]
    centered = real_embeddings - real_embeddings.mean(axis=0)
    _, singular_values, right_singular = np.linalg.svd(
        centered,
        full_matrices=False,
    )
    components = min(2, right_singular.shape[0])
    projection = centered @ right_singular[:components].T
    if components < 2:
        projection = np.concatenate(
            [projection, np.zeros((projection.shape[0], 2 - components))],
            axis=1,
        )
    total_variance = float((singular_values**2).sum())
    explained = (
        (singular_values[:components] ** 2 / total_variance).tolist()
        if total_variance > 0.0
        else [0.0] * components
    )
    explained = explained + [0.0] * (2 - len(explained))

    frame = pd.DataFrame(
        {
            "hero_key": list(vocabulary.heroes),
            "source_name": [
                _source_name(hero, display_names)
                for hero in vocabulary.heroes
            ],
            "pc1": projection[:, 0],
            "pc2": projection[:, 1],
            "explained_variance_ratio_pc1": explained[0],
            "explained_variance_ratio_pc2": explained[1],
        }
    )
    frame.insert(0, "fold_id", fold_id)
    frame.insert(0, "l2", l2)
    frame.insert(0, "embedding_dim", embedding_dim)
    frame.insert(0, "candidate_id", candidate_id)
    frame["descriptive_only"] = True
    return frame, {
        "explained_variance_ratio_pc1": explained[0],
        "explained_variance_ratio_pc2": explained[1],
    }


def _descriptive_embeddings_frame(
    vocabulary: HeroVocabulary,
    parameters: object,
    *,
    display_names: dict[str, str],
    candidate_id: str,
    embedding_dim: int,
    l2: float,
    fold_id: str,
) -> pd.DataFrame:
    real_embeddings = parameters.embeddings[: len(vocabulary.heroes)]
    real_main_effects = parameters.main_effects[: len(vocabulary.heroes)]
    norms = np.linalg.norm(real_embeddings, axis=1)
    columns = {
        f"v_{index}": real_embeddings[:, index]
        for index in range(embedding_dim)
    }
    frame = pd.DataFrame(
        {
            "hero_key": list(vocabulary.heroes),
            "source_name": [
                _source_name(hero, display_names)
                for hero in vocabulary.heroes
            ],
            "main_effect": real_main_effects,
            **columns,
            "embedding_norm": norms,
        }
    )
    frame.insert(0, "fold_id", fold_id)
    frame.insert(0, "l2", l2)
    frame.insert(0, "embedding_dim", embedding_dim)
    frame.insert(0, "candidate_id", candidate_id)
    frame["descriptive_only"] = True
    return frame


def _descriptive_pooled_metrics(
    config: HeroEmbeddingExperimentConfig,
    joined: pd.DataFrame,
    *,
    embedding_dim: int,
    l2: float,
) -> dict[str, object]:
    """Refit at the chosen weaker L2 across the selection folds and pool.

    Mirrors the pooled 2025-Q1 through 2025-Q3 scope used everywhere else
    in this project, purely to put the performance cost of this
    intentionally under-regularized, descriptive-only refit on record.
    """

    per_fold: list[dict[str, object]] = []
    all_targets: list[np.ndarray] = []
    all_probabilities: list[np.ndarray] = []
    for fold_id in _SELECTION_FOLD_IDS:
        fold = _fold_by_id(config, fold_id)
        training, evaluation = _fold_window(joined, fold)
        targets = training["radiant_win"].astype("int8").to_numpy(
            dtype=np.float64
        )
        vocabulary = fit_hero_vocabulary(training)
        training_indices = draft_index_arrays(
            vocabulary,
            training,
            context=f"{fold_id} descriptive training rows",
        )
        evaluation_indices = draft_index_arrays(
            vocabulary,
            evaluation,
            context=f"{fold_id} descriptive evaluation rows",
        )
        result = _fit_candidate_on_fold(
            vocabulary,
            training_indices,
            targets,
            embedding_dim=embedding_dim,
            l2=l2,
            config=config,
        )
        probabilities = predict_draft_probabilities(
            result.parameters,
            vocabulary,
            evaluation_indices,
        )
        evaluation_targets = evaluation["radiant_win"].astype(
            "int8"
        ).to_numpy(dtype=np.float64)
        clipped = np.clip(
            probabilities,
            np.finfo(np.float64).eps,
            1 - np.finfo(np.float64).eps,
        )
        log_loss = float(
            -(
                evaluation_targets * np.log(clipped)
                + (1 - evaluation_targets) * np.log1p(-clipped)
            ).mean()
        )
        brier = float(np.mean((evaluation_targets - probabilities) ** 2))
        per_fold.append(
            {
                "fold_id": fold_id,
                "rows": len(evaluation),
                "log_loss": log_loss,
                "brier_score": brier,
                "iterations_run": result.iterations_run,
                "converged": result.converged,
            }
        )
        all_targets.append(evaluation_targets)
        all_probabilities.append(probabilities)

    pooled_targets = np.concatenate(all_targets)
    pooled_probabilities = np.concatenate(all_probabilities)
    clipped = np.clip(
        pooled_probabilities,
        np.finfo(np.float64).eps,
        1 - np.finfo(np.float64).eps,
    )
    pooled_log_loss = float(
        -(
            pooled_targets * np.log(clipped)
            + (1 - pooled_targets) * np.log1p(-clipped)
        ).mean()
    )
    pooled_brier = float(
        np.mean((pooled_targets - pooled_probabilities) ** 2)
    )
    return {
        "descriptive_only": True,
        "scope": "pooled_2025_q1_q3_development_only",
        "selection_use": "not_used_for_selection",
        "per_fold": per_fold,
        "pooled_rows": len(pooled_targets),
        "pooled_log_loss": pooled_log_loss,
        "pooled_brier_score": pooled_brier,
        "note": (
            "This descriptive-only refit is not evaluated against a"
            " paired bootstrap gate and is not a qualifying candidate."
            " It is reported only to put the performance cost of"
            " intentionally weak regularization on record."
        ),
    }


def _runtime_versions() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "duckdb": duckdb.__version__,
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "scipy": scipy.__version__,
        "scikit_learn": sklearn.__version__,
    }


def run_embedding_interpretability(
    experiment_config_path: Path,
    *,
    output_root: Path = Path("models/m8"),
    repository_root: Path | None = None,
) -> InterpretabilityResult:
    """Produce Phase 4 interpretability artifacts inside the verified M8 build."""

    root = (
        repository_root.resolve()
        if repository_root is not None
        else Path(__file__).resolve().parents[2]
    )
    parent = run_embedding_experiment(
        experiment_config_path,
        output_root=output_root,
        repository_root=root,
    )
    config = load_embedding_experiment_config(
        experiment_config_path.resolve(),
        repository_root=root,
    )
    selection_payload = json.loads(
        parent.selection_path.read_text(encoding="utf-8")
    )
    primary_candidate = _select_primary_candidate(selection_payload, config)
    display_names = load_hero_display_names()

    corpus = load_working_corpus(config.corpus_config_path)
    split = build_split_manifest(corpus.frame)
    joined = _masked_development_frame(corpus.frame, split.manifest)
    final_fold = _fold_by_id(config, _FINAL_FOLD_ID)
    training, _evaluation = _fold_window(joined, final_fold)
    targets = training["radiant_win"].astype("int8").to_numpy(
        dtype=np.float64
    )
    vocabulary = fit_hero_vocabulary(training)
    training_indices = draft_index_arrays(
        vocabulary,
        training,
        context=f"{_FINAL_FOLD_ID} interpretability training rows",
    )
    if training_indices.unknown_activations != 0:
        raise EmbeddingInterpretabilityError(
            "Interpretability training rows activate the unknown hero."
        )

    primary_fit = _fit_candidate_on_fold(
        vocabulary,
        training_indices,
        targets,
        embedding_dim=primary_candidate.embedding_dim,
        l2=primary_candidate.l2,
        config=config,
    )

    hero_main_effects = _hero_main_effects_frame(
        vocabulary,
        primary_fit.parameters.main_effects,
        training_indices,
        candidate=primary_candidate,
        fold_id=_FINAL_FOLD_ID,
        display_names=display_names,
    )
    collapse_analysis = _collapse_analysis(
        primary_candidate=primary_candidate,
        fold_id=_FINAL_FOLD_ID,
        fold=final_fold,
        vocabulary=vocabulary,
        training_indices=training_indices,
        targets=targets,
        config=config,
        primary_fit_result=primary_fit,
    )

    descriptive_l2, l2_sweep = _choose_descriptive_l2(
        vocabulary,
        training_indices,
        targets,
        embedding_dim=primary_candidate.embedding_dim,
        config=config,
    )
    descriptive_candidate_id = (
        f"descriptive_d{primary_candidate.embedding_dim}_l2_{descriptive_l2:.6g}"
    )
    descriptive_fit = _fit_candidate_on_fold(
        vocabulary,
        training_indices,
        targets,
        embedding_dim=primary_candidate.embedding_dim,
        l2=descriptive_l2,
        config=config,
    )
    descriptive_embeddings_frame = _descriptive_embeddings_frame(
        vocabulary,
        descriptive_fit.parameters,
        display_names=display_names,
        candidate_id=descriptive_candidate_id,
        embedding_dim=primary_candidate.embedding_dim,
        l2=descriptive_l2,
        fold_id=_FINAL_FOLD_ID,
    )
    projection_frame, explained_variance = _descriptive_projection_2d(
        vocabulary,
        descriptive_fit.parameters.embeddings,
        display_names=display_names,
        candidate_id=descriptive_candidate_id,
        embedding_dim=primary_candidate.embedding_dim,
        l2=descriptive_l2,
        fold_id=_FINAL_FOLD_ID,
    )
    neighbours = _descriptive_neighbours(
        vocabulary,
        descriptive_fit.parameters.embeddings[: len(vocabulary.heroes)],
        display_names=display_names,
        candidate_id=descriptive_candidate_id,
        fold_id=_FINAL_FOLD_ID,
    )
    learned_pairs = _descriptive_learned_pairs(
        vocabulary,
        descriptive_fit.parameters.embeddings,
        training_indices,
        display_names=display_names,
        candidate_id=descriptive_candidate_id,
        fold_id=_FINAL_FOLD_ID,
    )
    descriptive_pooled_metrics = _descriptive_pooled_metrics(
        config,
        joined,
        embedding_dim=primary_candidate.embedding_dim,
        l2=descriptive_l2,
    )

    target = parent.output_directory
    paths = {
        "hero_main_effects": target / "hero_main_effects.parquet",
        "collapse_analysis": target / "collapse_analysis.json",
        "descriptive_hero_embeddings": (
            target / "descriptive_hero_embeddings.parquet"
        ),
        "descriptive_hero_projection_2d": (
            target / "descriptive_hero_projection_2d.parquet"
        ),
        "descriptive_hero_neighbours": (
            target / "descriptive_hero_neighbours.json"
        ),
        "descriptive_learned_pairs": (
            target / "descriptive_learned_pairs.json"
        ),
    }
    manifest_path = target / "interpretability_manifest.json"

    _write_parquet(hero_main_effects, paths["hero_main_effects"])
    _write_json(paths["collapse_analysis"], collapse_analysis)
    _write_parquet(
        descriptive_embeddings_frame,
        paths["descriptive_hero_embeddings"],
    )
    _write_parquet(projection_frame, paths["descriptive_hero_projection_2d"])
    _write_json(paths["descriptive_hero_neighbours"], neighbours)
    _write_json(paths["descriptive_learned_pairs"], learned_pairs)

    manifest = {
        "schema_version": INTERPRETABILITY_SCHEMA_VERSION,
        "parent_build_fingerprint": parent.build_fingerprint,
        "primary_candidate_id": primary_candidate.candidate_id,
        "final_fold_id": _FINAL_FOLD_ID,
        "vocabulary_fingerprint": vocabulary.fingerprint,
        "part_a": {
            "descriptive_only": False,
            "artifacts": {
                "hero_main_effects": _artifact(paths["hero_main_effects"]),
                "collapse_analysis": _artifact(paths["collapse_analysis"]),
            },
        },
        "part_b": {
            "descriptive_only": True,
            "candidate_id": descriptive_candidate_id,
            "embedding_dim": primary_candidate.embedding_dim,
            "l2_selection": {
                "method": (
                    "fixed geometric sweep of L2 in half-decade steps from"
                    " 10^-2.0 down to 10^-4.0; the first value (in"
                    " decreasing-penalty order) whose maximum fitted"
                    " embedding norm exceeds "
                    f"{_DESCRIPTIVE_COLLAPSE_NORM_THRESHOLD} was selected,"
                    " where the threshold is far above the ~1e-5 numerical"
                    " noise floor observed at collapse"
                ),
                "sweep": l2_sweep,
                "chosen_l2": descriptive_l2,
            },
            "pooled_2025_metrics": descriptive_pooled_metrics,
            "not_used_for_selection": True,
            "not_a_qualifying_candidate": True,
            "identifiability_note": (
                "Embeddings are identifiable only up to an orthogonal"
                " rotation; only pairwise dot products and relative"
                " geometry are meaningful."
            ),
            "artifacts": {
                "descriptive_hero_embeddings": _artifact(
                    paths["descriptive_hero_embeddings"]
                ),
                "descriptive_hero_projection_2d": _artifact(
                    paths["descriptive_hero_projection_2d"]
                ),
                "descriptive_hero_neighbours": _artifact(
                    paths["descriptive_hero_neighbours"]
                ),
                "descriptive_learned_pairs": _artifact(
                    paths["descriptive_learned_pairs"]
                ),
            },
            "projection_explained_variance": explained_variance,
        },
        "safety": {
            "calibration_prediction_rows": 0,
            "locked_test_prediction_rows": 0,
            "authenticated_api_requests": 0,
            "model_serialization_performed": False,
        },
        "runtime_versions": _runtime_versions(),
    }
    _write_json(manifest_path, manifest)

    return InterpretabilityResult(
        output_directory=target,
        manifest_path=manifest_path,
        hero_main_effects_path=paths["hero_main_effects"],
        collapse_analysis_path=paths["collapse_analysis"],
        descriptive_hero_embeddings_path=(
            paths["descriptive_hero_embeddings"]
        ),
        descriptive_hero_projection_2d_path=(
            paths["descriptive_hero_projection_2d"]
        ),
        descriptive_hero_neighbours_path=(
            paths["descriptive_hero_neighbours"]
        ),
        descriptive_learned_pairs_path=paths["descriptive_learned_pairs"],
    )


__all__ = [
    "EmbeddingInterpretabilityError",
    "InterpretabilityResult",
    "load_hero_display_names",
    "run_embedding_interpretability",
]
