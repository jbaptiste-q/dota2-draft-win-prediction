"""Offline integration tests for the bounded M8 embedding experiment runner."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from types import SimpleNamespace

import duckdb
import numpy as np
import pandas as pd
import pytest

from src.draft_ai_modeling.embedding_config import (
    EmbeddingConfigError,
    load_embedding_experiment_config,
)
from src.draft_ai_modeling.embedding_experiment import EmbeddingExperimentError
from src.draft_ai_modeling.embeddings import (
    DraftEmbeddingError,
    draft_index_arrays,
    fit_draft_embedding_model,
    fit_hero_vocabulary,
    predict_draft_probabilities,
)
from src.draft_ai_modeling.loader import LoadedWorkingCorpus
from src.draft_ai_modeling.splits import SplitManifestResult
from src.draft_training_dataset.schema import TRAINING_COLUMNS


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "modeling" / "m8_embeddings.json"


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


class TestHeroVocabulary:
    def test_vocabulary_is_sorted_and_reserves_unknown(self) -> None:
        frame = _synthetic_frame().head(4)
        vocabulary = fit_hero_vocabulary(frame)

        assert list(vocabulary.heroes) == sorted(set(vocabulary.heroes))
        assert vocabulary.unknown_index == len(vocabulary.heroes)
        assert vocabulary.hero_count == len(vocabulary.heroes) + 1
        assert len(vocabulary.fingerprint) == 64
        assert fit_hero_vocabulary(frame).fingerprint == (
            vocabulary.fingerprint
        )

    def test_unseen_heroes_map_to_the_unknown_index(self) -> None:
        frame = _synthetic_frame()
        training = frame.head(6)
        later = frame.tail(2)
        vocabulary = fit_hero_vocabulary(training)

        seen = draft_index_arrays(
            vocabulary,
            training,
            context="training rows",
        )
        unseen = draft_index_arrays(
            vocabulary,
            later,
            context="later rows",
        )

        assert seen.unknown_activations == 0
        assert unseen.unknown_activations == 4
        assert (unseen.radiant == vocabulary.unknown_index).sum() == 2
        assert (unseen.dire == vocabulary.unknown_index).sum() == 2

    def test_unknown_heroes_contribute_zero_log_odds(self) -> None:
        frame = _synthetic_frame()
        training = frame[
            frame["match_start_utc"] < pd.Timestamp("2024-01-01", tz="UTC")
        ]
        vocabulary = fit_hero_vocabulary(training)
        indices = draft_index_arrays(
            vocabulary,
            training,
            context="training rows",
        )
        targets = training["radiant_win"].astype("int8").to_numpy(
            dtype=np.float64
        )
        result = fit_draft_embedding_model(
            vocabulary,
            indices,
            targets,
            embedding_dim=2,
            l2=0.1,
            learning_rate=0.05,
            max_iterations=200,
            gradient_tolerance=1e-6,
            seed=42,
            init_scale=0.1,
        )

        unknown = vocabulary.unknown_index
        assert result.parameters.main_effects[unknown] == 0.0
        assert (result.parameters.embeddings[unknown] == 0.0).all()

        base = training.head(1)
        known = draft_index_arrays(vocabulary, base, context="known")
        with_unknown = draft_index_arrays(
            vocabulary,
            base.assign(
                radiant_pick_slot_2="never-seen-hero-a",
                radiant_pick_slot_3="never-seen-hero-b",
            ),
            context="unknown",
        )
        assert with_unknown.unknown_activations == 2

        full = predict_draft_probabilities(
            result.parameters,
            vocabulary,
            known,
        )
        replaced = predict_draft_probabilities(
            result.parameters,
            vocabulary,
            with_unknown,
        )
        removed_positions = known.radiant[0, 1:3]
        removed_main = result.parameters.main_effects[
            removed_positions
        ].sum()
        assert np.isfinite(replaced).all()
        assert replaced[0] != full[0]
        assert removed_main != 0.0

    def test_training_rows_with_unknowns_are_rejected(self) -> None:
        frame = _synthetic_frame()
        vocabulary = fit_hero_vocabulary(frame.head(4))
        indices = draft_index_arrays(
            vocabulary,
            frame.tail(2),
            context="later rows",
        )
        assert indices.unknown_activations > 0
        with pytest.raises(DraftEmbeddingError, match="unknown hero index"):
            fit_draft_embedding_model(
                vocabulary,
                indices,
                np.zeros(2),
                embedding_dim=2,
                l2=0.1,
                learning_rate=0.05,
                max_iterations=10,
                gradient_tolerance=1e-6,
                seed=42,
                init_scale=0.1,
            )


def test_reserved_targets_are_masked_before_window_selection() -> None:
    from src.draft_ai_modeling.embedding_experiment import (
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


def test_window_rows_rejects_a_fold_that_reads_a_reserved_role() -> None:
    from src.draft_ai_modeling.embedding_experiment import (
        _joined_development_frame,
        _window_rows,
    )

    config = load_embedding_experiment_config(
        CONFIG,
        repository_root=ROOT,
        verify_local_artifacts=False,
    )
    frame = _synthetic_frame()
    joined = _joined_development_frame(frame, _split(frame).manifest)
    unsafe_fold = SimpleNamespace(
        fold_id="unsafe",
        train_start_utc=pd.Timestamp("2022-01-01", tz="UTC"),
        train_end_utc=pd.Timestamp("2025-07-01", tz="UTC"),
        evaluation_start_utc=pd.Timestamp("2025-10-01", tz="UTC"),
        evaluation_end_utc=pd.Timestamp("2026-01-01", tz="UTC"),
    )

    with pytest.raises(EmbeddingConfigError, match="prohibited"):
        _window_rows(joined, unsafe_fold, config)


def test_window_rows_rejects_a_fold_that_crosses_source_matches() -> None:
    from src.draft_ai_modeling.embedding_experiment import (
        _joined_development_frame,
        _window_rows,
    )

    config = load_embedding_experiment_config(
        CONFIG,
        repository_root=ROOT,
        verify_local_artifacts=False,
    )
    frame = _synthetic_frame()
    joined = _joined_development_frame(frame, _split(frame).manifest)
    overlapping_fold = SimpleNamespace(
        fold_id="overlapping",
        train_start_utc=pd.Timestamp("2022-01-01", tz="UTC"),
        train_end_utc=pd.Timestamp("2024-03-01", tz="UTC"),
        evaluation_start_utc=pd.Timestamp("2024-01-01", tz="UTC"),
        evaluation_end_utc=pd.Timestamp("2024-06-01", tz="UTC"),
    )

    with pytest.raises(EmbeddingExperimentError, match="crosses"):
        _window_rows(joined, overlapping_fold, config)


def test_synthetic_runner_never_predicts_reserved_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.draft_ai_modeling import embedding_experiment as module

    config = load_embedding_experiment_config(
        CONFIG,
        repository_root=ROOT,
        verify_local_artifacts=False,
    )
    config = dataclasses.replace(
        config,
        estimator=dataclasses.replace(
            config.estimator,
            max_iterations=150,
        ),
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
        "load_embedding_experiment_config",
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
            "m4b2": {
                "build_fingerprint": config.m4b2.build.build_fingerprint
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
        "_verify_frozen_b1_reproduction",
        lambda *args: {
            "candidate_id": "b1_full_uniform_c0p01",
            "rows": 14,
            "maximum_absolute_probability_difference": 0.0,
            "maximum_absolute_b0_difference": 0.0,
            "tolerance": 0.0,
            "passed": True,
            "parent_predictions_sha256": "a" * 64,
        },
    )

    result = module.run_embedding_experiment(
        config.config_path,
        output_root=tmp_path / "models" / "m8",
        repository_root=ROOT,
    )
    repeated = module.run_embedding_experiment(
        config.config_path,
        output_root=tmp_path / "models" / "m8",
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
    assert len(manifest["artifacts"]) == 6

    audits = json.loads(
        result.vocabulary_audits_path.read_text(encoding="utf-8")
    )
    assert len(audits["evaluations"]) == 63
    assert all(
        record["training_unknown_activations"] == 0
        for record in audits["evaluations"]
    )
    assert all(
        record["evaluation_unknown_activations"] == 4
        for record in audits["evaluations"]
    )

    selection = json.loads(result.selection_path.read_text(encoding="utf-8"))
    assert selection["audit"]["candidate_count"] == 9
    assert selection["not_a_final_champion"] is True
    assert selection["calibration_or_locked_test_used"] is False
