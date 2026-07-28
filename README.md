# Dota 2 Draft AI

A production-oriented Applied AI portfolio project built from the official
Liquipedia API.

The flagship product is an interactive Draft Assistant that will estimate
Radiant win probability from validated pregame draft information, recommend
legal candidate heroes, and explain the evidence behind its output. The final
deliverable is a deployed web application, not only a dataset or model.

## Product architecture

```text
Official Liquipedia API
  -> immutable acquisition and provenance
  -> normalized and versioned datasets
  -> canonical supervised training dataset
  -> drift-aware probability modeling
  -> recommendation and explanation engine
  -> inference API
  -> interactive web application
```

The API is an offline data source. The future browser application will never
receive the API credential or call Liquipedia directly.

## Current status

| Stage | Status | Result |
| --- | --- | --- |
| Gate 0: repository consolidation | Complete | The official pipeline is canonical; the earlier Kaggle experiment is preserved under `archive/` and removed from active execution paths. |
| Milestone 1: product and data contract | Complete | Official fields, payload shapes, edge cases, and unavailable semantics were validated with bounded requests. |
| Milestone 2: deterministic data pipeline | Complete | Immutable JSON is parsed into typed objects, normalized, and exported to versioned Parquet datasets. |
| Milestone 3: historical acquisition pilot | Complete | Rate-safe acquisition, caching, checkpoints, deduplication, lineage, coverage, and the supervised contract were proven. |
| Milestone 3.5: bounded historical expansion | Provisional publication complete | The verified contiguous prefix covers 2022-Q1 through 2024-Q1 and contains 9,700 eligible games. |
| Milestone 3.6: dataset completion | Next | Resume the existing campaign through the fixed 2026-07-27 boundary. |
| Milestone 4+: model and product | Planned | Modeling, recommendations, serving, frontend, and deployment have not been implemented. |

The current release is deliberately **provisional**, not the final training
corpus:

```text
m3.5-tier1-tier2-2022q1-2024q1-provisional-v1
  -> release a485f713ffaf94f784ea1c770478be5c172d60285eb8369e294d34d9d447e7da
  -> normalized 6f44f771e75eabffb393f2a3a2bbe27097d4c882d38fbfd10b476fa66dfcae1f
  -> supervised c1ea1d31968eb4c9c6fc4cd8dd7812ca2189694ca94ace48b1aae676e146acd9
```

It contains 4,977 accepted matches, 10,014 normalized games, 9,700 eligible
supervised games, and 314 explicit exclusions. Milestone 3.6 will complete the
approved historical window before final model selection.

## Canonical packages

| Path | Responsibility |
| --- | --- |
| `src/liquipedia_pipeline/` | Immutable loading, typed parsing, deterministic normalization, relational tables, quality observations, and Parquet export. |
| `src/liquipedia_backfill/` | Request planning, guarded API access, immutable cache, SQLite ledger, checkpoints, deduplication, campaign coordination, coverage, and publication. |
| `src/draft_training_dataset/` | Independent `dota-draft-supervised-v1` schema and builder using normalized Parquet only. |

These packages are separate architectural layers, not competing
implementations. `dota-draft-supervised-v1` is the canonical boundary between
data engineering and future model-specific features.

## Canonical entry points

### Offline commands

| Command | Purpose |
| --- | --- |
| `scripts/build_liquipedia_dataset.py` | Build normalized Parquet from saved immutable responses. |
| `scripts/build_draft_training_dataset.py` | Build the canonical supervised release from normalized Parquet. |
| `scripts/plan_liquipedia_history_campaign.py` | Produce and verify credential-free campaign plans and reports. |
| `scripts/publish_historical_dataset.py` | Verify and publish a content-addressed historical release. |
| `scripts/check_repository_hygiene.py` | Reject tracked credentials, raw state, caches, generated builds, and high-confidence secret signatures. |

### Guarded authenticated commands

