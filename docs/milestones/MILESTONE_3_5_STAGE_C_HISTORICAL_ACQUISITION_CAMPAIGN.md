# Milestone 3.5 Stage C: Historical Acquisition Campaign

> Generated from the immutable campaign plan, SQLite request ledger, per-run
> checkpoints and manifests, cached-response metadata, normalized manifests,
> supervised manifests, and offline validation results.

Status: **halted at the 2024-Q1 recovery gates**
Report date: 2026-07-28
Campaign: `m3_5_20220101_20260727_e2c4c37a9792`
Source: official Liquipedia API only
Stage D: **not started and not authorized**

## 1. Outcome

The approved compatibility and eligibility changes were implemented narrowly:

- the exact normalized duration sentinel `Default` maps to `None`;
- it does not map to zero;
- no duration is inferred;
- every other unsupported duration remains an error;
- missing normalized duration is now an explicit ineligible condition evaluated
  after every pre-existing exclusion criterion;
- duration remains forbidden as a predictive feature; and
- no API client, parser, schema, target, or other eligibility rule changed.

All eight completed historical quarters and the cached July 2026 pilot were
rebuilt offline through normalized Parquet and
`dota-draft-supervised-v1`. The rebuild made zero authenticated requests,
left the request ledger at 48 rows, and passed the complete raw → assembly →
normalized → supervised lineage gate.

Stage C resumed at `2022-Q3`. Seven Stage C partitions, `2022-Q2` through
`2023-Q4`, are now fully validated. The next partition, `2024-Q1`, returned
eight full pages of 100 records. Because no terminal page was reached before
the approved eight-request partition ceiling, the run entered
`budget_exhausted`. Acquisition stopped immediately.

No `2024-Q2` or later historical partition was requested. The incomplete
`2024-Q1` pages were not assembled, normalized, or included in a supervised
dataset.

## 2. Duration compatibility and eligibility policy

The only implementation change is in
`src/liquipedia_pipeline/normalization.py::parse_duration_seconds`.
After the existing whitespace normalization, `Default` returns `None`.

The tests prove:

- `Default` and its whitespace-wrapped form normalize to `None`;
- `default`, `N/A`, and other unsupported strings remain errors; and
- the observed Q2 placeholder retains its higher-priority existing exclusion
  reason; and
- an otherwise complete game with a null duration is excluded as
  `missing_game_duration`.

The cached source record is:

| Field | Value |
| --- | --- |
| Match | `Q50KVBPsgK_0003` |
| Game | `2` |
| Source duration | `Default` |
| Normalized duration | null |
| Eligibility | excluded |
| Existing exclusion reason | `missing_or_invalid_sides` |

Q2 recovery results:

| Metric | Result |
| --- | ---: |
| New authenticated requests | 0 |
| Cached pages reused | 4 |
| Matches | 357 |
| Games | 764 |
| Eligible games | 754 |
| Excluded games | 10 |
| Eligibility | 98.691099% |
| Normalized fingerprint | `4b5a88b16703131951bc5066decfd96ae3ca4be16b97c6f3a4e50eeaebdff3d5` |
| Supervised fingerprint | `fa6980d55e2913451e7ce175802c823c0749c792b18be18851e5410361891c60` |

### Eligibility-contract update

The approved contract now requires a valid normalized duration for
eligibility. Duration is used only as a gameplay-metadata completeness gate
and remains excluded from draft-model features as post-game information.
The Q2 sentinel game still reports `missing_or_invalid_sides` because the new
duration check is appended last and does not disturb existing first-reason
diagnostics.

The incomplete `2024-Q1` cache contains a counterexample that makes this
distinction concrete: match `OCtGCrWT2m_R02-M004`, game `2`, has duration
`Default`, an explicit winner, both sides, ten picks, and fourteen bans. Under
the approved policy it would be excluded as `missing_game_duration` if the
partition could be normalized and finalized. The record remains unpublished
because `2024-Q1` is incomplete.

Exactly one row in the completed historical corpus changed from eligible to
excluded: match `7vCFkekwDr_0003`, game `2`, in `2023-Q1`. Its blank source
duration normalizes to null and its new reason is `missing_game_duration`.

## 3. Partition results

The table separates completed data from the incomplete budget-exhausted
partition.

