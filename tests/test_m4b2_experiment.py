"""Offline integration tests for the bounded M4B.2 experiment runner."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pandas as pd
import pytest

from src.draft_ai_modeling.baselines import (
    BaselineId,
    baseline_contract_payload,
    baseline_fingerprint,
)
from src.draft_ai_modeling.loader import LoadedWorkingCorpus
from src.draft_ai_modeling.recency import RecencyPolicy
from src.draft_ai_modeling.recency_config import (
    load_recency_experiment_config,
)
from src.draft_ai_modeling.splits import SplitManifestResult
from src.draft_training_dataset.schema import TRAINING_COLUMNS


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "modeling" / "m4b2_recency.json"


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
    periods = (
        ("2022q1", "2022-02-01T00:00:00Z"),
        ("2022q2", "2022-05-01T00:00:00Z"),
        ("2022q3", "2022-08-01T00:00:00Z"),
        ("2022q4", "2022-11-01T00:00:00Z"),
        ("2023q1", "2023-02-01T00:00:00Z"),
        ("2023q2", "2023-05-01T00:00:00Z"),
        ("2023q3", "2023-08-01T00:00:00Z"),
        ("2023q4", "2023-11-01T00:00:00Z"),
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


def _split(frame: pd.DataFrame) -> SplitManifestResult:
    manifest = pd.DataFrame(
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
    return SplitManifestResult(
        manifest=manifest,
        fingerprint="e" * 64,
        report={},
    )


def test_reserved_targets_are_masked_before_window_selection() -> None:
    from src.draft_ai_modeling.recency_experiment import (
        _joined_development_frame,
    )

    frame = _synthetic_frame()
    joined = _joined_development_frame(frame, _split(frame).manifest)

    assert joined.loc[
        joined["split_role"].isin({"calibration", "locked_test"}),
        "radiant_win",
    ].isna().all()
    assert joined.loc[
        joined["split_role"].isin({"train", "tuning"}),
        "radiant_win",
    ].notna().all()


def test_exponential_fit_receives_weights_but_uniform_fit_does_not() -> None:
    from src.draft_ai_modeling.recency_experiment import _fit_estimator

    class RecordingEstimator:
        def __init__(self) -> None:
            self.kwargs: dict[str, object] | None = None

        def fit(
            self,
            matrix: object,
            targets: object,
            **kwargs: object,
        ) -> "RecordingEstimator":
            del matrix, targets
            self.kwargs = kwargs
            return self

    weights = pd.Series([0.5, 1.5]).to_numpy()
    exponential = RecordingEstimator()
    _fit_estimator(
        exponential,
        SimpleNamespace(),
        pd.Series([0, 1]).to_numpy(),
        policy=RecencyPolicy.FULL_EXP180,
        sample_weights=weights,
    )
    assert exponential.kwargs is not None
    assert exponential.kwargs["sample_weight"] is weights

    uniform = RecordingEstimator()
    _fit_estimator(
        uniform,
        SimpleNamespace(),
        pd.Series([0, 1]).to_numpy(),
        policy=RecencyPolicy.FULL_UNIFORM,
        sample_weights=weights,
    )
    assert uniform.kwargs == {}


def test_candidate_factory_does_not_mutate_canonical_b1_contract() -> None:
    from src.draft_ai_modeling.recency_experiment import _estimator

    config = load_recency_experiment_config(
        CONFIG,
        repository_root=ROOT,
        verify_local_artifacts=False,
    )
    before_payload = baseline_contract_payload(
        BaselineId.B1_PICK_PRESENCE
    )
    before_fingerprint = baseline_fingerprint(
        BaselineId.B1_PICK_PRESENCE
    )

    estimator = _estimator(config, config.candidates[0])

    assert estimator.C == 0.01
    assert baseline_contract_payload(
        BaselineId.B1_PICK_PRESENCE
    ) == before_payload
    assert baseline_fingerprint(
        BaselineId.B1_PICK_PRESENCE
    ) == before_fingerprint


def test_synthetic_runner_never_predicts_reserved_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.draft_ai_modeling import recency_experiment as module

    config = load_recency_experiment_config(
        CONFIG,
        repository_root=ROOT,
        verify_local_artifacts=False,
    )
    config.selection_policy["paired_group_bootstrap"]["replicates"] = 5
    frame = _synthetic_frame()
    split = _split(frame)
    corpus = LoadedWorkingCorpus(
        config=SimpleNamespace(corpus_id=config.corpus_id),
        frame=frame,
        verified_component_ids=("synthetic",),
    )
    monkeypatch.setattr(
        module,
        "load_recency_experiment_config",
        lambda *args, **kwargs: config,
    )
    monkeypatch.setattr(module, "load_working_corpus", lambda *args: corpus)
    monkeypatch.setattr(
        module,
        "build_split_manifest",
        lambda *args: split,
    )
    monkeypatch.setattr(
        module,
        "_source_lineage",
        lambda *args, **kwargs: {
            "corpus_id": config.corpus_id,
            "corpus_config_path": "configs/modeling/m4a_working_corpus.json",
            "corpus_config_sha256": config.corpus_config_sha256,
            "split_manifest_fingerprint": split.fingerprint,
            "m4a": {"build_fingerprint": config.m4a.build_fingerprint},
            "m4b1": {
                "build_fingerprint": config.m4b1.build.build_fingerprint
            },
        },
    )
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
        "_verify_m4b1_reproduction",
        lambda *args: {
            "candidate_id": "b1_full_uniform_c1",
            "rows": 14,
            "maximum_absolute_probability_difference": 0.0,
            "tolerance": 1e-12,
            "passed": True,
            "parent_predictions_sha256": "a" * 64,
        },
    )

    result = module.run_recency_experiment(
        config.config_path,
        output_root=tmp_path / "models" / "m4b2",
        repository_root=ROOT,
    )
    repeated = module.run_recency_experiment(
        config.config_path,
        output_root=tmp_path / "models" / "m4b2",
        repository_root=ROOT,
    )

    assert repeated.build_fingerprint == result.build_fingerprint
    with duckdb.connect() as connection:
        predictions = connection.execute(
            "SELECT * FROM read_parquet(?)",
            [str(result.predictions_path)],
        ).fetchdf()
    assert len(predictions) == 126
    assert predictions["candidate_id"].nunique() == 9
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
    assert manifest["result"]["evaluation_records"] == 63
    assert manifest["result"]["calibration_prediction_rows"] == 0
    assert manifest["result"]["locked_test_prediction_rows"] == 0
    assert manifest["result"]["authenticated_api_requests"] == 0
    assert manifest["result"]["model_serialization_performed"] is False
    assert len(manifest["artifacts"]) == 8
