"""Deterministic, development-only orchestration for Draft AI baselines.

This module is the Milestone 4B.1 boundary.  It consumes the verified M4A
working corpus, fits only the declared B0--B3 baselines, and evaluates only
past-only development folds plus the tuning interval.  Calibration and locked
test rows are deliberately unreachable from the fitting loop.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import warnings
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import scipy
import sklearn
from scipy.sparse import csr_matrix

from .baselines import (
    BASELINE_FEATURE_VARIANTS,
    BaselineId,
    baseline_contract_payload,
    baseline_fingerprint,
    create_unfitted_estimator,
)
from .contracts import (
    CURRENT_TEMPORAL_SPLIT,
    SPLIT_ROLE_CALIBRATION,
    SPLIT_ROLE_LOCKED_TEST,
    SPLIT_ROLE_TRAIN,
    SPLIT_ROLE_TUNING,
)
from .evaluation import (
    evaluate_probabilities,
    global_logistic_coefficient_explanations,
    grouped_bootstrap_confidence_intervals,
)
from .experiment_config import (
    BaselineExperimentConfig,
    RollingOriginFold,
    load_experiment_config,
)
from .features import DraftFeatureTransformer
from .loader import load_working_corpus, sha256_file
from .splits import build_split_manifest


EXPERIMENT_SCHEMA_VERSION = "draft-ai-baseline-experiment-v1"
PREDICTION_SCHEMA_VERSION = "draft-ai-development-predictions-v1"
EXPECTED_ROLLING_FOLDS = 7
_FORBIDDEN_EVALUATION_ROLES = frozenset(
    {SPLIT_ROLE_CALIBRATION, SPLIT_ROLE_LOCKED_TEST}
)
_PREDICTION_COLUMNS = (
    "evaluation_id",
    "evaluation_kind",
    "baseline_id",
    "sample_id",
    "source_match_id",
    "match_start_utc",
    "radiant_win",
    "radiant_win_probability",
)


class BaselineExperimentError(ValueError):
    """Raised when an experiment would violate its frozen development policy."""


@dataclass(frozen=True, slots=True)
class EvaluationWindow:
    """One strictly past-only training and evaluation window."""

    evaluation_id: str
    evaluation_kind: str
    train_start_utc: datetime
    train_end_utc: datetime
    evaluation_start_utc: datetime
    evaluation_end_utc: datetime


@dataclass(frozen=True, slots=True)
class BaselineExperimentResult:
    """Content-addressed outputs from one completed development experiment."""

    build_fingerprint: str
    output_directory: Path
    manifest_path: Path
    tuning_predictions_path: Path
    rolling_predictions_path: Path
    metrics_path: Path
    comparison_path: Path
    confidence_intervals_path: Path
    reliability_path: Path
    explanations_path: Path
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
        "baseline_experiment.py",
        "baselines.py",
        "contracts.py",
        "evaluation.py",
        "experiment_config.py",
        "features.py",
        "loader.py",
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


def _runtime_versions() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "duckdb": duckdb.__version__,
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "scipy": scipy.__version__,
        "scikit_learn": sklearn.__version__,
    }


def _baseline_ids(
    config: BaselineExperimentConfig,
) -> tuple[BaselineId, ...]:
    if config.baseline_ids != tuple(BaselineId):
        raise BaselineExperimentError(
            "M4B.1 must evaluate B0, B1, B2, and B3 in canonical order."
        )
    return config.baseline_ids


def _window_from_config(value: RollingOriginFold) -> EvaluationWindow:
    window = EvaluationWindow(
        evaluation_id=value.fold_id,
        evaluation_kind="rolling_origin",
        train_start_utc=value.train_start_utc,
        train_end_utc=value.train_end_utc,
        evaluation_start_utc=value.evaluation_start_utc,
        evaluation_end_utc=value.evaluation_end_utc,
    )
    if not (
        window.train_start_utc
        < window.train_end_utc
        <= window.evaluation_start_utc
        < window.evaluation_end_utc
    ):
        raise BaselineExperimentError(
            f"{window.evaluation_id} is not a strictly past-only fold."
        )
    tuning_end = next(
        interval.end_utc
        for interval in CURRENT_TEMPORAL_SPLIT.intervals
        if interval.role == SPLIT_ROLE_TUNING
    )
    if window.evaluation_end_utc > tuning_end:
        raise BaselineExperimentError(
            f"{window.evaluation_id} reaches a reserved future role."
        )
    return window


def _rolling_windows(
    config: BaselineExperimentConfig,
) -> tuple[EvaluationWindow, ...]:
    windows = tuple(
        _window_from_config(item)
        for item in config.rolling_origin_folds
    )
    if len(windows) != EXPECTED_ROLLING_FOLDS:
        raise BaselineExperimentError(
            f"M4B.1 requires exactly {EXPECTED_ROLLING_FOLDS} rolling folds."
        )
    if len({item.evaluation_id for item in windows}) != len(windows):
        raise BaselineExperimentError("Rolling fold IDs must be unique.")
    return windows


def _verify_m4a_pins(
    config: BaselineExperimentConfig,
    *,
    root: Path,
    corpus_config_path: Path,
    split_fingerprint: str,
) -> dict[str, object]:
    manifest_path = config.m4a_manifest_path
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BaselineExperimentError("Invalid pinned M4A manifest.") from error
    expected_build = config.m4a_build_fingerprint
    expected_split = config.split_manifest_fingerprint
    if manifest.get("build_fingerprint") != expected_build:
        raise BaselineExperimentError("M4A build fingerprint changed.")
    if split_fingerprint != expected_split or (
        manifest.get("split", {}).get("split_manifest_fingerprint")
        != expected_split
    ):
        raise BaselineExperimentError("M4A split fingerprint changed.")
    config_sha256 = sha256_file(corpus_config_path)
    if manifest.get("source", {}).get("config_sha256") != config_sha256:
        raise BaselineExperimentError("M4A corpus-config hash changed.")
    for artifact in manifest.get("artifacts", {}).values():
        artifact_path = manifest_path.parent / str(artifact["file"])
        if (
            not artifact_path.is_file()
            or sha256_file(artifact_path) != artifact["sha256"]
        ):
            raise BaselineExperimentError("A pinned M4A artifact changed.")
    return {
        "build_fingerprint": expected_build,
        "manifest_path": manifest_path.relative_to(root).as_posix(),
        "manifest_sha256": sha256_file(manifest_path),
        "split_manifest_fingerprint": expected_split,
        "corpus_config_sha256": config_sha256,
    }


def _joined_development_frame(
    corpus_frame: pd.DataFrame,
    split_manifest: pd.DataFrame,
) -> pd.DataFrame:
    roles = split_manifest[["sample_id", "split_role"]]
    joined = corpus_frame.merge(
        roles,
        on="sample_id",
        how="left",
        validate="one_to_one",
    )
    if joined["split_role"].isna().any():
        raise BaselineExperimentError("Split roles do not cover the corpus.")
    reserved = joined["split_role"].isin(_FORBIDDEN_EVALUATION_ROLES)
    joined.loc[reserved, "radiant_win"] = pd.NA
    return joined


def _tuning_window() -> EvaluationWindow:
    train = next(
        item
        for item in CURRENT_TEMPORAL_SPLIT.intervals
        if item.role == SPLIT_ROLE_TRAIN
    )
    tuning = next(
        item
        for item in CURRENT_TEMPORAL_SPLIT.intervals
        if item.role == SPLIT_ROLE_TUNING
    )
    return EvaluationWindow(
        evaluation_id="tuning",
        evaluation_kind="tuning",
        train_start_utc=train.start_utc,
        train_end_utc=train.end_utc,
        evaluation_start_utc=tuning.start_utc,
        evaluation_end_utc=tuning.end_utc,
    )


def _window_rows(
    joined: pd.DataFrame,
    window: EvaluationWindow,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    timestamps = joined["match_start_utc"]
    train = joined[
        timestamps.ge(window.train_start_utc)
        & timestamps.lt(window.train_end_utc)
    ].copy()
    evaluation = joined[
        timestamps.ge(window.evaluation_start_utc)
        & timestamps.lt(window.evaluation_end_utc)
    ].copy()
    if train.empty or evaluation.empty:
        raise BaselineExperimentError(
            f"{window.evaluation_id} contains an empty dataset role."
        )
    forbidden = set(evaluation["split_role"]).intersection(
        _FORBIDDEN_EVALUATION_ROLES
    )
    if forbidden:
        raise BaselineExperimentError(
            f"{window.evaluation_id} selects a reserved role: {sorted(forbidden)}"
        )
    overlap = set(train["source_match_id"]).intersection(
        evaluation["source_match_id"]
    )
    if overlap:
        raise BaselineExperimentError(
            f"{window.evaluation_id} crosses source-match groups."
        )
    return train, evaluation


def _positive_probabilities(estimator: object, matrix: csr_matrix) -> np.ndarray:
    classes = list(getattr(estimator, "classes_"))
    try:
        positive_position = classes.index(1)
    except ValueError as error:
        raise BaselineExperimentError(
            "A fitted baseline does not expose the positive class."
        ) from error
    values = np.asarray(estimator.predict_proba(matrix)[:, positive_position])
    if values.shape != (matrix.shape[0],) or not np.isfinite(values).all():
        raise BaselineExperimentError("Baseline probabilities are malformed.")
    return values


def _fit_one(
    baseline_id: BaselineId,
    train: pd.DataFrame,
    evaluation: pd.DataFrame,
    *,
    random_state: int,
    coefficient_top_k: int,
) -> tuple[np.ndarray, dict[str, object]]:
    estimator = create_unfitted_estimator(
        baseline_id,
        random_state=random_state,
    )
    variant = BASELINE_FEATURE_VARIANTS[baseline_id]
    if variant is None:
        train_matrix = csr_matrix((len(train), 1), dtype=np.int8)
        evaluation_matrix = csr_matrix((len(evaluation), 1), dtype=np.int8)
        feature_names = ("empirical_prior_input",)
        feature_fingerprint = None
    else:
        transformer = DraftFeatureTransformer(variant).fit(train)
        train_matrix = transformer.transform(train)
        evaluation_matrix = transformer.transform(evaluation)
        feature_names = tuple(transformer.get_feature_names_out())
        feature_fingerprint = transformer.fingerprint

    target = train["radiant_win"].astype("int8").to_numpy()
    if len(np.unique(target)) != 2:
        raise BaselineExperimentError("Baseline training requires both classes.")
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="'penalty' was deprecated in version 1.8",
            category=FutureWarning,
            module=r"sklearn\.linear_model\._logistic",
        )
        estimator.fit(train_matrix, target)
    probabilities = _positive_probabilities(estimator, evaluation_matrix)
    if baseline_id == BaselineId.B0_EMPIRICAL_PRIOR:
        explanation = {
            "kind": "empirical_prior",
            "training_rows": len(train),
            "training_positive_rate": float(target.mean()),
            "coefficients": [],
            "top_positive": [],
            "top_negative": [],
        }
    else:
        explanation = global_logistic_coefficient_explanations(
            estimator,
            train_matrix,
            feature_names,
            top_k=coefficient_top_k,
        )
    return probabilities, {
        "baseline_id": baseline_id.value,
        "baseline_fingerprint": baseline_fingerprint(
            baseline_id,
            random_state=random_state,
        ),
        "baseline_contract": baseline_contract_payload(
            baseline_id,
            random_state=random_state,
        ),
        "feature_fingerprint": feature_fingerprint,
        "explanation": explanation,
    }


def _prediction_frame(
    evaluation: pd.DataFrame,
    probabilities: np.ndarray,
    *,
    window: EvaluationWindow,
    baseline_id: BaselineId,
) -> pd.DataFrame:
    result = evaluation[
        [
            "sample_id",
            "source_match_id",
            "match_start_utc",
            "radiant_win",
        ]
    ].copy()
    result.insert(0, "baseline_id", baseline_id.value)
    result.insert(0, "evaluation_kind", window.evaluation_kind)
    result.insert(0, "evaluation_id", window.evaluation_id)
    result["radiant_win_probability"] = probabilities.astype("float64")
    return result[list(_PREDICTION_COLUMNS)].sort_values(
        ["baseline_id", "match_start_utc", "source_match_id", "sample_id"],
        kind="mergesort",
    )


def _write_parquet(frame: pd.DataFrame, path: Path) -> None:
    with duckdb.connect() as connection:
        connection.register("prediction_frame", frame)
        escaped = path.resolve().as_posix().replace("'", "''")
        connection.execute(
            "COPY (SELECT * FROM prediction_frame) "
            f"TO '{escaped}' (FORMAT PARQUET, COMPRESSION ZSTD)"
        )


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _artifact(path: Path) -> dict[str, object]:
    return {
        "file": path.name,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def compare_development_baselines(
    evaluations: list[dict[str, object]],
    selection_policy: dict[str, Any],
) -> dict[str, object]:
    """Apply the predeclared B0-relative development selection policy."""

    baseline_ids = tuple(item.value for item in BaselineId)
    tuning: dict[str, dict[str, float]] = {}
    rolling: dict[str, dict[str, dict[str, float]]] = {
        baseline_id: {} for baseline_id in baseline_ids
    }
    for record in evaluations:
        baseline_id = str(record["baseline_id"])
        if baseline_id not in rolling:
            raise BaselineExperimentError(
                f"Unknown baseline evaluation: {baseline_id}."
            )
        metrics = {
            str(name): float(value)
            for name, value in dict(record["metrics"]).items()
            if value is not None
        }
        if record["evaluation_kind"] == "tuning":
            if baseline_id in tuning:
                raise BaselineExperimentError(
                    f"Duplicate tuning evaluation for {baseline_id}."
                )
            tuning[baseline_id] = metrics
        elif record["evaluation_kind"] == "rolling_origin":
            fold_id = str(record["evaluation_id"])
            if fold_id in rolling[baseline_id]:
                raise BaselineExperimentError(
                    f"Duplicate rolling evaluation for {baseline_id}/{fold_id}."
                )
            rolling[baseline_id][fold_id] = metrics
        else:
            raise BaselineExperimentError("Unknown development evaluation kind.")

    if set(tuning) != set(baseline_ids):
        raise BaselineExperimentError("Tuning evaluations are incomplete.")
    fold_sets = {tuple(sorted(values)) for values in rolling.values()}
    if len(fold_sets) != 1 or len(next(iter(fold_sets), ())) != EXPECTED_ROLLING_FOLDS:
        raise BaselineExperimentError("Rolling evaluations are incomplete.")

    b0_tuning = tuning[BaselineId.B0_EMPIRICAL_PRIOR.value]
    b0_folds = rolling[BaselineId.B0_EMPIRICAL_PRIOR.value]
    b0_mean_log_loss = float(
        np.mean([values["log_loss"] for values in b0_folds.values()])
    )
    b0_mean_brier = float(
        np.mean([values["brier_score"] for values in b0_folds.values()])
    )
    maximum_regression = float(
        selection_policy["maximum_single_fold_log_loss_regression_vs_b0"]
    )
    require_tuning_brier = bool(
        selection_policy["require_tuning_brier_improvement_vs_b0"]
    )
    require_rolling_brier = bool(
        selection_policy[
            "require_mean_rolling_brier_improvement_vs_b0"
        ]
    )
    complexity_order = tuple(
        str(value) for value in selection_policy["complexity_order"]
    )
    if complexity_order != ("B1", "B2", "B3"):
        raise BaselineExperimentError("Baseline complexity order changed.")

    summaries: list[dict[str, object]] = []
    eligible: list[str] = []
    for baseline_id in baseline_ids:
        fold_metrics = rolling[baseline_id]
        mean_log_loss = float(
            np.mean([values["log_loss"] for values in fold_metrics.values()])
        )
        mean_brier = float(
            np.mean([values["brier_score"] for values in fold_metrics.values()])
        )
        fold_regressions = {
            fold_id: values["log_loss"] - b0_folds[fold_id]["log_loss"]
            for fold_id, values in fold_metrics.items()
        }
        gate_results = {
            "tuning_log_loss_beats_b0": (
                tuning[baseline_id]["log_loss"] < b0_tuning["log_loss"]
            ),
            "mean_rolling_log_loss_beats_b0": (
                mean_log_loss < b0_mean_log_loss
            ),
            "tuning_brier_beats_b0": (
                tuning[baseline_id]["brier_score"]
                < b0_tuning["brier_score"]
            ),
            "mean_rolling_brier_beats_b0": mean_brier < b0_mean_brier,
            "maximum_fold_regression_within_limit": (
                max(fold_regressions.values()) <= maximum_regression
            ),
        }
        qualifies = (
            baseline_id != BaselineId.B0_EMPIRICAL_PRIOR.value
            and gate_results["tuning_log_loss_beats_b0"]
            and gate_results["mean_rolling_log_loss_beats_b0"]
            and (
                gate_results["tuning_brier_beats_b0"]
                or not require_tuning_brier
            )
            and (
                gate_results["mean_rolling_brier_beats_b0"]
                or not require_rolling_brier
            )
            and gate_results["maximum_fold_regression_within_limit"]
        )
        if qualifies:
            eligible.append(baseline_id)
        summaries.append(
            {
                "baseline_id": baseline_id,
                "tuning_metrics": tuning[baseline_id],
                "mean_rolling_log_loss": mean_log_loss,
                "mean_rolling_brier_score": mean_brier,
                "maximum_fold_log_loss_regression_vs_b0": max(
                    fold_regressions.values()
                ),
                "gate_results": gate_results,
                "qualifies_as_development_candidate": qualifies,
            }
        )

    selected: str | None = None
    if eligible:
        best_log_loss = min(
            tuning[baseline_id]["log_loss"] for baseline_id in eligible
        )
        practical_tie = float(selection_policy["practical_log_loss_tie"])
        tied = {
            baseline_id
            for baseline_id in eligible
            if tuning[baseline_id]["log_loss"] <= best_log_loss + practical_tie
        }
        selected = next(
            baseline_id
            for baseline_id in complexity_order
            if baseline_id in tied
        )

    return {
        "selection_scope": "development_only",
        "result_label": str(selection_policy["result_label"]),
        "selected_baseline_id": selected,
        "selection_status": (
            "development_candidate_selected"
            if selected is not None
            else "no_baseline_passed_all_development_gates"
        ),
        "not_a_final_champion": True,
        "calibration_or_locked_test_used": False,
        "reference_baseline_id": BaselineId.B0_EMPIRICAL_PRIOR.value,
        "policy": selection_policy,
        "summaries": summaries,
    }


def _render_report(
    fingerprint: str,
    evaluations: list[dict[str, object]],
    source: dict[str, object],
    comparison: dict[str, object],
) -> str:
    tuning = [
        item
        for item in evaluations
        if item["evaluation_kind"] == "tuning"
    ]
    return "\n".join(
        [
            "# Milestone 4B.1: Baseline Modeling",
            "",
            f"- Build fingerprint: `{fingerprint}`",
            f"- Working corpus: `{source['corpus_id']}`",
            f"- M4A build: `{source['m4a']['build_fingerprint']}`",
            f"- Baselines: `{len(tuning)}`",
            (
                "- Development candidate: "
                f"`{comparison['selected_baseline_id'] or 'none'}`"
            ),
            f"- Past-only rolling folds: `{EXPECTED_ROLLING_FOLDS}`",
            "- Calibration rows predicted: `0`",
            "- Locked-test rows predicted: `0`",
            "- Hyperparameter searches: `0`",
            "- Model serialization: `none`",
            "- Authenticated API requests: `0`",
            "",
        ]
    )


def run_baseline_experiment(
    experiment_config_path: Path,
    *,
    output_root: Path = Path("models/m4b"),
    repository_root: Path | None = None,
) -> BaselineExperimentResult:
    """Fit and evaluate the fixed baselines on development data only."""

    root = (
        repository_root.resolve()
        if repository_root is not None
        else Path(__file__).resolve().parents[2]
    )
    config = load_experiment_config(
        experiment_config_path.resolve(),
        repository_root=root,
    )
    corpus = load_working_corpus(config.corpus_config_path)
    split = build_split_manifest(corpus.frame)
    m4a = _verify_m4a_pins(
        config,
        root=root,
        corpus_config_path=config.corpus_config_path,
        split_fingerprint=split.fingerprint,
    )
    windows = (_tuning_window(), *_rolling_windows(config))
    baseline_ids = _baseline_ids(config)
    joined = _joined_development_frame(corpus.frame, split.manifest)

    random_state = config.evaluation.random_seed
    n_resamples = config.evaluation.bootstrap_replicates
    n_bins = config.evaluation.reliability_bins
    confidence_level = config.evaluation.bootstrap_confidence_level
    coefficient_top_k = config.evaluation.coefficient_top_k
    source = {
        "corpus_id": corpus.config.corpus_id,
        "corpus_config_path": (
            config.corpus_config_path.relative_to(root).as_posix()
        ),
        "corpus_config_sha256": sha256_file(config.corpus_config_path),
        "m4a": m4a,
        "split_manifest_fingerprint": split.fingerprint,
        "rows": len(corpus.frame),
        "source_matches": int(corpus.frame["source_match_id"].nunique()),
    }
    core = {
        "experiment_schema_version": EXPERIMENT_SCHEMA_VERSION,
        "prediction_schema_version": PREDICTION_SCHEMA_VERSION,
        "experiment_id": config.experiment_id,
        "experiment_config_fingerprint": config.fingerprint,
        "config_path": config.config_path.relative_to(root).as_posix(),
        "config_sha256": sha256_file(config.config_path),
        "modeling_source_sha256": _source_sha256(),
        "source": source,
        "baselines": [item.value for item in baseline_ids],
        "evaluation_windows": [
            {
                "evaluation_id": window.evaluation_id,
                "evaluation_kind": window.evaluation_kind,
                "train_start_utc": window.train_start_utc.isoformat(),
                "train_end_utc": window.train_end_utc.isoformat(),
                "evaluation_start_utc": (
                    window.evaluation_start_utc.isoformat()
                ),
                "evaluation_end_utc": window.evaluation_end_utc.isoformat(),
            }
            for window in windows
        ],
        "evaluation_policy": {
            "selection_roles": [SPLIT_ROLE_TRAIN, SPLIT_ROLE_TUNING],
            "rolling_folds": EXPECTED_ROLLING_FOLDS,
            "calibration_predictions_allowed": False,
            "locked_test_predictions_allowed": False,
        },
        "random_state": random_state,
        "bootstrap": {
            "resamples": n_resamples,
            "confidence_level": confidence_level,
        },
        "reliability_bins": n_bins,
        "runtime_versions": _runtime_versions(),
        "git": _git_state(root),
    }
    fingerprint = _sha256_json(core)
    target = output_root.resolve() / f"build_{fingerprint}"
    manifest_path = target / "experiment_manifest.json"
    paths = {
        "tuning_predictions": target / "tuning_predictions.parquet",
        "rolling_predictions": target / "rolling_predictions.parquet",
        "metrics": target / "metrics.json",
        "comparison": target / "baseline_comparison.json",
        "confidence_intervals": target / "confidence_intervals.json",
        "reliability": target / "reliability.json",
        "explanations": target / "coefficient_explanations.json",
        "report": target / "experiment_report.md",
    }
    if target.exists():
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise BaselineExperimentError(
                "Existing M4B build is incomplete."
            ) from error
        if existing.get("build_fingerprint") != fingerprint:
            raise BaselineExperimentError("Existing M4B build fingerprint changed.")
        for artifact in existing.get("artifacts", {}).values():
            path = target / artifact["file"]
            if not path.is_file() or sha256_file(path) != artifact["sha256"]:
                raise BaselineExperimentError("Existing M4B artifact changed.")
        return BaselineExperimentResult(
            fingerprint,
            target,
            manifest_path,
            paths["tuning_predictions"],
            paths["rolling_predictions"],
            paths["metrics"],
            paths["comparison"],
            paths["confidence_intervals"],
            paths["reliability"],
            paths["explanations"],
            paths["report"],
        )

    target.mkdir(parents=True)
    tuning_predictions: list[pd.DataFrame] = []
    rolling_predictions: list[pd.DataFrame] = []
    metrics: list[dict[str, object]] = []
    intervals: list[dict[str, object]] = []
    reliability: list[dict[str, object]] = []
    explanations: list[dict[str, object]] = []

    for window in windows:
        train, evaluation = _window_rows(joined, window)
        for baseline_id in baseline_ids:
            probabilities, fit_record = _fit_one(
                baseline_id,
                train,
                evaluation,
                random_state=random_state,
                coefficient_top_k=coefficient_top_k,
            )
            predictions = _prediction_frame(
                evaluation,
                probabilities,
                window=window,
                baseline_id=baseline_id,
            )
            target_list = evaluation["radiant_win"].astype("int8").tolist()
            metric = evaluate_probabilities(
                target_list,
                probabilities,
                n_bins=n_bins,
            )
            confidence = grouped_bootstrap_confidence_intervals(
                target_list,
                probabilities,
                evaluation["source_match_id"].tolist(),
                confidence_level=confidence_level,
                n_resamples=n_resamples,
                random_state=random_state,
                n_bins=n_bins,
            )
            identity = {
                "evaluation_id": window.evaluation_id,
                "evaluation_kind": window.evaluation_kind,
                "baseline_id": baseline_id.value,
                "training_rows": len(train),
                "evaluation_rows": len(evaluation),
            }
            metrics.append({**identity, "metrics": metric["metrics"]})
            intervals.append({**identity, "bootstrap": confidence})
            reliability.append(
                {**identity, "reliability_bins": metric["reliability_bins"]}
            )
            explanations.append(
                {
                    **identity,
                    **{
                        key: value
                        for key, value in fit_record.items()
                        if key != "explanation"
                    },
                    "explanation": fit_record["explanation"],
                }
            )
            (
                tuning_predictions
                if window.evaluation_kind == "tuning"
                else rolling_predictions
            ).append(predictions)

    tuning_frame = pd.concat(tuning_predictions, ignore_index=True)
    rolling_frame = pd.concat(rolling_predictions, ignore_index=True)
    _write_parquet(tuning_frame, paths["tuning_predictions"])
    _write_parquet(rolling_frame, paths["rolling_predictions"])
    _write_json(paths["metrics"], {"evaluations": metrics})
    comparison = compare_development_baselines(
        metrics,
        config.selection_policy,
    )
    _write_json(paths["comparison"], comparison)
    _write_json(
        paths["confidence_intervals"],
        {"evaluations": intervals},
    )
    _write_json(paths["reliability"], {"evaluations": reliability})
    _write_json(paths["explanations"], {"evaluations": explanations})
    paths["report"].write_text(
        _render_report(fingerprint, metrics, source, comparison),
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
            "tuning_prediction_rows": len(tuning_frame),
            "rolling_prediction_rows": len(rolling_frame),
            "evaluation_records": len(metrics),
            "calibration_prediction_rows": 0,
            "locked_test_prediction_rows": 0,
            "hyperparameter_search_performed": False,
            "model_calibration_performed": False,
            "model_serialization_performed": False,
            "selected_development_candidate": comparison[
                "selected_baseline_id"
            ],
            "authenticated_api_requests": 0,
        },
        "artifacts": artifacts,
    }
    _write_json(manifest_path, manifest)
    return BaselineExperimentResult(
        fingerprint,
        target,
        manifest_path,
        paths["tuning_predictions"],
        paths["rolling_predictions"],
        paths["metrics"],
        paths["comparison"],
        paths["confidence_intervals"],
        paths["reliability"],
        paths["explanations"],
        paths["report"],
    )


__all__ = [
    "BaselineExperimentError",
    "BaselineExperimentResult",
    "EvaluationWindow",
    "compare_development_baselines",
    "run_baseline_experiment",
]
