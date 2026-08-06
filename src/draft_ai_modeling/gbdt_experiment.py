"""Offline orchestration for the pre-registered GBDT baseline experiment.

The runner has two structurally separate entry points. `run_gbdt_selection_stage`
ranks the four pre-registered candidates on 2024-Q1 through 2025-Q3 only and
never loads a row at or after 2025-10-01. `run_gbdt_q4_gate` refits only the
candidate that stage selected and requires that stage's own result object as
an input, so Q4 cannot be opened without a completed selection run.
"""

from __future__ import annotations

import hashlib
import json
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import lightgbm as lgb
import numpy as np
import pandas as pd
import scipy
import sklearn
from scipy.sparse import csr_matrix

from .experiment_config import RollingOriginFold
from .features import DraftFeatureTransformer, FeatureVariant
from .gbdt_config import (
    GbdtBaselineConfig,
    GbdtCandidateSpec,
    canonical_json,
    load_gbdt_baseline_config,
)
from .gbdt_selection import evaluate_gbdt_q4_readiness, evaluate_gbdt_selection
from .loader import load_working_corpus_prefix, sha256_file


EXPERIMENT_SCHEMA_VERSION = "draft-ai-gbdt-baseline-experiment-run-v1"
PREDICTION_SCHEMA_VERSION = "draft-ai-gbdt-baseline-predictions-v1"


class GbdtExperimentError(ValueError):
    """Raised when the GBDT baseline experiment crosses its frozen contract."""


@dataclass(frozen=True, slots=True)
class GbdtSelectionStageResult:
    """Paths and decisions from the fold-based, Q4-blind selection stage."""

    build_fingerprint: str
    output_directory: Path
    selected_candidate_id: str
    selection_evaluation: dict[str, Any]
    fold_predictions_path: Path
    selection_evaluation_path: Path
    manifest_path: Path
    report_path: Path


@dataclass(frozen=True, slots=True)
class GbdtQ4GateResult:
    """Paths and decisions from the single selected candidate's Q4 gate."""

    build_fingerprint: str
    output_directory: Path
    selected_candidate_id: str
    q4_readiness: dict[str, Any]
    q4_predictions_path: Path
    q4_readiness_path: Path
    manifest_path: Path
    report_path: Path


def _sha256_json(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GbdtExperimentError(f"Cannot read {label}.") from error
    if not isinstance(payload, dict):
        raise GbdtExperimentError(f"{label} must be a JSON object.")
    return payload


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
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
        "evaluation.py",
        "features.py",
        "gbdt_config.py",
        "gbdt_experiment.py",
        "gbdt_selection.py",
        "loader.py",
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
        "lightgbm": lgb.__version__,
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "scipy": scipy.__version__,
        "scikit_learn": sklearn.__version__,
    }


def _as_float_matrix(matrix: csr_matrix) -> csr_matrix:
    """LightGBM requires float32/float64 CSR data; the transformer emits int8."""

    return matrix.astype(np.float64)


def _new_estimator(
    config: GbdtBaselineConfig,
    candidate: GbdtCandidateSpec,
) -> lgb.LGBMClassifier:
    params = config.estimator.lightgbm_params(
        num_leaves=candidate.num_leaves,
        learning_rate=candidate.learning_rate,
    )
    return lgb.LGBMClassifier(
        n_estimators=config.estimator.num_boost_round,
        **params,
    )


def _positive_probabilities(
    model: lgb.LGBMClassifier,
    matrix: csr_matrix,
) -> np.ndarray:
    classes = list(model.classes_)
    if 1 not in classes:
        raise GbdtExperimentError("A GBDT estimator lacks the positive class.")
    probabilities = np.asarray(
        model.predict_proba(matrix, num_iteration=model.best_iteration_)[
            :, classes.index(1)
        ],
        dtype=np.float64,
    )
    if (
        probabilities.shape != (matrix.shape[0],)
        or not np.isfinite(probabilities).all()
        or ((probabilities < 0) | (probabilities > 1)).any()
    ):
        raise GbdtExperimentError(
            "A GBDT estimator produced invalid probabilities."
        )
    return probabilities


