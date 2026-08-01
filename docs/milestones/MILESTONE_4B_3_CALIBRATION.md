# Milestone 4B.3: Frozen B1 Probability Calibration

Status: **complete — calibration policy frozen; readiness gate failed**

Milestone 4B.3 asked one bounded product question:

> Does the frozen Draft AI candidate need a probability calibrator before its
> one-time 2026-Q1 evaluation?

The answer is **no calibrator should be added**, but the candidate is also
**not ready for the locked test**.

Raw probability remains the frozen policy because sigmoid's apparent
improvement was not conclusive under a paired series bootstrap and isotonic
was unstable. More importantly, raw, sigmoid, and isotonic were all worse
than the Train + Tuning empirical prior on 2025-Q4 point log loss and Brier
score. Calibration cannot recover ranking signal that the base model does not
have.

No 2026-Q1 prediction was generated.

## Frozen lineage

| Contract | Value |
| --- | --- |
| Working corpus | `m4a-tier1-tier2-2022q1-2026q1-working-v1` |
| Corpus rows | 23,123 games |
| M4A build | `2c8c8d1ad87eb711cf474a4cf48b9dc2ad85d2f876b3b9c4c6f8a4d0e8a37e0b` |
| Split fingerprint | `dcb1227db92e585d3faab3a435a02aac2e9cb81da44d79bbcf3d7c353cc06fd1` |
| M4B.2 build | `a05b2792e3096869d10d7b58339542ceb3bfcf96810a6357520bacc8ac711456` |
| Frozen candidate | `b1_full_uniform_c0p01` |
| Candidate fingerprint | `cc74f23fbd16e6ff6f5a3e2598cd9d326b78abee860bfceeb569154c0c77837e` |
| M4B.3 config fingerprint | `53bda5500004f68c6c69c7e3d7c8049d72ff63219317ea1180c0541222dee7e9` |
| M4B.3 build fingerprint | `3f768bb13f0b447bcf6704086f00c28f4652a21e467089d3549060ad3ab64a5c` |

The exact M4B.2 candidate was reproduced on its 1,464-row 2025-Q3 evaluation
set with maximum absolute probability difference `0.0`.

## Data boundary

| Role | Interval | Rows | Source matches | Use |
| --- | --- | ---: | ---: | --- |
| Train | `[2022-01-01, 2025-07-01)` | 18,623 | 9,254 | Base refit |
| Tuning | `[2025-07-01, 2025-10-01)` | 1,464 | 781 | Base refit |
| Calibration | `[2025-10-01, 2026-01-01)` | 1,089 | 523 | Calibrator comparison and fit |
| Locked test | `[2026-01-01, 2026-04-01)` | 1,947 | 1,106 | Masked and unused |

The base B1 transformer and estimator were refit once on the 20,087 Train +
Tuning rows. The calibration set contains 550 Radiant wins and 539 losses.
No source match crosses a role or calibration fold.

## Honest calibration comparison

The comparison was deliberately limited to:

1. raw identity;
2. sigmoid/Platt calibration on the base logit; and
3. increasing isotonic calibration on the raw probability.

Sigmoid and isotonic predictions came from deterministic five-fold
`StratifiedGroupKFold` cross-fitting:

- grouping unit: `source_match_id`;
- folds: 5;
- shuffle: true;
- seed: 42; and
- fold-assignment fingerprint:
  `b323bf9ba016fd7d957b85a252e4a74a1ca03bd7430473217dc330f3167cdccc`.

Every sigmoid and isotonic Q4 prediction came from a calibrator that had not
seen that game or any other game from its series; raw predictions came from
the past-only base estimator. After selection, only the chosen policy could be
fit on all Q4 rows. Raw identity was selected, so no calibrator fit was
required. Full-fit calibrator outputs would never be used as evaluation
evidence.

## Results

Lower log loss, Brier score, and ECE are better. ECE and classification
metrics were diagnostic only.

| Method | Log loss | Brier | ROC-AUC | ECE |
| --- | ---: | ---: | ---: | ---: |
| Raw | 0.698246 | 0.252450 | 0.5172 | 0.032048 |
| Sigmoid | **0.693463** | **0.250156** | 0.5130 | 0.019960 |
| Isotonic | 0.725801 | 0.250946 | 0.5024 | **0.011585** |

Sigmoid-minus-raw paired intervals:

| Metric | Difference | Paired 95% interval |
| --- | ---: | --- |
| Log loss | -0.004782 | `[-0.010891, 0.001786]` |
| Brier score | -0.002294 | `[-0.005308, 0.000921]` |

Both point estimates favored sigmoid, but both intervals crossed zero. Under
the frozen selection policy, a more complex calibrator cannot replace raw
without a clear paired improvement in both proper scores.

Isotonic was not competitive:

- log loss was `0.027556` worse than raw;
- three cross-fitted predictions reached an exact probability boundary; and
- its worst fold was `0.162634` log-loss points worse than sigmoid.

The selected method is therefore **raw identity**. This is a simplicity
decision, not a claim that the raw model is production-ready.

## Readiness failure

The Train + Tuning empirical-prior B0 probability is `0.508090`.

| Metric | Raw B1 | B0 | B1 minus B0 | Paired 95% interval |
| --- | ---: | ---: | ---: | --- |
| Log loss | 0.698246 | 0.693115 | +0.005131 | `[-0.002989, 0.012958]` |
| Brier score | 0.252450 | 0.249984 | +0.002466 | `[-0.001546, 0.006311]` |

Both readiness gates failed. This is not caused by preferring raw over
sigmoid: sigmoid also remained slightly worse than B0 on both point metrics.
Opening 2026-Q1 would therefore spend the locked test on a candidate that has
not passed the final development-period gate.

