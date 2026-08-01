"""Bounded, development-only orchestration for the M4B.2 Draft AI experiment."""

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
import numpy as np
import pandas as pd
import scipy
import sklearn
from scipy.sparse import csr_matrix
from sklearn.linear_model import LogisticRegression

from .baselines import (
    BaselineId,
    baseline_contract_payload,
    baseline_fingerprint,
)
from .contracts import (
    SPLIT_ROLE_CALIBRATION,
    SPLIT_ROLE_LOCKED_TEST,
)
from .evaluation import (
    evaluate_probabilities,
    global_logistic_coefficient_explanations,
)
from .features import DraftFeatureTransformer, FeatureVariant
from .loader import load_working_corpus, sha256_file
from .recency import RecencyPolicy, select_training_rows
from .recency_config import (
    RecencyCandidate,
    RecencyExperimentConfig,
    load_recency_experiment_config,
)
from .recency_evaluation import patch_group_descriptive_metrics
from .recency_selection import select_recency_candidate
from .splits import build_split_manifest


EXPERIMENT_SCHEMA_VERSION = "draft-ai-recency-experiment-run-v1"
PREDICTION_SCHEMA_VERSION = "draft-ai-recency-development-predictions-v1"
_FORBIDDEN_ROLES = frozenset(
    {SPLIT_ROLE_CALIBRATION, SPLIT_ROLE_LOCKED_TEST}
)
_PREDICTION_COLUMNS = (
    "candidate_id",
    "history_policy_id",
    "C",
    "evaluation_id",
    "sample_id",
    "source_match_id",
    "match_start_utc",
    "patch",
    "radiant_win",
    "candidate_probability",
    "policy_matched_b0_probability",
    "canonical_b0_probability",
)


class RecencyExperimentError(ValueError):
    """Raised when M4B.2 violates its frozen development-only contract."""


@dataclass(frozen=True, slots=True)
class RecencyExperimentResult:
    """Content-addressed outputs from one completed M4B.2 experiment."""

    build_fingerprint: str
    output_directory: Path
    manifest_path: Path
    predictions_path: Path
    metrics_path: Path
    selection_path: Path
    reliability_path: Path
    weight_audits_path: Path
    explanations_path: Path
    patch_diagnostics_path: Path
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
        "baselines.py",
        "contracts.py",
        "evaluation.py",
        "features.py",
        "loader.py",
        "recency.py",
        "recency_config.py",
        "recency_evaluation.py",
        "recency_experiment.py",
        "recency_selection.py",
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


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RecencyExperimentError(f"Cannot read {label}.") from error
    if not isinstance(value, dict):
        raise RecencyExperimentError(f"{label} must be a JSON object.")
    return value


