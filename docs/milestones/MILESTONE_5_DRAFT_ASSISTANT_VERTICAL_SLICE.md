# Milestone 5: Draft Assistant Vertical Slice

Status: **complete — runnable experimental product slice**

M5.3 subsequently froze the v1 product contract: completed 5v5 pick-only
probability, exact additive local explanations, and user-directed one-for-one
completed-draft comparisons. The candidate remains experimental and
readiness-failed. Partial drafts, rankings, recommendations, and bans are not
supported.

Milestone 5 turns the validated data and modeling work into the first
user-visible Draft AI workflow:

```text
Completed 5v5 hero picks
  -> strict product contract
  -> frozen JSON inference snapshot
  -> Radiant/Dire probability
  -> exact signed hero contributions
  -> interactive Draft Lab
```

This is deliberately narrower than the final product. It proves the complete
inference and explanation path without pretending that the current development
candidate passed its readiness gate.

## Product outcome

The local application now lets a user:

1. search a 125-hero catalog;
2. select five unique Radiant and five unique Dire heroes;
3. analyze the completed draft;
4. see complementary Radiant and Dire win probabilities;
5. inspect all ten signed hero log-odds contributions; and
6. see the model cutoff, failed readiness status, sealed-test status, and
   limitations next to the result.

Run it with:

```bash
python scripts/run_draft_assistant.py
```

The interactive product is served at `http://127.0.0.1:8000` and its OpenAPI
documentation at `http://127.0.0.1:8000/docs`.

## Honest product boundary

The slice supports only the contract earned by the frozen B1 model:

- input is one completed set of five Radiant and five Dire picks;
- all ten heroes must be unique and present in the frozen vocabulary;
- order within one side has no model meaning;
- the output is a raw logistic probability;
- local explanations are exact additive base-model log-odds contributions; and
- contribution direction is associative, not causal.

The product does **not** claim or provide:

- partial-draft or next-pick recommendations;
- ban effects;
- synergy or counter effects;
- first-pick or globally interleaved draft order;
- patch, team, player, or tournament conditioning;
- readiness-approved or production probability quality; or
- a live Liquipedia connection.

Those boundaries appear in the interface and API output, not only in this
report.

## Frozen lineage

| Contract | Value |
| --- | --- |
| Candidate | `b1_full_uniform_c0p01` |
| Candidate fingerprint | `cc74f23fbd16e6ff6f5a3e2598cd9d326b78abee860bfceeb569154c0c77837e` |
| M4B.3 build | `3f768bb13f0b447bcf6704086f00c28f4652a21e467089d3549060ad3ab64a5c` |
| M4B.3 experiment manifest SHA-256 | `5a968b5d0d1b9e09e3ba31d16c09454078f4b2ec0d7ba99fa4d9a8018de9cd15` |
| Source bundle manifest SHA-256 | `043646136f4034b62cf08679ce15c406e6c4c132a7d6c64afc248599785991f4` |
| Source bundle fingerprint | `d89104b0688a68b0c708b2719d616786d752d0880f8e9662384f9769c38aadb6` |
| Feature fingerprint | `f651eb86302489110e9af72ea03ef3ffdc790f13b73531a893d3a7bdd4d5401a` |
| Split fingerprint | `dcb1227db92e585d3faab3a435a02aac2e9cb81da44d79bbcf3d7c353cc06fd1` |
| Hero catalog SHA-256 | `273cc7fc94fd3e6ade0a7393d6183404699a5eae31ac09a6f884e4df66d4d709` |
| Base fit rows | 20,087 |
| Base fit cutoff | `<2025-10-01T00:00:00Z` |
| Calibration policy | Raw identity |
| Readiness gate | Failed on 2025-Q4 |
| 2026-Q1 locked evaluation | Not performed |
| Authenticated requests | 0 |

The working corpus contains validated 2026-Q1 data, but this product model does
not use it. The readiness gate failed before the locked period could be opened,
so the interface explicitly shows the earlier fit cutoff instead of implying
that the probability is a 2026-validated forecast.

## Public inference snapshot

The ignored M4B.3 joblib bundle is not required at product runtime. A
deterministic offline export converts it into one reviewed, JSON-only snapshot:

```text
src/draft_ai_assistant/resources/development_candidate_v0.json
```

| Property | Value |
| --- | --- |
| File size | 22,319 bytes |
| File SHA-256 | `bfb7fc8d907e77057cafaef8109a4aec8085915c9215f0dc43cc15ff61dc1a61` |
| Artifact fingerprint | `69730a62f42cda234337e8cbf152fb50fcb7ae02faf38367955c267fbe714442` |
| Heroes | 125 |
| Hero coefficients | 125 Radiant + 125 Dire |
| Executable serialization | None |
| Training/source rows | None |
| API payloads or credentials | None |

The export:

1. verifies the externally pinned bundle manifest hash;
2. verifies component hashes before trusted local joblib loading;
3. verifies the experiment manifest's zero locked-target, locked-transform,
   locked-prediction, and authenticated-request counters;
4. verifies the readiness evidence and pre-reserved-period hero catalog;
5. converts only the intercept, hero coefficients, display catalog,
   limitations, and lineage to JSON;
