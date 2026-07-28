# Milestone 4: Draft AI Modeling Plan

Status: **design only; no model has been trained**
Date: **2026-07-28**
Canonical input schema: `dota-draft-supervised-v1`
Published release alias:
`m3.5-tier1-tier2-2022q1-2024q1-provisional-v1`

## 1. Objective

Milestone 4 will build and evaluate the first production-quality probability
model for the flagship AI Draft Assistant:

> Given a completed professional Dota 2 draft, estimate the probability that
> Radiant wins and explain the draft evidence behind that estimate.

This milestone starts at the published canonical supervised dataset. It does
not call the Liquipedia API, reinterpret raw payloads, change eligibility, or
modify the normalized and supervised data contracts.

The output is an evaluated, calibrated, reproducible modeling artifact—not a
backend, frontend, live recommendation engine, or automated drafting agent.
Hero recommendations and counterfactual draft search should be designed only
after the probability model proves useful out of time.

## 2. Fixed input release

All Milestone 4 experiments must pin this exact release:

| Item | Fixed value |
| --- | --- |
| Historical interval | `[2022-01-01T00:00:00Z, 2024-04-01T00:00:00Z)` |
| Included partitions | `2022-Q1` through `2024-Q1` |
| Liquipedia tiers | Tier 1 and Tier 2 |
| Release status | `provisional_contiguous_prefix` |
| Release fingerprint | `a485f713ffaf94f784ea1c770478be5c172d60285eb8369e294d34d9d447e7da` |
| Normalized fingerprint | `6f44f771e75eabffb393f2a3a2bbe27097d4c882d38fbfd10b476fa66dfcae1f` |
| Supervised fingerprint | `c1ea1d31968eb4c9c6fc4cd8dd7812ca2189694ca94ace48b1aae676e146acd9` |
| Supervised Parquet SHA-256 | `86fc4327c30a92ef50de889b343682f5934615b6b14f75057a4a9e3ff957a719` |
| Supervised schema SHA-256 | `4bae8474d0d982c0356bda042ab15739572e97f97b63548e3685c028480872b4` |
| Eligible supervised rows | `9,700` |
| Source matches represented | `4,683` |
| Hero vocabulary size | `124` |
| Radiant wins / losses | `4,833 / 4,867` |

The release is intentionally a provisional contiguous prefix rather than a
claim of complete Dota 2 history. Results must be versioned against this
release and must not be silently compared with models trained on later
expansions.

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
| Train | `[2022-01-01, 2023-07-01)` | 5,458 | 2,486 | 2,543 | 46.592% |
| Validation | `[2023-07-01, 2024-01-01)` | 1,732 | 824 | 931 | 53.753% |
| Locked test | `[2024-01-01, 2024-04-01)` | 2,510 | 1,373 | 1,359 | 54.143% |
| Total | `[2022-01-01, 2024-04-01)` | 9,700 | 4,683 | 4,833 | 49.825% |

No source match crosses these boundaries in the published release. The split
builder must still assert this invariant and fail if it changes in a future
release.

The validation interval has two fixed internal roles:

| Validation role | UTC interval | Rows | Source matches | Radiant wins |
| --- | --- | ---: | ---: | ---: |
| Tuning | `[2023-07-01, 2023-10-01)` | 921 | 406 | 461 |
| Calibration | `[2023-10-01, 2024-01-01)` | 811 | 418 | 470 |

Hyperparameters and feature choices are selected using the tuning interval.
The selected estimator is then refit on Train + Tuning (`6,379` rows), and its
probability calibrator is fit only on the `811` calibration rows. The locked
test is evaluated once after the experiment decision is frozen.

The changing Radiant win rate is real evidence of temporal distribution
shift. Rows must not be globally rebalanced, and class weights are off by
default because they would alter probability calibration. The large,
newer-patch `2024-Q1` partition is a valuable holdout rather than an
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
2. Verify exactly 9,700 unique `sample_id` values.
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
| C1 | Sparse logistic model with supported pick-pair interactions | Model interpretable synergy and counters |
| C2 | Categorical gradient boosting on the 24 draft slots | Nonlinear challenger without manual pair explosion |