## Patch evidence

Patch was not a feature and did not influence calibration selection.
Post-selection diagnostics show where the Q4 degradation occurred:

| Patch | Rows | Source matches | Raw log loss | Raw ROC-AUC |
| --- | ---: | ---: | ---: | ---: |
| 7.39 | 812 | 389 | 0.700765 | 0.5041 |
| 7.39e | 196 | 97 | 0.681188 | 0.6018 |

Three smaller or missing-patch groups totaling 81 rows were suppressed under
the pre-existing 100-row reporting threshold.

Patch 7.39 dominates Q4 and has essentially random ranking performance. This
is evidence of model drift or missing draft interactions, not a reason to
collect more historical data or tune a more flexible calibrator.

## Frozen bundle and explanation boundary

The content-addressed local bundle separately identifies:

- the B1 pick-presence transformer;
- the `C=0.01` logistic base estimator; and
- raw identity as the selected calibration component.

Bundle fingerprint:
`d89104b0688a68b0c708b2719d616786d752d0880f8e9662384f9769c38aadb6`.

The bundle was reloaded only after manifest and component hashes were
verified. Its raw and served probabilities reproduced the in-memory
components with maximum absolute difference `0.0`.

Coefficient explanations remain faithful to the base logistic log-odds.
They do not claim to add up to a separately calibrated probability.

## Implementation

| Path | Responsibility |
| --- | --- |
| `configs/modeling/m4b3_calibration.json` | Frozen lineage, roles, methods, selection gates, and safety boundary |
| `src/draft_ai_modeling/calibration_config.py` | Strict typed config and local lineage verification |
| `src/draft_ai_modeling/calibration.py` | Grouped cross-fitting, fixed calibrators, and paired bootstrap |
| `src/draft_ai_modeling/calibration_selection.py` | Proper-score evaluation and fixed complexity hierarchy |
| `src/draft_ai_modeling/model_bundle.py` | Separately hashed trusted bundle components |
| `src/draft_ai_modeling/calibration_experiment.py` | Offline orchestration, masking, reproduction, artifacts, and bundle validation |
| `scripts/run_draft_calibration.py` | Credential-free M4B.3 entry point |
| `tests/test_m4b3_*.py` | Config, leakage, calibration, selection, bundle, and end-to-end safeguards |

`joblib==1.5.3` is now a direct dependency because the trusted local bundle
uses it explicitly. Bundle loading verifies a hash supplied outside the
bundle before parsing and verifies every component before deserialization.
User-supplied or untrusted model paths are outside this contract.

## Generated artifacts

Local outputs remain ignored by Git under:

```text
models/m4b3/build_3f768bb13f0b447bcf6704086f00c28f4652a21e467089d3549060ad3ab64a5c/
```

| Artifact | SHA-256 |
| --- | --- |
| OOF predictions | `0e6612c9ad6690988bd7e750ef3a01b6d90b0fe0394454590064fed871d52b12` |
| Fold assignments | `99c5ac49b3b50c5a8927dce7ef623e0ca8b0e5e5362da9b34640005f43d00628` |
| Metrics | `42228ebed01a77f4c932416219e3842682ebd8cfeeb45c161e865ed93cc19f47` |
| Pairwise comparisons | `5d13d61f091b36d3f0ac6d418533fd13be503f25420ed0bb3bd71d171c4d2d66` |
| Selection | `06d5d37bd65e84c27b67f539e101d2d8118e17c588a90ff15c1da93e0c4bdf60` |
| Readiness gate | `a5c3ea0dadb59cffc7e4b2a79fd1227e105eaa22c5cd3f8865338761b443891b` |
| Patch diagnostics | `ab5e7e709187f817f507d78a3d7d892ed8fb63b97d340ed89b9eeb23061be761` |
| Base explanations | `ecd9022e40c0453976a641a7ccfc36a4f317c73ccf150893d3198c33560b9e85` |
| Bundle manifest | `043646136f4034b62cf08679ce15c406e6c4c132a7d6c64afc248599785991f4` |
| Transformer | `1dcff32af6dc78be361c9df76c3e7fdd7d9a68b0dbb2c3c8720e9332e320c279` |
| Base estimator | `a67be6c6ad0feba4a71c928b92425abbd8fdc53ebf7ba3bba534d5a228997989` |

## Validation

- M4B.3 focused suite: **34 passed**.
- Complete active offline suite: **284 passed**.
- Python compilation: passed.
- Dependency consistency: passed.
- Repository and credential hygiene: passed.
- Working-tree whitespace validation: passed.
- Non-blocking warning: 16 `joblib`/NumPy 2.5 deprecation warnings during
  serialization tests; no correctness failure.
- Authenticated API requests: **0**.
- Locked-test target rows used for modeling: **0**.
- Locked-test transforms: **0**.
- Locked-test predictions: **0**.

Commands:

```bash
env LIQUIPEDIA_API_KEY= NO_NETWORK_TESTS=1 \
  .venv/bin/python scripts/run_draft_calibration.py

env LIQUIPEDIA_API_KEY= NO_NETWORK_TESTS=1 \
  .venv/bin/python -m pytest -q
```

## Completion and next gate

M4B.3 is complete as a calibrated-model readiness gate. It produced a
reproducible negative result and correctly preserved the locked test.

The next step must remain development-only. It should target missing draft
signal or patch robustness using the existing corpus—not collect more data,
retune calibration, or open 2026-Q1. The smallest product-aligned candidate
is a bounded interaction model for hero synergy and counters, compared
against B0 and the frozen B1 on the existing rolling and Q4 development
periods.

Implementation of that recovery experiment requires a new explicit
development contract. The 2026-Q1 test remains sealed until a candidate
passes the same Q4 readiness gate.
