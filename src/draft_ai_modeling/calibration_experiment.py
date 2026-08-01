"""Offline orchestration for the bounded M4B.3 Draft AI calibration gate."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import joblib
import numpy as np
import pandas as pd
import scipy
import sklearn
from scipy.sparse import csr_matrix
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

from .calibration import (
    apply_calibrator,
    cross_fitted_calibration_predictions,
    fit_calibrator,
    paired_method_bootstrap_comparison,
)
from .calibration_config import (
    CalibrationExperimentConfig,
    load_calibration_experiment_config,
)
from .calibration_selection import (
    build_pairwise_comparisons,
    evaluate_calibration_methods,
    method_prediction_frame,
    select_calibration_method,
)
from .contracts import (
    SPLIT_ROLE_CALIBRATION,
    SPLIT_ROLE_LOCKED_TEST,
    SPLIT_ROLE_TRAIN,
    SPLIT_ROLE_TUNING,
)
from .evaluation import global_logistic_coefficient_explanations
from .features import DraftFeatureTransformer, FeatureVariant
from .loader import load_working_corpus, sha256_file
from .model_bundle import load_model_bundle, write_model_bundle
from .recency_evaluation import patch_group_descriptive_metrics
from .splits import split_manifest_fingerprint


EXPERIMENT_SCHEMA_VERSION = "draft-ai-calibration-experiment-run-v1"
PREDICTION_SCHEMA_VERSION = "draft-ai-calibration-oof-predictions-v1"


class CalibrationExperimentError(ValueError):
    """Raised when M4B.3 crosses its data, lineage, or safety boundary."""


@dataclass(frozen=True, slots=True)
class CalibrationExperimentResult:
    """Content-addressed outputs from one completed calibration gate."""

    build_fingerprint: str
    output_directory: Path
    manifest_path: Path
    predictions_path: Path
    metrics_path: Path
    comparisons_path: Path
    selection_path: Path
    readiness_path: Path
    bundle_manifest_path: Path
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


def _source_sha256() -> str:
    root = Path(__file__).resolve().parent
    names = (
        "calibration.py",
        "calibration_config.py",
        "calibration_experiment.py",
        "calibration_selection.py",
        "contracts.py",
        "evaluation.py",
        "features.py",
        "loader.py",
        "model_bundle.py",
        "recency_evaluation.py",
        "splits.py",
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
        "joblib": joblib.__version__,
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "scipy": scipy.__version__,
        "scikit_learn": sklearn.__version__,
    }


def _git_state(root: Path) -> dict[str, object]:
    def run(*args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    try:
        head = run("rev-parse", "HEAD")
        status = run("status", "--porcelain=v1", "--untracked-files=all")
    except (OSError, subprocess.CalledProcessError):
        return {"available": False, "head": None, "dirty": None}
    return {
        "available": True,
        "head": head,
        "dirty": bool(status),
        "status_sha256": hashlib.sha256(status.encode("utf-8")).hexdigest(),
    }


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CalibrationExperimentError(f"Cannot read {label}.") from error
    if not isinstance(payload, dict):
        raise CalibrationExperimentError(f"{label} must be a JSON object.")
    return payload


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
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


def _artifact(path: Path, *, root: Path) -> dict[str, object]:
    return {
        "file": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _load_split_manifest(
    config: CalibrationExperimentConfig,
) -> pd.DataFrame:
    with duckdb.connect() as connection:
        manifest = connection.execute(
            "SELECT * FROM read_parquet(?) ORDER BY match_start_utc, "
            "source_match_id, sample_id",
            [str(config.m4a.split_manifest_path)],
        ).fetchdf()
    observed = split_manifest_fingerprint(manifest)
    if observed != config.split_manifest_fingerprint:
        raise CalibrationExperimentError("The M4A split fingerprint changed.")
    return manifest


def _source_lineage(
    config: CalibrationExperimentConfig,
) -> dict[str, Any]:
    m4a = _read_json(config.m4a.manifest_path, label="M4A manifest")
    m4b2 = _read_json(config.m4b2.manifest_path, label="M4B.2 manifest")
    selection = _read_json(
        config.m4b2.selection_path,
        label="M4B.2 selection",
    )
    if (
        m4a.get("build_fingerprint") != config.m4a.build_fingerprint
        or m4a.get("split", {}).get("split_manifest_fingerprint")
        != config.split_manifest_fingerprint
    ):
        raise CalibrationExperimentError("The pinned M4A lineage changed.")
    if (
        m4b2.get("build_fingerprint") != config.m4b2.build_fingerprint
        or m4b2.get("experiment_config_fingerprint")
        != config.m4b2.config_fingerprint
        or m4b2.get("result", {}).get("selected_development_candidate")
        != config.candidate_id
        or m4b2.get("result", {}).get("calibration_prediction_rows") != 0
        or m4b2.get("result", {}).get("locked_test_prediction_rows") != 0
        or selection.get("selected_candidate_id") != config.candidate_id
    ):
        raise CalibrationExperimentError("The pinned M4B.2 lineage changed.")
    return {
        "corpus_id": config.corpus_id,
        "corpus_config_path": config.corpus_config_path.relative_to(
            config.repository_root
        ).as_posix(),
        "corpus_config_sha256": config.corpus_config_sha256,
        "split_manifest_fingerprint": config.split_manifest_fingerprint,
        "m4a": {
            "build_fingerprint": config.m4a.build_fingerprint,
            "manifest_sha256": config.m4a.manifest_sha256,
            "split_manifest_sha256": config.m4a.split_manifest_sha256,
        },
        "m4b2": {
            "build_fingerprint": config.m4b2.build_fingerprint,
            "config_fingerprint": config.m4b2.config_fingerprint,
            "manifest_sha256": config.m4b2.manifest_sha256,
            "selection_sha256": config.m4b2.selection_sha256,
            "selected_candidate_id": config.candidate_id,
            "selected_candidate_fingerprint": (
                config.candidate_fingerprint
            ),
        },
    }


def _masked_modeling_rows(
    corpus: pd.DataFrame,
    split_manifest: pd.DataFrame,
    config: CalibrationExperimentConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    roles = split_manifest[["sample_id", "split_role"]]
    joined = corpus.merge(
        roles,
        on="sample_id",
        how="left",
        validate="one_to_one",
    )
    if joined["split_role"].isna().any():
        raise CalibrationExperimentError("Split roles do not cover the corpus.")
    locked_mask = joined["split_role"] == SPLIT_ROLE_LOCKED_TEST
    locked_rows = int(locked_mask.sum())
    joined.loc[locked_mask, "radiant_win"] = pd.NA
    if (
        locked_rows != config.expected_counts["locked_test_rows"]
        or not joined.loc[locked_mask, "radiant_win"].isna().all()
    ):
        raise CalibrationExperimentError(
            "Locked-test masking did not match the frozen contract."
        )

    base_mask = joined["split_role"].isin(config.base_fit_roles)
    calibration_mask = joined["split_role"] == config.calibration_role
    base = joined.loc[base_mask].copy()
    calibration = joined.loc[calibration_mask].copy()
    for role in sorted(set(base["split_role"].astype(str))):
        config.assert_role_allowed(role, purpose="base_fit")
    config.assert_role_allowed(
        str(calibration["split_role"].iloc[0]),
        purpose="calibrate",
    )
    if base["radiant_win"].isna().any() or calibration["radiant_win"].isna().any():
        raise CalibrationExperimentError("Approved modeling targets are missing.")
    base_groups = set(base["source_match_id"].astype(str))
    calibration_groups = set(calibration["source_match_id"].astype(str))
    if base_groups.intersection(calibration_groups):
        raise CalibrationExperimentError(
            "A source match crosses base-fit and calibration roles."
        )
    counts = {
        "base_fit_rows": len(base),
        "base_fit_source_matches": len(base_groups),
        "calibration_rows": len(calibration),
        "calibration_source_matches": len(calibration_groups),
        "calibration_positive_rows": int(
            calibration["radiant_win"].astype("int8").sum()
        ),
        "calibration_negative_rows": int(
            len(calibration)
            - calibration["radiant_win"].astype("int8").sum()
        ),
        "locked_test_rows": locked_rows,
    }
    if counts != config.expected_counts:
        raise CalibrationExperimentError(
            f"M4B.3 role counts changed: {counts!r}."
        )
    return base, calibration, {
        **counts,
        "locked_test_targets_masked_before_role_selection": True,
        "locked_test_transform_rows": 0,
        "locked_test_prediction_rows": 0,
    }


def _new_estimator(
    config: CalibrationExperimentConfig,
) -> LogisticRegression:
    policy = config.estimator
    return LogisticRegression(
        C=policy.regularization_c,
        class_weight=policy.class_weight,
        max_iter=policy.max_iter,
        penalty=policy.penalty,
        random_state=policy.random_seed,
        solver=policy.solver,
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
        raise CalibrationExperimentError(
            "The frozen estimator lacks the positive class."
        )
    values = np.asarray(
        estimator.predict_proba(matrix)[:, classes.index(1)],
        dtype=np.float64,
    )
    if (
        values.shape != (matrix.shape[0],)
        or not np.isfinite(values).all()
        or ((values <= 0) | (values >= 1)).any()
    ):
        raise CalibrationExperimentError(
            "The frozen estimator produced invalid raw probabilities."
        )
    return values


def _m4b2_prediction_path(
    config: CalibrationExperimentConfig,
) -> tuple[Path, str]:
    manifest = _read_json(config.m4b2.manifest_path, label="M4B.2 manifest")
    artifact = manifest.get("artifacts", {}).get("predictions", {})
    path = config.m4b2.manifest_path.parent / str(artifact.get("file"))
    digest = str(artifact.get("sha256"))
    if not path.is_file() or sha256_file(path) != digest:
        raise CalibrationExperimentError(
            "Pinned M4B.2 development predictions changed."
        )
    return path, digest


def _reproduce_frozen_candidate(
    base_rows: pd.DataFrame,
    config: CalibrationExperimentConfig,
) -> dict[str, Any]:
    training = base_rows[
        base_rows["split_role"] == SPLIT_ROLE_TRAIN
    ].copy()
    tuning = base_rows[
        base_rows["split_role"] == SPLIT_ROLE_TUNING
    ].copy()
    transformer = DraftFeatureTransformer(
        FeatureVariant.B1_PICK_PRESENCE
    ).fit(training)
    estimator = _new_estimator(config)
    _fit_estimator(
        estimator,
        transformer.transform(training),
        training["radiant_win"].astype("int8").to_numpy(),
    )
    reproduced = pd.DataFrame(
        {
            "sample_id": tuning["sample_id"].astype(str),
            "probability": _positive_probabilities(
                estimator,
                transformer.transform(tuning),
            ),
        }
    ).sort_values("sample_id", kind="stable").reset_index(drop=True)
    parent_path, parent_sha256 = _m4b2_prediction_path(config)
    with duckdb.connect() as connection:
        parent = connection.execute(
            "SELECT sample_id, candidate_probability AS probability "
            "FROM read_parquet(?) WHERE candidate_id = ? "
            "AND evaluation_id = '2025-Q3' ORDER BY sample_id",
            [str(parent_path), config.candidate_id],
        ).fetchdf()
    if len(parent) != len(reproduced) or parent["sample_id"].astype(
        str
    ).tolist() != reproduced["sample_id"].tolist():
        raise CalibrationExperimentError(
            "M4B.2 frozen-candidate reproduction alignment changed."
        )
    difference = np.abs(
        parent["probability"].to_numpy(dtype=np.float64)
        - reproduced["probability"].to_numpy(dtype=np.float64)
    )
    maximum = float(difference.max(initial=0.0))
    if maximum > 1e-12:
        raise CalibrationExperimentError(
            "The frozen M4B.2 candidate no longer reproduces."
        )
    return {
        "candidate_id": config.candidate_id,
        "evaluation_id": "2025-Q3",
        "training_rows": len(training),
        "prediction_rows": len(tuning),
        "maximum_absolute_probability_difference": maximum,
        "tolerance": 1e-12,
        "parent_predictions_sha256": parent_sha256,
        "passed": True,
    }


def _b0_readiness(
    selected_predictions: pd.DataFrame,
    *,
    base_prior: float,
    n_resamples: int,
    random_state: int,
    confidence_level: float,
) -> dict[str, Any]:
    reference = selected_predictions[
        [
            "sample_id",
            "source_match_id",
            "radiant_win",
        ]
    ].copy()
    reference["radiant_win_probability"] = base_prior
    comparison = paired_method_bootstrap_comparison(
        reference,
        selected_predictions,
        n_resamples=n_resamples,
        random_state=random_state,
        confidence_level=confidence_level,
    )
    gates = {
        metric: (
            float(comparison["metrics"][metric]["point_estimate"]) < 0
            and float(comparison["metrics"][metric]["upper"]) < 0
        )
        for metric in ("log_loss", "brier_score")
    }
    return {
        "reference": "train_tuning_empirical_prior",
        "base_prior": base_prior,
        "comparison": comparison,
        "gates": gates,
        "passed": all(gates.values()),
        "required_before_locked_test": True,
    }


def _calibrator_diagnostics(
    method: str,
    calibrator: LogisticRegression | IsotonicRegression | None,
    raw_probabilities: np.ndarray,
) -> dict[str, Any]:
    calibrated = apply_calibrator(method, calibrator, raw_probabilities)
    common = {
        "method": method,
        "fit_rows": len(raw_probabilities),
        "output_minimum": float(calibrated.min()),
        "output_maximum": float(calibrated.max()),
        "boundary_output_rows": int(
            ((calibrated == 0) | (calibrated == 1)).sum()
        ),
    }
    if method == "raw":
        return {**common, "calibrator_fit": False}
    if method == "sigmoid":
        assert isinstance(calibrator, LogisticRegression)
        return {
            **common,
            "calibrator_fit": True,
            "slope": float(calibrator.coef_[0, 0]),
            "intercept": float(calibrator.intercept_[0]),
        }
    assert isinstance(calibrator, IsotonicRegression)
    return {
        **common,
        "calibrator_fit": True,
        "threshold_count": int(len(calibrator.X_thresholds_)),
        "fitted_output_minimum": float(calibrator.y_thresholds_.min()),
        "fitted_output_maximum": float(calibrator.y_thresholds_.max()),
    }


def _render_report(
    *,
    fingerprint: str,
    selection: dict[str, Any],
    evaluation: dict[str, Any],
    readiness: dict[str, Any],
    role_audit: dict[str, Any],
    reproduction: dict[str, Any],
    patch_diagnostics: dict[str, Any],
) -> str:
    selected = str(selection["selected_method"])
    metrics = evaluation["pooled"]
    final_fit_note = (
        "Raw identity has no fitted calibrator; Q4 labels were used only for "
        "the grouped comparison and readiness gate."
        if selected == "raw"
        else (
            f"The selected {selected} calibrator was fit once on all Q4 "
            "rows after selection; those fitted values were not used as "
            "evaluation evidence."
        )
    )
    rows = [
        "# Milestone 4B.3: Frozen B1 Probability Calibration",
        "",
        f"- Build fingerprint: `{fingerprint}`",
        "- Base candidate: `b1_full_uniform_c0p01`",
        (
            "- Base refit: "
            f"`{role_audit['base_fit_rows']}` Train + Tuning rows"
        ),
        (
            "- Calibration comparison: "
            f"`{role_audit['calibration_rows']}` 2025-Q4 rows across "
            f"`{role_audit['calibration_source_matches']}` series"
        ),
        f"- Selected calibration method: `{selected}`",
        (
            "- Calibration-period B0 readiness gate: "
            f"`{'passed' if readiness['passed'] else 'failed'}`"
        ),
        (
            "- M4B.2 reproduction maximum difference: "
            f"`{reproduction['maximum_absolute_probability_difference']}`"
        ),
        "- Locked-test rows predicted: `0`",
        "- Authenticated API requests: `0`",
        "",
        "| Method | OOF log loss | OOF Brier | ECE |",
        "| --- | ---: | ---: | ---: |",
    ]
    for method in ("raw", "sigmoid", "isotonic"):
        values = metrics[method]["metrics"]
        rows.append(
            f"| {method} | {values['log_loss']:.6f} | "
            f"{values['brier_score']:.6f} | "
            f"{values['expected_calibration_error']:.6f} |"
        )
    rows.extend(
        [
            "",
            "The selected method was chosen from grouped five-fold "
            "out-of-fold predictions.",
            "",
            final_fit_note,
            "",
            "Patch diagnostics were generated only after selection and were "
            "not selection inputs.",
            "",
        ]
    )
    for patch in patch_diagnostics["patches"]:
        if patch["reportable"]:
            patch_metrics = patch["metrics"]
            rows.append(
                f"- Patch `{patch['patch']}`: `{patch['rows']}` rows, "
                f"log loss `{patch_metrics['log_loss']:.6f}`, "
                f"ROC-AUC `{patch_metrics['roc_auc']:.4f}`."
            )
    rows.append("")
    return "\n".join(rows)


def _result_from_paths(
    fingerprint: str,
    target: Path,
    paths: dict[str, Path],
) -> CalibrationExperimentResult:
    return CalibrationExperimentResult(
        build_fingerprint=fingerprint,
        output_directory=target,
        manifest_path=paths["manifest"],
        predictions_path=paths["predictions"],
        metrics_path=paths["metrics"],
        comparisons_path=paths["comparisons"],
        selection_path=paths["selection"],
        readiness_path=paths["readiness"],
        bundle_manifest_path=paths["bundle_manifest"],
        report_path=paths["report"],
    )


def run_calibration_experiment(
    experiment_config_path: Path,
    *,
    output_root: Path = Path("models/m4b3"),
    repository_root: Path | None = None,
) -> CalibrationExperimentResult:
    """Refit the frozen B1, choose Q4 calibration, and seal a model bundle."""

    root = (
        repository_root.resolve()
        if repository_root is not None
        else Path(__file__).resolve().parents[2]
    )
    config = load_calibration_experiment_config(
        experiment_config_path.resolve(),
        repository_root=root,
        verify_local_artifacts=True,
    )
    lineage = _source_lineage(config)
    core = {
        "experiment_schema_version": EXPERIMENT_SCHEMA_VERSION,
        "prediction_schema_version": PREDICTION_SCHEMA_VERSION,
        "experiment_id": config.experiment_id,
        "experiment_config_fingerprint": config.fingerprint,
        "config_path": config.config_path.relative_to(root).as_posix(),
        "config_sha256": sha256_file(config.config_path),
        "modeling_source_sha256": _source_sha256(),
        "source": lineage,
        "frozen_candidate": {
            "candidate_id": config.candidate_id,
            "candidate_fingerprint": config.candidate_fingerprint,
            "feature_variant": config.feature_variant,
            "history_policy_id": config.history_policy_id,
            "estimator": {
                "family": config.estimator.family,
                "penalty": config.estimator.penalty,
                "C": config.estimator.regularization_c,
                "solver": config.estimator.solver,
                "class_weight": config.estimator.class_weight,
                "max_iter": config.estimator.max_iter,
                "random_seed": config.estimator.random_seed,
            },
        },
        "calibration_contract": {
            "methods": list(config.methods),
            "cross_fit": config.cross_fit,
            "evaluation": config.evaluation,
            "selection_policy": config.selection_policy,
        },
        "safety": config.safety,
        "runtime_versions": _runtime_versions(),
    }
    fingerprint = _sha256_json(core)
    target = output_root.resolve() / f"build_{fingerprint}"
    paths = {
        "manifest": target / "experiment_manifest.json",
        "predictions": target / "calibration_oof_predictions.parquet",
        "fold_assignments": target / "calibration_fold_assignments.parquet",
        "metrics": target / "calibration_metrics.json",
        "comparisons": target / "calibration_comparisons.json",
        "selection": target / "calibration_selection.json",
        "readiness": target / "readiness_gate.json",
        "explanations": target / "base_coefficient_explanations.json",
        "patch_diagnostics": target / "patch_diagnostics.json",
        "bundle_manifest": target / "bundle" / "model_bundle.json",
        "report": target / "experiment_report.md",
    }
    if target.exists():
        existing = _read_json(paths["manifest"], label="M4B.3 manifest")
        if existing.get("build_fingerprint") != fingerprint:
            raise CalibrationExperimentError(
                "Existing M4B.3 build fingerprint changed."
            )
        for artifact in existing.get("artifacts", {}).values():
            artifact_path = target / str(artifact["file"])
            if (
                not artifact_path.is_file()
                or sha256_file(artifact_path) != artifact["sha256"]
            ):
                raise CalibrationExperimentError(
                    "An existing M4B.3 artifact changed."
                )
        return _result_from_paths(fingerprint, target, paths)

    corpus = load_working_corpus(config.corpus_config_path)
    split_manifest = _load_split_manifest(config)
    base, calibration, role_audit = _masked_modeling_rows(
        corpus.frame,
        split_manifest,
        config,
    )
    reproduction = _reproduce_frozen_candidate(base, config)

    transformer = DraftFeatureTransformer(
        FeatureVariant(config.feature_variant)
    ).fit(base)
    base_matrix = transformer.transform(base)
    calibration_matrix = transformer.transform(calibration)
    base_targets = base["radiant_win"].astype("int8").to_numpy()
    calibration_targets = (
        calibration["radiant_win"].astype("int8").to_numpy()
    )
    estimator = _new_estimator(config)
    _fit_estimator(estimator, base_matrix, base_targets)
    raw_probabilities = _positive_probabilities(
        estimator,
        calibration_matrix,
    )
    calibration_input = calibration[
        ["sample_id", "source_match_id", "radiant_win"]
    ].copy()
    calibration_input["raw_probability"] = raw_probabilities

    cross_fit = cross_fitted_calibration_predictions(
        calibration_input,
        n_splits=int(config.cross_fit["folds"]),
        random_state=int(config.cross_fit["random_seed"]),
    )
    expected = config.expected_counts
    if (
        cross_fit.audit["rows"] != expected["calibration_rows"]
        or cross_fit.audit["source_matches"]
        != expected["calibration_source_matches"]
        or cross_fit.audit["positive_rows"]
        != expected["calibration_positive_rows"]
        or cross_fit.audit["negative_rows"]
        != expected["calibration_negative_rows"]
    ):
        raise CalibrationExperimentError(
            "Cross-fitted calibration coverage changed."
        )
    evaluation = evaluate_calibration_methods(
        cross_fit.predictions,
        reliability_bins=int(config.evaluation["reliability_bins"]),
    )
    bootstrap = config.evaluation["paired_group_bootstrap"]
    comparisons = build_pairwise_comparisons(
        cross_fit.predictions,
        n_resamples=int(bootstrap["replicates"]),
        random_state=int(bootstrap["random_seed"]),
        confidence_level=float(bootstrap["confidence_level"]),
    )
    selection = select_calibration_method(evaluation, comparisons)
    selected_method = str(selection["selected_method"])
    selected_predictions = method_prediction_frame(
        cross_fit.predictions,
        selected_method,
    )
    selected_patch_predictions = selected_predictions[
        [
            "sample_id",
            "source_match_id",
            "radiant_win",
            "radiant_win_probability",
        ]
    ].merge(
        calibration[["sample_id", "patch"]],
        on="sample_id",
        how="left",
        validate="one_to_one",
    )
    selected_patch_predictions["evaluation_id"] = "2025-Q4"
    patch_diagnostics = {
        "selected_method": selected_method,
        **patch_group_descriptive_metrics(selected_patch_predictions),
    }
    base_prior = float(base_targets.mean())
    readiness = _b0_readiness(
        selected_predictions,
        base_prior=base_prior,
        n_resamples=int(bootstrap["replicates"]),
        random_state=int(bootstrap["random_seed"]),
        confidence_level=float(bootstrap["confidence_level"]),
    )

    calibrator = fit_calibrator(
        selected_method,
        raw_probabilities,
        calibration_targets,
        random_state=config.estimator.random_seed,
    )
    calibrator_diagnostics = _calibrator_diagnostics(
        selected_method,
        calibrator,
        raw_probabilities,
    )
    explanations = global_logistic_coefficient_explanations(
        estimator,
        base_matrix,
        transformer.get_feature_names_out(),
        top_k=20,
    )

    target.mkdir(parents=True)
    _write_parquet(cross_fit.predictions, paths["predictions"])
    _write_parquet(cross_fit.fold_assignments, paths["fold_assignments"])
    _write_json(
        paths["metrics"],
        {
            "evaluation": evaluation,
            "cross_fit_audit": cross_fit.audit,
        },
    )
    _write_json(paths["comparisons"], comparisons)
    _write_json(
        paths["selection"],
        {
            **selection,
            "final_calibrator": calibrator_diagnostics,
        },
    )
    _write_json(paths["readiness"], readiness)
    _write_json(paths["patch_diagnostics"], patch_diagnostics)
    _write_json(
        paths["explanations"],
        {
            "candidate_id": config.candidate_id,
            "feature_fingerprint": transformer.fingerprint,
            "explanation_surface": "base_estimator_log_odds",
            "calibrated_output_separate": True,
            "explanation": explanations,
        },
    )
    bundle_path = write_model_bundle(
        paths["bundle_manifest"].parent,
        transformer=transformer,
        estimator=estimator,
        calibrator=calibrator,
        selected_method=selected_method,
        metadata={
            "experiment_id": config.experiment_id,
            "experiment_build_fingerprint": fingerprint,
            "source_split_fingerprint": config.split_manifest_fingerprint,
            "candidate_id": config.candidate_id,
            "candidate_fingerprint": config.candidate_fingerprint,
            "base_fit_roles": sorted(config.base_fit_roles),
            "base_fit_rows": len(base),
            "base_fit_end_utc_exclusive": "2025-10-01T00:00:00Z",
            "calibration_role": config.calibration_role,
            "calibration_rows": len(calibration),
            "calibration_interval": (
                "[2025-10-01T00:00:00Z,2026-01-01T00:00:00Z)"
            ),
            "selection_evidence": "five_fold_grouped_oof",
            "readiness_gate_passed": readiness["passed"],
            "locked_test_predictions": 0,
        },
    )
    bundle_manifest_sha256 = sha256_file(bundle_path)
    loaded = load_model_bundle(
        bundle_path,
        expected_manifest_sha256=bundle_manifest_sha256,
        trusted_root=target,
    )
    round_trip = loaded.predict(calibration)
    expected_calibrated = apply_calibrator(
        selected_method,
        calibrator,
        raw_probabilities,
    )
    raw_difference = float(
        np.max(
            np.abs(
                round_trip["raw_radiant_win_probability"]
                - raw_probabilities
            ),
            initial=0.0,
        )
    )
    calibrated_difference = float(
        np.max(
            np.abs(
                round_trip["calibrated_radiant_win_probability"]
                - expected_calibrated
            ),
            initial=0.0,
        )
    )
    if raw_difference > 1e-12 or calibrated_difference > 1e-12:
        raise CalibrationExperimentError(
            "Serialized bundle predictions changed after round-trip."
        )
    bundle_validation = {
        "manifest_sha256": bundle_manifest_sha256,
        "bundle_fingerprint": loaded.manifest["bundle_fingerprint"],
        "calibration_rows_checked": len(calibration),
        "maximum_raw_probability_difference": raw_difference,
        "maximum_calibrated_probability_difference": calibrated_difference,
        "tolerance": 1e-12,
        "passed": True,
    }

    paths["report"].write_text(
        _render_report(
            fingerprint=fingerprint,
            selection=selection,
            evaluation=evaluation,
            readiness=readiness,
            role_audit=role_audit,
            reproduction=reproduction,
            patch_diagnostics=patch_diagnostics,
        ),
        encoding="utf-8",
    )
    artifact_paths = {
        "predictions": paths["predictions"],
        "fold_assignments": paths["fold_assignments"],
        "metrics": paths["metrics"],
        "comparisons": paths["comparisons"],
        "selection": paths["selection"],
        "readiness": paths["readiness"],
        "explanations": paths["explanations"],
        "patch_diagnostics": paths["patch_diagnostics"],
        "bundle_manifest": paths["bundle_manifest"],
        "bundle_transformer": (
            paths["bundle_manifest"].parent / "feature_transformer.joblib"
        ),
        "bundle_estimator": (
            paths["bundle_manifest"].parent / "base_estimator.joblib"
        ),
        "report": paths["report"],
    }
    calibrator_path = (
        paths["bundle_manifest"].parent / "selected_calibrator.joblib"
    )
    if calibrator_path.is_file():
        artifact_paths["bundle_calibrator"] = calibrator_path
    artifacts = {
        name: _artifact(path, root=target)
        for name, path in artifact_paths.items()
    }
    manifest = {
        **core,
        "build_fingerprint": fingerprint,
        "git": _git_state(root),
        "role_audit": role_audit,
        "frozen_candidate_reproduction": reproduction,
        "cross_fit_audit": cross_fit.audit,
        "result": {
            "selected_calibration_method": selected_method,
            "calibration_readiness_gate_passed": readiness["passed"],
            "base_fit_rows": len(base),
            "calibration_rows": len(calibration),
            "calibration_prediction_rows_per_method": len(calibration),
            "locked_test_target_rows_used_for_modeling": 0,
            "locked_test_transform_rows": 0,
            "locked_test_prediction_rows": 0,
            "authenticated_api_requests": 0,
            "base_estimator_serialized": True,
            "selected_calibrator_serialized": selected_method != "raw",
            "bundle_frozen": True,
        },
        "bundle_validation": bundle_validation,
        "artifacts": artifacts,
    }
    _write_json(paths["manifest"], manifest)
    return _result_from_paths(fingerprint, target, paths)


__all__ = [
    "CalibrationExperimentError",
    "CalibrationExperimentResult",
    "run_calibration_experiment",
]
