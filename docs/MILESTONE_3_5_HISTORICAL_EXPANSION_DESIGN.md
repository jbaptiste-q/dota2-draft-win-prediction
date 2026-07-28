# Milestone 3.5: Historical Expansion Design

Status: design complete; Stage C halted at the 2024-Q1 recovery gates
Report date: 2026-07-28
Historical scope: `2022-01-01T00:00:00Z` inclusive to
`2026-07-27T00:00:00Z` exclusive
Source: official Liquipedia API only
Acquisition contract: `liquipedia-history-v1`
Normalized schema: `liquipedia-dota-draft-v1`
Supervised schema: `dota-draft-supervised-v1`

## 1. Outcome

Milestone 3.5 has a bounded design for expanding the validated Milestone 3
pilot into a useful professional Dota 2 training corpus without changing the
established data contracts.

The expansion will:

- acquire completed Tier 1 and Tier 2 matches in calendar-quarter partitions;
- reuse the existing immutable cache, SQLite ledger, checkpoints, parser,
  normalizer, and supervised-dataset builder;
- validate every partition before it can contribute to the aggregate dataset;
- preserve an auditable raw-to-supervised fingerprint chain; and
- stop before feature engineering, model training, dataset splitting, backend
  work, or frontend work.

This document is the approved design authority. Stage A, the bounded Stage B
canary, and the approved portion of Stage C have been executed under separate
approvals. It does not authorize recovery from the current Stage C hard stop
or Stage D.

## 2. Relationship to adjacent milestones

| Milestone | Responsibility | Explicit boundary |
| --- | --- | --- |
| Milestone 3 | Proved bounded, resumable acquisition and the complete raw → normalized → supervised lineage with a small live pilot. | It did not build a historical-scale corpus. |
| Milestone 3.5 | Repeats the validated process over a bounded historical range and publishes one aggregate canonical dataset. | It does not create model-specific features, splits, or models. |
| Milestone 4 | Defines evaluation policy, temporal splits, baselines, feature transformations, experiments, and model selection. | It consumes the canonical supervised dataset and does not reacquire source data. |

Milestone 3.5 is a scaling exercise, not a redesign. New abstractions are
justified only when they coordinate existing partition runs or aggregate their
validated outputs.

## 3. Validated baseline

The Milestone 3 pilot used the official `match` endpoint for completed Tier 1
and Tier 2 matches from `2026-07-01T00:00:00Z` through
`2026-07-27T00:00:00Z`, exclusive.

| Pilot result | Value |
| --- | ---: |
| HTTP attempts | 2 |
| Successful responses | 2 |
| Returned matches | 108 |
| Normalized games | 261 |
| Eligible supervised games | 232 |
| Excluded supervised games | 29 |
| Eligibility percentage | 88.888889% |
| Duplicate matches or games | 0 |
| Conflicted or quarantined records | 0 |
| Full offline test suite | 36 passed |

The pilot established that the request contract, immutable cache, ledger,
checkpoint, normalization pipeline, reporting, and
`dota-draft-supervised-v1` builder work together. Historical expansion should
reuse those components unchanged unless a reproducible defect is found.

## 4. Historical scope

### 4.1 Recommended range

The initial expansion covers:

```text
[2022-01-01T00:00:00Z, 2026-07-27T00:00:00Z)
```

Only completed professional matches with Liquipedia tier `1` or `2` are in
scope.

This range is recommended because it provides several years of modern Dota 2
patch and tournament variation while avoiding an immediate commitment to
legacy eras whose draft rules, hero identifiers, and payload completeness may
produce lower-value complexity. Earlier history can be evaluated later from
coverage evidence rather than assumed to be necessary.

The upper bound is fixed, not “now,” so the build remains reproducible.

### 4.2 Partitioning

Use half-open calendar-quarter partitions:

```text
[quarter_start, next_quarter_start)
```

The campaign contains 19 logical partitions:

- 18 new full quarters from 2022-Q1 through 2026-Q2; and
- the exact cached Milestone 3 pilot partition from 2026-07-01 through
  2026-07-27.

The existing pilot must be reused by its exact request hashes and must not be
requested again.

Quarterly partitions are small enough for review and recovery, large enough to
avoid orchestration overhead, and naturally support coverage reporting. Patch
is metadata and a reporting dimension, not an acquisition partition key,
because patches do not align cleanly with time windows and nested patch
availability varies.

## 5. Request contract and sequence

Every new partition uses the already validated contract:

| Setting | Value |
| --- | --- |
| Method and endpoint | `GET https://api.liquipedia.net/api/v3/match` |
| Wiki | `dota2` |
| Match state | `finished=1` |
| Tiers | `1`, `2` |
| Page size | `100` |
| Ordering | `date ASC, match2id ASC` |
| Projection | Unchanged validated Milestone 3 projection |
| Pagination | Offsets `0`, `100`, `200`, ... |
| Automatic retries | `0` |

For each partition:

1. Build the exact credential-free request plan offline.
2. Compare the plan and its hashes with the approved campaign manifest.
3. Check the immutable cache before any network operation.
4. Request offset `0` only when no valid cache entry exists.
5. Request the next offset only when the accepted page contains exactly 100
   records.
6. Mark the partition complete when a page contains fewer than 100 records.
7. Stop at the partition or campaign request budget without silently widening
   either limit.

No server-side patch filter, unrelated hydration endpoint, HTML page, or
undocumented query is introduced.

## 6. Estimated request budget

The pilot returned 108 matches in two pages across 26 days. Straight-line
extrapolation is not reliable because tournament density is seasonal, so the
campaign should use a range rather than a false exact count.

| Estimate | Value |
| --- | ---: |
| Expected matches | 5,500–8,000 |
| Expected normalized games | 13,000–19,000 |
| Expected eligible supervised games | 10,000–15,000 |
| Expected total successful pages | 75–95 |
| Hard maximum additional HTTP attempts | 100 |
| Maximum attempts for one new quarter | 8 |
| Requests needed for cached pilot | 0 |

All HTTP attempts count against the budgets, including failed or malformed
responses. Cache hits do not.

The expected counts are planning ranges, not success gates. Data quality and
lineage matter more than reaching a round row-count target.

## 7. Rate limiting

The expansion retains the validated conservative policy:

- one active requester;
- at least 67 seconds between live request starts;
- no more than 54 attempts in any rolling hour across runs sharing the state
  database;
- no automatic retries; and
- persistent attempt accounting written before network I/O.

There is no benefit to concurrency for a campaign of approximately 100
requests. Serial execution is easier to audit and remains safely below the
documented limit.

## 8. Checkpoint, resume, and cache reuse

### 8.1 Source of truth

The existing SQLite database remains the transactional source of truth for:

- request attempts and outcomes;
- global rolling-hour rate history;
- accepted pages;
- request and response hashes;
- cache references; and
- run and partition state.

Human-readable JSON checkpoints and Markdown status reports are derived audit
artifacts. A second state system is not required.

### 8.2 Campaign coordination

A thin campaign plan may coordinate the existing partition runner. It should
record:

- campaign ID and immutable configuration hash;
- ordered partition IDs and half-open time bounds;
- exact request plans and maximum budgets;
- cached, pending, active, complete, failed, and blocked states;
- partition acquisition and build fingerprints; and
- aggregate build fingerprints after all gates pass.

The coordinator must not duplicate HTTP, parsing, normalization, or dataset
logic.

### 8.3 Resume behavior

On restart:

1. Verify campaign configuration and plan hashes.
2. Read SQLite state and verify every referenced cached response.
3. Reuse successful pages whose request and response hashes match.
4. Resume at the first unfinished offset in the first unfinished partition.
5. Preserve failed attempts in the request budget and ledger.

Successful cached bytes are immutable. A checksum mismatch or different
response for an already successful request is a hard stop, not an overwrite.

## 9. Failure recovery

The whole campaign stops for:

- authentication failure;
- HTTP `403` or `429`;
- malformed JSON or an API-level error;
- a response that conflicts with the approved request contract;
- a cache or metadata checksum mismatch;
- an out-of-scope returned record;
- an unresolved conflicting match or game version;
- any quarantined record;
- an identity duplicate that is not an exact payload duplicate;
- partition or campaign request-budget exhaustion; or
- a broken raw → normalized → supervised lineage check.

Recovery is evidence-driven:

1. Preserve the response bytes, redacted error, ledger row, and checkpoint.
2. Diagnose the failure without modifying cached successful pages.
3. Make a minimal correction only if the defect is reproducible and documented.
4. Run the complete offline suite.
5. Regenerate the request plan when the correction changes a request hash.
6. Obtain approval before resuming live acquisition when the approved contract
   or budget would change.

There are no hidden retries or automatic skips.

## 10. Per-partition validation gates

A partition contributes to the historical dataset only after all required
checks pass.

### 10.1 Request and scope

- Actual HTTP attempts do not exceed the approved partition budget.
- Every ledger entry maps to a planned request hash.
- Dates fall within the half-open partition.
- Every record is Tier 1 or Tier 2 and completed.
- Pagination terminates with a short page.

### 10.2 Raw acquisition