| Command | Purpose |
| --- | --- |
| `scripts/discover_liquipedia_samples.py` | Bounded representative-sample discovery. |
| `scripts/validate_liquipedia_api.py` | Bounded exact-ID field validation. |
| `scripts/backfill_liquipedia_history.py` | Planned, budget-confirmed historical acquisition and offline finalization. |

Authenticated commands require explicit execution flags and local credentials.
They are never run by tests or CI.

## Quick start

Python 3.12 is the validated local and CI runtime.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/check_repository_hygiene.py
python -m pytest -q
```

Build a normalized dataset from a previously saved response:

```bash
python scripts/build_liquipedia_dataset.py \
  --input data/validation/liquipedia/runs/<run-id>/response.json
```

The build command is offline: it neither reads the API key nor makes a
request.

## Data and credential policy

- `.secrets/`, `.env*`, authenticated responses, raw caches, SQLite state,
  checkpoints, normalized builds, supervised builds, and model artifacts are
  ignored.
- The Liquipedia key remains only in
  `.secrets/liquipedia_api_key`, outside Git.
- Credential-free campaign plans, fingerprints, release manifests, aliases,
  and compact coverage evidence are versioned.
- Saved API responses are immutable inputs. Parser and normalizer stages never
  rewrite them.
- Missing fields remain missing; first pick and global draft order are never
  inferred.

See [`data/README.md`](data/README.md) for the exact public/local boundary.

## Offline validation

The root test suite contains only the active official pipeline. An autouse
pytest policy blocks DNS resolution and outbound sockets, including future
tests accidentally attempting network access. CI runs:

1. dependency consistency;
2. Python compilation;
3. repository and credential hygiene;
4. the complete offline test suite.

A formatter or linter is not yet configured. Gate 0 intentionally did not add
an unreviewed style tool merely to create another CI dependency.

## Historical Kaggle baseline

The original Kaggle-based experiment is preserved under
[`archive/kaggle_baseline/`](archive/kaggle_baseline/README.md). It remains
useful project history, but it is deprecated, excluded from root CI, and must
not be used by the official Draft AI pipeline.

## Product roadmap

1. **Milestone 3.6 — Dataset completion:** finish the fixed official campaign
   through 2026-07-27 and publish a non-provisional release.
2. **Milestone 4 — Draft probability modeling:** compare chronological,
   patch-aware, and recency-aware policies; calibrate and qualify the model on
   recent professional matches.
3. **Milestone 5 — Recommendation and explanations:** score legal candidates
   for a user-declared side-relative draft state without inventing global draft
   order.
4. **Milestone 6 — Inference API:** expose versioned prediction,
   recommendation, hero, model, and health contracts.
5. **Milestone 7 — Interactive application:** build the draft board,
   probability display, recommendation explorer, evidence panels, and
   uncertainty warnings.
6. **Milestone 8 — Deployment:** containerize, deploy, observe, document, and
   demonstrate the complete product.

## Documentation

- [Product and data architecture](docs/MILESTONE_1_PRODUCT_DATA_ARCHITECTURE.md)
- [Validated Liquipedia field contract](docs/MILESTONE_1_LIQUIPEDIA_FIELD_CONTRACT.md)
- [Milestone 2 data pipeline](docs/MILESTONE_2_DATA_PIPELINE.md)
- [Milestone 3 historical backfill](docs/MILESTONE_3_HISTORICAL_BACKFILL.md)
- [Milestone 3.5 design](docs/MILESTONE_3_5_HISTORICAL_EXPANSION_DESIGN.md)
- [Milestone 3.5 bounded publication](docs/milestones/MILESTONE_3_5_BOUNDED_HISTORICAL_DATASET_PUBLICATION.md)
- [Milestone 4 modeling plan](docs/MILESTONE_4_DRAFT_AI_MODELING_PLAN.md)
- [Gate 0 consolidation report](docs/milestones/GATE_0_REPOSITORY_CONSOLIDATION.md)

Every completed milestone or sub-milestone receives a Markdown report under
`docs/milestones/`.
