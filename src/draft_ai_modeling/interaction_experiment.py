"""Development-only orchestration for the M4B.4 interaction recovery gate.

The experiment deliberately stops at the last development fold (2025-Q3).
It never transforms or predicts the reserved 2025-Q4 calibration rows or the
locked 2026-Q1 rows.  Reference probabilities are read from the immutable,
pinned M4B.2 development artifact rather than recomputed.
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
from scipy.sparse import csr_matrix
from sklearn.linear_model import LogisticRegression

from .contracts import (
    SPLIT_ROLE_CALIBRATION,
    SPLIT_ROLE_LOCKED_TEST,
)
from .evaluation import (
    evaluate_probabilities,
    global_logistic_coefficient_explanations,
)
from .interaction_config import (
    InteractionCandidate,
    InteractionExperimentConfig,
    load_interaction_experiment_config,
)
from .interaction_features import (
    MIN_INTERACTION_ROW_SUPPORT,
    PickInteractionTransformer,
)
from .interaction_selection import select_interaction_candidate
from .loader import load_working_corpus, sha256_file
from .recency_evaluation import patch_group_descriptive_metrics
from .splits import split_manifest_fingerprint


EXPERIMENT_SCHEMA_VERSION = "draft-ai-interaction-experiment-run-v1"
PREDICTION_SCHEMA_VERSION = "draft-ai-interaction-development-predictions-v1"
_RESERVED_ROLES = frozenset(
    {SPLIT_ROLE_CALIBRATION, SPLIT_ROLE_LOCKED_TEST}
)
_PREDICTION_COLUMNS = (
    "candidate_id",
    "C",
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
_REFERENCE_COLUMNS = (
    "evaluation_id",
    "sample_id",
    "source_match_id",
    "match_start_utc",
    "patch",
    "radiant_win",
    "frozen_b1_probability",
    "canonical_b0_probability",
)


class InteractionExperimentError(ValueError):
    """Raised when M4B.4 violates its frozen development-only contract."""


@dataclass(frozen=True, slots=True)
class InteractionExperimentResult:
    """Content-addressed local outputs from one completed M4B.4 run."""

    build_fingerprint: str
    output_directory: Path
    manifest_path: Path
    predictions_path: Path
    metrics_path: Path
    support_audits_path: Path
    explanations_path: Path
    selection_path: Path
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


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InteractionExperimentError(f"Cannot read {label}.") from error
    if not isinstance(payload, dict):
        raise InteractionExperimentError(f"{label} must be a JSON object.")
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


def _source_sha256() -> str:
    root = Path(__file__).resolve().parent
    names = (
        "contracts.py",
        "evaluation.py",
        "features.py",
        "interaction_config.py",
        "interaction_experiment.py",
        "interaction_features.py",
        "interaction_selection.py",
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


def _runtime_versions() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "duckdb": duckdb.__version__,
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


def _artifact(path: Path) -> dict[str, object]:
    return {
        "file": path.name,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _load_split_manifest(
    config: InteractionExperimentConfig,
) -> pd.DataFrame:
    if (
        sha256_file(config.m4a.split_manifest_path)
        != config.m4a.split_manifest_sha256
    ):
        raise InteractionExperimentError("The pinned M4A split artifact changed.")
    with duckdb.connect() as connection:
        manifest = connection.execute(
            "SELECT * FROM read_parquet(?) ORDER BY match_start_utc, "
            "source_match_id, sample_id",
            [str(config.m4a.split_manifest_path)],
        ).fetchdf()
    if split_manifest_fingerprint(manifest) != config.split_manifest_fingerprint:
        raise InteractionExperimentError("The M4A split fingerprint changed.")
    return manifest


def _masked_development_frame(
    corpus: pd.DataFrame,
    split_manifest: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, int | bool]]:
    """Join roles and immediately erase both reserved target vectors."""

    required = {"sample_id", "source_match_id", "split_role"}
    missing = sorted(required.difference(split_manifest.columns))
    if missing:
        raise InteractionExperimentError(
            "The split manifest is missing columns: " + ", ".join(missing)
        )
    roles = split_manifest[
        ["sample_id", "source_match_id", "split_role"]
    ].rename(columns={"source_match_id": "manifest_source_match_id"})
    joined = corpus.merge(
        roles,
        on="sample_id",
        how="left",
        validate="one_to_one",
    )
    if joined["split_role"].isna().any():
        raise InteractionExperimentError("Split roles do not cover the corpus.")
    if not joined["source_match_id"].astype(str).equals(
        joined["manifest_source_match_id"].astype(str)
    ):
        raise InteractionExperimentError(
            "Corpus and split source-match groups are misaligned."
        )
    joined = joined.drop(columns=["manifest_source_match_id"])
    role_counts = {
        role: int((joined["split_role"] == role).sum())
        for role in sorted(set(joined["split_role"].astype(str)))
    }
    reserved = joined["split_role"].isin(_RESERVED_ROLES)
    reserved_count = int(reserved.sum())
    joined.loc[reserved, "radiant_win"] = pd.NA
    if reserved_count == 0 or not joined.loc[reserved, "radiant_win"].isna().all():
        raise InteractionExperimentError("Reserved targets were not masked.")
    return joined, {
        "calibration_rows_masked": role_counts.get(
            SPLIT_ROLE_CALIBRATION,
            0,
        ),
        "locked_test_rows_masked": role_counts.get(
            SPLIT_ROLE_LOCKED_TEST,
            0,
        ),
        "reserved_targets_masked_before_window_selection": True,
    }


def _source_lineage(
    config: InteractionExperimentConfig,
    *,
    root: Path,
) -> dict[str, Any]:
    if sha256_file(config.corpus_config_path) != config.corpus_config_sha256:
        raise InteractionExperimentError("The M4A corpus config changed.")
    pins = (
        ("M4A manifest", config.m4a.manifest_path, config.m4a.manifest_sha256),
        (
            "M4B.2 config",
            config.m4b2.config_path,
            config.m4b2.config_sha256,
        ),
        (
            "M4B.2 manifest",
            config.m4b2.manifest_path,
            config.m4b2.manifest_sha256,
        ),
        (
            "M4B.2 predictions",
            config.m4b2.predictions_path,
            config.m4b2.predictions_sha256,
        ),
        (
            "M4B.2 selection",
            config.m4b2.selection_path,
            config.m4b2.selection_sha256,
        ),
        (
            "M4B.3 manifest",
            config.m4b3.manifest_path,
            config.m4b3.manifest_sha256,
        ),
        (
            "M4B.3 readiness",
            config.m4b3.readiness_path,
            config.m4b3.readiness_sha256,
        ),
        (
            "M4B.3 selection",
            config.m4b3.selection_path,
            config.m4b3.selection_sha256,
        ),
    )
    for label, path, expected in pins:
        if sha256_file(path) != expected:
            raise InteractionExperimentError(f"The pinned {label} changed.")

    m4a = _read_json(config.m4a.manifest_path, label="M4A manifest")
    m4b2 = _read_json(config.m4b2.manifest_path, label="M4B.2 manifest")
    m4b2_selection = _read_json(
        config.m4b2.selection_path,
        label="M4B.2 selection",
    )
    m4b3 = _read_json(config.m4b3.manifest_path, label="M4B.3 manifest")
    m4b3_readiness = _read_json(
        config.m4b3.readiness_path,
        label="M4B.3 readiness",
    )
    m4b3_selection = _read_json(
        config.m4b3.selection_path,
        label="M4B.3 selection",
    )
    if (
        m4a.get("build_fingerprint") != config.m4a.build_fingerprint
        or m4a.get("split", {}).get("split_manifest_fingerprint")
        != config.split_manifest_fingerprint
    ):
        raise InteractionExperimentError("The pinned M4A lineage changed.")
    if (
        m4b2.get("build_fingerprint") != config.m4b2.build_fingerprint
        or m4b2.get("experiment_config_fingerprint")
        != config.m4b2.config_fingerprint
        or m4b2.get("result", {}).get("selected_development_candidate")
        != config.m4b2.frozen_candidate_id
        or m4b2.get("result", {}).get("calibration_prediction_rows") != 0
        or m4b2.get("result", {}).get("locked_test_prediction_rows") != 0
        or m4b2_selection.get("selected_candidate_id")
        != config.m4b2.frozen_candidate_id
    ):
        raise InteractionExperimentError("The pinned M4B.2 lineage changed.")
    if (
        m4b3.get("build_fingerprint") != config.m4b3.build_fingerprint
        or m4b3.get("result", {}).get("locked_test_prediction_rows") != 0
        or m4b3.get("result", {}).get("authenticated_api_requests") != 0
        or m4b3_readiness.get("passed") is not False
        or m4b3_selection.get("selected_method") != "raw"
    ):
        raise InteractionExperimentError(
            "The pinned M4B.3 safety or readiness result changed."
        )

    def relative(path: Path) -> str:
        return path.relative_to(root).as_posix()
    return {
        "corpus_id": config.corpus_id,
        "corpus_config_path": relative(config.corpus_config_path),
        "corpus_config_sha256": config.corpus_config_sha256,
        "split_manifest_fingerprint": config.split_manifest_fingerprint,
        "m4a": {
            "build_fingerprint": config.m4a.build_fingerprint,
            "manifest_path": relative(config.m4a.manifest_path),
            "manifest_sha256": config.m4a.manifest_sha256,
            "split_manifest_path": relative(config.m4a.split_manifest_path),
            "split_manifest_sha256": config.m4a.split_manifest_sha256,
        },
        "m4b2": {
            "build_fingerprint": config.m4b2.build_fingerprint,
            "manifest_sha256": config.m4b2.manifest_sha256,
            "development_predictions_path": relative(
                config.m4b2.predictions_path
            ),
            "development_predictions_sha256": (
                config.m4b2.predictions_sha256
            ),
            "selection_sha256": config.m4b2.selection_sha256,
            "frozen_candidate_id": config.m4b2.frozen_candidate_id,
            "frozen_candidate_fingerprint": (
                config.m4b2.frozen_candidate_fingerprint
            ),
        },
        "m4b3": {
            "build_fingerprint": config.m4b3.build_fingerprint,
            "manifest_sha256": config.m4b3.manifest_sha256,
            "selection_sha256": config.m4b3.selection_sha256,
            "readiness_sha256": config.m4b3.readiness_sha256,
            "ready_for_locked_test": False,
        },
    }


def _load_reference_predictions(
    config: InteractionExperimentConfig,
) -> pd.DataFrame:
    if (
        sha256_file(config.m4b2.predictions_path)
        != config.m4b2.predictions_sha256
    ):
        raise InteractionExperimentError(
            "The pinned M4B.2 prediction artifact changed."
        )
    with duckdb.connect() as connection:
        reference = connection.execute(
            "SELECT evaluation_id, sample_id, source_match_id, "
            "match_start_utc, patch, radiant_win, "
            "candidate_probability AS frozen_b1_probability, "
            "canonical_b0_probability "
            "FROM read_parquet(?) WHERE candidate_id = ? "
            "ORDER BY evaluation_id, sample_id",
            [
                str(config.m4b2.predictions_path),
                config.m4b2.frozen_candidate_id,
            ],
        ).fetchdf()
    if reference.empty:
        raise InteractionExperimentError(
            "The pinned M4B.2 candidate has no predictions."
        )
    if reference.duplicated(["evaluation_id", "sample_id"]).any():
        raise InteractionExperimentError(
            "The pinned M4B.2 reference has duplicate samples."
        )
    expected_folds = tuple(fold.fold_id for fold in config.rolling_origin_folds)
    if tuple(sorted(reference["evaluation_id"].unique())) != tuple(
        sorted(expected_folds)
    ):
        raise InteractionExperimentError(
            "The pinned M4B.2 reference fold coverage changed."
        )
    group_folds = reference.groupby("source_match_id")["evaluation_id"].nunique()
    if (group_folds != 1).any():
        raise InteractionExperimentError(
            "A pinned M4B.2 source match crosses evaluation folds."
        )
    targets = pd.to_numeric(reference["radiant_win"], errors="coerce")
    if targets.isna().any() or not set(targets.unique()).issubset({0, 1}):
        raise InteractionExperimentError(
            "The pinned M4B.2 reference targets are invalid."
        )
    reference["radiant_win"] = targets.astype("int8")
    for column in ("frozen_b1_probability", "canonical_b0_probability"):
        values = pd.to_numeric(reference[column], errors="coerce").to_numpy(
            dtype=np.float64
        )
        if not np.isfinite(values).all() or ((values < 0) | (values > 1)).any():
            raise InteractionExperimentError(
                f"The pinned M4B.2 {column} values are invalid."
            )
        reference[column] = values
    return reference[list(_REFERENCE_COLUMNS)]


def _window_rows(
    joined: pd.DataFrame,
    fold: object,
    config: InteractionExperimentConfig,
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
        raise InteractionExperimentError(f"{fold.fold_id} contains an empty role.")
    for role in sorted(set(training["split_role"].astype(str))):
        config.assert_role_allowed(role, purpose="fit")
    for role in sorted(set(evaluation["split_role"].astype(str))):
        config.assert_role_allowed(role, purpose="evaluate")
    if training["radiant_win"].isna().any():
        raise InteractionExperimentError(
            f"{fold.fold_id} training labels are missing."
        )
    if evaluation["radiant_win"].isna().any():
        raise InteractionExperimentError(
            f"{fold.fold_id} evaluation labels are unavailable."
        )
    overlap = set(training["source_match_id"]).intersection(
        evaluation["source_match_id"]
    )
    if overlap:
        raise InteractionExperimentError(
            f"{fold.fold_id} crosses source-match groups."
        )
    return training, evaluation


def _align_reference_fold(
    evaluation: pd.DataFrame,
    reference: pd.DataFrame,
    *,
    fold_id: str,
) -> pd.DataFrame:
    """Require exact M4A-to-M4B.2 sample, group, target, and fold alignment."""

    local = evaluation[
        [
            "sample_id",
            "source_match_id",
            "match_start_utc",
            "patch",
            "radiant_win",
        ]
    ].copy()
    local.insert(0, "evaluation_id", fold_id)
    local["radiant_win"] = local["radiant_win"].astype("int8")
    local = local.reset_index(drop=True)
    fold_reference = reference[
        reference["evaluation_id"] == fold_id
    ].copy()
    if (
        len(local) != len(fold_reference)
        or fold_reference["sample_id"].duplicated().any()
        or set(local["sample_id"]) != set(fold_reference["sample_id"])
    ):
        raise InteractionExperimentError(
            f"{fold_id} reference sample coverage changed."
        )
    pinned = fold_reference.set_index("sample_id", drop=False).loc[
        local["sample_id"].tolist()
    ].reset_index(drop=True)
    for column in (
        "evaluation_id",
        "sample_id",
        "source_match_id",
        "patch",
        "radiant_win",
    ):
        left = local[column].astype("string").fillna("<NA>").to_numpy()
        right = pinned[column].astype("string").fillna("<NA>").to_numpy()
        if not np.array_equal(left, right):
            raise InteractionExperimentError(
                f"{fold_id} reference alignment changed: {column}."
            )
    local_timestamps = pd.to_datetime(
        local["match_start_utc"],
        errors="coerce",
        utc=True,
    )
    pinned_timestamps = pd.to_datetime(
        pinned["match_start_utc"],
        errors="coerce",
        utc=True,
    )
    if (
        local_timestamps.isna().any()
        or pinned_timestamps.isna().any()
        or not np.array_equal(
            local_timestamps.to_numpy(),
            pinned_timestamps.to_numpy(),
        )
    ):
        raise InteractionExperimentError(
            f"{fold_id} reference alignment changed: match_start_utc."
        )
    return pinned


def _candidate_fingerprint(
    config: InteractionExperimentConfig,
    candidate: InteractionCandidate,
) -> str:
    return _sha256_json(
        {
            "candidate_id": candidate.candidate_id,
            "C": candidate.regularization_c,
            "history_policy_id": config.history_policy_id,
            "transformer": config.transformer,
            "estimator": {
                "family": config.estimator.family,
                "penalty": config.estimator.penalty,
                "solver": config.estimator.solver,
                "class_weight": config.estimator.class_weight,
                "max_iter": config.estimator.max_iter,
                "random_seed": config.estimator.random_seed,
            },
        }
    )


def _new_estimator(
    config: InteractionExperimentConfig,
    candidate: InteractionCandidate,
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
        raise InteractionExperimentError(
            "An interaction candidate lacks the positive class."
        )
    values = np.asarray(
        estimator.predict_proba(matrix)[:, classes.index(1)],
        dtype=np.float64,
    )
    if (
        values.shape != (matrix.shape[0],)
        or not np.isfinite(values).all()
        or ((values < 0) | (values > 1)).any()
    ):
        raise InteractionExperimentError(
            "Interaction candidate probabilities are malformed."
        )
    return values


def _prediction_frame(
    pinned: pd.DataFrame,
    *,
    candidate: InteractionCandidate,
    probabilities: np.ndarray,
) -> pd.DataFrame:
    result = pinned.copy()
    result.insert(0, "C", candidate.regularization_c)
    result.insert(0, "candidate_id", candidate.candidate_id)
    result["candidate_probability"] = probabilities
    return result[list(_PREDICTION_COLUMNS)]


def _metrics(
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


def _selection_kwargs(config: InteractionExperimentConfig) -> dict[str, object]:
    policy = config.selection_policy
    bootstrap = policy["paired_group_bootstrap"]
    return {
        "n_resamples": int(bootstrap["replicates"]),
        "random_state": int(bootstrap["random_seed"]),
        "confidence_level": float(bootstrap["confidence_level"]),
        "minimum_recent_log_loss_improvement": float(
            policy["pooled_recent"][
                "minimum_log_loss_improvement_vs_frozen_b1"
            ]
        ),
        "practical_log_loss_tie": float(
            policy["ranking"]["practical_log_loss_tie"]
        ),
        "maximum_single_fold_log_loss_regression": float(
            policy["seven_fold"][
                "maximum_single_fold_log_loss_regression"
            ]
        ),
    }


def _render_report(
    *,
    fingerprint: str,
    config: InteractionExperimentConfig,
    selection: dict[str, Any],
    masking: dict[str, int | bool],
) -> str:
    selected = selection.get("selected_candidate_id") or "none"
    return "\n".join(
        [
            "# Milestone 4B.4: Draft Interaction Recovery Gate",
            "",
            f"- Build fingerprint: `{fingerprint}`",
            f"- Fixed candidates evaluated: `{len(config.candidates)}`",
            f"- Selected development candidate: `{selected}`",
            (
                "- Selection status: "
                f"`{selection.get('selection_status', 'unknown')}`"
            ),
            "- Feature family: `B1 pick presence + supported pick interactions`",
            (
                "- Minimum train-only interaction support: "
                f"`{MIN_INTERACTION_ROW_SUPPORT}`"
            ),
            "- Development folds: `2024-Q1 through 2025-Q3`",
            "- Selection folds: `2025-Q1 through 2025-Q3`",
            (
                "- Calibration targets masked before window selection: "
                f"`{masking['calibration_rows_masked']}` rows"
            ),
            (
                "- Locked-test targets masked before window selection: "
                f"`{masking['locked_test_rows_masked']}` rows"
            ),
            "- 2025-Q4 transforms / predictions: `0 / 0`",
            "- 2026-Q1 transforms / predictions: `0 / 0`",
            "- Model calibration: `not performed`",
            "- Model bundle: `not produced`",
            "- Authenticated API requests: `0`",
            "",
        ]
    )


def _result_from_paths(
    fingerprint: str,
    target: Path,
    manifest_path: Path,
    paths: dict[str, Path],
) -> InteractionExperimentResult:
    return InteractionExperimentResult(
        build_fingerprint=fingerprint,
        output_directory=target,
        manifest_path=manifest_path,
        predictions_path=paths["predictions"],
        metrics_path=paths["metrics"],
        support_audits_path=paths["support_audits"],
        explanations_path=paths["explanations"],
        selection_path=paths["selection"],
        patch_diagnostics_path=paths["patch_diagnostics"],
        report_path=paths["report"],
    )


def _verify_existing_build(
    *,
    fingerprint: str,
    target: Path,
    manifest_path: Path,
    paths: dict[str, Path],
) -> InteractionExperimentResult:
    manifest = _read_json(
        manifest_path,
        label="the existing M4B.4 manifest",
    )
    if manifest.get("build_fingerprint") != fingerprint:
        raise InteractionExperimentError("Existing M4B.4 fingerprint changed.")
    expected_names = set(paths)
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != expected_names:
        raise InteractionExperimentError(
            "Existing M4B.4 artifact inventory changed."
        )
    for name, path in paths.items():
        pin = artifacts[name]
        if (
            not isinstance(pin, dict)
            or pin.get("file") != path.name
            or not path.is_file()
            or sha256_file(path) != pin.get("sha256")
            or path.stat().st_size != pin.get("bytes")
        ):
            raise InteractionExperimentError(
                f"Existing M4B.4 artifact changed: {name}."
            )
    result = manifest.get("result", {})
    if (
        result.get("calibration_transform_rows") != 0
        or result.get("calibration_prediction_rows") != 0
        or result.get("locked_test_transform_rows") != 0
        or result.get("locked_test_prediction_rows") != 0
        or result.get("authenticated_api_requests") != 0
    ):
        raise InteractionExperimentError(
            "Existing M4B.4 safety result changed."
        )
    return _result_from_paths(
        fingerprint,
        target,
        manifest_path,
        paths,
    )


def run_interaction_experiment(
    experiment_config_path: Path,
    *,
    output_root: Path = Path("models/m4b4"),
    repository_root: Path | None = None,
) -> InteractionExperimentResult:
    """Run the two-candidate pre-Q4 interaction recovery experiment."""

    root = (
        repository_root.resolve()
        if repository_root is not None
        else Path(__file__).resolve().parents[2]
    )
    config = load_interaction_experiment_config(
        experiment_config_path.resolve(),
        repository_root=root,
    )
    split_manifest = _load_split_manifest(config)
    corpus = load_working_corpus(config.corpus_config_path)
    joined, masking = _masked_development_frame(
        corpus.frame,
        split_manifest,
    )
    source_rows = len(corpus.frame)
    source_matches = int(corpus.frame["source_match_id"].nunique())
    del corpus

    source = _source_lineage(config, root=root)
    reference = _load_reference_predictions(config)
    expected_folds = tuple(fold.fold_id for fold in config.rolling_origin_folds)
    if expected_folds[-1] != "2025-Q3":
        raise InteractionExperimentError(
            "M4B.4 must stop at the 2025-Q3 development fold."
        )
    if config.transformer["minimum_training_row_support"] != (
        MIN_INTERACTION_ROW_SUPPORT
    ):
        raise InteractionExperimentError(
            "The interaction support threshold changed."
        )

    candidates = [
        {
            "candidate_id": candidate.candidate_id,
            "C": candidate.regularization_c,
            "fingerprint": _candidate_fingerprint(config, candidate),
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
            "rows": source_rows,
            "source_matches": source_matches,
        },
        "candidates": candidates,
        "transformer": config.transformer,
        "selection_scope": list(
            config.selection_policy["selection_fold_ids"]
        ),
        "safety": config.safety,
        "runtime_versions": _runtime_versions(),
    }
    fingerprint = _sha256_json(core)
    target = output_root.resolve() / f"build_{fingerprint}"
    manifest_path = target / "experiment_manifest.json"
    paths = {
        "predictions": target / "development_predictions.parquet",
        "metrics": target / "fold_metrics.json",
        "support_audits": target / "feature_support_audits.json",
        "explanations": target / "coefficient_explanations.json",
        "selection": target / "selection.json",
        "patch_diagnostics": target / "patch_diagnostics.json",
        "report": target / "report.md",
    }
    if target.exists():
        return _verify_existing_build(
            fingerprint=fingerprint,
            target=target,
            manifest_path=manifest_path,
            paths=paths,
        )

    target.mkdir(parents=True)
    prediction_frames: list[pd.DataFrame] = []
    metric_records: list[dict[str, object]] = []
    support_audits: list[dict[str, object]] = []
    explanation_records: list[dict[str, object]] = []

    for fold in config.rolling_origin_folds:
        training, evaluation = _window_rows(joined, fold, config)
        pinned = _align_reference_fold(
            evaluation,
            reference,
            fold_id=fold.fold_id,
        )
        targets = training["radiant_win"].astype("int8").to_numpy()
        evaluation_targets = (
            evaluation["radiant_win"].astype("int8").to_numpy()
        )
        if len(np.unique(targets)) != 2:
            raise InteractionExperimentError(
                f"{fold.fold_id} training rows lack both target classes."
            )

        transformer = PickInteractionTransformer().fit(training)
        training_result = transformer.transform_with_audit(training)
        evaluation_result = transformer.transform_with_audit(evaluation)
        contract = transformer.feature_contract()
        support_audits.append(
            {
                "evaluation_id": fold.fold_id,
                "training_rows": len(training),
                "evaluation_rows": len(evaluation),
                "training_source_matches": int(
                    training["source_match_id"].nunique()
                ),
                "evaluation_source_matches": int(
                    evaluation["source_match_id"].nunique()
                ),
                "feature_fingerprint": transformer.fingerprint,
                "feature_columns": training_result.matrix.shape[1],
                "same_side_pair_vocabulary": len(
                    transformer.same_side_pairs_
                ),
                "radiant_synergy_columns": len(
                    transformer.same_side_pairs_
                ),
                "dire_synergy_columns": len(
                    transformer.same_side_pairs_
                ),
                "counter_pair_vocabulary": len(transformer.counter_pairs_),
                "training_transform_audit": training_result.audit,
                "evaluation_transform_audit": evaluation_result.audit,
                "feature_contract": contract,
            }
        )
        frozen_metrics = _metrics(
            evaluation_targets,
            pinned["frozen_b1_probability"].to_numpy(dtype=np.float64),
            n_bins=config.evaluation.reliability_bins,
        )
        b0_metrics = _metrics(
            evaluation_targets,
            pinned["canonical_b0_probability"].to_numpy(dtype=np.float64),
            n_bins=config.evaluation.reliability_bins,
        )

        for candidate in config.candidates:
            estimator = _new_estimator(config, candidate)
            _fit_estimator(estimator, training_result.matrix, targets)
            probabilities = _positive_probabilities(
                estimator,
                evaluation_result.matrix,
            )
            prediction_frames.append(
                _prediction_frame(
                    pinned,
                    candidate=candidate,
                    probabilities=probabilities,
                )
            )
            identity = {
                "candidate_id": candidate.candidate_id,
                "C": candidate.regularization_c,
                "evaluation_id": fold.fold_id,
                "training_rows": len(training),
                "evaluation_rows": len(evaluation),
                "candidate_fingerprint": next(
                    item["fingerprint"]
                    for item in candidates
                    if item["candidate_id"] == candidate.candidate_id
                ),
                "feature_fingerprint": transformer.fingerprint,
            }
            metric_records.append(
                {
                    **identity,
                    "candidate_metrics": _metrics(
                        evaluation_targets,
                        probabilities,
                        n_bins=config.evaluation.reliability_bins,
                    ),
                    "frozen_b1_metrics": frozen_metrics,
                    "canonical_b0_metrics": b0_metrics,
                }
            )
            explanation_records.append(
                {
                    **identity,
                    "explanation": (
                        global_logistic_coefficient_explanations(
                            estimator,
                            training_result.matrix,
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
    selection = select_interaction_candidate(
        predictions,
        **_selection_kwargs(config),
    )
    selected_id = selection.get("selected_candidate_id")
    selection_folds = set(config.selection_policy["selection_fold_ids"])
    if selected_id is None:
        patch_diagnostics: dict[str, object] = {
            "status": "not_generated_no_qualifying_candidate",
            "used_for_selection": False,
            "q4_or_locked_test_used": False,
        }
    else:
        selected_predictions = predictions[
            (predictions["candidate_id"] == selected_id)
            & predictions["evaluation_id"].isin(selection_folds)
        ].rename(
            columns={"candidate_probability": "radiant_win_probability"}
        )
        patch_diagnostics = {
            "status": "generated_pre_q4_for_selected_candidate",
            "candidate_id": selected_id,
            "q4_or_locked_test_used": False,
            **patch_group_descriptive_metrics(selected_predictions),
        }

    _write_parquet(predictions, paths["predictions"])
    _write_json(paths["metrics"], {"evaluations": metric_records})
    _write_json(
        paths["support_audits"],
        {"evaluations": support_audits},
    )
    _write_json(
        paths["explanations"],
        {"evaluations": explanation_records},
    )
    _write_json(paths["selection"], selection)
    _write_json(paths["patch_diagnostics"], patch_diagnostics)
    paths["report"].write_text(
        _render_report(
            fingerprint=fingerprint,
            config=config,
            selection=selection,
            masking=masking,
        ),
        encoding="utf-8",
    )
    artifacts = {name: _artifact(path) for name, path in paths.items()}
    manifest = {
        **core,
        "build_fingerprint": fingerprint,
        "git": _git_state(root),
        "masking": masking,
        "result": {
            "prediction_rows": len(predictions),
            "evaluation_records": len(metric_records),
            "feature_support_audits": len(support_audits),
            "selected_development_candidate": selected_id,
            "selection_status": selection.get("selection_status"),
            "calibration_transform_rows": 0,
            "calibration_prediction_rows": 0,
            "locked_test_transform_rows": 0,
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
    "InteractionExperimentError",
    "InteractionExperimentResult",
    "run_interaction_experiment",
]
