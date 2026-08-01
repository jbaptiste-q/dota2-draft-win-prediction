"""Synthetic, offline tests for development-only M4B.1 orchestration."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pandas as pd
import pytest

from src.draft_ai_modeling.baselines import BaselineId
from src.draft_ai_modeling.contracts import (
    SPLIT_ROLE_CALIBRATION,
    SPLIT_ROLE_LOCKED_TEST,
    SPLIT_ROLE_TRAIN,
    SPLIT_ROLE_TUNING,
)
from src.draft_ai_modeling.experiment_config import (
    BaselineExperimentConfig,
    EvaluationPolicy,
    RollingOriginFold,
)
from src.draft_ai_modeling.loader import LoadedWorkingCorpus
from src.draft_ai_modeling.splits import SplitManifestResult
from src.draft_training_dataset.schema import TRAINING_COLUMNS


def utc(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=UTC)


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
    for side in ("radiant", "dire"):
        for slot in range(1, 6):
            row[f"{side}_pick_slot_{slot}"] = (
                f"{side}-pick-{slot}"
                if slot != 1
                else f"{row_id}-{side}-pick-{slot}"
            )
        for slot in range(1, 8):
            row[f"{side}_ban_slot_{slot}"] = f"{side}-ban-{slot}"
    return row


def _synthetic_frame() -> pd.DataFrame:
    periods = [
        ("seed-a", "2022-02-01T00:00:00Z"),
        ("seed-b", "2022-05-01T00:00:00Z"),
        ("seed-c", "2023-02-01T00:00:00Z"),
        ("seed-d", "2023-05-01T00:00:00Z"),
        ("2024q1", "2024-02-01T00:00:00Z"),
        ("2024q2", "2024-05-01T00:00:00Z"),
        ("2024q3", "2024-08-01T00:00:00Z"),
        ("2024q4", "2024-11-01T00:00:00Z"),
        ("2025q1", "2025-02-01T00:00:00Z"),
        ("2025q2", "2025-05-01T00:00:00Z"),
        ("2025q3", "2025-08-01T00:00:00Z"),
        ("calibration", "2025-11-01T00:00:00Z"),
        ("locked", "2026-02-01T00:00:00Z"),
    ]
    rows: list[dict[str, object]] = []
    for prefix, timestamp in periods:
        rows.extend(
            [
                _row(f"{prefix}-win", timestamp, radiant_win=True),
                _row(f"{prefix}-loss", timestamp, radiant_win=False),
            ]
        )
    frame = pd.DataFrame(rows, columns=TRAINING_COLUMNS)
    frame["match_start_utc"] = pd.to_datetime(frame["match_start_utc"], utc=True)
    frame["radiant_win"] = frame["radiant_win"].astype("boolean")
    return frame


def _role(timestamp: pd.Timestamp) -> tuple[str, str, str]:
    if timestamp < pd.Timestamp("2025-07-01", tz="UTC"):
        return "train", SPLIT_ROLE_TRAIN, "train"
    if timestamp < pd.Timestamp("2025-10-01", tz="UTC"):
        return "validation", SPLIT_ROLE_TUNING, "validation_tuning"
    if timestamp < pd.Timestamp("2026-01-01", tz="UTC"):
        return (
            "validation",
            SPLIT_ROLE_CALIBRATION,
            "validation_calibration",
        )
    return "test", SPLIT_ROLE_LOCKED_TEST, "locked_test"


def _split(frame: pd.DataFrame, fingerprint: str) -> SplitManifestResult:
    records = []
    for row in frame.to_dict(orient="records"):
        primary, role, interval = _role(row["match_start_utc"])
        records.append(
            {
                "sample_id": row["sample_id"],
                "source_match_id": row["source_match_id"],
                "match_start_utc": row["match_start_utc"],
                "primary_split": primary,
                "split_role": role,
                "split_interval_id": interval,
            }
        )
    return SplitManifestResult(
        manifest=pd.DataFrame(records),
        fingerprint=fingerprint,
        report={},
    )


def _folds() -> tuple[RollingOriginFold, ...]:
    boundaries = (
        utc(2024, 1, 1),
        utc(2024, 4, 1),
        utc(2024, 7, 1),
        utc(2024, 10, 1),
        utc(2025, 1, 1),
        utc(2025, 4, 1),
        utc(2025, 7, 1),
        utc(2025, 10, 1),
    )
    return tuple(
        RollingOriginFold(
            fold_id=f"{start.year}-Q{((start.month - 1) // 3) + 1}",
            train_start_utc=utc(2022, 1, 1),
            train_end_utc=start,
            evaluation_start_utc=start,
            evaluation_end_utc=end,
        )
        for start, end in zip(boundaries, boundaries[1:], strict=False)
    )


def _selection_policy() -> dict[str, object]:
    return {
        "practical_log_loss_tie": 0.002,
        "maximum_single_fold_log_loss_regression_vs_b0": 0.01,
        "require_tuning_brier_improvement_vs_b0": True,
        "require_mean_rolling_brier_improvement_vs_b0": True,
        "complexity_order": ["B1", "B2", "B3"],
        "result_label": "baseline_candidate_not_final_champion",
    }


def _config(root: Path, split_fingerprint: str) -> BaselineExperimentConfig:
    config_path = root / "configs" / "modeling" / "m4b.json"
    corpus_path = root / "configs" / "modeling" / "corpus.json"
    manifest_path = root / "models" / "m4a" / "manifest.json"
    for path in (config_path, corpus_path, manifest_path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
    return BaselineExperimentConfig(
        config_path=config_path,
        repository_root=root,
        experiment_id="m4b1-b0-b3-temporal-baselines-v1",
        corpus_config_path=corpus_path,
        corpus_config_sha256="a" * 64,
        corpus_id="synthetic-corpus",
        m4a_build_fingerprint="b" * 64,
        m4a_manifest_path=manifest_path,
        m4a_manifest_sha256="c" * 64,
        split_manifest_fingerprint=split_fingerprint,
        baseline_ids=tuple(BaselineId),
        fit_role=SPLIT_ROLE_TRAIN,
        selection_role=SPLIT_ROLE_TUNING,
        prohibited_roles=frozenset(
            {SPLIT_ROLE_CALIBRATION, SPLIT_ROLE_LOCKED_TEST}
        ),
        rolling_origin_folds=_folds(),
        evaluation=EvaluationPolicy(
            primary_metric="log_loss",
            metrics=("log_loss", "brier_score"),
            reliability_bins=4,
            bootstrap_replicates=5,
            bootstrap_confidence_level=0.95,
            bootstrap_group_column="source_match_id",
            random_seed=42,
            coefficient_top_k=3,
        ),
        selection_policy=_selection_policy(),
        safety={},
        fingerprint="d" * 64,
    )


def _read_parquet(path: Path) -> pd.DataFrame:
    with duckdb.connect() as connection:
        return connection.execute(
            "SELECT * FROM read_parquet(?)",
            [str(path)],
        ).fetchdf()


def test_runner_fits_all_baselines_without_touching_reserved_labels(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.draft_ai_modeling import baseline_experiment as module

    frame = _synthetic_frame()
    split_fingerprint = "e" * 64
    split = _split(frame, split_fingerprint)
    config = _config(tmp_path, split_fingerprint)
    corpus = LoadedWorkingCorpus(
        config=SimpleNamespace(corpus_id="synthetic-corpus"),
        frame=frame,
        verified_component_ids=("synthetic",),
    )
    fit_sizes: list[int] = []
    real_transformer = module.DraftFeatureTransformer

    class RecordingTransformer(real_transformer):
        def fit(
            self,
            training_frame: pd.DataFrame,
            y: object = None,
        ) -> "RecordingTransformer":
            fit_sizes.append(len(training_frame))
            return super().fit(training_frame, y)

    monkeypatch.setattr(module, "load_experiment_config", lambda *a, **k: config)
    monkeypatch.setattr(module, "load_working_corpus", lambda *a, **k: corpus)
    monkeypatch.setattr(module, "build_split_manifest", lambda *a, **k: split)
    monkeypatch.setattr(module, "DraftFeatureTransformer", RecordingTransformer)
    monkeypatch.setattr(module, "_source_sha256", lambda: "f" * 64)
    monkeypatch.setattr(
        module,
        "_git_state",
        lambda root: {"available": False, "head": None, "dirty": None},
    )
    monkeypatch.setattr(
        module,
        "_runtime_versions",
        lambda: {"python": "test"},
    )
    monkeypatch.setattr(
        module,
        "_verify_m4a_pins",
        lambda *a, **k: {
            "build_fingerprint": "b" * 64,
            "manifest_path": "models/m4a/manifest.json",
            "manifest_sha256": "c" * 64,
            "split_manifest_fingerprint": split_fingerprint,
            "corpus_config_sha256": "a" * 64,
        },
    )

    result = module.run_baseline_experiment(
        config.config_path,
        output_root=tmp_path / "models" / "m4b",
        repository_root=tmp_path,
    )
    repeated = module.run_baseline_experiment(
        config.config_path,
        output_root=tmp_path / "models" / "m4b",
        repository_root=tmp_path,
    )

    assert repeated.build_fingerprint == result.build_fingerprint
    assert len(fit_sizes) == 24
    tuning = _read_parquet(result.tuning_predictions_path)
    rolling = _read_parquet(result.rolling_predictions_path)
    assert len(tuning) == 8
    assert len(rolling) == 56
    assert set(tuning["baseline_id"]) == {"B0", "B1", "B2", "B3"}
    assert not any(
        marker in sample_id
        for sample_id in [*tuning["sample_id"], *rolling["sample_id"]]
        for marker in ("calibration", "locked")
    )
    assert set(rolling["evaluation_id"]) == {
        "2024-Q1",
        "2024-Q2",
        "2024-Q3",
        "2024-Q4",
        "2025-Q1",
        "2025-Q2",
        "2025-Q3",
    }

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["result"]["calibration_prediction_rows"] == 0
    assert manifest["result"]["locked_test_prediction_rows"] == 0
    assert manifest["result"]["hyperparameter_search_performed"] is False
    assert manifest["result"]["model_serialization_performed"] is False
    assert len(manifest["artifacts"]) == 8
    comparison = json.loads(
        result.comparison_path.read_text(encoding="utf-8")
    )
    assert comparison["not_a_final_champion"] is True
    assert comparison["calibration_or_locked_test_used"] is False

    explanations = json.loads(
        result.explanations_path.read_text(encoding="utf-8")
    )["evaluations"]
    b1_fingerprints = {
        item["feature_fingerprint"]
        for item in explanations
        if item["baseline_id"] == "B1"
        and item["evaluation_kind"] == "rolling_origin"
    }
    assert len(b1_fingerprints) == 7


def test_reserved_future_window_is_rejected_before_fitting() -> None:
    from src.draft_ai_modeling.baseline_experiment import (
        BaselineExperimentError,
        _joined_development_frame,
        _window_from_config,
    )

    with pytest.raises(BaselineExperimentError, match="reserved future role"):
        _window_from_config(
            RollingOriginFold(
                fold_id="unsafe",
                train_start_utc=utc(2022, 1, 1),
                train_end_utc=utc(2025, 10, 1),
                evaluation_start_utc=utc(2025, 10, 1),
                evaluation_end_utc=utc(2026, 1, 1),
            )
        )

    frame = _synthetic_frame()
    joined = _joined_development_frame(frame, _split(frame, "e" * 64).manifest)
    assert joined.loc[
        joined["split_role"].isin(
            {SPLIT_ROLE_CALIBRATION, SPLIT_ROLE_LOCKED_TEST}
        ),
        "radiant_win",
    ].isna().all()


def test_development_selection_prefers_simpler_model_within_tie() -> None:
    from src.draft_ai_modeling.baseline_experiment import (
        compare_development_baselines,
    )

    evaluations: list[dict[str, object]] = []
    tuning_values = {
        "B0": (0.700, 0.250),
        "B1": (0.680, 0.240),
        "B2": (0.679, 0.239),
        "B3": (0.6785, 0.238),
    }
    for baseline_id, (log_loss, brier) in tuning_values.items():
        evaluations.append(
            {
                "evaluation_id": "tuning",
                "evaluation_kind": "tuning",
                "baseline_id": baseline_id,
                "metrics": {
                    "log_loss": log_loss,
                    "brier_score": brier,
                },
            }
        )
        for quarter in range(1, 8):
            evaluations.append(
                {
                    "evaluation_id": f"fold-{quarter}",
                    "evaluation_kind": "rolling_origin",
                    "baseline_id": baseline_id,
                    "metrics": {
                        "log_loss": log_loss + 0.001,
                        "brier_score": brier + 0.001,
                    },
                }
            )

    comparison = compare_development_baselines(
        evaluations,
        _selection_policy(),
    )

    assert comparison["selected_baseline_id"] == "B1"
    assert comparison["not_a_final_champion"] is True
