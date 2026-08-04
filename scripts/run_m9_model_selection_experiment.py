#!/usr/bin/env python3
"""Milestone 9 Phase 2, Step 2A: model selection experiment.

Labels a 120-change, scope-stratified sample with all three candidate
models (claude-haiku-4-5-20251001, claude-sonnet-5, claude-fable-5)
using the identical prompt, temperature 0. claude-fable-5 is in this
comparison only -- it is never a candidate for the Step 3 full pass.

The sample is topped up with a small number of targeted additions, found
via a cheap Haiku pre-pass over a larger candidate pool, to guarantee at
least STEP_2A_MIN_REWORK_EXAMPLES changes Haiku labels 'rework' and at
least STEP_2A_MIN_NEUTRAL_EXAMPLES it labels 'neutral' -- both directions
are rare in the corpus and a purely random 120-item draw is not reliably
guaranteed to surface either. Since Haiku is itself one of the three
compared models, a Haiku hit already satisfies "any model labels it
X" -- no need to screen with all three.

Network-touching (Anthropic Messages API). Not part of the offline test
suite -- see src/patch_alignment/llm_labeling.py for why.

Requires ANTHROPIC_API_KEY in the environment.

Writes three LOCAL-ONLY files under data/derived/patch_labels/step2a/
(gitignored, verified before writing -- never committed):

  annotation_sheet.csv        pure data, one row per change, two empty
                               columns (direction, magnitude) to fill in
  annotation_guide.md         the labeling guide, kept out of the CSV
  model_outputs_withheld.json the three models' outputs plus sample
                               origin (random/targeted) -- do not open
                               until annotation_sheet.csv is committed
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

from src.patch_alignment.change_flattening import FlattenedChange, flatten_patch_changes  # noqa: E402
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
    STEP_2A_MIN_NEUTRAL_EXAMPLES,
    STEP_2A_MIN_REWORK_EXAMPLES,
    STEP_2A_SAMPLE_SEED,
    STEP_2A_SAMPLE_SIZE,
    draw_screening_pool,
    interleave,
    stratified_sample,
)
from src.patch_alignment.path_guard import assert_path_is_gitignored  # noqa: E402

HAIKU_MODEL_ID = "claude-haiku-4-5-20251001"

STEP2A_DIRECTORY = Path("data/derived/patch_labels/step2a")
ANNOTATION_SHEET_PATH = STEP2A_DIRECTORY / "annotation_sheet.csv"
ANNOTATION_GUIDE_PATH = STEP2A_DIRECTORY / "annotation_guide.md"
MODEL_OUTPUTS_PATH = STEP2A_DIRECTORY / "model_outputs_withheld.json"
CACHE_PATH = STEP2A_DIRECTORY / "label_cache.json"

ANNOTATION_GUIDE_MARKDOWN = """# Milestone 9 Phase 2 Step 2A -- annotation guide

## Fields

- **direction**: `buff` | `nerf` | `neutral` | `rework` | `unclear`
- **magnitude**: `minor` | `moderate` | `major` | `unclear`

## Rules

- A number going up is not automatically a buff -- cooldown, mana cost,
  and cast time going up are nerfs.
- Structural changes to how an ability works are `rework`, not buff or
  nerf, even if they look favourable.
- Bug fixes and tooltip corrections are `neutral`.
- `unclear` is a valid answer and is preferred over guessing.
- Magnitude is a judgement call; internal consistency matters more than
  any absolute standard.
