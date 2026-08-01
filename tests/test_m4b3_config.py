"""Tests for the immutable M4B.3 calibration contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.draft_ai_modeling.calibration_config import (
    CalibrationConfigError,
    load_calibration_experiment_config,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "modeling" / "m4b3_calibration.json"


def _payload() -> dict[str, object]:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def _write(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def test_current_config_pins_the_frozen_candidate_and_roles() -> None:
    config = load_calibration_experiment_config(
        CONFIG,
        repository_root=ROOT,
        verify_local_artifacts=False,
    )

    assert config.candidate_id == "b1_full_uniform_c0p01"
    assert config.feature_variant == "b1-pick-presence"
    assert config.history_policy_id == "full_uniform"
    assert config.estimator.regularization_c == 0.01
    assert config.base_fit_roles == {"train", "tuning"}
    assert config.calibration_role == "calibration"
    assert config.prohibited_roles == {"locked_test"}
    assert config.methods == ("raw", "sigmoid", "isotonic")
    assert config.expected_counts["base_fit_rows"] == 20_087
    assert config.expected_counts["calibration_rows"] == 1_089
    assert config.expected_counts["locked_test_rows"] == 1_947
    assert config.fingerprint == (
        "53bda5500004f68c6c69c7e3d7c8049d72ff63219317ea1180c0541222dee7e9"
    )


def test_role_guard_seals_the_locked_test() -> None:
    config = load_calibration_experiment_config(
        CONFIG,
        repository_root=ROOT,
        verify_local_artifacts=False,
    )

    config.assert_role_allowed("train", purpose="base_fit")
    config.assert_role_allowed("tuning", purpose="base_fit")
    config.assert_role_allowed("calibration", purpose="calibrate")
    with pytest.raises(CalibrationConfigError, match="prohibited"):
        config.assert_role_allowed("locked_test", purpose="base_fit")
    with pytest.raises(CalibrationConfigError, match="not approved"):
        config.assert_role_allowed("calibration", purpose="base_fit")
    with pytest.raises(CalibrationConfigError, match="not approved"):
        config.assert_role_allowed("tuning", purpose="calibrate")


def test_current_local_lineage_pins_verify() -> None:
    config = load_calibration_experiment_config(
        CONFIG,
        repository_root=ROOT,
        verify_local_artifacts=True,
    )

    assert config.m4a.build_fingerprint.startswith("2c8c8d1a")
    assert config.m4b2.build_fingerprint.startswith("a05b2792")


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda payload: payload["methods"].append("beta"),
            "exactly raw",
        ),
        (
            lambda payload: payload["frozen_candidate"]["estimator"].update(
                {"C": 0.1}
            ),
            "estimator contract",
        ),
        (
            lambda payload: payload["cross_fit"].update({"folds": 4}),
            "cross-fit policy",
        ),
        (
            lambda payload: payload["selection_policy"][
                "calibrator_vs_raw"
            ].update({"minimum_log_loss_improvement": 0.0}),
            "selection policy",
        ),
        (
            lambda payload: payload["safety"].update(
                {"locked_test_predictions": True}
            ),
            "safety policy",
        ),
    ],
)
def test_config_rejects_policy_drift(
    tmp_path: Path,
    mutation: object,
    message: str,
) -> None:
    payload = _payload()
    mutation(payload)
    path = _write(tmp_path / "changed.json", payload)

    with pytest.raises(CalibrationConfigError, match=message):
        load_calibration_experiment_config(
            path,
            repository_root=ROOT,
            verify_local_artifacts=False,
        )


def test_config_rejects_escaping_paths(tmp_path: Path) -> None:
    payload = _payload()
    payload["source"]["corpus_config_path"] = "../outside.json"
    path = _write(tmp_path / "escape.json", payload)

    with pytest.raises(CalibrationConfigError, match="repository-relative"):
        load_calibration_experiment_config(
            path,
            repository_root=ROOT,
            verify_local_artifacts=False,
        )
