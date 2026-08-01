"""Offline orchestration for the bounded M4B.5 team-context recovery gate.

The runner evaluates exactly one added signal: a causal pre-series Elo logit.
It opens development components first, opens 2025-Q4 only after development
qualification, and never opens the locked 2026-Q1 supervised component.
"""

from __future__ import annotations

import hashlib
import json
import platform
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import scipy
import sklearn
from scipy.sparse import csr_matrix, hstack
from sklearn.linear_model import LogisticRegression

from .features import DraftFeatureTransformer, FeatureVariant
from .loader import (
    CorpusValidationError,
    load_working_corpus_prefix,
    sha256_file,
)
from .team_context_config import (
    TeamContextExperimentConfig,
    load_team_context_experiment_config,
)
from .team_context_selection import (
    TeamContextSelectionError,
    evaluate_team_context_development,
    evaluate_team_context_q4_readiness,
)
from .team_strength import (
    TeamStrengthPolicy,
    build_training_team_strength,
    transform_frozen_team_strength,
)


EXPERIMENT_SCHEMA_VERSION = "draft-ai-team-context-experiment-run-v1"
PREDICTION_SCHEMA_VERSION = "draft-ai-team-context-predictions-v1"
_SORT_COLUMNS = (
    "match_start_utc",
    "source_match_id",
    "game_index",
    "sample_id",
)


class TeamContextExperimentError(ValueError):
    """Raised when the bounded experiment crosses its frozen contract."""


@dataclass(frozen=True, slots=True)
class TeamContextExperimentResult:
    """Paths and decisions from one content-addressed M4B.5 run."""

    build_fingerprint: str
    output_directory: Path
    development_qualified: bool
    q4_opened: bool
    q4_readiness_passed: bool | None
    manifest_path: Path
    development_predictions_path: Path
    development_evaluation_path: Path
    q4_predictions_path: Path | None
    q4_readiness_path: Path | None
    audit_path: Path
    report_path: Path


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TeamContextExperimentError(f"Cannot read {label}.") from error
    if not isinstance(payload, dict):
        raise TeamContextExperimentError(f"{label} must be a JSON object.")
    return payload


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_parquet(frame: pd.DataFrame, path: Path) -> None:
    with duckdb.connect() as connection:
        connection.register("artifact_frame", frame)
        escaped = path.resolve().as_posix().replace("'", "''")
        connection.execute(
            "COPY (SELECT * FROM artifact_frame) "
            f"TO '{escaped}' (FORMAT PARQUET, COMPRESSION ZSTD)"
        )


def _artifact(path: Path) -> dict[str, object]:
    return {
        "file": path.name,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _source_sha256() -> str:
    root = Path(__file__).resolve().parent
    names = (
        "calibration.py",
        "features.py",
        "loader.py",
        "team_context_config.py",
        "team_context_experiment.py",
        "team_context_selection.py",
        "team_strength.py",
    )
    digest = hashlib.sha256()
    for name in names:
        path = root / name
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _runtime_versions() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "duckdb": duckdb.__version__,
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "scipy": scipy.__version__,
        "scikit_learn": sklearn.__version__,
    }


def _team_policy(config: TeamContextExperimentConfig) -> TeamStrengthPolicy:
    payload = config.payload["team_strength"]
    return TeamStrengthPolicy(
        initial_rating=float(payload["initial_rating"]),
        rating_scale=float(payload["rating_scale"]),
        k_factor=float(payload["k_factor"]),
    )


def _new_estimator(config: TeamContextExperimentConfig) -> LogisticRegression:
    policy = config.payload["candidate"]["estimator"]
    return LogisticRegression(
        C=float(policy["C"]),
        class_weight=policy["class_weight"],
        max_iter=int(policy["max_iter"]),
        penalty=str(policy["penalty"]),
        random_state=int(policy["random_seed"]),
        solver=str(policy["solver"]),
    )


def _fit_estimator(
    estimator: LogisticRegression,
    matrix: csr_matrix,
    targets: np.ndarray,
) -> None:
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="'penalty' was deprecated in version 1.8",
            category=FutureWarning,
            module=r"sklearn\.linear_model\._logistic",
        )
        estimator.fit(matrix, targets)


