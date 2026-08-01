# Milestone 4B.2: B1 Regularization and Recency

Status: **complete — development candidate frozen**

Milestone 4B.2 tested the smallest useful response to the M4B.1 result:
whether the promising pick-presence model needed stronger regularization,
less historical data, or both.

The selected development candidate is:

```text
candidate_id = b1_full_uniform_c0p01
features = side-relative pick presence
history = all validated rows strictly before each training cutoff
regularization_C = 0.01
result = development candidate, not final champion
```

Calibration and the locked 2026-Q1 test remain sealed.

## Product question

This stage directly answers:

> For a Draft AI intended to generalize to 2026, should matches from 2022–2023
> retain full, reduced, or zero training influence?

No acquisition, data-platform redesign, patch identity feature, context
feature, ban feature, slot feature, nonlinear model, or recommendation code
was added.

## Frozen inputs

| Contract | Value |
| --- | --- |
| Working corpus | `m4a-tier1-tier2-2022q1-2026q1-working-v1` |
| Corpus rows | 23,123 games |
| Corpus interval | `[2022-01-01T00:00:00Z, 2026-04-01T00:00:00Z)` |
| M4A build | `2c8c8d1ad87eb711cf474a4cf48b9dc2ad85d2f876b3b9c4c6f8a4d0e8a37e0b` |
| M4B.1 build | `391418b8096620924b75c09f518b94ba304fbf5d02a16dc94af7eb7cd7f3410f` |
| Split fingerprint | `dcb1227db92e585d3faab3a435a02aac2e9cb81da44d79bbcf3d7c353cc06fd1` |
| M4B.2 config fingerprint | `acf46a96a10acc575020de8cbec3768168e00f13e7916af4184fd32c1c766b91` |
| M4B.2 build fingerprint | `a05b2792e3096869d10d7b58339542ceb3bfcf96810a6357520bacc8ac711456` |

The incomplete 2026-Q2 cache and noncontiguous July 2026 pilot remain excluded.

## Pre-registered experiment

Nine candidates were declared before fitting.

| Factor | Values |
| --- | --- |
| Model | B1 side-relative pick-presence logistic regression only |
| L2 `C` | `0.01`, `0.1`, `1.0` |
| History policy | Full uniform; full history with 180-day exponential decay; trailing 365 days |
| Rolling diagnostics | 2024-Q1 through 2025-Q3 |
| Selection scope | Pooled 2025-Q1 through 2025-Q3 |
| Uncertainty | 1,000 paired `source_match_id` bootstrap replicates |

The history policies represent:

- **full influence:** retain all strictly past professional games uniformly;
- **reduced influence:** retain all games but halve weight every 180 days; and
- **zero old influence:** discard games older than 365 days.

Exponential weights are anchored at each exact training cutoff and normalized
to mean one. This keeps `C` comparable instead of changing regularization
accidentally through total weight scale.

At the 2025-Q3 fit boundary:

| History policy | Physical rows | Effective sample size |
| --- | ---: | ---: |
| Full uniform | 18,623 | 18,623 |
| 180-day exponential | 18,623 | 9,406 |
| Trailing 365 days | 7,211 | 7,211 |

## Selection policy

A candidate had to:

1. beat both the canonical and history-policy-matched B0 on log loss and
   Brier score in each of 2025-Q1, Q2, and Q3;
2. beat both references on the pooled 5,487 development games;
3. have paired 95% upper confidence bounds below zero versus its matched B0
   for both metrics; and
4. rank by pooled log loss, with a `0.002` practical tie favoring full history,
   then soft decay, then a hard window, followed by lower-capacity `C`.

This 2025-focused policy is deliberate because the product targets 2026
drafts. M4B.1 exposed the 2024/2025 difference before this experiment, so the
motivation is disclosed rather than presented as a prospectively untouched
choice. The independent safeguards are the still-unused 2025-Q4 calibration
and 2026-Q1 locked test periods.

