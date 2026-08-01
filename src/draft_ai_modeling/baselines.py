"""Declarative, unfitted estimator factories for Draft AI baselines."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from types import MappingProxyType

from sklearn.base import BaseEstimator
from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression

from .contracts import (
    BASELINE_CONTRACT_VERSION,
    CURRENT_BASELINE_FRAMEWORK,
    BaselineSpec,
)
from .features import FeatureVariant


DEFAULT_RANDOM_STATE = 42


class BaselineId(StrEnum):
    """Stable identifiers for the deliberately small baseline sequence."""

    B0_EMPIRICAL_PRIOR = "B0"
    B1_PICK_PRESENCE = "B1"
    B2_PICK_BAN_PRESENCE = "B2"
    B3_SLOT_AWARE = "B3"


BASELINE_SPECS = MappingProxyType(
    {
        BaselineId(spec.baseline_id): spec
        for spec in CURRENT_BASELINE_FRAMEWORK.baselines
    }
)

BASELINE_FEATURE_VARIANTS = MappingProxyType(
    {
        BaselineId.B0_EMPIRICAL_PRIOR: None,
        BaselineId.B1_PICK_PRESENCE: FeatureVariant.B1_PICK_PRESENCE,
        BaselineId.B2_PICK_BAN_PRESENCE: (
            FeatureVariant.B2_PICK_BAN_PRESENCE
        ),
        BaselineId.B3_SLOT_AWARE: FeatureVariant.B3_SLOT_AWARE,
    }
)

_LOGISTIC_PARAMETERS = MappingProxyType(
    {
        "C": 1.0,
        "class_weight": None,
        "max_iter": 2000,
        "penalty": "l2",
        "solver": "liblinear",
    }
)


def get_baseline_spec(baseline_id: BaselineId | str) -> BaselineSpec:
    """Resolve one stable baseline declaration."""

    return BASELINE_SPECS[BaselineId(baseline_id)]


def baseline_contract_payload(
    baseline_id: BaselineId | str,
    *,
    random_state: int = DEFAULT_RANDOM_STATE,
) -> dict[str, object]:
    """Return one deterministic declaration plus fixed factory parameters."""

    resolved = BaselineId(baseline_id)
    spec = get_baseline_spec(resolved)
    parameters = (
        {
            "random_state": random_state,
            "strategy": "prior",
        }
        if resolved == BaselineId.B0_EMPIRICAL_PRIOR
        else {
            **dict(_LOGISTIC_PARAMETERS),
            "random_state": random_state,
        }
    )
    variant = BASELINE_FEATURE_VARIANTS[resolved]
    return {
        "contract_version": BASELINE_CONTRACT_VERSION,
        "baseline_id": spec.baseline_id,
        "family": spec.family,
        "feature_profile": spec.feature_profile,
        "feature_variant": variant.value if variant is not None else None,
        "includes_picks": spec.includes_picks,
        "includes_bans": spec.includes_bans,
        "slot_aware": spec.slot_aware,
        "purpose": spec.purpose,
        "parameters": parameters,
    }


def baseline_fingerprint(
    baseline_id: BaselineId | str,
    *,
    random_state: int = DEFAULT_RANDOM_STATE,
) -> str:
    """Return a stable fingerprint of one baseline and estimator declaration."""

    encoded = json.dumps(
        baseline_contract_payload(
            baseline_id,
            random_state=random_state,
        ),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def create_unfitted_estimator(
    baseline_id: BaselineId | str,
    *,
    random_state: int = DEFAULT_RANDOM_STATE,
) -> BaseEstimator:
    """Create a fresh estimator without fitting or reading any dataset."""

    spec = get_baseline_spec(baseline_id)
    resolved = BaselineId(spec.baseline_id)
    parameters = baseline_contract_payload(
        resolved,
        random_state=random_state,
    )["parameters"]
    if not isinstance(parameters, dict):
        raise TypeError("Baseline parameter contract must be a dictionary.")
    if resolved == BaselineId.B0_EMPIRICAL_PRIOR:
        return DummyClassifier(**parameters)
    return LogisticRegression(**parameters)
