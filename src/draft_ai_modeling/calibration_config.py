"""Strict, credential-free contract for the bounded M4B.3 calibration gate."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import (
    SPLIT_ROLE_CALIBRATION,
    SPLIT_ROLE_LOCKED_TEST,
    SPLIT_ROLE_TRAIN,
    SPLIT_ROLE_TUNING,
    WORKING_CORPUS_ID,
)
from .loader import sha256_file


CONFIG_SCHEMA_VERSION = "draft-ai-calibration-experiment-v1"
EXPERIMENT_ID = "m4b3-frozen-b1-calibration-v1"
FROZEN_CANDIDATE_ID = "b1_full_uniform_c0p01"
FROZEN_CANDIDATE_FINGERPRINT = (
    "cc74f23fbd16e6ff6f5a3e2598cd9d326b78abee860bfceeb569154c0c77837e"
)
CALIBRATION_METHODS = ("raw", "sigmoid", "isotonic")
BASE_FIT_ROLES = frozenset({SPLIT_ROLE_TRAIN, SPLIT_ROLE_TUNING})
PROHIBITED_ROLES = frozenset({SPLIT_ROLE_LOCKED_TEST})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

EXPECTED_ESTIMATOR: dict[str, Any] = {
    "family": "logistic_regression",
    "penalty": "l2",
    "C": 0.01,
    "solver": "liblinear",
    "class_weight": None,
    "max_iter": 2000,
    "random_seed": 42,
}
EXPECTED_CROSS_FIT: dict[str, Any] = {
    "splitter": "StratifiedGroupKFold",
    "folds": 5,
    "group_column": "source_match_id",
    "shuffle": True,
    "random_seed": 42,
}
EXPECTED_ROLE_COUNTS: dict[str, int] = {
    "base_fit_rows": 20_087,
    "base_fit_source_matches": 10_035,
    "calibration_rows": 1_089,
    "calibration_source_matches": 523,
    "calibration_positive_rows": 550,
    "calibration_negative_rows": 539,
    "locked_test_rows": 1_947,
}
EXPECTED_SELECTION_POLICY: dict[str, Any] = {
    "complexity_order": ["raw", "sigmoid", "isotonic"],
    "raw_is_default": True,
    "calibrator_vs_raw": {
        "minimum_log_loss_improvement": 0.002,
        "require_lower_brier_score": True,
        "require_paired_upper_bound_below_zero": [
            "log_loss",
            "brier_score",
        ],
    },
    "isotonic_vs_sigmoid": {
        "minimum_log_loss_improvement": 0.002,
        "require_lower_brier_score": True,
        "require_paired_upper_bound_below_zero": [
            "log_loss",
            "brier_score",
        ],
        "maximum_single_fold_log_loss_regression": 0.005,
    },
    "readiness_reference": {
        "method": "train_tuning_empirical_prior",
        "require_lower_point_estimate": ["log_loss", "brier_score"],
        "require_paired_upper_bound_below_zero": [
            "log_loss",
            "brier_score",
        ],
    },
    "selection_uses_only": ["cross_fitted_2025_q4_predictions"],
}
EXPECTED_SAFETY: dict[str, Any] = {
    "api_dependency": False,
    "acquisition_dependency": False,
    "raw_cache_dependency": False,
    "dynamic_candidate_search": False,
    "base_estimator_refit_after_calibration": False,
    "locked_test_target_use": False,
    "locked_test_transform": False,
    "locked_test_predictions": False,
    "patch_features": False,
    "context_features": False,
    "ban_features": False,
    "slot_features": False,
    "authenticated_api_requests": 0,
}


class CalibrationConfigError(ValueError):
    """Raised when the M4B.3 contract or its immutable pins drift."""


@dataclass(frozen=True, slots=True)
class M4APin:
    """Pinned M4A infrastructure and split artifacts."""

    build_fingerprint: str
    manifest_path: Path
    manifest_sha256: str
    split_manifest_path: Path
    split_manifest_sha256: str


@dataclass(frozen=True, slots=True)
class M4B2Pin:
    """Pinned M4B.2 experiment and candidate-selection evidence."""

    build_fingerprint: str
    config_path: Path
    config_sha256: str
    config_fingerprint: str
    manifest_path: Path
    manifest_sha256: str
    selection_path: Path
    selection_sha256: str


@dataclass(frozen=True, slots=True)
class EstimatorPolicy:
    """Exact frozen base-estimator parameters."""

    family: str
    penalty: str
    regularization_c: float
    solver: str
    class_weight: str | None
    max_iter: int
    random_seed: int


@dataclass(frozen=True, slots=True)
class CalibrationExperimentConfig:
    """Resolved immutable inputs and policy for one M4B.3 run."""

    config_path: Path
    repository_root: Path
    experiment_id: str
    corpus_config_path: Path
    corpus_config_sha256: str
    corpus_id: str
    split_manifest_fingerprint: str
    m4a: M4APin
    m4b2: M4B2Pin
    candidate_id: str
    candidate_fingerprint: str
    baseline_id: str
    feature_variant: str
    history_policy_id: str
    estimator: EstimatorPolicy
    base_fit_roles: frozenset[str]
    calibration_role: str
    prohibited_roles: frozenset[str]
    expected_counts: dict[str, int]
    methods: tuple[str, ...]
    cross_fit: dict[str, Any]
    evaluation: dict[str, Any]
    selection_policy: dict[str, Any]
    bundle: dict[str, Any]
    safety: dict[str, Any]
    fingerprint: str

    def assert_role_allowed(self, role: str, *, purpose: str) -> None:
        """Enforce the one-way Train+Tuning -> Q4 calibration boundary."""

        if role in self.prohibited_roles:
            raise CalibrationConfigError(
                f"{role} is prohibited during M4B.3 {purpose}."
            )
        allowed = (
            self.base_fit_roles
            if purpose == "base_fit"
            else frozenset({self.calibration_role})
        )
        if role not in allowed:
            raise CalibrationConfigError(
                f"{role} is not approved for M4B.3 {purpose}."
            )


def canonical_json(value: object) -> str:
    """Return the deterministic JSON representation used for fingerprints."""

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _repository_root(config_path: Path) -> Path:
    for candidate in (config_path.resolve().parent, *config_path.resolve().parents):
        if (candidate / "src" / "draft_ai_modeling").is_dir():
            return candidate
    raise CalibrationConfigError("Could not discover the repository root.")


def _repository_path(root: Path, value: object, *, label: str) -> Path:
    relative = Path(str(value))
    if relative.is_absolute() or ".." in relative.parts:
        raise CalibrationConfigError(
            f"{label} must be a repository-relative path."
        )
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise CalibrationConfigError(f"{label} escapes the repository.") from error
    return resolved


def _require_sha256(value: object, *, label: str) -> str:
    text = str(value)
    if _SHA256.fullmatch(text) is None:
        raise CalibrationConfigError(f"{label} is not a valid SHA-256 value.")
    return text


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CalibrationConfigError(f"Cannot read {label}.") from error
    if not isinstance(payload, dict):
        raise CalibrationConfigError(f"{label} must be a JSON object.")
    return payload


def _parse_m4a(payload: dict[str, Any], *, root: Path) -> M4APin:
    return M4APin(
        build_fingerprint=_require_sha256(
            payload["build_fingerprint"],
            label="M4A build fingerprint",
        ),
        manifest_path=_repository_path(
            root,
            payload["manifest_path"],
            label="M4A manifest path",
        ),
        manifest_sha256=_require_sha256(
            payload["manifest_sha256"],
            label="M4A manifest SHA-256",
        ),
        split_manifest_path=_repository_path(
            root,
            payload["split_manifest_path"],
            label="M4A split-manifest path",
        ),
        split_manifest_sha256=_require_sha256(
            payload["split_manifest_sha256"],
            label="M4A split-manifest SHA-256",
        ),
    )


def _parse_m4b2(payload: dict[str, Any], *, root: Path) -> M4B2Pin:
    return M4B2Pin(
        build_fingerprint=_require_sha256(
            payload["build_fingerprint"],
            label="M4B.2 build fingerprint",
        ),
        config_path=_repository_path(
            root,
            payload["config_path"],
            label="M4B.2 config path",
        ),
        config_sha256=_require_sha256(
            payload["config_sha256"],
            label="M4B.2 config SHA-256",
        ),
        config_fingerprint=_require_sha256(
            payload["config_fingerprint"],
            label="M4B.2 config fingerprint",
        ),
        manifest_path=_repository_path(
            root,
            payload["manifest_path"],
            label="M4B.2 manifest path",
        ),
        manifest_sha256=_require_sha256(
            payload["manifest_sha256"],
            label="M4B.2 manifest SHA-256",
        ),
        selection_path=_repository_path(
            root,
            payload["selection_path"],
            label="M4B.2 selection path",
        ),
        selection_sha256=_require_sha256(
            payload["selection_sha256"],
            label="M4B.2 selection SHA-256",
        ),
    )


def _verify_file(path: Path, expected_sha256: str, *, label: str) -> None:
    if not path.is_file():
        raise CalibrationConfigError(f"Missing pinned {label}: {path}")
    if sha256_file(path) != expected_sha256:
        raise CalibrationConfigError(f"Pinned {label} changed.")


def _verify_local_artifacts(config: CalibrationExperimentConfig) -> None:
    _verify_file(
        config.corpus_config_path,
        config.corpus_config_sha256,
        label="corpus config",
    )
    for path, digest, label in (
        (
            config.m4a.manifest_path,
            config.m4a.manifest_sha256,
            "M4A manifest",
        ),
        (
            config.m4a.split_manifest_path,
            config.m4a.split_manifest_sha256,
            "M4A split manifest",
        ),
        (
            config.m4b2.config_path,
            config.m4b2.config_sha256,
            "M4B.2 config",
        ),
        (
            config.m4b2.manifest_path,
            config.m4b2.manifest_sha256,
            "M4B.2 manifest",
        ),
        (
            config.m4b2.selection_path,
            config.m4b2.selection_sha256,
            "M4B.2 selection",
        ),
    ):
        _verify_file(path, digest, label=label)

    manifest = _read_json(config.m4b2.manifest_path, label="M4B.2 manifest")
    selection = _read_json(config.m4b2.selection_path, label="M4B.2 selection")
    if (
        manifest.get("build_fingerprint") != config.m4b2.build_fingerprint
        or manifest.get("experiment_config_fingerprint")
        != config.m4b2.config_fingerprint
        or manifest.get("result", {}).get("selected_development_candidate")
        != config.candidate_id
        or manifest.get("result", {}).get("calibration_prediction_rows") != 0
        or manifest.get("result", {}).get("locked_test_prediction_rows") != 0
        or selection.get("selected_candidate_id") != config.candidate_id
    ):
        raise CalibrationConfigError(
            "Pinned M4B.2 selection lineage changed."
        )
    candidates = {
        item.get("candidate_id"): item
        for item in manifest.get("candidates", [])
        if isinstance(item, dict)
    }
    selected = candidates.get(config.candidate_id, {})
    if selected.get("fingerprint") != config.candidate_fingerprint:
        raise CalibrationConfigError(
            "The frozen candidate fingerprint changed."
        )


def _validate_policy(config: CalibrationExperimentConfig) -> None:
    if config.experiment_id != EXPERIMENT_ID:
        raise CalibrationConfigError("Unexpected M4B.3 experiment ID.")
    if config.corpus_id != WORKING_CORPUS_ID:
        raise CalibrationConfigError("Unexpected M4B.3 corpus ID.")
    if (
        config.candidate_id != FROZEN_CANDIDATE_ID
        or config.candidate_fingerprint != FROZEN_CANDIDATE_FINGERPRINT
        or config.baseline_id != "B1"
        or config.feature_variant != "b1-pick-presence"
        or config.history_policy_id != "full_uniform"
    ):
        raise CalibrationConfigError("The frozen M4B.2 candidate changed.")
    observed_estimator = {
        "family": config.estimator.family,
        "penalty": config.estimator.penalty,
        "C": config.estimator.regularization_c,
        "solver": config.estimator.solver,
        "class_weight": config.estimator.class_weight,
        "max_iter": config.estimator.max_iter,
        "random_seed": config.estimator.random_seed,
    }
    if observed_estimator != EXPECTED_ESTIMATOR:
        raise CalibrationConfigError("The frozen estimator contract changed.")
    if (
        config.base_fit_roles != BASE_FIT_ROLES
        or config.calibration_role != SPLIT_ROLE_CALIBRATION
        or config.prohibited_roles != PROHIBITED_ROLES
        or config.expected_counts != EXPECTED_ROLE_COUNTS
    ):
        raise CalibrationConfigError("The M4B.3 role contract changed.")
    if config.methods != CALIBRATION_METHODS:
        raise CalibrationConfigError(
            "M4B.3 must compare exactly raw, sigmoid, and isotonic."
        )
    if config.cross_fit != EXPECTED_CROSS_FIT:
        raise CalibrationConfigError("The calibration cross-fit policy changed.")
    bootstrap = config.evaluation.get("paired_group_bootstrap", {})
    if (
        config.evaluation.get("primary_metric") != "log_loss"
        or config.evaluation.get("confirmation_metric") != "brier_score"
        or config.evaluation.get("reliability_bins") != 10
        or bootstrap
        != {
            "group_column": "source_match_id",
            "replicates": 1000,
            "confidence_level": 0.95,
            "random_seed": 42,
        }
    ):
        raise CalibrationConfigError("The M4B.3 evaluation policy changed.")
    if config.selection_policy != EXPECTED_SELECTION_POLICY:
        raise CalibrationConfigError("The calibration selection policy changed.")
    if config.safety != EXPECTED_SAFETY:
        raise CalibrationConfigError("The M4B.3 safety policy changed.")
    if config.bundle != {
        "serialization": "joblib",
        "trusted_local_artifacts_only": True,
        "hash_before_load": True,
        "components": [
            "feature_transformer",
            "base_estimator",
            "selected_calibrator",
        ],
    }:
        raise CalibrationConfigError("The M4B.3 bundle policy changed.")


def load_calibration_experiment_config(
    config_path: Path,
    *,
    repository_root: Path | None = None,
    verify_local_artifacts: bool = True,
) -> CalibrationExperimentConfig:
    """Load, validate, fingerprint, and optionally verify the M4B.3 contract."""

    resolved_config_path = config_path.resolve()
    root = (
        repository_root.resolve()
        if repository_root is not None
        else _repository_root(resolved_config_path)
    )
    payload = _read_json(resolved_config_path, label="M4B.3 config")
    if payload.get("schema_version") != CONFIG_SCHEMA_VERSION:
        raise CalibrationConfigError("Unexpected M4B.3 config schema.")

    source = payload["source"]
    candidate = payload["frozen_candidate"]
    estimator = candidate["estimator"]
    roles = payload["roles"]
    config = CalibrationExperimentConfig(
        config_path=resolved_config_path,
        repository_root=root,
        experiment_id=str(payload["experiment_id"]),
        corpus_config_path=_repository_path(
            root,
            source["corpus_config_path"],
            label="corpus config path",
        ),
        corpus_config_sha256=_require_sha256(
            source["corpus_config_sha256"],
            label="corpus config SHA-256",
        ),
        corpus_id=str(source["corpus_id"]),
        split_manifest_fingerprint=_require_sha256(
            source["split_manifest_fingerprint"],
            label="split-manifest fingerprint",
        ),
        m4a=_parse_m4a(source["m4a"], root=root),
        m4b2=_parse_m4b2(source["m4b2"], root=root),
        candidate_id=str(candidate["candidate_id"]),
        candidate_fingerprint=_require_sha256(
            candidate["candidate_fingerprint"],
            label="candidate fingerprint",
        ),
        baseline_id=str(candidate["baseline_id"]),
        feature_variant=str(candidate["feature_variant"]),
        history_policy_id=str(candidate["history_policy_id"]),
        estimator=EstimatorPolicy(
            family=str(estimator["family"]),
            penalty=str(estimator["penalty"]),
            regularization_c=float(estimator["C"]),
            solver=str(estimator["solver"]),
            class_weight=estimator["class_weight"],
            max_iter=int(estimator["max_iter"]),
            random_seed=int(estimator["random_seed"]),
        ),
        base_fit_roles=frozenset(str(value) for value in roles["base_fit"]),
        calibration_role=str(roles["calibration"]),
        prohibited_roles=frozenset(
            str(value) for value in roles["prohibited"]
        ),
        expected_counts={
            str(key): int(value)
            for key, value in roles["expected"].items()
        },
        methods=tuple(str(value) for value in payload["methods"]),
        cross_fit=dict(payload["cross_fit"]),
        evaluation=dict(payload["evaluation"]),
        selection_policy=dict(payload["selection_policy"]),
        bundle=dict(payload["bundle"]),
        safety=dict(payload["safety"]),
        fingerprint=hashlib.sha256(
            canonical_json(payload).encode("utf-8")
        ).hexdigest(),
    )
    _validate_policy(config)
    if verify_local_artifacts:
        _verify_local_artifacts(config)
    return config


__all__ = [
    "CALIBRATION_METHODS",
    "CalibrationConfigError",
    "CalibrationExperimentConfig",
    "load_calibration_experiment_config",
]
