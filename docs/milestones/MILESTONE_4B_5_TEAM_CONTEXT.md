# Milestone 4B.5: Team Context Recovery Gate

Status: **complete — development hypothesis confirmed; Q4 readiness failed**

Milestone 4B.5 tested one bounded product hypothesis:

> Does adding one leakage-safe pre-series team-strength signal explain the
> Draft AI candidate's weak probabilities while preserving measurable draft
> value?

The answer is **yes on rolling development data, but not reliably enough for
promotion**.

The combined candidate substantially outperformed draft-only B1, team-only
Elo, and the empirical prior across 2025-Q1 through Q3. It also passed the
paired draft-attribution gate against team-only Elo. However, the exact frozen
candidate became worse than every reference on 2025-Q4. The locked 2026-Q1
test therefore remains sealed, and the current product candidate was not
changed.

No second Elo policy, model family, or hyperparameter search was attempted.

## Product decision

- Do not promote or serialize the M4B.5 candidate.
- Do not open the locked 2026-Q1 test.
- Keep the current M5.1 draft-only model as an explicitly limited
  demonstration candidate.
- Preserve the positive development result as evidence that a useful product
  should distinguish expected team strength from the incremental draft
  adjustment.
- Treat the Q4 failure as a temporal robustness failure, not as permission to
  weaken the gate.

## Fixed candidate

The experiment added exactly one feature to B1:

```text
elo_logit = ln(10) / 400 * (Radiant pre-series rating - Dire pre-series rating)
```

The feature policy was fixed before evaluation:

- initial rating: `1500`;
- rating scale: `400`;
- K-factor: `32`;
- one update per `source_match_id`;
- series score: mean game outcome for lexically ordered team A;
- same-timestamp series read one shared pre-batch state;
- all games in a series share pre-series ratings;
- evaluation ratings freeze at the fit cutoff;
- unseen teams receive the neutral initial rating;
- no side advantage, decay, roster inference, team-ID feature, patch feature,
  tournament feature, or hyperparameter search.

The estimator remained the frozen B1 policy: L2 logistic regression,
`C=0.01`, `liblinear`, seed `42`.

## Physical data boundary

The experiment introduced a whole-component prefix loader because the general
M4A loader verifies and opens the full corpus. M4B.5 instead opened only:

1. components through `2025-Q3` for development; and
2. the additional `2025-Q4` component only after development qualification.

The `2026-Q1` supervised Parquet, targets, transforms, and predictions were
never opened.

| Boundary | Rows | Use |
| --- | ---: | --- |
| 2022-Q1 through 2025-Q3 | 20,087 | Past-only fits and rolling development |
| 2025-Q4 | 1,089 | Conditional readiness gate |
| 2026-Q1 | 0 opened | Locked test |

Older 2022–2023 games are used only to warm up causal team ratings. All
selection and readiness evidence is from 2024–2025, with the primary product
decision based on 2025.

## Development result

The fixed candidate passed all seven rolling folds and every pre-registered
development gate.

### Pooled 2025-Q1 through Q3

| Model | Log loss | Brier score |
| --- | ---: | ---: |
| B1 + Elo | **0.656693** | **0.232140** |
| Elo only | 0.662272 | 0.234704 |
| Frozen B1 | 0.684171 | 0.245540 |
| Empirical prior B0 | 0.692793 | 0.249823 |

Combined-minus-reference paired series-bootstrap evidence:

| Reference | Metric | Difference | Paired 95% interval |
| --- | --- | ---: | --- |
| Frozen B1 | Log loss | -0.027478 | `[-0.035419, -0.019531]` |
| Frozen B1 | Brier score | -0.013400 | `[-0.016894, -0.009859]` |
| Elo only | Log loss | -0.005579 | `[-0.008151, -0.002784]` |
| Elo only | Brier score | -0.002564 | `[-0.003712, -0.001328]` |

The team-only comparison is essential: it shows that draft features added
incremental probability value rather than merely relabeling a generic team
predictor as Draft AI.

### Rolling log loss

| Evaluation | B1 + Elo | Elo only | Frozen B1 | B0 |
| --- | ---: | ---: | ---: | ---: |
| 2024-Q1 | 0.675321 | 0.679044 | 0.691700 | 0.696504 |
| 2024-Q2 | 0.666337 | 0.666726 | 0.692613 | 0.693153 |
| 2024-Q3 | 0.676556 | 0.676307 | 0.694210 | 0.693247 |
| 2024-Q4 | 0.689672 | 0.692271 | 0.689654 | 0.693061 |
| 2025-Q1 | 0.658203 | 0.664737 | 0.684160 | 0.692830 |
| 2025-Q2 | 0.646701 | 0.652479 | 0.683557 | 0.692838 |
| 2025-Q3 | 0.666796 | 0.670688 | 0.684948 | 0.692682 |

Seven-fold mean log loss improved by `0.020179` versus B1. The maximum
single-fold regression was only `0.000017`, below the fixed `0.01` limit.

## Q4 readiness failure

The candidate was refit on all 20,087 pre-Q4 games. The 2025-Q4 feature
transform received no Q4 target column; Q4 reference labels were joined only
after both probability vectors already existed.

| Model | Log loss | Brier score |
| --- | ---: | ---: |
| Empirical prior B0 | **0.693115** | **0.249984** |
| Frozen B1 | 0.698246 | 0.252450 |
| Elo only | 0.706071 | 0.252000 |
| B1 + Elo | 0.708685 | 0.252679 |

The combined candidate was worse on both proper scores against all three
references. Every point-estimate and paired-upper-bound readiness gate failed.

