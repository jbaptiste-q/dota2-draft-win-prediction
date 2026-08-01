# Milestone 5.2: Completed-Draft Replacement Explorer

Status: **complete**

M5.3 subsequently froze this interaction as the final v1 product capability.
The comparison remains user-directed, associative, and non-recommendational.

Milestone 5.2 adds one bounded product interaction to Draft Lab: after a user
analyzes a complete 5v5 draft, they choose one current hero and one supported
hero that is not already selected, then compare the frozen model's output
before and after that replacement.

The feature is deliberately user-directed. It does not search or rank the hero
catalog, present a recommendation, or claim that the change causes a match
outcome. It demonstrates how the existing model responds to a precise
hypothetical input change.

## Why this is forward product work

Milestone 5.1 made the completed-draft estimator easy to inspect. Milestone 5.2
makes it interactive in a way that is directly related to the Draft Assistant:

```text
Analyze one completed 5v5 draft
  -> choose an outgoing hero
  -> choose a supported unselected incoming hero
  -> analyze the changed completed draft
  -> compare the two model outputs
```

This moves the product forward without reopening acquisition or model
selection. It helps a portfolio reviewer see the boundary between model
inference, product contracts, and interface behavior while keeping the model's
known limitations visible.

Milestone 4B.5 remains a closed supporting experiment, not a roadmap rollback.
Its team-context candidate was not promoted. Milestone 5.2 continues from the
M5 product slice and uses the already published M5.1 development snapshot.

This feature is also distinct from the partial-draft recommendation engine
envisioned in Milestone 1. That capability is optional and outside the frozen
v1 roadmap. If explicitly approved later, it must score incomplete draft
states with a context-sensitive model and earn its own offline evaluation
contract. A completed-draft replacement comparison does not satisfy that
separate gate.

## Product contract

FastAPI version `0.3.0` adds:

```text
POST /api/v1/replacement-comparisons
```

Schema version:

```text
draft-assistant-replacement-comparison-v1
```

The request contains:

| Field | Meaning |
| --- | --- |
| `radiant_picks` | Exactly five unique supported Radiant hero keys |
| `dire_picks` | Exactly five unique supported Dire hero keys, distinct from the Radiant picks |
| `side` | The lineup to change: `radiant` or `dire` |
| `hero_to_replace` | A hero currently selected on `side` |
| `replacement_hero` | A supported hero not present in the original ten picks |

The response contains:

| Field | Meaning |
| --- | --- |
| `schema_version` | `draft-assistant-replacement-comparison-v1` |
| `comparison_id` | Deterministic identity for the exact comparison and artifact |
| `interpretation` | `associative_model_comparison_not_causal` |
| `recommendation` | Always `false` |
| `side` | The user-selected side |
| `outgoing` | Catalog identity for the selected outgoing hero |
| `incoming` | Catalog identity for the selected incoming hero |
| `baseline` | Original draft, prediction ID, and probability |
| `replacement` | Changed draft, prediction ID, and probability |
| `delta` | Exact `radiant_win`, `dire_win`, and `selected_side_win` changes |
| `model` | The same artifact and lineage disclosure used by draft analysis |
| `limitations` | Product and model boundaries that apply to the comparison |

Both `baseline` and `replacement` are scenario objects containing
`prediction_id`, `draft`, and `probability`. The response therefore exposes
enough information for the frontend and tests to verify which two completed
drafts were compared.

## Architecture

The comparison service composes the existing analyzer instead of introducing a
second inference implementation:

```text
ReplacementComparisonRequest
  -> analyze(original complete draft)
  -> replace one hero in a copied draft
  -> analyze(changed complete draft)
  -> calculate exact probability deltas
  -> ReplacementComparisonResponse
```

The original request is not mutated. Both scenarios pass through the same
strict completed-draft validation, canonical side-relative ordering, frozen
coefficients, deterministic prediction identity, and model disclosure as
`POST /api/v1/analyze`.

The browser receives only the two scenario outputs and their difference. The
implementation adds no data store, model artifact, model fit, acquisition
dependency, or alternate probability calculation.

## Product guardrails

The API and interface make these boundaries explicit:

- the user selects both the outgoing and incoming hero;
- the service does not enumerate or rank alternatives;
- `recommendation` is always `false`;
- `interpretation` is always
  `associative_model_comparison_not_causal`;
