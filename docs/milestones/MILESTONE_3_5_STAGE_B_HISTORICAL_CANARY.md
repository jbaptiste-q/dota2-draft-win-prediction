# Milestone 3.5 Stage B: Historical Canary

> Definition-of-Done evidence artifact generated from the local request
> ledger, immutable cache metadata, manifests, Parquet reports, and offline
> validation output.

Report schema: `milestone-report-v1`
Report date: 2026-07-28
Status: **data canary complete; Stage C blocked pending review of one
rate-control compatibility issue**
Campaign ID: `m3_5_20220101_20260727_e2c4c37a9792`
Partition: `2022-Q1`
Run ID: `m3_20220101_20220401_36bbf248c8cf`

## 1. Outcome

The bounded 2022-Q1 historical canary completed through the complete
raw → acquisition snapshot → normalized relational dataset → canonical
supervised dataset lineage.

The historical payload compatibility objective passed:

- 4 authenticated requests returned HTTP 200;
- 353 completed Tier 1/2 matches were returned in scope;
- 353 matches and 787 games were accepted;
- no duplicate, conflicting, or quarantined record was produced;
- the unchanged `liquipedia-dota-draft-v1` pipeline completed;
- 779 of 787 games are eligible for `dota-draft-supervised-v1`;
- all lineage and artifact checksums reconcile; and
- the complete offline suite passes with 53 tests.

Stage C was not executed. No partition after 2022-Q1 was requested.

One operational compatibility issue requires review before another live
request. The ledger records request-start intervals of `66.985433`,
`66.999675`, and `67.005450` seconds. The minimum is approximately 15 ms
below the configured 67-second floor. The rolling-hour limit was still
satisfied, no rate-limit response occurred, and the acquired data remains
valid. However, the current wall-clock sleep implementation does not provide
strict evidence that every start is at least 67.000000 seconds apart.

No acquisition code was changed during Stage B. A minimal rate-limiter
hardening should be reviewed and approved before Stage C.

## 2. Scope boundary

Included:

- the approved half-open window
  `[2022-01-01T00:00:00Z, 2022-04-01T00:00:00Z)`;
- completed Liquipedia Tier 1 and Tier 2 matches only;
- the exact approved `/api/v3/match` projection, ordering, pagination,
  request hashes, and eight-attempt partition ceiling;
- immutable cache, ledger, checkpoint, snapshot, normalization, coverage,
  supervised dataset, lineage, and test validation; and
- this mandatory Stage B report.

Excluded:

- all other historical partitions;
- Stage C campaign execution;
- aggregate historical publication;
- changes to the API client, parser, normalizer, or supervised builder;
- feature engineering, splitting, model training, inference, backend, and
  frontend work.

## 3. Approved acquisition contract

| Field | Value |
| --- | --- |
| Endpoint | `GET https://api.liquipedia.net/api/v3/match` |
| Wiki | `dota2` |
| Time range | `2022-01-01T00:00:00Z` inclusive to `2022-04-01T00:00:00Z` exclusive |
| Tiers | `1`, `2` |
| Completion filter | `finished::1` |
| Ordering | `date ASC, match2id ASC` |
| Page size | 100 |
| Expected requests | 3–6 |
| Hard partition ceiling | 8 attempts |
| Campaign ceiling | 100 additional attempts |
| Automatic retries | None |
| Configured request interval | 67 seconds |
| Rolling-hour limit | 54 attempts |
| Timeout | 30 seconds |
| Configuration hash | `36bbf248c8cfc2fe9c7505af9eabedcb2c39f31a9dbe7c424eb57e9b2257f477` |

The executed request hashes are the first four hashes in the immutable
2022-Q1 plan. The fourth page contained 53 records and was terminal, so
conditional request slots 5–8 were not needed.

## 4. Live request evidence

