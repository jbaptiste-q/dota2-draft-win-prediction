"""Strict, credential-free contract for the bounded M4B.4 interaction gate."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .contracts import (
    SPLIT_ROLE_CALIBRATION,
    SPLIT_ROLE_LOCKED_TEST,
    SPLIT_ROLE_TRAIN,
    SPLIT_ROLE_TUNING,
    WORKING_CORPUS_ID,
)
from .experiment_config import EvaluationPolicy, RollingOriginFold
from .loader import sha256_file


CONFIG_SCHEMA_VERSION = "draft-ai-interaction-experiment-v1"
EXPERIMENT_ID = "m4b4-pick-interaction-recovery-gate-v1"
FROZEN_B1_CANDIDATE_ID = "b1_full_uniform_c0p01"
FROZEN_B1_CANDIDATE_FINGERPRINT = (
    "cc74f23fbd16e6ff6f5a3e2598cd9d326b78abee860bfceeb569154c0c77837e"
)
SELECTION_FOLD_IDS = ("2025-Q1", "2025-Q2", "2025-Q3")
FIT_ROLES = frozenset({SPLIT_ROLE_TRAIN})
DEVELOPMENT_EVALUATION_ROLES = frozenset(
    {SPLIT_ROLE_TRAIN, SPLIT_ROLE_TUNING}
)
PROHIBITED_ROLES = frozenset(
    {SPLIT_ROLE_CALIBRATION, SPLIT_ROLE_LOCKED_TEST}
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

EXPECTED_CANDIDATES = (
    ("c1_pick_interactions_c0p001", 0.001),
    ("c1_pick_interactions_c0p01", 0.01),
)
EXPECTED_REPRESENTATION: dict[str, Any] = {
    "baseline_id": "C1",
    "feature_variant": "c1-pick-interactions",
    "extends": "b1-pick-presence",
    "side_relative": True,
    "main_effects": True,
    "includes_bans": False,
    "slot_aware": False,
    "includes_context": False,
}
EXPECTED_HISTORY_POLICY: dict[str, Any] = {
    "history_policy_id": "full_uniform",
    "training_rows": "all_strictly_past_rows",
    "sample_weight": "uniform",
    "anchor": "train_end_utc",
}
EXPECTED_TRANSFORMER: dict[str, Any] = {
    "class": "PickInteractionTransformer",
    "base_feature_variant": "b1-pick-presence",
    "minimum_training_row_support": 50,
    "synergy": {
        "pair_order": "unordered",
        "support_count_basis": "combined_radiant_and_dire_training_rows",
        "feature_groups": ["radiant", "dire"],
    },
    "counter": {
        "pair_order": "radiant_hero_then_dire_hero",
        "support_count_basis": "exact_orientation_training_rows",
        "feature_group": "radiant_vs_dire",
    },
    "unsupported_interactions": "ignore_and_audit",
}
EXPECTED_ESTIMATOR: dict[str, Any] = {
    "family": "logistic_regression",
    "penalty": "l2",
    "solver": "liblinear",
    "class_weight": None,
    "max_iter": 2000,
    "random_seed": 42,
}
EXPECTED_SELECTION_POLICY: dict[str, Any] = {
    "selection_fold_ids": list(SELECTION_FOLD_IDS),
    "references": ["frozen_b1", "canonical_b0"],
    "recent_per_fold": {
        "versus": ["frozen_b1", "canonical_b0"],
        "require_strict_lower": ["log_loss", "brier_score"],
        "required_folds": "all",
    },
    "pooled_recent": {
        "minimum_log_loss_improvement_vs_frozen_b1": 0.002,
        "require_lower_brier_score_vs_frozen_b1": True,
        "require_strict_lower_vs_canonical_b0": [
            "log_loss",
            "brier_score",
        ],
    },
    "paired_group_bootstrap": {
        "reference": "frozen_b1",
        "metrics": ["log_loss", "brier_score"],
        "confidence_level": 0.95,
        "replicates": 1000,
        "group_column": "source_match_id",
        "require_upper_bound_below": 0.0,
        "random_seed": 42,
    },
    "seven_fold": {
        "mean_log_loss_no_worse_than_frozen_b1": True,
        "maximum_single_fold_log_loss_regression": 0.01,
    },
    "ranking": {
        "metric": "pooled_recent_log_loss",
        "direction": "minimize",
        "practical_log_loss_tie": 0.002,
        "C_preference": [0.001, 0.01],
    },
}
EXPECTED_SAFETY: dict[str, Any] = {
    "api_dependency": False,
    "acquisition_dependency": False,
    "raw_cache_dependency": False,
    "authenticated_api_requests": 0,
    "pre_registered_candidates_only": True,
    "open_ended_hyperparameter_search": False,
    "ban_features": False,
    "slot_features": False,
    "context_features": False,
    "patch_features": False,
    "calibration_fit": False,
    "calibration_predictions": False,
    "locked_test_target_use": False,
    "locked_test_transform": False,
    "locked_test_predictions": False,
    "model_serialization": False,
}
EXPECTED_METRICS = (
    "log_loss",
    "brier_score",
    "roc_auc",
    "accuracy",
    "balanced_accuracy",
    "calibration_in_the_large",
    "calibration_slope",
    "expected_calibration_error",
)


class InteractionConfigError(ValueError):
    """Raised when the M4B.4 contract or immutable lineage pins drift."""


@dataclass(frozen=True, slots=True)
class M4APin:
    """Pinned M4A corpus and split evidence."""

    build_fingerprint: str
    manifest_path: Path
    manifest_sha256: str
    split_manifest_path: Path
    split_manifest_sha256: str


@dataclass(frozen=True, slots=True)
class M4B2Pin:
    """Pinned development predictions for the frozen B1/B0 references."""

    build_fingerprint: str
    config_path: Path
    config_sha256: str
    config_fingerprint: str
    manifest_path: Path
    manifest_sha256: str
    predictions_path: Path
    predictions_sha256: str
    selection_path: Path
    selection_sha256: str
    frozen_candidate_id: str
    frozen_candidate_fingerprint: str


@dataclass(frozen=True, slots=True)
class M4B3Pin:
    """Pinned negative Q4 result; no Q4 prediction artifact is exposed."""

    build_fingerprint: str
    manifest_path: Path
    manifest_sha256: str
    readiness_path: Path
    readiness_sha256: str
    selection_path: Path
    selection_sha256: str


@dataclass(frozen=True, slots=True)
class InteractionCandidate:
    """One of the two pre-registered interaction-model strengths."""

    candidate_id: str
    regularization_c: float


@dataclass(frozen=True, slots=True)
class EstimatorPolicy:
    """Fixed estimator settings shared by both candidates."""

    family: str
    penalty: str
    solver: str
    class_weight: str | None
    max_iter: int
    random_seed: int


@dataclass(frozen=True, slots=True)
class InteractionExperimentConfig:
    """Resolved, fingerprinted, development-only M4B.4 experiment."""

    config_path: Path
    repository_root: Path
    experiment_id: str
    corpus_config_path: Path
    corpus_config_sha256: str
    corpus_id: str
    split_manifest_fingerprint: str
    m4a: M4APin
    m4b2: M4B2Pin
    m4b3: M4B3Pin
    representation: dict[str, Any]
    history_policy_id: str
    transformer: dict[str, Any]
    candidates: tuple[InteractionCandidate, ...]
    estimator: EstimatorPolicy
    fit_roles: frozenset[str]
    development_evaluation_roles: frozenset[str]
    prohibited_roles: frozenset[str]
    rolling_origin_folds: tuple[RollingOriginFold, ...]
    evaluation: EvaluationPolicy
    selection_policy: dict[str, Any]
    safety: dict[str, Any]
    fingerprint: str

    def assert_role_allowed(self, role: str, *, purpose: str) -> None:
        """Reject Q4 calibration and locked-test access before any work."""

        if role in self.prohibited_roles:
            raise InteractionConfigError(
                f"{role} is prohibited during M4B.4 {purpose}."
            )
        allowed = (
            self.fit_roles
            if purpose == "fit"
            else self.development_evaluation_roles
        )
        if role not in allowed:
            raise InteractionConfigError(
                f"{role} is not approved for M4B.4 {purpose}."
            )


def canonical_json(value: object) -> str:
    """Return the deterministic JSON representation used for fingerprints."""

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _expect_keys(
    payload: dict[str, Any],
    expected: set[str],
    *,
    label: str,
) -> None:
    observed = set(payload)
    if observed != expected:
        missing = sorted(expected - observed)
        extra = sorted(observed - expected)
        raise InteractionConfigError(
            f"Malformed {label} shape; missing={missing}, extra={extra}."
        )


def _repository_root(path: Path) -> Path:
    for candidate in (path.resolve().parent, *path.resolve().parents):
        if (candidate / "src" / "draft_ai_modeling").is_dir():
            return candidate
    raise InteractionConfigError("Could not discover the repository root.")


def _repository_path(root: Path, value: object, *, label: str) -> Path:
    relative = Path(str(value))
    if relative.is_absolute() or ".." in relative.parts:
        raise InteractionConfigError(
            f"{label} must be a repository-relative path."
        )
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise InteractionConfigError(f"{label} escapes the repository.") from error
    return resolved


def _require_sha256(value: object, *, label: str) -> str:
    text = str(value)
    if _SHA256.fullmatch(text) is None:
        raise InteractionConfigError(f"{label} is not a lowercase SHA-256.")
    return text


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InteractionConfigError(f"Cannot read {label}.") from error
    if not isinstance(payload, dict):
        raise InteractionConfigError(f"{label} must be a JSON object.")
    return payload


def _utc(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise InteractionConfigError("Experiment timestamps require an offset.")
    return parsed.astimezone(UTC)


def _parse_folds(values: list[dict[str, Any]]) -> tuple[RollingOriginFold, ...]:
    fold_keys = {
        "fold_id",
        "train_start_utc",
        "train_end_utc",
        "evaluation_start_utc",
        "evaluation_end_utc",
    }
    for index, value in enumerate(values):
        _expect_keys(value, fold_keys, label=f"rolling fold {index}")
    folds = tuple(
        RollingOriginFold(
            fold_id=str(value["fold_id"]),
            train_start_utc=_utc(value["train_start_utc"]),
            train_end_utc=_utc(value["train_end_utc"]),
            evaluation_start_utc=_utc(value["evaluation_start_utc"]),
            evaluation_end_utc=_utc(value["evaluation_end_utc"]),
        )
        for value in values
    )
    expected_ids = (
        "2024-Q1",
        "2024-Q2",
        "2024-Q3",
        "2024-Q4",
        "2025-Q1",
        "2025-Q2",
        "2025-Q3",
    )
    if tuple(fold.fold_id for fold in folds) != expected_ids:
        raise InteractionConfigError(
            "M4B.4 requires the exact seven M4B.2 folds."
        )
    expected_evaluation_start = datetime(2024, 1, 1, tzinfo=UTC)
    for fold in folds:
        if (
            fold.train_start_utc != datetime(2022, 1, 1, tzinfo=UTC)
            or fold.train_end_utc != expected_evaluation_start
            or fold.evaluation_start_utc != expected_evaluation_start
            or fold.evaluation_start_utc >= fold.evaluation_end_utc
        ):
            raise InteractionConfigError(
                f"{fold.fold_id} is not an approved past-only fold."
            )
        expected_evaluation_start = fold.evaluation_end_utc
    if expected_evaluation_start != datetime(2025, 10, 1, tzinfo=UTC):
        raise InteractionConfigError("The final development boundary changed.")
    return folds


def _parse_m4a(payload: dict[str, Any], *, root: Path) -> M4APin:
    _expect_keys(
        payload,
        {
            "build_fingerprint",
            "manifest_path",
            "manifest_sha256",
            "split_manifest_path",
            "split_manifest_sha256",
        },
        label="M4A pin",
    )
    return M4APin(
        build_fingerprint=_require_sha256(
            payload["build_fingerprint"], label="M4A build fingerprint"
        ),
        manifest_path=_repository_path(
            root, payload["manifest_path"], label="M4A manifest path"
        ),
        manifest_sha256=_require_sha256(
            payload["manifest_sha256"], label="M4A manifest SHA-256"
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
    _expect_keys(
        payload,
        {
            "build_fingerprint",
            "config_path",
            "config_sha256",
            "config_fingerprint",
            "manifest_path",
            "manifest_sha256",
            "predictions_path",
            "predictions_sha256",
            "selection_path",
            "selection_sha256",
            "frozen_candidate_id",
            "frozen_candidate_fingerprint",
        },
        label="M4B.2 pin",
    )
    return M4B2Pin(
        build_fingerprint=_require_sha256(
            payload["build_fingerprint"], label="M4B.2 build fingerprint"
        ),
        config_path=_repository_path(
            root, payload["config_path"], label="M4B.2 config path"
        ),
        config_sha256=_require_sha256(
            payload["config_sha256"], label="M4B.2 config SHA-256"
        ),
        config_fingerprint=_require_sha256(
            payload["config_fingerprint"], label="M4B.2 config fingerprint"
        ),
        manifest_path=_repository_path(
            root, payload["manifest_path"], label="M4B.2 manifest path"
        ),
        manifest_sha256=_require_sha256(
            payload["manifest_sha256"], label="M4B.2 manifest SHA-256"
        ),
        predictions_path=_repository_path(
            root, payload["predictions_path"], label="M4B.2 predictions path"
        ),
        predictions_sha256=_require_sha256(
            payload["predictions_sha256"], label="M4B.2 predictions SHA-256"
        ),
        selection_path=_repository_path(
            root, payload["selection_path"], label="M4B.2 selection path"
        ),
        selection_sha256=_require_sha256(
            payload["selection_sha256"], label="M4B.2 selection SHA-256"
        ),
        frozen_candidate_id=str(payload["frozen_candidate_id"]),
        frozen_candidate_fingerprint=_require_sha256(
            payload["frozen_candidate_fingerprint"],
            label="frozen B1 candidate fingerprint",
        ),
    )


def _parse_m4b3(payload: dict[str, Any], *, root: Path) -> M4B3Pin:
    _expect_keys(
        payload,
        {
            "build_fingerprint",
            "manifest_path",
            "manifest_sha256",
            "readiness_path",
            "readiness_sha256",
            "selection_path",
            "selection_sha256",
        },
        label="M4B.3 pin",
    )
    return M4B3Pin(
        build_fingerprint=_require_sha256(
            payload["build_fingerprint"], label="M4B.3 build fingerprint"
        ),
        manifest_path=_repository_path(
            root, payload["manifest_path"], label="M4B.3 manifest path"
        ),
        manifest_sha256=_require_sha256(
            payload["manifest_sha256"], label="M4B.3 manifest SHA-256"
        ),
        readiness_path=_repository_path(
            root, payload["readiness_path"], label="M4B.3 readiness path"
        ),
        readiness_sha256=_require_sha256(
            payload["readiness_sha256"], label="M4B.3 readiness SHA-256"
        ),
        selection_path=_repository_path(
            root, payload["selection_path"], label="M4B.3 selection path"
        ),
        selection_sha256=_require_sha256(
            payload["selection_sha256"], label="M4B.3 selection SHA-256"
        ),
    )


def _verify_file(path: Path, expected_sha256: str, *, label: str) -> None:
    if not path.is_file():
        raise InteractionConfigError(f"Missing pinned {label}: {path}")
    if sha256_file(path) != expected_sha256:
        raise InteractionConfigError(f"Pinned {label} changed.")


def _verify_local_artifacts(config: InteractionExperimentConfig) -> None:
    for path, digest, label in (
        (
            config.corpus_config_path,
            config.corpus_config_sha256,
            "corpus config",
        ),
        (config.m4a.manifest_path, config.m4a.manifest_sha256, "M4A manifest"),
        (
            config.m4a.split_manifest_path,
            config.m4a.split_manifest_sha256,
            "M4A split manifest",
        ),
        (config.m4b2.config_path, config.m4b2.config_sha256, "M4B.2 config"),
        (
            config.m4b2.manifest_path,
            config.m4b2.manifest_sha256,
            "M4B.2 manifest",
        ),
        (
            config.m4b2.predictions_path,
            config.m4b2.predictions_sha256,
            "M4B.2 development predictions",
        ),
        (
            config.m4b2.selection_path,
            config.m4b2.selection_sha256,
            "M4B.2 selection",
        ),
        (
            config.m4b3.manifest_path,
            config.m4b3.manifest_sha256,
            "M4B.3 manifest",
        ),
        (
            config.m4b3.readiness_path,
            config.m4b3.readiness_sha256,
            "M4B.3 readiness",
        ),
        (
            config.m4b3.selection_path,
            config.m4b3.selection_sha256,
            "M4B.3 selection",
        ),
    ):
        _verify_file(path, digest, label=label)

    m4a_manifest = _read_json(config.m4a.manifest_path, label="M4A manifest")
    m4a_source = m4a_manifest.get("source", {})
    m4a_split = m4a_manifest.get("split", {})
    if (
        m4a_manifest.get("build_fingerprint") != config.m4a.build_fingerprint
        or not isinstance(m4a_source, dict)
        or m4a_source.get("corpus_id") != config.corpus_id
        or m4a_source.get("config_sha256") != config.corpus_config_sha256
        or not isinstance(m4a_split, dict)
        or m4a_split.get("split_manifest_fingerprint")
        != config.split_manifest_fingerprint
    ):
        raise InteractionConfigError("Pinned M4A lineage changed.")

    m4b2_manifest = _read_json(
        config.m4b2.manifest_path, label="M4B.2 manifest"
    )
    m4b2_selection = _read_json(
        config.m4b2.selection_path, label="M4B.2 selection"
    )
    m4b2_result = m4b2_manifest.get("result", {})
    m4b2_candidates = {
        item.get("candidate_id"): item
        for item in m4b2_manifest.get("candidates", [])
        if isinstance(item, dict)
    }
    m4b2_artifacts = m4b2_manifest.get("artifacts", {})
    if (
        m4b2_manifest.get("build_fingerprint") != config.m4b2.build_fingerprint
        or m4b2_manifest.get("config_sha256") != config.m4b2.config_sha256
        or m4b2_manifest.get("experiment_config_fingerprint")
        != config.m4b2.config_fingerprint
        or not isinstance(m4b2_result, dict)
        or m4b2_result.get("selected_development_candidate")
        != config.m4b2.frozen_candidate_id
        or m4b2_result.get("calibration_prediction_rows") != 0
        or m4b2_result.get("locked_test_prediction_rows") != 0
        or m4b2_selection.get("selected_candidate_id")
        != config.m4b2.frozen_candidate_id
        or m4b2_candidates.get(config.m4b2.frozen_candidate_id, {}).get(
            "fingerprint"
        )
        != config.m4b2.frozen_candidate_fingerprint
        or not isinstance(m4b2_artifacts, dict)
        or m4b2_artifacts.get("predictions", {}).get("sha256")
        != config.m4b2.predictions_sha256
        or m4b2_artifacts.get("selection", {}).get("sha256")
        != config.m4b2.selection_sha256
    ):
        raise InteractionConfigError("Pinned M4B.2 reference lineage changed.")

    # Deliberately verify only summaries of the negative Q4 decision. The
    # calibration-prediction artifact is neither pinned nor opened by M4B.4.
    m4b3_manifest = _read_json(
        config.m4b3.manifest_path, label="M4B.3 manifest"
    )
    m4b3_readiness = _read_json(
        config.m4b3.readiness_path, label="M4B.3 readiness"
    )
    m4b3_selection = _read_json(
        config.m4b3.selection_path, label="M4B.3 selection"
    )
    m4b3_result = m4b3_manifest.get("result", {})
    m4b3_artifacts = m4b3_manifest.get("artifacts", {})
    if (
        m4b3_manifest.get("build_fingerprint") != config.m4b3.build_fingerprint
        or not isinstance(m4b3_result, dict)
        or m4b3_result.get("selected_calibration_method") != "raw"
        or m4b3_result.get("calibration_readiness_gate_passed") is not False
        or m4b3_result.get("locked_test_prediction_rows") != 0
        or m4b3_result.get("locked_test_target_rows_used_for_modeling") != 0
        or m4b3_result.get("locked_test_transform_rows") != 0
        or m4b3_readiness.get("passed") is not False
        or m4b3_selection.get("selected_method") != "raw"
        or not isinstance(m4b3_artifacts, dict)
        or m4b3_artifacts.get("readiness", {}).get("sha256")
        != config.m4b3.readiness_sha256
        or m4b3_artifacts.get("selection", {}).get("sha256")
        != config.m4b3.selection_sha256
    ):
        raise InteractionConfigError("Pinned M4B.3 negative result changed.")


def _validate_policy(config: InteractionExperimentConfig) -> None:
    if (
        config.experiment_id != EXPERIMENT_ID
        or config.corpus_id != WORKING_CORPUS_ID
    ):
        raise InteractionConfigError("The approved M4B.4 identity changed.")
    if config.representation != EXPECTED_REPRESENTATION:
        raise InteractionConfigError(
            "The approved interaction representation changed."
        )
    if config.history_policy_id != "full_uniform":
        raise InteractionConfigError("The full-uniform history policy changed.")
    if config.transformer != EXPECTED_TRANSFORMER:
        raise InteractionConfigError(
            "The approved interaction transformer contract changed."
        )
    observed_candidates = tuple(
        (candidate.candidate_id, candidate.regularization_c)
        for candidate in config.candidates
    )
    if observed_candidates != EXPECTED_CANDIDATES:
        raise InteractionConfigError(
            "M4B.4 requires exactly the two pre-registered candidates."
        )
    if config.estimator != EstimatorPolicy(
        family="logistic_regression",
        penalty="l2",
        solver="liblinear",
        class_weight=None,
        max_iter=2000,
        random_seed=42,
    ):
        raise InteractionConfigError("The approved estimator policy changed.")
    if (
        config.fit_roles != FIT_ROLES
        or config.development_evaluation_roles
        != DEVELOPMENT_EVALUATION_ROLES
        or config.prohibited_roles != PROHIBITED_ROLES
    ):
        raise InteractionConfigError("The development-only role policy changed.")
    if (
        config.evaluation.metrics != EXPECTED_METRICS
        or config.evaluation.primary_metric != "log_loss"
        or config.evaluation.reliability_bins != 10
        or config.evaluation.bootstrap_replicates != 1000
        or config.evaluation.bootstrap_confidence_level != 0.95
        or config.evaluation.bootstrap_group_column != "source_match_id"
        or config.evaluation.random_seed != 42
        or config.evaluation.coefficient_top_k != 20
    ):
        raise InteractionConfigError("The approved evaluation policy changed.")
    if config.selection_policy != EXPECTED_SELECTION_POLICY:
        raise InteractionConfigError("The interaction selection policy changed.")
    if config.safety != EXPECTED_SAFETY:
        raise InteractionConfigError("The M4B.4 safety policy changed.")
    if (
        config.m4b2.frozen_candidate_id != FROZEN_B1_CANDIDATE_ID
        or config.m4b2.frozen_candidate_fingerprint
        != FROZEN_B1_CANDIDATE_FINGERPRINT
    ):
        raise InteractionConfigError("The frozen B1 reference changed.")


def load_interaction_experiment_config(
    config_path: Path,
    *,
    repository_root: Path | None = None,
    verify_local_artifacts: bool = True,
) -> InteractionExperimentConfig:
    """Load, validate, fingerprint, and optionally verify M4B.4."""

    path = config_path.resolve()
    root = (
        repository_root.resolve()
        if repository_root is not None
        else _repository_root(path)
    )
    payload = _read_json(path, label="M4B.4 config")
    try:
        _expect_keys(
            payload,
            {
                "config_schema_version",
                "experiment_id",
                "source",
                "representation",
                "history_policy",
                "transformer",
                "candidates",
                "estimator",
                "roles",
                "rolling_origin_folds",
                "evaluation",
                "selection_policy",
                "safety",
            },
            label="M4B.4 config",
        )
        if payload["config_schema_version"] != CONFIG_SCHEMA_VERSION:
            raise InteractionConfigError("Unexpected M4B.4 config schema.")

        source = dict(payload["source"])
        _expect_keys(
            source,
            {
                "corpus_config_path",
                "corpus_config_sha256",
                "corpus_id",
                "split_manifest_fingerprint",
                "m4a",
                "m4b2",
                "m4b3",
            },
            label="M4B.4 source",
        )
        representation = dict(payload["representation"])
        _expect_keys(
            representation, set(EXPECTED_REPRESENTATION), label="representation"
        )
        history = dict(payload["history_policy"])
        _expect_keys(
            history, set(EXPECTED_HISTORY_POLICY), label="history policy"
        )
        if history != EXPECTED_HISTORY_POLICY:
            raise InteractionConfigError(
                "The full-uniform history policy changed."
            )
        transformer = dict(payload["transformer"])
        _expect_keys(
            transformer, set(EXPECTED_TRANSFORMER), label="transformer"
        )
        _expect_keys(
            dict(transformer["synergy"]),
            set(EXPECTED_TRANSFORMER["synergy"]),
            label="synergy transformer",
        )
        _expect_keys(
            dict(transformer["counter"]),
            set(EXPECTED_TRANSFORMER["counter"]),
            label="counter transformer",
        )
        candidate_values = list(payload["candidates"])
        for index, value in enumerate(candidate_values):
            _expect_keys(
                dict(value), {"candidate_id", "C"}, label=f"candidate {index}"
            )
        estimator_payload = dict(payload["estimator"])
        _expect_keys(
            estimator_payload, set(EXPECTED_ESTIMATOR), label="estimator"
        )
        roles = dict(payload["roles"])
        _expect_keys(
            roles,
            {"fit", "development_evaluation", "prohibited"},
            label="roles",
        )
        evaluation_payload = dict(payload["evaluation"])
        _expect_keys(
            evaluation_payload,
            {
                "metrics",
                "reliability_bins",
                "bootstrap_replicates",
                "bootstrap_confidence_level",
                "bootstrap_group_column",
                "random_seed",
                "coefficient_top_k",
            },
            label="evaluation",
        )
        selection = dict(payload["selection_policy"])
        _expect_keys(
            selection, set(EXPECTED_SELECTION_POLICY), label="selection policy"
        )
        for key in (
            "recent_per_fold",
            "pooled_recent",
            "paired_group_bootstrap",
            "seven_fold",
            "ranking",
        ):
            _expect_keys(
                dict(selection[key]),
                set(EXPECTED_SELECTION_POLICY[key]),
                label=f"selection policy {key}",
            )
        safety = dict(payload["safety"])
        _expect_keys(safety, set(EXPECTED_SAFETY), label="safety")

        config = InteractionExperimentConfig(
            config_path=path,
            repository_root=root,
            experiment_id=str(payload["experiment_id"]),
            corpus_config_path=_repository_path(
                root, source["corpus_config_path"], label="corpus config path"
            ),
            corpus_config_sha256=_require_sha256(
                source["corpus_config_sha256"], label="corpus config SHA-256"
            ),
            corpus_id=str(source["corpus_id"]),
            split_manifest_fingerprint=_require_sha256(
                source["split_manifest_fingerprint"],
                label="split-manifest fingerprint",
            ),
            m4a=_parse_m4a(dict(source["m4a"]), root=root),
            m4b2=_parse_m4b2(dict(source["m4b2"]), root=root),
            m4b3=_parse_m4b3(dict(source["m4b3"]), root=root),
            representation=representation,
            history_policy_id=str(history["history_policy_id"]),
            transformer=transformer,
            candidates=tuple(
                InteractionCandidate(
                    candidate_id=str(value["candidate_id"]),
                    regularization_c=float(value["C"]),
                )
                for value in candidate_values
            ),
            estimator=EstimatorPolicy(
                family=str(estimator_payload["family"]),
                penalty=str(estimator_payload["penalty"]),
                solver=str(estimator_payload["solver"]),
                class_weight=estimator_payload["class_weight"],
                max_iter=int(estimator_payload["max_iter"]),
                random_seed=int(estimator_payload["random_seed"]),
            ),
            fit_roles=frozenset(str(value) for value in roles["fit"]),
            development_evaluation_roles=frozenset(
                str(value) for value in roles["development_evaluation"]
            ),
            prohibited_roles=frozenset(
                str(value) for value in roles["prohibited"]
            ),
            rolling_origin_folds=_parse_folds(
                [dict(value) for value in payload["rolling_origin_folds"]]
            ),
            evaluation=EvaluationPolicy(
                primary_metric="log_loss",
                metrics=tuple(str(value) for value in evaluation_payload["metrics"]),
                reliability_bins=int(evaluation_payload["reliability_bins"]),
                bootstrap_replicates=int(
                    evaluation_payload["bootstrap_replicates"]
                ),
                bootstrap_confidence_level=float(
                    evaluation_payload["bootstrap_confidence_level"]
                ),
                bootstrap_group_column=str(
                    evaluation_payload["bootstrap_group_column"]
                ),
                random_seed=int(evaluation_payload["random_seed"]),
                coefficient_top_k=int(evaluation_payload["coefficient_top_k"]),
            ),
            selection_policy=selection,
            safety=safety,
            fingerprint=hashlib.sha256(
                canonical_json(payload).encode("utf-8")
            ).hexdigest(),
        )
    except InteractionConfigError:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise InteractionConfigError("Malformed M4B.4 config.") from error

    _validate_policy(config)
    if verify_local_artifacts:
        _verify_local_artifacts(config)
    return config


__all__ = [
    "CONFIG_SCHEMA_VERSION",
    "InteractionCandidate",
    "InteractionConfigError",
    "InteractionExperimentConfig",
    "M4APin",
    "M4B2Pin",
    "M4B3Pin",
    "SELECTION_FOLD_IDS",
    "load_interaction_experiment_config",
]
