"""Immutable configuration for the M8 hero-embedding experiment.

The public contract can be validated without ignored model artifacts. Runtime
execution keeps strict verification enabled and therefore cannot fit unless
the pinned M4A, M4B.1, and M4B.2 builds, manifests, and artifacts are present
and unchanged.
"""

from __future__ import annotations

import hashlib
import json
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


CONFIG_SCHEMA_VERSION = "draft-ai-hero-embedding-experiment-v1"
EXPERIMENT_ID = "m8-hero-embeddings-v1"
M4B1_EXPERIMENT_ID = "m4b1-b0-b3-temporal-baselines-v1"
M4B2_EXPERIMENT_ID = "m4b2-b1-regularization-recency-v1"
FROZEN_REFERENCE_CANDIDATE_ID = "b1_full_uniform_c0p01"
PROHIBITED_ROLES = frozenset(
    {SPLIT_ROLE_CALIBRATION, SPLIT_ROLE_LOCKED_TEST}
)
FIT_ROLES = frozenset({SPLIT_ROLE_TRAIN})
DEVELOPMENT_EVALUATION_ROLES = frozenset(
    {SPLIT_ROLE_TRAIN, SPLIT_ROLE_TUNING}
)
SELECTION_FOLD_IDS = ("2025-Q1", "2025-Q2", "2025-Q3")

EXPECTED_CANDIDATES = (
    ("emb_d4_l2_0p01", "full_uniform", 4, 0.01),
    ("emb_d4_l2_0p1", "full_uniform", 4, 0.1),
    ("emb_d4_l2_1", "full_uniform", 4, 1.0),
    ("emb_d8_l2_0p01", "full_uniform", 8, 0.01),
    ("emb_d8_l2_0p1", "full_uniform", 8, 0.1),
    ("emb_d8_l2_1", "full_uniform", 8, 1.0),
    ("emb_d16_l2_0p01", "full_uniform", 16, 0.01),
    ("emb_d16_l2_0p1", "full_uniform", 16, 0.1),
    ("emb_d16_l2_1", "full_uniform", 16, 1.0),
)

EXPECTED_ESTIMATOR: dict[str, Any] = {
    "family": "low_rank_hero_embedding",
    "objective": "penalized_binary_cross_entropy",
    "gradient_source": "hand_derived_analytic",
    "optimizer": "full_batch_adam",
    "learning_rate": 0.05,
    "adam_beta_1": 0.9,
    "adam_beta_2": 0.999,
    "adam_epsilon": 1e-08,
    "max_iterations": 2500,
    "gradient_tolerance": 1e-06,
    "init_scale": 0.1,
    "random_seed": 42,
}

EXPECTED_SELECTION_POLICY: dict[str, Any] = {
    "selection_fold_ids": list(SELECTION_FOLD_IDS),
    "pooled_predictions": "concatenate_each_selected_game_once",
    "qualification_metrics": ["log_loss", "brier_score"],
    "point_estimate_references": [
        "canonical_b0",
        "frozen_b1_candidate",
    ],
    "require_strict_improvement_in_each_fold": True,
    "require_strict_improvement_on_pooled_predictions": True,
    "paired_group_bootstrap": {
        "references": ["canonical_b0", "frozen_b1_candidate"],
        "metrics": ["log_loss", "brier_score"],
        "confidence_level": 0.95,
        "replicates": 1000,
        "group_column": "source_match_id",
        "require_upper_bound_below": 0.0,
        "random_seed": 42,
    },
    "ranking_metric": "pooled_log_loss",
    "ranking_direction": "minimize",
    "practical_log_loss_tie": 0.002,
    "embedding_dim_preference": [4, 8, 16],
    "l2_preference": [1.0, 0.1, 0.01],
    "result_label": "hero_embedding_candidate_not_final_champion",
}

