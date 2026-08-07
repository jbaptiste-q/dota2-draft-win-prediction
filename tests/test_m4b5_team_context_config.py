"""Contract tests for the fixed M4B.5 team-context experiment."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.draft_ai_modeling import team_context_config
from src.draft_ai_modeling.team_context_config import (
    TeamContextConfigError,
    load_team_context_experiment_config,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "configs/modeling/m4b5_team_context.json"


def _split_manifest_available() -> bool:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    manifest_path = ROOT / payload["source"]["split_manifest_path"]
    return manifest_path.is_file()


def test_repository_config_is_valid_and_deterministic() -> None:
    if not _split_manifest_available():
        pytest.skip("Ignored local M4A build is not present.")

    first = load_team_context_experiment_config(CONFIG_PATH)
    second = load_team_context_experiment_config(CONFIG_PATH)

    assert first.fingerprint == second.fingerprint
    assert len(first.fingerprint) == 64
    assert first.development_end_utc.isoformat() == (
        "2025-10-01T00:00:00+00:00"
    )
    assert first.q4_end_utc.isoformat() == "2026-01-01T00:00:00+00:00"
    assert [fold[0] for fold in first.folds] == [
        "2024-Q1",
        "2024-Q2",
        "2024-Q3",
        "2024-Q4",
        "2025-Q1",
        "2025-Q2",
        "2025-Q3",
    ]


def test_q4_prediction_hash_can_be_deferred(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not _split_manifest_available():
        pytest.skip("Ignored local M4A build is not present.")

    observed: list[str] = []
    real = team_context_config.sha256_file

    def recording(path: Path) -> str:
        observed.append(path.name)
        return real(path)

    monkeypatch.setattr(team_context_config, "sha256_file", recording)
    loaded = load_team_context_experiment_config(
        CONFIG_PATH,
        verify_q4_predictions=False,
    )

    assert loaded.source_paths["m4b3_predictions"].name == (
        "calibration_oof_predictions.parquet"
    )
    assert "calibration_oof_predictions.parquet" not in observed
    assert "development_predictions.parquet" in observed


def test_fixed_team_policy_cannot_drift(tmp_path: Path) -> None:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    payload["team_strength"]["k_factor"] = 24.0
    path = tmp_path / "drifted.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(TeamContextConfigError, match="team-strength"):
        load_team_context_experiment_config(
            path,
            repository_root=ROOT,
            verify_artifacts=False,
        )


def test_source_paths_cannot_escape_repository(tmp_path: Path) -> None:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    payload["source"]["corpus_config_path"] = "../outside.json"
    path = tmp_path / "escaping.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(TeamContextConfigError, match="repository-relative"):
        load_team_context_experiment_config(
            path,
            repository_root=ROOT,
            verify_artifacts=False,
        )