- the result is described as a change in model output, not match outcome;
- only completed 5v5 picks are accepted;
- the additive model does not evaluate hero synergy, counters, roles, lanes,
  bans, draft order, first pick, patch, teams, players, or tournament context;
- the development candidate failed its 2025-Q4 readiness gate; and
- the locked 2026-Q1 test remains unevaluated.

These are product semantics, not interface-only disclaimers. The structured API
fields prevent a client from accidentally treating the response as a
recommendation contract.

## Implementation

| Path | Change |
| --- | --- |
| `src/draft_ai_assistant/contracts.py` | Strict request, scenario, delta, and response models |
| `src/draft_ai_assistant/service.py` | Deterministic comparison assembled from two existing analysis calls |
| `src/draft_ai_assistant/api.py` | Versioned replacement-comparison route and stable validation behavior |
| `src/draft_ai_assistant/web/index.html` | User-directed replacement controls and visible guardrail panel |
| `src/draft_ai_assistant/web/app.js` | Draft-state binding, response validation, and before/after rendering |
| `src/draft_ai_assistant/web/styles.css` | Responsive comparison presentation |
| `tests/test_draft_assistant_service.py` | Analyzer parity, immutability, delta, identity, and rejection tests |
| `tests/test_draft_assistant_api.py` | Exact HTTP contract and validation tests |
| `tests/test_draft_assistant_frontend.py` | Static interface, terminology, endpoint, and local-only safeguards |
| `README.md` | Quick start, current status, roadmap, and documentation link |

## Acceptance criteria

Milestone 5.2 is accepted when:

1. a valid user-selected replacement returns two complete draft scenarios;
2. each scenario exactly matches an independent call to the existing analyzer;
3. probability deltas reconstruct from the two scenario probabilities;
4. comparison identity is deterministic;
5. the original request and draft state remain unchanged;
6. unsupported, already selected, missing, and wrong-side heroes are rejected;
7. the interface does not automatically rank heroes or label the result as a
   recommendation;
8. the product continues to work without credentials, network access, local
   training data, or executable model serialization;
9. the existing analysis and model-card contracts remain backward compatible;
   and
10. the full active offline suite passes.

## Validation

- Focused Draft Assistant suite: **53 passed**.
- Complete active offline suite: **409 passed**.
- Existing non-blocking warnings: **16** joblib/NumPy deprecation warnings.
- Python compilation: **passed**.
- Dependency consistency: **passed**.
- JavaScript syntax: **passed**.
- Static frontend contract: **10 passed**.
- Repository hygiene: **passed**.
- Working-tree whitespace validation: **passed**.
- Local browser walkthrough: **passed**. The fixed example returned Radiant
  `44.5%` and Dire `55.5%`; replacing Radiant Axe with Abaddon displayed
  `47.9%` and a `+3.4 pp` change. Both product POST routes returned HTTP 200,
  the guardrails remained visible, and the browser reported no console errors.
- Authenticated Liquipedia requests: **0**.
- Model fits or optimization runs: **0**.
- Locked 2026-Q1 evaluation access: **0**.

Expected offline commands:

```bash
env LIQUIPEDIA_API_KEY= NO_NETWORK_TESTS=1 \
  .venv/bin/python -m pytest -q \
  tests/test_draft_assistant_snapshot.py \
  tests/test_draft_assistant_service.py \
  tests/test_draft_assistant_api.py \
  tests/test_draft_assistant_frontend.py

env LIQUIPEDIA_API_KEY= NO_NETWORK_TESTS=1 \
  .venv/bin/python -m pytest -q

.venv/bin/python -m compileall -q src scripts tests
.venv/bin/python -m pip check
.venv/bin/python scripts/check_repository_hygiene.py
node --check src/draft_ai_assistant/web/app.js
git diff --check
```

## Completion and current product path

M5.2 is complete. Its output is an auditable, user-directed completed-draft
comparison, not a recommendation engine.

M5.3 freezes the supported product at completed-draft analysis and
user-directed one-for-one comparison. The required roadmap continues with M6
deployment and M7 portfolio release.

A context-sensitive partial-draft recommendation system is optional and
outside v1. It requires explicit approval because it would reopen modeling
research and needs separate evidence before any automatic candidate-scoring
claim.
