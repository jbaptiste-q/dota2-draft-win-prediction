# Milestone 4B.1: Draft Baseline Backtesting

Status: **complete — honest negative baseline result**

Milestone 4B.1 fit and compared the four predeclared Draft AI baselines. It
used development data only. No model passed the complete temporal-stability
gate, so no final champion was selected and no weak model was promoted.

## Product question

This stage answers a narrow question that directly advances the Draft
Assistant:

> Do professional hero picks, bans, or per-team draft slots provide a stable
> out-of-time win-probability improvement over an empirical-prior baseline?

The stage does not add data-platform infrastructure, call Liquipedia, train a
nonlinear model, calibrate probabilities, open the locked test, or implement a
recommendation engine.

## Frozen inputs

| Contract | Value |
| --- | --- |
| Working corpus | `m4a-tier1-tier2-2022q1-2026q1-working-v1` |
| Corpus interval | `[2022-01-01T00:00:00Z, 2026-04-01T00:00:00Z)` |
| Corpus rows | 23,123 games |
| Source matches | 11,664 |
| M4A build | `2c8c8d1ad87eb711cf474a4cf48b9dc2ad85d2f876b3b9c4c6f8a4d0e8a37e0b` |
| Split fingerprint | `dcb1227db92e585d3faab3a435a02aac2e9cb81da44d79bbcf3d7c353cc06fd1` |
| M4B config fingerprint | `fc9ec3eae2fa9a888c60e02746f10c0747e79fdbd69bd81136192ec5e6f2e142` |
| M4B build fingerprint | `391418b8096620924b75c09f518b94ba304fbf5d02a16dc94af7eb7cd7f3410f` |

The incomplete 2026-Q2 cache remains excluded. The July 2026 pilot remains
noncontiguous and excluded.

## Leakage boundary

The runner verifies the M4A corpus, split, and artifact hashes before fitting.
It then masks the target for calibration and locked-test rows before any
modeling window is selected.

| Role | Use in M4B.1 |
| --- | --- |
| Train through 2025-Q2 | Fit the tuning-window models |
| Seven expanding rolling folds, 2024-Q1 through 2025-Q3 | Temporal backtesting |
| 2025-Q3 tuning | Development comparison |
| 2025-Q4 calibration | No fit and no prediction |
| 2026-Q1 locked test | No fit and no prediction |

Every feature transformer is fit again on the past-only training rows for its
own window. Series are grouped by `source_match_id`, and uncertainty is
estimated with 1,000 deterministic source-match bootstrap replicates.

## Baselines

| ID | Input | Model |
| --- | --- | --- |
| B0 | No draft features | Training empirical prior |
| B1 | Side-relative pick presence | Fixed L2 logistic regression |
| B2 | Side-relative pick and ban presence | Fixed L2 logistic regression |
| B3 | Canonical per-team pick and ban slots | Fixed L2 logistic regression |

All logistic baselines used the frozen M4A parameters: `C=1`,
`class_weight=None`, `max_iter=2000`, L2 penalty, `liblinear`, and random seed
42. There was no hyperparameter search.

## Tuning result

Lower log loss and Brier score are better.

| Baseline | Log loss | Brier | ROC-AUC | Accuracy | ECE |
| --- | ---: | ---: | ---: | ---: | ---: |
| B0 | 0.692682 | 0.249767 | 0.5000 | 0.5198 | 0.0126 |
| B1 | **0.685971** | **0.246371** | 0.5776 | 0.5464 | 0.0374 |
| B2 | 0.699638 | 0.252471 | **0.5814** | **0.5540** | 0.0848 |
| B3 | 0.781584 | 0.281383 | 0.5537 | 0.5246 | 0.1601 |

B1 improves tuning log loss over B0 by `0.006711` (0.97%) and Brier score by
`0.003397` (1.36%). Its grouped 95% intervals are:

| Metric | B0 95% interval | B1 95% interval |
| --- | --- | --- |
| Log loss | `[0.691976, 0.693427]` | `[0.675914, 0.696389]` |
| Brier score | `[0.249414, 0.250140]` | `[0.241541, 0.251407]` |
| ROC-AUC | `[0.500000, 0.500000]` | `[0.547384, 0.607108]` |

These are per-model intervals, not a paired significance test. They support
uncertainty reporting but do not justify claiming a final win.

## Temporal result

Across all seven rolling folds, no learned baseline beats B0 on mean log loss
or mean Brier score.

| Baseline | Mean rolling log loss | Mean rolling Brier |
| --- | ---: | ---: |
| B0 | **0.693474** | **0.250163** |
| B1 | 0.695773 | 0.251004 |
| B2 | 0.709885 | 0.256666 |
| B3 | 0.865540 | 0.304143 |

B1's per-quarter differences from B0 show the important pattern. Negative is
an improvement.

| Evaluation quarter | Log-loss difference | Brier difference |
| --- | ---: | ---: |
| 2024-Q1 | +0.009230 | +0.003818 |
| 2024-Q2 | +0.011781 | +0.005393 |
| 2024-Q3 | +0.014807 | +0.006728 |
| 2024-Q4 | +0.002179 | +0.000984 |
| 2025-Q1 | -0.008745 | -0.004398 |
| 2025-Q2 | -0.006446 | -0.003245 |
| 2025-Q3 | -0.006711 | -0.003397 |