EXPECTED_SAFETY = {
    "api_dependency": False,
    "acquisition_dependency": False,
    "calibration_fit": False,
    "calibration_predictions": False,
    "locked_test_predictions": False,
    "patch_features": False,
    "context_features": False,
    "ban_features": False,
    "slot_features": False,
    "b2_or_b3_candidates": False,
    "deep_learning_framework_dependency": False,
    "autodiff_dependency": False,
    "open_ended_hyperparameter_search": False,
    "pre_registered_candidates_only": True,
    "model_serialization": False,
}

EXPECTED_REPRESENTATION = {
    "baseline_id": "M8",
    "feature_variant": "hero-embedding-low-rank-interactions",
    "side_relative": True,
    "includes_bans": False,
    "slot_aware": False,
    "includes_main_effects": True,
    "includes_pairwise_interactions": True,
    "interaction_form": "bilinear_dot_product",
    "interaction_scope": [
        "within_radiant",
        "within_dire",
        "cross_side",
    ],
}


class EmbeddingConfigError(ValueError):
    """Raised when the M8 contract is unsafe or inconsistent."""


@dataclass(frozen=True, slots=True)
class ArtifactPin:
    """One public artifact name, file name, and expected digest."""

    name: str
    file: str
    sha256: str


@dataclass(frozen=True, slots=True)
class BuildPin:
    """One content-addressed local build and all of its public artifact pins."""

    build_fingerprint: str
    manifest_path: Path
    manifest_sha256: str
    artifacts: tuple[ArtifactPin, ...]


@dataclass(frozen=True, slots=True)
class M4B1Pin:
    """The exact M4B.1 experiment consumed as comparison evidence."""

    experiment_id: str
    experiment_config_path: Path
    experiment_config_sha256: str
    experiment_config_fingerprint: str
    build: BuildPin


@dataclass(frozen=True, slots=True)
class FrozenReferenceCandidate:
    """The frozen M4B.2 development candidate this experiment must beat."""

    candidate_id: str
    candidate_fingerprint: str
    history_policy_id: str
    regularization_c: float


@dataclass(frozen=True, slots=True)
class M4B2Pin:
    """The exact M4B.2 experiment and frozen candidate consumed as evidence."""

    experiment_id: str
    experiment_config_path: Path
    experiment_config_sha256: str
    experiment_config_fingerprint: str
    build: BuildPin
    frozen_reference_candidate: FrozenReferenceCandidate


@dataclass(frozen=True, slots=True)
class HistoryPolicy:
    """A predeclared training-row and sample-weight policy."""

    history_policy_id: str
    training_rows: str
    sample_weight: str
    anchor: str


@dataclass(frozen=True, slots=True)
class EmbeddingCandidate:
    """One explicit embedding-dimension and L2 combination."""

    candidate_id: str
    history_policy_id: str
    embedding_dim: int
    l2: float


@dataclass(frozen=True, slots=True)
class EstimatorPolicy:
    """Fixed hero-embedding optimizer settings shared by all nine candidates."""

    family: str
    objective: str
    gradient_source: str
    optimizer: str
    learning_rate: float
    adam_beta_1: float
    adam_beta_2: float
    adam_epsilon: float
    max_iterations: int
    gradient_tolerance: float
    init_scale: float
    random_seed: int