def _chronological_early_stopping_split(
    matrix: csr_matrix,
    targets: np.ndarray,
    *,
    validation_fraction: float,
) -> tuple[csr_matrix, np.ndarray, csr_matrix, np.ndarray]:
    n_rows = matrix.shape[0]
    split_index = int(round(n_rows * (1 - validation_fraction)))
    split_index = min(max(split_index, 1), n_rows - 1)
    train_matrix, valid_matrix = matrix[:split_index], matrix[split_index:]
    train_targets, valid_targets = targets[:split_index], targets[split_index:]
    if (
        len(np.unique(train_targets)) != 2
        or len(np.unique(valid_targets)) != 2
    ):
        raise GbdtExperimentError(
            "The chronological early-stopping split lacks both target "
            "classes in the train or validation partition."
        )
    return train_matrix, train_targets, valid_matrix, valid_targets


def _fit_with_early_stopping(
    config: GbdtBaselineConfig,
    candidate: GbdtCandidateSpec,
    fit_matrix: csr_matrix,
    fit_targets: np.ndarray,
) -> lgb.LGBMClassifier:
    train_matrix, train_targets, valid_matrix, valid_targets = (
        _chronological_early_stopping_split(
            fit_matrix,
            fit_targets,
            validation_fraction=config.early_stopping.validation_fraction,
        )
    )
    model = _new_estimator(config, candidate)
    model.fit(
        train_matrix,
        train_targets,
        eval_X=valid_matrix,
        eval_y=valid_targets,
        eval_metric=config.early_stopping.monitored_metric,
        callbacks=[
            lgb.early_stopping(
                config.estimator.early_stopping_rounds,
                verbose=False,
            )
        ],
    )
    if model.best_iteration_ is None or model.best_iteration_ < 1:
        raise GbdtExperimentError(
            "Early stopping did not select a positive boosting iteration."
        )
    return model


