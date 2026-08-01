# Milestone 4: Draft AI Modeling Plan

> **Closed modeling record.** Milestone 4A replaced the earlier provisional
> split with the contiguous working corpus through 2026-Q1. M4B.1–M4B.5 then
> completed the approved bounded research program. This document preserves
> that implemented design; it is not the active product roadmap.

Status: **complete — M4B.5 failed Q4 readiness; research closed; locked test remains sealed**
Updated: **2026-08-01**
Canonical input schema: `dota-draft-supervised-v1`
Working corpus: `m4a-tier1-tier2-2022q1-2026q1-working-v1`

## 1. Objective

Milestone 4 built and evaluated the first probability-model candidate for the
flagship AI Draft Assistant:

> Given a completed professional Dota 2 draft, estimate the probability that
> Radiant wins and explain the draft evidence behind that estimate.

This milestone started at the published canonical supervised dataset. It did
not call the Liquipedia API, reinterpret raw payloads, change eligibility, or
modify the normalized and supervised data contracts.

The output was a reproducible, readiness-failed development candidate—not a
readiness-approved forecast, recommendation engine, or automated drafting
agent. M5.3 freezes the supported product around that evidence instead of
reopening research.

## 2. Fixed working corpus

All Milestone 4 experiments pinned this exact component manifest:

| Item | Fixed value |
| --- | --- |
| Historical interval | `[2022-01-01T00:00:00Z, 2026-04-01T00:00:00Z)` |
| Included partitions | `2022-Q1` through `2026-Q1` |
| Liquipedia tiers | Tier 1 and Tier 2 |
| Corpus status | `working_contiguous_prefix` |
| M4A build fingerprint | `2c8c8d1ad87eb711cf474a4cf48b9dc2ad85d2f876b3b9c4c6f8a4d0e8a37e0b` |
| Corpus config SHA-256 | `2c287af2668bd88e02db1fac3a3363d7b1a6f5f12b04c795741832c6bc81030a` |
| Split fingerprint | `dcb1227db92e585d3faab3a435a02aac2e9cb81da44d79bbcf3d7c353cc06fd1` |
| Supervised schema SHA-256 | `4bae8474d0d982c0356bda042ab15739572e97f97b63548e3685c028480872b4` |
| Eligible supervised rows | `23,123` |
| Source matches represented | `11,664` |
| Radiant wins / losses | `11,762 / 11,361` |

This is a fixed modeling corpus, not a claim of complete Dota 2 history.
Every result remains versioned against the nine pinned supervised components.

## 3. Prediction contract and hard semantic limits

### 3.1 Unit of prediction

One sample is one eligible, completed professional game. The prediction point
is after both teams' recorded picks and bans are complete and before gameplay
begins.

The binary target is:

```text
radiant_win = true  when the explicit game winner occupied Radiant
radiant_win = false when the explicit game winner occupied Dire
```

### 3.2 Side-relative representation

The only supported representation is side-relative:

- Radiant pick slots 1–5;
- Dire pick slots 1–5;
- Radiant ban slots 1–7; and
- Dire ban slots 1–7.

Liquipedia's slot numbers are preserved as per-team slots. They are not a
globally interleaved draft sequence.

### 3.3 Unavailable semantics

Explicit first-pick assignment and global draft order are unavailable. They
must not be reconstructed from slot numbers, side, tournament convention, or
assumed Dota draft rules. Milestone 4 therefore cannot measure or explain a
first-pick effect.

### 3.4 Duration policy

`duration_seconds` is a post-game eligibility field and a forbidden model
feature. Duration must never enter training, calibration, explanations,
subgroup definitions, or model selection. Its use in upstream eligibility is
a known selection condition that must be disclosed in the model card.

## 4. Exact temporal split policy

Random row splitting is prohibited. The primary split is chronological,
half-open, UTC-based, and grouped by `source_match_id`.

| Split | UTC interval | Rows | Source matches | Radiant wins | Radiant win rate |
| --- | --- | ---: | ---: | ---: | ---: |
| Train | `[2022-01-01, 2025-07-01)` | 18,623 | 9,254 | 9,445 | 50.717% |
| Validation | `[2025-07-01, 2026-01-01)` | 2,553 | 1,304 | 1,311 | 51.351% |
| Locked test | `[2026-01-01, 2026-04-01)` | 1,947 | 1,106 | 1,006 | 51.669% |
| Total | `[2022-01-01, 2026-04-01)` | 23,123 | 11,664 | 11,762 | 50.867% |

No source match crosses these boundaries in the published release. The split
builder must still assert this invariant and fail if it changes in a future
release.

