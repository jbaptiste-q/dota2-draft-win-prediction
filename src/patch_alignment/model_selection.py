"""Milestone 9 Phase 2, Step 2A: stratified sampling for the model-selection
experiment.

Pure and offline -- no network, no LLM calls. Given the already-flattened
change list, deterministically samples a fixed-size subset stratified
across patch and scope (hero / ability / talent only; general and item
are excluded from the experiment population).
"""

from __future__ import annotations

import random
from collections.abc import Sequence

from src.patch_alignment.change_flattening import FlattenedChange

MODEL_IDS: tuple[str, ...] = (
    "claude-haiku-4-5-20251001",
    "claude-sonnet-5",
    "claude-fable-5",
)

STEP_2A_SAMPLE_SIZE = 120
STEP_2A_SAMPLE_SEED = 20260804
STEP_2A_SCOPES: tuple[str, ...] = ("hero", "ability", "talent")

# Guarantee at least this many changes labeled 'rework' and 'neutral' by
# the cheap screening model (Haiku), so the model-selection experiment
# always has some examples of each even though both are rare in the
# corpus overall. Since Haiku is itself one of the three compared
# models, a Haiku-screened hit already satisfies "any model labels it
# rework/neutral" -- no need to screen with all three models.
STEP_2A_MIN_REWORK_EXAMPLES = 10
STEP_2A_MIN_NEUTRAL_EXAMPLES = 10
STEP_2A_SCREENING_POOL_SIZE = 500
STEP_2A_SCREENING_SEED = STEP_2A_SAMPLE_SEED + 1
STEP_2A_INTERLEAVE_SEED = STEP_2A_SAMPLE_SEED + 2


def stratified_sample(
    changes: Sequence[FlattenedChange],
    *,
    sample_size: int = STEP_2A_SAMPLE_SIZE,
    seed: int = STEP_2A_SAMPLE_SEED,
    scopes: tuple[str, ...] = STEP_2A_SCOPES,
) -> list[FlattenedChange]:
    """Deterministically sample sample_size changes, stratified by (patch, scope).

    Allocation across strata is proportional to stratum size (largest
    remainder method), so patches and scopes with more changes get more
    of the sample, but every non-empty stratum sized `sample_size` or
    larger relative to the population contributes at least a fair share.
    Fully deterministic for a fixed (changes, sample_size, seed, scopes).
    """

    population = [change for change in changes if change.scope in scopes]
    if not population:
        raise ValueError("No changes available in the requested scopes.")
    if sample_size > len(population):
        raise ValueError(
            f"sample_size={sample_size} exceeds population={len(population)}."
        )

    strata: dict[tuple[str, str], list[FlattenedChange]] = {}
    for change in population:
        strata.setdefault((change.patch, change.scope), []).append(change)
    for stratum in strata.values():
        stratum.sort(key=lambda change: change.change_uid)

    stratum_keys = sorted(strata.keys())
    total = len(population)

    raw_allocation = {key: sample_size * len(strata[key]) / total for key in stratum_keys}
    allocation = {key: int(raw_allocation[key]) for key in stratum_keys}
    remainder = sample_size - sum(allocation.values())

    by_fraction = sorted(
        stratum_keys,
        key=lambda key: (-(raw_allocation[key] - allocation[key]), key),
    )
    for key in by_fraction[:remainder]:
        allocation[key] += 1

    for key in stratum_keys:
        allocation[key] = min(allocation[key], len(strata[key]))

    shortfall = sample_size - sum(allocation.values())
    if shortfall > 0:
        spare = sorted(
            (key for key in stratum_keys if allocation[key] < len(strata[key])),
            key=lambda key: (-(len(strata[key]) - allocation[key]), key),
        )
        index = 0
        while shortfall > 0 and spare:
            key = spare[index % len(spare)]
            if allocation[key] < len(strata[key]):
                allocation[key] += 1
                shortfall -= 1
            index += 1

    rng = random.Random(seed)
    sample: list[FlattenedChange] = []
    for key in stratum_keys:
        count = allocation[key]
        if count > 0:
            sample.extend(rng.sample(strata[key], count))

    sample.sort(key=lambda change: (change.patch, change.scope, change.change_uid))
    return sample


def draw_screening_pool(
    changes: Sequence[FlattenedChange],
    *,
    exclude_uids: set[str],
    pool_size: int = STEP_2A_SCREENING_POOL_SIZE,
    seed: int = STEP_2A_SCREENING_SEED,
    scopes: tuple[str, ...] = STEP_2A_SCOPES,
) -> list[FlattenedChange]:
    """Deterministically draw a bounded candidate pool for targeted top-up.

    Excludes anything already in the main random sample. Sorted by
    change_uid so scanning the pool in order (with early stopping once
    quotas are met) is itself deterministic.
    """

    population = sorted(
        (
            change for change in changes
            if change.scope in scopes and change.change_uid not in exclude_uids
        ),
        key=lambda change: change.change_uid,
    )
    if not population:
        return []
    rng = random.Random(seed)
    size = min(pool_size, len(population))
    pool = rng.sample(population, size)
    pool.sort(key=lambda change: change.change_uid)
    return pool


def interleave(
    changes: Sequence[FlattenedChange], *, seed: int = STEP_2A_INTERLEAVE_SEED
) -> list[FlattenedChange]:
    """Deterministically shuffle so origin (random vs targeted) isn't visible
    from row order alone."""

    shuffled = sorted(changes, key=lambda change: change.change_uid)
    random.Random(seed).shuffle(shuffled)
    return shuffled


__all__ = [
    "MODEL_IDS",
    "STEP_2A_INTERLEAVE_SEED",
    "STEP_2A_MIN_NEUTRAL_EXAMPLES",
    "STEP_2A_MIN_REWORK_EXAMPLES",
    "STEP_2A_SAMPLE_SEED",
    "STEP_2A_SAMPLE_SIZE",
    "STEP_2A_SCOPES",
    "STEP_2A_SCREENING_POOL_SIZE",
    "STEP_2A_SCREENING_SEED",
    "draw_screening_pool",
    "interleave",
    "stratified_sample",
]