def _positive_probabilities(
    estimator: LogisticRegression,
    matrix: csr_matrix,
) -> np.ndarray:
    classes = list(estimator.classes_)
    if 1 not in classes:
        raise TeamContextExperimentError(
            "A team-context estimator lacks the positive class."
        )
    probabilities = np.asarray(
        estimator.predict_proba(matrix)[:, classes.index(1)],
        dtype=np.float64,
    )
    if (
        probabilities.shape != (matrix.shape[0],)
        or not np.isfinite(probabilities).all()
        or ((probabilities <= 0) | (probabilities >= 1)).any()
    ):
        raise TeamContextExperimentError(
            "A team-context estimator produced invalid probabilities."
        )
    return probabilities


def _elo_vector(
    rows: pd.DataFrame,
    features: pd.DataFrame,
) -> np.ndarray:
    required = {"sample_id", "elo_logit"}
    missing = sorted(required.difference(features.columns))
    if missing:
        raise TeamContextExperimentError(
            "Team-strength output is missing columns: " + ", ".join(missing)
        )
    aligned = rows[["sample_id"]].merge(
        features[["sample_id", "elo_logit"]],
        on="sample_id",
        how="left",
        validate="one_to_one",
    )
    values = pd.to_numeric(aligned["elo_logit"], errors="coerce").to_numpy(
        dtype=np.float64
    )
    if len(values) != len(rows) or not np.isfinite(values).all():
        raise TeamContextExperimentError(
            "Team-strength features do not align with modeling rows."
        )
    return values


