# Milestone 9: Patch Note Semantic Alignment

Status: **complete — labeling pipeline and evaluation delivered; Phase 4 not run**

## 1. What this milestone produced

M9 set out to align Dota 2 patch notes with the M4A match corpus, to test
whether patch-driven hero changes explain shifts in professional pick
rates. It produced a working acquisition → flattening → LLM-labeling
pipeline, a blind model-selection evaluation of that pipeline, and a full
label set over the corpus's entire observed patch history. It did not
produce an alignment result — Phase 4 is not run; see §5 for why.

**Phase note:** the evaluation originally planned as a separate Phase 3
was folded into Phase 2 as its model-selection step, since evaluating
label quality has to happen before committing to a full labeling run, not
after. "Full pass" below is what was Phase 2 Step 3.

## 2. Pipeline: acquisition → flatten → labeling

| Stage | Result |
| --- | --- |
| Acquisition | 44/45 corpus-observed patch versions fetched; `'7.4'` does not exist upstream |
| Hero mapping | 126 mapped (125 frozen vocabulary + 1 corpus-confirmed addition, Kez); 1 unmatched (Largo) |
| Flatten | 10,713 atomic hero changes: ability 6,904, talent 1,970, hero 1,521, general 318 |
| Unmapped-hero changes | 70: hero_id 1961 (Valve feed placeholder, not a real hero) 48, hero_id 155 (Largo) 22 |

Labeling setup: temperature=0, four-field JSON schema (direction,
magnitude, change_type, confidence), one call per change, cached on
`(change_uid, model_id, prompt_version)`.

## 3. Model selection

120 changes, stratified by scope plus 9 targeted additions (to guarantee
at least 10 `rework` and 10 `neutral` examples), hand-annotated blind —
model outputs withheld until annotation was committed. Annotated twice:
pass 2 applied `rework` without an operational rule; pass 3 re-reviewed
every pass-2 `rework` label against an explicit rule adopted after
comparing pass-2 labels to independent model output:

> Keep `rework` only if the change alters HOW the ability or hero works —
> i.e. it cannot be fully described as "the same thing, stronger or
> weaker." Downgrade to buff/nerf/neutral if it is: a pure numeric
> adjustment, a UI or display change, the addition or removal of an
> effect of a kind that already existed, or the extension of an existing
> effect to another unit.

| Direction accuracy | Pass 2 | Pass 3 | Δ |
| --- | --- | --- | --- |
| Haiku 4.5 | 0.658 | 0.658 | +0.000 |
| Sonnet 5 | 0.617 | 0.667 | +0.050 |
| Fable 5 | **0.700** | 0.633 | −0.067 |

**No model's predictions changed between pass 2 and pass 3.** All three
models were called once per change and cached; every pass-3 number above
is that same frozen set of model outputs re-scored against a revised
human label. The entire ranking change — Fable going from best to worst,
Sonnet improving, Haiku unmoved — is a property of where the annotator
drew the `rework` boundary, not of anything the models did differently.
That is the whole finding. Neither ranking is significant at n=120
(McNemar p=0.267, p=0.508; bootstrap CI spans zero both times).
**Magnitude was dropped**: all three models scored 22.5–29.2% against a
72.5% baseline, κ≈0 — see
[`docs/findings/2026-08-05_m9_magnitude_dropped.md`](../findings/2026-08-05_m9_magnitude_dropped.md).

Haiku was chosen for the full pass on determinism and cost, not measured
quality. Determinism was verified against the API and the published docs
rather than assumed: Sonnet 5 and Fable 5 reject non-default
`temperature`, `top_p`, and `top_k` unconditionally (confirmed both by
direct API error text and by Anthropic's documentation), so Haiku's
`temperature=0` is the only one of the three actually honored. Haiku also
used markedly fewer output tokens per call in this comparison — 4,131
across 120 calls versus Fable's 17,190, a 4.2x difference — from Fable's
adaptive-thinking overhead.

## 4. Full pass

10,708 of 10,713 changes labeled (99.95%) with `claude-haiku-4-5-20251001`,
direction only. 5 permanent failures: the same malformed response on
repeated identical calls, a genuine model formatting quirk rather than a
transient error.

The first full run surfaced a parser bug: the model sometimes
self-corrects mid-response ("wait, let me reconsider" plus a second JSON
block), and the parser treated the whole response as one document and
failed instead of recovering the corrected answer — 22 of that run's 81
initial failures were this pattern. Fixed to try every JSON candidate in
the response, last to first, before this final pass.

Direction distribution: buff 4,830, nerf 3,643, unclear 1,435, neutral
410, rework 390.

## 5. Scope and known gaps

**Phase 4 (alignment analysis) is not run.** A hero's pick rate moves
because it was changed, because a counter was nerfed, because a partner
was buffed, or because team preferences drifted — these are not
separable in this data. This milestone's output is the labeling pipeline
and its evaluation, not an alignment result.

Patches `7.40`, `7.40b`, `7.40c`, `7.41`, `7.41a` are below the
sample-size threshold outside the sealed window (31 rows or fewer) and
would be excluded from any Phase 4 analysis on those grounds — see
[`docs/incidents/2026-08-04_sealed_window_metadata_query.md`](../incidents/2026-08-04_sealed_window_metadata_query.md).

Largo (hero_id 155) is unmapped: its first patch-notes appearance is
`7.40b` (2025-12-23), 9 days before the sealed window opens, and that
patch has 0 corpus rows outside the seal — effectively no readable match
data regardless of the mapping gap.

1,435 of 10,708 labels (13.4%) are `unclear` — the model's own
lowest-confidence bucket, not a defect to resolve before any future
Phase 4 work.
