"""Offline integration tests for the Milestone 4A preparation gate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.draft_ai_modeling.loader import load_corpus_config, sha256_file
from src.draft_ai_modeling.preparation import (
    build_baseline_declarations,
    prepare_modeling_infrastructure,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
REAL_CONFIG = (
    REPOSITORY_ROOT
    / "configs"
    / "modeling"
    / "m4a_working_corpus.json"
)


def _real_components_available() -> bool:
    config = load_corpus_config(REAL_CONFIG)
    return all(
        component.manifest_path.is_file()
        and component.training_path.is_file()
        for component in config.components
    )


def test_baseline_declarations_are_unfitted_and_complete() -> None:
    declarations = build_baseline_declarations()

    assert [item["baseline_id"] for item in declarations] == [
        "B0",
        "B1",
        "B2",
        "B3",
    ]
    assert all(item["fitted"] is False for item in declarations)
    assert len(
        {item["baseline_fingerprint"] for item in declarations}
    ) == 4


@pytest.mark.skipif(
    not _real_components_available(),
    reason="Ignored local supervised builds are unavailable in CI.",
)
def test_real_working_corpus_preparation_is_content_addressed(
    tmp_path: Path,
) -> None:
    first = prepare_modeling_infrastructure(
        REAL_CONFIG,
        output_root=tmp_path / "models",
    )
    second = prepare_modeling_infrastructure(
        REAL_CONFIG,
        output_root=tmp_path / "models",
    )

    assert first.build_fingerprint == second.build_fingerprint
    assert first.output_directory == second.output_directory
    manifest = json.loads(
        first.manifest_path.read_text(encoding="utf-8")
    )
    assert manifest["source"]["rows"] == 23_123
    assert manifest["split"]["split_manifest_fingerprint"] == (
        "dcb1227db92e585d3faab3a435a02aac2e9cb81da44d79bbcf3d7c353cc06fd1"
    )
    assert manifest["safety"]["estimator_fit_performed"] is False
    assert manifest["safety"]["api_dependency"] is False
    for artifact in manifest["artifacts"].values():
        path = first.output_directory / artifact["file"]
        assert sha256_file(path) == artifact["sha256"]
