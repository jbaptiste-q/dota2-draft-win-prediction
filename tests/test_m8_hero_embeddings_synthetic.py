"""Milestone 8 Phase 1: synthetic validation of the hero-embedding model.

Every test runs on synthetic games generated from a known ground-truth
embedding.  No real supervised data, split period, or artifact is read.
"""

from __future__ import annotations

import numpy as np
import pytest
from sklearn.linear_model import LogisticRegression

from src.draft_ai_modeling.hero_embeddings import (
    HeroEmbeddingConfig,
    HeroEmbeddingError,
    HeroEmbeddingParameters,
    compute_objective_and_gradients,
    fit_hero_embedding_model,
    initialize_parameters,
    predict_log_odds,
    predict_probabilities,
)


def _make_config(**overrides: object) -> HeroEmbeddingConfig:
    base: dict[str, object] = {
        "hero_count": 16,
        "embedding_dim": 2,
        "l2_main": 1e-4,
        "l2_embedding": 1e-4,
        "learning_rate": 0.05,
        "max_iterations": 2500,
        "gradient_tolerance": 1e-6,
        "seed": 7,
        "init_scale": 0.1,
    }
    base.update(overrides)
    return HeroEmbeddingConfig(**base)  # type: ignore[arg-type]


def _sample_drafts(
    rng: np.random.Generator, games: int, hero_count: int
) -> tuple[np.ndarray, np.ndarray]:
    picks = np.empty((games, 10), dtype=np.int64)
    for row in range(games):
        picks[row] = rng.permutation(hero_count)[:10]
    return picks[:, :5], picks[:, 5:]


def _sample_targets(
    rng: np.random.Generator,
    truth: HeroEmbeddingParameters,
    radiant: np.ndarray,
    dire: np.ndarray,
) -> np.ndarray:
    log_odds = predict_log_odds(truth, radiant, dire)
    probabilities = 1.0 / (1.0 + np.exp(-log_odds))
    return (rng.random(radiant.shape[0]) < probabilities).astype(np.float64)


def _planted_truth(rng: np.random.Generator) -> HeroEmbeddingParameters:
    """Sixteen heroes with one planted synergy pair and one counter pair.

    Heroes 0 and 1 share the vector (1.2, 0) so their same-team dot product
    is a strong +1.44 synergy.  Heroes 2 and 3 share (-1.2, 0), so pairs
    drawn across {0, 1} x {2, 3} have dot product -1.44: a strong
    cross-team counter and same-team anti-synergy.
    """

    embeddings = 0.35 * rng.standard_normal((16, 2))
    embeddings[0] = embeddings[1] = (1.2, 0.0)
    embeddings[2] = embeddings[3] = (-1.2, 0.0)
    return HeroEmbeddingParameters(
        bias=0.1,
        main_effects=0.25 * rng.standard_normal(16),
        embeddings=embeddings,
    )


class TestAnalyticGradients:
    def _finite_difference_check(self, config: HeroEmbeddingConfig) -> None:
        rng = np.random.default_rng(11)
        radiant, dire = _sample_drafts(rng, 6, config.hero_count)
        targets = (rng.random(6) < 0.5).astype(np.float64)
        parameters = HeroEmbeddingParameters(
            bias=0.3,
            main_effects=0.5 * rng.standard_normal(config.hero_count),
            embeddings=0.5
            * rng.standard_normal(
                (config.hero_count, config.embedding_dim)
            ),
        )

        objective, grad_bias, grad_main, grad_embeddings = (
            compute_objective_and_gradients(
                parameters, radiant, dire, targets, config
            )
        )
        assert np.isfinite(objective)

        flat = np.concatenate(
            [
                [parameters.bias],
                parameters.main_effects,
                parameters.embeddings.ravel(),
            ]
        )
        analytic = np.concatenate(
            [[grad_bias], grad_main, grad_embeddings.ravel()]
        )

        def objective_at(vector: np.ndarray) -> float:
            candidate = HeroEmbeddingParameters(
                bias=float(vector[0]),
                main_effects=vector[1 : 1 + config.hero_count].copy(),
                embeddings=vector[1 + config.hero_count :].reshape(
                    config.hero_count, config.embedding_dim
                ),
            )
            value, _, _, _ = compute_objective_and_gradients(
                candidate, radiant, dire, targets, config
            )
            return value

        epsilon = 1e-6
        numeric = np.empty_like(analytic)
        for index in range(flat.size):
            forward = flat.copy()
            backward = flat.copy()
            forward[index] += epsilon
            backward[index] -= epsilon
            numeric[index] = (
                objective_at(forward) - objective_at(backward)
            ) / (2.0 * epsilon)

        np.testing.assert_allclose(analytic, numeric, rtol=1e-6, atol=1e-8)

    def test_gradients_match_finite_differences(self) -> None:
        self._finite_difference_check(
            _make_config(hero_count=12, embedding_dim=3, l2_main=0.01,
                         l2_embedding=0.02)
        )

    def test_gradients_match_finite_differences_zero_dim(self) -> None:
        self._finite_difference_check(
            _make_config(hero_count=12, embedding_dim=0, l2_main=0.01)
        )