B1 regresses in all four 2024 folds and improves in all three 2025 folds.
This is evidence that a current-draft model may need a controlled recency or
patch-drift policy. It is not proof that older games are useless: sample size,
patch evolution, hero availability, and fixed regularization all change
together in these expanding-window comparisons.

## Interpretation

- **Picks contain useful signal.** B1 reaches ROC-AUC 0.578 and improves
  probability quality in each 2025 development quarter.
- **The signal is not yet temporally stable.** B1's maximum quarterly
  log-loss regression versus B0 is 0.014807, above the declared 0.01 limit.
- **Bans do not yet improve probability estimates.** B2 slightly improves
  tuning ranking but worsens log loss, Brier score, ECE, and rolling means.
  Its calibration slope of 0.573 is consistent with predictions that are too
  extreme for this evaluation period.
- **Slot-aware B3 overfits.** Its 3,024 columns produce the worst log loss and
  Brier score. Several largest coefficients have fewer than 50 training
  examples, so slot complexity is not justified at this stage.
- **Coefficient evidence remains associative.** The generated signed
  log-odds and support counts are faithful to each linear model, but they do
  not claim causal hero effects.

## Candidate decision

The predeclared development gate requires:

1. better tuning log loss than B0;
2. better mean rolling log loss than B0;
3. better tuning and mean rolling Brier score than B0;
4. no rolling fold more than 0.01 log loss worse than B0; and
5. the simpler baseline when qualifying candidates are practically tied.

No baseline passes all five conditions. The machine-readable result is:

```text
selection_status = no_baseline_passed_all_development_gates
selected_baseline_id = null
not_a_final_champion = true
```

The correct engineering decision is to preserve B1 as the most promising
simple draft representation while refusing to publish it as the champion.

## Implementation

| Path | Responsibility |
| --- | --- |
| `configs/modeling/m4b_baselines.json` | Immutable experiment, fold, metric, and selection policy |
| `src/draft_ai_modeling/experiment_config.py` | Public-contract validation and strict local artifact verification |
| `src/draft_ai_modeling/evaluation.py` | Probability metrics, reliability bins, grouped bootstrap intervals, and coefficient evidence |
| `src/draft_ai_modeling/baseline_experiment.py` | Development-only orchestration, leakage guards, fitting, comparison, and content-addressed outputs |
| `scripts/run_draft_baselines.py` | Offline M4B.1 entry point |
| `tests/test_m4b_config.py` | Contract, path, fingerprint, and role-safety tests |
| `tests/test_m4b_evaluation.py` | Metric, bootstrap, and explanation tests |
| `tests/test_m4b_experiment.py` | End-to-end synthetic orchestration and reserved-role tests |

The public config can be validated in a clean CI checkout without requiring
ignored local model artifacts. The real runner keeps strict local verification
enabled and refuses to fit unless the corpus and M4A hashes match.

## Generated artifacts

Local generated outputs are ignored by Git under:

```text
models/m4b/build_391418b8096620924b75c09f518b94ba304fbf5d02a16dc94af7eb7cd7f3410f/
```

| Artifact | Rows or records | SHA-256 |
| --- | ---: | --- |
| `tuning_predictions.parquet` | 5,856 predictions | `3460623554c7e9e4c64dc22fa20ad14a2887bfb6959cfd34c100a1d0a8076b7e` |
| `rolling_predictions.parquet` | 51,588 predictions | `f87a0f17edcab35b87331e7ee91e179337fbb57692c2e0ed3ad614a8db10ddde` |
| `metrics.json` | 32 evaluations | `f8bfd2e6690fd19f9d2f6e310fc0b30b7debabcd0d682b7fe517dca0174a138f` |
| `baseline_comparison.json` | 4 summaries | `d5b8923f1c5f04468245b4c1a24bf7b78c0ec88ea5f8b87704c3c67bf9cc0d80` |
| `confidence_intervals.json` | 32 evaluations | `8a16b9d667380d75d524257cb8430bf731c870eb977e9723a1a218e43a2ce416` |
| `reliability.json` | 32 evaluations | `65dd587ea311193b62173714e0135a61243242e75c0fa7690d9fbb89017fa16f` |
| `coefficient_explanations.json` | 32 evaluations | `4dff61e4d603d5d30075b39d84a2bbe0888ad6960ab7d545c5b4fe853fb6b049` |

## Validation

- Complete active offline suite: **208 passed**.
- Python compilation: passed.
- Dependency consistency: passed.
- Repository and credential hygiene: passed.
- Staged/working-tree whitespace validation: passed.
- Authenticated API requests: **0**.
- Calibration prediction rows: **0**.
- Locked-test prediction rows: **0**.
- Hyperparameter searches: **0**.
- Serialized models: **0**.

Command executed:

```bash
env LIQUIPEDIA_API_KEY= NO_NETWORK_TESTS=1 \
  .venv/bin/python scripts/run_draft_baselines.py
```

## Completion and next gate

M4B.1 is complete because all four baselines are reproducible, all declared
development metrics and grouped intervals exist, temporal behavior is
measured, linear evidence is auditable, and the project can state exactly why
no model was selected.

The next product-focused decision is whether to approve a narrow M4B.2
experiment around B1: controlled regularization plus recency/patch-drift
comparisons on the existing development folds. B2 should remain an ablation,
and B3 should be dropped unless future evidence justifies its complexity.
Calibration and 2026-Q1 must remain sealed until a development candidate is
frozen.