def _source_lineage(
    config: RecencyExperimentConfig,
    *,
    root: Path,
    observed_split_fingerprint: str,
) -> dict[str, object]:
    if observed_split_fingerprint != config.split_manifest_fingerprint:
        raise RecencyExperimentError("The M4A split fingerprint changed.")
    if sha256_file(config.corpus_config_path) != config.corpus_config_sha256:
        raise RecencyExperimentError("The M4A corpus config changed.")

    m4a_manifest = _read_json(
        config.m4a.manifest_path,
        label="the pinned M4A manifest",
    )
    if (
        m4a_manifest.get("build_fingerprint")
        != config.m4a.build_fingerprint
        or m4a_manifest.get("source", {}).get("config_sha256")
        != config.corpus_config_sha256
        or m4a_manifest.get("split", {}).get(
            "split_manifest_fingerprint"
        )
        != config.split_manifest_fingerprint
    ):
        raise RecencyExperimentError("The M4A source lineage changed.")

    m4b1_manifest = _read_json(
        config.m4b1.build.manifest_path,
        label="the pinned M4B.1 manifest",
    )
    m4b1_result = m4b1_manifest.get("result", {})
    if (
        m4b1_manifest.get("build_fingerprint")
        != config.m4b1.build.build_fingerprint
        or m4b1_manifest.get("source", {}).get(
            "split_manifest_fingerprint"
        )
        != config.split_manifest_fingerprint
        or m4b1_result.get("calibration_prediction_rows") != 0
        or m4b1_result.get("locked_test_prediction_rows") != 0
        or m4b1_result.get("authenticated_api_requests") != 0
    ):
        raise RecencyExperimentError("The M4B.1 lineage or safety result changed.")

    return {
        "corpus_id": config.corpus_id,
        "corpus_config_path": (
            config.corpus_config_path.relative_to(root).as_posix()
        ),
        "corpus_config_sha256": config.corpus_config_sha256,
        "split_manifest_fingerprint": observed_split_fingerprint,
        "m4a": {
            "build_fingerprint": config.m4a.build_fingerprint,
            "manifest_path": (
                config.m4a.manifest_path.relative_to(root).as_posix()
            ),
            "manifest_sha256": config.m4a.manifest_sha256,
        },
        "m4b1": {
            "build_fingerprint": config.m4b1.build.build_fingerprint,
            "manifest_path": (
                config.m4b1.build.manifest_path.relative_to(root).as_posix()
            ),
            "manifest_sha256": config.m4b1.build.manifest_sha256,
            "rolling_predictions_sha256": next(
                artifact.sha256
                for artifact in config.m4b1.build.artifacts
                if artifact.name == "rolling_predictions"
            ),
        },
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
        raise RecencyExperimentError("Split roles do not cover the corpus.")
    reserved = joined["split_role"].isin(_FORBIDDEN_ROLES)
    joined.loc[reserved, "radiant_win"] = pd.NA
    if not joined.loc[reserved, "radiant_win"].isna().all():
        raise RecencyExperimentError("Reserved targets were not masked.")
    return joined


def _window_rows(
    joined: pd.DataFrame,
    fold: object,
    config: RecencyExperimentConfig,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    timestamps = joined["match_start_utc"]
    training = joined[
        timestamps.ge(fold.train_start_utc)
        & timestamps.lt(fold.train_end_utc)
    ].copy()
    evaluation = joined[
        timestamps.ge(fold.evaluation_start_utc)
        & timestamps.lt(fold.evaluation_end_utc)
    ].copy()
    if training.empty or evaluation.empty:
        raise RecencyExperimentError(f"{fold.fold_id} contains an empty role.")
    for role in sorted(set(training["split_role"])):
        config.assert_role_allowed(str(role), purpose="fit")
    for role in sorted(set(evaluation["split_role"])):
        config.assert_role_allowed(str(role), purpose="evaluate")
    if training["radiant_win"].isna().any():
        raise RecencyExperimentError(f"{fold.fold_id} training labels are missing.")
    if evaluation["radiant_win"].isna().any():
        raise RecencyExperimentError(
            f"{fold.fold_id} evaluation labels are unavailable."
        )
    overlap = set(training["source_match_id"]).intersection(
        evaluation["source_match_id"]
    )
    if overlap:
        raise RecencyExperimentError(
            f"{fold.fold_id} crosses source-match groups."
        )
    return training, evaluation


def _candidate_fingerprint(
    candidate: RecencyCandidate,
    *,
    parent_b1_fingerprint: str,
    random_state: int,
) -> str:
    return _sha256_json(
        {
            "candidate_id": candidate.candidate_id,
            "history_policy_id": candidate.history_policy_id,
            "C": candidate.regularization_c,
            "parent_baseline_id": "B1",
            "parent_baseline_fingerprint": parent_b1_fingerprint,
            "random_state": random_state,
        }
    )


def _estimator(
    config: RecencyExperimentConfig,
    candidate: RecencyCandidate,
) -> LogisticRegression:
    return LogisticRegression(
        C=candidate.regularization_c,
        class_weight=config.estimator.class_weight,
        max_iter=config.estimator.max_iter,
        penalty=config.estimator.penalty,
        random_state=config.estimator.random_seed,
        solver=config.estimator.solver,
    )


def _fit_estimator(
    estimator: LogisticRegression,
    matrix: csr_matrix,
    targets: np.ndarray,
    *,
    policy: RecencyPolicy,
    sample_weights: np.ndarray,
) -> None:
    kwargs: dict[str, object] = {}
    if policy == RecencyPolicy.FULL_EXP180:
        kwargs["sample_weight"] = sample_weights
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="'penalty' was deprecated in version 1.8",
            category=FutureWarning,
            module=r"sklearn\.linear_model\._logistic",
        )
        estimator.fit(matrix, targets, **kwargs)


def _positive_probabilities(
    estimator: LogisticRegression,
    matrix: csr_matrix,
) -> np.ndarray:
    classes = list(estimator.classes_)
    if 1 not in classes:
        raise RecencyExperimentError("A candidate lacks the positive class.")
    values = np.asarray(
        estimator.predict_proba(matrix)[:, classes.index(1)],
        dtype=np.float64,
    )
    if values.shape != (matrix.shape[0],) or not np.isfinite(values).all():
        raise RecencyExperimentError("Candidate probabilities are malformed.")
    return values


def _prior(targets: np.ndarray, weights: np.ndarray | None = None) -> float:
    value = float(
        targets.mean()
        if weights is None
        else np.average(targets, weights=weights)
    )
    if not 0 < value < 1:
        raise RecencyExperimentError("A B0 reference prior is degenerate.")
    return value


def _prediction_frame(
    evaluation: pd.DataFrame,
    *,
    candidate: RecencyCandidate,
    fold_id: str,
    probabilities: np.ndarray,
    policy_prior: float,
    canonical_prior: float,
) -> pd.DataFrame:
    result = evaluation[
        [
            "sample_id",
            "source_match_id",
            "match_start_utc",
            "patch",
            "radiant_win",
        ]
    ].copy()
    result.insert(0, "evaluation_id", fold_id)
    result.insert(0, "C", candidate.regularization_c)
    result.insert(0, "history_policy_id", candidate.history_policy_id)
    result.insert(0, "candidate_id", candidate.candidate_id)
    result["radiant_win"] = result["radiant_win"].astype("int8")
    result["candidate_probability"] = probabilities
    result["policy_matched_b0_probability"] = policy_prior
    result["canonical_b0_probability"] = canonical_prior
    return result[list(_PREDICTION_COLUMNS)]


def _reference_metrics(
    targets: np.ndarray,
    probability: float,
    *,
    n_bins: int,
) -> dict[str, object]:
    return evaluate_probabilities(
        targets,
        np.full(len(targets), probability, dtype=np.float64),
        n_bins=n_bins,
    )["metrics"]


def _m4b1_rolling_path(config: RecencyExperimentConfig) -> Path:
    artifact = next(
        (
            item
            for item in config.m4b1.build.artifacts
            if item.name == "rolling_predictions"
        ),
        None,
    )
    if artifact is None:
        raise RecencyExperimentError("M4B.1 rolling predictions are not pinned.")
    return config.m4b1.build.manifest_path.parent / artifact.file


def _verify_m4b1_reproduction(
    predictions: pd.DataFrame,
    config: RecencyExperimentConfig,
) -> dict[str, object]:
    candidate_id = "b1_full_uniform_c1"
    reproduced = predictions[
        predictions["candidate_id"] == candidate_id
    ][
        [
            "evaluation_id",
            "sample_id",
            "source_match_id",
            "radiant_win",
            "candidate_probability",
        ]
    ].copy()
    with duckdb.connect() as connection:
        parent = connection.execute(
            "SELECT evaluation_id, sample_id, source_match_id, radiant_win, "
            "radiant_win_probability "
            "FROM read_parquet(?) WHERE baseline_id = 'B1' "
            "ORDER BY evaluation_id, sample_id",
            [str(_m4b1_rolling_path(config))],
        ).fetchdf()
    reproduced = reproduced.sort_values(
        ["evaluation_id", "sample_id"],
        kind="mergesort",
    ).reset_index(drop=True)
    parent = parent.reset_index(drop=True)
    if len(reproduced) != len(parent):
        raise RecencyExperimentError("M4B.1 reproduction row count changed.")
    for column in (
        "evaluation_id",
        "sample_id",
        "source_match_id",
        "radiant_win",
    ):
        if not np.array_equal(
            reproduced[column].to_numpy(),
            parent[column].to_numpy(),
        ):
            raise RecencyExperimentError(
                f"M4B.1 reproduction alignment changed: {column}."
            )
    difference = np.abs(
        reproduced["candidate_probability"].to_numpy(dtype=np.float64)
        - parent["radiant_win_probability"].to_numpy(dtype=np.float64)
    )
    maximum = float(difference.max(initial=0.0))
    if maximum > 1e-12:
        raise RecencyExperimentError(
            "Full-history C=1 does not reproduce the pinned M4B.1 B1 result."
        )
    return {
        "candidate_id": candidate_id,
        "rows": len(reproduced),
        "maximum_absolute_probability_difference": maximum,
        "tolerance": 1e-12,
        "passed": True,
        "parent_predictions_sha256": sha256_file(
            _m4b1_rolling_path(config)
        ),
    }


def _write_parquet(frame: pd.DataFrame, path: Path) -> None:
    with duckdb.connect() as connection:
        connection.register("artifact_frame", frame)
        escaped = path.resolve().as_posix().replace("'", "''")
        connection.execute(
            "COPY (SELECT * FROM artifact_frame) "
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


def _render_report(
    *,
    fingerprint: str,
    config: RecencyExperimentConfig,
    selection: dict[str, object],
    reproduction: dict[str, object],
) -> str:
    return "\n".join(
        [
            "# Milestone 4B.2: B1 Regularization and Recency",
            "",
            f"- Build fingerprint: `{fingerprint}`",
            f"- Candidate configurations: `{len(config.candidates)}`",
            (
                "- Selected development candidate: "
                f"`{selection['selected_candidate_id'] or 'none'}`"
            ),
            (
                "- M4B.1 B1 reproduction maximum difference: "
                f"`{reproduction['maximum_absolute_probability_difference']}`"
            ),
            "- Selection scope: `2025-Q1 through 2025-Q3 development only`",
            "- Calibration rows predicted: `0`",
            "- Locked-test rows predicted: `0`",
            "- Authenticated API requests: `0`",
            "- Model serialization: `none`",
            "",
        ]
    )


def _result_from_paths(
    fingerprint: str,
    target: Path,
    manifest_path: Path,
    paths: dict[str, Path],
) -> RecencyExperimentResult:
    return RecencyExperimentResult(
        fingerprint,
        target,
        manifest_path,
        paths["predictions"],
        paths["metrics"],
        paths["selection"],
        paths["reliability"],
        paths["weight_audits"],
        paths["explanations"],
        paths["patch_diagnostics"],
        paths["report"],
    )


def run_recency_experiment(
    experiment_config_path: Path,
    *,
    output_root: Path = Path("models/m4b2"),
    repository_root: Path | None = None,
) -> RecencyExperimentResult:
    """Fit and compare exactly nine B1 candidates on development data only."""

    root = (
        repository_root.resolve()
        if repository_root is not None
        else Path(__file__).resolve().parents[2]
    )
    config = load_recency_experiment_config(
        experiment_config_path.resolve(),
        repository_root=root,
    )
    corpus = load_working_corpus(config.corpus_config_path)
    split = build_split_manifest(corpus.frame)
    source = _source_lineage(
        config,
        root=root,
        observed_split_fingerprint=split.fingerprint,
    )
    joined = _joined_development_frame(corpus.frame, split.manifest)

    parent_b1_contract = baseline_contract_payload(
        BaselineId.B1_PICK_PRESENCE,
        random_state=config.estimator.random_seed,
    )
    expected_parent_parameters = {
        "C": 1.0,
        "class_weight": config.estimator.class_weight,
        "max_iter": config.estimator.max_iter,
        "penalty": config.estimator.penalty,
        "random_state": config.estimator.random_seed,
        "solver": config.estimator.solver,
    }
    if parent_b1_contract["parameters"] != expected_parent_parameters:
        raise RecencyExperimentError("The canonical B1 parent contract changed.")
    parent_b1_fingerprint = baseline_fingerprint(
        BaselineId.B1_PICK_PRESENCE,
        random_state=config.estimator.random_seed,
    )
    candidates = [
        {
            "candidate_id": candidate.candidate_id,
            "history_policy_id": candidate.history_policy_id,
            "C": candidate.regularization_c,
            "fingerprint": _candidate_fingerprint(
                candidate,
                parent_b1_fingerprint=parent_b1_fingerprint,
                random_state=config.estimator.random_seed,
            ),
        }
        for candidate in config.candidates
    ]
    core = {
        "experiment_schema_version": EXPERIMENT_SCHEMA_VERSION,
        "prediction_schema_version": PREDICTION_SCHEMA_VERSION,
        "experiment_id": config.experiment_id,
        "experiment_config_fingerprint": config.fingerprint,
        "config_path": config.config_path.relative_to(root).as_posix(),
        "config_sha256": sha256_file(config.config_path),
        "modeling_source_sha256": _source_sha256(),
        "source": {
            **source,
            "rows": len(corpus.frame),
            "source_matches": int(corpus.frame["source_match_id"].nunique()),
        },
        "parent_b1": {
            "fingerprint": parent_b1_fingerprint,
            "contract": parent_b1_contract,
        },
        "candidates": candidates,
        "selection_scope": list(
            config.selection_policy["selection_fold_ids"]
        ),
        "safety": config.safety,
        "runtime_versions": _runtime_versions(),
        "git": _git_state(root),
    }
    fingerprint = _sha256_json(core)
    target = output_root.resolve() / f"build_{fingerprint}"
    manifest_path = target / "experiment_manifest.json"
    paths = {
        "predictions": target / "development_predictions.parquet",
        "metrics": target / "fold_metrics.json",
        "selection": target / "selection.json",
        "reliability": target / "reliability.json",
        "weight_audits": target / "weight_audits.json",
        "explanations": target / "coefficient_explanations.json",
        "patch_diagnostics": target / "patch_diagnostics.json",
        "report": target / "experiment_report.md",
    }
    if target.exists():
        existing = _read_json(manifest_path, label="the existing M4B.2 manifest")
        if existing.get("build_fingerprint") != fingerprint:
            raise RecencyExperimentError("Existing M4B.2 fingerprint changed.")
        for artifact in existing.get("artifacts", {}).values():
            artifact_path = target / str(artifact["file"])
            if (
                not artifact_path.is_file()
                or sha256_file(artifact_path) != artifact["sha256"]
            ):
                raise RecencyExperimentError("An M4B.2 artifact changed.")
        return _result_from_paths(
            fingerprint,
            target,
            manifest_path,
            paths,
        )

    target.mkdir(parents=True)
    prediction_frames: list[pd.DataFrame] = []
    metric_records: list[dict[str, object]] = []
    reliability_records: list[dict[str, object]] = []
    weight_audits: list[dict[str, object]] = []
    explanation_records: list[dict[str, object]] = []

    for fold in config.rolling_origin_folds:
        training, evaluation = _window_rows(joined, fold, config)
        full_targets = training["radiant_win"].astype("int8").to_numpy()
        canonical_prior = _prior(full_targets)
        evaluation_targets = (
            evaluation["radiant_win"].astype("int8").to_numpy()
        )
        candidates_by_policy = {
            policy.history_policy_id: [
                candidate
                for candidate in config.candidates
                if candidate.history_policy_id
                == policy.history_policy_id
            ]
            for policy in config.history_policies
        }
        for policy_config in config.history_policies:
            policy = RecencyPolicy(policy_config.history_policy_id)
            recency = select_training_rows(
                training,
                policy=policy,
                train_cutoff_utc=fold.train_end_utc,
            )
            effective_targets = (
                recency.frame["radiant_win"].astype("int8").to_numpy()
            )
            if len(np.unique(effective_targets)) != 2:
                raise RecencyExperimentError(
                    f"{fold.fold_id}/{policy.value} lacks both target classes."
                )
            policy_weights = (
                recency.sample_weights
                if policy == RecencyPolicy.FULL_EXP180
                else None
            )
            policy_prior = _prior(effective_targets, policy_weights)
            if (
                policy == RecencyPolicy.FULL_UNIFORM
                and not np.isclose(
                    policy_prior,
                    canonical_prior,
                    rtol=0,
                    atol=1e-15,
                )
            ):
                raise RecencyExperimentError(
                    "The full-uniform B0 reference changed."
                )

            transformer = DraftFeatureTransformer(
                FeatureVariant.B1_PICK_PRESENCE
            ).fit(recency.frame)
            training_matrix = transformer.transform(recency.frame)
            evaluation_matrix = transformer.transform(evaluation)
            weight_audits.append(
                {
                    "evaluation_id": fold.fold_id,
                    "history_policy_id": policy.value,
                    "policy_fingerprint": recency.policy_fingerprint,
                    "feature_fingerprint": transformer.fingerprint,
                    "feature_columns": training_matrix.shape[1],
                    "training_nonzero_values": training_matrix.nnz,
                    "evaluation_nonzero_values": evaluation_matrix.nnz,
                    "audit": recency.audit.to_payload(),
                }
            )
            canonical_metrics = _reference_metrics(
                evaluation_targets,
                canonical_prior,
                n_bins=config.evaluation.reliability_bins,
            )
            policy_metrics = _reference_metrics(
                evaluation_targets,
                policy_prior,
                n_bins=config.evaluation.reliability_bins,
            )
            for candidate in candidates_by_policy[policy.value]:
                estimator = _estimator(config, candidate)
                _fit_estimator(
                    estimator,
                    training_matrix,
                    effective_targets,
                    policy=policy,
                    sample_weights=recency.sample_weights,
                )
                probabilities = _positive_probabilities(
                    estimator,
                    evaluation_matrix,
                )
                evaluated = evaluate_probabilities(
                    evaluation_targets,
                    probabilities,
                    n_bins=config.evaluation.reliability_bins,
                )
                prediction_frames.append(
                    _prediction_frame(
                        evaluation,
                        candidate=candidate,
                        fold_id=fold.fold_id,
                        probabilities=probabilities,
                        policy_prior=policy_prior,
                        canonical_prior=canonical_prior,
                    )
                )
                identity = {
                    "candidate_id": candidate.candidate_id,
                    "history_policy_id": candidate.history_policy_id,
                    "C": candidate.regularization_c,
                    "evaluation_id": fold.fold_id,
                    "training_rows": len(recency.frame),
                    "evaluation_rows": len(evaluation),
                }
                metric_records.append(
                    {
                        **identity,
                        "candidate_metrics": evaluated["metrics"],
                        "policy_matched_b0_metrics": policy_metrics,
                        "canonical_b0_metrics": canonical_metrics,
                    }
                )
                reliability_records.append(
                    {
                        **identity,
                        "reliability_bins": evaluated["reliability_bins"],
                    }
                )
                explanation_records.append(
                    {
                        **identity,
                        "candidate_fingerprint": next(
                            item["fingerprint"]
                            for item in candidates
                            if item["candidate_id"]
                            == candidate.candidate_id
                        ),
                        "feature_fingerprint": transformer.fingerprint,
                        "explanation": (
                            global_logistic_coefficient_explanations(
                                estimator,
                                training_matrix,
                                transformer.get_feature_names_out(),
                                top_k=config.evaluation.coefficient_top_k,
                            )
                        ),
                    }
                )

    predictions = pd.concat(prediction_frames, ignore_index=True).sort_values(
        ["candidate_id", "evaluation_id", "sample_id"],
        kind="mergesort",
    ).reset_index(drop=True)
    reproduction = _verify_m4b1_reproduction(predictions, config)
    recent = predictions[
        predictions["evaluation_id"].isin(
            config.selection_policy["selection_fold_ids"]
        )
    ].copy()
    paired_policy = config.selection_policy["paired_group_bootstrap"]
    selection = select_recency_candidate(
        recent,
        n_resamples=int(paired_policy["replicates"]),
        random_state=int(paired_policy["random_seed"]),
        confidence_level=float(paired_policy["confidence_level"]),
        practical_log_loss_tie=float(
            config.selection_policy["practical_log_loss_tie"]
        ),
    )
    selected_id = selection["selected_candidate_id"]
    if selected_id is None:
        patch_diagnostics: dict[str, object] = {
            "status": "not_generated_no_selected_candidate",
            "used_for_selection": False,
        }
    else:
        selected_predictions = recent[
            recent["candidate_id"] == selected_id
        ].rename(
            columns={
                "candidate_probability": "radiant_win_probability",
            }
        )
        patch_diagnostics = {
            "status": "generated_for_selected_development_candidate",
            "candidate_id": selected_id,
            **patch_group_descriptive_metrics(selected_predictions),
        }

    _write_parquet(predictions, paths["predictions"])
    _write_json(paths["metrics"], {"evaluations": metric_records})
    _write_json(paths["selection"], selection)
    _write_json(paths["reliability"], {"evaluations": reliability_records})
    _write_json(paths["weight_audits"], {"evaluations": weight_audits})
    _write_json(
        paths["explanations"],
        {"evaluations": explanation_records},
    )
    _write_json(paths["patch_diagnostics"], patch_diagnostics)
    paths["report"].write_text(
        _render_report(
            fingerprint=fingerprint,
            config=config,
            selection=selection,
            reproduction=reproduction,
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
        "reproduction_gate": reproduction,
        "result": {
            "prediction_rows": len(predictions),
            "evaluation_records": len(metric_records),
            "selected_development_candidate": selected_id,
            "calibration_prediction_rows": 0,
            "locked_test_prediction_rows": 0,
            "dynamic_hyperparameter_search_performed": False,
            "model_calibration_performed": False,
            "model_serialization_performed": False,
            "authenticated_api_requests": 0,
        },
        "artifacts": artifacts,
    }
    _write_json(manifest_path, manifest)
    return _result_from_paths(
        fingerprint,
        target,
        manifest_path,
        paths,
    )


__all__ = [
    "RecencyExperimentError",
    "RecencyExperimentResult",
    "run_recency_experiment",
]
