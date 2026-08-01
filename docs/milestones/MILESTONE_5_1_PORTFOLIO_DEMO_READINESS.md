# Milestone 5.1: Portfolio Demo Readiness

Status: **complete**

M5.3 subsequently froze the v1 product contract around the completed-draft
workflow. The current required roadmap is deployment and portfolio release,
not additional modeling or recommendation work.

Milestone 5.1 makes the existing Draft Assistant easier to understand and
demonstrate without changing its model, data, or claims.

Two product problems were addressed:

1. a reviewer previously had to select ten heroes before seeing the product;
2. the failed readiness evidence was documented but not visible until after an
   analysis.

Draft Lab now provides a one-click example and an always-visible public model
card.

## Why this was the next step

Another acquisition or open-ended modeling milestone would not improve the
current product experience. A recommendation engine would also be misleading:
the frozen B1 estimator is additive, so candidate rankings would be driven by a
hero's isolated side coefficient rather than the surrounding draft.

This sub-milestone therefore improves immediate portfolio value while preserving
the honest boundary:

```text
Open Draft Lab
  -> see why the model is experimental
  -> select "Try example draft"
  -> receive a real API result and exact explanation
```

No result is mocked, cached, or hard-coded.

## One-click product walkthrough

The **Try example draft** control loads:

| Side | Heroes |
| --- | --- |
| Radiant | Axe, Puck, Lina, Tusk, Luna |
| Dire | Doom, Invoker, Tiny, Phoenix, Slark |

It then calls the unchanged `POST /api/v1/analyze` route. The interface labels
the lineup as a fixed workflow example and explicitly says it is not a hero
recommendation.

The deterministic result remains:

- Radiant probability: `0.44484184557293205`;
- Dire probability: `0.555158154427068`;
- ten exact signed hero contributions; and
- prediction ID:
  `90be33786adefbd7f019211071005493a46b9936360a2c79dc0185ab89151357`.

## Public model-card contract

FastAPI version `0.2.0` adds:

```text
GET /api/v1/model-card
```

Schema version:

```text
draft-assistant-model-card-v1
```

The response is generated only from the already verified public JSON snapshot.
It publishes:

- candidate and artifact identity;
- 20,087 fit rows;
- fit cutoff `<2025-10-01T00:00:00Z`;
- 125 supported heroes;
- side-relative completed-pick representation;
- exact 2025-Q4 candidate and empirical-prior proper scores;
- failed readiness status;
- unevaluated locked 2026-Q1 status;
- supported and unsupported capabilities; and
- the product limitations.

It contains no credential, source payload, local path, ignored artifact path,
training row, or executable model serialization.

## Visible evidence

The product now shows the development comparison before draft interaction:

| 2025-Q4 metric | B1 candidate | Empirical prior | Better |
| --- | ---: | ---: | --- |
| Log loss | `0.6982455480507083` | `0.6931146429704167` | Empirical prior |
| Brier score | `0.2524500613459483` | `0.24998372976923464` | Empirical prior |

Lower is better for both scores. The interface therefore shows:

- readiness gate: **failed**;
- locked 2026-Q1: **not evaluated**; and
- fit cutoff: **September 30, 2025 UTC**.

If the model-card request fails, the evidence panel reports that evidence is
unavailable but does not disable draft analysis.

## Product and architecture boundary

M5.1 reuses the existing layers:

```text
Tracked JSON snapshot
  -> framework-independent DraftAssistantService
  -> versioned FastAPI model-card and analysis routes
  -> same-origin static Draft Lab
```

It adds no:

- Liquipedia request;
- acquisition, normalization, or dataset change;
- model fit, calibration, or optimization;
- Q4 row-level target or prediction access;
- 2026-Q1 transform, prediction, target, or evaluation access;
- recommendation or partial-draft behavior;
- database or persistence;
- external frontend asset; or
- deployment.

This milestone did not deploy the product. M5.3 later clarified that an
explicitly experimental portfolio deployment is allowed; readiness-approved
model promotion and production-quality probability claims remain blocked.

## Implementation

| Path | Change |
| --- | --- |
| `src/draft_ai_assistant/contracts.py` | Strict model-card response contracts |
| `src/draft_ai_assistant/service.py` | Snapshot-only `model_card()` assembly |
| `src/draft_ai_assistant/api.py` | Versioned `GET /api/v1/model-card` route |
| `src/draft_ai_assistant/web/index.html` | One-click example and visible evidence panel |
| `src/draft_ai_assistant/web/app.js` | Example execution, model-card loading, validation, and graceful failure |
| `src/draft_ai_assistant/web/styles.css` | Responsive example and evidence presentation |
| `tests/test_draft_assistant_*.py` | Exact API, service, example, evidence, and local-only safeguards |
| `README.md` | Demo instructions and current roadmap status |

## Validation

- Focused Draft Assistant suite: **37 passed**.
- Complete active offline suite: **359 passed**.
- Existing non-blocking warnings: **16** joblib/NumPy deprecation warnings.
- Python compilation: passed.
- Dependency consistency: passed.
- JavaScript syntax: passed.
- Static DOM-reference contract: passed.
- Local-only asset check: passed.
- Repository hygiene: passed.
- Working-tree whitespace validation: passed.
- Authenticated requests: **0**.
- Model fits or optimization runs: **0**.
- Locked-test access: **0**.

Commands:

```bash
env LIQUIPEDIA_API_KEY= NO_NETWORK_TESTS=1 \
  python -m pytest -q \
  tests/test_draft_assistant_snapshot.py \
  tests/test_draft_assistant_service.py \
  tests/test_draft_assistant_api.py \
  tests/test_draft_assistant_frontend.py

env LIQUIPEDIA_API_KEY= NO_NETWORK_TESTS=1 \
  python -m pytest -q

python -m compileall -q src scripts tests
python -m pip check
python scripts/check_repository_hygiene.py
node --check src/draft_ai_assistant/web/app.js
git diff --check
```

## Completion and current product path

The completed-draft product can now demonstrate its real workflow and its
negative evaluation result immediately. That is the correct stopping point for
M5.1.

M5.2 added only a user-directed completed-draft comparison, and M5.3 froze the
resulting v1 contract. The required roadmap continues with M6 deployment and
M7 portfolio release. Recommendations remain optional and out of scope unless
explicit approval is given to reopen modeling research.
