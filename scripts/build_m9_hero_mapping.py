#!/usr/bin/env python3
"""Milestone 9 Phase 1, Step 3: build the hero_id -> hero_key mapping.

Network-touching (OpenDota /api/heroes only). Not part of the offline
test suite -- see src/patch_alignment/hero_mapping.py for why.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.patch_alignment.hero_mapping import (  # noqa: E402
    DEFAULT_MAPPING_OUTPUT_PATH,
    DEFAULT_VOCABULARY_PATH,
    build_hero_id_mapping,
    fetch_opendota_heroes,
    load_vocabulary_hero_keys,
    write_mapping,
)


def main() -> int:
    print("=== Step 3: hero_id -> hero_key mapping ===")
    vocabulary = load_vocabulary_hero_keys(DEFAULT_VOCABULARY_PATH)
    print(f"Vocabulary ({DEFAULT_VOCABULARY_PATH}): {len(vocabulary)} heroes")

    opendota_heroes = fetch_opendota_heroes()
    print(f"OpenDota /api/heroes: {len(opendota_heroes)} heroes")

    result = build_hero_id_mapping(opendota_heroes, vocabulary)
    print()
    print(f"Mapped cleanly: {len(result.mapped)} / {result.vocabulary_size}")
    print(f"Unmatched vocabulary hero_key values: {len(result.unmatched_vocabulary)}")
    for hero_key in result.unmatched_vocabulary:
        print(f"  vocabulary side: {hero_key!r}")
    print(f"Unmatched OpenDota heroes: {len(result.unmatched_opendota)}")
    for entry in result.unmatched_opendota:
        print(
            f"  opendota side: hero_id={entry['hero_id']} "
            f"localized_name={entry['localized_name']!r} "
            f"normalized={entry['normalized_key']!r}"
        )

    write_mapping(
        result,
        output_path=DEFAULT_MAPPING_OUTPUT_PATH,
        generated_at_utc=datetime.now(UTC).isoformat(),
    )
    print()
    print(f"Mapping written: {DEFAULT_MAPPING_OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