The validation interval has two fixed internal roles:

| Validation role | UTC interval | Rows | Source matches | Radiant wins |
| --- | --- | ---: | ---: | ---: |
| Tuning | `[2025-07-01, 2025-10-01)` | 1,464 | 781 | 761 |
| Calibration | `[2025-10-01, 2026-01-01)` | 1,089 | 523 | 550 |

Hyperparameters and feature choices are selected using the tuning interval.
The selected estimator is then refit on Train + Tuning (`20,087` rows), and
its probability calibrator is fit only on the `1,089` calibration rows. The
locked test may be evaluated once only after the readiness gate passes and
the experiment decision is frozen.

The changing Radiant win rate is real evidence of temporal distribution
shift. Rows must not be globally rebalanced, and class weights are off by
default because they would alter probability calibration. The large,
newer-patch `2026-Q1` partition is a valuable holdout rather than an
inconvenient test set.

Quarterly rolling-origin checks inside Train and Tuning may be used to assess
stability, but they do not replace the fixed test. Every fold must keep all
games from a source match together and fit transformations using past data
only.

## 5. Feature contracts

Model-specific transformations form a new layer after
`dota-draft-supervised-v1`. They must not be written back into the canonical
dataset.

### 5.1 Core draft-only features

The first model family uses only heroes known at the completed-draft
prediction point.

For every hero `h` in a training-fitted vocabulary:

```text
RP[h] = 1 if Radiant picked h, else 0
DP[h] = 1 if Dire picked h, else 0
RB[h] = 1 if Radiant banned h, else 0
DB[h] = 1 if Dire banned h, else 0
```

This produces a sparse, slot-invariant representation that makes no claim
about global action order.

A separate slot-aware representation one-hot encodes each of the 24 canonical
per-team columns. It may learn that a hero's per-team slot is informative, but
must continue to describe that value as a per-team slot.

All categorical vocabularies and encoders are fit on the applicable training
window only. Unseen heroes or context values map to an explicit unknown token;
test vocabulary is never used to choose columns.

### 5.2 Controlled interaction features

An explainable interaction experiment may add:

- unordered Radiant pick pairs for same-side synergy;
- unordered Dire pick pairs for same-side synergy; and
- side-ordered Radiant-versus-Dire pick pairs for counters.

Frequency thresholds are computed from training inputs only, without looking
at outcomes. Ban interactions are deferred unless simpler pick interactions
show stable value; expanding every possible interaction immediately would add
sparsity and complexity without proving portfolio value.

### 5.3 Context features and ablations

The primary model is draft-only. The following pre-game columns may be tested
only as named ablations:

- `patch`;
- `liquipedia_tier`;
- `radiant_team_key` and `dire_team_key`;
- `tournament`; and
- `series`.

Team and tournament identity can improve in-sample accuracy by memorizing
competitive strength or event structure while weakening generalization. A
context-enhanced model cannot replace the draft-only result unless it improves
out-of-time probability quality and its limitations are explicit.

`match_start_utc` is used for splitting and recency weights, not as a direct
numeric feature in the first model. Nullable patch values use an explicit
missing category; they are not inferred from dates.

### 5.4 Columns that never become features

The following remain identifiers, grouping metadata, targets, or forbidden
post-game fields:

- `sample_id`, `game_key`, `source_game_id`, `source_match_id`, `game_index`;
- `radiant_win`, except as the label;
- winner slot, score, status, result type, and walkover;
- duration;
- first-pick fields; and
- any reconstructed global draft sequence.

## 6. Leakage prevention

Every experiment must pass these gates before fitting:

1. Verify the release, supervised, schema, and Parquet fingerprints.
2. Verify exactly 23,123 unique `sample_id` values.
3. Verify the temporal boundaries and expected split counts.
4. Verify every `source_match_id` belongs to exactly one split.
5. Verify all 24 draft columns are complete.
6. Verify every forbidden column is absent from the fitted feature matrix.
7. Fit vocabularies, rare-category rules, scaling, interaction selection, and
   encoders on past training data only.
8. Keep the test labels inaccessible to tuning, feature selection,
   calibration, and explanation-method choice.
9. Preserve original class frequencies.
10. Fail on unknown schema roles rather than silently including a new column.

When rolling-origin evaluation is used, each fold must rebuild its
transformers. Reusing a vocabulary, target encoding, team statistic, or
frequency threshold learned from a later fold is leakage.

Target encoding is excluded from the first implementation. If introduced
later, it requires ordered, out-of-fold computation. Pregame team-strength
features are also deferred until a past-only sequential definition is
approved.

