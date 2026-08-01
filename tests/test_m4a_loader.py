"""Offline tests for the verified Milestone 4A working-corpus loader."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from src.draft_ai_modeling.loader import (
    CONFIG_SCHEMA_VERSION,
    CorpusValidationError,
    load_corpus_config,
    load_working_corpus,
    sha256_file,
    verify_working_corpus,
)
from src.draft_training_dataset.builder import write_parquet
from src.draft_training_dataset.schema import (
    SCHEMA_VERSION,
    TRAINING_COLUMNS,
    schema_payload,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
REAL_CONFIG = (
    REPOSITORY_ROOT / "configs" / "modeling" / "m4a_working_corpus.json"
)


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _row(
    match_id: str,
    *,
    game_index: int,
    start_utc: str,
    radiant_win: bool,
    patch: str | None = "7.35",
    series: str | None = "Group Stage",
    radiant_team: str = "team-radiant",
    dire_team: str = "team-dire",
) -> dict[str, object]:
    game_key = f"{match_id}:game:{game_index}"
    row: dict[str, object] = {
        "sample_id": game_key,
        "game_key": game_key,
        "source_game_id": str(game_index),
        "game_index": game_index,
        "source_match_id": match_id,
        "match_start_utc": pd.Timestamp(start_utc),
        "patch": patch,
        "liquipedia_tier": "1",
        "tournament": "Offline Loader Test",
        "series": series,
        "radiant_team_key": radiant_team,
        "dire_team_key": dire_team,
        "radiant_win": radiant_win,
    }
    row.update(
        {
            f"radiant_pick_slot_{slot}": f"radiant-pick-{slot}"
            for slot in range(1, 6)
        }
    )
    row.update(
        {
            f"dire_pick_slot_{slot}": f"dire-pick-{slot}"
            for slot in range(1, 6)
        }
    )
    row.update(
        {
            f"radiant_ban_slot_{slot}": f"radiant-ban-{slot}"
            for slot in range(1, 8)
        }
    )
    row.update(
        {
            f"dire_ban_slot_{slot}": f"dire-ban-{slot}"
            for slot in range(1, 8)
        }
    )
    return row


def _typed_frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=TRAINING_COLUMNS)
    string_columns = [
        column
        for column in TRAINING_COLUMNS
        if column not in {"game_index", "match_start_utc", "radiant_win"}
    ]
    frame[string_columns] = frame[string_columns].astype("string")
    frame["game_index"] = frame["game_index"].astype("Int64")
    frame["match_start_utc"] = pd.to_datetime(
        frame["match_start_utc"],
        utc=True,
    ).astype("datetime64[us, UTC]")
    frame["radiant_win"] = frame["radiant_win"].astype("boolean")
    return frame


def _write_component(
    root: Path,
    *,
    component_id: str,
    start_utc: str,
    end_utc: str,
    rows: list[dict[str, object]],
    excluded_rows: int = 0,
) -> tuple[dict[str, object], pd.DataFrame]:
    directory = root / "artifacts" / component_id
    directory.mkdir(parents=True)
    frame = _typed_frame(rows)
    training_path = directory / "draft_training_games.parquet"
    write_parquet(frame, training_path)

    schema_path = directory / "schema.json"
    schema_path.write_text(
        json.dumps(
            schema_payload(),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    build_fingerprint = _fingerprint(component_id)
    manifest = {
        "artifacts": {
            "draft_training_games": {
                "file": training_path.name,
                "sha256": sha256_file(training_path),
            },
            "schema": {
                "file": schema_path.name,
                "sha256": sha256_file(schema_path),
            },
        },
        "build_fingerprint": build_fingerprint,
        "row_counts": {
            "excluded": excluded_rows,
            "training": len(frame),
        },
        "schema_version": SCHEMA_VERSION,
        "training_columns": list(TRAINING_COLUMNS),
    }
    manifest_path = directory / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    component = {
        "build_fingerprint": build_fingerprint,
        "component_id": component_id,
        "expected": {
            "excluded_rows": excluded_rows,
            "training_rows": len(frame),
        },
        "manifest_path": manifest_path.relative_to(root).as_posix(),
        "manifest_sha256": sha256_file(manifest_path),
        "scope": {
            "end_utc_exclusive": end_utc,
            "start_utc_inclusive": start_utc,
        },
        "training_artifact": {
            "path": training_path.relative_to(root).as_posix(),
            "sha256": sha256_file(training_path),
        },
    }
    frame["__component_id"] = component_id
    return component, frame


def _iso_utc(value: pd.Timestamp) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _write_config(
    root: Path,
    *,
    definitions: list[dict[str, Any]],
    cross_component_expected: int | None = None,
) -> Path:
    components: list[dict[str, object]] = []
    frames: list[pd.DataFrame] = []
    for definition in definitions:
        component, frame = _write_component(root, **definition)
        components.append(component)
        frames.append(frame)
    combined = pd.concat(frames, ignore_index=True)
    grouped = combined.groupby("source_match_id", sort=False)
    cross_component = int(
        grouped["__component_id"].nunique(dropna=False).gt(1).sum()
    )
    multi_patch = int(grouped["patch"].nunique(dropna=True).gt(1).sum())
    side_changes = int(
        grouped["radiant_team_key"].nunique(dropna=False).gt(1).sum()
    )
    null_counts = {
        column: int(combined[column].isna().sum())
        for column in TRAINING_COLUMNS
        if combined[column].isna().any()
    }
    years = {
        str(int(year)): int(count)
        for year, count in (
            combined["match_start_utc"].dt.year.value_counts().items()
        )
    }
    duplicate_source_games = int(
        combined.duplicated(
            ["source_match_id", "source_game_id"],
            keep=False,
        ).sum()
    )
    duplicate_game_indexes = int(
        combined.duplicated(
            ["source_match_id", "game_index"],
            keep=False,
        ).sum()
    )
    payload = {
        "components": components,
        "config_schema_version": CONFIG_SCHEMA_VERSION,
        "corpus_id": "synthetic-working-corpus",
        "expected_aggregate": {
            "excluded_rows": sum(
                int(component["expected"]["excluded_rows"])
                for component in components
            ),
            "grouping": {
                "cross_component_match_groups": (
                    cross_component
                    if cross_component_expected is None
                    else cross_component_expected
                ),
                "multi_patch_match_groups": multi_patch,
                "side_assignment_change_match_groups": side_changes,
            },
            "identity": {
                "duplicate_match_game_index_pairs": duplicate_game_indexes,
                "duplicate_match_source_game_pairs": duplicate_source_games,
                "unique_game_keys": int(combined["game_key"].nunique()),
                "unique_sample_ids": int(combined["sample_id"].nunique()),
            },
            "maximum_match_start_utc": _iso_utc(
                combined["match_start_utc"].max()
            ),
            "minimum_match_start_utc": _iso_utc(
                combined["match_start_utc"].min()
            ),
            "null_counts": null_counts,
            "radiant_win_false": int((~combined["radiant_win"]).sum()),
            "radiant_win_true": int(combined["radiant_win"].sum()),
            "scope": {
                "end_utc_exclusive": definitions[-1]["end_utc"],
                "start_utc_inclusive": definitions[0]["start_utc"],
            },
            "source_match_groups": int(
                combined["source_match_id"].nunique()
            ),
            "training_rows": len(combined),
            "year_row_counts": years,
        },
        "group_column": "source_match_id",
        "sort_columns": [
            "match_start_utc",
            "source_match_id",
            "game_index",
        ],
        "supervised_schema": {
            "columns": list(TRAINING_COLUMNS),
            "schema_sha256": sha256_file(
                root
                / str(components[0]["manifest_path"])
                .removesuffix("manifest.json")
                / "schema.json"
            ),
            "schema_version": SCHEMA_VERSION,
        },
        "target_column": "radiant_win",
    }
    config_path = root / "configs" / "modeling" / "working.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return config_path


def _valid_definitions() -> list[dict[str, Any]]:
    return [
        {
            "component_id": "2024-01",
            "start_utc": "2024-01-01T00:00:00Z",
            "end_utc": "2024-02-01T00:00:00Z",
            "rows": [
                _row(
                    "match-b",
                    game_index=1,
                    start_utc="2024-01-20T12:00:00Z",
                    radiant_win=False,
                ),
                _row(
                    "match-a",
                    game_index=1,
                    start_utc="2024-01-10T12:00:00Z",
                    radiant_win=True,
                ),
            ],
        },
        {
            "component_id": "2024-02",
            "start_utc": "2024-02-01T00:00:00Z",
            "end_utc": "2024-03-01T00:00:00Z",
            "rows": [
                _row(
                    "match-c",
                    game_index=1,
                    start_utc="2024-02-10T12:00:00Z",
                    radiant_win=True,
                    series=None,
                )
            ],
        },
    ]


def test_loader_verifies_types_and_sorts_deterministically(
    tmp_path: Path,
) -> None:
    config_path = _write_config(
        tmp_path,
        definitions=_valid_definitions(),
    )

    loaded = load_working_corpus(
        config_path,
        repository_root=tmp_path,
    )

    assert loaded.frame["source_match_id"].tolist() == [
        "match-a",
        "match-b",
        "match-c",
    ]
    assert str(loaded.frame["match_start_utc"].dtype) == "datetime64[us, UTC]"
    assert str(loaded.frame["game_index"].dtype) == "Int64"
    assert str(loaded.frame["radiant_win"].dtype) == "boolean"
    assert tuple(loaded.frame.columns) == TRAINING_COLUMNS
    assert loaded.verified_component_ids == ("2024-01", "2024-02")


def test_verification_rejects_a_tampered_training_artifact(
    tmp_path: Path,
) -> None:
    config_path = _write_config(
        tmp_path,
        definitions=_valid_definitions(),
    )
    config = load_corpus_config(config_path, repository_root=tmp_path)
    artifact = config.components[0].training_path
    artifact.write_bytes(artifact.read_bytes() + b"tampered")

    with pytest.raises(CorpusValidationError, match="artifact checksum"):
        verify_working_corpus(config)


def test_loader_rejects_a_match_group_crossing_components(
    tmp_path: Path,
) -> None:
    definitions = _valid_definitions()
    definitions[0]["rows"] = [
        _row(
            "shared-match",
            game_index=1,
            start_utc="2024-01-20T12:00:00Z",
            radiant_win=True,
        )
    ]
    definitions[1]["rows"] = [
        _row(
            "shared-match",
            game_index=2,
            start_utc="2024-02-10T12:00:00Z",
            radiant_win=False,
        )
    ]
    config_path = _write_config(
        tmp_path,
        definitions=definitions,
        cross_component_expected=0,
    )

    with pytest.raises(
        CorpusValidationError,
        match="Cross-component match group",
    ):
        load_working_corpus(config_path, repository_root=tmp_path)


def test_config_rejects_non_contiguous_component_scopes(
    tmp_path: Path,
) -> None:
    definitions = _valid_definitions()
    definitions[1]["start_utc"] = "2024-02-02T00:00:00Z"
    config_path = _write_config(tmp_path, definitions=definitions)

    with pytest.raises(
        CorpusValidationError,
        match="ordered contiguous time range",
    ):
        load_corpus_config(config_path, repository_root=tmp_path)


def test_real_working_corpus_integration_when_local_artifacts_exist() -> None:
    raw = json.loads(REAL_CONFIG.read_text(encoding="utf-8"))
    artifact_paths = [
        REPOSITORY_ROOT / component["training_artifact"]["path"]
        for component in raw["components"]
    ]
    if not all(path.is_file() for path in artifact_paths):
        pytest.skip("Ignored local M3.6 supervised builds are unavailable.")

    loaded = load_working_corpus(REAL_CONFIG)

    assert len(loaded.frame) == 23_123
    assert loaded.frame["source_match_id"].nunique() == 11_664
    assert int(loaded.frame["radiant_win"].sum()) == 11_762
    assert loaded.frame["match_start_utc"].max() == pd.Timestamp(
        datetime(2026, 3, 31, 15, 15, tzinfo=UTC)
    )