## Pooled 2025 results

Lower log loss and Brier score are better. Canonical B0 scores are
`0.692793` and `0.249823`.

| History | `C` | Log loss | Brier | Qualified | Rank |
| --- | ---: | ---: | ---: | --- | ---: |
| Full uniform | 0.01 | **0.684171** | **0.245540** | Yes | 1 |
| Full uniform | 0.1 | 0.684298 | 0.245586 | Yes | 2 |
| Full uniform | 1.0 | 0.685351 | 0.246073 | Yes | 3 |
| 180-day decay | 0.01 | 0.685139 | 0.245983 | Yes | 4 |
| 180-day decay | 0.1 | 0.689777 | 0.248017 | No | — |
| 180-day decay | 1.0 | 0.692722 | 0.249298 | No | — |
| Trailing 365 days | 0.01 | 0.687038 | 0.246940 | Yes | 5 |
| Trailing 365 days | 0.1 | 0.692864 | 0.249432 | No | — |
| Trailing 365 days | 1.0 | 0.701896 | 0.253201 | No | — |

The selected candidate improves pooled 2025 log loss by `0.008622` (1.24%)
and Brier score by `0.004283` (1.71%) versus canonical B0.

Paired candidate-minus-B0 intervals are:

| Metric | Difference | Paired 95% interval |
| --- | ---: | --- |
| Log loss | -0.008622 | `[-0.011448, -0.005737]` |
| Brier score | -0.004283 | `[-0.005674, -0.002857]` |

Both intervals remain below zero across 1,000 grouped resamples of 2,822
professional series.

## Temporal diagnostics

| Quarter | Selected log loss | B0 log loss | Difference |
| --- | ---: | ---: | ---: |
| 2024-Q1 | 0.691700 | 0.696504 | -0.004804 |
| 2024-Q2 | 0.692613 | 0.693153 | -0.000540 |
| 2024-Q3 | 0.694210 | 0.693247 | +0.000963 |
| 2024-Q4 | 0.689654 | 0.693061 | -0.003407 |
| 2025-Q1 | 0.684160 | 0.692830 | -0.008669 |
| 2025-Q2 | 0.683557 | 0.692838 | -0.009282 |
| 2025-Q3 | 0.684948 | 0.692682 | -0.007734 |

The selected model beats B0 in six of seven quarters. Its seven-fold mean log
loss is `0.688692`, versus `0.693474` for B0 and `0.695773` for the original
M4B.1 `C=1` model. Stronger shrinkage therefore resolves most of the earlier
temporal instability without removing old matches.

## Answer about older data

The experiment does **not** support discarding older matches.

- Full-history `C=0.01` is the best pooled 2025 candidate.
- Soft 180-day decay with the same `C` is `0.000968` worse in log loss.
- A hard one-year window is `0.002867` worse.
- All three strongly regularized candidates beat their B0 references, showing
  that current draft signal is real, but full historical coverage provides
  the best overall probability estimate.

The earlier problem was excessive coefficient variance, not simply the age of
the dataset. Older matches remain useful when their associations are strongly
regularized. They also remain essential drift evidence even if a future model
eventually adopts recency weighting.

## Patch diagnostics

Patch was never a feature and never influenced selection. Descriptive metrics
were reported only after candidate selection.

Seven of ten observed patch groups met the 100-game reporting threshold.
Performance varies materially:

- patch `7.39b`: log loss `0.676614`, ROC-AUC `0.6054`;
- patch `7.37e`: log loss `0.680254`, ROC-AUC `0.5952`; and
- patch `7.38`: log loss `0.693555`, ROC-AUC `0.5275`.

This confirms that patch drift remains a product limitation to measure and
communicate. It does not justify adding patch identity to the model before
the locked evaluation.

## Leakage and lineage gates

- M4A and M4B.1 manifests and every pinned artifact were hash-verified.
- The full-history `C=1` candidate reproduced all 12,897 M4B.1 B1 rolling
  probabilities with maximum absolute difference `0.0`.