| Seq. | Offset | Start UTC | Request hash | HTTP | Records | Response bytes | Response SHA-256 | Final |
| ---: | ---: | --- | --- | ---: | ---: | ---: | --- | --- |
| 1 | 0 | `2026-07-28T10:57:17.999228+00:00` | `a1d14b750bc61ccb403aa57ecb1276e0aeefffebfbbb9ee84435c810fafcf621` | 200 | 100 | 593,865 | `1421bf9a2a1f2ba225be85d729c6624204c18d2a926c4b0cc9139450b5140417` | No |
| 2 | 100 | `2026-07-28T10:58:24.984661+00:00` | `6fdcd3580cd1eb1ad6ce121e1367036cb723de488f4d5d92bebded1e1ea6d36a` | 200 | 100 | 597,969 | `3cd6f7ee162dac21b91bc1ef22efe6d77b3a9ffdfe54ae5e2978315d8b48ab2a` | No |
| 3 | 200 | `2026-07-28T10:59:31.984336+00:00` | `7eec2a674958ad83cd0a7e6f1417d5c33f9b5e2619a138bd58f69aeb2d204381` | 200 | 100 | 558,433 | `26226331cd0ed1161ca89443203f8dcfe39d2ff020e587eae4d1fd3dbddcb0a3` | No |
| 4 | 300 | `2026-07-28T11:00:38.989786+00:00` | `67987592fcc87df00a8afcdc02698878fa4646c8f5bd90c0de9d05aa49875495` | 200 | 53 | 316,609 | `357d4c40ebd61a3f42c1c0565fccdc748a737b9e69b2b57c60e3d13be883b54e` | Yes |

Request summary:

- actual HTTP attempts: **4**;
- successful HTTP 200 outcomes: **4**;
- cache hits during the canary: **0**;
- retries: **0**;
- API, authentication, malformed-response, 403, and 429 errors: **0**;
- returned records: **353**;
- response bytes: **2,066,876**;
- partition budget used: **4 / 8**; and
- campaign budget used: **4 / 100**, leaving **96**.

The live runner read the local credential only for the approved acquisition.
The credential was not printed, embedded in a URL, written to cache metadata,
or persisted in any generated artifact. Finalization, reporting, validation,
and tests did not read the credential and made zero authenticated requests.

## 5. Rate-control review

| Interval | Recorded seconds | 67-second floor |
| --- | ---: | --- |
| Request 1 → 2 | 66.985433 | Below by 0.014567 |
| Request 2 → 3 | 66.999675 | Below by 0.000325 |
| Request 3 → 4 | 67.005450 | Pass |

The existing rate limiter computes a wall-clock wait, sleeps once, and then
records another wall-clock timestamp before network I/O. It does not recheck
the remaining interval after sleep and does not use a monotonic deadline.
Scheduler or wall-clock movement can therefore produce a ledger delta
slightly below the configured floor.

This did not exceed the conservative 54-attempt rolling-hour policy and did
not produce a server-side rate-limit response. It is nevertheless a strict
contract-evidence gap. Stage C remains blocked until the project reviews a
minimal fix such as a monotonic deadline plus a post-sleep recheck or a small
explicit safety margin. This report does not authorize or implement that
change.

## 6. Scope and raw-data validation

All 353 raw records passed the approved source-scope checks:

| Check | Result |
| --- | ---: |
| Earliest source date | `2022-01-03T04:55:00Z` |
| Latest source date | `2022-03-31T22:10:00Z` |
| Out-of-range records | 0 |
| Tier 1 records | 27 |
| Tier 2 records | 326 |
| Other tiers | 0 |
| `finished != 1` | 0 |
| Missing stable match IDs | 0 |
| Duplicate stable match IDs | 0 |
| Ordering violations | 0 |

For every page, the response byte hash, cache metadata, request ledger,
checkpoint, and accepted-page index agree on the request hash, response hash,
offset, record count, and terminal state. Cache metadata contains no
credential or authorization header.

## 7. Assembly result

| Metric | Count |
| --- | ---: |
| Raw pages | 4 |
| Record occurrences | 353 |
| Accepted matches | 353 |
| Accepted games | 787 |
| Exact duplicate matches | 0 |
| Exact duplicate games | 0 |
| Conflicts | 0 |
| Quarantined records | 0 |

Six completed, forfeit-tagged matches contain no game payloads. They are
preserved as matches, but no games are invented:

- `qELspEgBuo_0002`
- `E7aPTt9t18_0001`
- `dC5BL0cQid_0001`
- `N0OHDKWflr_0002`
- `LnUHhCgSnQ_0001`
- `DPC2122SE1_0005`

Assembly fingerprint:
`79d921a5e899a88cc34d5c66b4888d681f8f71ad64f3c1bc10fd25c421fd68a7`.

Snapshot SHA-256:
`cc09da8e918f7c4c8d85f22fa5d92048c641dd98467c94c0c586218090a86a32`.

## 8. Normalized relational dataset

