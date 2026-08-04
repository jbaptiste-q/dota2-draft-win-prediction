"""Offline tests for Milestone 9 Phase 2 Step 1: change flattening.

Uses a small fabricated payload shaped like the real Dota 2 patch-notes
feed, never real Valve text, and never touches data/raw/patch_notes/.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.patch_alignment.change_flattening import (
    ChangeFlatteningError,
    compute_change_uid,
    flatten_patch_changes,
    flatten_payload,
)

FAKE_PAYLOAD = {
    "success": True,
    "patch_number": "9.99z",
    "patch_name": "Fixture Patch",
    "patch_timestamp": "0",
    "heroes": [
        {
            "hero_id": 1,
            "hero_notes": [{"indent_level": 1, "note": "Fixture hero note"}],
            "talent_notes": [{"indent_level": 1, "note": "Fixture talent note"}],
            "abilities": [
                {
                    "ability_id": 100,
                    "ability_notes": [{"indent_level": 1, "note": "Fixture ability note"}],
                }
            ],
            "subsections": [
                {
                    "title": "Fixture Facet",
                    "style": "hero_facet",
                    "facet": "fixture_facet",
                    "abilities": [
                        {
                            "ability_id": 200,
                            "ability_notes": [
                                {"indent_level": 1, "note": "Fixture facet ability note"}
                            ],
                        }
                    ],
                    "talent_notes": [{"indent_level": 1, "note": "Fixture facet talent note"}],
                    "general_notes": [{"indent_level": 1, "note": "Fixture facet general note"}],
                }
            ],
        },
        {
            "hero_id": 999,
            "hero_notes": [{"indent_level": 1, "note": "Fixture unmapped hero note"}],
        },
    ],
}

HERO_MAPPING = {"mapping": [{"hero_key": "fixture_hero", "hero_id": 1, "opendota_localized_name": "Fixture Hero"}]}


@pytest.fixture
def fixture_raw_directory(tmp_path: Path) -> Path:
    raw_directory = tmp_path / "raw"
    raw_directory.mkdir()
    (raw_directory / "9.99z.json").write_text(json.dumps(FAKE_PAYLOAD), encoding="utf-8")
    (raw_directory / "manifest.json").write_text(
        json.dumps({"versions": [{"version": "9.99z", "raw_file": "9.99z.json"}], "failures": []}),
        encoding="utf-8",
    )
    mapping_path = tmp_path / "hero_id_mapping.json"
    mapping_path.write_text(json.dumps(HERO_MAPPING), encoding="utf-8")
    return raw_directory


def test_flatten_counts_and_scopes(fixture_raw_directory: Path) -> None:
    changes = flatten_patch_changes(
        raw_directory=fixture_raw_directory,
        hero_mapping_path=fixture_raw_directory.parent / "hero_id_mapping.json",
    )
    assert len(changes) == 7

    scopes = [change.scope for change in changes]
    assert scopes.count("hero") == 2
    assert scopes.count("talent") == 2
    assert scopes.count("ability") == 2
    assert scopes.count("general") == 1
    assert scopes.count("item") == 0


def test_flatten_resolves_hero_key_and_flags_unmapped(fixture_raw_directory: Path) -> None:
    changes = flatten_patch_changes(
        raw_directory=fixture_raw_directory,
        hero_mapping_path=fixture_raw_directory.parent / "hero_id_mapping.json",
    )
    mapped = [c for c in changes if c.hero_id == 1]
    unmapped = [c for c in changes if c.hero_id == 999]
    assert all(c.hero_key == "fixture_hero" for c in mapped)
    assert len(unmapped) == 1
    assert unmapped[0].hero_key is None


def test_flatten_json_paths_are_distinct_and_locate_the_source(fixture_raw_directory: Path) -> None:
    changes = flatten_patch_changes(
        raw_directory=fixture_raw_directory,
        hero_mapping_path=fixture_raw_directory.parent / "hero_id_mapping.json",
    )
    paths = [c.json_path for c in changes]
    assert len(paths) == len(set(paths))
    assert "heroes[0].hero_notes[0]" in paths
    assert "heroes[0].subsections[0].general_notes[0]" in paths


def test_change_uid_is_deterministic_and_content_sensitive() -> None:
    first = compute_change_uid(version="7.39e", hero_id=1, json_path="heroes[0].hero_notes[0]", raw_text="X")
    again = compute_change_uid(version="7.39e", hero_id=1, json_path="heroes[0].hero_notes[0]", raw_text="X")
    different_text = compute_change_uid(version="7.39e", hero_id=1, json_path="heroes[0].hero_notes[0]", raw_text="Y")
    assert first == again
    assert first != different_text


def test_flatten_payload_rejects_missing_patch_number() -> None:
    with pytest.raises(ChangeFlatteningError):
        list(flatten_payload({"heroes": []}, hero_id_to_key={}))


def test_flatten_payload_rejects_hero_without_numeric_hero_id() -> None:
    payload = {"patch_number": "9.99z", "heroes": [{"hero_notes": []}]}
    with pytest.raises(ChangeFlatteningError):
        list(flatten_payload(payload, hero_id_to_key={}))


def test_flatten_payload_rejects_note_without_text() -> None:
    payload = {
        "patch_number": "9.99z",
        "heroes": [{"hero_id": 1, "hero_notes": [{"indent_level": 1}]}],
    }
    with pytest.raises(ChangeFlatteningError):
        list(flatten_payload(payload, hero_id_to_key={}))