def _fit_two_models(
    fit_rows: pd.DataFrame,
    evaluation_rows_without_target: pd.DataFrame,
    fit_elo: np.ndarray,
    evaluation_elo: np.ndarray,
    config: TeamContextExperimentConfig,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    transformer = DraftFeatureTransformer(
        FeatureVariant.B1_PICK_PRESENCE
    ).fit(fit_rows)
    fit_draft = transformer.transform(fit_rows)
    evaluation_draft = transformer.transform(evaluation_rows_without_target)
    fit_team = csr_matrix(fit_elo.reshape(-1, 1))
    evaluation_team = csr_matrix(evaluation_elo.reshape(-1, 1))
    fit_joint = hstack([fit_draft, fit_team], format="csr")
    evaluation_joint = hstack(
        [evaluation_draft, evaluation_team],
        format="csr",
    )
    targets = fit_rows["radiant_win"].astype("int8").to_numpy()
    joint = _new_estimator(config)
    team_only = _new_estimator(config)
    _fit_estimator(joint, fit_joint, targets)
    _fit_estimator(team_only, fit_team, targets)
    joint_probabilities = _positive_probabilities(joint, evaluation_joint)
    team_probabilities = _positive_probabilities(
        team_only,
        evaluation_team,
    )
    return joint_probabilities, team_probabilities, {
        "fit_rows": len(fit_rows),
        "evaluation_rows": len(evaluation_rows_without_target),
        "draft_feature_columns": fit_draft.shape[1],
        "joint_feature_columns": fit_joint.shape[1],
        "feature_fingerprint": transformer.fingerprint,
        "joint_elo_coefficient": float(joint.coef_[0, -1]),
        "team_only_elo_coefficient": float(team_only.coef_[0, 0]),
        "joint_intercept": float(joint.intercept_[0]),
        "team_only_intercept": float(team_only.intercept_[0]),
    }


def _load_development_references(
    config: TeamContextExperimentConfig,
) -> pd.DataFrame:
    candidate_id = config.payload["source"]["m4b2"]["candidate_id"]
    with duckdb.connect() as connection:
        reference = connection.execute(
            "SELECT evaluation_id, sample_id, source_match_id, radiant_win, "
            "candidate_probability AS frozen_b1_probability, "
            "canonical_b0_probability "
            "FROM read_parquet(?) WHERE candidate_id = ? "
            "ORDER BY evaluation_id, sample_id",
            [
                str(config.source_paths["m4b2_predictions"]),
                candidate_id,
            ],
        ).fetchdf()
    selection = _read_json(
        config.source_paths["m4b2_selection"],
        label="M4B.2 selection",
    )
    if selection.get("selected_candidate_id") != candidate_id:
        raise TeamContextExperimentError(
            "The pinned M4B.2 candidate selection changed."
        )
    if len(reference) != 12_897:
        raise TeamContextExperimentError(
            "The pinned M4B.2 development coverage changed."
        )
    return reference


def _aligned_reference(
    evaluation_rows: pd.DataFrame,
    reference_rows: pd.DataFrame,
    *,
    evaluation_id: str,
) -> pd.DataFrame:
    selected = reference_rows[
        reference_rows["evaluation_id"] == evaluation_id
    ].copy()
    aligned = evaluation_rows[
        ["sample_id", "source_match_id", "radiant_win"]
    ].merge(
        selected,
        on="sample_id",
        how="left",
        validate="one_to_one",
        suffixes=("_source", "_reference"),
    )
    if (
        len(aligned) != len(evaluation_rows)
        or aligned["evaluation_id"].isna().any()
        or not aligned["source_match_id_source"].astype(str).equals(
            aligned["source_match_id_reference"].astype(str)
        )
        or not np.array_equal(
            aligned["radiant_win_source"].astype("int8").to_numpy(),
            aligned["radiant_win_reference"].astype("int8").to_numpy(),
        )
    ):
        raise TeamContextExperimentError(
            f"The pinned reference does not align for {evaluation_id}."
        )
    return aligned


def _development_predictions(
    frame: pd.DataFrame,
    references: pd.DataFrame,
    config: TeamContextExperimentConfig,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    policy = _team_policy(config)
    predictions: list[pd.DataFrame] = []
    audits: list[dict[str, Any]] = []
    for fold_id, train_end, evaluation_end in config.folds:
        fit = frame[
            (frame["match_start_utc"] >= pd.Timestamp(config.history_start_utc))
            & (frame["match_start_utc"] < pd.Timestamp(train_end))
        ].copy()
        evaluation = frame[
            (frame["match_start_utc"] >= pd.Timestamp(train_end))
            & (frame["match_start_utc"] < pd.Timestamp(evaluation_end))
        ].copy()
        if fit.empty or evaluation.empty:
            raise TeamContextExperimentError(
                f"The {fold_id} fit or evaluation window is empty."
            )
        fit_groups = set(fit["source_match_id"].astype(str))
        evaluation_groups = set(evaluation["source_match_id"].astype(str))
        if fit_groups.intersection(evaluation_groups):
            raise TeamContextExperimentError(
                f"A source match crosses the {fold_id} boundary."
            )

        history = build_training_team_strength(fit, policy=policy)
        frozen = transform_frozen_team_strength(
            evaluation.drop(columns=["radiant_win"]),
            history.state,
            policy=policy,
        )
        fit_elo = _elo_vector(fit, history.features)
        evaluation_elo = _elo_vector(evaluation, frozen.features)
        joint, team_only, model_audit = _fit_two_models(
            fit,
            evaluation.drop(columns=["radiant_win"]),
            fit_elo,
            evaluation_elo,
            config,
        )
        aligned = _aligned_reference(
            evaluation,
            references,
            evaluation_id=fold_id,
        )
        predictions.append(
            pd.DataFrame(
                {
                    "evaluation_id": fold_id,
                    "sample_id": evaluation["sample_id"].astype(str).to_numpy(),
                    "source_match_id": evaluation[
                        "source_match_id"
                    ].astype(str).to_numpy(),
                    "match_start_utc": evaluation[
                        "match_start_utc"
                    ].to_numpy(),
                    "patch": evaluation["patch"].astype("string").to_numpy(),
                    "radiant_win": evaluation[
                        "radiant_win"
                    ].astype("int8").to_numpy(),
                    "elo_logit": evaluation_elo,
                    "joint_probability": joint,
                    "team_only_probability": team_only,
                    "frozen_b1_probability": aligned[
                        "frozen_b1_probability"
                    ].to_numpy(dtype=np.float64),
                    "canonical_b0_probability": aligned[
                        "canonical_b0_probability"
                    ].to_numpy(dtype=np.float64),
                }
            )
        )
        audits.append(
            {
                "evaluation_id": fold_id,
                "fit_end_utc_exclusive": train_end.isoformat(),
                "evaluation_end_utc_exclusive": evaluation_end.isoformat(),
                "fit_source_matches": len(fit_groups),
                "evaluation_source_matches": len(evaluation_groups),
                "team_strength_history": history.audit.to_payload(),
                "team_strength_evaluation": frozen.audit.to_payload(),
                "model": model_audit,
                "evaluation_target_passed_to_team_transform": False,
            }
        )
    return (
        pd.concat(predictions, ignore_index=True).sort_values(
            ["evaluation_id", "sample_id"],
            kind="stable",
        ).reset_index(drop=True),
        audits,
    )


def _verify_q4_prediction_pin(config: TeamContextExperimentConfig) -> None:
    expected = str(
        config.payload["source"]["m4b3"]["predictions_sha256"]
    )
    path = config.source_paths["m4b3_predictions"]
    if not path.is_file() or sha256_file(path) != expected:
        raise TeamContextExperimentError(
            "The deferred M4B.3 Q4 prediction artifact changed."
        )


def _load_q4_reference(
    config: TeamContextExperimentConfig,
) -> pd.DataFrame:
    _verify_q4_prediction_pin(config)
    method = config.payload["source"]["m4b3"]["raw_method"]
    with duckdb.connect() as connection:
        reference = connection.execute(
            "SELECT sample_id, source_match_id, radiant_win, "
            "radiant_win_probability AS frozen_b1_probability "
            "FROM read_parquet(?) WHERE calibration_method = ? "
            "ORDER BY sample_id",
            [str(config.source_paths["m4b3_predictions"]), method],
        ).fetchdf()
    expected = config.payload["data_boundaries"]["expected"]
    if (
        len(reference) != int(expected["q4_rows"])
        or reference["source_match_id"].nunique()
        != int(expected["q4_source_matches"])
    ):
        raise TeamContextExperimentError("The M4B.3 Q4 coverage changed.")
    return reference


def _q4_predictions(
    base: pd.DataFrame,
    q4: pd.DataFrame,
    config: TeamContextExperimentConfig,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    policy = _team_policy(config)
    history = build_training_team_strength(base, policy=policy)
    q4_without_target = q4.drop(columns=["radiant_win"])
    frozen = transform_frozen_team_strength(
        q4_without_target,
        history.state,
        policy=policy,
    )
    base_elo = _elo_vector(base, history.features)
    q4_elo = _elo_vector(q4, frozen.features)
    joint, team_only, model_audit = _fit_two_models(
        base,
        q4_without_target,
        base_elo,
        q4_elo,
        config,
    )

    # The Q4 reference, including labels, is deliberately opened only after
    # the feature transform and probability vectors already exist.
    reference = _load_q4_reference(config)
    aligned = q4[
        ["sample_id", "source_match_id", "radiant_win"]
    ].merge(
        reference,
        on="sample_id",
        how="left",
        validate="one_to_one",
        suffixes=("_source", "_reference"),
    )
    if (
        len(aligned) != len(q4)
        or aligned["frozen_b1_probability"].isna().any()
        or not aligned["source_match_id_source"].astype(str).equals(
            aligned["source_match_id_reference"].astype(str)
        )
        or not np.array_equal(
            aligned["radiant_win_source"].astype("int8").to_numpy(),
            aligned["radiant_win_reference"].astype("int8").to_numpy(),
        )
    ):
        raise TeamContextExperimentError(
            "The Q4 source and M4B.3 reference do not align."
        )
    prior = float(base["radiant_win"].astype("int8").mean())
    prior_evidence = _read_json(
        config.source_paths["m4b3_readiness"],
        label="M4B.3 readiness evidence",
    )
    if abs(float(prior_evidence.get("base_prior")) - prior) > 1e-15:
        raise TeamContextExperimentError(
            "The pinned M4B.3 empirical prior changed."
        )
    predictions = pd.DataFrame(
        {
            "evaluation_id": "2025-Q4",
            "sample_id": q4["sample_id"].astype(str).to_numpy(),
            "source_match_id": q4[
                "source_match_id"
            ].astype(str).to_numpy(),
            "match_start_utc": q4["match_start_utc"].to_numpy(),
            "patch": q4["patch"].astype("string").to_numpy(),
            "radiant_win": q4["radiant_win"].astype("int8").to_numpy(),
            "elo_logit": q4_elo,
            "joint_probability": joint,
            "team_only_probability": team_only,
            "frozen_b1_probability": aligned[
                "frozen_b1_probability"
            ].to_numpy(dtype=np.float64),
            "canonical_b0_probability": prior,
        }
    )
    return predictions, {
        "fit_rows": len(base),
        "fit_source_matches": int(base["source_match_id"].nunique()),
        "evaluation_rows": len(q4),
        "evaluation_source_matches": int(q4["source_match_id"].nunique()),
        "team_strength_history": history.audit.to_payload(),
        "team_strength_evaluation": frozen.audit.to_payload(),
        "model": model_audit,
        "evaluation_target_passed_to_team_transform": False,
        "q4_reference_opened_after_predictions": True,
    }


def _render_report(
    *,
    fingerprint: str,
    development: dict[str, Any],
    q4: dict[str, Any] | None,
    safety: dict[str, Any],
) -> str:
    recent = development["metrics"]["recent_pooled"]
    rows = [
        "# Milestone 4B.5: Team Context Recovery Gate",
        "",
        f"- Build fingerprint: `{fingerprint}`",
        "- Candidate: `B1 pick presence + one pre-series Elo logit`",
        "- Hyperparameter search: `none`",
        (
            "- Development qualification: "
            f"`{'passed' if development['qualified'] else 'failed'}`"
        ),
        (
            "- 2025-Q4 readiness: "
            + (
                "`not opened`"
                if q4 is None
                else f"`{'passed' if q4['passed'] else 'failed'}`"
            )
        ),
        "- Locked 2026-Q1 component rows opened: `0`",
        "- Authenticated API requests: `0`",
        "",
        "## Pooled 2025-Q1 through Q3",
        "",
        "| Model | Log loss | Brier score |",
        "| --- | ---: | ---: |",
    ]
    for model in ("joint", "team_only", "frozen_b1", "canonical_b0"):
        metrics = recent[model]
        rows.append(
            f"| {model} | {metrics['log_loss']:.6f} | "
            f"{metrics['brier_score']:.6f} |"
        )
    if q4 is not None:
        rows.extend(
            [
                "",
                "## 2025-Q4 readiness",
                "",
                "| Model | Log loss | Brier score |",
                "| --- | ---: | ---: |",
            ]
        )
        for model in ("joint", "team_only", "frozen_b1", "canonical_b0"):
            metrics = q4["metrics"][model]
            rows.append(
                f"| {model} | {metrics['log_loss']:.6f} | "
                f"{metrics['brier_score']:.6f} |"
            )
    rows.extend(
        [
            "",
            "Pre-2024 games are rating warm-up only. Selection evidence comes "
            "from 2025 development games; the locked test remains sealed.",
            "",
            "The team-only comparison is mandatory: the combined candidate "
            "cannot qualify unless draft picks add clear incremental value.",
            "",
            f"Safety audit fingerprint: `{_sha256_json(safety)}`",
            "",
        ]
    )
    return "\n".join(rows)


def _result_from_existing(
    target: Path,
    manifest: dict[str, Any],
) -> TeamContextExperimentResult:
    artifacts = manifest["artifacts"]
    for artifact in artifacts.values():
        path = target / str(artifact["file"])
        if not path.is_file() or sha256_file(path) != artifact["sha256"]:
            raise TeamContextExperimentError(
                "An existing M4B.5 artifact changed."
            )
    result = manifest["result"]
    q4_opened = bool(result["q4_opened"])
    return TeamContextExperimentResult(
        build_fingerprint=str(manifest["build_fingerprint"]),
        output_directory=target,
        development_qualified=bool(result["development_qualified"]),
        q4_opened=q4_opened,
        q4_readiness_passed=(
            bool(result["q4_readiness_passed"]) if q4_opened else None
        ),
        manifest_path=target / "experiment_manifest.json",
        development_predictions_path=target
        / "development_predictions.parquet",
        development_evaluation_path=target
        / "development_evaluation.json",
        q4_predictions_path=(
            target / "q4_predictions.parquet" if q4_opened else None
        ),
        q4_readiness_path=(
            target / "q4_readiness.json" if q4_opened else None
        ),
        audit_path=target / "team_strength_audit.json",
        report_path=target / "report.md",
    )


def run_team_context_experiment(
    experiment_config_path: Path,
    *,
    output_root: Path = Path("models/m4b5"),
    repository_root: Path | None = None,
) -> TeamContextExperimentResult:
    """Run the fixed development gate and conditionally evaluate 2025-Q4."""

    root = (
        repository_root.resolve()
        if repository_root is not None
        else Path(__file__).resolve().parents[2]
    )
    config = load_team_context_experiment_config(
        experiment_config_path.resolve(),
        repository_root=root,
        verify_artifacts=True,
        verify_q4_predictions=False,
    )
    source = config.payload["source"]
    core = {
        "experiment_schema_version": EXPERIMENT_SCHEMA_VERSION,
        "prediction_schema_version": PREDICTION_SCHEMA_VERSION,
        "experiment_id": config.payload["experiment_id"],
        "config_fingerprint": config.fingerprint,
        "config_sha256": sha256_file(config.config_path),
        "modeling_source_sha256": _source_sha256(),
        "source": {
            "corpus_id": source["corpus_id"],
            "corpus_config_sha256": source["corpus_config_sha256"],
            "split_manifest_fingerprint": source[
                "split_manifest_fingerprint"
            ],
            "m4b2_build_fingerprint": source["m4b2"][
                "build_fingerprint"
            ],
            "m4b2_predictions_sha256": source["m4b2"][
                "predictions_sha256"
            ],
            "m4b3_build_fingerprint": source["m4b3"][
                "build_fingerprint"
            ],
            "m4b3_predictions_sha256": source["m4b3"][
                "predictions_sha256"
            ],
        },
        "team_strength": config.payload["team_strength"],
        "candidate": config.payload["candidate"],
        "selection": config.payload["selection"],
        "q4_readiness": config.payload["q4_readiness"],
        "safety": config.payload["safety"],
        "runtime_versions": _runtime_versions(),
    }
    fingerprint = _sha256_json(core)
    target = output_root.resolve() / f"build_{fingerprint}"
    manifest_path = target / "experiment_manifest.json"
    if target.exists():
        manifest = _read_json(manifest_path, label="M4B.5 manifest")
        if manifest.get("build_fingerprint") != fingerprint:
            raise TeamContextExperimentError(
                "Existing M4B.5 build fingerprint changed."
            )
        return _result_from_existing(target, manifest)

    development_prefix = load_working_corpus_prefix(
        config.source_paths["corpus_config"],
        end_utc=config.development_end_utc,
        repository_root=root,
    )
    expected = config.payload["data_boundaries"]["expected"]
    if (
        len(development_prefix.frame)
        != int(expected["development_source_rows"])
        or "2025-Q4" in development_prefix.verified_component_ids
        or "2026-Q1" in development_prefix.verified_component_ids
    ):
        raise TeamContextExperimentError(
            "The development-only corpus boundary changed."
        )
    references = _load_development_references(config)
    development_predictions, fold_audits = _development_predictions(
        development_prefix.frame,
        references,
        config,
    )
    bootstrap = config.payload["evaluation"]["paired_group_bootstrap"]
    development_evaluation = evaluate_team_context_development(
        development_predictions,
        n_resamples=int(bootstrap["replicates"]),
        random_state=int(bootstrap["random_seed"]),
        confidence_level=float(bootstrap["confidence_level"]),
        minimum_recent_log_loss_improvement=float(
            config.payload["selection"][
                "minimum_pooled_log_loss_improvement_vs_b1"
            ]
        ),
        maximum_single_fold_log_loss_regression=float(
            config.payload["selection"][
                "maximum_single_fold_log_loss_regression"
            ]
        ),
    )

    q4_predictions: pd.DataFrame | None = None
    q4_evaluation: dict[str, Any] | None = None
    q4_audit: dict[str, Any] | None = None
    q4_prefix_ids: tuple[str, ...] = ()
    if development_evaluation["qualified"]:
        q4_prefix = load_working_corpus_prefix(
            config.source_paths["corpus_config"],
            end_utc=config.q4_end_utc,
            repository_root=root,
        )
        q4_prefix_ids = q4_prefix.verified_component_ids
        if "2026-Q1" in q4_prefix_ids:
            raise TeamContextExperimentError(
                "The locked 2026-Q1 component was opened."
            )
        base = q4_prefix.frame[
            q4_prefix.frame["match_start_utc"]
            < pd.Timestamp(config.development_end_utc)
        ].copy()
        q4 = q4_prefix.frame[
            (q4_prefix.frame["match_start_utc"]
             >= pd.Timestamp(config.development_end_utc))
            & (
                q4_prefix.frame["match_start_utc"]
                < pd.Timestamp(config.q4_end_utc)
            )
        ].copy()
        if (
            len(base) != int(expected["development_source_rows"])
            or len(q4) != int(expected["q4_rows"])
            or q4["source_match_id"].nunique()
            != int(expected["q4_source_matches"])
        ):
            raise TeamContextExperimentError("The Q4 role counts changed.")
        q4_predictions, q4_audit = _q4_predictions(base, q4, config)
        q4_evaluation = evaluate_team_context_q4_readiness(
            q4_predictions,
            n_resamples=int(bootstrap["replicates"]),
            random_state=int(bootstrap["random_seed"]),
            confidence_level=float(bootstrap["confidence_level"]),
        )

    safety_audit = {
        "development_component_ids_opened": list(
            development_prefix.verified_component_ids
        ),
        "q4_component_ids_opened": list(q4_prefix_ids),
        "q4_opened_only_after_development_qualification": bool(
            q4_evaluation is not None
            and development_evaluation["qualified"]
        )
        if development_evaluation["qualified"]
        else True,
        "locked_component_id": "2026-Q1",
        "locked_component_opened": False,
        "locked_target_rows_used": 0,
        "locked_transform_rows": 0,
        "locked_prediction_rows": 0,
        "authenticated_api_requests": 0,
        "acquisition_or_raw_cache_dependency": False,
        "evaluation_target_passed_to_team_transform": False,
        "q4_reference_opened": q4_evaluation is not None,
        "model_bundle_serialized": False,
    }
    audits = {
        "team_strength_policy": config.payload["team_strength"],
        "development_folds": fold_audits,
        "q4": q4_audit,
        "safety": safety_audit,
    }

    target.mkdir(parents=True)
    paths = {
        "development_predictions": target
        / "development_predictions.parquet",
        "development_evaluation": target / "development_evaluation.json",
        "audit": target / "team_strength_audit.json",
        "report": target / "report.md",
    }
    _write_parquet(
        development_predictions,
        paths["development_predictions"],
    )
    _write_json(paths["development_evaluation"], development_evaluation)
    _write_json(paths["audit"], audits)
    if q4_predictions is not None and q4_evaluation is not None:
        paths["q4_predictions"] = target / "q4_predictions.parquet"
        paths["q4_readiness"] = target / "q4_readiness.json"
        _write_parquet(q4_predictions, paths["q4_predictions"])
        _write_json(paths["q4_readiness"], q4_evaluation)
    paths["report"].write_text(
        _render_report(
            fingerprint=fingerprint,
            development=development_evaluation,
            q4=q4_evaluation,
            safety=safety_audit,
        ),
        encoding="utf-8",
    )
    artifacts = {
        name: _artifact(path)
        for name, path in paths.items()
    }
    manifest = {
        **core,
        "build_fingerprint": fingerprint,
        "result": {
            "development_qualified": bool(
                development_evaluation["qualified"]
            ),
            "q4_opened": q4_evaluation is not None,
            "q4_readiness_passed": (
                bool(q4_evaluation["passed"])
                if q4_evaluation is not None
                else None
            ),
            "locked_test_ready_for_separate_approval": bool(
                q4_evaluation is not None and q4_evaluation["passed"]
            ),
            "product_candidate_changed": False,
        },
        "safety_audit": safety_audit,
        "artifacts": artifacts,
    }
    _write_json(manifest_path, manifest)
    return _result_from_existing(target, manifest)


__all__ = [
    "EXPERIMENT_SCHEMA_VERSION",
    "PREDICTION_SCHEMA_VERSION",
    "TeamContextExperimentError",
    "TeamContextExperimentResult",
    "run_team_context_experiment",
]