Schema: `liquipedia-dota-draft-v1`
Pipeline version: `2.0.0`
Build fingerprint:
`edb5ce9931bb88702f0b6ffcc0cb2856c763d3e0a9316fbdafe6c307d3843664`

| Table | Rows |
| --- | ---: |
| `matches` | 353 |
| `match_teams` | 706 |
| `match_players` | 3,673 |
| `games` | 787 |
| `heroes` | 119 |
| `draft_picks` | 7,870 |
| `draft_bans` | 11,018 |
| `ml_draft_games` | 779 |

Every normalized Parquet file matches its manifest SHA-256. Relationship and
slot checks passed:

- every game maps to an accepted match;
- each game has exactly ten pick rows;
- each game has exactly fourteen ban rows;
- `(game, team, slot)` keys are unique;
- all 787 games have known winners, sides, patches, complete picks, and
  complete bans; and
- no first-pick field or global draft order was inferred.

## 9. Coverage

### Overall

| Metric | Result |
| --- | ---: |
| Matches | 353 |
| Matches with games | 347 |
| Matches without games | 6 |
| Games | 787 |
| Trainable games | 779 |
| Eligibility | 98.983482% |
| Known winner | 100% |
| Known sides | 100% |
| Known patch | 100% |
| Complete picks | 100% |
| Complete bans | 100% |
| Distinct tournaments | 22 |

### Patch

| Patch | Matches with games | Games | Eligible | Eligibility |
| --- | ---: | ---: | ---: | ---: |
| `7.30e` | 260 | 600 | 592 | 98.666667% |
| `7.31b` | 87 | 187 | 187 | 100% |

### Liquipedia tier

| Tier | Matches with games | Games | Eligible | Eligibility |
| --- | ---: | ---: | ---: | ---: |
| 1 | 27 | 44 | 44 | 100% |
| 2 | 320 | 743 | 735 | 98.923284% |

### Tournament

| Tournament | Matches with games | Games | Eligible |
| --- | ---: | ---: | ---: |
| BTS Pro Series Season 10: Americas | 45 | 96 | 96 |
| BTS Pro Series Season 10: Southeast Asia | 42 | 90 | 82 |
| DPC CN 2021/2022 Tour 1: Division I | 29 | 71 | 71 |
| DPC CN 2021/2022 Tour 1: Regional Final | 6 | 17 | 17 |
| DPC CN 2021/2022 Tour 2: Division I | 12 | 28 | 28 |
| DPC EEU 2021/2022 Tour 1: Division I | 14 | 32 | 32 |
| DPC EEU 2021/2022 Tour 1: Regional Final | 6 | 15 | 15 |
| DPC NA 2021/2022 Tour 1: Division I | 14 | 31 | 31 |
| DPC NA 2021/2022 Tour 1: Regional Final | 6 | 17 | 17 |
| DPC NA 2021/2022 Tour 2: Division I | 13 | 31 | 31 |
| DPC SA 2021/2022 Tour 1: Division I | 15 | 37 | 37 |
| DPC SA 2021/2022 Tour 1: Regional Final | 6 | 15 | 15 |
| DPC SA 2021/2022 Tour 2: Division I | 11 | 27 | 27 |
| DPC SEA 2021/2022 Tour 1: Division I | 20 | 41 | 41 |
| DPC SEA 2021/2022 Tour 1: Regional Final | 6 | 17 | 17 |
| DPC SEA 2021/2022 Tour 2: Division I | 12 | 30 | 30 |
| DPC WEU 2021/2022 Tour 1: Division I | 17 | 31 | 31 |
| DPC WEU 2021/2022 Tour 1: Regional Final | 6 | 15 | 15 |
| DPC WEU 2021/2022 Tour 2: Division I | 12 | 27 | 27 |
| GAMERS GALAXY: Invitational Series Dubai 2022 | 27 | 44 | 44 |
| Intel World Open Beijing | 14 | 38 | 38 |
| OGA Dota PIT Season 6: China | 14 | 37 | 37 |

## 10. Canonical supervised dataset

Schema: `dota-draft-supervised-v1`
Builder version: `3.0.0`
Build fingerprint:
`481af6bf5f7c8e688ab04679699cff80620c328cbaa868660322bf1b07692484`