| Reference | Metric | Difference | Paired 95% interval |
| --- | --- | ---: | --- |
| B0 | Log loss | +0.015570 | `[-0.009518, +0.041995]` |
| B0 | Brier score | +0.002695 | `[-0.007707, +0.013740]` |
| Frozen B1 | Log loss | +0.010439 | `[-0.015040, +0.036464]` |
| Frozen B1 | Brier score | +0.000229 | `[-0.010688, +0.011585]` |
| Elo only | Log loss | +0.002614 | `[-0.004798, +0.010317]` |
| Elo only | Brier score | +0.000678 | `[-0.002550, +0.004009]` |

## Post-gate diagnostic

This diagnostic did not influence selection and cannot reverse the failed
gate.

| Month | Rows | B1 + Elo log loss | Elo-only log loss | Frozen B1 | B0 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2025-10 | 602 | **0.668832** | 0.667619 | 0.695234 | 0.693654 |
| 2025-11 | 229 | 0.762300 | 0.755104 | 0.703871 | 0.693207 |
| 2025-12 | 258 | 0.754087 | 0.752272 | 0.700281 | 0.691773 |

Ratings frozen on September 30 remained useful in October and degraded
sharply later. This is consistent with stale context, team/roster drift, or
both, but the current data contract cannot identify the cause. Nineteen of 98
Q4 team keys were unseen at the fit cutoff. This observation supports at most
one future product-semantic question—ratings available as of each series—not
a broader feature or model search.

## Reproducibility

| Item | Fingerprint |
| --- | --- |
| Config SHA-256 | `0cd3aea12f47b24c9a7dbb75156ba9a806b72f472eaf46f2b3c991c0e283188f` |
| Config fingerprint | `2e2d594859bb3d9ddd429d9ecf2a812fb114ed142dccd10b1d2ef84a13285c4a` |
| Team-strength policy | `039e4f03f17dfb188f127d53399de3e0e242903b118b609cd0c472459feed116` |
| Experiment build | `d90302404883e5ba7283c00e88d7d922f2b76e771630013acf9632ac20639e8b` |

Local content-addressed outputs remain ignored by Git:

```text
models/m4b5/build_d90302404883e5ba7283c00e88d7d922f2b76e771630013acf9632ac20639e8b/
```

| Artifact | SHA-256 |
| --- | --- |
| Development predictions | `26d1a46673d8b183255166889c82748d60f500cebcbe6c4fc68626edfdd69805` |
| Development evaluation | `b77a4062bf6df32aed26a1981863ceea1ed91a906e9133bd378ab684b0f630a9` |
| Q4 predictions | `476552017fddd84bd2732c333ecaa77c6380572c2128cb64a120dea5a63eecd2` |
| Q4 readiness | `cefd4c2a9857e5c42b1f1f559655b85c4ecba28357a62dbf418d4753bb6f1532` |
| Team-strength audit | `dc7c1e43cac6c9bed7c351394ebe5e26b360d2a2255085bbe89aeb9ae0f49580` |
| Local report | `19e500367f9af367a56628731ff6853c5724f6362060710c3beb868df6f1422b` |
| Manifest | `21c743f973d7ab50006fd22531cf890d7754b7e7111a1b00d8ee57ec41e9ce84` |

## Implementation

| Path | Responsibility |
| --- | --- |
| `configs/modeling/m4b5_team_context.json` | Exact single-candidate, lineage, gates, and safety contract |
| `src/draft_ai_modeling/loader.py` | Whole-component prefix loading without touching later artifacts |
| `src/draft_ai_modeling/team_strength.py` | Causal series-level Elo state and target-free frozen transform |
| `src/draft_ai_modeling/team_context_config.py` | Strict local contract validation and deferred Q4 pin |
| `src/draft_ai_modeling/team_context_selection.py` | Development, attribution, and Q4 readiness gates |
| `src/draft_ai_modeling/team_context_experiment.py` | Physical boundaries, fitting, prediction, lineage, and artifacts |
| `scripts/run_draft_team_context.py` | Credential-free offline entry point |
| `tests/test_m4b5_*.py` | Arithmetic, leakage, boundary, config, selection, and runner safeguards |

## Validation

- Focused M4B.5 suite: **34 passed**.
- Complete active offline suite: **393 passed**.
- Python compilation: passed.
- Dependency consistency: passed.
- Repository and credential hygiene: passed.
- Whitespace validation: passed.
- Existing non-blocking warnings: 16 `joblib`/NumPy deprecation warnings.
- Authenticated API requests: **0**.
- Q4 opened before development qualification: **no**.
- Locked component rows opened: **0**.
- Locked targets, transforms, or predictions: **0 / 0 / 0**.
- Model bundle or product snapshot changed: **no**.

Commands:

```bash
env LIQUIPEDIA_API_KEY= NO_NETWORK_TESTS=1 \
  .venv/bin/python scripts/run_draft_team_context.py

env LIQUIPEDIA_API_KEY= NO_NETWORK_TESTS=1 \
  .venv/bin/python -m pytest -q

.venv/bin/python -m compileall -q src scripts tests
.venv/bin/python -m pip check
NO_NETWORK_TESTS=1 .venv/bin/python scripts/check_repository_hygiene.py
git diff --check
```

## Completion

M4B.5 is complete. It produced the project's strongest evidence that team
context and draft signal are complementary, while correctly rejecting a
candidate that did not remain reliable across the final development quarter.

The Q4 result is now development evidence and must not be described as an
unbiased future test. A future as-of-series rating policy would need to be
fixed without a feature grid and evaluated only under a separately approved
locked-test decision. No such follow-up was implemented here.
