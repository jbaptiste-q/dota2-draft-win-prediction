# Milestone 4A: Modeling Infrastructure

Status: **complete**

Milestone 4A establishes the reproducible boundary between the validated
Liquipedia dataset and future Draft AI experiments. It does not train, tune,
select, or publish a model.

## Outcome

The active modeling path is now:

```text
dota-draft-supervised-v1 components
  -> verified working-corpus loader
  -> grouped chronological split
  -> training-fitted draft feature transformers
  -> unfitted baseline estimator blueprints
  -> future M4B experiments
```

No acquisition, raw JSON, parser, normalizer, or authenticated API dependency
exists in the modeling package.

## Frozen working corpus

The credential-free manifest
`configs/modeling/m4a_working_corpus.json` pins nine validated supervised
components:

| Scope | Eligible games |
| --- | ---: |
| 2022-Q1 through 2024-Q1 | 9,700 |
| 2024-Q2 | 1,712 |
| 2024-Q3 | 1,837 |
| 2024-Q4 | 1,351 |
| 2025-Q1 | 2,209 |
| 2025-Q2 | 1,814 |
| 2025-Q3 | 1,464 |
| 2025-Q4 | 1,089 |
| 2026-Q1 | 1,947 |
| **Total** | **23,123** |

The corpus is the contiguous interval
`[2022-01-01T00:00:00Z, 2026-04-01T00:00:00Z)`. It contains 11,664 source
matches, 11,762 Radiant wins, and 11,361 Dire wins. Every component is pinned
by its full supervised fingerprint, manifest checksum, schema checksum,
training-Parquet checksum, row counts, and half-open time range.

The incomplete 2026-Q2 cache and the noncontiguous July 2026 pilot are not
modeling inputs.

The loader validates:

- all nine component and artifact hashes;
- the exact 37-column `dota-draft-supervised-v1` schema;
- physical Parquet types and UTC timestamp conversion;
- deterministic ordering;
- unique sample and game keys;
- `(source_match_id, source_game_id)` and
  `(source_match_id, game_index)` identity;
- component boundaries and aggregate class/null counts; and
- source-match grouping integrity, including series whose sides change
  between games.

## Leakage-safe temporal split

All intervals are half-open and UTC-based. Every game from one
`source_match_id` remains in one role.

| Role | Interval | Rows | Source matches |
| --- | --- | ---: | ---: |
| Train | `[2022-01-01, 2025-07-01)` | 18,623 | 9,254 |
| Validation—tuning | `[2025-07-01, 2025-10-01)` | 1,464 | 781 |
| Validation—calibration | `[2025-10-01, 2026-01-01)` | 1,089 | 523 |
| Locked test | `[2026-01-01, 2026-04-01)` | 1,947 | 1,106 |

Split-manifest fingerprint:

```text
dcb1227db92e585d3faab3a435a02aac2e9cb81da44d79bbcf3d7c353cc06fd1
```

The locked test is the newest complete 2026 quarter. M4A reconciles its
membership but does not use it to fit a vocabulary, estimator, calibrator, or
selection rule.

## Feature engineering

`src/draft_ai_modeling/features.py` implements three deterministic sparse
contracts:

| Variant | Meaning | Columns |
| --- | --- | ---: |
| `b1-pick-presence` | Side-relative Radiant/Dire pick presence | 252 |
| `b2-pick-ban-presence` | Side-relative pick and ban presence | 504 |
| `b3-slot-aware` | One-hot canonical per-team pick and ban slots | 3,024 |

All variants use a 125-hero vocabulary fitted only on the training interval.
Unknown heroes use explicit `__UNKNOWN__` columns. Training and tuning contain
zero unknown activations; later periods exercise the policy explicitly,
including 1,209 pick/ban unknown activations in the locked 2026 test.

The matrices contain draft features only. Identifiers, source-match grouping,
timestamps, targets, patch, tier, team, tournament, series, duration, result
fields, inferred first pick, and reconstructed global draft order cannot enter
the default feature matrices.

Feature-contract fingerprints:

| Variant | Fingerprint |
| --- | --- |
| B1 | `f651eb86302489110e9af72ea03ef3ffdc790f13b73531a893d3a7bdd4d5401a` |
| B2 | `c1532a2da2859686c7e39652ee1c08c2888df2a3fc0acfa89503699e11436e0f` |
| B3 | `bdec9085f4ad0abecf48fe40badf081bb548f4ef4851616c7f4d2680cb6cd450` |

## Baseline framework

M4A declares and instantiates these estimator blueprints without calling
`fit`:

| ID | Purpose | Estimator |
| --- | --- | --- |
| B0 | Empirical-prior probability reference | `DummyClassifier` |
| B1 | Explainable pick-only baseline | L2 logistic regression |
| B2 | Measure incremental ban signal | L2 logistic regression |
| B3 | Measure canonical per-team slot signal | L2 logistic regression |

The estimator family, fixed initial parameters, random seed, feature profile,
and contract fingerprint are deterministic. Hyperparameter search belongs to
a later approved modeling stage.

## Reproducibility artifacts

Run the offline preparation gate:

```bash
.venv/bin/python scripts/prepare_draft_modeling.py
```

Generated artifacts remain local under `models/m4a/`:

```text
build_<fingerprint>/
  infrastructure_manifest.json
  split_manifest.parquet
  split_report.json
  split_report.md
  feature_contracts.json
  baseline_contracts.json
  preparation_report.md
```

The verified proof build is:

```text
2c8c8d1ad87eb711cf474a4cf48b9dc2ad85d2f876b3b9c4c6f8a4d0e8a37e0b
```

It records zero estimator fits, zero hyperparameter searches, and no
acquisition/API dependency.

## Validation

- M4A loader, split, feature, baseline, and preparation tests passed.
- Complete active offline suite: `158 passed`.
- Python compilation: passed.
- Dependency consistency: passed.
- Repository and credential hygiene: passed.
- Whitespace validation: passed.
- Authenticated Liquipedia requests: `0`.
- Acquisition code modified by M4A: `no`.
- Models trained: `0`.

## Boundary for the next stage

M4A is complete when infrastructure is reviewed. M4B may fit and compare the
declared baselines, evaluate temporal drift on tuning data, reserve
calibration for probability calibration, and keep 2026-Q1 locked until the
model-selection decision is frozen.

No recommendation engine, inference API, frontend, or deployment work is
claimed by this milestone.
