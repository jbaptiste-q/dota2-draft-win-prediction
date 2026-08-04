"""Step 3: automated hero_id -> hero_key mapping.

Fetches hero_id -> localized_name from OpenDota's public /api/heroes
endpoint, normalizes every name with the SAME identity_key() function
the Liquipedia pipeline already uses to build hero_key (imported, not
reimplemented), and joins on the normalized form. Coverage is checked
against the frozen 125-hero product catalog
(src/draft_ai_assistant/resources/development_candidate_v0.json), read
only -- draft_ai_assistant is not modified.

This is the second and last network-touching module in Milestone 9
Phase 1. Like patch_notes_client.py, it is deliberately kept out of
tests/, since tests/conftest.py unconditionally blocks outbound sockets
for every collected test.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen

from src.liquipedia_pipeline.normalization import (
    NormalizationError,
    identity_key,
)


USER_AGENT = "Dota2AIPortfolioPatchAlignment/1.0"
OPENDOTA_HEROES_URL = "https://api.opendota.com/api/heroes"
DEFAULT_TIMEOUT_SECONDS = 30.0
MAPPING_SCHEMA_VERSION = "dota2-ml-portfolio-hero-id-mapping-v1"
DEFAULT_VOCABULARY_PATH = Path(
    "src/draft_ai_assistant/resources/development_candidate_v0.json"
)
DEFAULT_MAPPING_OUTPUT_PATH = Path("configs/patch_alignment/hero_id_mapping.json")

# Heroes confirmed present in the M4A working corpus's pick/ban columns
# (via a sealed-window-compliant, non-sealed-rows-only check performed
# 2026-08-04) but absent from the frozen 125-hero product vocabulary
# catalog -- the catalog predates these heroes' addition to the corpus.
# The frozen catalog (DEFAULT_VOCABULARY_PATH) is never edited; these
# are added directly to the M9 mapping instead, with hero_id sourced
# from OpenDota. 'largo' (hero_id=155) was checked the same way and did
# not appear in the non-sealed portion of the corpus, so it is not
# added here -- its status in the sealed portion is unknown and
# unknowable under the locked test policy.
CORPUS_CONFIRMED_ADDITIONS: tuple[dict[str, object], ...] = (
    {
        "hero_key": "kez",
        "hero_id": 145,
        "opendota_localized_name": "Kez",
        "justification": (
            "Present as a pick/ban value in the M4A working corpus's "
            "non-sealed rows; absent from the frozen 125-hero vocabulary."
        ),
    },
)


class HeroMappingError(RuntimeError):
    """Raised when the OpenDota hero list cannot be fetched, parsed, or joined."""


@dataclass(frozen=True, slots=True)
class OpenDotaHero:
    """One hero as reported by OpenDota, plus its normalized join key."""

    hero_id: int
    localized_name: str
    normalized_key: str


@dataclass(frozen=True, slots=True)
class HeroMappingResult:
    """The outcome of joining OpenDota heroes onto our hero_key vocabulary."""

    mapped: tuple[dict[str, object], ...]
    unmatched_vocabulary: tuple[str, ...]
    unmatched_opendota: tuple[dict[str, object], ...]

    @property
    def vocabulary_size(self) -> int:
        return len(self.mapped) + len(self.unmatched_vocabulary)


def fetch_opendota_heroes(
    *, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
) -> list[OpenDotaHero]:
    """Fetch every hero from OpenDota and normalize its name with identity_key."""

    request = Request(
        OPENDOTA_HEROES_URL,
        method="GET",
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
    )
    with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
        body = response.read()
    payload = json.loads(body)
    if not isinstance(payload, list) or not payload:
        raise HeroMappingError(
            "OpenDota /api/heroes did not return a non-empty JSON array."
        )

    heroes: list[OpenDotaHero] = []
    for entry in payload:
        if not isinstance(entry, dict):
            raise HeroMappingError(f"Unexpected OpenDota hero entry: {entry!r}")
        hero_id = entry.get("id")
        localized_name = entry.get("localized_name")
        if not isinstance(hero_id, int) or not isinstance(localized_name, str):
            raise HeroMappingError(f"Unexpected OpenDota hero entry: {entry!r}")
        try:
            normalized = identity_key(localized_name)
        except NormalizationError as error:
            raise HeroMappingError(
                f"Could not normalize OpenDota hero name {localized_name!r} "
                f"(hero_id {hero_id})."
            ) from error
        heroes.append(
            OpenDotaHero(
                hero_id=hero_id,
                localized_name=localized_name,
                normalized_key=normalized,
            )
        )
    return heroes


def load_vocabulary_hero_keys(
    vocabulary_path: Path = DEFAULT_VOCABULARY_PATH,
) -> tuple[str, ...]:
    """Read the frozen 125-hero product catalog's hero_key set (read-only)."""

    payload = json.loads(vocabulary_path.read_text(encoding="utf-8"))
    heroes = payload.get("heroes")
    if not isinstance(heroes, list) or not heroes:
        raise HeroMappingError(
            f"{vocabulary_path} does not contain a non-empty 'heroes' list."
        )
    keys = tuple(
        sorted(
            str(hero["hero_key"])
            for hero in heroes
            if isinstance(hero, dict) and "hero_key" in hero
        )
    )
    if len(keys) != len(heroes):
        raise HeroMappingError(
            f"{vocabulary_path} contains a hero entry without hero_key."
        )
    return keys


