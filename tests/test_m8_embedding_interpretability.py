"""Offline tests for the M8 Phase 4 interpretability exports."""

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
    load_embedding_experiment_config,
)
from src.draft_ai_modeling.embedding_interpretability import (
    EmbeddingInterpretabilityError,
    load_hero_display_names,
    run_embedding_interpretability,
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


def test_hero_display_name_catalog_loads_and_falls_back() -> None:
    from src.draft_ai_modeling.embedding_interpretability import (
        _source_name,
    )

    names = load_hero_display_names()
    assert names["anti-mage"] == "Anti-Mage"
    assert len(names) > 100
    assert _source_name("anti-mage", names) == "Anti-Mage"
    assert _source_name("never-seen-hero", names) == "never-seen-hero"


def test_choose_descriptive_l2_escapes_collapse_and_documents_sweep() -> None:
    from src.draft_ai_modeling.embedding_interpretability import (
        _choose_descriptive_l2,
    )
    from src.draft_ai_modeling.embedding_config import (
        load_embedding_experiment_config,
    )
    from src.draft_ai_modeling.embeddings import (
        draft_index_arrays,
        fit_hero_vocabulary,
    )

    config = load_embedding_experiment_config(
        CONFIG,
        repository_root=ROOT,
        verify_local_artifacts=False,
    )
    rng = np.random.default_rng(0)
    hero_count = 16
    games = 400
    picks = np.empty((games, 10), dtype=np.int64)
    for row in range(games):
        picks[row] = rng.permutation(hero_count)[:10]
    training = pd.DataFrame(
        {
            f"radiant_pick_slot_{i}": [
                f"hero-{value}" for value in picks[:, i - 1]
            ]
            for i in range(1, 6)
        }
        | {
            f"dire_pick_slot_{i}": [
                f"hero-{value}" for value in picks[:, 4 + i]
            ]
            for i in range(1, 6)
        }
    )
    vocabulary = fit_hero_vocabulary(training)
    indices = draft_index_arrays(vocabulary, training, context="train")
    targets = (rng.random(400) < 0.5).astype(np.float64)

    chosen_l2, sweep = _choose_descriptive_l2(
        vocabulary,
        indices,
        targets,
        embedding_dim=4,
        config=config,
    )
    assert chosen_l2 in {item["l2"] for item in sweep}
    escaped = [item for item in sweep if item["escaped_collapse"]]
    assert escaped
    assert escaped[0]["l2"] == chosen_l2
    assert all(
        item["l2"] > chosen_l2
        for item in sweep
        if not item["escaped_collapse"]
    )


def test_masked_development_frame_hides_reserved_targets() -> None:
    from src.draft_ai_modeling.embedding_interpretability import (
        _masked_development_frame,
    )

    frame = _synthetic_frame()
    joined = _masked_development_frame(frame, _split(frame).manifest)

    assert joined.loc[
        joined["split_role"].isin({"calibration", "locked_test"}),
        "radiant_win",
    ].isna().all()
    assert joined.loc[
        joined["split_role"].isin({"train", "tuning"}),
        "radiant_win",
    ].notna().all()


def test_fold_window_rejects_reserved_rows() -> None:
    from src.draft_ai_modeling.embedding_interpretability import (
        _fold_window,
        _masked_development_frame,
    )

    frame = _synthetic_frame()
    joined = _masked_development_frame(frame, _split(frame).manifest)
    unsafe_fold = SimpleNamespace(
        fold_id="unsafe",
        train_start_utc=pd.Timestamp("2022-01-01", tz="UTC"),
        train_end_utc=pd.Timestamp("2025-07-01", tz="UTC"),
        evaluation_start_utc=pd.Timestamp("2025-10-01", tz="UTC"),
        evaluation_end_utc=pd.Timestamp("2026-01-01", tz="UTC"),
    )
    with pytest.raises(EmbeddingInterpretabilityError, match="reserved"):
        _fold_window(joined, unsafe_fold)


def test_synthetic_interpretability_export_is_deterministic_and_descriptive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.draft_ai_modeling import embedding_experiment as experiment_module
    from src.draft_ai_modeling import embedding_interpretability as module

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

    for target_module in (experiment_module, module):
        monkeypatch.setattr(
            target_module,
            "load_embedding_experiment_config",
            lambda *args, **kwargs: config,
        )
        monkeypatch.setattr(
            target_module, "load_working_corpus", lambda *args: corpus
        )
        monkeypatch.setattr(
            target_module, "build_split_manifest", lambda *args: split
        )
    monkeypatch.setattr(
        experiment_module,
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
    monkeypatch.setattr(experiment_module, "_source_sha256", lambda: "f" * 64)
    monkeypatch.setattr(
        experiment_module,
        "_git_state",
        lambda root: {"available": False, "head": None, "dirty": None},
    )
    monkeypatch.setattr(
        experiment_module, "_runtime_versions", lambda: {"python": "test"}
    )
    monkeypatch.setattr(
        experiment_module,
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

    result = module.run_embedding_interpretability(
        config.config_path,
        output_root=tmp_path / "models" / "m8",
        repository_root=ROOT,
    )
    repeated = module.run_embedding_interpretability(
        config.config_path,
        output_root=tmp_path / "models" / "m8",
        repository_root=ROOT,
    )
    assert repeated.output_directory == result.output_directory

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["part_a"]["descriptive_only"] is False
    assert manifest["part_b"]["descriptive_only"] is True
    assert manifest["part_b"]["not_used_for_selection"] is True
    assert manifest["part_b"]["not_a_qualifying_candidate"] is True
    assert manifest["safety"]["calibration_prediction_rows"] == 0
    assert manifest["safety"]["locked_test_prediction_rows"] == 0
    assert manifest["safety"]["model_serialization_performed"] is False

    collapse = json.loads(
        result.collapse_analysis_path.read_text(encoding="utf-8")
    )
    assert collapse["descriptive_only"] is False
    assert len(collapse["per_candidate_max_embedding_norms"]) == 9
    assert "identifiability_note" in collapse
    assert "orthogonal rotation" in collapse["identifiability_note"]

    with duckdb.connect() as connection:
        main_effects = connection.execute(
            "SELECT * FROM read_parquet(?)",
            [str(result.hero_main_effects_path)],
        ).fetchdf()
        descriptive_embeddings = connection.execute(
            "SELECT * FROM read_parquet(?)",
            [str(result.descriptive_hero_embeddings_path)],
        ).fetchdf()
        projection = connection.execute(
            "SELECT * FROM read_parquet(?)",
            [str(result.descriptive_hero_projection_2d_path)],
        ).fetchdf()

    assert "descriptive_only" not in main_effects.columns
    assert descriptive_embeddings["descriptive_only"].all()
    assert projection["descriptive_only"].all()
    assert set(main_effects["hero_key"]) == set(
        descriptive_embeddings["hero_key"]
    )

    neighbours = json.loads(
        result.descriptive_hero_neighbours_path.read_text(encoding="utf-8")
    )
    assert neighbours["descriptive_only"] is True
    assert all(
        len(hero["neighbours"]) <= 20 for hero in neighbours["heroes"]
    )

    pairs = json.loads(
        result.descriptive_learned_pairs_path.read_text(encoding="utf-8")
    )
    assert pairs["descriptive_only"] is True
    assert len(pairs["top_synergy_pairs"]) <= 30
    assert len(pairs["top_counter_pairs"]) <= 30
    for entry in pairs["top_synergy_pairs"] + pairs["top_counter_pairs"]:
        assert "same_side_training_games" in entry
        assert "opposing_side_training_games" in entry
