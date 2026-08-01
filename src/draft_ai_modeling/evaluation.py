"""Deterministic probability evaluation for development-only Draft AI models."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from typing import Any
from urllib.parse import unquote

import numpy as np
from scipy.sparse import csr_matrix
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    brier_score_loss,
    log_loss,
    roc_auc_score,
)


BOOTSTRAP_METRICS = (
    "log_loss",
    "brier_score",
    "roc_auc",
    "accuracy",
    "balanced_accuracy",
    "expected_calibration_error",
)


class EvaluationError(ValueError):
    """Raised when prediction, grouping, or coefficient evidence is invalid."""


def _arrays(
    targets: Sequence[object],
    probabilities: Sequence[float] | np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    y_true = np.asarray(targets, dtype=np.int8)
    predicted = np.asarray(probabilities, dtype=np.float64)
    if (
        y_true.ndim != 1
        or predicted.ndim != 1
        or len(y_true) != len(predicted)
        or not len(y_true)
    ):
        raise EvaluationError(
            "Targets and probabilities must be equal-length non-empty vectors."
        )
    if not set(np.unique(y_true)).issubset({0, 1}):
        raise EvaluationError("Targets must be binary zero/one values.")
    if not np.isfinite(predicted).all() or (
        (predicted < 0) | (predicted > 1)
    ).any():
        raise EvaluationError("Probabilities must be finite values in [0, 1].")
    return y_true, predicted


def _logit(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(values, 1e-12, 1 - 1e-12)
    return np.log(clipped / (1 - clipped))


def reliability_bins(
    targets: Sequence[object],
    probabilities: Sequence[float] | np.ndarray,
    *,
    n_bins: int = 10,
) -> tuple[list[dict[str, object]], float]:
    """Return fixed equal-width reliability bins and weighted ECE."""

    y_true, predicted = _arrays(targets, probabilities)
    if n_bins < 2 or n_bins > 100:
        raise EvaluationError("Reliability bin count must be between 2 and 100.")
    positions = np.minimum(
        np.floor(predicted * n_bins).astype(np.int64),
        n_bins - 1,
    )
    records: list[dict[str, object]] = []
    ece = 0.0
    for index in range(n_bins):
        selected = positions == index
        count = int(selected.sum())
        lower = index / n_bins
        upper = (index + 1) / n_bins
        if count:
            mean_probability = float(predicted[selected].mean())
            observed_rate = float(y_true[selected].mean())
            absolute_gap = abs(mean_probability - observed_rate)
            contribution = count / len(y_true) * absolute_gap
            ece += contribution
        else:
            mean_probability = None
            observed_rate = None
            absolute_gap = None
            contribution = 0.0
        records.append(
            {
                "bin_index": index,
                "lower_bound_inclusive": lower,
                "upper_bound_exclusive": upper if index < n_bins - 1 else None,
                "includes_probability_one": index == n_bins - 1,
                "count": count,
                "mean_probability": mean_probability,
                "observed_positive_rate": observed_rate,
                "absolute_gap": absolute_gap,
                "ece_contribution": float(contribution),
            }
        )
    return records, float(ece)


def _calibration_diagnostics(
    y_true: np.ndarray,
    predicted: np.ndarray,
) -> tuple[float, float | None, float]:
    observed_log_odds = float(_logit(np.asarray([y_true.mean()]))[0])
    predicted_log_odds = float(_logit(np.asarray([predicted.mean()]))[0])
    calibration_in_the_large = observed_log_odds - predicted_log_odds
    logits = _logit(predicted)
    if float(np.std(logits)) < 1e-12:
        return (
            float(calibration_in_the_large),
            None,
            observed_log_odds,
        )
    model = LogisticRegression(
        C=np.inf,
        solver="lbfgs",
        max_iter=2000,
        random_state=42,
    ).fit(logits.reshape(-1, 1), y_true)
    return (
        float(calibration_in_the_large),
        float(model.coef_[0, 0]),
        float(model.intercept_[0]),
    )


def _core_metrics(
    y_true: np.ndarray,
    predicted: np.ndarray,
    *,
    n_bins: int,
    include_calibration_fit: bool,
) -> tuple[dict[str, float | None], list[dict[str, object]]]:
    bins, ece = reliability_bins(y_true, predicted, n_bins=n_bins)
    classes = np.unique(y_true)
    metrics: dict[str, float | None] = {
        "log_loss": float(log_loss(y_true, predicted, labels=[0, 1])),
        "brier_score": float(brier_score_loss(y_true, predicted)),
        "roc_auc": (
            float(roc_auc_score(y_true, predicted))
            if len(classes) == 2
            else None
        ),
        "accuracy": float(accuracy_score(y_true, predicted >= 0.5)),
        "balanced_accuracy": (
            float(balanced_accuracy_score(y_true, predicted >= 0.5))
            if len(classes) == 2
            else None
        ),
        "expected_calibration_error": ece,
    }
    if include_calibration_fit:
        (
            calibration_in_the_large,
            calibration_slope,
            calibration_intercept,
        ) = _calibration_diagnostics(y_true, predicted)
        metrics.update(
            {
                "calibration_in_the_large": calibration_in_the_large,
                "calibration_slope": calibration_slope,
                "calibration_intercept": calibration_intercept,
            }
        )
    return metrics, bins


def evaluate_probabilities(
    targets: Sequence[object],
    probabilities: Sequence[float] | np.ndarray,
    *,
    n_bins: int = 10,
) -> dict[str, object]:
    """Evaluate one probability vector without fitting a calibrator."""

    y_true, predicted = _arrays(targets, probabilities)
    metrics, bins = _core_metrics(
        y_true,
        predicted,
        n_bins=n_bins,
        include_calibration_fit=True,
    )
    return {
        "rows": len(y_true),
        "positive_rows": int(y_true.sum()),
        "negative_rows": int(len(y_true) - y_true.sum()),
        "probability_threshold": 0.5,
        "reliability_bin_policy": "equal_width",
        "metrics": metrics,
        "reliability_bins": bins,
    }


def grouped_bootstrap_confidence_intervals(
    targets: Sequence[object],
    probabilities: Sequence[float] | np.ndarray,
    groups: Sequence[object],
    *,
    confidence_level: float = 0.95,
    n_resamples: int = 1000,
    random_state: int = 42,
    n_bins: int = 10,
) -> dict[str, object]:
    """Return deterministic percentile intervals from source-match resampling."""

    y_true, predicted = _arrays(targets, probabilities)
    group_values = np.asarray([str(value) for value in groups], dtype=object)
    if group_values.shape != y_true.shape or any(
        not value for value in group_values
    ):
        raise EvaluationError("Bootstrap groups must cover every prediction.")
    if not 0 < confidence_level < 1:
        raise EvaluationError("Bootstrap confidence level must be in (0, 1).")
    if n_resamples < 1:
        raise EvaluationError("Bootstrap replicate count must be positive.")

    unique_groups = np.asarray(sorted(set(group_values.tolist())), dtype=object)
    group_rows = {
        value: np.flatnonzero(group_values == value)
        for value in unique_groups
    }
    rng = np.random.default_rng(random_state)
    samples: dict[str, list[float]] = {
        name: [] for name in BOOTSTRAP_METRICS
    }
    successful = 0
    for _ in range(n_resamples):
        selected_groups = rng.choice(
            unique_groups,
            size=len(unique_groups),
            replace=True,
        )
        positions = np.concatenate(
            [group_rows[value] for value in selected_groups]
        )
        metrics, _ = _core_metrics(
            y_true[positions],
            predicted[positions],
            n_bins=n_bins,
            include_calibration_fit=False,
        )
        if any(metrics[name] is None for name in BOOTSTRAP_METRICS):
            continue
        for name in BOOTSTRAP_METRICS:
            samples[name].append(float(metrics[name]))
        successful += 1
    if not successful:
        raise EvaluationError("No grouped bootstrap replicate was evaluable.")

    point, _ = _core_metrics(
        y_true,
        predicted,
        n_bins=n_bins,
        include_calibration_fit=False,
    )
    tail = (1 - confidence_level) / 2
    intervals = {
        name: {
            "point_estimate": point[name],
            "lower": float(np.quantile(values, tail)),
            "upper": float(np.quantile(values, 1 - tail)),
        }
        for name, values in samples.items()
        if values
    }
    return {
        "method": "grouped_percentile_bootstrap",
        "group_unit": "source_match_id",
        "confidence_level": confidence_level,
        "random_state": random_state,
        "requested_resamples": n_resamples,
        "successful_resamples": successful,
        "unique_groups": len(unique_groups),
        "metrics": intervals,
    }


def _coefficient_record(
    name: str,
    coefficient: float,
    support: int,
) -> dict[str, object]:
    parts = name.split("::")
    return {
        "feature": name,
        "representation": parts[0] if parts else "unknown",
        "draft_role_or_slot": parts[1] if len(parts) > 1 else None,
        "hero_key": unquote(parts[-1]) if parts else None,
        "coefficient_log_odds": coefficient,
        "odds_ratio": float(math.exp(np.clip(coefficient, -50, 50))),
        "training_row_support": support,
    }


def global_logistic_coefficient_explanations(
    estimator: object,
    training_matrix: csr_matrix,
    feature_names: Sequence[object],
    *,
    top_k: int = 20,
) -> dict[str, object]:
    """Return faithful global signed log-odds evidence for a fitted logistic model."""

    if not isinstance(training_matrix, csr_matrix):
        raise EvaluationError("Coefficient support requires a CSR matrix.")
    coefficients = np.asarray(getattr(estimator, "coef_", None))
    intercept = np.asarray(getattr(estimator, "intercept_", None))
    names = tuple(str(value) for value in feature_names)
    if (
        coefficients.shape != (1, training_matrix.shape[1])
        or intercept.shape != (1,)
        or len(names) != training_matrix.shape[1]
        or len(set(names)) != len(names)
        or top_k < 1
    ):
        raise EvaluationError("Estimator coefficients do not match features.")
    values = coefficients[0].astype(np.float64)
    if not np.isfinite(values).all() or not np.isfinite(intercept).all():
        raise EvaluationError("Estimator coefficients are non-finite.")
    support = np.asarray(training_matrix.getnnz(axis=0)).reshape(-1)
    eligible = np.flatnonzero(support > 0)
    positive = sorted(
        eligible,
        key=lambda index: (-values[index], names[index]),
    )[:top_k]
    negative = sorted(
        eligible,
        key=lambda index: (values[index], names[index]),
    )[:top_k]
    vector_bytes = values.astype("<f8", copy=False).tobytes()
    return {
        "kind": "exact_linear_log_odds",
        "interpretation": "associative_not_causal",
        "intercept_log_odds": float(intercept[0]),
        "feature_count": len(names),
        "features_with_training_support": int((support > 0).sum()),
        "nonzero_coefficient_count": int((np.abs(values) > 1e-12).sum()),
        "coefficient_l1_norm": float(np.abs(values).sum()),
        "coefficient_l2_norm": float(np.linalg.norm(values)),
        "coefficient_vector_sha256": hashlib.sha256(vector_bytes).hexdigest(),
        "top_positive": [
            _coefficient_record(
                names[index],
                float(values[index]),
                int(support[index]),
            )
            for index in positive
        ],
        "top_negative": [
            _coefficient_record(
                names[index],
                float(values[index]),
                int(support[index]),
            )
            for index in negative
        ],
    }


__all__ = [
    "BOOTSTRAP_METRICS",
    "EvaluationError",
    "evaluate_probabilities",
    "global_logistic_coefficient_explanations",
    "grouped_bootstrap_confidence_intervals",
    "reliability_bins",
]