- Feature vocabularies were fit independently on each effective past-only
  training window.
- Calibration and locked-test targets were masked before modeling-window
  selection.
- No 2025-Q4 or 2026-Q1 predictions were generated.
- No API, acquisition, parser, normalizer, or raw cache dependency exists.

## Implementation

| Path | Responsibility |
| --- | --- |
| `configs/modeling/m4b2_recency.json` | Exact candidate matrix, history policies, source pins, selection gates, and safety boundary |
| `src/draft_ai_modeling/recency_config.py` | Typed public contract and strict local lineage verification |
| `src/draft_ai_modeling/recency.py` | Deterministic history selection, weights, effective sample size, and policy fingerprints |
| `src/draft_ai_modeling/recency_evaluation.py` | Paired series bootstrap and descriptive-only patch metrics |
| `src/draft_ai_modeling/recency_selection.py` | Exact nine-candidate qualification and ranking |
| `src/draft_ai_modeling/recency_experiment.py` | Offline fitting, reproduction gate, artifacts, and manifest |
| `scripts/run_draft_recency_experiment.py` | Credential-free M4B.2 entry point |
| `tests/test_m4b2_*.py` | Config, recency, uncertainty, selection, and orchestration safeguards |

## Generated artifacts

Local outputs remain ignored by Git under:

```text
models/m4b2/build_a05b2792e3096869d10d7b58339542ceb3bfcf96810a6357520bacc8ac711456/
```

| Artifact | Rows or records | SHA-256 |
| --- | ---: | --- |
| `development_predictions.parquet` | 116,073 predictions | `9ec6a96513cbd16113de155b24fee4eb2b8abfc4773d5960c6b0295daf49431b` |
| `fold_metrics.json` | 63 evaluations | `750667c02244ff71c76537698db34ed8024c603d5d892f08ebb0c77adbbbf2fb` |
| `selection.json` | 9 candidates | `120bbb45ee12714f67efb93db89ef5c51b7e60a8d12355188c204a9610ab261b` |
| `reliability.json` | 63 evaluations | `5e03a3e352bde5138938073d11e283e02169c1b4188c3ab90ea8cc58fb33bfb5` |
| `weight_audits.json` | 21 fold-policy audits | `aab88b82e1c9fbd49b22426ffeb4cbf661ffc14c9261ee85bf10426937efc0f1` |
| `coefficient_explanations.json` | 63 evaluations | `1470383a9c1db946576cd193c74a37dad93f50905b1f117059947a3629bd9179` |
| `patch_diagnostics.json` | 10 patch groups | `2bee2a05bdbd59b716e4a268ce00f6d83fcdfb7748216a9c3add8930416725a7` |

## Validation

- Complete active offline suite: **250 passed**.
- M4B.2 focused suite: **42 passed**.
- Python compilation: passed.
- Dependency consistency: passed.
- Repository and credential hygiene: passed.
- Working-tree whitespace validation: passed.
- Authenticated API requests: **0**.
- Calibration prediction rows: **0**.
- Locked-test prediction rows: **0**.
- Dynamic hyperparameter searches: **0**.
- Serialized models: **0**.

Command executed:

```bash
env LIQUIPEDIA_API_KEY= NO_NETWORK_TESTS=1 \
  .venv/bin/python scripts/run_draft_recency_experiment.py
```

## Completion and next gate

M4B.2 is complete. `b1_full_uniform_c0p01` is frozen as the development
candidate, but it is not a final champion or deployable model.

The next bounded stage is M4B.3:

1. refit the frozen estimator configuration on Train plus Tuning;
2. compare no calibrator, sigmoid, and isotonic using only 2025-Q4;
3. freeze one probability-calibration policy; and
4. stop before opening the 2026-Q1 locked test.

No recommendation, API, frontend, or deployment work should begin until the
frozen model bundle passes the locked-test gate.