class TestStructureRecovery:
    def test_recovers_planted_synergy_and_counter_structure(self) -> None:
        rng = np.random.default_rng(23)
        truth = _planted_truth(rng)
        radiant, dire = _sample_drafts(rng, 12_000, 16)
        targets = _sample_targets(rng, truth, radiant, dire)

        result = fit_hero_embedding_model(
            _make_config(), radiant, dire, targets
        )
        fitted = result.parameters

        # Embeddings are identifiable only up to orthogonal rotation, so
        # compare pairwise dot-product (Gram) structure, not raw vectors.
        gram_true = truth.embeddings @ truth.embeddings.T
        gram_fit = fitted.embeddings @ fitted.embeddings.T
        upper = np.triu_indices(16, k=1)
        correlation = np.corrcoef(gram_true[upper], gram_fit[upper])[0, 1]
        assert correlation > 0.9

        # The planted synergy pair must be the strongest fitted pair, and
        # the most counter-like pair must come from {0, 1} x {2, 3}.
        pair_values = gram_fit[upper]
        strongest = np.argmax(pair_values)
        weakest = np.argmin(pair_values)
        strongest_pair = {upper[0][strongest], upper[1][strongest]}
        weakest_pair = {upper[0][weakest], upper[1][weakest]}
        assert strongest_pair in ({0, 1}, {2, 3})
        assert len(weakest_pair & {0, 1}) == 1
        assert len(weakest_pair & {2, 3}) == 1
        assert gram_fit[0, 1] > 0.7
        assert gram_fit[0, 2] < -0.7

        # Main effects are identifiable up to an additive constant because
        # both sides pick exactly five heroes; compare centered values.
        centered_true = truth.main_effects - truth.main_effects.mean()
        centered_fit = fitted.main_effects - fitted.main_effects.mean()
        main_correlation = np.corrcoef(centered_true, centered_fit)[0, 1]
        assert main_correlation > 0.9


class TestDeterminism:
    def test_repeated_fits_are_bit_identical(self) -> None:
        rng = np.random.default_rng(31)
        truth = _planted_truth(rng)
        radiant, dire = _sample_drafts(rng, 1_500, 16)
        targets = _sample_targets(rng, truth, radiant, dire)
        config = _make_config(max_iterations=300)

        first = fit_hero_embedding_model(config, radiant, dire, targets)
        second = fit_hero_embedding_model(config, radiant, dire, targets)

        assert first.parameters.bias == second.parameters.bias
        assert np.array_equal(
            first.parameters.main_effects, second.parameters.main_effects
        )
        assert np.array_equal(
            first.parameters.embeddings, second.parameters.embeddings
        )
        assert first.objective_history == second.objective_history
        assert first.iterations_run == second.iterations_run
        assert first.final_objective == second.final_objective