## 7. Baseline and candidate models

Models are evaluated in increasing order of complexity:

| ID | Model | Purpose |
| --- | --- | --- |
| B0 | Training empirical-prior probability | Honest no-skill probability baseline |
| B1 | L2 logistic regression on side-relative pick presence | Simple, sparse, explainable draft baseline |
| B2 | L2 or elastic-net logistic regression on picks and bans | Quantify whether bans add signal |
| B3 | Regularized slot-aware logistic regression | Test the value of per-team slot positions |
| C1 | Sparse logistic model with supported pick-pair interactions | Completed; did not improve on B1 |
| C2 | Categorical gradient boosting on the 24 draft slots | Deliberately not run after the M4B.4 stop gate |

The empirical prior is learned independently for each training window. It is
not the all-release class rate.

The initial champion should be the simplest model with a repeatable temporal
advantage. M4B.4 showed that explicit supported pairs did not improve the
frozen B1. The approved stop rule therefore excludes C2, neural networks, and
further model-family escalation from this milestone.

Hyperparameter search must be a small, declared grid or deterministic search,
not an open-ended sweep. Complexity, runtime, and number of evaluated
configurations are recorded.

## 8. Patch and recency experiments

Patch drift is central to the product: the locked test consists of newer
`7.35` variants than the development period. Patch should therefore be
treated as a generalization problem, not merely another high-cardinality
category.

The implemented pre-registered comparisons were:

1. all available history with uniform sample weight;
2. all history with 180-day exponential recency weighting; and
3. a trailing 365-day uniform training window.

Patch remained a post-selection diagnostic rather than a model feature.
Team, tournament, and other context features were not introduced.

Half-life and window selection use only rolling development results and the
tuning interval. Calibration remains 2025-Q4, and the final comparison on
2026-Q1 cannot change the chosen configuration.

Reports must include:

- performance by test patch when the subgroup has adequate support;
- performance by month and tier;
- seen-versus-unseen categorical rates;
- the effective sample size under recency weighting; and
- comparison with the uniform all-history baseline.

Missing patches stay missing. Patch values are never derived from match date,
and no patch-note content or external data is introduced in this milestone.

## 9. Metrics and decision rules

The primary metric is **log loss**, because the product promises a win
probability rather than only a class label.

Required metrics are:

- log loss;
- Brier score;
- ROC-AUC;
- accuracy and balanced accuracy as secondary diagnostics;
- calibration intercept and slope;
- expected calibration error using a fixed, documented binning rule; and
- reliability diagrams with per-bin counts.

Confidence intervals use a deterministic bootstrap grouped by
`source_match_id`, not an independent row bootstrap. Grouping reflects the
correlation among games in the same series.

Subgroup metrics are reported by patch, tier, month, and sufficiently large
tournaments. Small groups are marked descriptive and are not used to select a
model.

The champion is chosen before test access using, in order:

1. lower tuning and rolling-origin log loss than B0;
2. stable Brier-score improvement;
3. no severe temporal-fold regression;
4. acceptable calibration after the fixed calibration stage; and
5. lower complexity when candidates are practically tied.

The test report includes the frozen champion and mandatory B0/B1 references.
It does not choose a different winner after seeing 2026-Q1.

## 10. Calibration

Raw probabilities are evaluated before calibration. The selected estimator is
refit on Train + Tuning, then these alternatives are compared on 2025-Q4:

- no additional calibrator;
- sigmoid/Platt calibration; and
- isotonic calibration.

The comparison uses deterministic five-fold out-of-fold predictions grouped
by `source_match_id`, followed by one full-Q4 fit of the selected policy. Raw
probability is the simplicity default. Sigmoid or isotonic may replace it only
after a meaningful paired improvement in both log loss and Brier score;
isotonic also has a stricter fold-stability gate. The choice uses Q4 only.
2026-Q1 remains locked.

The saved model bundle contains the estimator, preprocessing contract, and
calibrator as separately identified components. This prevents explanations of
the estimator score from being confused with the calibrated output
probability.

## 11. Explanations

Every prediction must support a faithful local explanation:

- training/calibration base probability;
- calibrated Radiant win probability;
- strongest Radiant-positive contributions;
- strongest Dire-positive contributions; and
- explicit identification of pick, ban, or interaction terms.

For the implemented linear models, signed log-odds contributions are exact
and are the supported explanation method. No boosted model or SHAP dependency
was introduced.

Global reporting includes coefficient or importance stability across temporal
folds, hero support counts, and representative correctly and incorrectly
predicted drafts.

