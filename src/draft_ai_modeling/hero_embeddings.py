"""Deterministic low-rank hero-embedding draft model (Milestone 8).

Each hero ``h`` carries a scalar main effect ``w[h]`` and a d-dimensional
vector ``v[h]``.  For Radiant picks ``R`` and Dire picks ``D`` the Radiant
win log-odds are:

    z = b
        + sum_{h in R} w[h] - sum_{h in D} w[h]
        + sum_{{i,j} subset R} v[i].v[j]
        - sum_{{i,j} subset D} v[i].v[j]
        - sum_{i in R, j in D} v[i].v[j]

The pair sums use the identity
``sum_{i<j} v[i].v[j] = (||sum v||^2 - sum ||v||^2) / 2`` and every heavy
computation is expressed through fixed sparse hero-membership matrices, so
prediction and gradients are fully vectorized.  Fitting minimizes mean
binary cross-entropy plus L2 penalties on ``w`` and ``v`` with hand-derived
gradients and a full-batch deterministic Adam loop: identical inputs
produce bit-identical parameters.  With ``embedding_dim = 0`` every
interaction term vanishes and the model reduces exactly to the additive B1
side-relative pick-presence logistic regression.

An optional ``unknown_index`` designates one reserved hero index that may
appear more than once in a game (multiple unseen heroes collapse onto it).
A duplicated index contributes with its slot multiplicity through the same
pair identity.  Combined with ``zero_init_hero_indices``, a reserved index
that never occurs in training keeps an exactly zero main effect and
embedding: its data gradient is zero by absence and its L2 gradient is zero
at zero, so deterministic Adam never moves it.

This module uses only numpy and scipy.sparse.  It does not load data, read
any split period, or depend on acquisition code.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.sparse import csr_matrix


HERO_EMBEDDING_MODEL_VERSION = "draft-ai-hero-embeddings-v1"
PICKS_PER_SIDE = 5
ADAM_BETA_1 = 0.9
ADAM_BETA_2 = 0.999
ADAM_EPSILON = 1e-8


class HeroEmbeddingError(ValueError):
    """Raised when a hero-embedding configuration or input is invalid."""


@dataclass(frozen=True, slots=True)
class HeroEmbeddingConfig:
    """Frozen fitting contract for one hero-embedding estimator."""

    hero_count: int
    embedding_dim: int
    l2_main: float
    l2_embedding: float
    learning_rate: float
    max_iterations: int
    gradient_tolerance: float
    seed: int
    init_scale: float

    def __post_init__(self) -> None:
        if self.hero_count < 2 * PICKS_PER_SIDE:
            raise HeroEmbeddingError(
                "hero_count must allow ten unique picks per game."
            )
        if self.embedding_dim < 0:
            raise HeroEmbeddingError("embedding_dim must be non-negative.")
        if self.l2_main < 0.0 or self.l2_embedding < 0.0:
            raise HeroEmbeddingError("L2 penalties must be non-negative.")
        if self.learning_rate <= 0.0:
            raise HeroEmbeddingError("learning_rate must be positive.")
        if self.max_iterations < 1:
            raise HeroEmbeddingError("max_iterations must be positive.")
        if self.gradient_tolerance < 0.0:
            raise HeroEmbeddingError(
                "gradient_tolerance must be non-negative."
            )
        if self.init_scale < 0.0:
            raise HeroEmbeddingError("init_scale must be non-negative.")


@dataclass(frozen=True, slots=True)
class HeroEmbeddingParameters:
    """Bias, per-hero main effects ``(H,)``, and embeddings ``(H, d)``."""

    bias: float
    main_effects: np.ndarray
    embeddings: np.ndarray


@dataclass(frozen=True, slots=True)
class HeroEmbeddingFitResult:
    """Fitted parameters plus the deterministic optimization trace."""

    parameters: HeroEmbeddingParameters
    iterations_run: int
    converged: bool
    final_objective: float
    final_gradient_infinity_norm: float
    objective_history: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class _DraftDesign:
    """Fixed sparse per-side hero-membership matrices for one set of games."""

    games: int
    radiant: csr_matrix
    dire: csr_matrix
    radiant_transpose: csr_matrix
    dire_transpose: csr_matrix


def _validate_draft_indices(
    radiant: np.ndarray,
    dire: np.ndarray,
    hero_count: int,
    *,
    unknown_index: int | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    radiant = np.asarray(radiant)
    dire = np.asarray(dire)
    for label, side in (("radiant", radiant), ("dire", dire)):
        if side.ndim != 2 or side.shape[1] != PICKS_PER_SIDE:
            raise HeroEmbeddingError(
                f"{label} indices must have shape (games, {PICKS_PER_SIDE})."
            )
        if not np.issubdtype(side.dtype, np.integer):
            raise HeroEmbeddingError(f"{label} indices must be integers.")
    if radiant.shape[0] != dire.shape[0]:
        raise HeroEmbeddingError(
            "radiant and dire must describe the same games."
        )
    if unknown_index is not None and not (
        0 <= unknown_index < hero_count
    ):
        raise HeroEmbeddingError(
            "unknown_index must lie in [0, hero_count)."
        )
    combined = np.concatenate([radiant, dire], axis=1)
    if combined.size and (
        combined.min() < 0 or combined.max() >= hero_count
    ):
        raise HeroEmbeddingError("hero indices must lie in [0, hero_count).")
    sorted_rows = np.sort(combined, axis=1)
    duplicated = sorted_rows[:, 1:] == sorted_rows[:, :-1]
    if unknown_index is not None:
        duplicated &= sorted_rows[:, 1:] != unknown_index
    if combined.size and duplicated.any():
        raise HeroEmbeddingError(
            "each game must contain ten unique hero indices."
        )
    return radiant, dire


def _validate_targets(targets: np.ndarray, games: int) -> np.ndarray:
    targets = np.asarray(targets, dtype=np.float64)
    if targets.shape != (games,):
        raise HeroEmbeddingError("targets must have shape (games,).")
    if not np.isin(targets, (0.0, 1.0)).all():
        raise HeroEmbeddingError("targets must be binary 0/1 outcomes.")
    return targets


def _validate_parameter_shapes(
    parameters: HeroEmbeddingParameters,
    config: HeroEmbeddingConfig,
) -> None:
    if parameters.main_effects.shape != (
        config.hero_count,
    ) or parameters.embeddings.shape != (
        config.hero_count,
        config.embedding_dim,
    ):
        raise HeroEmbeddingError(
            "parameters do not match the configured hero count and"
            " embedding dimension."
        )


def _stable_sigmoid(z: np.ndarray) -> np.ndarray:
    positive = z >= 0.0
    result = np.empty_like(z)
    result[positive] = 1.0 / (1.0 + np.exp(-z[positive]))
    exp_z = np.exp(z[~positive])
    result[~positive] = exp_z / (1.0 + exp_z)
    return result


def _side_membership(indices: np.ndarray, hero_count: int) -> csr_matrix:
    games = indices.shape[0]
    rows = np.repeat(np.arange(games, dtype=np.int64), PICKS_PER_SIDE)
    matrix = csr_matrix(
        (
            np.ones(indices.size, dtype=np.float64),
            (rows, indices.ravel().astype(np.int64)),
        ),
        shape=(games, hero_count),
    )
    matrix.sum_duplicates()
    matrix.sort_indices()
    return matrix


def _draft_design(
    radiant: np.ndarray,
    dire: np.ndarray,
    hero_count: int,
) -> _DraftDesign:
    radiant_matrix = _side_membership(radiant, hero_count)
    dire_matrix = _side_membership(dire, hero_count)
    return _DraftDesign(
        games=radiant.shape[0],
        radiant=radiant_matrix,
        dire=dire_matrix,
        radiant_transpose=radiant_matrix.T.tocsr(),
        dire_transpose=dire_matrix.T.tocsr(),
    )


def _log_odds(
    design: _DraftDesign,
    bias: float,
    main_effects: np.ndarray,
    embeddings: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    sum_radiant = design.radiant @ embeddings
    sum_dire = design.dire @ embeddings
    squared_norms = (embeddings**2).sum(axis=1)
    within_radiant = 0.5 * (
        (sum_radiant**2).sum(axis=1) - design.radiant @ squared_norms
    )
    within_dire = 0.5 * (
        (sum_dire**2).sum(axis=1) - design.dire @ squared_norms
    )
    cross = (sum_radiant * sum_dire).sum(axis=1)
    z = (
        bias
        + design.radiant @ main_effects
        - design.dire @ main_effects
        + within_radiant
        - within_dire
        - cross
    )
    return z, sum_radiant, sum_dire


def initialize_parameters(
    config: HeroEmbeddingConfig,
    *,
    zero_init_hero_indices: tuple[int, ...] = (),
) -> HeroEmbeddingParameters:
    """Seeded deterministic initialization: zero ``b``/``w``, Gaussian ``v``.

    Indices in ``zero_init_hero_indices`` start with an exactly zero
    embedding row.  A hero that also never occurs in the training games
    then stays exactly zero through the whole deterministic fit.
    """

    for index in zero_init_hero_indices:
        if not 0 <= index < config.hero_count:
            raise HeroEmbeddingError(
                "zero_init_hero_indices must lie in [0, hero_count)."
            )
    rng = np.random.default_rng(config.seed)
    embeddings = config.init_scale * rng.standard_normal(
        (config.hero_count, config.embedding_dim)
    )
    embeddings = embeddings.astype(np.float64)
    for index in zero_init_hero_indices:
        embeddings[index] = 0.0
    return HeroEmbeddingParameters(
        bias=0.0,
        main_effects=np.zeros(config.hero_count, dtype=np.float64),
        embeddings=embeddings,
    )


def predict_log_odds(
    parameters: HeroEmbeddingParameters,
    radiant: np.ndarray,
    dire: np.ndarray,
    *,
    unknown_index: int | None = None,
) -> np.ndarray:
    """Exact Radiant-win log-odds for completed drafts."""

    hero_count = parameters.main_effects.shape[0]
    radiant, dire = _validate_draft_indices(
        radiant,
        dire,
        hero_count,
        unknown_index=unknown_index,
    )
    design = _draft_design(radiant, dire, hero_count)
    z, _, _ = _log_odds(
        design,
        parameters.bias,
        parameters.main_effects,
        parameters.embeddings,
    )
    return z


def predict_probabilities(
    parameters: HeroEmbeddingParameters,
    radiant: np.ndarray,
    dire: np.ndarray,
    *,
    unknown_index: int | None = None,
) -> np.ndarray:
    """Radiant-win probabilities via a numerically stable sigmoid."""

    return _stable_sigmoid(
        predict_log_odds(
            parameters,
            radiant,
            dire,
            unknown_index=unknown_index,
        )
    )


def _objective_and_gradients(
    design: _DraftDesign,
    bias: float,
    main_effects: np.ndarray,
    embeddings: np.ndarray,
    targets: np.ndarray,
    config: HeroEmbeddingConfig,
) -> tuple[float, float, np.ndarray, np.ndarray]:
    games = design.games
    z, sum_radiant, sum_dire = _log_odds(
        design,
        bias,
        main_effects,
        embeddings,
    )
    cross_entropy = np.logaddexp(0.0, z) - targets * z
    objective = (
        float(cross_entropy.mean())
        + config.l2_main * float((main_effects**2).sum())
        + config.l2_embedding * float((embeddings**2).sum())
    )

    residual = _stable_sigmoid(z) - targets
    grad_bias = float(residual.mean())

    radiant_residual_totals = design.radiant_transpose @ residual
    dire_residual_totals = design.dire_transpose @ residual
    grad_main = (
        radiant_residual_totals - dire_residual_totals
    ) / games + 2.0 * config.l2_main * main_effects

    grad_embeddings = (
        design.radiant_transpose
        @ (residual[:, None] * (sum_radiant - sum_dire))
        - radiant_residual_totals[:, None] * embeddings
        + dire_residual_totals[:, None] * embeddings
        - design.dire_transpose
        @ (residual[:, None] * (sum_radiant + sum_dire))
    )
    grad_embeddings /= games
    grad_embeddings += 2.0 * config.l2_embedding * embeddings

    return objective, grad_bias, grad_main, grad_embeddings


def compute_objective_and_gradients(
    parameters: HeroEmbeddingParameters,
    radiant: np.ndarray,
    dire: np.ndarray,
    targets: np.ndarray,
    config: HeroEmbeddingConfig,
    *,
    unknown_index: int | None = None,
) -> tuple[float, float, np.ndarray, np.ndarray]:
    """Mean penalized cross-entropy and its exact analytic gradients.

    Objective:
        mean_i [softplus(z_i) - y_i z_i]
        + l2_main * sum(w**2) + l2_embedding * sum(v**2)

    Hand-derived gradients with ``g_i = sigmoid(z_i) - y_i`` and slot
    multiplicity ``m`` (one for every real hero, possibly larger for a
    duplicated unknown index):
        d/db      = mean(g)
        d/dw[h]   = mean over games of (+m g if h Radiant, -m g if h Dire)
                    + 2 * l2_main * w[h]
        d/dv[h]   = mean over games of
                    m g * (s_R - s_D) - m g * v[h]   when h is Radiant,
                    m g * v[h] - m g * (s_R + s_D)   when h is Dire,
                    + 2 * l2_embedding * v[h]
    where ``s_R`` and ``s_D`` are the per-game embedding sums.
    """

    radiant, dire = _validate_draft_indices(
        radiant,
        dire,
        config.hero_count,
        unknown_index=unknown_index,
    )
    targets = _validate_targets(targets, radiant.shape[0])
    _validate_parameter_shapes(parameters, config)
    design = _draft_design(radiant, dire, config.hero_count)
    return _objective_and_gradients(
        design,
        parameters.bias,
        parameters.main_effects,
        parameters.embeddings,
        targets,
        config,
    )


def fit_hero_embedding_model(
    config: HeroEmbeddingConfig,
    radiant: np.ndarray,
    dire: np.ndarray,
    targets: np.ndarray,
    *,
    zero_init_hero_indices: tuple[int, ...] = (),
) -> HeroEmbeddingFitResult:
    """Full-batch deterministic Adam fit of the penalized objective.

    There is no stochastic minibatching, dropout, or shuffling: the only
    randomness is the seeded embedding initialization, so repeated calls
    with identical inputs return bit-identical parameters.
    """

    radiant, dire = _validate_draft_indices(radiant, dire, config.hero_count)
    targets = _validate_targets(targets, radiant.shape[0])
    design = _draft_design(radiant, dire, config.hero_count)

    parameters = initialize_parameters(
        config,
        zero_init_hero_indices=zero_init_hero_indices,
    )
    bias = parameters.bias
    w = parameters.main_effects.copy()
    v = parameters.embeddings.copy()

    moment_bias = 0.0
    moment_w = np.zeros_like(w)
    moment_v = np.zeros_like(v)
    curvature_bias = 0.0
    curvature_w = np.zeros_like(w)
    curvature_v = np.zeros_like(v)

    history: list[float] = []
    converged = False
    gradient_norm = float("inf")
    iterations_run = 0

    for iteration in range(1, config.max_iterations + 1):
        objective, grad_bias, grad_w, grad_v = _objective_and_gradients(
            design, bias, w, v, targets, config
        )
        history.append(objective)
        iterations_run = iteration
        gradient_norm = max(
            abs(grad_bias),
            float(np.abs(grad_w).max()) if grad_w.size else 0.0,
            float(np.abs(grad_v).max()) if grad_v.size else 0.0,
        )
        if gradient_norm < config.gradient_tolerance:
            converged = True
            break

        moment_bias = ADAM_BETA_1 * moment_bias + (1 - ADAM_BETA_1) * grad_bias
        moment_w = ADAM_BETA_1 * moment_w + (1 - ADAM_BETA_1) * grad_w
        moment_v = ADAM_BETA_1 * moment_v + (1 - ADAM_BETA_1) * grad_v
        curvature_bias = (
            ADAM_BETA_2 * curvature_bias + (1 - ADAM_BETA_2) * grad_bias**2
        )
        curvature_w = ADAM_BETA_2 * curvature_w + (1 - ADAM_BETA_2) * grad_w**2
        curvature_v = ADAM_BETA_2 * curvature_v + (1 - ADAM_BETA_2) * grad_v**2

        correction_1 = 1.0 - ADAM_BETA_1**iteration
        correction_2 = 1.0 - ADAM_BETA_2**iteration
        step = config.learning_rate * np.sqrt(correction_2) / correction_1
        bias -= step * moment_bias / (
            np.sqrt(curvature_bias) + ADAM_EPSILON
        )
        w = w - step * moment_w / (np.sqrt(curvature_w) + ADAM_EPSILON)
        v = v - step * moment_v / (np.sqrt(curvature_v) + ADAM_EPSILON)

    final = HeroEmbeddingParameters(bias=bias, main_effects=w, embeddings=v)
    final_objective, grad_bias, grad_w, grad_v = _objective_and_gradients(
        design, bias, w, v, targets, config
    )
    gradient_norm = max(
        abs(grad_bias),
        float(np.abs(grad_w).max()) if grad_w.size else 0.0,
        float(np.abs(grad_v).max()) if grad_v.size else 0.0,
    )
    return HeroEmbeddingFitResult(
        parameters=final,
        iterations_run=iterations_run,
        converged=converged or gradient_norm < config.gradient_tolerance,
        final_objective=final_objective,
        final_gradient_infinity_norm=gradient_norm,
        objective_history=tuple(history),
    )