@dataclass(frozen=True, slots=True)
class HeroEmbeddingExperimentConfig:
    """Resolved, fingerprinted M8 development-only experiment."""

    config_path: Path
    repository_root: Path
    experiment_id: str
    corpus_config_path: Path
    corpus_config_sha256: str
    corpus_id: str
    split_manifest_fingerprint: str
    m4a: BuildPin
    m4b1: M4B1Pin
    m4b2: M4B2Pin
    history_policies: tuple[HistoryPolicy, ...]
    candidates: tuple[EmbeddingCandidate, ...]
    estimator: EstimatorPolicy
    fit_roles: frozenset[str]
    development_evaluation_roles: frozenset[str]
    prohibited_roles: frozenset[str]
    rolling_origin_folds: tuple[RollingOriginFold, ...]
    evaluation: EvaluationPolicy
    selection_policy: dict[str, Any]
    safety: dict[str, Any]
    fingerprint: str

    def history_policy(self, history_policy_id: str) -> HistoryPolicy:
        """Resolve one declared history policy by stable identifier."""

        for policy in self.history_policies:
            if policy.history_policy_id == history_policy_id:
                return policy
        raise EmbeddingConfigError(
            f"Unknown history policy: {history_policy_id!r}."
        )

    def assert_role_allowed(self, role: str, *, purpose: str) -> None:
        """Reject calibration or locked-test access before any fitting."""

        if role in self.prohibited_roles:
            raise EmbeddingConfigError(
                f"{role} is prohibited during M8 {purpose}."
            )
        allowed = (
            self.fit_roles
            if purpose == "fit"
            else self.development_evaluation_roles
        )
        if role not in allowed:
            raise EmbeddingConfigError(
                f"{role} is not approved for M8 {purpose}."
            )


def canonical_json(value: object) -> str:
    """Return the deterministic JSON representation used for fingerprints."""

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise EmbeddingConfigError("Experiment timestamps require an offset.")
    return parsed.astimezone(UTC)


def _repository_root(path: Path) -> Path:
    for candidate in path.resolve().parents:
        if (candidate / "src" / "draft_ai_modeling").is_dir():
            return candidate
    raise EmbeddingConfigError("Could not discover the repository root.")