- Response bytes match recorded SHA-256 hashes.
- Cache metadata is complete and contains no credential.
- Record counts agree across response, metadata, ledger, and checkpoint.
- No successful request hash has incompatible response bytes.

### 10.3 Assembly

- Stable source identifiers are present for accepted records.
- Exact duplicates collapse deterministically.
- Accepted, duplicate, conflicted, and quarantined counts reconcile.
- Conflict and quarantine counts are zero.
- Every accepted match and game maps back to a raw response hash.

### 10.4 Normalization

- The unchanged Milestone 2 pipeline completes.
- Manifest checksums and row counts verify.
- Match, team, player, game, hero, pick, and ban relationships are internally
  consistent.
- Missing legacy fields remain missing; no first-pick or global draft order is
  inferred.

### 10.5 Supervised dataset

- The builder reads only normalized Parquet.
- Schema is exactly `dota-draft-supervised-v1`.
- Every eligible row has explicit sides, a valid winner, five picks and seven
  bans per side, no duplicate picked hero, and a valid non-missing normalized
  duration.
- Exclusion reasons and counts reconcile with normalized eligibility.
- Forbidden leakage columns are absent; duration is an eligibility gate only
  and remains forbidden as a model feature.
- Target distribution, date range, patches, tiers, and tournaments are
  reported.

### 10.6 Review thresholds

These thresholds trigger review rather than automatic rejection:

- eligibility below 70%;
- known patch coverage below 95%;
- known winner or side coverage below 80%;
- a partition with zero matches;
- a previously unseen exclusion reason; or
- an abrupt payload-shape or row-count change.

A threshold should not be relaxed automatically. It is a signal to inspect the
official data and determine whether the partition is valid but unusual.

## 11. Dataset assembly and versioning

After all partitions pass:

1. Assemble accepted raw records using the existing deterministic
   deduplication rules.
2. Pass all accepted partition snapshots together to the unchanged Milestone 2
   `run_pipeline(...)` entry point.
3. Build one aggregate normalized dataset.
4. Build `dota-draft-supervised-v1` only from that aggregate normalized
   dataset.
5. Verify every checksum and fingerprint link.

Parquet files must not be merged manually. Rebuilding through the established
pipeline prevents schema drift and produces one coherent manifest.

The machine contracts remain:

- acquisition: `liquipedia-history-v1`;
- normalized: `liquipedia-dota-draft-v1`; and
- supervised: `dota-draft-supervised-v1`.

The first human-readable release alias is:

```text
m3.5-tier1-tier2-2022-2026-v1
```

The alias points to content-addressed artifacts; it does not replace their
fingerprints. Any source-byte, accepted-record, pipeline-code, schema, or
environment change produces a new fingerprint.

Temporal metadata and source-match grouping remain in the supervised dataset.
No train, validation, or test split is published in this milestone.

## 12. Expected deliverables

### Design and planning

- this design report;
- immutable campaign configuration;
- machine-readable and Markdown request plans;
- partition inventory and request-hash index; and
- a preflight report proving zero authenticated requests during planning.

### Acquisition

- verified immutable raw cache entries;
- shared SQLite request ledger;
- per-partition checkpoints and manifests;
- campaign status and request-accounting reports; and
- accepted-record snapshots with provenance indices.

### Processed data

- one aggregate `liquipedia-dota-draft-v1` build;
- coverage reports by year, patch, tier, and tournament;
- eligibility-failure reports;
- one aggregate `dota-draft-supervised-v1` build;
- exclusions and hero-vocabulary datasets;
- data card, schema, quality report, and manifest; and
- complete raw → normalized → supervised lineage and fingerprints.

### Verification

- per-partition validation results;
- aggregate reconciliation report;
- full offline test results; and
- final milestone completion report containing commands, counts, hashes,
  deviations, warnings, and limitations.

## 13. Execution stages and approval boundaries

### Stage A: offline campaign planning

Implement only the thin campaign coordinator and offline tests. Generate the
exact partition plans, request hashes, checkpoint paths, cache layout, and
budgets. Make zero authenticated requests.

### Stage B: historical canary

After separate approval, execute only 2022-Q1. The expected request count is
3–6 with a hard maximum of 8. Finalize and validate that partition through the
supervised layer, run the full offline suite, report results, and stop for
review.

### Stage C: remaining acquisition campaign

After canary approval, execute the remaining approved partitions serially.
Continue only while validation gates pass and the 100-attempt campaign budget
remains intact.

### Stage D: aggregate publication

Assemble all validated partitions, publish the content-addressed normalized
and supervised builds, verify lineage, run the full offline suite, and produce
the completion report.

