"""Offline tests for the immutable M4B.2 recency configuration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.draft_ai_modeling.recency_config import (
    RecencyConfigError,
    load_recency_experiment_config,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "modeling" / "m4b2_recency.json"


def _payload() -> dict[str, object]:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def _write_payload(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def test_public_config_is_exactly_the_nine_candidate_matrix() -> None:
    config = load_recency_experiment_config(
        CONFIG,
        repository_root=ROOT,
        verify_local_artifacts=False,
    )

    assert config.experiment_id == "m4b2-b1-regularization-recency-v1"
    assert len(config.candidates) == 9
    assert {
        candidate.regularization_c for candidate in config.candidates
    } == {0.01, 0.1, 1.0}
    assert {
        candidate.history_policy_id for candidate in config.candidates
    } == {
        "full_uniform",
        "full_exp180",
        "trailing365_uniform",
    }
    combinations = {
        (candidate.history_policy_id, candidate.regularization_c)
        for candidate in config.candidates
    }
    assert len(combinations) == 9
    assert config.history_policy("full_exp180").half_life_days == 180
    assert config.history_policy("full_exp180").normalization == "mean_one"
    assert config.history_policy("trailing365_uniform").window_days == 365
    assert len(config.fingerprint) == 64


def test_selection_and_safety_are_development_only() -> None:
    config = load_recency_experiment_config(
        CONFIG,
        repository_root=ROOT,
        verify_local_artifacts=False,
    )

    selection = config.selection_policy
    assert selection["selection_fold_ids"] == [
        "2025-Q1",
        "2025-Q2",
        "2025-Q3",
    ]
    assert selection["qualification_metrics"] == [
        "log_loss",
        "brier_score",
    ]
    assert selection["point_estimate_references"] == [
        "canonical_b0",
        "policy_matched_b0",
    ]
    paired = selection["paired_group_bootstrap"]
    assert paired["reference"] == "policy_matched_b0"
    assert paired["require_upper_bound_below"] == 0.0
    assert selection["history_preference"] == [
        "full_uniform",
        "full_exp180",
        "trailing365_uniform",
    ]
    assert selection["C_preference"] == [0.01, 0.1, 1.0]
    assert config.safety["api_dependency"] is False
    assert config.safety["acquisition_dependency"] is False
    assert config.safety["calibration_predictions"] is False
    assert config.safety["locked_test_predictions"] is False
    assert config.safety["patch_features"] is False
    assert config.safety["context_features"] is False
    assert config.safety["b2_or_b3_candidates"] is False


def test_role_guard_rejects_reserved_future_roles() -> None:
    config = load_recency_experiment_config(
        CONFIG,
        repository_root=ROOT,
        verify_local_artifacts=False,
    )

    config.assert_role_allowed("train", purpose="fit")
    config.assert_role_allowed("train", purpose="evaluate")
    config.assert_role_allowed("tuning", purpose="evaluate")
    with pytest.raises(RecencyConfigError, match="prohibited"):
        config.assert_role_allowed("calibration", purpose="evaluate")
    with pytest.raises(RecencyConfigError, match="prohibited"):
        config.assert_role_allowed("locked_test", purpose="evaluate")
    with pytest.raises(RecencyConfigError, match="not approved"):
        config.assert_role_allowed("tuning", purpose="fit")


def test_config_fingerprint_and_public_pins_are_stable() -> None:
    first = load_recency_experiment_config(
        CONFIG,
        repository_root=ROOT,
        verify_local_artifacts=False,
    )
    second = load_recency_experiment_config(
        CONFIG,
        repository_root=ROOT,
        verify_local_artifacts=False,
    )

    assert (
        first.fingerprint
        == second.fingerprint
        == "acf46a96a10acc575020de8cbec3768168e00f13e7916af4184fd32c1c766b91"
    )
    assert first.m4a.manifest_sha256 == (
        "33b144502306f1a7200bd5198be1fc8ae50c6b5e5a9e946f2e82461bb4c61f54"
    )
    assert first.m4b1.build.manifest_sha256 == (
        "635c1312616330ffd12c07bffbc3bcffae8a7d3e2a7a61b5f0479d3bb4a37fc0"
    )
    assert {
        artifact.name for artifact in first.m4a.artifacts
    } == {
        "baseline_contracts_json",
        "feature_contracts_json",
        "preparation_report_md",
        "split_manifest_parquet",
        "split_report_json",
        "split_report_md",
    }
    assert {
        artifact.name for artifact in first.m4b1.build.artifacts
    } == {
        "comparison",
        "confidence_intervals",
        "explanations",
        "metrics",
        "reliability",
        "report",
        "rolling_predictions",
        "tuning_predictions",
    }


def test_public_validation_does_not_require_ignored_artifacts(
    tmp_path: Path,
) -> None:
    path = _write_payload(tmp_path / "public.json", _payload())

    config = load_recency_experiment_config(
        path,
        repository_root=tmp_path,
        verify_local_artifacts=False,
    )
    assert len(config.candidates) == 9

    with pytest.raises(RecencyConfigError, match="corpus config"):
        load_recency_experiment_config(
            path,
            repository_root=tmp_path,
            verify_local_artifacts=True,
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda payload: payload["candidates"].pop(),
            "exact nine",
        ),
        (
            lambda payload: payload["candidates"][0].update({"C": 0.02}),
            "exact nine",
        ),
        (
            lambda payload: payload["history_policies"][1].update(
                {"half_life_days": 365}
            ),
            "history policies",
        ),
        (
            lambda payload: payload["selection_policy"].update(
                {"selection_fold_ids": ["2025-Q3"]}
            ),
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
def test_config_rejects_matrix_or_policy_drift(
    tmp_path: Path,
    mutation: object,
    message: str,
) -> None:
    payload = _payload()
    mutation(payload)
    path = _write_payload(tmp_path / "changed.json", payload)

    with pytest.raises(RecencyConfigError, match=message):
        load_recency_experiment_config(
            path,
            repository_root=ROOT,
            verify_local_artifacts=False,
        )


def test_config_rejects_unsafe_fold_and_path(tmp_path: Path) -> None:
    payload = _payload()
    payload["rolling_origin_folds"][0]["train_end_utc"] = (
        "2024-02-01T00:00:00Z"
    )
    path = _write_payload(tmp_path / "unsafe-fold.json", payload)
    with pytest.raises(RecencyConfigError, match="past-only"):
        load_recency_experiment_config(
            path,
            repository_root=ROOT,
            verify_local_artifacts=False,
        )

    payload = _payload()
    payload["source"]["corpus_config_path"] = "../outside.json"
    path = _write_payload(tmp_path / "escape.json", payload)
    with pytest.raises(RecencyConfigError, match="repository-relative"):
        load_recency_experiment_config(
            path,
            repository_root=ROOT,
            verify_local_artifacts=False,
        )


def test_current_local_pins_verify_strictly_when_present() -> None:
    manifest_path = (
        ROOT / _payload()["source"]["m4b1"]["manifest_path"]
    )
    if not manifest_path.is_file():
        pytest.skip("Ignored local M4B.1 build is not present.")

    config = load_recency_experiment_config(
        CONFIG,
        repository_root=ROOT,
        verify_local_artifacts=True,
    )

    assert config.m4b1.build.build_fingerprint == (
        "391418b8096620924b75c09f518b94ba304fbf5d02a16dc94af7eb7cd7f3410f"
    )
