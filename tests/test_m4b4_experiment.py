"""Offline integration tests for the bounded M4B.4 experiment runner."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pandas as pd
import pytest

from src.draft_ai_modeling.interaction_features import (
    PickInteractionTransformer,
)
from src.draft_ai_modeling.loader import LoadedWorkingCorpus
from src.draft_training_dataset.schema import TRAINING_COLUMNS


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "modeling" / "m4b4_interactions.json"


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _row(
    row_id: str,
    timestamp: str,
    *,
    radiant_win: bool,
) -> dict[str, object]:
    row: dict[str, object] = {
        "sample_id": row_id,
        "game_key": row_id,
        "source_game_id": "1",
        "game_index": 1,
        "source_match_id": f"match-{row_id}",
        "match_start_utc": pd.Timestamp(timestamp),
        "patch": "7.38",
        "liquipedia_tier": "1",
        "tournament": "Synthetic Cup",
        "series": "Group Stage",
        "radiant_team_key": f"radiant-{row_id}",
        "dire_team_key": f"dire-{row_id}",
        "radiant_win": radiant_win,
    }
    for side, prefix in (("radiant", "r"), ("dire", "d")):
        for slot in range(1, 6):
            row[f"{side}_pick_slot_{slot}"] = f"{prefix}-hero-{slot}"
        for slot in range(1, 8):
            row[f"{side}_ban_slot_{slot}"] = f"{prefix}-ban-{slot}"
    return row


def _synthetic_frame() -> pd.DataFrame:
    periods = (
        ("history", "2022-02-01T00:00:00Z"),
        ("2024q1", "2024-02-01T00:00:00Z"),
        ("2024q2", "2024-05-01T00:00:00Z"),
        ("2024q3", "2024-08-01T00:00:00Z"),
        ("2024q4", "2024-11-01T00:00:00Z"),
        ("2025q1", "2025-02-01T00:00:00Z"),
        ("2025q2", "2025-05-01T00:00:00Z"),
        ("2025q3", "2025-08-01T00:00:00Z"),
        ("calibration", "2025-11-01T00:00:00Z"),
        ("locked", "2026-02-01T00:00:00Z"),
    )
    rows = [
        _row(f"{prefix}-win", timestamp, radiant_win=True)
        for prefix, timestamp in periods
    ] + [
        _row(f"{prefix}-loss", timestamp, radiant_win=False)
        for prefix, timestamp in periods
    ]
    frame = pd.DataFrame(rows, columns=TRAINING_COLUMNS)
    frame["match_start_utc"] = pd.to_datetime(
        frame["match_start_utc"],
        utc=True,
    )
    frame["radiant_win"] = frame["radiant_win"].astype("boolean")
    return frame.sort_values(
        ["match_start_utc", "source_match_id"],
        kind="mergesort",
    ).reset_index(drop=True)


def _role(timestamp: pd.Timestamp) -> str:
    if timestamp < pd.Timestamp("2025-07-01", tz="UTC"):
        return "train"
    if timestamp < pd.Timestamp("2025-10-01", tz="UTC"):
        return "tuning"
    if timestamp < pd.Timestamp("2026-01-01", tz="UTC"):
        return "calibration"
    return "locked_test"


def _split(frame: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "sample_id": frame["sample_id"],
            "source_match_id": frame["source_match_id"],
            "match_start_utc": frame["match_start_utc"],
            "primary_split": [
                (
                    "train"
                    if _role(timestamp) == "train"
                    else (
                        "validation"
                        if _role(timestamp) != "locked_test"
                        else "test"
                    )
                )
                for timestamp in frame["match_start_utc"]
            ],
            "split_role": [
                _role(timestamp) for timestamp in frame["match_start_utc"]
            ],
            "split_interval_id": [
                _role(timestamp) for timestamp in frame["match_start_utc"]
            ],
        }
    )


def _folds() -> tuple[SimpleNamespace, ...]:
    values = (
        ("2024-Q1", "2024-01-01", "2024-04-01"),
        ("2024-Q2", "2024-04-01", "2024-07-01"),
        ("2024-Q3", "2024-07-01", "2024-10-01"),
        ("2024-Q4", "2024-10-01", "2025-01-01"),
        ("2025-Q1", "2025-01-01", "2025-04-01"),
        ("2025-Q2", "2025-04-01", "2025-07-01"),
        ("2025-Q3", "2025-07-01", "2025-10-01"),
    )
    return tuple(
        SimpleNamespace(
            fold_id=fold_id,
            train_start_utc=_utc("2022-01-01T00:00:00Z"),
            train_end_utc=_utc(f"{start}T00:00:00Z"),
            evaluation_start_utc=_utc(f"{start}T00:00:00Z"),
            evaluation_end_utc=_utc(f"{end}T00:00:00Z"),
        )
        for fold_id, start, end in values
    )


class _FakeConfig(SimpleNamespace):
    def assert_role_allowed(self, role: str, *, purpose: str) -> None:
        allowed = {"train"} if purpose == "fit" else {"train", "tuning"}
        if role not in allowed:
            raise ValueError(f"Forbidden synthetic role: {role}/{purpose}")


def _config() -> _FakeConfig:
    return _FakeConfig(
        config_path=CONFIG,
        experiment_id="m4b4-pick-interaction-recovery-v1",
        fingerprint="a" * 64,
        corpus_config_path=ROOT
        / "configs"
        / "modeling"
        / "m4a_working_corpus.json",
        corpus_config_sha256="b" * 64,
        corpus_id="synthetic-corpus",
        split_manifest_fingerprint="c" * 64,
        m4a=SimpleNamespace(build_fingerprint="d" * 64),
        m4b2=SimpleNamespace(
            frozen_candidate_id="b1_full_uniform_c0p01",
            frozen_candidate_fingerprint="e" * 64,
        ),
        m4b3=SimpleNamespace(build_fingerprint="f" * 64),
        candidates=(
            SimpleNamespace(
                candidate_id="c1_pick_interactions_c0p001",
                regularization_c=0.001,
            ),
            SimpleNamespace(
                candidate_id="c1_pick_interactions_c0p01",
                regularization_c=0.01,
            ),
        ),
        history_policy_id="full_uniform",
        transformer={"minimum_training_row_support": 50},
        estimator=SimpleNamespace(
            family="logistic_regression",
            penalty="l2",
            solver="liblinear",
            class_weight=None,
            max_iter=2000,
            random_seed=42,
        ),
        rolling_origin_folds=_folds(),
        evaluation=SimpleNamespace(
            reliability_bins=5,
            coefficient_top_k=3,
        ),
        selection_policy={
            "selection_fold_ids": ["2025-Q1", "2025-Q2", "2025-Q3"],
            "pooled_recent": {
                "minimum_log_loss_improvement_vs_frozen_b1": 0.002,
            },
            "ranking": {"practical_log_loss_tie": 0.002},
            "seven_fold": {
                "maximum_single_fold_log_loss_regression": 0.01,
            },
            "paired_group_bootstrap": {
                "replicates": 5,
                "random_seed": 42,
                "confidence_level": 0.95,
            },
        },
        safety={"authenticated_api_requests": 0},
    )


def _reference(
    frame: pd.DataFrame,
    folds: tuple[SimpleNamespace, ...],
) -> pd.DataFrame:
    records: list[pd.DataFrame] = []
    for fold in folds:
        rows = frame[
            frame["match_start_utc"].ge(fold.evaluation_start_utc)
            & frame["match_start_utc"].lt(fold.evaluation_end_utc)
        ][
            [
                "sample_id",
                "source_match_id",
                "match_start_utc",
                "patch",
                "radiant_win",
            ]
        ].copy()
        rows.insert(0, "evaluation_id", fold.fold_id)
        targets = rows["radiant_win"].astype("int8")
        rows["radiant_win"] = targets
        rows["frozen_b1_probability"] = targets.map({1: 0.55, 0: 0.45})
        rows["canonical_b0_probability"] = 0.5
        records.append(rows)
    return pd.concat(records, ignore_index=True)


def test_both_reserved_target_roles_are_masked_immediately() -> None:
    from src.draft_ai_modeling.interaction_experiment import (
        _masked_development_frame,
    )

    frame = _synthetic_frame()
    joined, audit = _masked_development_frame(frame, _split(frame))

    assert joined.loc[
        joined["split_role"].isin({"calibration", "locked_test"}),
        "radiant_win",
    ].isna().all()
    assert audit == {
        "calibration_rows_masked": 2,
        "locked_test_rows_masked": 2,
        "reserved_targets_masked_before_window_selection": True,
    }


def test_reference_alignment_rejects_a_source_match_change() -> None:
    from src.draft_ai_modeling.interaction_experiment import (
        InteractionExperimentError,
        _align_reference_fold,
    )

    frame = _synthetic_frame()
    fold = _folds()[0]
    evaluation = frame[
        frame["match_start_utc"].ge(fold.evaluation_start_utc)
        & frame["match_start_utc"].lt(fold.evaluation_end_utc)
    ]
    reference = _reference(frame, (fold,))
    reference["match_start_utc"] = reference[
        "match_start_utc"
    ].dt.tz_convert("Asia/Shanghai")
    aligned = _align_reference_fold(
        evaluation,
        reference,
        fold_id=fold.fold_id,
    )
    assert len(aligned) == len(evaluation)

    reference.loc[0, "source_match_id"] = "changed-group"

    with pytest.raises(
        InteractionExperimentError,
        match="source_match_id",
    ):
        _align_reference_fold(
            evaluation,
            reference,
            fold_id=fold.fold_id,
        )


def test_runner_never_transforms_reserved_rows_and_verifies_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.draft_ai_modeling import interaction_experiment as module

    config = _config()
    frame = _synthetic_frame()
    split = _split(frame)
    reference = _reference(frame, config.rolling_origin_folds)
    corpus = LoadedWorkingCorpus(
        config=SimpleNamespace(corpus_id=config.corpus_id),
        frame=frame,
        verified_component_ids=("synthetic",),
    )
    transformed_samples: list[set[str]] = []

    class GuardedTransformer(PickInteractionTransformer):
        def _guard(self, rows: pd.DataFrame) -> None:
            samples = set(rows["sample_id"].astype(str))
            assert not any(
                "calibration" in sample or "locked" in sample
                for sample in samples
            )
            transformed_samples.append(samples)

        def fit(
            self,
            rows: pd.DataFrame,
            y: object = None,
        ) -> "GuardedTransformer":
            self._guard(rows)
            super().fit(rows, y)
            return self

        def transform_with_audit(  # type: ignore[no-untyped-def]
            self,
            rows: pd.DataFrame,
        ):
            self._guard(rows)
            return super().transform_with_audit(rows)

    monkeypatch.setattr(
        module,
        "load_interaction_experiment_config",
        lambda *args, **kwargs: config,
    )
    monkeypatch.setattr(module, "_load_split_manifest", lambda *args: split)
    monkeypatch.setattr(module, "load_working_corpus", lambda *args: corpus)
    monkeypatch.setattr(
        module,
        "_source_lineage",
        lambda *args, **kwargs: {
            "corpus_id": config.corpus_id,
            "m4a": {"build_fingerprint": "d" * 64},
            "m4b2": {
                "development_predictions_sha256": "e" * 64,
            },
            "m4b3": {"build_fingerprint": "f" * 64},
        },
    )
    monkeypatch.setattr(
        module,
        "_load_reference_predictions",
        lambda *args: reference,
    )
    monkeypatch.setattr(module, "_source_sha256", lambda: "1" * 64)
    monkeypatch.setattr(
        module,
        "_runtime_versions",
        lambda: {"python": "test"},
    )
    monkeypatch.setattr(
        module,
        "_git_state",
        lambda root: {"available": False, "head": None, "dirty": None},
    )
    monkeypatch.setattr(module, "PickInteractionTransformer", GuardedTransformer)
    monkeypatch.setattr(
        module,
        "select_interaction_candidate",
        lambda predictions, **kwargs: {
            "selection_scope": ["2025-Q1", "2025-Q2", "2025-Q3"],
            "selection_status": "qualified",
            "selected_candidate_id": "c1_pick_interactions_c0p001",
            "q4_or_locked_test_used": False,
        },
    )

    result = module.run_interaction_experiment(
        CONFIG,
        output_root=tmp_path / "models" / "m4b4",
        repository_root=ROOT,
    )
    repeated = module.run_interaction_experiment(
        CONFIG,
        output_root=tmp_path / "models" / "m4b4",
        repository_root=ROOT,
    )

    assert repeated.build_fingerprint == result.build_fingerprint
    assert transformed_samples
    with duckdb.connect() as connection:
        predictions = connection.execute(
            "SELECT * FROM read_parquet(?)",
            [str(result.predictions_path)],
        ).fetchdf()
    assert len(predictions) == 28
    assert predictions["candidate_id"].nunique() == 2
    assert set(predictions["evaluation_id"]) == {
        "2024-Q1",
        "2024-Q2",
        "2024-Q3",
        "2024-Q4",
        "2025-Q1",
        "2025-Q2",
        "2025-Q3",
    }
    assert not predictions["sample_id"].str.contains(
        "calibration|locked",
        regex=True,
    ).any()

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["result"]["evaluation_records"] == 14
    assert manifest["result"]["calibration_transform_rows"] == 0
    assert manifest["result"]["calibration_prediction_rows"] == 0
    assert manifest["result"]["locked_test_transform_rows"] == 0
    assert manifest["result"]["locked_test_prediction_rows"] == 0
    assert manifest["result"]["authenticated_api_requests"] == 0
    assert manifest["result"]["model_serialization_performed"] is False
    assert len(manifest["artifacts"]) == 7

    result.selection_path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(
        module.InteractionExperimentError,
        match="artifact changed: selection",
    ):
        module.run_interaction_experiment(
            CONFIG,
            output_root=tmp_path / "models" / "m4b4",
            repository_root=ROOT,
        )