The design avoids a separate approval after every healthy quarter. The canary
provides the meaningful historical-schema gate; deterministic checks and
hard-stop rules then govern the approved campaign.

## 14. Success criteria

Milestone 3.5 is complete only when:

1. All 19 logical partitions are complete, including verified cache reuse of
   the Milestone 3 pilot.
2. No more than 100 additional live HTTP attempts were made.
3. Every attempt, cache hit, page, raw hash, and partition outcome is recorded.
4. There are no unresolved conflicts, quarantined records, or incompatible
   successful responses.
5. One aggregate normalized build covers the fixed 2022–2026 window.
6. One aggregate supervised build exactly satisfies
   `dota-draft-supervised-v1`.
7. Coverage, exclusions, class balance, and lineage reconcile at partition and
   aggregate levels.
8. The full fingerprint chain verifies from raw responses through supervised
   Parquet.
9. The full offline test suite passes.
10. No model feature transformation, split policy, training, inference,
    backend, or frontend work has entered the milestone.

Ten thousand eligible games is a useful planning target, not a condition that
justifies weaker data rules or unnecessarily old history.

## 15. Complexity decisions

The following tempting additions are deliberately rejected for the initial
historical expansion:

- **Airflow, Dagster, Prefect, Kafka, or distributed workers:** the campaign is
  too small to justify operational infrastructure. A deterministic CLI and
  SQLite ledger demonstrate the relevant engineering properties more clearly.
- **PostgreSQL as a control plane:** the existing local state store already
  supplies transactions, resume behavior, and auditability.
- **Patch-based acquisition partitions:** time partitions are stable and
  mutually exclusive; patch remains a downstream coverage dimension.
- **Per-quarter manual approval:** one historical canary plus strict automated
  gates provides equivalent safety with less ceremony.
- **Additional API hydration calls:** the validated match payload already
  supports the approved supervised contract.
- **All available historical years immediately:** older records should be
  added only if Milestone 4 demonstrates that the modern corpus is
  insufficient or a deliberate legacy-robustness experiment needs them.
- **A new aggregate processing path:** the existing normalization and
  supervised builders are the reproducibility boundary and should remain the
  only publication path.

This is the smallest design that demonstrates rate-safe acquisition,
recoverability, data contracts, deterministic dataset publication, and
production-minded quality gates at portfolio scale.

## 16. Current approval boundary

Stage A implemented this design's offline campaign planning and coordination
layer. Its immutable plan, cached-pilot proof, tests, and generated
Definition-of-Done report are documented in
[`docs/milestones/MILESTONE_3_5_STAGE_A_OFFLINE_CAMPAIGN_PLANNING.md`](milestones/MILESTONE_3_5_STAGE_A_OFFLINE_CAMPAIGN_PLANNING.md).

Stage B then executed only the approved 2022-Q1 canary and validated it
through `dota-draft-supervised-v1`. The data-contract and lineage gates
passed. The request ledger exposed a near-boundary rate-control timing issue:
its minimum recorded interval was `66.985433` seconds rather than at least
`67.000000`. The complete evidence and compatibility analysis are documented
in
[`docs/milestones/MILESTONE_3_5_STAGE_B_HISTORICAL_CANARY.md`](milestones/MILESTONE_3_5_STAGE_B_HISTORICAL_CANARY.md).

Stage C was authorized after the Stage B data-compatibility review. A minimal
compatibility change treats the exact official duration sentinel `"Default"`
as unavailable. The subsequently approved eligibility policy requires a
valid normalized duration, so missing duration—including `Default` normalized
to null—is ineligible without being replaced by zero or an inferred value.
Duration remains forbidden as a model feature, and every other eligibility
criterion is unchanged.

All completed cached partitions—`2022-Q1` through `2023-Q4` plus the July
2026 pilot—were rebuilt through normalized and supervised outputs entirely
offline. Their request ledgers and immutable raw caches were unchanged, and
the rebuilt datasets passed the existing validation gates.

`2024-Q1` then returned eight full pages without reaching a terminal page.
The campaign stopped at the approved eight-request partition ceiling. Its
partial cache also contains four unsupported non-missing duration strings.
They remain strict normalization errors because parser behavior was not
broadened. No later historical partition was requested. Evidence is
documented in
[`docs/milestones/MILESTONE_3_5_STAGE_C_HISTORICAL_ACQUISITION_CAMPAIGN.md`](milestones/MILESTONE_3_5_STAGE_C_HISTORICAL_ACQUISITION_CAMPAIGN.md).

Further authenticated acquisition and Stage D remain unauthorized pending an
explicit `2024-Q1` recovery review covering both its exhausted immutable
per-partition request budget and the unsupported duration values.
