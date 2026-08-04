"""Bounded, development-only orchestration for the M8 embedding experiment.

The runner fits exactly nine pre-registered hero-embedding candidates on
past-only rolling windows, refits the frozen M4B.2 B1 candidate as a
reference that must reproduce the pinned probabilities exactly, and
applies the approved development gates.  Calibration and locked-test rows
are masked before any window selection and never predicted.
"""

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
from sklearn.linear_model import LogisticRegression

from .contracts import (
    SPLIT_ROLE_CALIBRATION,
    SPLIT_ROLE_LOCKED_TEST,
)
from .embedding_config import (
    EmbeddingCandidate,
    HeroEmbeddingExperimentConfig,
    load_embedding_experiment_config,
)
from .embeddings import (
    HERO_EMBEDDING_MODEL_VERSION,
    draft_index_arrays,
    fit_draft_embedding_model,
    fit_hero_vocabulary,
    predict_draft_probabilities,
)
from .evaluation import evaluate_probabilities
from .features import DraftFeatureTransformer, FeatureVariant
from .loader import load_working_corpus, sha256_file
from .recency_evaluation import (
    RecencyEvaluationError,
    paired_recent_development_comparison,
)
from .splits import build_split_manifest


EXPERIMENT_SCHEMA_VERSION = "draft-ai-hero-embedding-experiment-run-v1"
PREDICTION_SCHEMA_VERSION = (
    "draft-ai-hero-embedding-development-predictions-v1"
)
EMBEDDING_DIM_PREFERENCE = (4, 8, 16)
L2_PREFERENCE = (1.0, 0.1, 0.01)
_FORBIDDEN_ROLES = frozenset(
    {SPLIT_ROLE_CALIBRATION, SPLIT_ROLE_LOCKED_TEST}
)
_PREDICTION_COLUMNS = (
    "candidate_id",
    "embedding_dim",
    "l2",
    "evaluation_id",
    "sample_id",
    "source_match_id",
    "match_start_utc",
    "patch",
    "radiant_win",
    "candidate_probability",
    "frozen_b1_probability",
    "canonical_b0_probability",
)
_REFERENCE_IDS = ("canonical_b0", "frozen_b1")
_REFERENCE_PROBABILITY_COLUMNS = {
    "canonical_b0": "canonical_b0_probability",
    "frozen_b1": "frozen_b1_probability",
}


class EmbeddingExperimentError(ValueError):
    """Raised when M8 violates its frozen development-only contract."""


@dataclass(frozen=True, slots=True)
class EmbeddingExperimentResult:
    """Content-addressed outputs from one completed M8 experiment."""

    build_fingerprint: str
    output_directory: Path
    manifest_path: Path
    predictions_path: Path
    metrics_path: Path
    selection_path: Path
    reliability_path: Path
    vocabulary_audits_path: Path
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
        "embedding_config.py",
        "embedding_experiment.py",
        "embeddings.py",
        "evaluation.py",
        "features.py",
        "hero_embeddings.py",
        "loader.py",
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
        raise EmbeddingExperimentError(f"Cannot read {label}.") from error
    if not isinstance(value, dict):
        raise EmbeddingExperimentError(f"{label} must be a JSON object.")
    return value


