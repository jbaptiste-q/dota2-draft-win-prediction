# Dota 2 Draft AI

**How much of a professional Dota 2 match is decided by the draft?**

Less than you would expect. A leakage-controlled model trained on 20,087
professional games fails to beat a constant prior on held-out data. That result
is published inside the product rather than hidden behind it — Draft Lab ships
labelled as an experimental candidate that did not pass its readiness gate.

[**Open Draft Lab →**](https://dota2-draft-lab.jbaptiste-q.workers.dev)

![Draft Lab](site/public/og.png)

---

## Three findings

### 1. Draft-only win prediction sits at the noise floor

Fit on 20,087 games before 2025-10-01, evaluated on the reserved 2025-Q4 window:

| 2025-Q4     | Draft model | Empirical prior | Better |
| ----------- | ----------- | ---------------- | ------ |
| Log loss    | 0.69825     | 0.69312          | prior  |
| Brier score | 0.25245     | 0.24998          | prior  |

The candidate was not promoted and the sealed 2026-Q1 test was never opened.

This is close to the realistic ceiling rather than a failure of technique.
Between elite teams, both sides draft competently by definition, so hero
composition carries little of the outcome signal — team strength does, and team
identity is deliberately excluded from the feature set.

### 2. Hero embeddings collapse to zero — forced open, they show no role structure

A low-rank interaction model — one embedding vector per hero, pairwise dot
products as within-side synergy and cross-side counters — was pre-registered as
nine candidates (`embedding_dim ∈ {4, 8, 16} × L2 ∈ {0.01, 0.1, 1.0}`). None
qualified: every candidate's embeddings converged to within `5.6e-5` of zero,
and the best of the nine still lost to the frozen draft-only candidate
(+0.000397 log loss, 95% CI `[-0.001164, +0.001880]`, inside the fail region).
`v = 0` is a stationary point of the interaction gradient at every
pre-registered penalty; the signal only escapes zero roughly 3x below the
weakest setting tested.

![Hero embedding projection](docs/assets/hero_projection.png)

A descriptive-only refit at that escape point (never gated, never promoted)
produces this 2D projection. Role clusters do not emerge. 123 of 125 heroes
sit at embedding norm under 0.2; the two that don't — Tiny (0.297) and
Pangolier (0.263) — have nearest neighbours with nothing in common
functionally. Tiny's three closest vectors are Chen, Shadow Shaman, and
Omniknight, all supports, none resembling a strength core. The strongest
recovered synergy pair is Puck–Tiny (dot product 0.051, 273 training games on
the same side, 364 opposing); the strongest counter is Pangolier–Tiny (−0.039,
603 opposing-side games). Both top pairs involve the same two outlier heroes —
what structure is recoverable is dominated by whichever embeddings happened to
escape zero, not by a broad interaction signal across the roster. Tiny and
Pangolier are also the two most-picked heroes in the corpus (5,736 and 4,655
picks against a median of 1,662) — the residual signal that survives
regularization concentrates on the two heroes with the most training exposure,
not on two functionally distinct roles. It reads less like emergent structure
and more like a frequency artifact: enough games to pull an embedding off
zero, not enough interaction signal for the result to mean anything
role-specific.

### 3. A model ranking can be an artifact of where you draw a category line

10,713 hero changes were extracted from official patch notes and labelled by an
LLM. Before the full pass, three candidate models were compared against 120
hand-annotated examples, with model outputs withheld until annotation was
complete.

Two things came out of it.

**The magnitude dimension was dropped.** All three models scored 22.5–29.2%
against a 72.5% majority-class baseline, with Cohen's κ indistinguishable from
zero. The annotation guide gave concrete rules for direction but no anchoring
for minor versus major, so the annotator's scale and the models' scales never
aligned. The label was removed rather than repaired.

**The ranking reversed when one category definition was tightened.** The
`rework` category was initially applied without an operational rule. After
adopting an explicit one — retain `rework` only where the change alters *how*
an ability works, not where it can be described as the same mechanic being
stronger or weaker — 22 of 29 labels moved.

| Direction accuracy | Broad definition | Narrow definition |
| ------------------- | ------------------ | -------------------- |
| Haiku 4.5           | 0.658               | 0.658                 |
| Sonnet 5             | 0.617               | 0.667                 |
| Fable 5              | **0.700**           | 0.633                 |

Model predictions were frozen across both passes. The best model became the
worst without a single prediction changing. What looked like a capability
difference was a moving measurement.

Neither ranking is significant at n=120 — McNemar p=0.267 and p=0.508, with the
bootstrap interval spanning zero in both directions. Haiku was chosen for the
full pass on determinism and cost instead: it is the only one of the three that
accepts `temperature=0` at all, since Sonnet 5 and Fable 5 reject non-default
sampling parameters outright.

Full pass: 10,708 of 10,713 changes labelled (99.95%), five permanent parse
failures traced to a reproducible formatting quirk rather than transient error.

---

## What Draft Lab does

Assemble a completed 5v5 draft and the service returns complementary Radiant and
Dire probabilities, the exact signed log-odds contribution of all ten heroes, and
a comparison against one user-chosen hero replacement. Every response carries the
model cutoff, its lineage, and its failed readiness gate.

It does not rank heroes, suggest a next pick, read partial drafts, or claim
causation. Bans, draft order, roles, lanes, patch, team, and player context are
all outside v1.

---

## Method

**Leakage control.** Grouped chronological splits by `source_match_id`,
transformers refit inside each fold, forbidden columns enforced in code, and a
locked test window that has never been opened. A sealed-window boundary rule is
enforced at the repository level; two violations were caught, recorded, and are
documented in `docs/incidents/`.

**Why not deep learning.** 23k games and 125 heroes is far too little for a
transformer to beat a regularized linear model with low-rank interactions, and
the linear form is what makes the per-hero contribution breakdown in Draft Lab
exact rather than approximate. Gradients are hand-derived in numpy; there is no
deep-learning framework in the dependency tree.

**Reproducibility.** Immutable raw cache, SHA-256 fingerprints chaining raw →
normalized → supervised → model, content-addressed build directories, and an
offline test suite that blocks sockets and DNS.

---

## Data

23,123 eligible professional games across 11,664 matches, 2022-Q1 through
2026-Q1, from the official Liquipedia API — no HTML scraping, rate-limited
acquisition, immutable caching, and a request ledger.

Patch notes come from Valve's `datafeed/patchnotes` endpoint. Raw text is never
committed; only derived labels are.

See [Data Boundaries](data/README.md) for the exact public/local split.

---

## Run locally

Python 3.12.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/run_draft_assistant.py   # http://127.0.0.1:8000
```

Full offline validation:

```bash
env LIQUIPEDIA_API_KEY= NO_NETWORK_TESTS=1 python -m pytest -q
python scripts/check_repository_hygiene.py
```

---

## Repository map

| Path                          | Responsibility                                            |
| ----------------------------- | ----------------------------------------------------------- |
| `src/liquipedia_backfill/`    | Guarded acquisition, cache, ledger, coverage              |
| `src/liquipedia_pipeline/`    | Typed parsing, normalization, Parquet export              |
| `src/draft_training_dataset/` | Canonical supervised-dataset contract                     |
| `src/draft_ai_modeling/`      | Temporal splits, experiments, gates, lineage              |
| `src/draft_ai_assistant/`     | Frozen contracts, inference service, FastAPI, Draft Lab   |
| `src/patch_alignment/`        | Patch-note acquisition and LLM labelling                  |
| `docs/`                       | Engineering log — see the index, not written to be read straight through |

---

## Scope and limitations

The model is an experimental candidate that failed its readiness gate. It is not
a forecasting, betting, or coaching service. Replacement comparisons are
associative, not causal.

Patch alignment covers only versions observed in the working corpus. Patches
7.40 and later have 31 games or fewer outside the sealed window and are excluded
on sample-size grounds — the data exists but is not readable under the sealed
window policy.

Two heroes are unmapped in the patch-note join: one placeholder entry in Valve's
feed that is not a real hero, and Largo, which debuted nine days before the
sealed window opened and therefore has effectively no readable match data.

---

## How this was built

Implementation was done with Claude Code. The experiment design, constraints,
scope decisions, and result review are mine, as are the 120 hand-annotated
labels the LLM evaluation is measured against.
