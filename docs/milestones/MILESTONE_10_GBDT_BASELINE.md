# Milestone 10: GBDT Baseline Recovery Check

Status: **complete — no candidate promoted**

Milestone 10 tested whether a gradient-boosted-tree model, given the exact
same B1 pick-presence feature contract as the frozen draft-only candidate,
recovers predictive signal a linear model cannot. It replaces argument with
measurement for the README's "why not gradient boosting" claim. Neither
outcome changes the frozen candidate: this milestone is evaluative, not a
promotion.

## Frozen inputs

| Contract | Value |
| --- | --- |
| Working corpus | `m4a-tier1-tier2-2022q1-2026q1-working-v1` |
| M4B.5 build (reference source) | `d90302404883e5ba7283c00e88d7d922f2b76e771630013acf9632ac20639e8b` |
| Config | `configs/modeling/m_gbdt_baseline.json` (fingerprint `68d9ac0e…2138f3d`) |
| Frozen reference candidate | `frozen_b1` (B1 pick-presence, linear) |
| Prior reference | `canonical_b0` (empirical base rate) |
| Selection build | `c6421159…86959de6` |
| Q4 gate build | `ceb1cf93…8ef41bf66` |

Calibration `[2025-10-01, 2026-01-01)` was used only for the Q4 gate itself,
exactly as pre-registered; the sealed test `[2026-01-01, 2026-04-01)` was
never opened.

## Method

Same 20,087 pre-2025-10-01 games, same B1 pick-presence feature contract
(hero one-hot indicators, Radiant/Dire sides, no bans/team/patch/player
context), same seven rolling-origin folds as M4B.5/M8 (2024-Q1 through
2025-Q3, expanding window from 2022-01-01), same evaluation code path.

Four LightGBM candidates were pre-registered: `num_leaves ∈ {15, 31} ×
learning_rate ∈ {0.05, 0.1}`, near-default otherwise (`min_child_samples=20`,
no feature/bagging subsampling, no L1/L2, `max_depth=-1`) — a baseline check,
not a tuning exercise. Every fit uses chronological-tail early stopping (last
10% of the fit window by time, monitoring `binary_logloss`, up to 1,000
rounds), applied identically to the 28 fold-selection fits and the single
final pre-Q4 refit.

Selection ranked the four candidates by pooled log loss on 2025-Q1 through
2025-Q3 only — 2025-Q4 was not read during selection. The selected candidate
was then refit once on all 20,087 pre-Q4 rows and evaluated once against Q4,
gated the same way M8's embedding candidates were: point estimate and 95%
upper confidence bound both below zero, against **both** `canonical_b0` and
`frozen_b1`, via a 1,000-replicate `source_match_id`-grouped paired
bootstrap.

## Result: selection

| Candidate | num_leaves | learning_rate | Recent pooled log loss | Recent pooled Brier |
| --- | ---: | ---: | ---: | ---: |
| `gbdt_leaves31_lr0p05` (selected) | 31 | 0.05 | 0.688278 | 0.247578 |
| `gbdt_leaves15_lr0p05` | 15 | 0.05 | 0.688820 | 0.247845 |
| `gbdt_leaves15_lr0p1` | 15 | 0.1 | 0.688995 | 0.247931 |
| `gbdt_leaves31_lr0p1` | 31 | 0.1 | 0.689815 | 0.248342 |
| frozen B1 (reference) | — | — | 0.684171 | 0.245540 |
| canonical B0 (reference) | — | — | 0.692793 | 0.249823 |

Every candidate beats the prior on pooled development folds but trails the
frozen linear candidate; ranking and margins are stable across the grid,
with no candidate close to B1.

## Result: Q4 readiness gate — not qualified

`gbdt_leaves31_lr0p05` refit on all 20,087 pre-Q4 rows (best iteration 77),
evaluated once on the 1,089 Q4 rows:

| 2025-Q4 | Log loss | Brier score |
| --- | ---: | ---: |
| GBDT candidate | 0.697705 | 0.252176 |
| Frozen B1 | 0.698246 | 0.252450 |
| Canonical B0 (prior) | 0.693115 | 0.249984 |

Paired 95% intervals, candidate − reference:

| vs. | Log loss | Brier |
| --- | --- | --- |
| canonical B0 | +0.004590 `[−0.002761, +0.012188]` | +0.002192 `[−0.001438, +0.005959]` |
| frozen B1 | −0.000541 `[−0.005983, +0.004677]` | −0.000275 `[−0.002921, +0.002312]` |

The candidate does not beat the prior (point estimate already positive) and
its edge over frozen B1, though favorable in point estimate, has a 95%
interval spanning zero — neither leg of the gate passes. The candidate is
statistically indistinguishable from the frozen linear model on Q4, not
measurably worse than the prior — both statements matter for how this result
should be read.

## Why: tree capacity finds nothing beyond the linear fit

The GBDT and the frozen linear candidate land within noise of each other on
Q4 despite very different model classes. Combined with Finding 2 — where
pairwise hero-embedding interactions collapsed to zero under every
pre-registered penalty — this is a second, independent line of evidence
against recoverable nonlinear or interaction structure in this feature
contract at this sample size: two structurally different mechanisms for
capturing interactions (learned low-rank embeddings, tree splits) both
converge back to the additive fit.

## Artifacts

Local, git-ignored:

- `models/gbdt_baseline/build_c6421159…86959de6/` (selection stage):
  `fold_predictions.parquet`, `selection_evaluation.json`,
  `selection_manifest.json`, `selection_report.md`.
- `models/gbdt_baseline/build_ceb1cf93…8ef41bf66/` (Q4 gate):
  `q4_predictions.parquet`, `q4_readiness.json`, `q4_manifest.json`,
  `q4_report.md`.

## Validation

- Complete active offline suite: **506 passed** (unchanged — this milestone
  added no dedicated unit tests; correctness rests on reusing
  `draft_ai_modeling`'s existing tested primitives — `DraftFeatureTransformer`,
  `evaluate_probabilities`, `grouped_bootstrap_confidence_intervals`,
  `paired_method_bootstrap_comparison` — and on every pinned source/reference
  artifact's SHA-256 being verified before it is read).
- Python compilation and repository hygiene: passed.
- Q4 rows read during selection: **0**. Locked 2026-Q1 rows opened: **0**.
- Authenticated API requests: **0**. Model serialization: **none**.

## Completion

Milestone 10 is complete. `b1_full_uniform_c0p01` remains the frozen
development candidate; the GBDT baseline is documented as an evaluated,
not-promoted direction. No further modeling stage is opened by this
milestone.
