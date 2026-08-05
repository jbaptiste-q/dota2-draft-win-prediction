# Milestone 9: Patch Note Semantic Alignment

Status: **Phase 2 complete, model confirmed (claude-haiku-4-5-20251001) — Phase 3 full pass next**

Milestone 9 assigns semantic labels (direction, magnitude, change_type,
confidence) to individual hero changes pulled from Dota 2 patch notes, as
a precursor to Phase 4 alignment analysis against the M4A working corpus.
Phase 1 (acquisition: 44/45 corpus-observed patch versions fetched,
hero_id → hero_key mapping) is complete and committed. This document is
being written incrementally so decisions are recorded when they happen
rather than reconstructed after the fact.

## Headline: the pass-2/pass-3 ranking reversal is an annotation-boundary
## effect, not a model property

Direction accuracy against the 120-item hand-annotated sample was
recomputed after a relabeling pass on the `rework` category (see
"Rework — three annotation passes" below). The model ranking changed:

| Model | Pass-2 acc. | Pass-3 acc. | Δ | Pass-2 κ | Pass-3 κ | Δ |
| --- | --- | --- | --- | --- | --- | --- |
| claude-haiku-4-5-20251001 | 0.658 | 0.658 | +0.000 | 0.528 | 0.504 | −0.025 |
| claude-sonnet-5 | 0.617 | 0.667 | +0.050 | 0.476 | 0.512 | +0.036 |
| claude-fable-5 | 0.700 | 0.633 | −0.067 | 0.575 | 0.462 | −0.112 |

**No model's predictions changed between pass 2 and pass 3.** The three
models were called once per change and cached; every pass-3 number above
is the same frozen set of model outputs re-scored against a revised human
label. The entire ranking change — Fable going from best to worst, Sonnet
improving, Haiku unmoved — is a property of where the annotator drew the
`rework` boundary, not of anything the models did differently. Fable's
pass-2 lead came from agreeing with the annotator's original, broader,
later-rejected sense of `rework`; when the boundary narrowed (see rule
below), Fable's `rework` calls on the reclassified items became wrong far
more often than they became right (net −8 of 22 relabeled items: 3 newly
correct, 11 newly wrong). Supporting evidence — Fable's pass-3 confusion
matrix (rows = revised human label, columns = Fable's frozen prediction),
where the `rework` column still catches items the revised labels call
`buff` (6) or `neutral` (7):

```
            buff     nerf  neutral   rework  unclear
    buff       44        1        0        6        1
    nerf        6       29        1        2        2
 neutral        3        4        1        7        5
  rework        4        1        0        2        0
 unclear        1        0        0        0        0
```

Fable is still calling many `buff`/`neutral` items `rework` under the
narrow definition — consistent with pattern-matching on structural-sounding
language rather than tracking the annotator's actual (now narrower)
boundary.

## Annotation protocol under-specification

Two of the four label fields turned out to be under-specified in the
original annotation guide used for the Step 2A model-selection
experiment (120 hand-annotated changes, `claude-haiku-4-5-20251001`,
`claude-sonnet-5`, `claude-fable-5`). Both failures share the same root
cause: the guide gave a category definition but no anchoring examples,
so the human annotator's and the models' implicit scales never aligned.

### Magnitude

All three models scored 22.5–29.2% against a 72.5% majority-class
baseline, κ ≈ 0 for all three. Dropped from Milestone 9; Phase 4 uses
direction only. Full writeup: `docs/findings/2026-08-05_m9_magnitude_dropped.md`.

### Rework — three annotation passes

The `rework` direction category went through three passes on the same
120-item sample before it stabilized:

1. **Pass 1** (initial annotation): `rework` was not applied at all —
   every change was forced into buff/nerf/neutral/unclear, with no
   category available for structural changes.
2. **Pass 2** (correction pass): `rework` was introduced and applied
   over the raw text, but without an operational definition of what
   qualified. Produced 29 `rework` labels (24.2% of the sample).
3. **Pass 3** (recount, completed 2026-08-05): re-reviewed all 29
   pass-2 `rework` labels against an explicit rule adopted after
   comparing pass-2 labels to independent model output:

   > Keep `rework` only if the change alters HOW the ability or hero
   > works — i.e. it cannot be fully described as "the same thing,
   > stronger or weaker." Downgrade to buff/nerf/neutral if it is: a
   > pure numeric adjustment, a UI or display change, the addition or
   > removal of an effect of a kind that already existed, or the
   > extension of an existing effect to another unit.

   Motivated by a review of the 10 pass-2 `rework` items with the most
   consistent model disagreement, where several items had all three
   models independently converge on the same non-rework label (e.g. a
   minimap icon addition unanimously called `neutral`) — a stronger
   signal than any single model's disagreement, suggesting the pass-2
   category boundary was too broad rather than the models being wrong.
   22 of 29 items were downgraded (7 remained `rework`); the submitted
   file initially used `remake` as a typo for `rework` on 7 rows,
   confirmed and corrected before merging.

**Model outputs were withheld throughout all three passes** — the
annotator did not see any model's answer before submitting each pass.

Majority-class baseline shifted with the relabeling: pass-2 `buff`
35.8% (43/120) → pass-3 `buff` 43.3% (52/120). All three models remain
comfortably above baseline in both passes.

## Model selection: claude-haiku-4-5-20251001

Haiku vs. Fable direction accuracy was tested both passes:

| | Pass-2 | Pass-3 |
| --- | --- | --- |
| acc(haiku) vs acc(fable) | 0.658 vs 0.700 | 0.658 vs 0.633 |
| diff (fable − haiku) | +0.042 | −0.025 |
| McNemar exact p | 0.267 | 0.508 |
| Bootstrap 95% CI on diff | [−0.017, 0.100] | [−0.075, 0.025] |

The three models are statistically indistinguishable on direction: the
point estimate flips sign between passes and neither McNemar test reaches
significance. With model quality not separating them, the choice for the
Phase 3 full pass fell to determinism, cost, and latency:

- **Determinism**: Haiku is the only one of the three whose sampling is
  actually controllable. `claude-sonnet-5` and `claude-fable-5` reject
  non-default `temperature`/`top_p`/`top_k` unconditionally (confirmed
  against the Anthropic API directly and against published docs, not
  assumed) — their outputs come from undocumented default sampling with
  no reproducibility guarantee outside the on-disk label cache. Haiku's
  `temperature=0` is honored.
- **Cost and latency**: Haiku used ~3x fewer output tokens per call than
  Fable in the Step 2A comparison (adaptive-thinking overhead on Fable),
  and needed no `max_tokens` workarounds.
- Haiku also happens to be the only model whose accuracy was unmoved by
  the pass-2→pass-3 relabeling (0.658 → 0.658) — not part of the
  decision basis above, but consistent with it not being especially
  sensitive to where this particular category boundary sits.

**Decision: `claude-haiku-4-5-20251001`, temperature=0, for the Phase 3
full labeling pass over all 10,713 flattened changes. Direction only —
magnitude is dropped (see above).**