def build_hero_id_mapping(
    opendota_heroes: list[OpenDotaHero],
    vocabulary_hero_keys: tuple[str, ...],
) -> HeroMappingResult:
    """Join OpenDota heroes onto our hero_key vocabulary by normalized name.

    Ambiguous matches (two OpenDota heroes normalizing to the same key)
    are treated as a hard error rather than a silent pick, since that
    would misattribute patch note changes between two different heroes.
    """

    by_normalized: dict[str, list[OpenDotaHero]] = {}
    for hero in opendota_heroes:
        by_normalized.setdefault(hero.normalized_key, []).append(hero)

    ambiguous = {
        key: candidates
        for key, candidates in by_normalized.items()
        if len(candidates) > 1
    }
    if ambiguous:
        details = {
            key: [hero.localized_name for hero in candidates]
            for key, candidates in ambiguous.items()
        }
        raise HeroMappingError(
            f"Ambiguous OpenDota normalized keys, each matching more than "
            f"one hero: {details}"
        )

    mapped: list[dict[str, object]] = []
    unmatched_vocabulary: list[str] = []
    matched_normalized_keys: set[str] = set()

    for hero_key in vocabulary_hero_keys:
        candidates = by_normalized.get(hero_key)
        if not candidates:
            unmatched_vocabulary.append(hero_key)
            continue
        matched_normalized_keys.add(hero_key)
        hero = candidates[0]
        mapped.append(
            {
                "hero_key": hero_key,
                "hero_id": hero.hero_id,
                "opendota_localized_name": hero.localized_name,
            }
        )

    unmatched_opendota = tuple(
        {
            "hero_id": hero.hero_id,
            "localized_name": hero.localized_name,
            "normalized_key": hero.normalized_key,
        }
        for hero in sorted(opendota_heroes, key=lambda hero: hero.hero_id)
        if hero.normalized_key not in matched_normalized_keys
    )

    return HeroMappingResult(
        mapped=tuple(mapped),
        unmatched_vocabulary=tuple(unmatched_vocabulary),
        unmatched_opendota=unmatched_opendota,
    )


def apply_corpus_confirmed_additions(
    result: HeroMappingResult,
    opendota_heroes: list[OpenDotaHero],
    *,
    additions: tuple[dict[str, object], ...] = CORPUS_CONFIRMED_ADDITIONS,
) -> tuple[HeroMappingResult, int]:
    """Fold CORPUS_CONFIRMED_ADDITIONS into a HeroMappingResult.

    Each addition is validated against the live OpenDota fetch (its
    hero_id must exist and its localized_name must still match) rather
    than trusted blindly, so a stale hardcoded entry cannot silently
    drift from what OpenDota actually reports. Returns the updated
    result plus how many additions were actually applied (already-mapped
    hero_keys are skipped, not double-added).
    """

    by_id = {hero.hero_id: hero for hero in opendota_heroes}
    already_mapped_keys = {str(item["hero_key"]) for item in result.mapped}

    extra_mapped: list[dict[str, object]] = []
    for addition in additions:
        hero_key = str(addition["hero_key"])
        hero_id = int(addition["hero_id"])
        if hero_key in already_mapped_keys:
            continue
        hero = by_id.get(hero_id)
        if hero is None:
            raise HeroMappingError(
                f"Corpus-confirmed addition {hero_key!r} (hero_id={hero_id}) "
                "is no longer present in the OpenDota hero list."
            )
        if hero.localized_name != addition["opendota_localized_name"]:
            raise HeroMappingError(
                f"Corpus-confirmed addition {hero_key!r} (hero_id={hero_id}) "
                f"expected OpenDota localized_name "
                f"{addition['opendota_localized_name']!r}, got {hero.localized_name!r}."
            )
        extra_mapped.append(
            {
                "hero_key": hero_key,
                "hero_id": hero.hero_id,
                "opendota_localized_name": hero.localized_name,
            }
        )

    added_ids = {int(item["hero_id"]) for item in extra_mapped}
    remaining_unmatched_opendota = tuple(
        entry for entry in result.unmatched_opendota if entry["hero_id"] not in added_ids
    )

    updated = HeroMappingResult(
        mapped=tuple(result.mapped) + tuple(extra_mapped),
        unmatched_vocabulary=result.unmatched_vocabulary,
        unmatched_opendota=remaining_unmatched_opendota,
    )
    return updated, len(extra_mapped)


def write_mapping(
    result: HeroMappingResult,
    *,
    output_path: Path = DEFAULT_MAPPING_OUTPUT_PATH,
    generated_at_utc: str,
    corpus_confirmed_additions_count: int = 0,
) -> None:
    """Write the committed hero_id -> hero_key mapping.

    Only the clean, unambiguous matches are written to the mapping file
    itself; unmatched entries on either side are a Step 3 report finding,
    not something this function silently papers over.
    """

    payload = {
        "schema_version": MAPPING_SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc,
        "source": OPENDOTA_HEROES_URL,
        "vocabulary_source": str(DEFAULT_VOCABULARY_PATH),
        "vocabulary_size": result.vocabulary_size,
        "mapped_count": len(result.mapped),
        "unmatched_vocabulary_count": len(result.unmatched_vocabulary),
        "corpus_confirmed_additions_count": corpus_confirmed_additions_count,
        "mapping": sorted(
            result.mapped, key=lambda item: str(item["hero_key"])
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


__all__ = [
    "CORPUS_CONFIRMED_ADDITIONS",
    "DEFAULT_MAPPING_OUTPUT_PATH",
    "DEFAULT_VOCABULARY_PATH",
    "HeroMappingError",
    "HeroMappingResult",
    "OpenDotaHero",
    "apply_corpus_confirmed_additions",
    "build_hero_id_mapping",
    "fetch_opendota_heroes",
    "load_vocabulary_hero_keys",
    "write_mapping",
]
