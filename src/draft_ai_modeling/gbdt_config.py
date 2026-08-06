"""Loader for the pre-registered GBDT baseline experiment.

Every protocol decision (the candidate grid, the estimator's fixed
hyperparameters, the early-stopping rule, the fold boundaries, the
selection ranking policy, and the Q4 readiness gate) lives in
configs/modeling/m_gbdt_baseline.json. This module parses and
structurally validates that file; it does not hardcode a shadow copy of
the protocol to compare against. The config is the single source of
truth the experiment code actually executes.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .experiment_config import RollingOriginFold
from .loader import sha256_file


CONFIG_SCHEMA_VERSION = "draft-ai-gbdt-baseline-experiment-v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class GbdtConfigError(ValueError):
    """Raised when the GBDT baseline config is malformed or its pins drift."""


@dataclass(frozen=True, slots=True)
class GbdtCandidateSpec:
    """One pre-registered grid member."""

    candidate_id: str
    num_leaves: int
    learning_rate: float


@dataclass(frozen=True, slots=True)
class GbdtEstimatorPolicy:
    """Fixed LightGBM settings shared by every candidate."""

    objective: str
    metric: str
    num_boost_round: int
    early_stopping_rounds: int
    min_child_samples: int
    feature_fraction: float
    bagging_fraction: float
    bagging_freq: int
    lambda_l1: float
    lambda_l2: float
    max_depth: int
    verbosity: int
    random_seed: int
    deterministic: bool
    force_row_wise: bool

    def lightgbm_params(
        self, *, num_leaves: int, learning_rate: float
    ) -> dict[str, Any]:
        """Return the exact LightGBM param dict for one grid member."""

        return {
            "objective": self.objective,
            "metric": self.metric,
            "num_leaves": num_leaves,
            "learning_rate": learning_rate,
            "min_child_samples": self.min_child_samples,
            "feature_fraction": self.feature_fraction,
            "bagging_fraction": self.bagging_fraction,
            "bagging_freq": self.bagging_freq,
            "lambda_l1": self.lambda_l1,
            "lambda_l2": self.lambda_l2,
            "max_depth": self.max_depth,
            "verbosity": self.verbosity,
            "random_state": self.random_seed,
            "deterministic": self.deterministic,
            "force_row_wise": self.force_row_wise,
        }


@dataclass(frozen=True, slots=True)
class EarlyStoppingPolicy:
    """The chronological-tail early-stopping rule, and where it applies."""

    validation_fraction: float
    monitored_metric: str
    applies_to_selection_stage_fold_fits: bool
    applies_to_q4_gate_final_refit: bool


@dataclass(frozen=True, slots=True)
class SelectionPolicy:
    """How the four grid members are ranked, without touching Q4."""

    recent_fold_ids: tuple[str, ...]
    ranking_metric: str
    ranking_direction: str
    ranking_scope: str
    tie_break: str


@dataclass(frozen=True, slots=True)
class Q4ReadinessPolicy:
    """The paired-bootstrap gate the selected candidate is run through."""

    references: tuple[str, ...]
    metrics: tuple[str, ...]
    require_point_below: float
    require_upper_bound_below: float


@dataclass(frozen=True, slots=True)
class GbdtEvaluationPolicy:
    """Shared reliability-bin and bootstrap settings."""

    reliability_bins: int
    bootstrap_replicates: int
    bootstrap_confidence_level: float
    bootstrap_group_column: str
    bootstrap_random_seed: int


@dataclass(frozen=True, slots=True)
class GbdtBaselineConfig:
    """Resolved, fingerprinted GBDT baseline experiment configuration."""

    config_path: Path
    repository_root: Path
    experiment_id: str
    corpus_config_path: Path
    corpus_config_sha256: str
    corpus_id: str
    m4b5_build_fingerprint: str
    m4b5_manifest_path: Path
    m4b5_manifest_sha256: str
    m4b5_development_predictions_path: Path
    m4b5_development_predictions_sha256: str
    m4b5_q4_predictions_path: Path
    m4b5_q4_predictions_sha256: str
    history_start_utc: datetime
    development_end_utc: datetime
    q4_end_utc: datetime
    expected_development_rows: int
    expected_q4_rows: int
    expected_q4_source_matches: int
    feature_variant: str
    candidates: tuple[GbdtCandidateSpec, ...]
    estimator: GbdtEstimatorPolicy
    early_stopping: EarlyStoppingPolicy
    folds: tuple[RollingOriginFold, ...]
    selection: SelectionPolicy
    q4_readiness: Q4ReadinessPolicy
    evaluation: GbdtEvaluationPolicy
    safety: dict[str, Any]
    fingerprint: str


def canonical_json(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise GbdtConfigError("GBDT config timestamps must include an offset.")
    return parsed.astimezone(UTC)


def _repository_root(path: Path) -> Path:
    for candidate in path.resolve().parents:
        if (candidate / "src" / "draft_ai_modeling").is_dir():
            return candidate
    raise GbdtConfigError("Could not discover the repository root.")


def _repository_path(root: Path, value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise GbdtConfigError("GBDT artifact paths must be repository-relative.")
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise GbdtConfigError(
            "A GBDT artifact path escapes the repository."
        ) from error
    return resolved


def _require_sha256(value: object, *, label: str) -> str:
    text = str(value)
    if _SHA256.fullmatch(text) is None:
        raise GbdtConfigError(f"{label} must be a SHA-256 digest.")
    return text


def _parse_candidates(
    values: list[dict[str, Any]],
) -> tuple[GbdtCandidateSpec, ...]:
    candidates = tuple(
        GbdtCandidateSpec(
            candidate_id=str(value["candidate_id"]),
            num_leaves=int(value["num_leaves"]),
            learning_rate=float(value["learning_rate"]),
        )
        for value in values
    )
    if not candidates or len({c.candidate_id for c in candidates}) != len(
        candidates
    ):
        raise GbdtConfigError(
            "The candidate grid must be non-empty with unique candidate_id values."
        )
    for candidate in candidates:
        if candidate.num_leaves < 2 or not (0 < candidate.learning_rate <= 1):
            raise GbdtConfigError(
                f"{candidate.candidate_id} has an invalid grid value."
            )
    return candidates


def _parse_folds(
    values: list[dict[str, Any]], *, history_start_utc: datetime
) -> tuple[RollingOriginFold, ...]:
    folds: list[RollingOriginFold] = []
    previous_end: datetime | None = None
    for value in values:
        train_end = _utc(value["train_end_utc"])
        evaluation_end = _utc(value["evaluation_end_utc"])
        evaluation_start = train_end
        if previous_end is not None and evaluation_start != previous_end:
            raise GbdtConfigError(
                "Rolling folds must be chronological expanding quarters."
            )
        if evaluation_start >= evaluation_end:
            raise GbdtConfigError(
                f"{value.get('fold_id')} is not a valid past-only fold."
            )
        folds.append(
            RollingOriginFold(
                fold_id=str(value["fold_id"]),
                train_start_utc=history_start_utc,
                train_end_utc=train_end,
                evaluation_start_utc=evaluation_start,
                evaluation_end_utc=evaluation_end,
            )
        )
        previous_end = evaluation_end
    if len(folds) != 7 or len({f.fold_id for f in folds}) != len(folds):
        raise GbdtConfigError("The GBDT config requires seven unique folds.")
    return tuple(folds)


def load_gbdt_baseline_config(
    config_path: Path,
    *,
    repository_root: Path | None = None,
    verify_local_artifacts: bool = True,
) -> GbdtBaselineConfig:
    """Load, structurally validate, and fingerprint the GBDT baseline config."""

    path = config_path.resolve()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GbdtConfigError("Cannot read the GBDT baseline config.") from error
    if not isinstance(payload, dict):
        raise GbdtConfigError("The GBDT baseline config must be a JSON object.")

    try:
        if payload["schema_version"] != CONFIG_SCHEMA_VERSION:
            raise GbdtConfigError("Unsupported GBDT baseline config version.")
        root = (
            repository_root.resolve()
            if repository_root is not None
            else _repository_root(path)
        )
        source = payload["source"]
        m4b5 = source["m4b5"]
        boundaries = payload["data_boundaries"]
        expected = boundaries["expected"]
        feature_contract = payload["feature_contract"]
        estimator_payload = payload["estimator"]
        early_stopping_payload = payload["early_stopping_policy"]
        selection_payload = payload["selection"]
        q4_payload = payload["q4_readiness"]
        evaluation_payload = payload["evaluation"]
        bootstrap_payload = evaluation_payload["paired_group_bootstrap"]

        history_start_utc = _utc(boundaries["history_start_utc"])

        config = GbdtBaselineConfig(
            config_path=path,
            repository_root=root,
            experiment_id=str(payload["experiment_id"]),
            corpus_config_path=_repository_path(
                root, str(source["corpus_config_path"])
            ),
            corpus_config_sha256=_require_sha256(
                source["corpus_config_sha256"], label="corpus_config_sha256"
            ),
            corpus_id=str(source["corpus_id"]),
            m4b5_build_fingerprint=_require_sha256(
                m4b5["build_fingerprint"], label="m4b5 build_fingerprint"
            ),
            m4b5_manifest_path=_repository_path(
                root, str(m4b5["manifest_path"])
            ),
            m4b5_manifest_sha256=_require_sha256(
                m4b5["manifest_sha256"], label="m4b5 manifest_sha256"
            ),
            m4b5_development_predictions_path=_repository_path(
                root, str(m4b5["development_predictions_path"])
            ),
            m4b5_development_predictions_sha256=_require_sha256(
                m4b5["development_predictions_sha256"],
                label="m4b5 development_predictions_sha256",
            ),
            m4b5_q4_predictions_path=_repository_path(
                root, str(m4b5["q4_predictions_path"])
            ),
            m4b5_q4_predictions_sha256=_require_sha256(
                m4b5["q4_predictions_sha256"],
                label="m4b5 q4_predictions_sha256",
            ),
            history_start_utc=history_start_utc,
            development_end_utc=_utc(
                boundaries["development_end_utc_exclusive"]
            ),
            q4_end_utc=_utc(boundaries["q4_end_utc_exclusive"]),
            expected_development_rows=int(
                expected["development_source_rows"]
            ),
            expected_q4_rows=int(expected["q4_rows"]),
            expected_q4_source_matches=int(expected["q4_source_matches"]),
            feature_variant=str(feature_contract["variant"]),
            candidates=_parse_candidates(list(payload["candidate_grid"])),
            estimator=GbdtEstimatorPolicy(
                objective=str(estimator_payload["objective"]),
                metric=str(estimator_payload["metric"]),
                num_boost_round=int(estimator_payload["num_boost_round"]),
                early_stopping_rounds=int(
                    estimator_payload["early_stopping_rounds"]
                ),
                min_child_samples=int(
                    estimator_payload["min_child_samples"]
                ),
                feature_fraction=float(
                    estimator_payload["feature_fraction"]
                ),
                bagging_fraction=float(
                    estimator_payload["bagging_fraction"]
                ),
                bagging_freq=int(estimator_payload["bagging_freq"]),
                lambda_l1=float(estimator_payload["lambda_l1"]),
                lambda_l2=float(estimator_payload["lambda_l2"]),
                max_depth=int(estimator_payload["max_depth"]),
                verbosity=int(estimator_payload["verbosity"]),
                random_seed=int(estimator_payload["random_seed"]),
                deterministic=bool(estimator_payload["deterministic"]),
                force_row_wise=bool(estimator_payload["force_row_wise"]),
            ),
            early_stopping=EarlyStoppingPolicy(
                validation_fraction=float(
                    early_stopping_payload["validation_fraction"]
                ),
                monitored_metric=str(
                    early_stopping_payload["monitored_metric"]
                ),
                applies_to_selection_stage_fold_fits=bool(
                    early_stopping_payload[
                        "applies_to_selection_stage_fold_fits"
                    ]
                ),
                applies_to_q4_gate_final_refit=bool(
                    early_stopping_payload["applies_to_q4_gate_final_refit"]
                ),
            ),
            folds=_parse_folds(
                list(payload["rolling_origin_folds"]),
                history_start_utc=history_start_utc,
            ),
            selection=SelectionPolicy(
                recent_fold_ids=tuple(
                    str(v) for v in selection_payload["recent_fold_ids"]
                ),
                ranking_metric=str(selection_payload["ranking_metric"]),
                ranking_direction=str(
                    selection_payload["ranking_direction"]
                ),
                ranking_scope=str(selection_payload["ranking_scope"]),
                tie_break=str(selection_payload["tie_break"]),
            ),
            q4_readiness=Q4ReadinessPolicy(
                references=tuple(
                    str(v) for v in q4_payload["references"]
                ),
                metrics=tuple(str(v) for v in q4_payload["metrics"]),
                require_point_below=float(
                    q4_payload["require_candidate_minus_reference_point_below"]
                ),
                require_upper_bound_below=float(
                    q4_payload[
                        "require_candidate_minus_reference_upper_bound_below"
                    ]
                ),
            ),
            evaluation=GbdtEvaluationPolicy(
                reliability_bins=int(
                    evaluation_payload["reliability_bins"]
                ),
                bootstrap_replicates=int(bootstrap_payload["replicates"]),
                bootstrap_confidence_level=float(
                    bootstrap_payload["confidence_level"]
                ),
                bootstrap_group_column=str(
                    bootstrap_payload["group_column"]
                ),
                bootstrap_random_seed=int(bootstrap_payload["random_seed"]),
            ),
            safety=dict(payload["safety"]),
            fingerprint=hashlib.sha256(
                canonical_json(payload).encode("utf-8")
            ).hexdigest(),
        )
    except GbdtConfigError:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise GbdtConfigError("Malformed GBDT baseline config.") from error

    if not set(config.selection.recent_fold_ids).issubset(
        {fold.fold_id for fold in config.folds}
    ):
        raise GbdtConfigError(
            "selection.recent_fold_ids must be a subset of the declared folds."
        )
    if not set(config.q4_readiness.references).issubset(
        {"canonical_b0", "frozen_b1"}
    ):
        raise GbdtConfigError(
            "q4_readiness.references must be drawn from the pinned M4B.5 columns."
        )
    if verify_local_artifacts:
        for check_path, expected_hash, label in (
            (config.corpus_config_path, config.corpus_config_sha256, "corpus config"),
            (config.m4b5_manifest_path, config.m4b5_manifest_sha256, "M4B.5 manifest"),
            (
                config.m4b5_development_predictions_path,
                config.m4b5_development_predictions_sha256,
                "M4B.5 development predictions",
            ),
            (
                config.m4b5_q4_predictions_path,
                config.m4b5_q4_predictions_sha256,
                "M4B.5 Q4 predictions",
            ),
        ):
            if not check_path.is_file() or sha256_file(check_path) != expected_hash:
                raise GbdtConfigError(f"The pinned {label} artifact changed.")
    return config


__all__ = [
    "CONFIG_SCHEMA_VERSION",
    "EarlyStoppingPolicy",
    "GbdtBaselineConfig",
    "GbdtCandidateSpec",
    "GbdtConfigError",
    "GbdtEstimatorPolicy",
    "GbdtEvaluationPolicy",
    "Q4ReadinessPolicy",
    "SelectionPolicy",
    "canonical_json",
    "load_gbdt_baseline_config",
]