def _fold_rows(
    frame: pd.DataFrame,
    fold: RollingOriginFold,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    fit_rows = frame[
        (frame["match_start_utc"] >= pd.Timestamp(fold.train_start_utc))
        & (frame["match_start_utc"] < pd.Timestamp(fold.train_end_utc))
    ].copy()
    evaluation_rows = frame[
        (frame["match_start_utc"] >= pd.Timestamp(fold.evaluation_start_utc))
        & (frame["match_start_utc"] < pd.Timestamp(fold.evaluation_end_utc))
    ].copy()
    if fit_rows.empty or evaluation_rows.empty:
        raise GbdtExperimentError(f"The {fold.fold_id} fit or evaluation window is empty.")
    fit_groups = set(fit_rows["source_match_id"].astype(str))
    evaluation_groups = set(evaluation_rows["source_match_id"].astype(str))
    if fit_groups.intersection(evaluation_groups):
        raise GbdtExperimentError(
            f"A source match crosses the {fold.fold_id} boundary."
        )
    return fit_rows, evaluation_rows


def _load_m4b5_reference(
    config: GbdtBaselineConfig,
    *,
    path: Path,
    expected_pin: str,
) -> pd.DataFrame:
    if not path.is_file() or sha256_file(path) != expected_pin:
        raise GbdtExperimentError("The pinned M4B.5 prediction artifact changed.")
    with duckdb.connect() as connection:
        reference = connection.execute(
            "SELECT evaluation_id, sample_id, source_match_id, radiant_win, "
            "frozen_b1_probability, canonical_b0_probability "
            "FROM read_parquet(?) ORDER BY evaluation_id, sample_id",
            [str(path)],
        ).fetchdf()
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
        raise GbdtExperimentError(
            f"The pinned M4B.5 reference does not align for {evaluation_id}."
        )
    return aligned


def _selection_predictions(
    frame: pd.DataFrame,
    references: pd.DataFrame,
    config: GbdtBaselineConfig,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    predictions: list[pd.DataFrame] = []
    audits: list[dict[str, Any]] = []
    for fold in config.folds:
        fit_rows, evaluation_rows = _fold_rows(frame, fold)
        transformer = DraftFeatureTransformer(
            FeatureVariant(config.feature_variant)
        ).fit(fit_rows)
        fit_matrix = _as_float_matrix(transformer.transform(fit_rows))
        evaluation_matrix = _as_float_matrix(
            transformer.transform(evaluation_rows.drop(columns=["radiant_win"]))
        )
        fit_targets = fit_rows["radiant_win"].astype("int8").to_numpy()
        aligned = _aligned_reference(
            evaluation_rows, references, evaluation_id=fold.fold_id
        )

        for candidate in config.candidates:
            model = _fit_with_early_stopping(
                config, candidate, fit_matrix, fit_targets
            )
            probabilities = _positive_probabilities(model, evaluation_matrix)
            predictions.append(
                pd.DataFrame(
                    {
                        "candidate_id": candidate.candidate_id,
                        "fold_id": fold.fold_id,
                        "sample_id": evaluation_rows["sample_id"]
                        .astype(str)
                        .to_numpy(),
                        "source_match_id": evaluation_rows["source_match_id"]
                        .astype(str)
                        .to_numpy(),
                        "match_start_utc": evaluation_rows[
                            "match_start_utc"
                        ].to_numpy(),
                        "radiant_win": evaluation_rows["radiant_win"]
                        .astype("int8")
                        .to_numpy(),
                        "candidate_probability": probabilities,
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
                    "fold_id": fold.fold_id,
                    "candidate_id": candidate.candidate_id,
                    "fit_rows": int(fit_matrix.shape[0]),
                    "evaluation_rows": int(evaluation_matrix.shape[0]),
                    "feature_columns": int(fit_matrix.shape[1]),
                    "feature_fingerprint": transformer.fingerprint,
                    "best_iteration": int(model.best_iteration_),
                    "requested_num_boost_round": config.estimator.num_boost_round,
                    "early_stopping_rounds": config.estimator.early_stopping_rounds,
                }
            )
    return (
        pd.concat(predictions, ignore_index=True)
        .sort_values(["fold_id", "candidate_id", "sample_id"], kind="stable")
        .reset_index(drop=True),
        audits,
    )


def _render_selection_report(
    *,
    fingerprint: str,
    selection_evaluation: dict[str, Any],
) -> str:
    rows = [
        "# GBDT baseline recovery check: selection stage",
        "",
        f"- Build fingerprint: `{fingerprint}`",
        "- Q4 rows used: `0`",
        "- Locked 2026-Q1 rows used: `0`",
        "- Authenticated API requests: `0`",
        "",
        "## Ranking (pooled log loss, 2025-Q1 through 2025-Q3)",
        "",
        "| Rank | Candidate | num_leaves | learning_rate | Recent pooled log loss |",
        "| ---: | --- | ---: | ---: | ---: |",
    ]
    for index, entry in enumerate(selection_evaluation["ranking"], start=1):
        rows.append(
            f"| {index} | {entry['candidate_id']} | {entry['num_leaves']} | "
            f"{entry['learning_rate']} | {entry['recent_pooled_log_loss']:.6f} |"
        )
    rows.extend(
        [
            "",
            f"Selected candidate: `{selection_evaluation['selected_candidate_id']}`",
            "",
            "This selection never opened 2025-Q4 or the sealed 2026-Q1 window.",
            "",
        ]
    )
    return "\n".join(rows)


def _selection_result_from_existing(
    target: Path,
    manifest: dict[str, Any],
) -> GbdtSelectionStageResult:
    for artifact in manifest["artifacts"].values():
        path = target / str(artifact["file"])
        if not path.is_file() or sha256_file(path) != artifact["sha256"]:
            raise GbdtExperimentError("An existing GBDT selection artifact changed.")
    selection_evaluation = _read_json(
        target / "selection_evaluation.json",
        label="GBDT selection evaluation",
    )
    return GbdtSelectionStageResult(
        build_fingerprint=str(manifest["build_fingerprint"]),
        output_directory=target,
        selected_candidate_id=str(selection_evaluation["selected_candidate_id"]),
        selection_evaluation=selection_evaluation,
        fold_predictions_path=target / "fold_predictions.parquet",
        selection_evaluation_path=target / "selection_evaluation.json",
        manifest_path=target / "selection_manifest.json",
        report_path=target / "selection_report.md",
    )


def run_gbdt_selection_stage(
    experiment_config_path: Path,
    *,
    output_root: Path = Path("models/gbdt_baseline"),
    repository_root: Path | None = None,
) -> GbdtSelectionStageResult:
    """Rank the four pre-registered candidates without ever opening Q4."""

    root = (
        repository_root.resolve()
        if repository_root is not None
        else Path(__file__).resolve().parents[2]
    )
    config = load_gbdt_baseline_config(
        experiment_config_path.resolve(),
        repository_root=root,
        verify_local_artifacts=True,
    )
    core = {
        "experiment_schema_version": EXPERIMENT_SCHEMA_VERSION,
        "prediction_schema_version": PREDICTION_SCHEMA_VERSION,
        "stage": "selection",
        "experiment_id": config.experiment_id,
        "config_fingerprint": config.fingerprint,
        "config_sha256": sha256_file(config.config_path),
        "modeling_source_sha256": _source_sha256(),
        "runtime_versions": _runtime_versions(),
    }
    fingerprint = _sha256_json(core)
    target = output_root.resolve() / f"build_{fingerprint}"
    manifest_path = target / "selection_manifest.json"
    if target.exists():
        manifest = _read_json(manifest_path, label="GBDT selection manifest")
        if manifest.get("build_fingerprint") != fingerprint:
            raise GbdtExperimentError(
                "Existing GBDT selection build fingerprint changed."
            )
        return _selection_result_from_existing(target, manifest)

    development_prefix = load_working_corpus_prefix(
        config.corpus_config_path,
        end_utc=config.development_end_utc,
        repository_root=root,
    )
    if (
        len(development_prefix.frame) != config.expected_development_rows
        or "2025-Q4" in development_prefix.verified_component_ids
        or "2026-Q1" in development_prefix.verified_component_ids
    ):
        raise GbdtExperimentError("The development-only corpus boundary changed.")

    references = _load_m4b5_reference(
        config,
        path=config.m4b5_development_predictions_path,
        expected_pin=config.m4b5_development_predictions_sha256,
    )
    fold_predictions, fold_audits = _selection_predictions(
        development_prefix.frame, references, config
    )
    selection_evaluation = evaluate_gbdt_selection(fold_predictions, config=config)

    target.mkdir(parents=True)
    paths = {
        "fold_predictions": target / "fold_predictions.parquet",
        "selection_evaluation": target / "selection_evaluation.json",
        "report": target / "selection_report.md",
    }
    _write_parquet(fold_predictions, paths["fold_predictions"])
    _write_json(paths["selection_evaluation"], selection_evaluation)
    paths["report"].write_text(
        _render_selection_report(
            fingerprint=fingerprint,
            selection_evaluation=selection_evaluation,
        ),
        encoding="utf-8",
    )
    manifest = {
        **core,
        "build_fingerprint": fingerprint,
        "development_component_ids_opened": list(
            development_prefix.verified_component_ids
        ),
        "fold_audits": fold_audits,
        "result": {
            "selected_candidate_id": selection_evaluation["selected_candidate_id"],
        },
        "safety_audit": {
            "q4_component_opened": False,
            "locked_component_opened": False,
            "authenticated_api_requests": 0,
            "model_bundle_serialized": False,
        },
        "artifacts": {name: _artifact(path) for name, path in paths.items()},
    }
    _write_json(manifest_path, manifest)
    return _selection_result_from_existing(target, manifest)


def _render_q4_report(
    *,
    fingerprint: str,
    selected_candidate_id: str,
    q4_readiness: dict[str, Any],
) -> str:
    metrics = q4_readiness["metrics"]
    rows = [
        "# GBDT baseline recovery check: Q4 readiness gate",
        "",
        f"- Build fingerprint: `{fingerprint}`",
        f"- Selected candidate: `{selected_candidate_id}`",
        f"- Q4 readiness: `{'passed' if q4_readiness['passed'] else 'failed'}`",
        "- Locked 2026-Q1 rows used: `0`",
        "- Authenticated API requests: `0`",
        "",
        "| Model | Log loss | Brier score |",
        "| --- | ---: | ---: |",
        f"| candidate | {metrics['candidate']['log_loss']:.6f} | "
        f"{metrics['candidate']['brier_score']:.6f} |",
        f"| frozen_b1 | {metrics['frozen_b1']['log_loss']:.6f} | "
        f"{metrics['frozen_b1']['brier_score']:.6f} |",
        f"| canonical_b0 | {metrics['canonical_b0']['log_loss']:.6f} | "
        f"{metrics['canonical_b0']['brier_score']:.6f} |",
        "",
    ]
    return "\n".join(rows)


def _q4_result_from_existing(
    target: Path,
    manifest: dict[str, Any],
) -> GbdtQ4GateResult:
    for artifact in manifest["artifacts"].values():
        path = target / str(artifact["file"])
        if not path.is_file() or sha256_file(path) != artifact["sha256"]:
            raise GbdtExperimentError("An existing GBDT Q4 gate artifact changed.")
    q4_readiness = _read_json(
        target / "q4_readiness.json", label="GBDT Q4 readiness"
    )
    return GbdtQ4GateResult(
        build_fingerprint=str(manifest["build_fingerprint"]),
        output_directory=target,
        selected_candidate_id=str(manifest["result"]["selected_candidate_id"]),
        q4_readiness=q4_readiness,
        q4_predictions_path=target / "q4_predictions.parquet",
        q4_readiness_path=target / "q4_readiness.json",
        manifest_path=target / "q4_manifest.json",
        report_path=target / "q4_report.md",
    )


def run_gbdt_q4_gate(
    experiment_config_path: Path,
    *,
    selection_result: GbdtSelectionStageResult,
    output_root: Path = Path("models/gbdt_baseline"),
    repository_root: Path | None = None,
) -> GbdtQ4GateResult:
    """Refit only the selected candidate and evaluate it once against Q4.

    Requires a completed `GbdtSelectionStageResult`; Q4 cannot be reached
    without first running (or loading) the fold-based selection stage.
    """

    root = (
        repository_root.resolve()
        if repository_root is not None
        else Path(__file__).resolve().parents[2]
    )
    config = load_gbdt_baseline_config(
        experiment_config_path.resolve(),
        repository_root=root,
        verify_local_artifacts=True,
    )
    candidate = next(
        (
            item
            for item in config.candidates
            if item.candidate_id == selection_result.selected_candidate_id
        ),
        None,
    )
    if candidate is None:
        raise GbdtExperimentError(
            "The selection stage's selected candidate is not in the "
            "pre-registered grid."
        )

    core = {
        "experiment_schema_version": EXPERIMENT_SCHEMA_VERSION,
        "prediction_schema_version": PREDICTION_SCHEMA_VERSION,
        "stage": "q4_gate",
        "experiment_id": config.experiment_id,
        "config_fingerprint": config.fingerprint,
        "config_sha256": sha256_file(config.config_path),
        "modeling_source_sha256": _source_sha256(),
        "selection_build_fingerprint": selection_result.build_fingerprint,
        "selected_candidate_id": candidate.candidate_id,
        "runtime_versions": _runtime_versions(),
    }
    fingerprint = _sha256_json(core)
    target = output_root.resolve() / f"build_{fingerprint}"
    manifest_path = target / "q4_manifest.json"
    if target.exists():
        manifest = _read_json(manifest_path, label="GBDT Q4 gate manifest")
        if manifest.get("build_fingerprint") != fingerprint:
            raise GbdtExperimentError(
                "Existing GBDT Q4 gate build fingerprint changed."
            )
        return _q4_result_from_existing(target, manifest)

    q4_prefix = load_working_corpus_prefix(
        config.corpus_config_path,
        end_utc=config.q4_end_utc,
        repository_root=root,
    )
    if "2026-Q1" in q4_prefix.verified_component_ids:
        raise GbdtExperimentError("The locked 2026-Q1 component was opened.")
    base = q4_prefix.frame[
        q4_prefix.frame["match_start_utc"] < pd.Timestamp(config.development_end_utc)
    ].copy()
    q4 = q4_prefix.frame[
        (q4_prefix.frame["match_start_utc"] >= pd.Timestamp(config.development_end_utc))
        & (q4_prefix.frame["match_start_utc"] < pd.Timestamp(config.q4_end_utc))
    ].copy()
    if (
        len(base) != config.expected_development_rows
        or len(q4) != config.expected_q4_rows
        or q4["source_match_id"].nunique() != config.expected_q4_source_matches
    ):
        raise GbdtExperimentError("The Q4 role counts changed.")

    transformer = DraftFeatureTransformer(
        FeatureVariant(config.feature_variant)
    ).fit(base)
    fit_matrix = _as_float_matrix(transformer.transform(base))
    q4_matrix = _as_float_matrix(transformer.transform(q4.drop(columns=["radiant_win"])))
    fit_targets = base["radiant_win"].astype("int8").to_numpy()
    model = _fit_with_early_stopping(config, candidate, fit_matrix, fit_targets)
    probabilities = _positive_probabilities(model, q4_matrix)

    references = _load_m4b5_reference(
        config,
        path=config.m4b5_q4_predictions_path,
        expected_pin=config.m4b5_q4_predictions_sha256,
    )
    aligned = _aligned_reference(q4, references, evaluation_id="2025-Q4")

    q4_predictions = pd.DataFrame(
        {
            "candidate_id": candidate.candidate_id,
            "sample_id": q4["sample_id"].astype(str).to_numpy(),
            "source_match_id": q4["source_match_id"].astype(str).to_numpy(),
            "match_start_utc": q4["match_start_utc"].to_numpy(),
            "radiant_win": q4["radiant_win"].astype("int8").to_numpy(),
            "candidate_probability": probabilities,
            "frozen_b1_probability": aligned["frozen_b1_probability"].to_numpy(
                dtype=np.float64
            ),
            "canonical_b0_probability": aligned[
                "canonical_b0_probability"
            ].to_numpy(dtype=np.float64),
        }
    )
    q4_readiness = evaluate_gbdt_q4_readiness(q4_predictions, config=config)

    target.mkdir(parents=True)
    paths = {
        "q4_predictions": target / "q4_predictions.parquet",
        "q4_readiness": target / "q4_readiness.json",
        "report": target / "q4_report.md",
    }
    _write_parquet(q4_predictions, paths["q4_predictions"])
    _write_json(paths["q4_readiness"], q4_readiness)
    paths["report"].write_text(
        _render_q4_report(
            fingerprint=fingerprint,
            selected_candidate_id=candidate.candidate_id,
            q4_readiness=q4_readiness,
        ),
        encoding="utf-8",
    )
    manifest = {
        **core,
        "build_fingerprint": fingerprint,
        "q4_component_ids_opened": list(q4_prefix.verified_component_ids),
        "model_audit": {
            "fit_rows": int(fit_matrix.shape[0]),
            "evaluation_rows": int(q4_matrix.shape[0]),
            "feature_fingerprint": transformer.fingerprint,
            "best_iteration": int(model.best_iteration_),
        },
        "result": {
            "selected_candidate_id": candidate.candidate_id,
            "q4_readiness_passed": bool(q4_readiness["passed"]),
        },
        "safety_audit": {
            "locked_component_id": "2026-Q1",
            "locked_component_opened": False,
            "authenticated_api_requests": 0,
            "model_bundle_serialized": False,
        },
        "artifacts": {name: _artifact(path) for name, path in paths.items()},
    }
    _write_json(manifest_path, manifest)
    return _q4_result_from_existing(target, manifest)


__all__ = [
    "EXPERIMENT_SCHEMA_VERSION",
    "GbdtExperimentError",
    "GbdtQ4GateResult",
    "GbdtSelectionStageResult",
    "PREDICTION_SCHEMA_VERSION",
    "run_gbdt_q4_gate",
    "run_gbdt_selection_stage",
]
