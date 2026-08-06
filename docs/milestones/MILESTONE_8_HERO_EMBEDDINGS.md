# Milestone 8: Hero Embeddings with Low-Rank Interactions

Status: **complete — no candidate promoted**

Milestone 8 tested whether a low-rank hero-embedding model with pairwise
synergy/counter interaction terms improves on the frozen M4B.2 development
candidate `b1_full_uniform_c0p01`, and produced interpretable hero
embeddings regardless of that outcome. Neither goal changes the frozen
candidate: this milestone is evaluative, not a promotion.

## Frozen inputs

| Contract | Value |
| --- | --- |
| Working corpus | `m4a-tier1-tier2-2022q1-2026q1-working-v1` (23,123 games) |
| M4A build | `2c8c8d1ad87eb711cf474a4cf48b9dc2ad85d2f876b3b9c4c6f8a4d0e8a37e0b` |
| M4B.1 build | `391418b8096620924b75c09f518b94ba304fbf5d02a16dc94af7eb7cd7f3410f` |
| M4B.2 build | `a05b2792e3096869d10d7b58339542ceb3bfcf96810a6357520bacc8ac711456` |
| Split fingerprint | `dcb1227db92e585d3faab3a435a02aac2e9cb81da44d79bbcf3d7c353cc06fd1` |
| Frozen reference candidate | `b1_full_uniform_c0p01` (fingerprint `cc74f23f…c77837e`) |

All three upstream manifests and every pinned artifact hash were verified
before any fitting. Calibration `[2025-10-01, 2026-01-01)` and the locked
test `[2026-01-01, 2026-04-01)` were never read.

## Model

For picks `R` (Radiant) and `D` (Dire), log-odds
`z = b + Σw[R] − Σw[D] + Σ_{i<j∈R} v_i·v_j − Σ_{i<j∈D} v_i·v_j − Σ_{i∈R,j∈D} v_i·v_j`,
fit by penalized cross-entropy with hand-derived gradients and deterministic
full-batch Adam (numpy/scipy only). Nine candidates were pre-registered:
`embedding_dim ∈ {4, 8, 16} × L2 ∈ {0.01, 0.1, 1.0}`, all under the
`full_uniform` history policy matching the frozen candidate, over the same
seven M4B.2 rolling-origin folds (2024-Q1 through 2025-Q3). Qualification
required beating **both** the canonical B0 and the frozen B1 candidate,
strictly in every selection fold and pooled, with a 1,000-replicate paired
`source_match_id` bootstrap 95% upper bound below zero against both
references.

The frozen B1 candidate was refit per fold as the comparison reference; it
reproduced all 12,897 pinned M4B.2 probabilities and B0 priors with maximum
absolute difference **exactly 0.0**.

## Result: no candidate qualified

Every embedding dimension converges to the same pooled metrics at each L2 —
direct evidence embeddings collapsed to zero regardless of `d`:

| L2 | Pooled log loss | Pooled Brier | Beats B0 | Beats frozen B1 |
| ---: | ---: | ---: | --- | --- |
| 0.01 | 0.684568 | 0.245731 | Yes | **No** |
| 0.1 | 0.690806 | 0.248830 | Yes | No |
| 1.0 | 0.692562 | 0.249707 | Yes | No |
| frozen B1 (reference) | 0.684171 | 0.245540 | — | — |
| canonical B0 (reference) | 0.692793 | 0.249823 | — | — |

Best candidate (`emb_d4_l2_0p01`) paired 95% intervals, candidate − reference:

| vs. | Log loss | Brier |
| --- | --- | --- |
| canonical B0 | −0.008225 `[−0.010321, −0.006168]` | −0.004092 `[−0.005136, −0.003071]` |
| frozen B1 | +0.000397 `[−0.001164, +0.001880]` (fails) | +0.000190 `[−0.000584, +0.000924]` (fails) |

All nine candidates fail the frozen-B1 gate; `qualifying_ranking` is empty
and no candidate is selected.

## Why: embeddings collapse to exactly zero

At `v = 0` both the cross-entropy data gradient and the `2·L2·v` penalty
gradient vanish identically, for every `L2 ≥ 0` — `v = 0` is always a
stationary point. It is additionally a *stable* one whenever the local
interaction curvature is smaller than `2·L2`; empirically this held at every
pre-registered `L2 ∈ {0.01, 0.1, 1.0}`, so all nine candidates converge back
to the additive-only model regardless of `d`. This was verified, not
assumed: an extended refit (20,000 iterations, gradient tolerance `1e-9`)
on `emb_d4_l2_0p01` still converges with embedding norm `~5e-8`, and its
final objective agrees with the exact `d=0` fit to `5e-10` — ruling out
premature stopping.