Explanations are associative, not causal. They must not claim that swapping a
hero guarantees a win-rate change. Counterfactual recommendations are outside
the initial completion gate and will require legal-candidate constraints,
out-of-distribution checks, and a separate product policy.

## 12. Reproducibility and experiment provenance

Each experiment receives a content-addressed manifest containing:

- release alias and all source fingerprints in Section 2;
- feature-contract version and canonical feature configuration;
- exact split boundaries and a hash of sorted `(sample_id, split)` assignments;
- model family and complete hyperparameters;
- training-window and recency policy;
- preprocessing and unknown-category policy;
- calibration method;
- random seeds, thread settings, Python version, and dependency versions;
- Git commit and clean/dirty state;
- model, calibrator, prediction, metric, and explanation artifact hashes; and
- wall-clock time and hardware summary.

Required artifacts are:

```text
artifacts/modeling/<experiment_id>/
  experiment_manifest.json
  split_manifest.parquet
  feature_contract.json
  model_artifact
  calibrator_artifact
  validation_predictions.parquet
  test_predictions.parquet
  metrics.json
  calibration_report.json
  explanation_report.json
  model_card.md
```

The modeling pipeline consumes only the canonical supervised Parquet and
schema. It has no API-client, raw-JSON, parser, or normalization dependency.

## 13. Staged implementation and completion criteria

### Stage A — Modeling contract and split gate

Deliver:

- versioned feature and split contracts;
- release-fingerprint verification;
- deterministic split manifest;
- leakage tests;
- class, patch, vocabulary, and unknown-category audit; and
- machine-readable experiment configuration.

Complete when the 23,123 rows reconcile exactly, split counts match Section 4,
no match crosses a split, forbidden features cannot enter a matrix, and the
offline tests pass. Stop for review before training.

### Stage B — Baselines and temporal backtesting

Deliver B0–B3, rolling-origin results, deterministic predictions, and
coefficient-based explanations.

Complete when every baseline is reproducible from its manifest, all metrics
and grouped confidence intervals are present, and the project can state
whether picks, bans, and per-team slots add stable out-of-time signal. Stop
for review before nonlinear candidates.

### Stage C — Drift experiments, challengers, and calibration

Deliver the fixed recency comparison, calibration gate, one bounded C1
interaction recovery attempt, and the resulting stop decision.

M4B.3 recorded an honest negative readiness result. M4B.4 then tested one
bounded, pre-Q4 B1-plus-synergy/counter representation; neither fixed
candidate improved on B1. M4B.5 tested the final approved team-context
hypothesis: it qualified on rolling development data but failed against every
reference on 2025-Q4. It was not promoted, modeling research closed, and the
locked test remained sealed.

### Stage D — Locked test and model publication (not opened)

After a development candidate passes the readiness gate, run its frozen
bundle once on 2026-Q1 and publish:

- test predictions and required metrics;
- temporal, patch, tier, and calibration diagnostics;
- faithful local and global explanation reports;
- limitation and selection-bias analysis;
- a model card;
- a content-addressed model bundle; and
- the mandatory Milestone 4 completion report.

No candidate passed that prerequisite, so Stage D was not opened. Closing the
research phase with the reserved test intact is the final Milestone 4
decision.

Milestone 4 completion required:

1. the full lineage from published dataset to model is reproducible;
2. the model beats the empirical-prior baseline on locked-test log loss and
   Brier score, or the project documents an honest negative result;
3. calibration and temporal degradation are measured rather than hidden;
4. explanations are faithful to supported side-relative features;
5. no forbidden or inferred field is used;
6. all offline tests pass; and
7. no readiness-approved or recommendation claim exceeds the evidence.

An honest negative result still completes the engineering milestone if the
experiment is rigorous. M4B.5 supplied that final result without opening the
test. M5–M5.3 subsequently turned the development candidate into a clearly
labeled completed-draft portfolio product. The remaining required roadmap is
M6 deployment followed by M7 portfolio release; recommendation research is
optional and outside the approved scope.

## 14. Deliberate simplifications

The strongest portfolio result is a trustworthy modeling system, not the
largest model catalog. Milestone 4 therefore does not initially need:

- a feature store;
- distributed training;
- a GPU pipeline;
- a transformer;
- automated hyperparameter infrastructure;
- online learning;
- inferred first-pick or action order; or
- draft recommendations before probability validation.

Sparse logistic baselines, one bounded linear interaction challenger, strict
temporal evaluation, calibration, explanations, and end-to-end provenance
demonstrate the relevant Applied AI Engineering skills with substantially
less accidental complexity.