| Metric | Result |
| --- | ---: |
| Eligible training rows | 779 |
| Excluded rows | 8 |
| Eligibility | 98.983482% |
| Hero vocabulary | 119 |
| Earliest training sample | `2022-01-03T04:55:00Z` |
| Latest training sample | `2022-03-31T22:10:00Z` |
| Radiant wins (`true`) | 379 / 48.652118% |
| Radiant losses (`false`) | 400 / 51.347882% |

All eight exclusions use the existing strict reason
`invalid_series_result`. They are the two played games from each of four
forfeit-tagged BTS Pro Series Southeast Asia matches:

- `7nVWNjTxx7_0002`
- `YcornYGWPf_0002`
- `kb5kra1zWn_0002`
- `kqoBtOA2cw_0001`

This exclusion reason did not occur in the July 2026 pilot, so it triggered
the designed review threshold. Review confirmed that it is expected behavior
from the unchanged eligibility contract: the games have complete drafts, but
their series is tagged as a forfeit. Excluding them avoids using an ambiguous
supervised target. The reason was not relaxed or remapped.

The training schema contains no forbidden outcome leakage, result status,
walkover, duration, first-pick, or global draft-sequence columns. Its only
target is `radiant_win`, and all draft columns use side-relative, per-team
slots.

The nullable `series` context field is absent in 38 eligible rows. It is not a
draft feature requirement and does not affect eligibility.

## 11. Fingerprint and lineage chain

```text
campaign configuration
e2c4c37a9792cfa3e724d6bfee1173feb1c1ec880644ef43b159c73a2ca52774
  ↓
campaign plan
b443f0910d40dfdb0f6986b17b76b582cc738c7c9f162d42317ef632c3759b9b
  ↓
2022-Q1 configuration
36bbf248c8cfc2fe9c7505af9eabedcb2c39f31a9dbe7c424eb57e9b2257f477
  ↓
four immutable raw response hashes
  ↓
acquisition fingerprint
75f7921aa401cb3faf216f92a54ab3c0324f6a558a270127e0f6c6a098966ebc
  ↓
assembly fingerprint / snapshot SHA-256
79d921a5e899a88cc34d5c66b4888d681f8f71ad64f3c1bc10fd25c421fd68a7
cc09da8e918f7c4c8d85f22fa5d92048c641dd98467c94c0c586218090a86a32
  ↓
normalized build fingerprint
edb5ce9931bb88702f0b6ffcc0cb2856c763d3e0a9316fbdafe6c307d3843664
  ↓
supervised build fingerprint
481af6bf5f7c8e688ab04679699cff80620c328cbaa868660322bf1b07692484
```

The normalized manifest identifies the exact assembly snapshot as its sole
source document. The supervised manifest identifies the exact normalized
fingerprint and verifies the source Parquet hashes. All published artifact
hashes were recalculated successfully.

## 12. Post-canary campaign state

Campaign state fingerprint:
`e5d766da94e41715de6b934ed5ed0614f1d4f6e507ec9f1cd002b6c7e06d0490`.

| Partition state | Result |
| --- | --- |
| `2022-Q1` | Complete: 4 pages, 353 records |
| `2022-Q2` | Pending: 0 requests |
| Later historical quarters | Pending: 0 requests |
| `2026-07-pilot` | Unchanged: complete, 2 cached pages, 108 records |
| Derived next partition | `2022-Q2` |
| Additional campaign attempts used | 4 |
| Additional campaign attempts remaining | 96 |

The coordinator derives `2022-Q2` as the next logical partition, but this is
state evidence only. It is not authorization to execute that partition.

## 13. Validation gates

| Gate | Result |
| --- | --- |
| Approved request hashes and offsets | Pass |
| Partition request budget | Pass: 4 / 8 |
| HTTP/API outcomes | Pass: four HTTP 200 responses |
| Terminal short page | Pass: 53 records |
| Date, tier, completion, and ordering scope | Pass |
| Raw response and cache checksums | Pass |
| Credential-free metadata/artifacts | Pass |
| Stable IDs and deduplication | Pass |
| Conflicts and quarantine | Pass: zero |
| Unchanged normalization pipeline | Pass |
| Relational and draft slot integrity | Pass |
| Supervised schema and leakage controls | Pass |
| Eligibility threshold ≥70% | Pass: 98.983482% |
| Patch coverage ≥95% | Pass: 100% |
| Winner and side coverage ≥80% | Pass: 100% |
| New exclusion reason review | Pass after review |
| Complete offline suite | Pass: 53 tests |
| Strict ≥67.000000-second start evidence | **Review required** |

