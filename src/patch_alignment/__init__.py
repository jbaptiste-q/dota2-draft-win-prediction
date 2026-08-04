"""Milestone 9: patch note alignment.

This package is deliberately independent of src/liquipedia_backfill,
src/liquipedia_pipeline, and src/draft_training_dataset. Its acquisition
modules (patch_notes_client, hero_mapping) are the only network-touching
code in Milestone 9 and must never be imported from anything under
tests/, since tests/conftest.py unconditionally blocks outbound sockets
for every collected test.
"""

from __future__ import annotations