| Partition | Stage | Requests | Page records | Matches | Games | Eligible | Excluded | Gate |
| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | --- |
| 2022-Q1 | B canary | 4 | 100/100/100/53 | 353 | 787 | 779 | 8 | Pass |
| 2022-Q2 | C | 4 | 100/100/100/57 | 357 | 764 | 754 | 10 | Pass after cache-only rebuild |
| 2022-Q3 | C | 5 | 100/100/100/100/46 | 446 | 969 | 964 | 5 | Pass |
| 2022-Q4 | C | 3 | 100/100/65 | 265 | 578 | 573 | 5 | Pass |
| 2023-Q1 | C | 6 | 100/100/100/100/100/51 | 551 | 1,224 | 1,222 | 2 | Pass after policy rebuild |
| 2023-Q2 | C | 6 | 100/100/100/100/100/46 | 546 | 1,171 | 1,166 | 5 | Pass |
| 2023-Q3 | C | 5 | 100/100/100/100/21 | 421 | 943 | 921 | 22 | Pass |
| 2023-Q4 | C | 5 | 100/100/100/100/28 | 428 | 826 | 811 | 15 | Pass |
| 2024-Q1 | C | 8 | 100 × 8 | 800 partial records | — | — | — | **Budget exhausted** |

Stage C completed seven partitions. Including the Stage B canary, eight
historical quarters are fully validated. Nine later historical quarters
remain unstarted; the cached July 2026 pilot remains separately complete.

## 4. Request accounting and hard stop

| Scope | Attempts | Notes |
| --- | ---: | --- |
| Stage B canary | 4 | Counts against Milestone 3.5 ceiling |
| Stage C completed partitions | 34 | Q2 2022 through Q4 2023 |
| Incomplete 2024-Q1 | 8 | All HTTP 200; every page had 100 records |
| Stage C total | 42 | 34 complete + 8 incomplete |
| Milestone 3.5 charged total | **46 / 100** | 54 attempts remain |
| July 2026 pilot | 2 | Prior Milestone 3 attempts; excluded from ceiling |
| Complete SQLite history | 48 | Milestone 3.5 plus pilot |

Stage C received 42 HTTP 200 responses, zero 403s, zero 429s, zero API-level
errors, and zero malformed responses. It made no automatic retry and recorded
no acquisition cache hit. The Q2 offline rebuild reused cache bytes outside
the acquisition loop, so it correctly added neither an HTTP request nor a
cache-hit ledger event.

The authoritative `2024-Q1` stop state is:

| Field | Value |
| --- | --- |
| Run ID | `m3_20240101_20240401_4aa59da8deab` |
| Status | `budget_exhausted` |
| Requests | 8 of 8 |
| Partial records | 800 |
| Terminal page | not reached |
| Resume sequence | 9 |
| Resume offset | 800 |
| Checkpoint SHA-256 | `b2a1c86ef486047a73cb64e9868ae23edb42e81417210ee0edd04a4e795c6110` |

The eight cached response SHA-256 values are:

1. `97620ce703a96f4d5441b92adfd0d1940a04fffbc3c81e3ac572115bf8613f67`
2. `55767332b49409129d9141fad66e2ed094bd94a7fd7830138d9851e1e6918bb7`
3. `b5d17cafce179d8bd6aa6285f7a14d1df8e44031c409ee457c4a215cee1ab4bf`
4. `407362909722e42512813f2af916e5fe77acd95ed52675eb42e52b9e46ec94ca`
5. `ab8a7135fe34faa0ac124c0b8ee722044693f8406d576a335e77071221f5f121`
6. `95a21b0164f2f2fed4dfc8f69aa8ad32177ce3b1dd091f6c49a75ca62a2e1ce1`
7. `158b4c0bbe85b4cccf7c3ff83b2c05be596f5f7a71da5c9856063bf1ed58e3c0`
8. `91b61bbd141d3841af969b12af2623b4166d7c28ab140134311d317fe7e69220`

The checkpoint, SQLite ledger, cache metadata, response bytes, request
hashes, response hashes, record counts, and HTTP outcomes agree.

The cached prefix also contains four non-missing duration strings that remain
outside the strict normalizer contract:

| Match | Game | Source value |
| --- | ---: | --- |
| `D8VM7QJos8_R04-M001` | 3 | `<s>Game 3</s>` |
| `D8VM7QJos8_R04-M003` | 3 | `<s>Game 3</s>` |
| `D8VM7QJos8_R05-M002` | 3 | `7m04` |
| `D8VM7QJos8_R06-M001` | 5 | `<s>Game 5</s>` |

These are not missing values and are not the approved `Default` sentinel.
The policy update therefore does not authorize their coercion.

## 5. Completed dataset coverage

### Stage C completed scope

For `2022-Q2` through `2023-Q4`:

| Metric | Result |
| --- | ---: |
| Accepted and normalized matches | 3,014 |
| Normalized games | 6,475 |
| Eligible supervised games | 6,411 |
| Excluded games | 64 |
| Eligibility | **99.011583%** |
| Radiant wins | 3,095 |
| Radiant losses | 3,316 |
| Radiant win share | 48.276400% |
| Distinct tournaments | 112 |
| Date range | 2022-04-01 19:05 UTC to 2023-12-17 08:00 UTC |

Exclusions use only established reasons:

| Reason | Games |
| --- | ---: |
| `incomplete_team1_bans` | 7 |
| `incomplete_team1_picks` | 19 |
| `incomplete_team2_bans` | 5 |
| `invalid_game_result` | 10 |
| `invalid_series_result` | 5 |
| `missing_game_duration` | 1 |
| `missing_or_invalid_sides` | 17 |

### Completed historical scope including Stage B

For `2022-Q1` through `2023-Q4`:

| Metric | Result |
| --- | ---: |
| Accepted and normalized matches | 3,367 |
| Normalized games | 7,262 |
| Eligible supervised games | 7,190 |
| Excluded games | 72 |
| Eligibility | **99.008538%** |
| Radiant wins / losses | 3,474 / 3,716 |
| Distinct tournaments | 129 |
| Union-distinct heroes | 124 |
| Date range | 2022-01-03 04:55 UTC to 2023-12-17 08:00 UTC |

Coverage by year:

| Year | Matches | Games | Eligible | Excluded | Eligibility |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2022 | 1,421 | 3,098 | 3,070 | 28 | 99.096191% |
| 2023 | 1,946 | 4,164 | 4,120 | 44 | 98.943324% |

Coverage by tier:

| Tier | Matches | Games | Eligible | Excluded |
| --- | ---: | ---: | ---: | ---: |
| 1 | 1,697 | 3,535 | 3,489 | 46 |
| 2 | 1,670 | 3,727 | 3,701 | 26 |

The completed history contains 18 known patch labels from `7.30e` through
`7.34e`; 7,187 of 7,262 games have a known patch (98.967227%). Seventy-five
games preserve a missing patch rather than inventing one. Full patch and
tournament coverage is stored in the machine-readable summary and the
per-partition coverage Parquet reports.

These are provisional sums and union-based audits of independently built
partitions. They are not a Stage D aggregate dataset, release alias, or
canonical aggregate fingerprint.

## 6. Deduplication, cache, and lineage

The explicit manifest-driven cross-partition audit found:

- zero duplicated match IDs;
- zero conflicting match payloads;
- zero duplicated game lineage keys;
- zero conflicting game payloads;
- zero duplicate normalized game keys;
- zero duplicate supervised `sample_id` or `game_key` values;
- zero quarantine rows; and
- zero missing source-game IDs.

Every accepted match maps to one normalized match. Every normalized game maps
to exactly one eligible or excluded supervised audit row.

Across the eight completed historical partitions and cached pilot, 135
artifact SHA-256 checks passed with zero mismatch. Every
assembly → snapshot → normalized → supervised chain was verified.

Audit catalog fingerprints:

| Scope | Fingerprint |
| --- | --- |
| Stage C completed partitions | `b63aad432598b4725508e4a20922125e89f5e2d481d9d42e45cd419a2d0dea8b` |
| Completed historical scope | `1de36d811a6b7d396bb7a29b9eb49f37d78eec2d0c018c5f39e0e0af9e135e81` |
| Completed history plus pilot | `04e33e299d132bbb6ccb67229309774be335ad4356943c12be85835d2b7ea855` |

Each partition's acquisition, assembly, snapshot, normalized, and supervised
fingerprints are recorded in
`data/backfill/campaigns/m3_5_20220101_20260727_e2c4c37a9792/stage_c_acquisition_summary.json`.

## 7. Rate-limit observations

| Control | Result |
| --- | ---: |
| Configured interval | 67 seconds |
| Rolling-hour limit | 54 attempts |
| Maximum observed in any rolling hour | 38 |
| Rolling-hour headroom | 16 |
| HTTP 429 responses | 0 |
| Automatic retries | 0 |

The minimum ledger delta was `66.985433` seconds, `0.014567` seconds below
the configured interval. Four deltas across Stage B and Stage C were slightly
below 67 seconds. This is the explicitly approved, known non-blocking
operational issue. No rolling-hour violation or rate-limit response occurred,
so no rate-limiter hardening was introduced.

## 8. Test and validation results

The final offline suite:

```text
.........................................................                [100%]
57 passed in 6.19s
```

Additional evidence:

- every completed partition passed its raw/cache/ledger/checkpoint gate;
- every completed partition passed assembly, normalized schema, table-hash,
  supervised lineage, leakage, eligibility, and known-exclusion checks;
- all eight completed historical partitions and the pilot passed a final
  cache-only policy rebuild and revalidation;
- no trainable normalized row has null `duration_seconds`;
- the supervised builder rejects stale normalized input marked trainable with
  null duration;
- the final report audit read no API credential; and
- no authenticated request was made after the `2024-Q1` hard stop.

## 9. Commands executed

Offline policy rebuild and validation used the following exact command shape
for each completed historical partition:

```bash
.venv/bin/python scripts/backfill_liquipedia_history.py \
  --start <inclusive-quarter-start> \
  --end <exclusive-quarter-end> \
  --tier 1 --tier 2 \
  --page-size 100 --max-requests 8 \
  --hourly-limit 54 --request-interval-seconds 67 \
  --finalize

.venv/bin/python scripts/build_draft_training_dataset.py \
  --normalized-build data/processed/liquipedia/build_<normalized-fingerprint-prefix>
```

The cached July 2026 pilot used the same commands with
`--start 2026-07-01T00:00:00Z`,
`--end 2026-07-27T00:00:00Z`, and `--max-requests 4`. No rebuild command
included `--execute`.

Validation then ran:

```bash
.venv/bin/python /private/tmp/validate_duration_policy_rebuild.py
.venv/bin/python -m pytest -q
.venv/bin/python scripts/plan_liquipedia_history_campaign.py \
  --check-partition-readiness 2024-Q1
```

The temporary validator was an operational audit helper and was removed after
the report was generated; the permanent test coverage remains in `tests/`.

For each subsequent partition, the coordinator first ran:

```bash
.venv/bin/python scripts/plan_liquipedia_history_campaign.py \
  --check-partition-readiness <partition>
```

It then executed the unchanged acquisition contract once:

```bash
.venv/bin/python scripts/backfill_liquipedia_history.py \
  --start <inclusive-quarter-start> \
  --end <exclusive-quarter-end> \
  --tier 1 --tier 2 \
  --page-size 100 --max-requests 8 \
  --hourly-limit 54 --request-interval-seconds 67 \
  --timeout-seconds 30 \
  --execute --confirm-live-request-budget 8
```

Successful partitions were finalized, converted to
`dota-draft-supervised-v1`, validated, and followed by the full test suite.
The coordinator exited nonzero at `2024-Q1` and did not invoke another
partition.

## 10. Deviations, warnings, and limitations

- **Resolved compatibility issue:** `Default` is now an explicit unavailable
  duration sentinel. No other unexpected duration is accepted.
- **Approved eligibility update:** missing duration is now an explicit
  ineligible condition, evaluated last. Exactly one completed historical game
  changed from eligible to `missing_game_duration`.
- **Expected hard stop:** `2024-Q1` exceeded the fixed partition page budget.
  The campaign-level budget was not exhausted.
- **Strict-format recovery gate:** the cached `2024-Q1` prefix contains four
  unsupported non-missing duration strings (`<s>Game 3</s>`,
  `<s>Game 5</s>`, and `7m04`). The parser continues to reject them.
- **Known timing issue:** a few ledger deltas are milliseconds below 67
  seconds, with no rolling-hour or HTTP-rate-limit breach.
- **Incomplete scope:** 2024-Q1 and nine later historical quarters do not
  contribute normalized or supervised rows.
- **Historical preflight:** `campaign_preflight.json` remains Stage A
  preflight evidence; it is not the current Stage C state authority.
- **No Stage D claim:** no global assembly, global dataset fingerprint,
  release alias, feature engineering, split, model, backend, or frontend was
  created.

## 11. Machine-readable evidence and approval boundary

The updated credential-free machine summary is:

`data/backfill/campaigns/m3_5_20220101_20260727_e2c4c37a9792/stage_c_acquisition_summary.json`

Its SHA-256 is:

`e2cd5bc84ddb650db02438e2a2ba2e3da5bb35970219daf41d3152822933d974`

The current authoritative operational state is the SQLite ledger plus the
per-run checkpoints and immutable cache. The machine summary is their
credential-free reporting projection.

Stage C stops here. Further authenticated acquisition requires a separately
approved recovery plan for `2024-Q1`—either a larger per-partition budget or a
smaller documented partition split. Finalization also requires an explicit
compatibility decision for the four unsupported non-missing duration strings;
this update intentionally did not coerce them.

Stage D remains unapproved and must not begin.
