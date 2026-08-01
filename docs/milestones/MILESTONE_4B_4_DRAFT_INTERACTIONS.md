# Milestone 4B.4: Draft Interaction Recovery Gate

Status: **complete — no interaction candidate qualified**

Milestone 4B.4 asked one final bounded modeling question:

> Do explicit hero synergies and counters add material, temporally stable
> predictive value beyond the frozen B1 pick-presence model?

The answer is **no under the pre-registered gate**. Both interaction
candidates remained better than the empirical-prior B0 on pooled 2025
development games, but neither improved on the frozen B1. The stronger
candidate was slightly worse than B1 on pooled log loss and Brier score and
regressed in five of seven rolling quarters.

The experiment therefore stopped as designed. It produced no 2025-Q4 or
2026-Q1 predictions, did not calibrate or serialize an interaction model, and
made no authenticated API request.

## Product decision

No further model family or hyperparameter search should be added now.

- Retain `b1_full_uniform_c0p01` as the honest development candidate.
- Do not promote either C1 interaction model.
- Do not present C1 coefficients as recommendation evidence.
- Keep 2026-Q1 sealed because the M4B.3 readiness gate remains failed.
- Move the next project decision toward a demonstrable product vertical slice,
  with model limitations visible, rather than another open-ended modeling
  milestone.

This is a useful negative result: the most product-relevant missing-signal
hypothesis was tested directly, without turning the repository into a model
catalog.

## Frozen lineage

| Contract | Value |
| --- | --- |
| Working corpus | `m4a-tier1-tier2-2022q1-2026q1-working-v1` |
| Corpus rows / source matches | `23,123 / 11,664` |
| M4A build | `2c8c8d1ad87eb711cf474a4cf48b9dc2ad85d2f876b3b9c4c6f8a4d0e8a37e0b` |
| Split fingerprint | `dcb1227db92e585d3faab3a435a02aac2e9cb81da44d79bbcf3d7c353cc06fd1` |
| M4B.2 build | `a05b2792e3096869d10d7b58339542ceb3bfcf96810a6357520bacc8ac711456` |
| Frozen B1 candidate | `b1_full_uniform_c0p01` |
| Frozen B1 fingerprint | `cc74f23fbd16e6ff6f5a3e2598cd9d326b78abee860bfceeb569154c0c77837e` |
| M4B.3 negative-result build | `3f768bb13f0b447bcf6704086f00c28f4652a21e467089d3549060ad3ab64a5c` |
| M4B.4 config fingerprint | `4662f98726c8d761785573eff7da76f6fbea3d39730c88c31b029bc2cd1fb701` |
| M4B.4 config file SHA-256 | `0ea91985ce431ab9e84f8e03eab5bce37a90250568a62a26a5b763fa70fdf293` |
| M4B.4 build fingerprint | `9d81434cbaaf5a977479a777b0cdcaf04e8f67458f0f16fe51eeb017481f9112` |
| M4B.4 manifest SHA-256 | `726e251a03f67e0b31979743d0bb542c23016c42268040837f500f0e66af5255` |

M4B.4 hash-verifies the M4A corpus/split, the M4B.2 reference predictions and
selection, and only the compact M4B.3 negative-result evidence. Its config
does not expose an M4B.3 Q4 prediction path.

## Pre-registered experiment

The feature representation was fixed before fitting:

- all B1 side-relative pick-presence main effects;
- unordered same-team pick pairs, emitted separately for Radiant and Dire;
- ordered Radiant-hero-versus-Dire-hero counter pairs;
- minimum support of 50 past-only training games;
- unsupported or unseen interactions ignored and audited;
- no bans, slots, patch, team, tournament, first-pick, or draft-order feature.

Support is computed only from each rolling fold's training inputs and never
from targets or evaluation rows.

Exactly two full-history, uniformly weighted L2 logistic candidates were
allowed:

| Candidate | `C` | Fingerprint |
| --- | ---: | --- |
| `c1_pick_interactions_c0p001` | `0.001` | `121805e52f5469741e7342036069684112277375a73a6e1eb3d481c03d64c6e4` |
| `c1_pick_interactions_c0p01` | `0.01` | `eef9f6e86b1391d730f1022de055635aa9bf70761a4302f526686b644889456d` |

No support-threshold search, feature-family search, nonlinear challenger, or
automatic tuning was performed.

## Temporal boundary

The seven existing expanding folds were reused:

| Evaluation | Past-only fit rows | Evaluation rows |
| --- | ---: | ---: |
| 2024-Q1 | 7,190 | 2,510 |
| 2024-Q2 | 9,700 | 1,712 |
| 2024-Q3 | 11,412 | 1,837 |
| 2024-Q4 | 13,249 | 1,351 |
| 2025-Q1 | 14,600 | 2,209 |
| 2025-Q2 | 16,809 | 1,814 |
| 2025-Q3 | 18,623 | 1,464 |

The ranking scope remained the 5,487 games from 2025-Q1 through 2025-Q3.
The four 2024 folds were stability gates and diagnostics.

Before any window was selected, the runner masked:

- 1,089 calibration-period targets; and
- 1,947 locked-test targets.

Neither reserved role reached the feature transformer, estimator, metrics, or
artifact writer.

## Qualification policy

A candidate had to pass every gate:

1. lower log loss and Brier score than B1 and B0 in each of 2025-Q1, Q2,
   and Q3;
2. at least `0.002` lower pooled 2025 log loss than B1;
3. lower pooled Brier score than B1 and both pooled proper scores below B0;
4. paired 95% source-match bootstrap upper bounds below zero versus B1 for
   log loss and Brier score;
5. seven-fold mean log loss no worse than B1; and
6. no single-fold log-loss regression greater than `0.01`.

The paired bootstrap used 1,000 deterministic resamples of
`source_match_id`, seed 42.

## Pooled 2025 result

Lower values are better.

| Model | Log loss | Brier score | Log-loss delta vs B1 | Brier delta vs B1 | Qualified |
| --- | ---: | ---: | ---: | ---: | --- |
| Frozen B1 | **0.684171** | **0.245540** | — | — | Reference |
| C1, `C=0.001` | 0.689246 | 0.248051 | +0.005075 | +0.002511 | No |
| C1, `C=0.01` | 0.684891 | 0.245880 | +0.000720 | +0.000339 | No |
| Canonical B0 | 0.692793 | 0.249823 | +0.008622 | +0.004283 | Reference |

Both interaction candidates beat B0, which confirms that pick information
still carries development-period signal. Neither beat the simpler frozen B1,
so the added pair terms did not provide incremental value.

Paired candidate-minus-B1 intervals:

| Candidate | Metric | Difference | Paired 95% interval |
| --- | --- | ---: | --- |
| `C=0.001` | Log loss | +0.005075 | `[+0.003063, +0.007110]` |
| `C=0.001` | Brier score | +0.002511 | `[+0.001515, +0.003516]` |
| `C=0.01` | Log loss | +0.000720 | `[-0.000977, +0.002511]` |
| `C=0.01` | Brier score | +0.000339 | `[-0.000490, +0.001211]` |

The `C=0.001` model is conclusively worse than B1. The `C=0.01` differences
are small and inconclusive, but their point estimates are still in the wrong
direction and the candidate fails the fixed material-improvement threshold.

## Temporal diagnostics

The more competitive `C=0.01` candidate behaved as follows:

| Quarter | C1 log loss | B1 log loss | C1 minus B1 |
| --- | ---: | ---: | ---: |
| 2024-Q1 | 0.690543 | 0.691700 | -0.001157 |
| 2024-Q2 | 0.696824 | 0.692613 | +0.004211 |
| 2024-Q3 | 0.696928 | 0.694210 | +0.002718 |
| 2024-Q4 | 0.692472 | 0.689654 | +0.002817 |
| 2025-Q1 | 0.684024 | 0.684160 | -0.000136 |
| 2025-Q2 | 0.685208 | 0.683557 | +0.001651 |
| 2025-Q3 | 0.685808 | 0.684948 | +0.000860 |

It improved only two of seven quarters. Its seven-fold mean log loss was
`0.690258`, compared with `0.688692` for B1. Its worst single-quarter
regression was `0.004211`, within the safety cap but insufficient to pass the
mean-stability gate.

## Interaction coverage

The vocabulary expanded as more strictly past data became available:

| Evaluation | Total columns | Same-side pairs | Counter pairs | Unsupported evaluation activations |
| --- | ---: | ---: | ---: | ---: |
| 2024-Q1 | 1,723 | 604 | 265 | 97,263 |
| 2024-Q2 | 3,284 | 1,145 | 744 | 58,955 |
| 2024-Q3 | 4,223 | 1,455 | 1,063 | 53,911 |
| 2024-Q4 | 5,294 | 1,764 | 1,516 | 37,799 |
| 2025-Q1 | 6,164 | 2,026 | 1,862 | 62,314 |
| 2025-Q2 | 7,391 | 2,367 | 2,405 | 47,166 |
| 2025-Q3 | 8,465 | 2,679 | 2,855 | 31,591 |