def _source_lineage(
    config: HeroEmbeddingExperimentConfig,
    *,
    root: Path,
    observed_split_fingerprint: str,
) -> dict[str, object]:
    if observed_split_fingerprint != config.split_manifest_fingerprint:
        raise EmbeddingExperimentError("The M4A split fingerprint changed.")
    if sha256_file(config.corpus_config_path) != config.corpus_config_sha256:
        raise EmbeddingExperimentError("The M4A corpus config changed.")

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
        raise EmbeddingExperimentError("The M4A source lineage changed.")

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
        raise EmbeddingExperimentError(
            "The M4B.1 lineage or safety result changed."
        )

    m4b2_manifest = _read_json(
        config.m4b2.build.manifest_path,
        label="the pinned M4B.2 manifest",
    )
    m4b2_result = m4b2_manifest.get("result", {})
    frozen = config.m4b2.frozen_reference_candidate
    if (
        m4b2_manifest.get("build_fingerprint")
        != config.m4b2.build.build_fingerprint
        or m4b2_manifest.get("source", {}).get(
            "split_manifest_fingerprint"
        )
        != config.split_manifest_fingerprint
        or m4b2_result.get("calibration_prediction_rows") != 0
        or m4b2_result.get("locked_test_prediction_rows") != 0
        or m4b2_result.get("authenticated_api_requests") != 0
        or m4b2_result.get("selected_development_candidate")
        != frozen.candidate_id
    ):
        raise EmbeddingExperimentError(
            "The M4B.2 lineage or safety result changed."
        )

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
        },
        "m4b2": {
            "build_fingerprint": config.m4b2.build.build_fingerprint,
            "manifest_path": (
                config.m4b2.build.manifest_path.relative_to(root).as_posix()
            ),
            "manifest_sha256": config.m4b2.build.manifest_sha256,
            "frozen_reference_candidate": {
                "candidate_id": frozen.candidate_id,
                "candidate_fingerprint": frozen.candidate_fingerprint,
                "history_policy_id": frozen.history_policy_id,
                "C": frozen.regularization_c,
            },
            "development_predictions_sha256": next(
                artifact.sha256
                for artifact in config.m4b2.build.artifacts
                if artifact.name == "predictions"
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
        raise EmbeddingExperimentError("Split roles do not cover the corpus.")
    reserved = joined["split_role"].isin(_FORBIDDEN_ROLES)
    joined.loc[reserved, "radiant_win"] = pd.NA
    if not joined.loc[reserved, "radiant_win"].isna().all():
        raise EmbeddingExperimentError("Reserved targets were not masked.")
    return joined


def _window_rows(
    joined: pd.DataFrame,
    fold: object,
    config: HeroEmbeddingExperimentConfig,
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
        raise EmbeddingExperimentError(
            f"{fold.fold_id} contains an empty role."
        )
    for role in sorted(set(training["split_role"])):
        config.assert_role_allowed(str(role), purpose="fit")
    for role in sorted(set(evaluation["split_role"])):
        config.assert_role_allowed(str(role), purpose="evaluate")
    if training["radiant_win"].isna().any():
        raise EmbeddingExperimentError(
            f"{fold.fold_id} training labels are missing."
        )
    if evaluation["radiant_win"].isna().any():
        raise EmbeddingExperimentError(
            f"{fold.fold_id} evaluation labels are unavailable."
        )
    overlap = set(training["source_match_id"]).intersection(
        evaluation["source_match_id"]
    )
    if overlap:
        raise EmbeddingExperimentError(
            f"{fold.fold_id} crosses source-match groups."
        )
    return training, evaluation


def _candidate_fingerprint(
    candidate: EmbeddingCandidate,
    config: HeroEmbeddingExperimentConfig,
) -> str:
    return _sha256_json(
        {
            "candidate_id": candidate.candidate_id,
            "history_policy_id": candidate.history_policy_id,
            "embedding_dim": candidate.embedding_dim,
            "l2": candidate.l2,
            "model_version": HERO_EMBEDDING_MODEL_VERSION,
            "estimator": {
                "family": config.estimator.family,
                "objective": config.estimator.objective,
                "optimizer": config.estimator.optimizer,
                "learning_rate": config.estimator.learning_rate,
                "max_iterations": config.estimator.max_iterations,
                "gradient_tolerance": config.estimator.gradient_tolerance,
                "init_scale": config.estimator.init_scale,
                "random_seed": config.estimator.random_seed,
            },
        }
    )


def _frozen_b1_estimator(
    config: HeroEmbeddingExperimentConfig,
) -> LogisticRegression:
    return LogisticRegression(
        C=config.m4b2.frozen_reference_candidate.regularization_c,
        class_weight=None,
        max_iter=2000,
        penalty="l2",
        random_state=config.estimator.random_seed,
        solver="liblinear",
    )


def _fit_frozen_b1(
    config: HeroEmbeddingExperimentConfig,
    training: pd.DataFrame,
    evaluation: pd.DataFrame,
    targets: np.ndarray,
) -> np.ndarray:
    transformer = DraftFeatureTransformer(
        FeatureVariant.B1_PICK_PRESENCE
    ).fit(training)
    estimator = _frozen_b1_estimator(config)
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="'penalty' was deprecated in version 1.8",
            category=FutureWarning,
            module=r"sklearn\.linear_model\._logistic",
        )
        estimator.fit(transformer.transform(training), targets)
    classes = list(estimator.classes_)
    if 1 not in classes:
        raise EmbeddingExperimentError(
            "The frozen B1 reference lacks the positive class."
        )
    values = np.asarray(
        estimator.predict_proba(transformer.transform(evaluation))[
            :, classes.index(1)
        ],
        dtype=np.float64,
    )
    if values.shape != (len(evaluation),) or not np.isfinite(values).all():
        raise EmbeddingExperimentError(
            "Frozen B1 probabilities are malformed."
        )
    return values


def _prior(targets: np.ndarray) -> float:
    value = float(targets.mean())
    if not 0 < value < 1:
        raise EmbeddingExperimentError("The B0 reference prior is degenerate.")
    return value


def _prediction_frame(
    evaluation: pd.DataFrame,
    *,
    candidate: EmbeddingCandidate,
    fold_id: str,
    probabilities: np.ndarray,
    frozen_b1: np.ndarray,
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
    result.insert(0, "l2", candidate.l2)
    result.insert(0, "embedding_dim", candidate.embedding_dim)
    result.insert(0, "candidate_id", candidate.candidate_id)
    result["radiant_win"] = result["radiant_win"].astype("int8")
    result["candidate_probability"] = probabilities
    result["frozen_b1_probability"] = frozen_b1
    result["canonical_b0_probability"] = canonical_prior
    return result[list(_PREDICTION_COLUMNS)]


def _reference_metrics(
    targets: np.ndarray,
    probabilities: np.ndarray,
    *,
    n_bins: int,
) -> dict[str, object]:
    return evaluate_probabilities(
        targets,
        probabilities,
        n_bins=n_bins,
    )["metrics"]


def _m4b2_predictions_path(config: HeroEmbeddingExperimentConfig) -> Path:
    artifact = next(
        (
            item
            for item in config.m4b2.build.artifacts
            if item.name == "predictions"
        ),
        None,
    )
    if artifact is None:
        raise EmbeddingExperimentError(
            "M4B.2 development predictions are not pinned."
        )
    return config.m4b2.build.manifest_path.parent / artifact.file


def _verify_frozen_b1_reproduction(
    predictions: pd.DataFrame,
    config: HeroEmbeddingExperimentConfig,
) -> dict[str, object]:
    frozen = config.m4b2.frozen_reference_candidate
    first_candidate = sorted(set(predictions["candidate_id"]))[0]
    reproduced = predictions[
        predictions["candidate_id"] == first_candidate
    ][
        [
            "evaluation_id",
            "sample_id",
            "source_match_id",
            "radiant_win",
            "frozen_b1_probability",
            "canonical_b0_probability",
        ]
    ].copy()
    with duckdb.connect() as connection:
        parent = connection.execute(
            "SELECT evaluation_id, sample_id, source_match_id, radiant_win, "
            "candidate_probability, canonical_b0_probability "
            "FROM read_parquet(?) WHERE candidate_id = ? "
            "ORDER BY evaluation_id, sample_id",
            [str(_m4b2_predictions_path(config)), frozen.candidate_id],
        ).fetchdf()
    reproduced = reproduced.sort_values(
        ["evaluation_id", "sample_id"],
        kind="mergesort",
    ).reset_index(drop=True)
    parent = parent.reset_index(drop=True)
    if len(reproduced) != len(parent):
        raise EmbeddingExperimentError(
            "Frozen B1 reproduction row count changed."
        )
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
            raise EmbeddingExperimentError(
                f"Frozen B1 reproduction alignment changed: {column}."
            )
    b1_difference = np.abs(
        reproduced["frozen_b1_probability"].to_numpy(dtype=np.float64)
        - parent["candidate_probability"].to_numpy(dtype=np.float64)
    )
    b0_difference = np.abs(
        reproduced["canonical_b0_probability"].to_numpy(dtype=np.float64)
        - parent["canonical_b0_probability"].to_numpy(dtype=np.float64)
    )
    maximum_b1 = float(b1_difference.max(initial=0.0))
    maximum_b0 = float(b0_difference.max(initial=0.0))
    if maximum_b1 > 0.0 or maximum_b0 > 0.0:
        raise EmbeddingExperimentError(
            "The frozen B1 reference does not reproduce the pinned M4B.2"
            " probabilities exactly."
        )
    return {
        "candidate_id": frozen.candidate_id,
        "candidate_fingerprint": frozen.candidate_fingerprint,
        "rows": len(reproduced),
        "maximum_absolute_probability_difference": maximum_b1,
        "maximum_absolute_b0_difference": maximum_b0,
        "tolerance": 0.0,
        "passed": True,
        "parent_predictions_sha256": sha256_file(
            _m4b2_predictions_path(config)
        ),
    }


def _probability_losses(
    targets: np.ndarray,
    probabilities: np.ndarray,
) -> dict[str, float]:
    clipped = np.clip(
        probabilities,
        np.finfo(np.float64).eps,
        1 - np.finfo(np.float64).eps,
    )
    log_losses = -(
        targets * np.log(clipped)
        + (1 - targets) * np.log1p(-clipped)
    )
    return {
        "log_loss": float(log_losses.mean()),
        "brier_score": float(np.square(targets - probabilities).mean()),
    }


def _candidate_evaluations(
    rows: pd.DataFrame,
    selection_fold_ids: tuple[str, ...],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    scopes = (
        *(
            (fold, rows[rows["evaluation_id"] == fold])
            for fold in selection_fold_ids
        ),
        ("pooled", rows),
    )
    for evaluation_id, selected in scopes:
        targets = selected["radiant_win"].to_numpy(dtype=np.float64)
        candidate = _probability_losses(
            targets,
            selected["candidate_probability"].to_numpy(dtype=np.float64),
        )
        references = {
            reference_id: _probability_losses(
                targets,
                selected[
                    _REFERENCE_PROBABILITY_COLUMNS[reference_id]
                ].to_numpy(dtype=np.float64),
            )
            for reference_id in _REFERENCE_IDS
        }
        gates = {
            metric: {
                f"beats_{reference_id}": (
                    candidate[metric] < references[reference_id][metric]
                )
                for reference_id in _REFERENCE_IDS
            }
            for metric in ("log_loss", "brier_score")
        }
        result[evaluation_id] = {
            "rows": len(selected),
            "candidate": candidate,
            **references,
            "strict_improvement_gates": gates,
            "passes_all_strict_improvement_gates": all(
                check
                for metric_gates in gates.values()
                for check in metric_gates.values()
            ),
        }
    return result


def _paired_reference_frames(
    rows: pd.DataFrame,
    reference_id: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    shared = rows[
        [
            "sample_id",
            "source_match_id",
            "evaluation_id",
            "radiant_win",
        ]
    ]
    reference = shared.copy()
    reference["radiant_win_probability"] = rows[
        _REFERENCE_PROBABILITY_COLUMNS[reference_id]
    ].to_numpy(dtype=np.float64)
    candidate = shared.copy()
    candidate["radiant_win_probability"] = rows[
        "candidate_probability"
    ].to_numpy(dtype=np.float64)
    return reference, candidate


def _rank_qualifying(
    candidates: list[dict[str, Any]],
    *,
    practical_tie: float,
) -> list[dict[str, Any]]:
    remaining = sorted(
        candidates,
        key=lambda item: (
            item["evaluations"]["pooled"]["candidate"]["log_loss"],
            item["candidate_id"],
        ),
    )
    ranked: list[dict[str, Any]] = []
    dim_rank = {
        value: index
        for index, value in enumerate(EMBEDDING_DIM_PREFERENCE)
    }
    l2_rank = {value: index for index, value in enumerate(L2_PREFERENCE)}

    while remaining:
        best_log_loss = remaining[0]["evaluations"]["pooled"][
            "candidate"
        ]["log_loss"]
        tie_group = [
            item
            for item in remaining
            if (
                item["evaluations"]["pooled"]["candidate"]["log_loss"]
                <= best_log_loss + practical_tie
            )
        ]
        tie_group.sort(
            key=lambda item: (
                dim_rank[item["embedding_dim"]],
                l2_rank[item["l2"]],
                item["candidate_id"],
            )
        )
        ranked.extend(tie_group)
        tied_ids = {item["candidate_id"] for item in tie_group}
        remaining = [
            item
            for item in remaining
            if item["candidate_id"] not in tied_ids
        ]
    return ranked


def select_embedding_candidate(
    predictions: pd.DataFrame,
    config: HeroEmbeddingExperimentConfig,
) -> dict[str, Any]:
    """Apply the approved development gates to exactly nine candidates."""

    selection_fold_ids = tuple(
        config.selection_policy["selection_fold_ids"]
    )
    paired_policy = config.selection_policy["paired_group_bootstrap"]
    practical_tie = float(
        config.selection_policy["practical_log_loss_tie"]
    )
    observed = {
        (
            candidate_id,
            int(rows["embedding_dim"].iloc[0]),
            float(rows["l2"].iloc[0]),
        )
        for candidate_id, rows in predictions.groupby(
            "candidate_id",
            sort=True,
        )
    }
    expected = {
        (candidate.candidate_id, candidate.embedding_dim, candidate.l2)
        for candidate in config.candidates
    }
    if observed != expected:
        raise EmbeddingExperimentError(
            "Selection input does not match the nine approved candidates."
        )

    candidate_results: list[dict[str, Any]] = []
    for candidate in config.candidates:
        rows = predictions[
            predictions["candidate_id"] == candidate.candidate_id
        ].sort_values("sample_id", kind="stable").reset_index(drop=True)
        evaluations = _candidate_evaluations(rows, selection_fold_ids)
        paired_results: dict[str, Any] = {}
        paired_gates: dict[str, bool] = {}
        for reference_id in _REFERENCE_IDS:
            reference, candidate_frame = _paired_reference_frames(
                rows,
                reference_id,
            )
            try:
                paired = paired_recent_development_comparison(
                    reference,
                    candidate_frame,
                    n_resamples=int(paired_policy["replicates"]),
                    random_state=int(paired_policy["random_seed"]),
                    confidence_level=float(
                        paired_policy["confidence_level"]
                    ),
                )
            except RecencyEvaluationError as error:
                raise EmbeddingExperimentError(
                    f"Paired evaluation failed for "
                    f"{candidate.candidate_id}: {error}"
                ) from error
            paired_results[reference_id] = paired
            for metric in ("log_loss", "brier_score"):
                paired_gates[f"{reference_id}_{metric}"] = (
                    paired["metrics"][metric]["upper"] < 0
                )
        strict_gates = all(
            evaluation["passes_all_strict_improvement_gates"]
            for evaluation in evaluations.values()
        )
        qualifies = strict_gates and all(paired_gates.values())
        candidate_results.append(
            {
                "candidate_id": candidate.candidate_id,
                "embedding_dim": candidate.embedding_dim,
                "l2": candidate.l2,
                "evaluations": evaluations,
                "paired_reference_comparisons": paired_results,
                "gate_results": {
                    "all_fold_and_pooled_strict_improvements": strict_gates,
                    **{
                        f"paired_{name}_upper_below_zero": value
                        for name, value in paired_gates.items()
                    },
                },
                "qualifies_as_development_candidate": qualifies,
            }
        )

    qualifying = [
        item
        for item in candidate_results
        if item["qualifies_as_development_candidate"]
    ]
    ranked = _rank_qualifying(qualifying, practical_tie=practical_tie)
    rank_by_id = {
        item["candidate_id"]: index
        for index, item in enumerate(ranked, start=1)
    }
    for item in candidate_results:
        item["selection_rank"] = rank_by_id.get(item["candidate_id"])

    selected = ranked[0] if ranked else None
    return {
        "selection_scope": "development_only_2025_q1_q3",
        "selection_status": (
            "development_candidate_selected"
            if selected is not None
            else "no_candidate_passed_all_development_gates"
        ),
        "selected_candidate_id": (
            selected["candidate_id"] if selected is not None else None
        ),
        "not_a_final_champion": True,
        "calibration_or_locked_test_used": False,
        "policy": {
            "strict_improvement_vs_references": (
                "candidate metric must be lower than the canonical B0 and"
                " the frozen M4B.2 B1 candidate in every selection fold"
                " and pooled"
            ),
            "paired_interval_references": list(_REFERENCE_IDS),
            "paired_interval_gate": (
                "95% upper bound below zero for log loss and Brier"
                " against both references"
            ),
            "practical_log_loss_tie": practical_tie,
            "embedding_dim_preference": list(EMBEDDING_DIM_PREFERENCE),
            "l2_preference": list(L2_PREFERENCE),
        },
        "audit": {
            "candidate_count": len(candidate_results),
            "expected_candidate_count": len(config.candidates),
            "qualifying_candidate_count": len(qualifying),
            "rows_per_candidate": (
                len(predictions) // len(config.candidates)
            ),
            "bootstrap_resamples_per_reference": int(
                paired_policy["replicates"]
            ),
            "bootstrap_random_state": int(paired_policy["random_seed"]),
            "bootstrap_confidence_level": float(
                paired_policy["confidence_level"]
            ),
            "probability_references": list(_REFERENCE_IDS),
        },
        "qualifying_ranking": [item["candidate_id"] for item in ranked],
        "candidates": candidate_results,
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
    config: HeroEmbeddingExperimentConfig,
    selection: dict[str, object],
    reproduction: dict[str, object],
) -> str:
    return "\n".join(
        [
            "# Milestone 8: Hero Embeddings with Low-Rank Interactions",
            "",
            f"- Build fingerprint: `{fingerprint}`",
            f"- Candidate configurations: `{len(config.candidates)}`",
            (
                "- Selected development candidate: "
                f"`{selection['selected_candidate_id'] or 'none'}`"
            ),
            (
                "- Frozen B1 reproduction maximum difference: "
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
) -> EmbeddingExperimentResult:
    return EmbeddingExperimentResult(
        fingerprint,
        target,
        manifest_path,
        paths["predictions"],
        paths["metrics"],
        paths["selection"],
        paths["reliability"],
        paths["vocabulary_audits"],
        paths["report"],
    )


def run_embedding_experiment(
    experiment_config_path: Path,
    *,
    output_root: Path = Path("models/m8"),
    repository_root: Path | None = None,
) -> EmbeddingExperimentResult:
    """Fit and compare exactly nine embedding candidates on development data."""

    root = (
        repository_root.resolve()
        if repository_root is not None
        else Path(__file__).resolve().parents[2]
    )
    config = load_embedding_experiment_config(
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

    candidates = [
        {
            "candidate_id": candidate.candidate_id,
            "history_policy_id": candidate.history_policy_id,
            "embedding_dim": candidate.embedding_dim,
            "l2": candidate.l2,
            "fingerprint": _candidate_fingerprint(candidate, config),
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
        "model_version": HERO_EMBEDDING_MODEL_VERSION,
        "source": {
            **source,
            "rows": len(corpus.frame),
            "source_matches": int(corpus.frame["source_match_id"].nunique()),
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
        "vocabulary_audits": target / "vocabulary_audits.json",
        "report": target / "experiment_report.md",
    }
    if target.exists():
        existing = _read_json(manifest_path, label="the existing M8 manifest")
        if existing.get("build_fingerprint") != fingerprint:
            raise EmbeddingExperimentError("Existing M8 fingerprint changed.")
        for artifact in existing.get("artifacts", {}).values():
            artifact_path = target / str(artifact["file"])
            if (
                not artifact_path.is_file()
                or sha256_file(artifact_path) != artifact["sha256"]
            ):
                raise EmbeddingExperimentError("An M8 artifact changed.")
        return _result_from_paths(fingerprint, target, manifest_path, paths)

    target.mkdir(parents=True)
    prediction_frames: list[pd.DataFrame] = []
    metric_records: list[dict[str, object]] = []
    reliability_records: list[dict[str, object]] = []
    vocabulary_audits: list[dict[str, object]] = []

    for fold in config.rolling_origin_folds:
        training, evaluation = _window_rows(joined, fold, config)
        training_targets = training["radiant_win"].astype("int8").to_numpy()
        if len(np.unique(training_targets)) != 2:
            raise EmbeddingExperimentError(
                f"{fold.fold_id} lacks both target classes."
            )
        evaluation_targets = (
            evaluation["radiant_win"].astype("int8").to_numpy()
        )
        canonical_prior = _prior(training_targets)
        frozen_b1 = _fit_frozen_b1(
            config,
            training,
            evaluation,
            training_targets,
        )

        vocabulary = fit_hero_vocabulary(training)
        training_indices = draft_index_arrays(
            vocabulary,
            training,
            context=f"{fold.fold_id} training rows",
        )
        evaluation_indices = draft_index_arrays(
            vocabulary,
            evaluation,
            context=f"{fold.fold_id} evaluation rows",
        )
        if training_indices.unknown_activations != 0:
            raise EmbeddingExperimentError(
                f"{fold.fold_id} training rows activate the unknown hero."
            )

        canonical_metrics = _reference_metrics(
            evaluation_targets,
            np.full(len(evaluation), canonical_prior, dtype=np.float64),
            n_bins=config.evaluation.reliability_bins,
        )
        frozen_b1_metrics = _reference_metrics(
            evaluation_targets,
            frozen_b1,
            n_bins=config.evaluation.reliability_bins,
        )
        for candidate in config.candidates:
            fit_result = fit_draft_embedding_model(
                vocabulary,
                training_indices,
                training_targets.astype(np.float64),
                embedding_dim=candidate.embedding_dim,
                l2=candidate.l2,
                learning_rate=config.estimator.learning_rate,
                max_iterations=config.estimator.max_iterations,
                gradient_tolerance=config.estimator.gradient_tolerance,
                seed=config.estimator.random_seed,
                init_scale=config.estimator.init_scale,
            )
            probabilities = predict_draft_probabilities(
                fit_result.parameters,
                vocabulary,
                evaluation_indices,
            )
            if not np.isfinite(probabilities).all():
                raise EmbeddingExperimentError(
                    "Candidate probabilities are malformed."
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
                    frozen_b1=frozen_b1,
                    canonical_prior=canonical_prior,
                )
            )
            identity = {
                "candidate_id": candidate.candidate_id,
                "embedding_dim": candidate.embedding_dim,
                "l2": candidate.l2,
                "evaluation_id": fold.fold_id,
                "training_rows": len(training),
                "evaluation_rows": len(evaluation),
            }
            metric_records.append(
                {
                    **identity,
                    "candidate_metrics": evaluated["metrics"],
                    "frozen_b1_metrics": frozen_b1_metrics,
                    "canonical_b0_metrics": canonical_metrics,
                }
            )
            reliability_records.append(
                {
                    **identity,
                    "reliability_bins": evaluated["reliability_bins"],
                }
            )
            vocabulary_audits.append(
                {
                    **identity,
                    "vocabulary_fingerprint": vocabulary.fingerprint,
                    "vocabulary_size": len(vocabulary.heroes),
                    "hero_count_with_unknown": vocabulary.hero_count,
                    "training_unknown_activations": (
                        training_indices.unknown_activations
                    ),
                    "evaluation_unknown_activations": (
                        evaluation_indices.unknown_activations
                    ),
                    "iterations_run": fit_result.iterations_run,
                    "converged": fit_result.converged,
                    "final_objective": fit_result.final_objective,
                    "final_gradient_infinity_norm": (
                        fit_result.final_gradient_infinity_norm
                    ),
                }
            )

    predictions = pd.concat(prediction_frames, ignore_index=True).sort_values(
        ["candidate_id", "evaluation_id", "sample_id"],
        kind="mergesort",
    ).reset_index(drop=True)
    reproduction = _verify_frozen_b1_reproduction(predictions, config)
    recent = predictions[
        predictions["evaluation_id"].isin(
            config.selection_policy["selection_fold_ids"]
        )
    ].copy()
    selection = select_embedding_candidate(recent, config)

    _write_parquet(predictions, paths["predictions"])
    _write_json(paths["metrics"], {"evaluations": metric_records})
    _write_json(paths["selection"], selection)
    _write_json(paths["reliability"], {"evaluations": reliability_records})
    _write_json(
        paths["vocabulary_audits"],
        {"evaluations": vocabulary_audits},
    )
    paths["report"].write_text(
        _render_report(
            fingerprint=fingerprint,
            config=config,
            selection=selection,
            reproduction=reproduction,
        ),
        encoding="utf-8",
    )
    artifacts = {name: _artifact(path) for name, path in paths.items()}
    manifest = {
        **core,
        "build_fingerprint": fingerprint,
        "reproduction_gate": reproduction,
        "result": {
            "prediction_rows": len(predictions),
            "evaluation_records": len(metric_records),
            "selected_development_candidate": (
                selection["selected_candidate_id"]
            ),
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
    return _result_from_paths(fingerprint, target, manifest_path, paths)


__all__ = [
    "EmbeddingExperimentError",
    "EmbeddingExperimentResult",
    "run_embedding_experiment",
    "select_embedding_candidate",
]