6. checks three representative drafts against the source bundle;
7. validates the completed snapshot against the runtime contract; and
8. replaces the tracked output atomically only after validation succeeds.

The maximum absolute source-bundle versus JSON probability difference across
the three export checks was
`5.551115123125783e-17`.

At runtime, the product verifies both the tracked file SHA-256 and its semantic
fingerprint before serving a result. It never deserializes joblib.

Reproduce or verify the snapshot offline:

```bash
python scripts/export_draft_assistant_snapshot.py
```

Use `--write` only when intentionally regenerating it from the exact pinned
local artifacts.

## API contracts

| Method and path | Contract | Purpose |
| --- | --- | --- |
| `GET /api/v1/health` | `draft-assistant-health-v1` | Model-loaded status and public identity |
| `GET /api/v1/heroes` | `draft-assistant-heroes-v1` | Frozen supported hero keys and display names |
| `POST /api/v1/analyze` | `draft-assistant-analysis-v1` | Completed-draft probability, explanation, disclosures, and limitations |

The analysis request is:

```json
{
  "radiant_picks": ["hero-key-1", "hero-key-2", "hero-key-3", "hero-key-4", "hero-key-5"],
  "dire_picks": ["hero-key-6", "hero-key-7", "hero-key-8", "hero-key-9", "hero-key-10"]
}
```

Unknown fields, wrong list lengths, empty identifiers, duplicate heroes,
cross-side duplicates, and out-of-vocabulary heroes fail closed with HTTP 422.

## Explanation fidelity

For a completed draft, the service computes:

```text
draft log-odds
  = intercept
  + sum(active Radiant hero coefficients)
  + sum(active Dire hero coefficients)

Radiant probability = sigmoid(draft log-odds)
Dire probability = 1 - Radiant probability
```

Every returned contribution is one active coefficient. Tests independently
reconstruct the draft logit and probability with a tolerance of `1e-15`.
Slot permutation within a side returns the same prediction identity and
response.

One deterministic example:

| Side | Picks |
| --- | --- |
| Radiant | Axe, Puck, Lina, Tusk, Luna |
| Dire | Doom, Invoker, Tiny, Phoenix, Slark |

Result:

- Radiant probability: `0.44484184557293205`;
- Dire probability: `0.555158154427068`;
- baseline log-odds: `0.04858559432632899`;
- draft log-odds: `-0.22153422029520553`;
- reconstruction error: `5.551115123125783e-17`; and
- deterministic prediction ID:
  `90be33786adefbd7f019211071005493a46b9936360a2c79dc0185ab89151357`.

This example demonstrates calculation fidelity only. It is not evaluation
evidence.

## Implementation

| Path | Responsibility |
| --- | --- |
| `configs/product/draft_assistant_v0.json` | Exact export sources, product boundary, and limitations |
| `src/draft_ai_assistant/contracts.py` | Strict Pydantic request and response schemas |
| `src/draft_ai_assistant/snapshot.py` | JSON artifact hash, semantic, and contract verification |
| `src/draft_ai_assistant/service.py` | Framework-independent validation, inference, and local explanation |
| `src/draft_ai_assistant/api.py` | FastAPI endpoints and same-origin static serving |
| `src/draft_ai_assistant/web/` | Responsive, accessible Draft Lab interface |
| `scripts/export_draft_assistant_snapshot.py` | Deterministic trusted-bundle-to-JSON export |
| `scripts/run_draft_assistant.py` | Local application entry point |
| `tests/test_draft_assistant_*.py` | Snapshot, service, API, and static frontend safeguards |

The slice adds pinned FastAPI, Pydantic, Uvicorn, and HTTPX dependencies.
There is no Node build, frontend framework, database, Docker layer, deployment
configuration, or live data dependency.

## Validation

- Focused product tests: **33 passed**.
- Complete active offline suite: **355 passed**.
- Existing non-blocking warnings: **16** joblib/NumPy 2.5 deprecation warnings
  from prior bundle serialization tests.
- Python compilation: passed.
- Dependency consistency: passed.
- JavaScript syntax: passed.
- Loopback entry-point smoke test: health and frontend returned HTTP 200.
- Repository hygiene: passed.
- Credential-pattern review: passed.
- Working-tree whitespace validation: passed.
- Snapshot reproducibility verification: passed.
- Authenticated Liquipedia requests: **0**.
- Model fits or optimization runs: **0**.
- Q4 target/prediction use by product code: **0**.
- 2026-Q1 target, transform, prediction, or evaluation use: **0**.

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

python -m pip check
python -m compileall -q src scripts tests
python scripts/check_repository_hygiene.py
node --check src/draft_ai_assistant/web/app.js
git diff --check
```

## Completion and current product path

Milestone 5 is complete because a fresh clone can run and inspect a real,
lineage-pinned Draft AI result without authenticated data or ignored model
artifacts.

M5.1–M5.3 completed the bounded product work that followed this slice. A
transparent portfolio deployment is allowed because the interface and API
identify the candidate as experimental, expose the failed readiness evidence,
and make no production-quality probability claim. Readiness-approved model
promotion remains blocked.

The required roadmap continues with M6 deployment and M7 portfolio release.
A partial-draft recommendation engine is optional, outside the frozen v1
contract, and requires explicit approval to reopen modeling research.