Each same-side pair creates separate Radiant and Dire columns, so the
2025-Q3 matrix contains 5,358 synergy columns, 2,855 counter columns, and 252
B1 main-effect columns.

The large and changing pair vocabulary explains why this apparently simple
feature family adds substantial capacity. The result does not prove that
synergy or counters are absent in Dota 2; it shows that this fixed
support-counted linear representation does not generalize better than B1 on
the available professional corpus.

## Compatibility observation

The first offline run stopped at the reference-alignment gate because the
same match timestamps were represented in different time zones:

- current corpus: UTC;
- pinned M4B.2 Parquet: Asia/Shanghai.

The instants and sample IDs were identical with zero timestamp delta. The
alignment check was minimally corrected to normalize both vectors to UTC
before comparison. No source value, row, split, prediction, or model policy
was changed.

## Implementation

| Path | Responsibility |
| --- | --- |
| `configs/modeling/m4b4_interactions.json` | Exact lineage, two candidates, feature contract, gates, and safety boundary |
| `src/draft_ai_modeling/interaction_config.py` | Strict credential-free config and local lineage verification |
| `src/draft_ai_modeling/interaction_features.py` | Train-only B1-plus-synergy/counter sparse transformer |
| `src/draft_ai_modeling/interaction_selection.py` | Fixed B1/B0 comparison, grouped bootstrap, stability gates, and ranking |
| `src/draft_ai_modeling/interaction_experiment.py` | Offline masking, alignment, fitting, artifact generation, and resume verification |
| `scripts/run_draft_interaction_experiment.py` | Credential-free M4B.4 entry point |
| `tests/test_m4b4_*.py` | Feature, config, selection, leakage, lineage, and orchestration safeguards |

## Generated local artifacts

The content-addressed build remains ignored by Git:

```text
models/m4b4/build_9d81434cbaaf5a977479a777b0cdcaf04e8f67458f0f16fe51eeb017481f9112/
```

| Artifact | SHA-256 |
| --- | --- |
| Development predictions | `c0f88a5f997af675ac8a1a6e57199120452165680bdcb8374796dec2d26920bc` |
| Fold metrics | `b481a0738c50999716cf5c568bc94d75b2b44dff993155a9bfcf512765f1123f` |
| Selection | `7f82fe4a757e41174963b5927cbb5fec6d81b0f7c8059da5d0a89b16330adee7` |
| Feature/support audits | `bf1a8acc889c7ee2c18c02b6ca24a07c39fe5990e739d948dd1885eb24b8d073` |
| Coefficient explanations | `36bd0fd4bceb800bfe972dc70e7eaa5758b791b5f7e71abbac217b610b34f794` |
| Patch diagnostics | `5875a908c47ac4f7db0ebc8deb8c49bedac5cc7a4e2cdb67ec1b8f6b211cbb4c` |
| Local report | `fb18f9ffa02c56026ac7097de8f3f44b9ae8bf22d268d311a2d0a942e2953b66` |

The build contains 25,794 aligned prediction rows: 12,897 games for each of
the two candidates. Re-running the command reused and hash-verified the same
build fingerprint.

## Validation

- M4B.4 focused suite: **38 passed**.
- Complete active offline suite: **322 passed**.
- Python compilation: passed.
- Dependency consistency: passed.
- Repository and credential hygiene: passed.
- Working-tree whitespace validation: passed.
- Authenticated API requests: **0**.
- Q4 target rows used by M4B.4: **0**.
- Q4 transforms / predictions: **0 / 0**.
- Locked-test target rows used: **0**.
- Locked-test transforms / predictions: **0 / 0**.
- Calibration, bundle serialization, or final-model fitting: **none**.
- Non-blocking warning: 16 existing `joblib`/NumPy deprecation warnings in
  serialization tests; no M4B.4 correctness failure.

Commands:

```bash
env LIQUIPEDIA_API_KEY= NO_NETWORK_TESTS=1 \
  .venv/bin/python scripts/run_draft_interaction_experiment.py

env LIQUIPEDIA_API_KEY= NO_NETWORK_TESTS=1 \
  .venv/bin/python -m pytest -q
```

## Completion

M4B.4 is complete. The bounded interaction hypothesis was rejected without
opening either reserved period. Under the approved contract, model expansion
now stops instead of escalating to boosting, neural models, larger feature
grids, or another data-acquisition cycle.

The next milestone should make the current Draft AI easier to demonstrate:
define the smallest inference and user-facing vertical slice around the
frozen development candidate, expose its status and limitations, and avoid
claiming that it passed a production-readiness or locked-test gate.
