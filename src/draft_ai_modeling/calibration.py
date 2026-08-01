"""Deterministic, group-safe calibration utilities for Draft AI.

The module operates only on an already-generated raw probability vector.  It
has no acquisition, feature-fitting, estimator-selection, or test-set
dependency.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedGroupKFold


CALIBRATION_METHODS = ("raw", "sigmoid", "isotonic")
DEFAULT_CALIBRATION_FOLDS = 5
DEFAULT_RANDOM_STATE = 42
DEFAULT_BOOTSTRAP_RESAMPLES = 1_000
DEFAULT_CONFIDENCE_LEVEL = 0.95
LOGIT_CLIP_EPSILON = 1e-12

_CALIBRATION_INPUT_COLUMNS = (
    "sample_id",
    "source_match_id",
    "radiant_win",
    "raw_probability",
)
_METHOD_PREDICTION_COLUMNS = (
    "sample_id",
    "source_match_id",
    "radiant_win",
    "radiant_win_probability",
)


class CalibrationError(ValueError):
    """Raised when calibration inputs or outputs violate the contract."""


@dataclass(frozen=True, slots=True)
class CrossFittedCalibrationResult:
    """Aligned cross-fitted method predictions and group-safe assignments."""

    predictions: pd.DataFrame
    fold_assignments: pd.DataFrame
    audit: dict[str, Any]


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _normalized_identifiers(
    values: pd.Series,
    *,
    column: str,
    context: str,
) -> pd.Series:
    if values.isna().any():
        raise CalibrationError(f"{context} contains missing {column}.")
    normalized = values.astype("string").str.strip()
    if normalized.eq("").any():
        raise CalibrationError(f"{context} contains empty {column}.")
    return normalized


def _binary_targets(
    values: pd.Series,
    *,
    context: str,
) -> pd.Series:
    if values.isna().any():
        raise CalibrationError(f"{context} contains missing radiant_win.")
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.isna().any() or not set(numeric.unique()).issubset({0, 1}):
        raise CalibrationError(f"{context} targets must be binary zero/one.")
    return numeric.astype("int8")


def _probabilities(
    values: pd.Series,
    *,
    context: str,
    strictly_interior: bool,
) -> np.ndarray:
    numeric = pd.to_numeric(values, errors="coerce").to_numpy(
        dtype=np.float64
    )
    invalid = not np.isfinite(numeric).all()
    if strictly_interior:
        invalid = invalid or ((numeric <= 0) | (numeric >= 1)).any()
        interval = "(0, 1)"
    else:
        invalid = invalid or ((numeric < 0) | (numeric > 1)).any()
        interval = "[0, 1]"
    if invalid:
        raise CalibrationError(
            f"{context} probabilities must be finite values in {interval}."
        )
    return numeric


def _validated_calibration_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("Calibration input must be a pandas DataFrame.")
    if frame.columns.duplicated().any():
        raise CalibrationError(
            "Calibration input contains duplicate column names."
        )
    missing = sorted(
        set(_CALIBRATION_INPUT_COLUMNS).difference(frame.columns)
    )
    if missing:
        raise CalibrationError(
            "Calibration input is missing columns: " + ", ".join(missing)
        )
    if frame.empty:
        raise CalibrationError("Calibration input cannot be empty.")

    result = frame.loc[:, list(_CALIBRATION_INPUT_COLUMNS)].copy()
    result["sample_id"] = _normalized_identifiers(
        result["sample_id"],
        column="sample_id",
        context="Calibration input",
    )
    result["source_match_id"] = _normalized_identifiers(
        result["source_match_id"],
        column="source_match_id",
        context="Calibration input",
    )
    if result["sample_id"].duplicated().any():
        duplicate = result.loc[
            result["sample_id"].duplicated(keep=False),
            "sample_id",
        ].iloc[0]
        raise CalibrationError(
            f"Calibration input contains duplicate sample_id: {duplicate}"
        )
    result["radiant_win"] = _binary_targets(
        result["radiant_win"],
        context="Calibration input",
    )
    result["raw_probability"] = _probabilities(
        result["raw_probability"],
        context="Raw calibration",
        strictly_interior=True,
    )
    return result.sort_values("sample_id", kind="stable").reset_index(
        drop=True
    )


def _raw_logits(probabilities: np.ndarray) -> np.ndarray:
    clipped = np.clip(
        probabilities,
        LOGIT_CLIP_EPSILON,
        1 - LOGIT_CLIP_EPSILON,
    )
    return np.log(clipped / (1 - clipped))


def _fit_sigmoid(
    fit_probabilities: np.ndarray,
    fit_targets: np.ndarray,
    *,
    random_state: int,
) -> LogisticRegression:
    calibrator = LogisticRegression(
        C=np.inf,
        solver="lbfgs",
        max_iter=2_000,
        random_state=random_state,
    )
    calibrator.fit(
        _raw_logits(fit_probabilities).reshape(-1, 1),
        fit_targets,
    )
    if float(calibrator.coef_[0, 0]) <= 0:
        raise CalibrationError(
            "Sigmoid calibration learned a non-positive slope."
        )
    return calibrator


def _fit_isotonic(
    fit_probabilities: np.ndarray,
    fit_targets: np.ndarray,
) -> IsotonicRegression:
    calibrator = IsotonicRegression(
        increasing=True,
        out_of_bounds="clip",
    )
    calibrator.fit(fit_probabilities, fit_targets)
    return calibrator


def fit_calibrator(
    method: str,
    raw_probabilities: np.ndarray,
    targets: np.ndarray,
    *,
    random_state: int = DEFAULT_RANDOM_STATE,
) -> LogisticRegression | IsotonicRegression | None:
    """Fit one declared calibrator; raw identity deliberately returns ``None``."""

    resolved = str(method)
    if resolved not in CALIBRATION_METHODS:
        raise CalibrationError(f"Unknown calibration method: {resolved!r}.")
    probabilities = np.asarray(raw_probabilities, dtype=np.float64)
    labels = np.asarray(targets, dtype=np.int8)
    if (
        probabilities.ndim != 1
        or labels.shape != probabilities.shape
        or not np.isfinite(probabilities).all()
        or ((probabilities <= 0) | (probabilities >= 1)).any()
    ):
        raise CalibrationError(
            "Calibrator fit requires aligned probabilities in (0, 1)."
        )
    if not set(np.unique(labels)).issubset({0, 1}) or len(
        np.unique(labels)
    ) != 2:
        raise CalibrationError(
            "Calibrator fit requires both binary target classes."
        )
    if resolved == "raw":
        return None
    if resolved == "sigmoid":
        return _fit_sigmoid(
            probabilities,
            labels,
            random_state=random_state,
        )
    return _fit_isotonic(probabilities, labels)


def apply_calibrator(
    method: str,
    calibrator: LogisticRegression | IsotonicRegression | None,
    raw_probabilities: np.ndarray,
) -> np.ndarray:
    """Apply a declared calibration mapping to an aligned raw vector."""

    resolved = str(method)
    probabilities = np.asarray(raw_probabilities, dtype=np.float64)
    if (
        probabilities.ndim != 1
        or not np.isfinite(probabilities).all()
        or ((probabilities <= 0) | (probabilities >= 1)).any()
    ):
        raise CalibrationError(
            "Calibration requires raw probabilities in (0, 1)."
        )
    if resolved == "raw":
        if calibrator is not None:
            raise CalibrationError("Raw calibration must not have an estimator.")
        result = probabilities.copy()
    elif resolved == "sigmoid":
        if not isinstance(calibrator, LogisticRegression):
            raise CalibrationError("Sigmoid calibrator type is invalid.")
        result = calibrator.predict_proba(
            _raw_logits(probabilities).reshape(-1, 1)
        )[:, 1]
    elif resolved == "isotonic":
        if not isinstance(calibrator, IsotonicRegression):
            raise CalibrationError("Isotonic calibrator type is invalid.")
        result = np.asarray(
            calibrator.predict(probabilities),
            dtype=np.float64,
        )
    else:
        raise CalibrationError(f"Unknown calibration method: {resolved!r}.")
    if (
        result.shape != probabilities.shape
        or not np.isfinite(result).all()
        or ((result < 0) | (result > 1)).any()
    ):
        raise CalibrationError(
            f"{resolved} produced invalid calibrated probabilities."
        )
    return result


def cross_fitted_calibration_predictions(
    frame: pd.DataFrame,
    *,
    n_splits: int = DEFAULT_CALIBRATION_FOLDS,
    random_state: int = DEFAULT_RANDOM_STATE,
) -> CrossFittedCalibrationResult:
    """Create aligned raw, sigmoid, and isotonic out-of-fold predictions."""

    rows = _validated_calibration_frame(frame)
    if n_splits != DEFAULT_CALIBRATION_FOLDS:
        raise CalibrationError("The calibration contract requires five folds.")
    group_count = int(rows["source_match_id"].nunique())
    if group_count < n_splits:
        raise CalibrationError(
            "Calibration requires at least one source match per fold."
        )
    targets = rows["radiant_win"].to_numpy(dtype=np.int8)
    if len(np.unique(targets)) != 2:
        raise CalibrationError(
            "Calibration input must contain both target classes."
        )
    if int(np.bincount(targets, minlength=2).min()) < n_splits:
        raise CalibrationError(
            "Calibration fold fits lack both classes with five-fold "
            "stratification."
        )
    probabilities = rows["raw_probability"].to_numpy(dtype=np.float64)
    groups = rows["source_match_id"].astype(str).to_numpy(dtype=object)

    splitter = StratifiedGroupKFold(
        n_splits=n_splits,
        shuffle=True,
        random_state=random_state,
    )
    fold_ids = np.full(len(rows), -1, dtype=np.int8)
    sigmoid = np.full(len(rows), np.nan, dtype=np.float64)
    isotonic = np.full(len(rows), np.nan, dtype=np.float64)
    fold_audits: list[dict[str, Any]] = []

    for fold_id, (fit_positions, evaluation_positions) in enumerate(
        splitter.split(
            np.zeros(len(rows), dtype=np.int8),
            targets,
            groups,
        )
    ):
        fit_targets = targets[fit_positions]
        if len(np.unique(fit_targets)) != 2:
            raise CalibrationError(
                f"Calibration fold {fold_id} fit rows lack both classes."
            )
        fit_groups = set(groups[fit_positions].tolist())
        evaluation_groups = set(groups[evaluation_positions].tolist())
        if fit_groups.intersection(evaluation_groups):
            raise CalibrationError(
                f"Calibration fold {fold_id} leaks source-match groups."
            )

        fold_ids[evaluation_positions] = fold_id
        sigmoid_calibrator = fit_calibrator(
            "sigmoid",
            probabilities[fit_positions],
            fit_targets,
            random_state=random_state,
        )
        isotonic_calibrator = fit_calibrator(
            "isotonic",
            probabilities[fit_positions],
            fit_targets,
            random_state=random_state,
        )
        sigmoid[evaluation_positions] = apply_calibrator(
            "sigmoid",
            sigmoid_calibrator,
            probabilities[evaluation_positions],
        )
        isotonic[evaluation_positions] = apply_calibrator(
            "isotonic",
            isotonic_calibrator,
            probabilities[evaluation_positions],
        )
        evaluation_targets = targets[evaluation_positions]
        if len(np.unique(evaluation_targets)) != 2:
            raise CalibrationError(
                f"Calibration fold {fold_id} evaluation rows lack both "
                "classes."
            )
        fold_audits.append(
            {
                "fold_id": fold_id,
                "fit_rows": len(fit_positions),
                "fit_source_matches": len(fit_groups),
                "fit_positive_rows": int(fit_targets.sum()),
                "fit_negative_rows": int(
                    len(fit_targets) - fit_targets.sum()
                ),
                "evaluation_rows": len(evaluation_positions),
                "evaluation_source_matches": len(evaluation_groups),
                "evaluation_positive_rows": int(
                    evaluation_targets.sum()
                ),
                "evaluation_negative_rows": int(
                    len(evaluation_targets) - evaluation_targets.sum()
                ),
                "group_overlap": 0,
                "sigmoid_slope": float(
                    sigmoid_calibrator.coef_[0, 0]
                ),
                "sigmoid_intercept": float(
                    sigmoid_calibrator.intercept_[0]
                ),
                "isotonic_threshold_count": int(
                    len(isotonic_calibrator.X_thresholds_)
                ),
                "isotonic_output_minimum": float(
                    isotonic[evaluation_positions].min()
                ),
                "isotonic_output_maximum": float(
                    isotonic[evaluation_positions].max()
                ),
                "isotonic_boundary_outputs": int(
                    (
                        (isotonic[evaluation_positions] == 0)
                        | (isotonic[evaluation_positions] == 1)
                    ).sum()
                ),
            }
        )

    if (fold_ids < 0).any() or not np.isfinite(sigmoid).all() or not np.isfinite(
        isotonic
    ).all():
        raise CalibrationError(
            "Cross-fitted calibration did not predict every row exactly once."
        )
    if ((sigmoid < 0) | (sigmoid > 1)).any() or (
        (isotonic < 0) | (isotonic > 1)
    ).any():
        raise CalibrationError(
            "A calibration method produced an invalid probability."
        )

    assignments = rows[
        ["sample_id", "source_match_id"]
    ].copy()
    assignments["calibration_fold"] = fold_ids
    group_fold_counts = assignments.groupby(
        "source_match_id",
        sort=False,
    )["calibration_fold"].nunique()
    if (group_fold_counts != 1).any():
        raise CalibrationError(
            "A source_match_id crosses calibration folds."
        )

    method_values = {
        "raw": probabilities,
        "sigmoid": sigmoid,
        "isotonic": isotonic,
    }
    prediction_frames: list[pd.DataFrame] = []
    for method in CALIBRATION_METHODS:
        method_frame = rows[
            ["sample_id", "source_match_id", "radiant_win"]
        ].copy()
        method_frame["calibration_method"] = method
        method_frame["radiant_win_probability"] = method_values[method]
        method_frame["calibration_fold"] = fold_ids
        prediction_frames.append(method_frame)
    predictions = pd.concat(
        prediction_frames,
        ignore_index=True,
    ).sort_values(
        ["calibration_method", "sample_id"],
        kind="stable",
    ).reset_index(drop=True)

    assignment_payload = assignments.to_dict(orient="records")
    return CrossFittedCalibrationResult(
        predictions=predictions,
        fold_assignments=assignments,
        audit={
            "rows": len(rows),
            "source_matches": group_count,
            "positive_rows": int(targets.sum()),
            "negative_rows": int(len(targets) - targets.sum()),
            "methods": list(CALIBRATION_METHODS),
            "prediction_rows": len(predictions),
            "prediction_rows_per_method": len(rows),
            "n_splits": n_splits,
            "splitter": "StratifiedGroupKFold",
            "shuffle": True,
            "random_state": random_state,
            "group_column": "source_match_id",
            "group_crossings": 0,
            "folds": fold_audits,
            "method_boundary_probability_counts": {
                method: int(
                    (
                        (values == 0)
                        | (values == 1)
                    ).sum()
                )
                for method, values in method_values.items()
            },
            "fold_assignment_sha256": hashlib.sha256(
                _canonical_json(assignment_payload).encode("utf-8")
            ).hexdigest(),
            "sigmoid_contract": {
                "input": "clipped_raw_logit",
                "logit_clip_epsilon": LOGIT_CLIP_EPSILON,
                "estimator": "LogisticRegression",
                "C": "infinity",
                "solver": "lbfgs",
                "max_iter": 2_000,
            },
            "isotonic_contract": {
                "input": "raw_probability",
                "estimator": "IsotonicRegression",
                "increasing": True,
                "out_of_bounds": "clip",
            },
        },
    )


def _validated_method_frame(
    frame: pd.DataFrame,
    *,
    context: str,
) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame):
        raise TypeError(f"{context} must be a pandas DataFrame.")
    if frame.columns.duplicated().any():
        raise CalibrationError(f"{context} has duplicate column names.")
    missing = sorted(
        set(_METHOD_PREDICTION_COLUMNS).difference(frame.columns)
    )
    if missing:
        raise CalibrationError(
            f"{context} is missing columns: " + ", ".join(missing)
        )
    if frame.empty:
        raise CalibrationError(f"{context} cannot be empty.")

    result = frame.loc[:, list(_METHOD_PREDICTION_COLUMNS)].copy()
    result["sample_id"] = _normalized_identifiers(
        result["sample_id"],
        column="sample_id",
        context=context,
    )
    result["source_match_id"] = _normalized_identifiers(
        result["source_match_id"],
        column="source_match_id",
        context=context,
    )
    if result["sample_id"].duplicated().any():
        raise CalibrationError(f"{context} contains duplicate sample IDs.")
    result["radiant_win"] = _binary_targets(
        result["radiant_win"],
        context=context,
    )
    result["radiant_win_probability"] = _probabilities(
        result["radiant_win_probability"],
        context=context,
        strictly_interior=False,
    )
    return result.sort_values("sample_id", kind="stable").reset_index(
        drop=True
    )


def _paired_method_rows(
    reference: pd.DataFrame,
    candidate: pd.DataFrame,
) -> pd.DataFrame:
    left = _validated_method_frame(
        reference,
        context="Reference method predictions",
    )
    right = _validated_method_frame(
        candidate,
        context="Candidate method predictions",
    )
    if left["sample_id"].tolist() != right["sample_id"].tolist():
        raise CalibrationError(
            "Reference and candidate sample alignment differs."
        )
    for column in ("source_match_id", "radiant_win"):
        if not np.array_equal(
            left[column].to_numpy(),
            right[column].to_numpy(),
        ):
            mismatch = int(
                np.flatnonzero(
                    left[column].to_numpy()
                    != right[column].to_numpy()
                )[0]
            )
            raise CalibrationError(
                f"Reference and candidate {column} differ for "
                f"{left.iloc[mismatch]['sample_id']}."
            )
    paired = left.rename(
        columns={
            "radiant_win_probability": "reference_probability",
        }
    )
    paired["candidate_probability"] = right[
        "radiant_win_probability"
    ].to_numpy(dtype=np.float64)
    return paired


def _per_row_losses(
    targets: np.ndarray,
    probabilities: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    clipped = np.clip(
        probabilities,
        np.finfo(np.float64).eps,
        1 - np.finfo(np.float64).eps,
    )
    log_losses = -(
        targets * np.log(clipped)
        + (1 - targets) * np.log1p(-clipped)
    )
    brier_losses = np.square(targets - probabilities)
    return log_losses, brier_losses


def _paired_interval(
    reference_losses: np.ndarray,
    candidate_losses: np.ndarray,
    bootstrap_differences: np.ndarray,
    *,
    confidence_level: float,
) -> dict[str, float | str]:
    tail = (1 - confidence_level) / 2
    return {
        "difference_direction": "candidate_minus_reference",
        "reference_point_estimate": float(reference_losses.mean()),
        "candidate_point_estimate": float(candidate_losses.mean()),
        "point_estimate": float(
            np.mean(candidate_losses - reference_losses)
        ),
        "lower": float(np.quantile(bootstrap_differences, tail)),
        "upper": float(
            np.quantile(bootstrap_differences, 1 - tail)
        ),
    }


def paired_method_bootstrap_comparison(
    reference_predictions: pd.DataFrame,
    candidate_predictions: pd.DataFrame,
    *,
    n_resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES,
    random_state: int = DEFAULT_RANDOM_STATE,
    confidence_level: float = DEFAULT_CONFIDENCE_LEVEL,
) -> dict[str, Any]:
    """Compare aligned method predictions with a paired match bootstrap."""

    if n_resamples < 1:
        raise CalibrationError("Bootstrap resamples must be positive.")
    if not 0 < confidence_level < 1:
        raise CalibrationError(
            "Bootstrap confidence level must be in (0, 1)."
        )
    paired = _paired_method_rows(
        reference_predictions,
        candidate_predictions,
    )
    targets = paired["radiant_win"].to_numpy(dtype=np.float64)
    reference_log, reference_brier = _per_row_losses(
        targets,
        paired["reference_probability"].to_numpy(dtype=np.float64),
    )
    candidate_log, candidate_brier = _per_row_losses(
        targets,
        paired["candidate_probability"].to_numpy(dtype=np.float64),
    )
    groups = paired["source_match_id"].astype(str).to_numpy(dtype=object)
    unique_groups = np.asarray(sorted(set(groups.tolist())), dtype=object)
    rows_by_group = {
        group: np.flatnonzero(groups == group)
        for group in unique_groups
    }
    rng = np.random.default_rng(random_state)
    log_differences = np.empty(n_resamples, dtype=np.float64)
    brier_differences = np.empty(n_resamples, dtype=np.float64)
    resampled_rows = np.empty(n_resamples, dtype=np.int64)
    for index in range(n_resamples):
        selected_groups = rng.choice(
            unique_groups,
            size=len(unique_groups),
            replace=True,
        )
        positions = np.concatenate(
            [rows_by_group[group] for group in selected_groups]
        )
        resampled_rows[index] = len(positions)
        log_differences[index] = float(
            np.mean(candidate_log[positions] - reference_log[positions])
        )
        brier_differences[index] = float(
            np.mean(
                candidate_brier[positions] - reference_brier[positions]
            )
        )

    return {
        "difference_direction": "candidate_minus_reference",
        "metrics": {
            "log_loss": _paired_interval(
                reference_log,
                candidate_log,
                log_differences,
                confidence_level=confidence_level,
            ),
            "brier_score": _paired_interval(
                reference_brier,
                candidate_brier,
                brier_differences,
                confidence_level=confidence_level,
            ),
        },
        "audit": {
            "rows": len(paired),
            "source_matches": len(unique_groups),
            "positive_rows": int(targets.sum()),
            "negative_rows": int(len(targets) - targets.sum()),
            "bootstrap_method": "paired_source_match_percentile",
            "confidence_level": confidence_level,
            "random_state": random_state,
            "requested_resamples": n_resamples,
            "successful_resamples": n_resamples,
            "group_draws_per_resample": len(unique_groups),
            "total_group_draws": n_resamples * len(unique_groups),
            "minimum_rows_per_resample": int(resampled_rows.min()),
            "maximum_rows_per_resample": int(resampled_rows.max()),
            "group_multiplicity_preserved": True,
        },
    }


__all__ = [
    "CALIBRATION_METHODS",
    "CalibrationError",
    "CrossFittedCalibrationResult",
    "DEFAULT_BOOTSTRAP_RESAMPLES",
    "DEFAULT_CALIBRATION_FOLDS",
    "DEFAULT_CONFIDENCE_LEVEL",
    "DEFAULT_RANDOM_STATE",
    "LOGIT_CLIP_EPSILON",
    "apply_calibrator",
    "cross_fitted_calibration_predictions",
    "fit_calibrator",
    "paired_method_bootstrap_comparison",
]
