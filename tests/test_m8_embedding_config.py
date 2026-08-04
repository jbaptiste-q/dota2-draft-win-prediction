"""Offline tests for the immutable M8 hero-embedding configuration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.draft_ai_modeling.embedding_config import (
    EmbeddingConfigError,
    load_embedding_experiment_config,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "modeling" / "m8_embeddings.json"


def _payload() -> dict[str, object]:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def _write_payload(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def test_public_config_is_exactly_the_nine_candidate_matrix() -> None:
    config = load_embedding_experiment_config(
        CONFIG,
        repository_root=ROOT,
        verify_local_artifacts=False,
    )

    assert config.experiment_id == "m8-hero-embeddings-v1"
    assert len(config.candidates) == 9
    assert {candidate.embedding_dim for candidate in config.candidates} == {
        4,
        8,
        16,
    }
    assert {candidate.l2 for candidate in config.candidates} == {
        0.01,
        0.1,
        1.0,
    }
    assert {
        candidate.history_policy_id for candidate in config.candidates
    } == {"full_uniform"}
    combinations = {
        (candidate.embedding_dim, candidate.l2)
        for candidate in config.candidates
    }
    assert len(combinations) == 9
    assert len(config.history_policies) == 1
    assert config.history_policy("full_uniform").sample_weight == "uniform"
    assert len(config.fingerprint) == 64


def test_selection_and_safety_are_development_only() -> None:
    config = load_embedding_experiment_config(
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
        "frozen_b1_candidate",
    ]
    paired = selection["paired_group_bootstrap"]
    assert paired["references"] == ["canonical_b0", "frozen_b1_candidate"]
    assert paired["replicates"] == 1000
    assert paired["group_column"] == "source_match_id"
    assert paired["require_upper_bound_below"] == 0.0
    assert selection["embedding_dim_preference"] == [4, 8, 16]
    assert selection["l2_preference"] == [1.0, 0.1, 0.01]
    assert config.safety["api_dependency"] is False
    assert config.safety["acquisition_dependency"] is False
    assert config.safety["calibration_predictions"] is False
    assert config.safety["locked_test_predictions"] is False
    assert config.safety["patch_features"] is False
    assert config.safety["context_features"] is False
    assert config.safety["deep_learning_framework_dependency"] is False
    assert config.safety["model_serialization"] is False


def test_role_guard_rejects_reserved_future_roles() -> None:
    config = load_embedding_experiment_config(
        CONFIG,
        repository_root=ROOT,
        verify_local_artifacts=False,
    )

    config.assert_role_allowed("train", purpose="fit")
    config.assert_role_allowed("train", purpose="evaluate")
    config.assert_role_allowed("tuning", purpose="evaluate")
    with pytest.raises(EmbeddingConfigError, match="prohibited"):
        config.assert_role_allowed("calibration", purpose="evaluate")
    with pytest.raises(EmbeddingConfigError, match="prohibited"):
        config.assert_role_allowed("locked_test", purpose="evaluate")
    with pytest.raises(EmbeddingConfigError, match="not approved"):
        config.assert_role_allowed("tuning", purpose="fit")


def test_config_fingerprint_and_public_pins_are_stable() -> None:
    first = load_embedding_experiment_config(
        CONFIG,
        repository_root=ROOT,
        verify_local_artifacts=False,
    )
    second = load_embedding_experiment_config(
        CONFIG,
        repository_root=ROOT,
        verify_local_artifacts=False,
    )

    assert first.fingerprint == second.fingerprint
    assert len(first.fingerprint) == 64
    assert first.m4a.manifest_sha256 == (
        "33b144502306f1a7200bd5198be1fc8ae50c6b5e5a9e946f2e82461bb4c61f54"
    )
    assert first.m4b1.build.manifest_sha256 == (
        "635c1312616330ffd12c07bffbc3bcffae8a7d3e2a7a61b5f0479d3bb4a37fc0"
    )
    assert first.m4b2.build.manifest_sha256 == (
        "fe18aac6aafd9e9e0848aeede14e49c6cee9bb8cfe2769c4c43c01a86f280872"
    )
    assert first.m4b2.frozen_reference_candidate.candidate_id == (
        "b1_full_uniform_c0p01"
    )
    assert first.m4b2.frozen_reference_candidate.regularization_c == 0.01
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
        artifact.name for artifact in first.m4b2.build.artifacts
    } == {"predictions", "selection", "metrics"}


def test_public_validation_does_not_require_ignored_artifacts(
    tmp_path: Path,
) -> None:
    path = _write_payload(tmp_path / "public.json", _payload())

    config = load_embedding_experiment_config(
        path,
        repository_root=tmp_path,
        verify_local_artifacts=False,
    )
    assert len(config.candidates) == 9

    with pytest.raises(EmbeddingConfigError, match="corpus config"):
        load_embedding_experiment_config(
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
            lambda payload: payload["candidates"][0].update(
                {"l2": 0.02}
            ),
            "exact nine",
        ),
        (
            lambda payload: payload["history_policies"].append(
                {
                    "history_policy_id": "full_exp180",
                    "training_rows": "all_strictly_past_rows",
                    "sample_weight": "exponential_half_life",
                    "anchor": "train_end_utc",
                }
            ),
            "full_uniform history policy",
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

    with pytest.raises(EmbeddingConfigError, match=message):
        load_embedding_experiment_config(
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
    with pytest.raises(EmbeddingConfigError, match="past-only"):
        load_embedding_experiment_config(
            path,
            repository_root=ROOT,
            verify_local_artifacts=False,
        )

    payload = _payload()
    payload["source"]["corpus_config_path"] = "../outside.json"
    path = _write_payload(tmp_path / "escape.json", payload)
    with pytest.raises(EmbeddingConfigError, match="repository-relative"):
        load_embedding_experiment_config(
            path,
            repository_root=ROOT,
            verify_local_artifacts=False,
        )


def test_current_local_pins_verify_strictly_when_present() -> None:
    manifest_path = (
        ROOT / _payload()["source"]["m4b2"]["manifest_path"]
    )
    if not manifest_path.is_file():
        pytest.skip("Ignored local M4B.2 build is not present.")

    config = load_embedding_experiment_config(
        CONFIG,
        repository_root=ROOT,
        verify_local_artifacts=True,
    )

    assert config.m4b2.build.build_fingerprint == (
        "a05b2792e3096869d10d7b58339542ceb3bfcf96810a6357520bacc8ac711456"
    )
