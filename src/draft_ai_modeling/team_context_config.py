"""Strict local contract for the bounded M4B.5 team-context experiment."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .loader import sha256_file


CONFIG_SCHEMA_VERSION = "draft-ai-team-context-experiment-v1"
EXPERIMENT_ID = "m4b5-team-context-recovery-gate-v1"
EXPECTED_FOLD_BOUNDARIES = (
    ("2024-Q1", "2024-01-01T00:00:00Z", "2024-04-01T00:00:00Z"),
    ("2024-Q2", "2024-04-01T00:00:00Z", "2024-07-01T00:00:00Z"),
    ("2024-Q3", "2024-07-01T00:00:00Z", "2024-10-01T00:00:00Z"),
    ("2024-Q4", "2024-10-01T00:00:00Z", "2025-01-01T00:00:00Z"),
    ("2025-Q1", "2025-01-01T00:00:00Z", "2025-04-01T00:00:00Z"),
    ("2025-Q2", "2025-04-01T00:00:00Z", "2025-07-01T00:00:00Z"),
    ("2025-Q3", "2025-07-01T00:00:00Z", "2025-10-01T00:00:00Z"),
)
EXPECTED_TEAM_STRENGTH = {
    "feature": "elo_logit",
    "initial_rating": 1500.0,
    "rating_scale": 400.0,
    "k_factor": 32.0,
    "radiant_advantage": 0.0,
    "decay": None,
    "update_unit": "source_match_series_mean_game_score",
    "same_timestamp_policy": "read_pre_batch_then_apply_all_updates",
    "evaluation_policy": "freeze_at_fit_cutoff",
    "unknown_team_policy": "initial_rating",
    "team_alias_inference": False,
}
EXPECTED_ESTIMATOR = {
    "family": "logistic_regression",
    "penalty": "l2",
    "C": 0.01,
    "solver": "liblinear",
    "class_weight": None,
    "max_iter": 2000,
    "random_seed": 42,
}
EXPECTED_SAFETY = {
    "api_dependency": False,
    "acquisition_dependency": False,
    "raw_cache_dependency": False,
    "authenticated_api_requests": 0,
    "hyperparameter_search": False,
    "raw_team_identity_features": False,
    "roster_inference": False,
    "tournament_features": False,
    "patch_features": False,
    "q4_open_only_after_development_qualification": True,
    "locked_component_open": False,
    "locked_test_target_use": False,
    "locked_test_transform": False,
    "locked_test_predictions": False,
    "model_bundle_serialization": False,
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class TeamContextConfigError(ValueError):
    """Raised when the fixed M4B.5 experiment contract drifts."""


@dataclass(frozen=True, slots=True)
class TeamContextExperimentConfig:
    """Resolved credential-free M4B.5 configuration."""

    config_path: Path
    repository_root: Path
    payload: dict[str, Any]
    source_paths: dict[str, Path]
    fingerprint: str

    @property
    def development_end_utc(self) -> datetime:
        return _utc(
            self.payload["data_boundaries"][
                "development_end_utc_exclusive"
            ]
        )

    @property
    def q4_end_utc(self) -> datetime:
        return _utc(
            self.payload["data_boundaries"]["q4_end_utc_exclusive"]
        )

    @property
    def history_start_utc(self) -> datetime:
        return _utc(
            self.payload["data_boundaries"]["history_start_utc"]
        )

    @property
    def folds(self) -> tuple[tuple[str, datetime, datetime], ...]:
        return tuple(
            (
                str(fold["fold_id"]),
                _utc(fold["train_end_utc"]),
                _utc(fold["evaluation_end_utc"]),
            )
            for fold in self.payload["rolling_origin_folds"]
        )


def canonical_json(value: object) -> str:
    """Return the stable representation used by the config fingerprint."""

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise TeamContextConfigError("M4B.5 timestamps must include an offset.")
    return parsed.astimezone(UTC)


def _root(config_path: Path) -> Path:
    for candidate in config_path.parents:
        if (candidate / "src" / "draft_ai_modeling").is_dir():
            return candidate.resolve()
    raise TeamContextConfigError("Could not discover the repository root.")


def _path(root: Path, value: object, *, label: str) -> Path:
    relative = Path(str(value))
    if relative.is_absolute() or ".." in relative.parts:
        raise TeamContextConfigError(f"{label} must be repository-relative.")
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise TeamContextConfigError(f"{label} escapes the repository.") from error
    return resolved


def _require_sha256(value: object, *, label: str) -> str:
    text = str(value)
    if _SHA256.fullmatch(text) is None:
        raise TeamContextConfigError(f"{label} must be a SHA-256 digest.")
    return text


def _expect_equal(
    observed: object,
    expected: object,
    *,
    label: str,
) -> None:
    if observed != expected:
        raise TeamContextConfigError(f"The fixed {label} contract changed.")


def _validate_payload(payload: dict[str, Any]) -> None:
    _expect_equal(
        payload.get("schema_version"),
        CONFIG_SCHEMA_VERSION,
        label="schema version",
    )
    _expect_equal(
        payload.get("experiment_id"),
        EXPERIMENT_ID,
        label="experiment identity",
    )
    _expect_equal(
        payload.get("team_strength"),
        EXPECTED_TEAM_STRENGTH,
        label="team-strength feature",
    )
    candidate = payload.get("candidate", {})
    _expect_equal(
        candidate.get("candidate_id"),
        "b1_plus_pre_series_elo_c0p01",
        label="candidate identity",
    )
    _expect_equal(
        candidate.get("representation"),
        "b1-pick-presence-plus-one-elo-logit",
        label="candidate representation",
    )
    _expect_equal(
        candidate.get("draft_feature_variant"),
        "b1-pick-presence",
        label="draft representation",
    )
    _expect_equal(
        candidate.get("estimator"),
        EXPECTED_ESTIMATOR,
        label="estimator",
    )
    _expect_equal(
        payload.get("safety"),
        EXPECTED_SAFETY,
        label="safety",
    )

    boundaries = payload.get("data_boundaries", {})
    if (
        _utc(boundaries.get("history_start_utc", ""))
        != datetime(2022, 1, 1, tzinfo=UTC)
        or _utc(boundaries.get("development_end_utc_exclusive", ""))
        != datetime(2025, 10, 1, tzinfo=UTC)
        or _utc(boundaries.get("q4_end_utc_exclusive", ""))
        != datetime(2026, 1, 1, tzinfo=UTC)
        or _utc(boundaries.get("locked_test_start_utc", ""))
        != datetime(2026, 1, 1, tzinfo=UTC)
    ):
        raise TeamContextConfigError("The fixed temporal boundary changed.")
    _expect_equal(
        boundaries.get("expected"),
        {
            "development_source_rows": 20087,
            "q4_rows": 1089,
            "q4_source_matches": 523,
            "locked_component_rows_opened": 0,
        },
        label="row-count",
    )

    folds = tuple(
        (
            fold.get("fold_id"),
            fold.get("train_end_utc"),
            fold.get("evaluation_end_utc"),
        )
        for fold in payload.get("rolling_origin_folds", ())
    )
    _expect_equal(folds, EXPECTED_FOLD_BOUNDARIES, label="rolling-fold")

    selection = payload.get("selection", {})
    _expect_equal(
        selection,
        {
            "recent_fold_ids": ["2025-Q1", "2025-Q2", "2025-Q3"],
            "minimum_pooled_log_loss_improvement_vs_b1": 0.002,
            "require_lower_brier_score_vs_b1": True,
            "require_each_recent_fold_lower_than": [
                "frozen_b1",
                "canonical_b0",
            ],
            "require_paired_upper_bound_below_zero_vs": [
                "frozen_b1",
                "team_only",
            ],
            "require_draft_incremental_value_vs_team_only": True,
            "seven_fold_mean_log_loss_no_worse_than_b1": True,
            "maximum_single_fold_log_loss_regression": 0.01,
        },
        label="selection",
    )
    _expect_equal(
        payload.get("q4_readiness"),
        {
            "references": ["canonical_b0", "frozen_b1", "team_only"],
            "metrics": ["log_loss", "brier_score"],
            "require_candidate_minus_reference_point_below": 0.0,
            "require_candidate_minus_reference_upper_bound_below": 0.0,
        },
        label="Q4 readiness",
    )
    _expect_equal(
        payload.get("evaluation"),
        {
            "reliability_bins": 10,
            "paired_group_bootstrap": {
                "group_column": "source_match_id",
                "replicates": 1000,
                "confidence_level": 0.95,
                "random_seed": 42,
            },
        },
        label="evaluation",
    )


def load_team_context_experiment_config(
    config_path: Path,
    *,
    repository_root: Path | None = None,
    verify_artifacts: bool = True,
    verify_q4_predictions: bool = True,
) -> TeamContextExperimentConfig:
    """Load, validate, resolve, and optionally verify the fixed contract."""

    path = config_path.resolve()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TeamContextConfigError("Cannot read the M4B.5 config.") from error
    if not isinstance(payload, dict):
        raise TeamContextConfigError("The M4B.5 config must be an object.")
    try:
        _validate_payload(payload)
        source = payload["source"]
        m4b2 = source["m4b2"]
        m4b3 = source["m4b3"]
        root = (
            repository_root.resolve()
            if repository_root is not None
            else _root(path)
        )
        path_specs = {
            "corpus_config": (
                source["corpus_config_path"],
                source["corpus_config_sha256"],
            ),
            "split_manifest": (
                source["split_manifest_path"],
                source["split_manifest_sha256"],
            ),
            "m4b2_predictions": (
                m4b2["predictions_path"],
                m4b2["predictions_sha256"],
            ),
            "m4b2_selection": (
                m4b2["selection_path"],
                m4b2["selection_sha256"],
            ),
            "m4b3_predictions": (
                m4b3["predictions_path"],
                m4b3["predictions_sha256"],
            ),
            "m4b3_readiness": (
                m4b3["readiness_path"],
                m4b3["readiness_sha256"],
            ),
        }
        resolved: dict[str, Path] = {}
        for label, (path_value, digest_value) in path_specs.items():
            artifact_path = _path(root, path_value, label=label)
            digest = _require_sha256(digest_value, label=f"{label} hash")
            should_verify = verify_artifacts and (
                label != "m4b3_predictions" or verify_q4_predictions
            )
            if should_verify and (
                not artifact_path.is_file()
                or sha256_file(artifact_path) != digest
            ):
                raise TeamContextConfigError(
                    f"The pinned {label} artifact changed."
                )
            resolved[label] = artifact_path
    except TeamContextConfigError:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise TeamContextConfigError("Malformed M4B.5 configuration.") from error

    return TeamContextExperimentConfig(
        config_path=path,
        repository_root=root,
        payload=payload,
        source_paths=resolved,
        fingerprint=hashlib.sha256(
            canonical_json(payload).encode("utf-8")
        ).hexdigest(),
    )


__all__ = [
    "CONFIG_SCHEMA_VERSION",
    "EXPERIMENT_ID",
    "TeamContextConfigError",
    "TeamContextExperimentConfig",
    "canonical_json",
    "load_team_context_experiment_config",
]
