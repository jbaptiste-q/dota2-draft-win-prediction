"""Offline tests for the strict M4B.4 interaction experiment contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.draft_ai_modeling.interaction_config import (
    InteractionConfigError,
    load_interaction_experiment_config,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "modeling" / "m4b4_interactions.json"


def _payload() -> dict[str, object]:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def _write(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def test_config_freezes_the_two_candidate_interaction_gate() -> None:
    config = load_interaction_experiment_config(
        CONFIG,
        repository_root=ROOT,
        verify_local_artifacts=False,
    )

    assert config.experiment_id == "m4b4-pick-interaction-recovery-gate-v1"
    assert [
        (candidate.candidate_id, candidate.regularization_c)
        for candidate in config.candidates
    ] == [
        ("c1_pick_interactions_c0p001", 0.001),
        ("c1_pick_interactions_c0p01", 0.01),
    ]
    assert config.history_policy_id == "full_uniform"
    assert config.transformer["class"] == "PickInteractionTransformer"
    assert config.transformer["minimum_training_row_support"] == 50
    assert config.transformer["synergy"]["pair_order"] == "unordered"
    assert config.transformer["counter"]["pair_order"] == (
        "radiant_hero_then_dire_hero"
    )
    assert tuple(
        fold.fold_id for fold in config.rolling_origin_folds
    ) == (
        "2024-Q1",
        "2024-Q2",
        "2024-Q3",
        "2024-Q4",
        "2025-Q1",
        "2025-Q2",
        "2025-Q3",
    )
    assert config.fingerprint == (
        "4662f98726c8d761785573eff7da76f6fbea3d39730c88c31b029bc2cd1fb701"
    )


def test_selection_policy_is_exact_and_development_only() -> None:
    config = load_interaction_experiment_config(
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
    assert selection["references"] == ["frozen_b1", "canonical_b0"]
    assert selection["recent_per_fold"]["required_folds"] == "all"
    assert (
        selection["pooled_recent"][
            "minimum_log_loss_improvement_vs_frozen_b1"
        ]
        == 0.002
    )
    assert (
        selection["paired_group_bootstrap"][
            "require_upper_bound_below"
        ]
        == 0.0
    )
    assert selection["seven_fold"] == {
        "mean_log_loss_no_worse_than_frozen_b1": True,
        "maximum_single_fold_log_loss_regression": 0.01,
    }
    assert selection["ranking"]["C_preference"] == [0.001, 0.01]

    assert config.fit_roles == {"train"}
    assert config.development_evaluation_roles == {"train", "tuning"}
    assert config.prohibited_roles == {"calibration", "locked_test"}
    assert config.safety["authenticated_api_requests"] == 0
    assert config.safety["calibration_predictions"] is False
    assert config.safety["locked_test_target_use"] is False
    assert config.safety["locked_test_transform"] is False
    assert config.safety["locked_test_predictions"] is False
    assert config.safety["model_serialization"] is False


def test_role_guard_seals_q4_and_locked_q1() -> None:
    config = load_interaction_experiment_config(
        CONFIG,
        repository_root=ROOT,
        verify_local_artifacts=False,
    )

    config.assert_role_allowed("train", purpose="fit")
    config.assert_role_allowed("train", purpose="evaluate")
    config.assert_role_allowed("tuning", purpose="evaluate")
    with pytest.raises(InteractionConfigError, match="prohibited"):
        config.assert_role_allowed("calibration", purpose="evaluate")
    with pytest.raises(InteractionConfigError, match="prohibited"):
        config.assert_role_allowed("locked_test", purpose="fit")
    with pytest.raises(InteractionConfigError, match="not approved"):
        config.assert_role_allowed("tuning", purpose="fit")


def test_lineage_pins_include_b1_references_but_not_q4_predictions() -> None:
    payload = _payload()
    m4b3 = payload["source"]["m4b3"]
    assert "predictions_path" not in m4b3
    assert "predictions_sha256" not in m4b3

    config = load_interaction_experiment_config(
        CONFIG,
        repository_root=ROOT,
        verify_local_artifacts=False,
    )
    assert config.m4b2.predictions_sha256 == (
        "9ec6a96513cbd16113de155b24fee4eb2b8abfc4773d5960c6b0295daf49431b"
    )
    assert config.m4b2.selection_sha256 == (
        "120bbb45ee12714f67efb93db89ef5c51b7e60a8d12355188c204a9610ab261b"
    )
    assert config.m4b3.manifest_sha256 == (
        "5a968b5d0d1b9e09e3ba31d16c09454078f4b2ec0d7ba99fa4d9a8018de9cd15"
    )
    assert config.m4b3.readiness_sha256 == (
        "a5c3ea0dadb59cffc7e4b2a79fd1227e105eaa22c5cd3f8865338761b443891b"
    )
    assert config.m4b3.selection_sha256 == (
        "06d5d37bd65e84c27b67f539e101d2d8118e17c588a90ff15c1da93e0c4bdf60"
    )


def test_current_local_lineage_verifies_without_opening_q4_predictions() -> None:
    config = load_interaction_experiment_config(
        CONFIG,
        repository_root=ROOT,
        verify_local_artifacts=True,
    )

    assert config.m4a.build_fingerprint.startswith("2c8c8d1a")
    assert config.m4b2.build_fingerprint.startswith("a05b2792")
    assert config.m4b3.build_fingerprint.startswith("3f768bb1")


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda payload: payload["candidates"].pop(),
            "exactly the two",
        ),
        (
            lambda payload: payload["candidates"][0].update({"C": 0.002}),
            "exactly the two",
        ),
        (
            lambda payload: payload["transformer"].update(
                {"minimum_training_row_support": 25}
            ),
            "transformer contract",
        ),
        (
            lambda payload: payload["selection_policy"]["pooled_recent"].update(
                {"minimum_log_loss_improvement_vs_frozen_b1": 0.0}
            ),
            "selection policy",
        ),
        (
            lambda payload: payload["safety"].update(
                {"calibration_predictions": True}
            ),
            "safety policy",
        ),
        (
            lambda payload: payload["roles"]["prohibited"].remove(
                "calibration"
            ),
            "role policy",
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

    with pytest.raises(InteractionConfigError, match=message):
        load_interaction_experiment_config(
            path,
            repository_root=ROOT,
            verify_local_artifacts=False,
        )


def test_strict_shape_rejects_unknown_keys(tmp_path: Path) -> None:
    payload = _payload()
    payload["safety"]["future_switch"] = False
    path = _write(tmp_path / "extra-key.json", payload)

    with pytest.raises(InteractionConfigError, match="Malformed safety shape"):
        load_interaction_experiment_config(
            path,
            repository_root=ROOT,
            verify_local_artifacts=False,
        )


def test_config_rejects_unsafe_fold_and_escaping_path(tmp_path: Path) -> None:
    payload = _payload()
    payload["rolling_origin_folds"][0]["train_end_utc"] = (
        "2024-02-01T00:00:00Z"
    )
    path = _write(tmp_path / "unsafe-fold.json", payload)
    with pytest.raises(InteractionConfigError, match="past-only"):
        load_interaction_experiment_config(
            path,
            repository_root=ROOT,
            verify_local_artifacts=False,
        )

    payload = _payload()
    payload["source"]["m4b2"]["predictions_path"] = "../predictions.parquet"
    path = _write(tmp_path / "escape.json", payload)
    with pytest.raises(
        InteractionConfigError, match="repository-relative"
    ):
        load_interaction_experiment_config(
            path,
            repository_root=ROOT,
            verify_local_artifacts=False,
        )
