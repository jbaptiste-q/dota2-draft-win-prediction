"""End-to-end safeguards for the local offline M4B.3 calibration gate."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from src.draft_ai_modeling.calibration_config import (
    load_calibration_experiment_config,
)
from src.draft_ai_modeling.calibration_experiment import (
    _masked_modeling_rows,
    run_calibration_experiment,
)
from src.draft_ai_modeling.loader import sha256_file


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "modeling" / "m4b3_calibration.json"


def test_locked_targets_are_masked_before_modeling_role_selection() -> None:
    config = load_calibration_experiment_config(
        CONFIG,
        repository_root=ROOT,
        verify_local_artifacts=False,
    )
    config = replace(
        config,
        expected_counts={
            "base_fit_rows": 2,
            "base_fit_source_matches": 2,
            "calibration_rows": 2,
            "calibration_source_matches": 2,
            "calibration_positive_rows": 1,
            "calibration_negative_rows": 1,
            "locked_test_rows": 2,
        },
    )
    corpus = pd.DataFrame(
        {
            "sample_id": [f"sample-{index}" for index in range(6)],
            "source_match_id": [f"match-{index}" for index in range(6)],
            "radiant_win": [0, 1, 0, 1, "poison", "poison"],
        }
    )
    split = pd.DataFrame(
        {
            "sample_id": corpus["sample_id"],
            "split_role": [
                "train",
                "tuning",
                "calibration",
                "calibration",
                "locked_test",
                "locked_test",
            ],
        }
    )

    base, calibration, audit = _masked_modeling_rows(
        corpus,
        split,
        config,
    )

    assert set(base["split_role"]) == {"train", "tuning"}
    assert set(calibration["split_role"]) == {"calibration"}
    assert "poison" not in base["radiant_win"].tolist()
    assert "poison" not in calibration["radiant_win"].tolist()
    assert audit["locked_test_targets_masked_before_role_selection"] is True
    assert audit["locked_test_transform_rows"] == 0
    assert audit["locked_test_prediction_rows"] == 0


def test_local_calibration_run_is_content_addressed_and_test_sealed(
    tmp_path: Path,
) -> None:
    payload = json.loads(CONFIG.read_text(encoding="utf-8"))
    required = (
        ROOT / payload["source"]["m4b2"]["manifest_path"],
        ROOT / payload["source"]["m4a"]["split_manifest_path"],
    )
    if not all(path.is_file() for path in required):
        pytest.skip("Ignored local M4A/M4B.2 artifacts are unavailable.")

    first = run_calibration_experiment(
        CONFIG,
        output_root=tmp_path / "m4b3",
        repository_root=ROOT,
    )
    second = run_calibration_experiment(
        CONFIG,
        output_root=tmp_path / "m4b3",
        repository_root=ROOT,
    )

    assert first.build_fingerprint == second.build_fingerprint
    assert first.output_directory == second.output_directory
    manifest = json.loads(first.manifest_path.read_text(encoding="utf-8"))
    result = manifest["result"]
    assert result["base_fit_rows"] == 20_087
    assert result["calibration_rows"] == 1_089
    assert result["calibration_prediction_rows_per_method"] == 1_089
    assert result["locked_test_target_rows_used_for_modeling"] == 0
    assert result["locked_test_transform_rows"] == 0
    assert result["locked_test_prediction_rows"] == 0
    assert result["authenticated_api_requests"] == 0
    assert manifest["frozen_candidate_reproduction"]["passed"] is True
    assert manifest["bundle_validation"]["passed"] is True
    assert manifest["cross_fit_audit"]["group_crossings"] == 0
    assert manifest["cross_fit_audit"]["prediction_rows"] == 3 * 1_089
    for artifact in manifest["artifacts"].values():
        path = first.output_directory / artifact["file"]
        assert path.is_file()
        assert sha256_file(path) == artifact["sha256"]

    with duckdb.connect() as connection:
        prediction_rows = connection.execute(
            "SELECT count(*) FROM read_parquet(?)",
            [str(first.predictions_path)],
        ).fetchone()[0]
        locked_overlap = connection.execute(
            "SELECT count(*) FROM read_parquet(?) p "
            "JOIN read_parquet(?) s USING (sample_id) "
            "WHERE s.split_role = 'locked_test'",
            [
                str(first.predictions_path),
                str(ROOT / payload["source"]["m4a"]["split_manifest_path"]),
            ],
        ).fetchone()[0]
    assert prediction_rows == 3 * 1_089
    assert locked_overlap == 0
