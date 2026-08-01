"""Immutable configuration for development-only Draft AI baseline experiments."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .baselines import BaselineId
from .contracts import (
    SPLIT_ROLE_CALIBRATION,
    SPLIT_ROLE_LOCKED_TEST,
    SPLIT_ROLE_TRAIN,
    SPLIT_ROLE_TUNING,
    WORKING_CORPUS_ID,
)
from .loader import sha256_file


CONFIG_SCHEMA_VERSION = "draft-ai-baseline-experiment-v1"
PROHIBITED_ROLES = frozenset(
    {SPLIT_ROLE_CALIBRATION, SPLIT_ROLE_LOCKED_TEST}
)


class ExperimentConfigError(ValueError):
    """Raised when the M4B experiment contract is unsafe or inconsistent."""


@dataclass(frozen=True, slots=True)
class RollingOriginFold:
    """One expanding-window, past-only evaluation fold."""

    fold_id: str
    train_start_utc: datetime
    train_end_utc: datetime
    evaluation_start_utc: datetime
    evaluation_end_utc: datetime


@dataclass(frozen=True, slots=True)
class EvaluationPolicy:
    """Fixed probability-quality and uncertainty settings."""

    primary_metric: str
    metrics: tuple[str, ...]
    reliability_bins: int
    bootstrap_replicates: int
    bootstrap_confidence_level: float
    bootstrap_group_column: str
    random_seed: int
    coefficient_top_k: int


@dataclass(frozen=True, slots=True)
class BaselineExperimentConfig:
    """Resolved, fingerprinted M4B.1 experiment configuration."""

    config_path: Path
    repository_root: Path
    experiment_id: str
    corpus_config_path: Path
    corpus_config_sha256: str
    corpus_id: str
    m4a_build_fingerprint: str
    m4a_manifest_path: Path
    m4a_manifest_sha256: str
    split_manifest_fingerprint: str
    baseline_ids: tuple[BaselineId, ...]
    fit_role: str
    selection_role: str
    prohibited_roles: frozenset[str]
    rolling_origin_folds: tuple[RollingOriginFold, ...]
    evaluation: EvaluationPolicy
    selection_policy: dict[str, Any]
    safety: dict[str, Any]
    fingerprint: str

    def assert_role_allowed(
        self,
        role: str,
        *,
        purpose: str,
    ) -> None:
        """Reject accidental calibration or locked-test access."""

        if role in self.prohibited_roles:
            raise ExperimentConfigError(
                f"{role} is prohibited during M4B.1 {purpose}."
            )
        allowed = (
            {self.fit_role}
            if purpose == "fit"
            else {self.selection_role}
        )
        if role not in allowed:
            raise ExperimentConfigError(
                f"{role} is not approved for M4B.1 {purpose}."
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
        raise ExperimentConfigError("Experiment timestamps require an offset.")
    return parsed.astimezone(UTC)


def _repository_root(path: Path) -> Path:
    for candidate in path.resolve().parents:
        if (candidate / "src" / "draft_ai_modeling").is_dir():
            return candidate
    raise ExperimentConfigError("Could not discover the repository root.")


def _repository_path(root: Path, value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ExperimentConfigError(
            "Experiment artifact paths must be repository-relative."
        )
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ExperimentConfigError(
            "An experiment artifact path escapes the repository."
        ) from error
    return resolved


def _sha256(value: str, *, label: str) -> str:
    if len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ExperimentConfigError(f"{label} must be a lowercase SHA-256.")
    return value


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
        raise ExperimentConfigError(
            "M4B.1 requires seven uniquely named quarterly folds."
        )
    for index, fold in enumerate(folds):
        if (
            not fold.fold_id
            or fold.train_start_utc >= fold.train_end_utc
            or fold.train_end_utc != fold.evaluation_start_utc
            or fold.evaluation_start_utc >= fold.evaluation_end_utc
        ):
            raise ExperimentConfigError(
                f"{fold.fold_id} is not a valid past-only fold."
            )
        if index:
            previous = folds[index - 1]
            if (
                fold.train_start_utc != previous.train_start_utc
                or fold.train_end_utc != previous.evaluation_end_utc
                or fold.evaluation_start_utc
                != previous.evaluation_end_utc
            ):
                raise ExperimentConfigError(
                    "Rolling folds must be chronological expanding quarters."
                )
    if (
        folds[0].fold_id != "2024-Q1"
        or folds[-1].fold_id != "2025-Q3"
        or folds[-1].evaluation_end_utc
        != datetime(2025, 10, 1, tzinfo=UTC)
    ):
        raise ExperimentConfigError("The approved rolling-fold boundary changed.")
    return folds


def _validate_safety(
    payload: dict[str, Any],
    *,
    fit_role: str,
    selection_role: str,
    prohibited_roles: frozenset[str],
) -> None:
    required_false = (
        "api_dependency",
        "acquisition_dependency",
        "hyperparameter_search",
        "calibration_fit",
        "locked_test_predictions",
        "nonlinear_challengers",
        "context_features",
        "patch_or_recency_experiments",
    )
    if any(payload.get(key) is not False for key in required_false):
        raise ExperimentConfigError("M4B.1 safety flags must remain disabled.")
    if (
        tuple(payload.get("model_fitting_roles", ())) != (fit_role,)
        or tuple(payload.get("model_evaluation_roles", ()))
        != (selection_role,)
        or prohibited_roles != PROHIBITED_ROLES
    ):
        raise ExperimentConfigError("M4B.1 role safety policy changed.")


def load_experiment_config(
    config_path: Path,
    *,
    repository_root: Path | None = None,
    verify_local_artifacts: bool = True,
) -> BaselineExperimentConfig:
    """Load, validate, and fingerprint the exact M4B.1 experiment.

    ``verify_local_artifacts=False`` validates the credential-free public
    contract without requiring ignored, locally generated M4A outputs.  The
    experiment runner keeps the default enabled and therefore cannot fit a
    model unless every local source pin is present and unchanged.
    """

    path = config_path.resolve()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ExperimentConfigError("Cannot read the M4B config.") from error
    if not isinstance(payload, dict):
        raise ExperimentConfigError("The M4B config must be a JSON object.")
    try:
        if payload["config_schema_version"] != CONFIG_SCHEMA_VERSION:
            raise ExperimentConfigError("Unsupported M4B config version.")
        root = (
            repository_root.resolve()
            if repository_root is not None
            else _repository_root(path)
        )
        source = payload["source"]
        roles = payload["roles"]
        evaluation_payload = payload["evaluation"]
        fit_role = str(roles["fit"])
        selection_role = str(roles["selection"])
        prohibited_roles = frozenset(str(item) for item in roles["prohibited"])
        baseline_ids = tuple(BaselineId(item) for item in payload["baselines"])
        evaluation = EvaluationPolicy(
            primary_metric=str(evaluation_payload["primary_metric"]),
            metrics=tuple(str(item) for item in evaluation_payload["metrics"]),
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
        )
        config = BaselineExperimentConfig(
            config_path=path,
            repository_root=root,
            experiment_id=str(payload["experiment_id"]),
            corpus_config_path=_repository_path(
                root, str(source["corpus_config_path"])
            ),
            corpus_config_sha256=_sha256(
                str(source["corpus_config_sha256"]),
                label="corpus_config_sha256",
            ),
            corpus_id=str(source["corpus_id"]),
            m4a_build_fingerprint=_sha256(
                str(source["m4a_build_fingerprint"]),
                label="m4a_build_fingerprint",
            ),
            m4a_manifest_path=_repository_path(
                root, str(source["m4a_manifest_path"])
            ),
            m4a_manifest_sha256=_sha256(
                str(source["m4a_manifest_sha256"]),
                label="m4a_manifest_sha256",
            ),
            split_manifest_fingerprint=_sha256(
                str(source["split_manifest_fingerprint"]),
                label="split_manifest_fingerprint",
            ),
            baseline_ids=baseline_ids,
            fit_role=fit_role,
            selection_role=selection_role,
            prohibited_roles=prohibited_roles,
            rolling_origin_folds=_parse_folds(
                list(payload["rolling_origin_folds"])
            ),
            evaluation=evaluation,
            selection_policy=dict(payload["selection_policy"]),
            safety=dict(payload["safety"]),
            fingerprint=hashlib.sha256(
                canonical_json(payload).encode("utf-8")
            ).hexdigest(),
        )
    except ExperimentConfigError:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise ExperimentConfigError("Malformed M4B experiment config.") from error

    if (
        config.experiment_id != "m4b1-b0-b3-temporal-baselines-v1"
        or config.corpus_id != WORKING_CORPUS_ID
        or config.baseline_ids != tuple(BaselineId)
        or config.fit_role != SPLIT_ROLE_TRAIN
        or config.selection_role != SPLIT_ROLE_TUNING
        or config.prohibited_roles != PROHIBITED_ROLES
    ):
        raise ExperimentConfigError("The approved M4B.1 identity changed.")
    if (
        config.evaluation.primary_metric != "log_loss"
        or config.evaluation.reliability_bins != 10
        or config.evaluation.bootstrap_replicates != 1000
        or config.evaluation.bootstrap_confidence_level != 0.95
        or config.evaluation.bootstrap_group_column != "source_match_id"
        or config.evaluation.random_seed != 42
        or config.evaluation.coefficient_top_k != 20
    ):
        raise ExperimentConfigError("The approved evaluation policy changed.")
    _validate_safety(
        config.safety,
        fit_role=config.fit_role,
        selection_role=config.selection_role,
        prohibited_roles=config.prohibited_roles,
    )
    if not config.experiment_id.strip():
        raise ExperimentConfigError("Experiment ID cannot be empty.")
    if verify_local_artifacts:
        if sha256_file(config.corpus_config_path) != config.corpus_config_sha256:
            raise ExperimentConfigError("The pinned corpus config changed.")
        if (
            not config.m4a_manifest_path.is_file()
            or sha256_file(config.m4a_manifest_path)
            != config.m4a_manifest_sha256
        ):
            raise ExperimentConfigError("The pinned M4A manifest changed.")
    return config
