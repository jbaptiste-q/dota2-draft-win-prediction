"""Deterministic, leakage-safe training-row recency policies.

This module only selects already-normalized supervised rows and calculates
optional training weights.  It does not load data, fit a transformer or
estimator, evaluate a model, or depend on acquisition code.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Hashable

import numpy as np
import pandas as pd

from .contracts import (
    SPLIT_ROLE_CALIBRATION,
    SPLIT_ROLE_LOCKED_TEST,
    SPLIT_ROLE_TRAIN,
)


RECENCY_POLICY_VERSION = "draft-ai-recency-policy-v1"
SECONDS_PER_DAY = 86_400.0
EXPONENTIAL_HALF_LIFE_DAYS = 180.0
TRAILING_WINDOW_DAYS = 365
RESERVED_ROLES = frozenset(
    {SPLIT_ROLE_CALIBRATION, SPLIT_ROLE_LOCKED_TEST}
)


class RecencyPolicyError(ValueError):
    """Raised when a recency selection could leak or produce invalid weights."""


class RecencyPolicy(StrEnum):
    """The deliberately small set of approved M4B.2 training policies."""

    FULL_UNIFORM = "full_uniform"
    FULL_EXP180 = "full_exp180"
    TRAILING365_UNIFORM = "trailing365_uniform"


@dataclass(frozen=True, slots=True)
class WeightAudit:
    """Reconciled coverage and normalized-weight statistics."""

    policy_id: str
    rows: int
    start_utc: datetime
    end_utc: datetime
    cutoff_utc_exclusive: datetime
    window_start_utc_inclusive: datetime | None
    weight_min: float
    weight_max: float
    weight_mean: float
    weight_sum: float
    effective_sample_size: float
    raw_weight_min: float
    raw_weight_max: float

    def to_payload(self) -> dict[str, object]:
        """Return a stable JSON-ready representation."""

        return {
            "policy_id": self.policy_id,
            "rows": self.rows,
            "start_utc": _iso_utc(self.start_utc),
            "end_utc": _iso_utc(self.end_utc),
            "cutoff_utc_exclusive": _iso_utc(
                self.cutoff_utc_exclusive
            ),
            "window_start_utc_inclusive": (
                _iso_utc(self.window_start_utc_inclusive)
                if self.window_start_utc_inclusive is not None
                else None
            ),
            "weight_min": self.weight_min,
            "weight_max": self.weight_max,
            "weight_mean": self.weight_mean,
            "weight_sum": self.weight_sum,
            "effective_sample_size": self.effective_sample_size,
            "raw_weight_min": self.raw_weight_min,
            "raw_weight_max": self.raw_weight_max,
        }


@dataclass(frozen=True, slots=True)
class RecencySelection:
    """Effective training rows, their original indices, and aligned weights."""

    policy: RecencyPolicy
    frame: pd.DataFrame
    source_indices: tuple[Hashable, ...]
    sample_weights: np.ndarray
    audit: WeightAudit
    policy_fingerprint: str


def _iso_utc(value: datetime | pd.Timestamp) -> str:
    timestamp = pd.Timestamp(value).tz_convert("UTC")
    return timestamp.isoformat().replace("+00:00", "Z")


def _aware_utc_timestamp(value: object, *, label: str) -> pd.Timestamp:
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError) as error:
        raise RecencyPolicyError(f"{label} is not a valid timestamp.") from error
    if pd.isna(timestamp) or timestamp.tzinfo is None:
        raise RecencyPolicyError(
            f"{label} must be a non-missing timezone-aware timestamp."
        )
    return timestamp.tz_convert("UTC")


def _normalized_timestamps(
    values: pd.Series,
    *,
    column: str,
) -> pd.Series:
    normalized = [
        _aware_utc_timestamp(value, label=column)
        for value in values.tolist()
    ]
    return pd.Series(
        normalized,
        index=values.index,
        dtype="datetime64[ns, UTC]",
    )


def _policy_payload(
    policy: RecencyPolicy,
    cutoff: pd.Timestamp,
) -> dict[str, object]:
    definition: dict[str, object]
    if policy == RecencyPolicy.FULL_UNIFORM:
        definition = {
            "training_window": "all_available_strictly_before_cutoff",
            "weighting": "uniform_mean_one",
        }
    elif policy == RecencyPolicy.FULL_EXP180:
        definition = {
            "training_window": "all_available_strictly_before_cutoff",
            "weighting": "exponential_mean_one",
            "raw_weight_formula": "2**(-age_days/180)",
            "half_life_days": EXPONENTIAL_HALF_LIFE_DAYS,
            "age_anchor": "exact_train_cutoff",
        }
    else:
        definition = {
            "training_window": "trailing_days",
            "trailing_days": TRAILING_WINDOW_DAYS,
            "window_start": "exact_cutoff_minus_365_days",
            "weighting": "uniform_mean_one",
        }
    return {
        "policy_version": RECENCY_POLICY_VERSION,
        "policy_id": policy.value,
        "train_cutoff_utc_exclusive": _iso_utc(cutoff),
        "definition": definition,
    }


def recency_policy_fingerprint(
    policy: RecencyPolicy | str,
    *,
    train_cutoff_utc: object,
) -> str:
    """Fingerprint one policy definition and its exact training cutoff."""

    resolved = RecencyPolicy(policy)
    cutoff = _aware_utc_timestamp(
        train_cutoff_utc,
        label="train_cutoff_utc",
    )
    encoded = json.dumps(
        _policy_payload(resolved, cutoff),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _raw_weights(
    policy: RecencyPolicy,
    timestamps: pd.Series,
    cutoff: pd.Timestamp,
) -> np.ndarray:
    if policy != RecencyPolicy.FULL_EXP180:
        return np.ones(len(timestamps), dtype=np.float64)
    age_seconds = (
        cutoff - timestamps
    ).dt.total_seconds().to_numpy(dtype=np.float64)
    if not np.isfinite(age_seconds).all() or (age_seconds <= 0).any():
        raise RecencyPolicyError(
            "Exponential weights require finite, strictly past timestamps."
        )
    age_days = age_seconds / SECONDS_PER_DAY
    return np.exp2(-age_days / EXPONENTIAL_HALF_LIFE_DAYS)


def _normalized_weights(raw_weights: np.ndarray) -> np.ndarray:
    if (
        raw_weights.ndim != 1
        or raw_weights.size == 0
        or not np.isfinite(raw_weights).all()
        or (raw_weights <= 0).any()
    ):
        raise RecencyPolicyError(
            "Raw sample weights must be non-empty, finite, and positive."
        )
    raw_mean = float(raw_weights.mean())
    if not np.isfinite(raw_mean) or raw_mean <= 0:
        raise RecencyPolicyError("Raw sample weights have an invalid mean.")
    weights = np.asarray(raw_weights / raw_mean, dtype=np.float64)
    if not np.isfinite(weights).all() or (weights <= 0).any():
        raise RecencyPolicyError(
            "Normalized sample weights must be finite and positive."
        )
    weights.setflags(write=False)
    return weights


def select_training_rows(
    frame: pd.DataFrame,
    *,
    policy: RecencyPolicy | str,
    train_cutoff_utc: object,
    time_column: str = "match_start_utc",
    role_column: str = "split_role",
) -> RecencySelection:
    """Select strictly past training rows and calculate aligned mean-one weights.

    Rows at or after ``train_cutoff_utc`` are never returned or inspected for
    targets.  Any reserved or otherwise non-training role that falls inside
    the effective training interval fails closed.
    """

    if not isinstance(frame, pd.DataFrame):
        raise TypeError("Training input must be a pandas DataFrame.")
    if frame.empty:
        raise RecencyPolicyError("Training input cannot be empty.")
    missing = sorted({time_column, role_column}.difference(frame.columns))
    if missing:
        raise RecencyPolicyError(
            "Training input is missing required columns: "
            + ", ".join(missing)
        )
    if not frame.index.is_unique:
        raise RecencyPolicyError(
            "Training input indices must be unique for reproducible alignment."
        )

    resolved = RecencyPolicy(policy)
    cutoff = _aware_utc_timestamp(
        train_cutoff_utc,
        label="train_cutoff_utc",
    )
    timestamps = _normalized_timestamps(
        frame[time_column],
        column=time_column,
    )
    window_start = (
        cutoff - pd.Timedelta(days=TRAILING_WINDOW_DAYS)
        if resolved == RecencyPolicy.TRAILING365_UNIFORM
        else None
    )
    selected = timestamps.lt(cutoff)
    if window_start is not None:
        selected &= timestamps.ge(window_start)

    source_indices = tuple(frame.index[selected].tolist())
    effective = frame.loc[selected].copy()
    effective[time_column] = timestamps.loc[selected]
    if effective.empty:
        raise RecencyPolicyError(
            f"{resolved.value} produced no effective training rows."
        )

    roles = effective[role_column].astype("string")
    if roles.isna().any() or roles.str.strip().eq("").any():
        raise RecencyPolicyError("Effective training rows contain a missing role.")
    reserved = sorted(set(roles).intersection(RESERVED_ROLES))
    if reserved:
        raise RecencyPolicyError(
            "Effective training rows include reserved roles: "
            + ", ".join(reserved)
        )
    unsupported = sorted(set(roles).difference({SPLIT_ROLE_TRAIN}))
    if unsupported:
        raise RecencyPolicyError(
            "Effective training rows include non-training roles: "
            + ", ".join(unsupported)
        )

    effective_timestamps = effective[time_column]
    if effective_timestamps.ge(cutoff).any():
        raise RecencyPolicyError(
            "Effective training timestamps must be strictly before cutoff."
        )
    if (
        window_start is not None
        and effective_timestamps.lt(window_start).any()
    ):
        raise RecencyPolicyError(
            "A trailing-window row precedes the exact 365-day boundary."
        )

    raw = _raw_weights(resolved, effective_timestamps, cutoff)
    weights = _normalized_weights(raw)
    weight_sum = float(weights.sum())
    effective_sample_size = float(
        (weight_sum * weight_sum) / np.square(weights).sum()
    )
    audit = WeightAudit(
        policy_id=resolved.value,
        rows=len(effective),
        start_utc=effective_timestamps.min().to_pydatetime(warn=False),
        end_utc=effective_timestamps.max().to_pydatetime(warn=False),
        cutoff_utc_exclusive=cutoff.to_pydatetime(warn=False),
        window_start_utc_inclusive=(
            window_start.to_pydatetime(warn=False)
            if window_start is not None
            else None
        ),
        weight_min=float(weights.min()),
        weight_max=float(weights.max()),
        weight_mean=float(weights.mean()),
        weight_sum=weight_sum,
        effective_sample_size=effective_sample_size,
        raw_weight_min=float(raw.min()),
        raw_weight_max=float(raw.max()),
    )
    return RecencySelection(
        policy=resolved,
        frame=effective,
        source_indices=source_indices,
        sample_weights=weights,
        audit=audit,
        policy_fingerprint=recency_policy_fingerprint(
            resolved,
            train_cutoff_utc=cutoff,
        ),
    )


__all__ = [
    "EXPONENTIAL_HALF_LIFE_DAYS",
    "RECENCY_POLICY_VERSION",
    "TRAILING_WINDOW_DAYS",
    "RecencyPolicy",
    "RecencyPolicyError",
    "RecencySelection",
    "WeightAudit",
    "recency_policy_fingerprint",
    "select_training_rows",
]
