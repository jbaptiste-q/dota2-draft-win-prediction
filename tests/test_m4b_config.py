"""Offline tests for the immutable M4B.1 experiment configuration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.draft_ai_modeling.experiment_config import (
    ExperimentConfigError,
    load_experiment_config,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "modeling" / "m4b_baselines.json"


def test_real_m4b_config_is_pinned_and_development_only() -> None:
    config = load_experiment_config(
        CONFIG,
        repository_root=ROOT,
        verify_local_artifacts=False,
    )

    assert [item.value for item in config.baseline_ids] == [
        "B0",
        "B1",
        "B2",
        "B3",
    ]
    assert config.fit_role == "train"
    assert config.selection_role == "tuning"
    assert config.prohibited_roles == {"calibration", "locked_test"}
    assert [fold.fold_id for fold in config.rolling_origin_folds] == [
        "2024-Q1",
        "2024-Q2",
        "2024-Q3",
        "2024-Q4",
        "2025-Q1",
        "2025-Q2",
        "2025-Q3",
    ]
    assert len(config.fingerprint) == 64


def test_role_guard_rejects_calibration_and_locked_test() -> None:
    config = load_experiment_config(
        CONFIG,
        repository_root=ROOT,
        verify_local_artifacts=False,
    )

    config.assert_role_allowed("train", purpose="fit")
    config.assert_role_allowed("tuning", purpose="evaluate")
    with pytest.raises(ExperimentConfigError, match="prohibited"):
        config.assert_role_allowed("calibration", purpose="evaluate")
    with pytest.raises(ExperimentConfigError, match="prohibited"):
        config.assert_role_allowed("locked_test", purpose="evaluate")
    with pytest.raises(ExperimentConfigError, match="not approved"):
        config.assert_role_allowed("tuning", purpose="fit")


def test_config_fingerprint_is_stable() -> None:
    first = load_experiment_config(
        CONFIG,
        repository_root=ROOT,
        verify_local_artifacts=False,
    )
    second = load_experiment_config(
        CONFIG,
        repository_root=ROOT,
        verify_local_artifacts=False,
    )

    assert first.fingerprint == second.fingerprint


def test_config_rejects_unsafe_role_or_fold(
    tmp_path: Path,
) -> None:
    payload = json.loads(CONFIG.read_text(encoding="utf-8"))
    payload["roles"]["selection"] = "locked_test"
    path = tmp_path / "unsafe.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ExperimentConfigError):
        load_experiment_config(path, repository_root=ROOT)

    payload = json.loads(CONFIG.read_text(encoding="utf-8"))
    payload["rolling_origin_folds"][0]["train_end_utc"] = (
        "2024-02-01T00:00:00Z"
    )
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ExperimentConfigError, match="past-only"):
        load_experiment_config(path, repository_root=ROOT)


def test_config_paths_cannot_escape_repository(
    tmp_path: Path,
) -> None:
    payload = json.loads(CONFIG.read_text(encoding="utf-8"))
    payload["source"]["corpus_config_path"] = "../outside.json"
    path = tmp_path / "escape.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ExperimentConfigError, match="repository-relative"):
        load_experiment_config(path, repository_root=ROOT)