The data-contract and historical-schema canary passed. The operational
rate-control evidence gap blocks further live expansion until reviewed.

## 14. Commands executed

The only live command was the exact approved Stage B command:

```bash
.venv/bin/python scripts/plan_liquipedia_history_campaign.py \
  --check-partition-readiness 2022-Q1 && \
.venv/bin/python scripts/backfill_liquipedia_history.py \
  --start 2022-01-01T00:00:00Z \
  --end 2022-04-01T00:00:00Z \
  --tier 1 \
  --tier 2 \
  --page-size 100 \
  --max-requests 8 \
  --hourly-limit 54 \
  --request-interval-seconds 67 \
  --timeout-seconds 30 \
  --execute \
  --confirm-live-request-budget 8
```

Post-live campaign state refresh:

```bash
.venv/bin/python scripts/plan_liquipedia_history_campaign.py
```

Offline finalization through the unchanged acquisition snapshot and
Milestone 2 normalization layers:

```bash
.venv/bin/python scripts/backfill_liquipedia_history.py \
  --start 2022-01-01T00:00:00Z \
  --end 2022-04-01T00:00:00Z \
  --tier 1 \
  --tier 2 \
  --page-size 100 \
  --max-requests 8 \
  --hourly-limit 54 \
  --request-interval-seconds 67 \
  --finalize
```

Canonical supervised build from normalized Parquet only:

```bash
.venv/bin/python scripts/build_draft_training_dataset.py \
  --normalized-build data/processed/liquipedia/build_edb5ce9931bb8870
```

Complete offline suite:

```bash
.venv/bin/python -m pytest -q
```

Result:

```text
53 passed in 5.31s
```

Additional read-only SHA-256, JSON, DuckDB, and Parquet assertions verified
the current local artifacts. Those checks made no network request and did not
modify acquisition state.

## 15. Key local artifacts

Authenticated response bodies and reproducible content-addressed builds
remain local and Git-ignored.

| Artifact | Identity or SHA-256 |
| --- | --- |
| Campaign post-canary preflight | `97030de83f0b8c143fd1b7aa0d9de33e17046625d9f9b1b8837961f06dd1bdbf` |
| Run manifest | `e154f80e20a382874e626755e97152eac94b2fd5c702745ce493f4bc0c3b570a` |
| Assembly manifest | `25ddddf04c87385b9b2380bf474bfa968cb03510435402bb1aff3962ae89ac2e` |
| Assembly snapshot | `cc09da8e918f7c4c8d85f22fa5d92048c641dd98467c94c0c586218090a86a32` |
| Normalized manifest | `7e7055c8412bebb29a221c6609377a806d07b7833d133d683885457aa55d6768` |
| Supervised manifest | `905a10c01ddac182c9631e9b78e8122bd0b64b5c61c5064e8dd1d8ebf68776a1` |

Primary paths:

- `data/backfill/campaigns/m3_5_20220101_20260727_e2c4c37a9792/`
- `data/backfill/runs/m3_20220101_20220401_36bbf248c8cf/`
- `data/raw/liquipedia/backfill/cache/<request-hash>/`
- `data/processed/liquipedia/build_edb5ce9931bb8870/`
- `data/training/dota_draft_supervised/build_481af6bf5f7c8e68/`

## 16. Deviations, warnings, and compatibility findings

- **Rate-control evidence:** two recorded wall-clock intervals are slightly
  below 67 seconds. No additional live work is authorized until a minimal
  hardening is reviewed.
- **Forfeit payloads without games:** six matches correctly remain
  match-only records; the pipeline invents no games.
- **Forfeit-tagged series with played games:** eight games have complete
  drafts but are strictly excluded as `invalid_series_result`.
- **Legacy schema:** the 2022 payload required no parser, normalized schema,
  or supervised schema change.
- **Draft semantics:** first pick and globally interleaved draft order remain
  unavailable and were not inferred.
- **No hidden expansion:** all partitions after 2022-Q1 remain untouched.
- **No product-layer drift:** no feature transformation, model, split,
  backend, or frontend work was started.

## 17. Next approval boundary

Stage B stops here.

Stage C has not been authorized and must not be executed from this report.
Before any further authenticated request, the rate-control compatibility
finding should be reviewed and the next action explicitly approved. The
existing 2022-Q1 raw, normalized, and supervised artifacts remain valid and
reproducible regardless of that operational follow-up.