"""


def screen_with_haiku(
    changes: list[FlattenedChange], *, client: AnthropicMessagesClient, cache: LabelCache,
) -> tuple[dict[str, str], list[tuple[str, str]]]:
    """Label every change with Haiku. Returns {change_uid: direction} and failures."""

    directions: dict[str, str] = {}
    failures: list[tuple[str, str]] = []
    for change in changes:
        try:
            result = label_change(change, model_id=HAIKU_MODEL_ID, client=client, cache=cache)
        except (LabelParseError, LLMClientError) as error:
            failures.append((change.change_uid, str(error)))
            continue
        directions[change.change_uid] = result.direction
    return directions, failures


def main() -> int:
    print("Verifying local-only output paths are gitignored before writing anything...")
    for path in (ANNOTATION_SHEET_PATH, ANNOTATION_GUIDE_PATH, MODEL_OUTPUTS_PATH):
        assert_path_is_gitignored(path)
        print(f"  OK (gitignored): {path}")

    changes = flatten_patch_changes()
    changes_by_uid = {change.change_uid: change for change in changes}

    random_sample = stratified_sample(changes, sample_size=STEP_2A_SAMPLE_SIZE, seed=STEP_2A_SAMPLE_SEED)
    print(
        f"Random stratified sample: {len(random_sample)} changes "
        f"(seed={STEP_2A_SAMPLE_SEED}), scopes {sorted({c.scope for c in random_sample})}."
    )

    client = AnthropicMessagesClient.from_env()
    cache = LabelCache(CACHE_PATH)

    print("Screening the random sample with Haiku (this doubles as its Haiku comparison label)...")
    haiku_directions, screen_failures = screen_with_haiku(random_sample, client=client, cache=cache)
    cache.save()

    rework_in_random = [uid for uid, d in haiku_directions.items() if d == "rework"]
    neutral_in_random = [uid for uid, d in haiku_directions.items() if d == "neutral"]
    rework_deficit = max(0, STEP_2A_MIN_REWORK_EXAMPLES - len(rework_in_random))
    neutral_deficit = max(0, STEP_2A_MIN_NEUTRAL_EXAMPLES - len(neutral_in_random))
    print(
        f"Random sample Haiku hits -- rework: {len(rework_in_random)} "
        f"(need {STEP_2A_MIN_REWORK_EXAMPLES}), neutral: {len(neutral_in_random)} "
        f"(need {STEP_2A_MIN_NEUTRAL_EXAMPLES})."
    )

    targeted_uids: list[str] = []
    pool_scanned = 0
    if rework_deficit or neutral_deficit:
        exclude_uids = {c.change_uid for c in random_sample}
        pool = draw_screening_pool(changes, exclude_uids=exclude_uids)
        print(f"Screening a pool of up to {len(pool)} additional changes for targeted top-up...")
        found_rework: list[str] = []
        found_neutral: list[str] = []
        for change in pool:
            if len(found_rework) >= rework_deficit and len(found_neutral) >= neutral_deficit:
                break
            pool_scanned += 1
            try:
                result = label_change(change, model_id=HAIKU_MODEL_ID, client=client, cache=cache)
            except (LabelParseError, LLMClientError) as error:
                screen_failures.append((change.change_uid, str(error)))
                continue
            if result.direction == "rework" and len(found_rework) < rework_deficit:
                found_rework.append(change.change_uid)
            elif result.direction == "neutral" and len(found_neutral) < neutral_deficit:
                found_neutral.append(change.change_uid)
        cache.save()
        targeted_uids = found_rework + found_neutral
        print(
            f"Pool scan complete: scanned {pool_scanned}, found "
            f"{len(found_rework)}/{rework_deficit} rework, {len(found_neutral)}/{neutral_deficit} neutral."
        )
        if len(found_rework) < rework_deficit or len(found_neutral) < neutral_deficit:
            print(
                "WARNING: could not fill the full quota within the screening pool budget. "
                "Reporting the shortfall honestly rather than fabricating examples."
            )

    num_to_drop = len(targeted_uids)
    if num_to_drop:
        protected_uids = set(rework_in_random) | set(neutral_in_random)
        droppable = sorted(
            (uid for uid in haiku_directions if uid not in protected_uids),
            reverse=True,
        )
        dropped_uids = set(droppable[:num_to_drop])
        final_random_uids = [uid for uid in haiku_directions if uid not in dropped_uids]
    else:
        final_random_uids = list(haiku_directions)

    origin_by_uid: dict[str, str] = {uid: "random" for uid in final_random_uids}
    origin_by_uid.update({uid: "targeted" for uid in targeted_uids})
    final_changes = [changes_by_uid[uid] for uid in origin_by_uid]
    print(f"Final sample size: {len(final_changes)} (random: {len(final_random_uids)}, targeted: {len(targeted_uids)})")

    print("Labeling the final sample with all three models (Haiku hits the cache)...")
    outputs: dict[str, dict] = {}
    mismatches: list[tuple[str, str, str]] = []
    label_failures: list[tuple[str, str, str]] = []
    calls_made = 0
    cache_hits = 0
    tokens_by_model: dict[str, dict[str, int]] = {
        model_id: {"input_tokens": 0, "output_tokens": 0, "calls": 0} for model_id in MODEL_IDS
    }

    for change in final_changes:
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
                label_failures.append((change.change_uid, model_id, str(error)))
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
            tokens_by_model[model_id]["input_tokens"] += result.input_tokens
            tokens_by_model[model_id]["output_tokens"] += result.output_tokens
            tokens_by_model[model_id]["calls"] += 1
            if result.model_id_returned != model_id:
                mismatches.append((change.change_uid, model_id, result.model_id_returned))
        outputs[change.change_uid] = {"origin": origin_by_uid[change.change_uid], "models": per_model}
        cache.save()

    # --- annotation_sheet.csv: pure data, interleaved, no guide text ---
    interleaved = interleave(final_changes)
    STEP2A_DIRECTORY.mkdir(parents=True, exist_ok=True)
    with ANNOTATION_SHEET_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["change_uid", "patch", "hero_key", "scope", "ability/context", "raw text", "direction", "magnitude"])
        for change in interleaved:
            writer.writerow(
                [change.change_uid, change.patch, change.hero_key or "", change.scope, change.json_path, change.raw_text, "", ""]
            )

    ANNOTATION_GUIDE_PATH.write_text(ANNOTATION_GUIDE_MARKDOWN, encoding="utf-8")

    MODEL_OUTPUTS_PATH.write_text(
        json.dumps(
            {
                "warning": (
                    "DO NOT OPEN until annotation_sheet.csv is fully annotated and committed. "
                    "Opening this first invalidates the blind comparison."
                ),
                "generated_at_utc": datetime.now(UTC).isoformat(),
                "sample_seed": STEP_2A_SAMPLE_SEED,
                "prompt_version": PROMPT_VERSION,
                "model_ids_requested": list(MODEL_IDS),
                "min_rework_examples": STEP_2A_MIN_REWORK_EXAMPLES,
                "min_neutral_examples": STEP_2A_MIN_NEUTRAL_EXAMPLES,
                "pool_scanned": pool_scanned,
                "outputs": outputs,
            },
            indent=2, sort_keys=True, ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    # --- report ---
    print()
    print("=== Sampling breakdown (random vs targeted, per scope) ===")
    for scope in sorted({c.scope for c in final_changes}):
        random_n = sum(1 for c in final_changes if c.scope == scope and origin_by_uid[c.change_uid] == "random")
        targeted_n = sum(1 for c in final_changes if c.scope == scope and origin_by_uid[c.change_uid] == "targeted")
        print(f"  {scope:>8}: random={random_n:>3}  targeted={targeted_n:>3}  total={random_n + targeted_n:>3}")
    print(f"  {'TOTAL':>8}: random={len(final_random_uids):>3}  targeted={len(targeted_uids):>3}  total={len(final_changes):>3}")

    print()
    print(f"Screening pool scanned: {pool_scanned}")
    print(f"Calls made: {calls_made}  Cache hits: {cache_hits}")
    print(f"Screening/label failures: {len(screen_failures) + len(label_failures)}")
    for uid, error in screen_failures:
        print(f"  screen failure  {uid}  {error}")
    for uid, model_id, error in label_failures:
        print(f"  label failure  {uid}  {model_id}  {error}")

    print()
    print("=== Token counts per model ===")
    for model_id in MODEL_IDS:
        stats = tokens_by_model[model_id]
        print(f"  {model_id}: calls={stats['calls']}  input_tokens={stats['input_tokens']}  output_tokens={stats['output_tokens']}")

    print()
    if mismatches:
        print("Model identifier mismatches (requested vs returned):")
        for change_uid, requested, returned in mismatches:
            print(f"  {change_uid}: requested={requested} returned={returned}")
    else:
        print("No model identifier mismatches.")

    print()
    print(f"Annotation sheet (fill in direction/magnitude, then tell me): {ANNOTATION_SHEET_PATH}")
    print(f"Annotation guide: {ANNOTATION_GUIDE_PATH}")
    print(f"Model outputs (DO NOT OPEN YET): {MODEL_OUTPUTS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