A geometric L2 sweep (`10^-2.0` → `10^-4.0` in half-decade steps) locates
the escape threshold **between `L2=0.01` and `L2≈0.00316`**: at `0.01` the
maximum embedding norm is `5.6e-5` (collapsed); at `0.00316` it jumps to
`0.297`. This means the corpus's pairwise interaction signal is real but
weak — it only survives regularization roughly 3× below the weakest
pre-registered value. `L2=0.01` was not too aggressive by accident; it sits
just past where this particular interaction signal disappears.

## Part B: descriptive-only refit (not a candidate)

One refit at `d=4, L2≈0.00316` (the sweep's first escape point) produced
interpretable hero embeddings, a 2-D PCA projection, top-20 cosine
neighbours per hero, and the top 30 synergy/counter pairs with training
support counts. Its pooled 2025 log loss (`0.682857`) and Brier
(`0.244902`) are **recorded, not claimed**: this penalty was chosen
post-hoc by observing where collapse ends, not pre-registered, and the
refit was never evaluated against a paired bootstrap gate. It is explicitly
marked `descriptive_only: true` throughout and did not influence selection.
Embeddings are identifiable only up to an orthogonal rotation; only
pairwise dot products and relative geometry (neighbours, projection) carry
meaning.

## Artifacts

Local, git-ignored, under `models/m8/build_<fingerprint>/`:
`development_predictions.parquet`, `fold_metrics.json`, `selection.json`,
`reliability.json`, `vocabulary_audits.json`, `experiment_report.md`,
`hero_main_effects.parquet`, `collapse_analysis.json`,
`descriptive_hero_embeddings.parquet`, `descriptive_hero_projection_2d.parquet`,
`descriptive_hero_neighbours.json`, `descriptive_learned_pairs.json`,
`experiment_manifest.json`, `interpretability_manifest.json`.

## Validation

- Complete active offline suite: **463 passed**.
- M8-focused suite (`tests/test_m8_*.py`): config, gradients (analytic vs.
  finite-difference), determinism, unknown-hero leakage boundaries, fold
  role/overlap boundaries, selection gates and tie-break, and end-to-end
  synthetic orchestration.
- Python compilation, dependency consistency, and repository hygiene:
  passed.
- Calibration and locked-test prediction rows: **0**.
- Authenticated API requests: **0**. Model serialization: **none**.

## Completion

Milestone 8 is complete. `b1_full_uniform_c0p01` remains the frozen
development candidate; hero embeddings are documented as an evaluated,
not-promoted direction, with descriptive interpretability artifacts
preserved for future reference. No further modeling stage is opened by
this milestone.

---

## Appendix: descriptive artifacts (added 2026-08-06)

This appendix surfaces specific values from `descriptive_hero_neighbours.json`
and `descriptive_learned_pairs.json` — artifacts already listed under
"Artifacts" above and already covered by "Part B: descriptive-only refit"
— for readers of the top-level README's Finding 2. It changes no
conclusion, gate result, or number recorded elsewhere in this document.

### Nearest neighbours (cosine similarity)

The two heroes with non-negligible embedding norm have nearest neighbours
with no shared functional role:

- **Tiny** (norm 0.297): Chen (1.000), Shadow Shaman (1.000), Omniknight
  (1.000) — all supports, none resembling a strength core.
- **Pangolier** (norm 0.263): Skywrath Mage (1.000), Broodmother (0.999),
  Sand King (0.998) — a ranged intelligence hero, an agility carry, and an
  initiator.

### Top synergy and counter pairs (training support counts)

| Rank | Pair | Dot product | Same-side games | Opposing-side games |
| --- | --- | ---: | ---: | ---: |
| Synergy 1 | Puck – Tiny | 0.051 | 273 | 364 |
| Synergy 2 | Mirana – Tiny | 0.048 | 262 | 252 |
| Synergy 3 | Dawnbreaker – Tiny | 0.048 | 198 | 268 |
| Counter 1 | Pangolier – Tiny | −0.039 | 310 | 603 |
| Counter 2 | Magnus – Tiny | −0.035 | 222 | 270 |
| Counter 3 | Muerta – Pangolier | −0.035 | 199 | 189 |

Every row in both the synergy and counter tables involves Tiny or
Pangolier — the same two heroes that dominate the embedding-norm ranking.
The recoverable "structure" is concentrated on the two most-picked heroes
in the corpus, not distributed across the roster.
