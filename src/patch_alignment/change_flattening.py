"""Milestone 9 Phase 2, Step 1: flatten hero changes out of raw payloads.

Offline and read-only against the local raw patch-note cache written by
patch_notes_client.py in Phase 1, joined against the hero_id -> hero_key
mapping committed in that same phase. No network access.

Only hero-scoped sources are flattened here, matching Phase 2's stated
goal of labeling individual *hero* changes: hero_notes, talent_notes,
abilities (both hero-level and per-facet via subsections), and
subsections' own general_notes. Top-level items, neutral creeps, and
patch-wide general_notes are out of scope for this phase and are never
emitted -- the "item" scope value exists in the schema for completeness
but this flatten pass does not produce it.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

DEFAULT_RAW_DIRECTORY = Path("data/raw/patch_notes")
DEFAULT_HERO_MAPPING_PATH = Path("configs/patch_alignment/hero_id_mapping.json")

SCOPE_HERO = "hero"
SCOPE_ABILITY = "ability"
SCOPE_TALENT = "talent"
SCOPE_ITEM = "item"
SCOPE_GENERAL = "general"
VALID_SCOPES = (SCOPE_HERO, SCOPE_ABILITY, SCOPE_TALENT, SCOPE_ITEM, SCOPE_GENERAL)


class ChangeFlatteningError(RuntimeError):
    """Raised when a raw payload does not have the expected hero-note shape."""


@dataclass(frozen=True, slots=True)
class FlattenedChange:
    """One atomic hero change, ready to be sent to the labeling model."""

    change_uid: str
    patch: str
    hero_id: int
    hero_key: str | None
    json_path: str
    scope: str
    raw_text: str


def compute_change_uid(
    *, version: str, hero_id: int, json_path: str, raw_text: str
) -> str:
    """sha256 of version + hero_id + json_path + raw_text, stably delimited."""

    payload = "\x1f".join((version, str(hero_id), json_path, raw_text))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_hero_id_to_key(
    mapping_path: Path = DEFAULT_HERO_MAPPING_PATH,
) -> dict[int, str]:
    """Invert the Phase 1 hero_key -> hero_id mapping for lookup by hero_id."""

    payload = json.loads(mapping_path.read_text(encoding="utf-8"))
    return {int(entry["hero_id"]): str(entry["hero_key"]) for entry in payload["mapping"]}


def _notes_records(
    notes: Iterable[dict], *, version: str, hero_id: int, hero_key: str | None,
    path_prefix: str, scope: str,
) -> Iterator[FlattenedChange]:
    for index, entry in enumerate(notes):
        note_text = entry.get("note")
        if not isinstance(note_text, str) or not note_text:
            raise ChangeFlatteningError(
                f"{version}: {path_prefix}[{index}] has no usable 'note' text: {entry!r}"
            )
        json_path = f"{path_prefix}[{index}]"
        yield FlattenedChange(
            change_uid=compute_change_uid(
                version=version, hero_id=hero_id, json_path=json_path, raw_text=note_text
            ),
            patch=version,
            hero_id=hero_id,
            hero_key=hero_key,
            json_path=json_path,
            scope=scope,
            raw_text=note_text,
        )


def _ability_records(
    abilities: Iterable[dict], *, version: str, hero_id: int, hero_key: str | None,
    path_prefix: str,
) -> Iterator[FlattenedChange]:
    for a_index, ability in enumerate(abilities):
        notes = ability.get("ability_notes") or []
        yield from _notes_records(
            notes,
            version=version, hero_id=hero_id, hero_key=hero_key,
            path_prefix=f"{path_prefix}[{a_index}].ability_notes", scope=SCOPE_ABILITY,
        )


def _hero_records(
    hero: dict, *, version: str, hero_key: str | None, hero_index: int,
) -> Iterator[FlattenedChange]:
    hero_id = hero["hero_id"]
    path_prefix = f"heroes[{hero_index}]"

    yield from _notes_records(
        hero.get("hero_notes") or [],
        version=version, hero_id=hero_id, hero_key=hero_key,
        path_prefix=f"{path_prefix}.hero_notes", scope=SCOPE_HERO,
    )
    yield from _notes_records(
        hero.get("talent_notes") or [],
        version=version, hero_id=hero_id, hero_key=hero_key,
        path_prefix=f"{path_prefix}.talent_notes", scope=SCOPE_TALENT,
    )
    yield from _ability_records(
        hero.get("abilities") or [],
        version=version, hero_id=hero_id, hero_key=hero_key,
        path_prefix=f"{path_prefix}.abilities",
    )
    for s_index, sub in enumerate(hero.get("subsections") or []):
        sub_prefix = f"{path_prefix}.subsections[{s_index}]"
        yield from _ability_records(
            sub.get("abilities") or [],
            version=version, hero_id=hero_id, hero_key=hero_key,
            path_prefix=f"{sub_prefix}.abilities",
        )
        yield from _notes_records(
            sub.get("talent_notes") or [],
            version=version, hero_id=hero_id, hero_key=hero_key,
            path_prefix=f"{sub_prefix}.talent_notes", scope=SCOPE_TALENT,
        )
        yield from _notes_records(
            sub.get("general_notes") or [],
            version=version, hero_id=hero_id, hero_key=hero_key,
            path_prefix=f"{sub_prefix}.general_notes", scope=SCOPE_GENERAL,
        )


def flatten_payload(
    payload: dict, *, hero_id_to_key: dict[int, str]
) -> Iterator[FlattenedChange]:
    """Flatten one raw patch-notes payload into atomic hero-change records."""

    version = payload.get("patch_number")
    if not isinstance(version, str) or not version:
        raise ChangeFlatteningError("payload has no patch_number.")
    for hero_index, hero in enumerate(payload.get("heroes") or []):
        hero_id = hero.get("hero_id")
        if not isinstance(hero_id, int):
            raise ChangeFlatteningError(
                f"{version}: heroes[{hero_index}] has no numeric hero_id: {hero!r}"
            )
        hero_key = hero_id_to_key.get(hero_id)
        yield from _hero_records(hero, version=version, hero_key=hero_key, hero_index=hero_index)


def flatten_patch_changes(
    *,
    raw_directory: Path = DEFAULT_RAW_DIRECTORY,
    manifest_path: Path | None = None,
    hero_mapping_path: Path = DEFAULT_HERO_MAPPING_PATH,
) -> list[FlattenedChange]:
    """Flatten every successfully fetched Phase 1 payload, in manifest order."""

    manifest_path = manifest_path or (raw_directory / "manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    hero_id_to_key = load_hero_id_to_key(hero_mapping_path)

    changes: list[FlattenedChange] = []
    for entry in sorted(manifest["versions"], key=lambda item: item["version"]):
        raw_path = raw_directory / entry["raw_file"]
        payload = json.loads(raw_path.read_text(encoding="utf-8"))
        changes.extend(flatten_payload(payload, hero_id_to_key=hero_id_to_key))
    return changes


__all__ = [
    "DEFAULT_HERO_MAPPING_PATH",
    "DEFAULT_RAW_DIRECTORY",
    "SCOPE_ABILITY",
    "SCOPE_GENERAL",
    "SCOPE_HERO",
    "SCOPE_ITEM",
    "SCOPE_TALENT",
    "VALID_SCOPES",
    "ChangeFlatteningError",
    "FlattenedChange",
    "compute_change_uid",
    "flatten_patch_changes",
    "flatten_payload",
    "load_hero_id_to_key",
]
