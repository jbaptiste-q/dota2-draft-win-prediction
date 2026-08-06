#!/usr/bin/env python3
"""Milestone 9 Phase 2, Step 3: full labeling pass and commit-ready output.

Network-touching (Anthropic Messages API). Not part of the offline test
suite -- see src/patch_alignment/llm_labeling.py for why.

Requires ANTHROPIC_API_KEY in the environment. The model to use is a
required CLI argument -- this script has no hardcoded default, since
Milestone 9 Phase 2 requires the model be confirmed by hand (via the
Step 2A experiment) before this runs.

Writes data/derived/patch_labels/labels.json: change_uid, patch,
hero_key, scope, direction, change_type, confidence, model_id (as
returned by the API), and prompt_version. magnitude is still requested
from the model (the prompt/schema is unchanged, so the existing label
cache stays valid) but is dropped from the committed output -- see
docs/findings/2026-08-05_m9_magnitude_dropped.md for why Phase 4 uses
direction only. raw_text is never included -- it is Valve's content and
stays in the gitignored local cache (data/derived/patch_labels/cache.json).

Usage:
    .venv/bin/python scripts/run_m9_full_labeling_pass.py --model-id claude-haiku-4-5-20251001
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.patch_alignment.change_flattening import flatten_patch_changes  # noqa: E402
from src.patch_alignment.llm_labeling import (  # noqa: E402
    AnthropicMessagesClient,
    LabelCache,
    LabelParseError,
    LLMClientError,
    PROMPT_VERSION,
    label_change,
)

CACHE_PATH = Path("data/derived/patch_labels/cache.json")
LABELS_OUTPUT_PATH = Path("data/derived/patch_labels/labels.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model-id", required=True,
        help="Model id confirmed via the Step 2A experiment (e.g. claude-sonnet-5). "
             "No default -- must be explicit.",
    )
    parser.add_argument(
        "--input-price-per-million", type=float, default=None,
        help="USD per 1M input tokens, for the cost estimate in the report. "
             "If omitted, only raw token counts are reported.",
    )
    parser.add_argument(
        "--output-price-per-million", type=float, default=None,
        help="USD per 1M output tokens, for the cost estimate in the report.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    changes = flatten_patch_changes()
    unmapped = [change for change in changes if change.hero_key is None]

    client = AnthropicMessagesClient.from_env()
    cache = LabelCache(CACHE_PATH)

    labeled: list[dict] = []
    failures: list[tuple[str, str]] = []
    calls_made = 0
    cache_hits = 0
    total_input_tokens = 0
    total_output_tokens = 0

    for change in changes:
        already_cached = cache.get(
            change_uid=change.change_uid, model_id=args.model_id, prompt_version=PROMPT_VERSION
        )
        if already_cached is not None:
            cache_hits += 1
        else:
            calls_made += 1
        try:
            result = label_change(change, model_id=args.model_id, client=client, cache=cache)
        except (LabelParseError, LLMClientError) as error:
            failures.append((change.change_uid, str(error)))
            continue

        total_input_tokens += result.input_tokens
        total_output_tokens += result.output_tokens
        labeled.append(
            {
                "change_uid": change.change_uid,
                "patch": change.patch,
                "hero_key": change.hero_key,
                "scope": change.scope,
                "direction": result.direction,
                "change_type": result.change_type,
                "confidence": result.confidence,
                "model_id": result.model_id_returned,
                "prompt_version": PROMPT_VERSION,
            }
        )
        if calls_made and calls_made % 200 == 0:
            cache.save()

    cache.save()

    LABELS_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    LABELS_OUTPUT_PATH.write_text(
        json.dumps(
            sorted(labeled, key=lambda item: item["change_uid"]),
            indent=2, sort_keys=True, ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    direction_counts = Counter(item["direction"] for item in labeled)
    unmapped_by_hero = Counter(change.hero_id for change in unmapped)

    print(f"Total changes: {len(changes)}")
    print(f"Labeled successfully: {len(labeled)}")
    print(f"Calls made: {calls_made}  Cache hits: {cache_hits}  Parse/API failures: {len(failures)}")
    print(f"Total input tokens: {total_input_tokens}  Total output tokens: {total_output_tokens}")
    if args.input_price_per_million is not None and args.output_price_per_million is not None:
        cost = (
            total_input_tokens / 1_000_000 * args.input_price_per_million
            + total_output_tokens / 1_000_000 * args.output_price_per_million
        )
        print(f"Estimated cost: ${cost:.4f}")
    else:
        print("Estimated cost: not computed (pass --input-price-per-million and "
              "--output-price-per-million to compute).")
    print("Direction distribution:", dict(direction_counts))
    print(f"Unmapped-hero changes: {len(unmapped)} across hero_ids {dict(unmapped_by_hero)}")
    if failures:
        print("Failures (change_uid, error):")
        for change_uid, error in failures:
            print(f"  {change_uid}  {error}")
    print(f"Labels written: {LABELS_OUTPUT_PATH}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