def _repository_path(root: Path, value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise EmbeddingConfigError(
            "Experiment artifact paths must be repository-relative."
        )
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise EmbeddingConfigError(
            "An experiment artifact path escapes the repository."
        ) from error
    return resolved


def _sha256(value: str, *, label: str) -> str:
    if len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise EmbeddingConfigError(f"{label} must be a lowercase SHA-256.")
    return value


def _parse_artifacts(payload: dict[str, Any]) -> tuple[ArtifactPin, ...]:
    artifacts = tuple(
        ArtifactPin(
            name=str(name),
            file=str(value["file"]),
            sha256=_sha256(
                str(value["sha256"]),
                label=f"{name} artifact sha256",
            ),
        )
        for name, value in sorted(payload.items())
    )
    if not artifacts or len({item.name for item in artifacts}) != len(artifacts):
        raise EmbeddingConfigError("Artifact pins must be non-empty and unique.")
    for artifact in artifacts:
        file = Path(artifact.file)
        if (
            not artifact.name
            or not artifact.file
            or file.is_absolute()
            or len(file.parts) != 1
            or file.name != artifact.file
        ):
            raise EmbeddingConfigError(
                "Pinned artifact files must be safe file names."
            )
    return artifacts


def _parse_build(
    payload: dict[str, Any],
    *,
    root: Path,
    label: str,
) -> BuildPin:
    return BuildPin(
        build_fingerprint=_sha256(
            str(payload["build_fingerprint"]),
            label=f"{label} build fingerprint",
        ),
        manifest_path=_repository_path(root, str(payload["manifest_path"])),
        manifest_sha256=_sha256(
            str(payload["manifest_sha256"]),
            label=f"{label} manifest sha256",
        ),
        artifacts=_parse_artifacts(dict(payload["artifacts"])),
    )


def _parse_history_policies(
    values: list[dict[str, Any]],
) -> tuple[HistoryPolicy, ...]:
    policies = tuple(
        HistoryPolicy(
            history_policy_id=str(value["history_policy_id"]),
            training_rows=str(value["training_rows"]),
            sample_weight=str(value["sample_weight"]),
            anchor=str(value["anchor"]),
        )
        for value in values
    )
    expected = (
        HistoryPolicy(
            "full_uniform",
            "all_strictly_past_rows",
            "uniform",
            "train_end_utc",
        ),
    )
    if policies != expected:
        raise EmbeddingConfigError(
            "M8 must use only the frozen full_uniform history policy."
        )
    return policies


def _parse_candidates(
    values: list[dict[str, Any]],
) -> tuple[EmbeddingCandidate, ...]:
    candidates = tuple(
        EmbeddingCandidate(
            candidate_id=str(value["candidate_id"]),
            history_policy_id=str(value["history_policy_id"]),
            embedding_dim=int(value["embedding_dim"]),
            l2=float(value["l2"]),
        )
        for value in values
    )
    observed = tuple(
        (
            item.candidate_id,
            item.history_policy_id,
            item.embedding_dim,
            item.l2,
        )
        for item in candidates
    )
    if observed != EXPECTED_CANDIDATES:
        raise EmbeddingConfigError(
            "M8 requires the exact nine pre-registered candidates."
        )
    return candidates


def _parse_folds(values: list[dict[str, Any]]) -> tuple[RollingOriginFold, ...]:
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
    if len(folds) != 7 or len({fold.fold_id for fold in folds}) != len(folds):
        raise EmbeddingConfigError(
            "M8 requires seven uniquely named quarterly folds."
        )
    expected_start = datetime(2024, 1, 1, tzinfo=UTC)
    for index, fold in enumerate(folds):
        expected_evaluation_start = (
            expected_start
            if index == 0
            else folds[index - 1].evaluation_end_utc
        )
        if (
            fold.train_start_utc != datetime(2022, 1, 1, tzinfo=UTC)
            or fold.train_end_utc != expected_evaluation_start
            or fold.evaluation_start_utc != expected_evaluation_start
            or fold.evaluation_start_utc >= fold.evaluation_end_utc
        ):
            raise EmbeddingConfigError(
                f"{fold.fold_id} is not an approved past-only fold."
            )
    if (
        tuple(fold.fold_id for fold in folds)
        != (
            "2024-Q1",
            "2024-Q2",
            "2024-Q3",
            "2024-Q4",
            "2025-Q1",
            "2025-Q2",
            "2025-Q3",
        )
        or folds[-1].evaluation_end_utc
        != datetime(2025, 10, 1, tzinfo=UTC)
    ):
        raise EmbeddingConfigError("The approved rolling-fold boundary changed.")
    return folds


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EmbeddingConfigError(f"Cannot read the pinned {label}.") from error
    if not isinstance(value, dict):
        raise EmbeddingConfigError(f"The pinned {label} must be a JSON object.")
    return value


def _artifact_map(
    artifacts: tuple[ArtifactPin, ...],
) -> dict[str, ArtifactPin]:
    return {artifact.name: artifact for artifact in artifacts}


def _verify_build(
    build: BuildPin,
    *,
    label: str,
    required_manifest_values: dict[str, object],
) -> dict[str, Any]:
    if (
        not build.manifest_path.is_file()
        or sha256_file(build.manifest_path) != build.manifest_sha256
    ):
        raise EmbeddingConfigError(f"The pinned {label} manifest changed.")
    manifest = _read_json(build.manifest_path, label=f"{label} manifest")
    for key, expected in required_manifest_values.items():
        if manifest.get(key) != expected:
            raise EmbeddingConfigError(
                f"The pinned {label} manifest identity changed."
            )
    declared = _artifact_map(build.artifacts)
    observed = manifest.get("artifacts")
    if not isinstance(observed, dict) or not set(declared) <= set(observed):
        raise EmbeddingConfigError(
            f"The pinned {label} artifact inventory changed."
        )
    for name, pin in declared.items():
        record = observed.get(name)
        if (
            not isinstance(record, dict)
            or record.get("file") != pin.file
            or record.get("sha256") != pin.sha256
        ):
            raise EmbeddingConfigError(
                f"The pinned {label} artifact metadata changed."
            )
        artifact_path = build.manifest_path.parent / pin.file
        if (
            not artifact_path.is_file()
            or sha256_file(artifact_path) != pin.sha256
        ):
            raise EmbeddingConfigError(
                f"The pinned {label} artifact changed: {name}."
            )
    return manifest


def _verify_local_artifacts(config: HeroEmbeddingExperimentConfig) -> None:
    if (
        not config.corpus_config_path.is_file()
        or sha256_file(config.corpus_config_path)
        != config.corpus_config_sha256
    ):
        raise EmbeddingConfigError("The pinned corpus config changed.")
    m4a_manifest = _verify_build(
        config.m4a,
        label="M4A",
        required_manifest_values={
            "build_fingerprint": config.m4a.build_fingerprint,
        },
    )
    m4a_source = m4a_manifest.get("source")
    m4a_split = m4a_manifest.get("split")
    if (
        not isinstance(m4a_source, dict)
        or m4a_source.get("corpus_id") != config.corpus_id
        or m4a_source.get("config_sha256") != config.corpus_config_sha256
        or not isinstance(m4a_split, dict)
        or m4a_split.get("split_manifest_fingerprint")
        != config.split_manifest_fingerprint
    ):
        raise EmbeddingConfigError("The pinned M4A source identity changed.")

    if (
        not config.m4b1.experiment_config_path.is_file()
        or sha256_file(config.m4b1.experiment_config_path)
        != config.m4b1.experiment_config_sha256
    ):
        raise EmbeddingConfigError("The pinned M4B.1 config changed.")
    m4b1_manifest = _verify_build(
        config.m4b1.build,
        label="M4B.1",
        required_manifest_values={
            "experiment_id": config.m4b1.experiment_id,
            "experiment_config_fingerprint": (
                config.m4b1.experiment_config_fingerprint
            ),
            "build_fingerprint": config.m4b1.build.build_fingerprint,
            "config_sha256": config.m4b1.experiment_config_sha256,
        },
    )
    m4b1_source = m4b1_manifest.get("source")
    if (
        not isinstance(m4b1_source, dict)
        or m4b1_source.get("corpus_id") != config.corpus_id
        or m4b1_source.get("split_manifest_fingerprint")
        != config.split_manifest_fingerprint
    ):
        raise EmbeddingConfigError("The pinned M4B.1 source identity changed.")

    if (
        not config.m4b2.experiment_config_path.is_file()
        or sha256_file(config.m4b2.experiment_config_path)
        != config.m4b2.experiment_config_sha256
    ):
        raise EmbeddingConfigError("The pinned M4B.2 config changed.")
    m4b2_manifest = _verify_build(
        config.m4b2.build,
        label="M4B.2",
        required_manifest_values={
            "experiment_id": config.m4b2.experiment_id,
            "experiment_config_fingerprint": (
                config.m4b2.experiment_config_fingerprint
            ),
            "build_fingerprint": config.m4b2.build.build_fingerprint,
            "config_sha256": config.m4b2.experiment_config_sha256,
        },
    )
    m4b2_source = m4b2_manifest.get("source")
    if (
        not isinstance(m4b2_source, dict)
        or m4b2_source.get("corpus_id") != config.corpus_id
        or m4b2_source.get("split_manifest_fingerprint")
        != config.split_manifest_fingerprint
    ):
        raise EmbeddingConfigError("The pinned M4B.2 source identity changed.")
    m4b2_candidates = m4b2_manifest.get("candidates")
    if not isinstance(m4b2_candidates, list):
        raise EmbeddingConfigError("The pinned M4B.2 candidates changed.")
    matched = next(
        (
            candidate
            for candidate in m4b2_candidates
            if isinstance(candidate, dict)
            and candidate.get("candidate_id")
            == config.m4b2.frozen_reference_candidate.candidate_id
        ),
        None,
    )
    if (
        matched is None
        or matched.get("fingerprint")
        != config.m4b2.frozen_reference_candidate.candidate_fingerprint
        or matched.get("history_policy_id")
        != config.m4b2.frozen_reference_candidate.history_policy_id
        or matched.get("C")
        != config.m4b2.frozen_reference_candidate.regularization_c
    ):
        raise EmbeddingConfigError(
            "The pinned frozen M4B.2 reference candidate changed."
        )


def load_embedding_experiment_config(
    config_path: Path,
    *,
    repository_root: Path | None = None,
    verify_local_artifacts: bool = True,
) -> HeroEmbeddingExperimentConfig:
    """Load and validate the exact development-only M8 experiment."""

    path = config_path.resolve()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EmbeddingConfigError("Cannot read the M8 config.") from error
    if not isinstance(payload, dict):
        raise EmbeddingConfigError("The M8 config must be a JSON object.")
    try:
        if payload["config_schema_version"] != CONFIG_SCHEMA_VERSION:
            raise EmbeddingConfigError("Unsupported M8 config version.")
        root = (
            repository_root.resolve()
            if repository_root is not None
            else _repository_root(path)
        )
        source = dict(payload["source"])
        m4a_payload = dict(source["m4a"])
        m4b1_payload = dict(source["m4b1"])
        m4b2_payload = dict(source["m4b2"])
        roles = dict(payload["roles"])
        evaluation_payload = dict(payload["evaluation"])
        estimator_payload = dict(payload["estimator"])
        m4b1 = M4B1Pin(
            experiment_id=str(m4b1_payload["experiment_id"]),
            experiment_config_path=_repository_path(
                root,
                str(m4b1_payload["experiment_config_path"]),
            ),
            experiment_config_sha256=_sha256(
                str(m4b1_payload["experiment_config_sha256"]),
                label="M4B.1 config sha256",
            ),
            experiment_config_fingerprint=_sha256(
                str(m4b1_payload["experiment_config_fingerprint"]),
                label="M4B.1 config fingerprint",
            ),
            build=_parse_build(m4b1_payload, root=root, label="M4B.1"),
        )
        frozen_payload = dict(m4b2_payload["frozen_reference_candidate"])
        m4b2 = M4B2Pin(
            experiment_id=str(m4b2_payload["experiment_id"]),
            experiment_config_path=_repository_path(
                root,
                str(m4b2_payload["experiment_config_path"]),
            ),
            experiment_config_sha256=_sha256(
                str(m4b2_payload["experiment_config_sha256"]),
                label="M4B.2 config sha256",
            ),
            experiment_config_fingerprint=_sha256(
                str(m4b2_payload["experiment_config_fingerprint"]),
                label="M4B.2 config fingerprint",
            ),
            build=_parse_build(m4b2_payload, root=root, label="M4B.2"),
            frozen_reference_candidate=FrozenReferenceCandidate(
                candidate_id=str(frozen_payload["candidate_id"]),
                candidate_fingerprint=_sha256(
                    str(frozen_payload["candidate_fingerprint"]),
                    label="frozen reference candidate fingerprint",
                ),
                history_policy_id=str(frozen_payload["history_policy_id"]),
                regularization_c=float(frozen_payload["C"]),
            ),
        )
        config = HeroEmbeddingExperimentConfig(
            config_path=path,
            repository_root=root,
            experiment_id=str(payload["experiment_id"]),
            corpus_config_path=_repository_path(
                root,
                str(source["corpus_config_path"]),
            ),
            corpus_config_sha256=_sha256(
                str(source["corpus_config_sha256"]),
                label="corpus config sha256",
            ),
            corpus_id=str(source["corpus_id"]),
            split_manifest_fingerprint=_sha256(
                str(source["split_manifest_fingerprint"]),
                label="split manifest fingerprint",
            ),
            m4a=_parse_build(m4a_payload, root=root, label="M4A"),
            m4b1=m4b1,
            m4b2=m4b2,
            history_policies=_parse_history_policies(
                list(payload["history_policies"])
            ),
            candidates=_parse_candidates(list(payload["candidates"])),
            estimator=EstimatorPolicy(
                family=str(estimator_payload["family"]),
                objective=str(estimator_payload["objective"]),
                gradient_source=str(estimator_payload["gradient_source"]),
                optimizer=str(estimator_payload["optimizer"]),
                learning_rate=float(estimator_payload["learning_rate"]),
                adam_beta_1=float(estimator_payload["adam_beta_1"]),
                adam_beta_2=float(estimator_payload["adam_beta_2"]),
                adam_epsilon=float(estimator_payload["adam_epsilon"]),
                max_iterations=int(estimator_payload["max_iterations"]),
                gradient_tolerance=float(
                    estimator_payload["gradient_tolerance"]
                ),
                init_scale=float(estimator_payload["init_scale"]),
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
                list(payload["rolling_origin_folds"])
            ),
            evaluation=EvaluationPolicy(
                primary_metric="log_loss",
                metrics=tuple(
                    str(value) for value in evaluation_payload["metrics"]
                ),
                reliability_bins=int(
                    evaluation_payload["reliability_bins"]
                ),
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
                coefficient_top_k=int(
                    evaluation_payload["coefficient_top_k"]
                ),
            ),
            selection_policy=dict(payload["selection_policy"]),
            safety=dict(payload["safety"]),
            fingerprint=hashlib.sha256(
                canonical_json(payload).encode("utf-8")
            ).hexdigest(),
        )
    except EmbeddingConfigError:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise EmbeddingConfigError("Malformed M8 config.") from error

    if payload.get("representation") != EXPECTED_REPRESENTATION:
        raise EmbeddingConfigError("The approved M8 representation changed.")
    if (
        config.experiment_id != EXPERIMENT_ID
        or config.corpus_id != WORKING_CORPUS_ID
        or config.m4b1.experiment_id != M4B1_EXPERIMENT_ID
        or config.m4b2.experiment_id != M4B2_EXPERIMENT_ID
        or config.m4b2.frozen_reference_candidate.candidate_id
        != FROZEN_REFERENCE_CANDIDATE_ID
        or config.fit_roles != FIT_ROLES
        or config.development_evaluation_roles
        != DEVELOPMENT_EVALUATION_ROLES
        or config.prohibited_roles != PROHIBITED_ROLES
    ):
        raise EmbeddingConfigError("The approved M8 identity changed.")
    if config.estimator != EstimatorPolicy(**EXPECTED_ESTIMATOR):
        raise EmbeddingConfigError("The approved estimator policy changed.")
    if (
        config.evaluation.metrics
        != (
            "log_loss",
            "brier_score",
            "roc_auc",
            "accuracy",
            "balanced_accuracy",
            "calibration_in_the_large",
            "calibration_slope",
            "expected_calibration_error",
        )
        or config.evaluation.reliability_bins != 10
        or config.evaluation.bootstrap_replicates != 1000
        or config.evaluation.bootstrap_confidence_level != 0.95
        or config.evaluation.bootstrap_group_column != "source_match_id"
        or config.evaluation.random_seed != 42
        or config.evaluation.coefficient_top_k != 20
    ):
        raise EmbeddingConfigError("The approved evaluation policy changed.")
    if config.selection_policy != EXPECTED_SELECTION_POLICY:
        raise EmbeddingConfigError("The approved selection policy changed.")
    if config.safety != EXPECTED_SAFETY:
        raise EmbeddingConfigError("The approved M8 safety policy changed.")
    if verify_local_artifacts:
        _verify_local_artifacts(config)
    return config


__all__ = [
    "ArtifactPin",
    "BuildPin",
    "CONFIG_SCHEMA_VERSION",
    "EmbeddingCandidate",
    "EmbeddingConfigError",
    "EstimatorPolicy",
    "FrozenReferenceCandidate",
    "HeroEmbeddingExperimentConfig",
    "HistoryPolicy",
    "M4B1Pin",
    "M4B2Pin",
    "SELECTION_FOLD_IDS",
    "load_embedding_experiment_config",
]