class TestAdditiveReduction:
    def test_zero_dim_log_odds_are_purely_additive(self) -> None:
        rng = np.random.default_rng(41)
        parameters = HeroEmbeddingParameters(
            bias=0.2,
            main_effects=rng.standard_normal(14),
            embeddings=np.zeros((14, 0)),
        )
        radiant, dire = _sample_drafts(rng, 50, 14)
        expected = (
            0.2
            + parameters.main_effects[radiant].sum(axis=1)
            - parameters.main_effects[dire].sum(axis=1)
        )
        np.testing.assert_allclose(
            predict_log_odds(parameters, radiant, dire), expected
        )

    def test_zero_dim_fit_matches_reference_logistic_regression(self) -> None:
        rng = np.random.default_rng(43)
        hero_count = 14
        games = 6_000
        truth = HeroEmbeddingParameters(
            bias=0.15,
            main_effects=0.4 * rng.standard_normal(hero_count),
            embeddings=np.zeros((hero_count, 0)),
        )
        radiant, dire = _sample_drafts(rng, games, hero_count)
        targets = _sample_targets(rng, truth, radiant, dire)

        l2_main = 1e-3
        config = _make_config(
            hero_count=hero_count,
            embedding_dim=0,
            l2_main=l2_main,
            l2_embedding=0.0,
            learning_rate=0.1,
            max_iterations=8_000,
            gradient_tolerance=1e-9,
        )
        result = fit_hero_embedding_model(config, radiant, dire, targets)
        assert result.converged

        # Signed pick-presence design: +1 Radiant, -1 Dire, matching the
        # B1 side-relative contract.  Our mean-loss objective with penalty
        # l2 * ||w||^2 equals sklearn's with C = 1 / (2 * n * l2).
        design = np.zeros((games, hero_count))
        rows = np.arange(games)[:, None]
        design[rows, radiant] = 1.0
        design[rows, dire] = -1.0
        reference = LogisticRegression(
            C=1.0 / (2.0 * games * l2_main),
            solver="lbfgs",
            tol=1e-10,
            max_iter=20_000,
        )
        reference.fit(design, targets)

        np.testing.assert_allclose(
            result.parameters.main_effects,
            reference.coef_[0],
            atol=2e-4,
        )
        assert result.parameters.bias == pytest.approx(
            reference.intercept_[0], abs=2e-4
        )
        np.testing.assert_allclose(
            predict_probabilities(result.parameters, radiant, dire),
            reference.predict_proba(design)[:, 1],
            atol=1e-4,
        )


class TestValidation:
    def test_rejects_invalid_configurations(self) -> None:
        with pytest.raises(HeroEmbeddingError):
            _make_config(hero_count=9)
        with pytest.raises(HeroEmbeddingError):
            _make_config(embedding_dim=-1)
        with pytest.raises(HeroEmbeddingError):
            _make_config(l2_main=-0.1)
        with pytest.raises(HeroEmbeddingError):
            _make_config(learning_rate=0.0)
        with pytest.raises(HeroEmbeddingError):
            _make_config(max_iterations=0)

    def test_rejects_invalid_drafts_and_targets(self) -> None:
        parameters = initialize_parameters(_make_config())
        good_radiant = np.array([[0, 1, 2, 3, 4]])
        good_dire = np.array([[5, 6, 7, 8, 9]])

        with pytest.raises(HeroEmbeddingError):
            predict_log_odds(
                parameters, np.array([[0, 1, 2, 3, 3]]), good_dire
            )
        with pytest.raises(HeroEmbeddingError):
            predict_log_odds(
                parameters, good_radiant, np.array([[5, 6, 7, 8, 99]])
            )
        with pytest.raises(HeroEmbeddingError):
            predict_log_odds(
                parameters, good_radiant, np.array([[0, 6, 7, 8, 9]])
            )
        with pytest.raises(HeroEmbeddingError):
            predict_log_odds(
                parameters, good_radiant[:, :4], good_dire
            )
        with pytest.raises(HeroEmbeddingError):
            compute_objective_and_gradients(
                parameters,
                good_radiant,
                good_dire,
                np.array([0.5]),
                _make_config(),
            )

    def test_initialization_is_seeded(self) -> None:
        first = initialize_parameters(_make_config())
        second = initialize_parameters(_make_config())
        different = initialize_parameters(_make_config(seed=8))
        assert np.array_equal(first.embeddings, second.embeddings)
        assert not np.array_equal(first.embeddings, different.embeddings)
