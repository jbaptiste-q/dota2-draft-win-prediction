#!/usr/bin/env python3
"""Milestone 9 Phase 1, Steps 1-2: determine scope, then fetch patch notes.

Network-touching. Not part of the offline test suite -- see
src/patch_alignment/patch_notes_client.py for why.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.patch_alignment.corpus_scope import (  # noqa: E402
    DEFAULT_CORPUS_CONFIG_PATH,
    observed_patch_scope,
)
from src.patch_alignment.patch_notes_client import (  # noqa: E402
    DEFAULT_MANIFEST_PATH,
    DEFAULT_RAW_DIRECTORY,
    fetch_versions,
    write_manifest,
)


def main() -> int:
    scope = observed_patch_scope(DEFAULT_CORPUS_CONFIG_PATH)

    print("=== Step 1: observed patch scope (offline, no network yet) ===")
    print(f"Total corpus rows: {scope.total_rows}")
    print(f"Rows with no patch recorded (excluded): {scope.missing_patch_rows}")
    print(f"Distinct patch versions: {len(scope.versions)}")
    print(f"Rows covered by those versions: {scope.covered_rows}")
    for item in scope.versions:
        print(f"  {item.patch:>8}  {item.games:>6} games")
    print()

    print(f"=== Step 2: fetching {len(scope.versions)} versions ===")
    successes, failures = fetch_versions(
        scope.version_strings,
        output_directory=DEFAULT_RAW_DIRECTORY,
    )
    for item in successes:
        print(f"  OK    {item.version:>8}  {item.byte_count:>7} bytes  {item.sha256[:12]}")
    for failure in failures:
        print(f"  FAIL  {failure.version:>8}  {failure.reason}")

    write_manifest(
        manifest_path=DEFAULT_MANIFEST_PATH,
        successes=successes,
        failures=failures,
        generated_at_utc=datetime.now(UTC).isoformat(),
    )
    print()
    print(f"Manifest written: {DEFAULT_MANIFEST_PATH}")
    print(f"Fetched: {len(successes)}  Failed: {len(failures)}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
