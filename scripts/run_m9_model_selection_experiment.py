#!/usr/bin/env python3
"""Milestone 9 Phase 2, Step 2A: model selection experiment.

Labels 80 stratified-sampled changes with all three candidate models
(claude-haiku-4-5-20251001, claude-sonnet-5, claude-fable-5) using the
identical prompt, temperature 0.

Network-touching (Anthropic Messages API, up to 240 calls). Not part of
the offline test suite -- see src/patch_alignment/llm_labeling.py for why.

Requires ANTHROPIC_API_KEY in the environment.

Writes two LOCAL-ONLY files under data/derived/patch_labels/step2a/
(gitignored, never committed):

  review_sheet.csv            raw text + empty columns for hand annotation
  model_outputs_withheld.json the three models' outputs -- do not open
                               until review_sheet.csv is fully annotated

This script only produces those two files and a disagreement report; it
does not compute accuracy or recommend a model. That happens in a later,
separate step once the hand annotation is back.
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import UTC, datetime
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
from src.patch_alignment.model_selection import (  # noqa: E402
    MODEL_IDS,
    STEP_2A_SAMPLE_SEED,
    STEP_2A_SAMPLE_SIZE,
    stratified_sample,
)

STEP2A_DIRECTORY = Path("data/derived/patch_labels/step2a")
REVIEW_SHEET_PATH = STEP2A_DIRECTORY / "review_sheet.csv"
MODEL_OUTPUTS_PATH = STEP2A_DIRECTORY / "model_outputs_withheld.json"
CACHE_PATH = STEP2A_DIRECTORY / "label_cache.json"


def main() -> int:
    changes = flatten_patch_changes()
    sample = stratified_sample(changes, sample_size=STEP_2A_SAMPLE_SIZE, seed=STEP_2A_SAMPLE_SEED)
    print(
        f"Sampled {len(sample)} changes (seed={STEP_2A_SAMPLE_SEED}) across "
        f"{len({c.patch for c in sample})} patches, scopes "
        f"{sorted({c.scope for c in sample})}."
    )

    client = AnthropicMessagesClient.from_env()
    cache = LabelCache(CACHE_PATH)

    outputs: dict[str, dict] = {}
    mismatches: list[tuple[str, str, str]] = []
    failures: list[tuple[str, str, str]] = []
    calls_made = 0
    cache_hits = 0

    for change in sample:
        per_model: dict[str, dict] = {}
        for model_id in MODEL_IDS:
            already_cached = cache.get(
                change_uid=change.change_uid, model_id=model_id, prompt_version=PROMPT_VERSION
            )
            if already_cached is not None:
                cache_hits += 1
            else:
                calls_made += 1
            try:
                result = label_change(change, model_id=model_id, client=client, cache=cache)
            except (LabelParseError, LLMClientError) as error:
                failures.append((change.change_uid, model_id, str(error)))
                continue
            per_model[model_id] = {
                "direction": result.direction,
                "magnitude": result.magnitude,
                "change_type": result.change_type,
                "confidence": result.confidence,
                "model_id_requested": result.model_id_requested,
                "model_id_returned": result.model_id_returned,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
            }
            if result.model_id_returned != model_id:
                mismatches.append((change.change_uid, model_id, result.model_id_returned))
        outputs[change.change_uid] = per_model
        cache.save()

    STEP2A_DIRECTORY.mkdir(parents=True, exist_ok=True)
    with REVIEW_SHEET_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "change_uid", "patch", "hero_key", "scope", "json_path", "raw_text",
                "my_direction", "my_magnitude", "my_change_type", "my_confidence", "my_notes",
            ]
        )
        for change in sample:
            writer.writerow(
                [
                    change.change_uid, change.patch, change.hero_key or "", change.scope,
                    change.json_path, change.raw_text, "", "", "", "", "",
                ]
            )

    MODEL_OUTPUTS_PATH.write_text(
        json.dumps(
            {
                "warning": (
                    "DO NOT OPEN until your review_sheet.csv annotation is complete. "
                    "Opening this first invalidates the blind comparison."
                ),
                "generated_at_utc": datetime.now(UTC).isoformat(),
                "sample_seed": STEP_2A_SAMPLE_SEED,
                "prompt_version": PROMPT_VERSION,
                "model_ids_requested": list(MODEL_IDS),
                "outputs": outputs,
            },
            indent=2, sort_keys=True, ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"Calls made: {calls_made}  Cache hits: {cache_hits}  Failures: {len(failures)}")
    print(f"Review sheet (fill this in by hand, then tell me): {REVIEW_SHEET_PATH}")
    print(f"Model outputs (DO NOT OPEN YET): {MODEL_OUTPUTS_PATH}")
    if failures:
        print("Label failures (change_uid, model_id, error):")
        for change_uid, model_id, error in failures:
            print(f"  {change_uid}  {model_id}  {error}")
    if mismatches:
        print("Model identifier mismatches (requested vs returned):")
        for change_uid, requested, returned in mismatches:
            print(f"  {change_uid}: requested={requested} returned={returned}")
    else:
        print("No model identifier mismatches.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