The empirical prior is learned independently for each training window. It is
not the all-release class rate.

The initial champion should be the simplest model with a repeatable temporal
advantage. A neural network is not a Milestone 4 requirement. With 9,700 rows,
a deep embedding or transformer model adds optimization and explanation cost
before the project has shown that regularized sparse or boosted models are
insufficient. A shallow embedding or permutation-invariant set model is a
stretch experiment only after the classical gates pass.

Hyperparameter search must be a small, declared grid or deterministic search,
not an open-ended sweep. Complexity, runtime, and number of evaluated
configurations are recorded.

## 8. Patch and recency experiments

Patch drift is central to the product: the locked test consists of newer
`7.35` variants than the development period. Patch should therefore be
treated as a generalization problem, not merely another high-cardinality
category.

The pre-registered comparisons are:

1. all available history, draft-only, uniform sample weight;
2. all history plus an explicit patch category with unknown-patch handling;
3. all history with exponential recency weighting using half-lives of 90,
   180, or 365 days;
4. a trailing 365-day training window; and
5. draft-only versus draft plus the limited context ablation.

Half-life and window selection use only rolling development results and the
tuning interval. Calibration remains Q4 2023, and the final comparison on Q1
2024 cannot change the chosen configuration.

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
It does not choose a different winner after seeing Q1 2024.

## 10. Calibration

Raw probabilities are evaluated before calibration. The selected estimator is
refit on Train + Tuning, then these alternatives are fit on Q4 2023:

- no additional calibrator;
- sigmoid/Platt calibration; and
- isotonic calibration.

With only 811 calibration rows, sigmoid calibration is the default unless
isotonic calibration shows a meaningful, stable advantage without visibly
overfitting. The calibrator choice uses Q4 only. Q1 2024 remains locked.

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

For linear models, signed log-odds contributions are exact and are the
preferred first explanation. For the boosted challenger, SHAP values may be
used only with a pinned implementation and a validation check that local
contributions reconcile with the model score.

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

Complete when the 9,700 rows reconcile exactly, split counts match Section 4,
no match crosses a split, forbidden features cannot enter a matrix, and the
offline tests pass. Stop for review before training.

### Stage B — Baselines and temporal backtesting

Deliver B0–B3, rolling-origin results, deterministic predictions, and
coefficient-based explanations.

Complete when every baseline is reproducible from its manifest, all metrics
and grouped confidence intervals are present, and the project can state
whether picks, bans, and per-team slots add stable out-of-time signal. Stop
for review before nonlinear candidates.

### Stage C — Drift experiments, challenger, and calibration

Deliver the fixed patch/recency matrix, C1/C2 challengers, frozen champion
decision, and calibration comparison.

Complete when model selection uses no Q1 2024 labels, the champion and
calibrator are frozen, and every artifact hash and validation result is
recorded. Stop for approval before opening the test.

### Stage D — Locked test and model publication

Run the frozen bundle once on Q1 2024 and publish:

- test predictions and required metrics;
- temporal, patch, tier, and calibration diagnostics;
- faithful local and global explanation reports;
- limitation and selection-bias analysis;
- a model card;
- a content-addressed model bundle; and
- the mandatory Milestone 4 completion report.

Milestone 4 succeeds only if:

1. the full lineage from published dataset to model is reproducible;
2. the model beats the empirical-prior baseline on locked-test log loss and
   Brier score, or the project documents an honest negative result;
3. calibration and temporal degradation are measured rather than hidden;
4. explanations are faithful to supported side-relative features;
5. no forbidden or inferred field is used;
6. all offline tests pass; and
7. no backend, frontend, or recommendation claim is presented as complete.

An honest negative result still completes the engineering milestone if the
experiment is rigorous. It would mean the next decision is better features or
more current data—not a more complicated model chosen after looking at the
test.

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

Sparse logistic baselines, one nonlinear challenger, strict temporal
evaluation, calibration, explanations, and end-to-end provenance demonstrate
the relevant Applied AI Engineering skills with substantially less accidental
complexity.
