# Milestone 3.5: Bounded Historical Dataset Publication

> Final evidence for the verified contiguous historical release, the approved
> `2024-Q1` compatibility and request-budget amendment, and the deliberate
> hard stop at incomplete `2024-Q2`.

Status: **bounded finalization complete; full campaign window incomplete**
Report date: 2026-07-28
Campaign: `m3_5_20220101_20260727_e2c4c37a9792`
Source: official Liquipedia API only
Published schema: `dota-draft-historical-release-v1`
Supervised contract: `dota-draft-supervised-v1`
Broader Stage D: **not started; only the publication step required for this
auditable handoff was implemented**
Model implementation: **not started**

## 1. Outcome

Milestone 3.5 now has a deterministic, immutable, and model-ready release for
the largest verified contiguous prefix completed by the approved campaign:

```text
[2022-01-01T00:00:00Z, 2024-04-01T00:00:00Z)
```

The release contains all nine completed quarterly partitions from `2022-Q1`
through `2024-Q1`, limited to completed Tier 1 and Tier 2 professional
matches. It contains:

- 4,977 accepted match records;
- 10,014 normalized games;
- 9,700 eligible supervised draft games;
- 314 explicit exclusion rows;
- 124 heroes;
- 246 tournaments; and
- 22 named patch values from `7.30e` through `7.35d`, plus an unknown-patch
  bucket.

The release is intentionally labeled
`provisional_contiguous_prefix`. It does not claim to cover the complete
approved campaign window through 2026-07-27.

`2024-Q2` reached the unchanged eight-request partition ceiling after eight
full pages. The run stopped in `budget_exhausted` without a terminal page.
Its 800 cached records were not assembled, normalized, or published. No
request was made for `2024-Q3` or any later historical quarter. The completed
July 2026 pilot is also excluded because including it after the historical
gap would violate the contiguous-prefix release contract.

This boundary is a successful safety outcome, not silent truncation. The
published alias identifies exactly what is complete and reproducible, while
the incomplete cache and checkpoint remain available for a separately
approved continuation.

## 2. Canonical release identity

| Artifact | Identity |
| --- | --- |
| Logical alias | `m3.5-tier1-tier2-2022q1-2024q1-provisional-v1` |
| Publication version | `1.0.0` |
| Release fingerprint | `a485f713ffaf94f784ea1c770478be5c172d60285eb8369e294d34d9d447e7da` |
| Release directory | `data/releases/dota_draft_historical/build_a485f713ffaf94f7` |
| Release manifest SHA-256 | `fb456a7cf03be15852060e0dc4d619798d4da787dc3ad7c3cf328c0a83ee33cb` |
| Alias SHA-256 | `02e9cdae337732ecbcc478d586348b82f8308a60d8b1978cf279ebab85244610` |
| Publisher source SHA-256 | `07f25eb1e643cf6f2d755f83073a715bdacb7b62696cc1c5050bdef0ccfdcac3` |
| Release status | `provisional_contiguous_prefix` |

The immutable alias resolves to the release fingerprint, which resolves to
the aggregate normalized and supervised builds. Re-running publication with
the same completed partition manifests is idempotent; an incompatible
attempt to overwrite the alias fails.

## 3. Scope and partition lineage

All source intervals are half-open. The table records the exact accepted
partition lineage used by the release.

| Partition | Run ID | HTTP | Cache | Matches | Games | Acquisition fingerprint | Assembly fingerprint | Snapshot SHA-256 |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| `2022-Q1` | `m3_20220101_20220401_36bbf248c8cf` | 4 | 0 | 353 | 787 | `a940da4bc82f802ec0eb1618f0c9acdee7e0fbca0e3a56ec1db9876463e0cdea` | `79d921a5e899a88cc34d5c66b4888d681f8f71ad64f3c1bc10fd25c421fd68a7` | `cc09da8e918f7c4c8d85f22fa5d92048c641dd98467c94c0c586218090a86a32` |
| `2022-Q2` | `m3_20220401_20220701_60f8944a646a` | 4 | 0 | 357 | 764 | `1db8f69e3b54d2e754a9d64e7e0f92e7819ea909aa9e595f8c1f5cb1ca4a3004` | `e9f6a7465b552271e6d520806b47ba05d5407b4b9a177ee4f9f99e01d29e2d85` | `8f4704d26feadd3e987907cc0ca5f92e8a8d57318701e9a4d7be8630b1e06857` |
| `2022-Q3` | `m3_20220701_20221001_19a8d74f1c5b` | 5 | 0 | 446 | 969 | `01347a87198cbc9858513ae0a8c0fc596d33b185ad884ac6a470672e00f0011a` | `30806006bda3cd16e675c550908d504ae029879ec16e0e3b044083f0a4e9af68` | `b4f4c76fd9ca0dee2bced24a0046559919d141be269323ffcabb7127de19ae6f` |
| `2022-Q4` | `m3_20221001_20230101_ef93d0bbe56b` | 3 | 0 | 265 | 578 | `3d09ee8570cd723e6e24333f686e923cce4b3585eac5f008bbf776ff55f6b76d` | `da1a9a854986d18838e577f9a1612321fcf86b2ef188e2b666dec6ab806c10c0` | `9a1d15782d5ac07594d5eb5bcf5fa338e2633a9cf1239f5ce393d6af0a2b9611` |
| `2023-Q1` | `m3_20230101_20230401_f0eaf0202083` | 6 | 0 | 551 | 1,224 | `e9bef6328a996ea3c38dccc42e5c161829f9a1885d5e7ecc8b38ee3224245985` | `66b221d3f87d058d7022a40bf9dae2f21704c4cd46ef1e40a7f0d17549a335d5` | `c5b55891d298faea24aef0570c9ca701ec0c37549c35f580432a11a8c5b5f44c` |
| `2023-Q2` | `m3_20230401_20230701_5d5756ba4fd9` | 6 | 0 | 546 | 1,171 | `a2d180cf07239af9a5154a63b83fa1d06b4957d445f758c7bb204f2a87f5e006` | `9573cfd8c0943cebb1aab41da079e3c1427c56f6a14880c875997f43c8e21962` | `0fea9338fb12c701e199f32b08ee13560e029b7e9d3398bc7613ebef1826db50` |
| `2023-Q3` | `m3_20230701_20231001_3914e6822405` | 5 | 0 | 421 | 943 | `0a22eacdac2c43851acb116f67f1301a050ec205f679d4e0766246da178beba9` | `dadaa3e5a3aba73b38547974691f7bdcec2342edbde172b182510905fa6730e0` | `325e099b03404e1ef12c4c620b14a88615532ce959add6b49c6f32a1b53f3b09` |
| `2023-Q4` | `m3_20231001_20240101_5afa75ba56fa` | 5 | 0 | 428 | 826 | `29779e12f2d3a11491d2d51d47c74cfb9cf670777acfb55ef8848790c821146d` | `f5e8f0ef41882f08373f86472419960489dcd6c7ec75a52f687ad0ad2d753668` | `a0a5abed7a8738618b31c5b60a297dc8624bb5e2b155ae5b5bb28a11d529cf98` |
| `2024-Q1` | `m3_20240101_20240401_2c59812252db` | 9 | 8 | 1,610 | 2,752 | `b731416b76aa91d795641733fe7e4d7a8992e07ec8758be7d09e41f64a0c5a3b` | `d865cd1ba34fdc1b3f728c75f30a94786b43827732baef503e81080b91bdb195` | `c7c671dbc90aeabc4b761ab84a1e87042101b5e8102cc360249817b988a4848c` |

Across these manifests there are:

- zero duplicate matches;
- zero duplicate games;
- zero payload conflicts;
- zero quarantined records; and
- 55 accepted page slots, comprising 47 network attempts and eight immutable
  cache hits.

The complete raw-response hash lists, request identities, per-page record
counts, record-index hashes, game-index hashes, checkpoints, and run-manifest
hashes are embedded in the release manifest rather than duplicated into this
human-readable report.

## 4. `2024-Q1` bounded amendment

### 4.1 Why an amendment was necessary

The original `2024-Q1` run,
`m3_20240101_20240401_4aa59da8deab`, reached the default eight-page ceiling
with eight full 100-record pages. It was preserved with
`budget_exhausted`; no response bytes or ledger history were rewritten.

The approved amendment changed one acquisition control only: the
`2024-Q1` page-slot ceiling increased from 8 to 20. Endpoint, projection,
conditions, ordering, page size, date boundaries, tiers, rate limit, retry
policy, cache identities, parser, schemas, normalizer, and eligibility
contract remained fixed.

| Amendment identity | Value |
| --- | --- |
| Campaign configuration fingerprint | `e2c4c37a9792cfa3e724d6bfee1173feb1c1ec880644ef43b159c73a2ca52774` |
| Base campaign-plan fingerprint | `b443f0910d40dfdb0f6986b17b76b582cc738c7c9f162d42317ef632c3759b9b` |
| Budget-amendment fingerprint | `95d0a475c79f38692641bb29c0bc93168b873e3056b4be37cef10c377ff6b9e8` |
| Effective-plan fingerprint | `29993c0a7718a2a39d67fab1eb865df4fb017b4e9d0890e46d55d88b23428ae4` |
| Amendment JSON SHA-256 | `3dfd919ba1c9121513c1bcfb15edb924dc0b7bba1b246a94036c09bb8248a9be` |
| Amendment Markdown SHA-256 | `6acea2688b85fd8255cf51bb44627a5f2742210ac52f204d5a06cf090cef6422` |
| Amended run configuration hash | `2c59812252db906c8b373ec33fbc9b5cec0bb3f06e7b7c3250eafd94e442d097` |
| Maximum new HTTP attempts | 12 |
| Required certified cache prefix | 8 pages |

The amended run verified and reused all eight predecessor pages as cache
hits, then made nine new HTTP attempts for sequences 9 through 17. Sequence
17 returned ten records and established the terminal page. The completed run
therefore contains 1,610 matches across sixteen full pages and one ten-record
page.

The final amended checkpoint SHA-256 is
`c27a9243aedb95ca40d7e09e0fa8002ae593f97359a1a6f248bec71509599abc`;
the run-manifest SHA-256 is
`825c2294193b037064053d1408de38884ed87774531b79e83890afa8e34b499c`.

### 4.2 Strict duration compatibility

Duration parsing was not broadly relaxed. The generic duration parser still rejects
unsupported strings rather than stripping markup or guessing omitted units.
The already approved exact `Default` sentinel normalizes to missing, and
missing duration remains an eligibility failure.

Four previously reviewed `2024-Q1` occurrences are handled only under exact
source/context checks:

| Match and game | Raw value | Normalized duration | Existing exclusion |
| --- | --- | --- | --- |
| `D8VM7QJos8_R04-M001`, game 3 | `<s>Game 3</s>` | null | `missing_game_winner` |
| `D8VM7QJos8_R04-M003`, game 3 | `<s>Game 3</s>` | null | `missing_game_winner` |
| `D8VM7QJos8_R05-M002`, game 3 | `7m04` | null | `incomplete_team1_picks` |
| `D8VM7QJos8_R06-M001`, game 5 | `<s>Game 5</s>` | null | `missing_game_winner` |

The three struck-through values occur in unused series slots. `7m04` is
duration-like but lacks a documented seconds suffix; it is not converted to
424 seconds. Any mismatch to the certified match, game, value, or surrounding
payload fails closed. An arbitrary unsupported duration on an otherwise
eligible row also remains an error.

The exact `Default` value in `OCtGCrWT2m_R02-M004`, game 2, normalizes to
null and is excluded as `missing_game_duration`. It is not converted to zero
and no duration is inferred.

These are project compatibility policies for observed official API payloads,
not claims that the literals are part of an officially documented duration
grammar. The immutable raw values remain unchanged.

The completed `2024-Q1` partition produces 2,510 eligible rows and 242
exclusions from 2,752 games, or 91.206395% eligibility. Its partition
normalized fingerprint is
`b3938ba4a6f737fee1c28b8a16bb8e662bc8f9e013f992da234ac2c10662c34b`;
its supervised fingerprint is
`49a6979be0cc6d151d5602f5bce9879ebebb48486d1eafa5761515fe15774a70`.

## 5. `2024-Q2` hard stop and unpublished cache

The next chronological run is
`m3_20240401_20240701_6575003bb769`, configuration hash
`6575003bb7696a42a2ceb6f0a09ff0e6f4d81267a578912b64fdbe6cc9e45bad`.
It made eight HTTP attempts, received eight valid HTTP 200 responses, and
cached eight full pages:

| State field | Value |
| --- | --- |
| Status | `budget_exhausted` |
| HTTP attempts | 8 of 8 |
| Cache hits | 0 |
| Partial records | 800 |
| Terminal page | not reached |
| Next sequence | 9 |
| Next offset | 800 |
| Checkpoint SHA-256 | `3c5d43d66f9a3deb721de21ef7351c16805d32c9108c29b92f85831d71d6f22c` |
| Last returned match date | `2024-06-25 05:00:00` |
| Partition end | `2024-07-01T00:00:00Z` |

The last cached date is approximately 5.8 days before the partition
boundary. Using only the observed record density gives a point estimate of
roughly 54 remaining matches, so one additional request is the most likely
completion cost. A cautious operational estimate is one to two requests,
because event density is uneven and a full ninth page would require a tenth
request to prove termination. This is an estimate, not permission to request
or an assertion that the partition is complete.

The response hashes for the preserved partial cache are:

1. `80049ac016c375a9381b982e3b6efc45aae5c7666f464f2757fc2f7142693756`
2. `0a5d10f02e2aac645eb834877bf164e1bb6163046083673f9e7c6839e04e23ef`
3. `038c37424f273e8f23afb3f98e3bbdf0c0beda60fced3332945c2a8c1a70f9a5`
4. `0f716f631e411481106c787057c07e7acc9a722b3cdca5115479d8bc55242e20`
5. `250f43d75e3b51f578aacdd0f3861a05b958cf5618ddd69c09ae6adbddd7441d`
6. `bb5c6d186d3916549c7e3b6d01d23955e7a42dfab77c3f46961f4858523a634d`
7. `2bda2ac87c2d31a8695c8627ed6ec1852441f69ddd1029d2c1e71b52ae501343`
8. `91945898f851d7540ec85a99e89a6d4e456c4f884f2287e52783fe40477b2214`

### Known unpublished compatibility finding

An offline inventory of the 25 newly acquired `2024-Q1` and `2024-Q2` pages
covered 2,410 matches and 4,340 game objects. It found five unsupported
duration strings. The four published `2024-Q1` occurrences behave under
their approved exact compatibility rules.

The fifth occurs only in unpublished `2024-Q2`:

| Field | Value |
| --- | --- |
| JSON path | `result[40].match2games[1].length` |
| Request sequence / offset | 7 / 600 |
| Match and game | `ubD8YXh91K_R02-M001`, game 2 |
| Exact source value | `21m38` |
| Source response SHA-256 | `2bda2ac87c2d31a8695c8627ed6ec1852441f69ddd1029d2c1e71b52ae501343` |
| Patch | `7.36b` |
| Tournament | TI2024 China Open Qualifier #2 |

The object otherwise describes a completed team-mode game: the finished
series is 2–0, the game winner is team 1, scores are `[1, 0]`, Radiant and
Dire are explicit, ten picks and fourteen bans are present, and publisher ID
`7783589011` is populated. `21m38` likely omits the `s` suffix, but converting
it would be an inference. It therefore remains an unsupported, ambiguous
value and a strict duration-normalization error. No compatibility change was
made for it.
Because `2024-Q2` is incomplete and excluded, this finding does not affect
the published release.

## 6. Campaign request and rate evidence

| Request scope | Actual attempts |
| --- | ---: |
| Canonical published runs | 47 |
| Superseded `2024-Q1` prefix run | 8 |
| Incomplete `2024-Q2` run | 8 |
| Milestone 3.5 campaign total | **63 / 100** |
| Campaign attempts remaining | **37** |
| Earlier July 2026 Milestone 3 pilot | 2, excluded from the campaign ceiling |
| Complete SQLite ledger | 65 |

The eight requests in the superseded `2024-Q1` run created the certified
cache prefix later reused by the amended run. They are counted once in
campaign HTTP accounting but are not repeated in the canonical release-run
count.

Across the complete SQLite ledger:

- all 65 network attempts returned HTTP 200 and passed response validation;
- HTTP 403 responses: 0;
- HTTP 429 responses: 0;
- API-level errors: 0;
- malformed JSON responses: 0;
- automatic retries: 0;
- first recorded attempt:
  `2026-07-27T22:33:55.859737+00:00`;
- last recorded attempt:
  `2026-07-28T15:31:46.946265+00:00`;
- maximum observed attempts in any rolling hour: 38, below the limit of 54;
  and
- configured request-start interval: 67 seconds.

The minimum observed consecutive ledger interval is
`66.98543310165405` seconds, and five intervals are fractionally below 67
seconds. This is the previously accepted non-blocking timestamp/scheduler
issue. It caused no rolling-hour violation and no rate-limit response.
Rate-limiter hardening was correctly left outside this bounded finalization.

## 7. Aggregate normalized dataset

| Field | Value |
| --- | --- |
| Schema | `liquipedia-dota-draft-v1` |
| Build | `data/processed/liquipedia/build_6f44f771e75eabff` |
| Build fingerprint | `6f44f771e75eabffb393f2a3a2bbe27097d4c882d38fbfd10b476fa66dfcae1f` |
| Manifest SHA-256 | `b18256f9fa5fe85c920a00e41233247c651e6d6b3e183ce92058951fda9d73a4` |

| Table | Rows | SHA-256 |
| --- | ---: | --- |
| `matches` | 4,977 | `2b89790f6c0ead223c1aab02d8fd372c124ade08c0680241dadf453d518999f9` |
| `games` | 10,014 | `e05c2a6669c725145ab13ee73fbe096434bcb76d0eb63e34afa43cf4d7b9e8ca` |
| `match_teams` | 9,954 | `872003a6510e287e071ea15db5c525319139be2cef5e0d78ac9c54dad1382314` |
| `match_players` | 49,342 | `31ae7d16411702ee4dffaf18ec1e0cee63d9758b789d63eb1e7b673404abea09` |
| `heroes` | 124 | `8d7f7a49e114d528f0e395dbc8c0a39261a0a82b54609095c36d4b49aefa7b16` |
| `draft_picks` | 97,556 | `6929939716f94cc9228691ce411546bf86bc5592a852b74442863fbbfa98acc5` |
| `draft_bans` | 136,231 | `13b942ced132bb1cff6098c1f16f1aa4d357dc56c3c4c5f1b04f67f9433ed2c0` |
| `ml_draft_games` | 9,700 | `d6619a57bf29549982c9a05fdf87b45d88ced625da41cc4e065e5885d02cd1b4` |

Of 4,977 accepted match records, 4,909 contain game rows and 68 preserve
no-game source shapes. This is why coverage dimensions derived through games
sum to 4,909 rather than 4,977.

## 8. Canonical supervised dataset

| Field | Value |
| --- | --- |
| Schema | `dota-draft-supervised-v1` |
| Build | `data/training/dota_draft_supervised/build_c1ea1d31968eb4c9` |
| Dataset fingerprint | `c1ea1d31968eb4c9c6fc4cd8dd7812ca2189694ca94ace48b1aae676e146acd9` |
| Manifest SHA-256 | `5b4b807f81c2b960ed813d373ccd3f2b602b77cff61a680a86002c6b2d9810ad` |
| Eligible rows | 9,700 |
| Excluded rows | 314 |
| Reconciliation | 10,014 = 9,700 + 314 |
| Eligibility | 96.864390% |
| Hero vocabulary | 124 |
| Date minimum | `2022-01-03T04:55:00+00:00` |
| Date maximum | `2024-03-31T18:20:00+00:00` |
| Training Parquet SHA-256 | `86fc4327c30a92ef50de889b343682f5934615b6b14f75057a4a9e3ff957a719` |
| Exclusions Parquet SHA-256 | `f4e25cff320f1504a00861a9660ff0d3689cfa938f5118c3fb22245511cecd57` |
| Schema artifact SHA-256 | `4bae8474d0d982c0356bda042ab15739572e97f97b63548e3685c028480872b4` |

All required source IDs, target values, sides, picks, and bans are non-null in
the eligible table. Patch is nullable for 74 eligible rows and series is
nullable for 373; these are preserved metadata limitations rather than
invented values.

### Target balance

| Target | Rows | Share |
| --- | ---: | ---: |
| Radiant win | 4,833 | 49.824742% |
| Radiant loss | 4,867 | 50.175258% |

### Exclusion audit

| First eligibility failure | Games |
| --- | ---: |
| `incomplete_team1_bans` | 12 |
| `incomplete_team1_picks` | 71 |
| `incomplete_team2_bans` | 10 |
| `invalid_game_result` | 13 |
| `invalid_series_result` | 18 |
| `missing_game_duration` | 2 |
| `missing_game_winner` | 3 |
| `missing_or_invalid_sides` | 185 |
| **Total** | **314** |

No eligibility rule infers first pick or a globally interleaved draft order;
those values are unavailable in the validated official response. Duration is
used only as a gameplay-metadata completeness gate and is forbidden as a
predictive feature.

## 9. Coverage

### By calendar year

`2024` in this release means `2024-Q1` only.

| Year | Matches with games | Games | Eligible | Eligibility |
| --- | ---: | ---: | ---: | ---: |
| 2022 | 1,401 | 3,098 | 3,070 | 99.096191% |
| 2023 | 1,935 | 4,164 | 4,120 | 98.943324% |
| 2024 Q1 | 1,573 | 2,752 | 2,510 | 91.206395% |

### By tournament tier

| Tier | Matches with games | Games | Eligible | Eligibility |
| --- | ---: | ---: | ---: | ---: |
| Tier 1 | 3,212 | 6,194 | 5,906 | 95.350339% |
| Tier 2 | 1,697 | 3,820 | 3,794 | 99.319372% |

### Patch and tournament coverage

- 9,886 of 10,014 games have a known patch.
- The release contains 22 named patches spanning `7.30e` through `7.35d`.
- The unknown-patch bucket contains 128 games, of which 74 are eligible.
- The largest named-patch bucket is `7.35b`, with 1,295 games and 1,131
  eligible rows.
- `7.35b` eligibility is 87.335907%; the reduced `2024-Q1` eligibility is
  driven by preserved incomplete and solo-event payload shapes, not by
  invented normalization.
- The release covers 246 distinct tournaments.

Exact patch and tournament rows are stored in:

- `coverage/coverage_by_patch.parquet`;
- `coverage/coverage_by_tournament.parquet`;
- `coverage/coverage_by_tier.parquet`;
- `coverage/coverage_by_year.parquet`; and
- `coverage/eligibility_failures.parquet`.

The coverage artifact SHA-256 values are:

| Artifact | SHA-256 |
| --- | --- |
| `coverage_by_patch.parquet` | `d6203e993d16d71380d26e3ad6060f3f60e2516792fddc1e970da929a7be092d` |
| `coverage_by_tier.parquet` | `224036afe8c818e958b48aad0485d29771991e348a32874a90008839e5c4d4b4` |
| `coverage_by_tournament.parquet` | `c08eac715c9215c50a7e4c1a3f4edeb341bec408703cc365705999746e81c249` |
| `coverage_by_year.parquet` | `dc02cfffd5de14350b0e36ae79dfcad428cf2353ab37f3bc0d0aa03adc02b26c` |
| `coverage_summary.json` | `1555bc0bb25f184e4b7a6c4ab33d1d0c3ac4b397b2b00cad38c49e114cad9e27` |
| `coverage_summary.md` | `d037affcbb8092bfcd84982a79f179480b02f23d9d7e65b5c8e93d84ab22ad8f` |
| `eligibility_failures.parquet` | `cd908367d2a635e9b2076a66ad78f2301985895445e005459df6e9ccb81c2e39` |

## 10. Reproducibility and validation gates

The verified lineage is:

```text
official API request identities
  -> immutable cached response bytes + SHA-256
  -> completed partition checkpoints and manifests
  -> accepted-record snapshots
  -> aggregate normalized build
       6f44f771e75eabffb393f2a3a2bbe27097d4c882d38fbfd10b476fa66dfcae1f
  -> canonical supervised build
       c1ea1d31968eb4c9c6fc4cd8dd7812ca2189694ca94ace48b1aae676e146acd9
  -> immutable release
       a485f713ffaf94f784ea1c770478be5c172d60285eb8369e294d34d9d447e7da
  -> immutable logical alias
       m3.5-tier1-tier2-2022q1-2024q1-provisional-v1
```

Publication reverified:

- every partition is complete and has a terminal page;
- scopes form a contiguous, non-overlapping prefix;
- request, cache, checkpoint, snapshot, and manifest hashes agree;
- no incomplete partition or post-gap pilot enters the release;
- match and game identities are conflict-free across partitions;
- aggregate normalized tables reconcile with source manifests;
- supervised eligible and excluded rows reconcile to normalized games;
- normalized and supervised manifests are content addressed;
- alias publication is immutable and idempotent; and
- publication has no HTTP-client or credential dependency.

The final complete offline suite result is:

```text
92 passed in 11.27s
```

Command:

```bash
.venv/bin/python -m pytest -q
```

The suite includes campaign and amendment planning, request/hash stability,
cache-prefix adoption, budget enforcement, exact compatibility gates,
eligibility, raw-to-supervised lineage, aggregate publication, scope
rejection, tamper detection, alias immutability, and offline-only behavior.
The test run made zero authenticated API requests.

The exact offline publication command is:

```bash
.venv/bin/python scripts/publish_historical_dataset.py \
  --mode provisional-prefix \
  --alias m3.5-tier1-tier2-2022q1-2024q1-provisional-v1 \
  --partition 2022-Q1=m3_20220101_20220401_36bbf248c8cf \
  --partition 2022-Q2=m3_20220401_20220701_60f8944a646a \
  --partition 2022-Q3=m3_20220701_20221001_19a8d74f1c5b \
  --partition 2022-Q4=m3_20221001_20230101_ef93d0bbe56b \
  --partition 2023-Q1=m3_20230101_20230401_f0eaf0202083 \
  --partition 2023-Q2=m3_20230401_20230701_5d5756ba4fd9 \
  --partition 2023-Q3=m3_20230701_20231001_3914e6822405 \
  --partition 2023-Q4=m3_20231001_20240101_5afa75ba56fa \
  --partition 2024-Q1=m3_20240101_20240401_2c59812252db
```

It makes zero authenticated requests and reads no API key.

### Executed acquisition and build boundary

The only authenticated commands in this bounded finalization were:

```bash
.venv/bin/python scripts/backfill_liquipedia_history.py \
  --start 2024-01-01T00:00:00Z \
  --end 2024-04-01T00:00:00Z \
  --tier 1 --tier 2 \
  --page-size 100 \
  --max-requests 20 \
  --max-network-attempts 12 \
  --require-cache-prefix-pages 8 \
  --hourly-limit 54 \
  --request-interval-seconds 67 \
  --timeout-seconds 30 \
  --execute \
  --confirm-live-request-budget 12

.venv/bin/python scripts/backfill_liquipedia_history.py \
  --start 2024-04-01T00:00:00Z \
  --end 2024-07-01T00:00:00Z \
  --tier 1 --tier 2 \
  --page-size 100 \
  --max-requests 8 \
  --hourly-limit 54 \
  --request-interval-seconds 67 \
  --timeout-seconds 30 \
  --execute \
  --confirm-live-request-budget 8
```

The first command completed after nine network attempts and eight cache hits.
The second stopped with exit status 2 and the expected
`budget_exhausted` checkpoint after eight network attempts. No authenticated
command followed it.

The post-acquisition processing commands were offline:

```bash
.venv/bin/python scripts/backfill_liquipedia_history.py \
  --start 2024-01-01T00:00:00Z \
  --end 2024-04-01T00:00:00Z \
  --tier 1 --tier 2 \
  --page-size 100 \
  --max-requests 20 \
  --hourly-limit 54 \
  --request-interval-seconds 67 \
  --finalize

.venv/bin/python scripts/build_draft_training_dataset.py \
  --normalized-build data/processed/liquipedia/build_b3938ba4a6f737fe

.venv/bin/python -m pytest -q
```

The aggregate publication command shown above was executed twice: once to
create the release and once to prove idempotent verification and reuse.

## 11. Dataset sufficiency for Milestone 4

The canonical 9,700-row dataset is sufficient to begin Milestone 4 baseline
and feature work:

- it is large enough for reproducible linear and tree-based baselines;
- the target is almost perfectly balanced;
- all 124 observed heroes are represented in one stable vocabulary;
- nine chronological quarters allow honest temporal validation;
- 246 tournaments and both approved tiers support grouped robustness checks;
- 22 named patches support patch-aware and recency-ablation experiments; and
- explicit exclusions and immutable fingerprints make experiment inputs
  auditable.

This conclusion is deliberately bounded. The dataset is not evidence of:

- exhaustive 2022–2026 professional-match coverage;
- current July 2026 meta coverage;
- production recommendation quality;
- reliable estimation for every rare hero combination or lineup;
- sufficient sample scale for complex deep-learning architectures; or
- first-pick or globally ordered draft-sequence features.

A simpler, well-controlled baseline program on 9,700 clean games has more
portfolio value than spending the remaining campaign budget merely to claim a
larger row count before modeling. Additional acquisition should be driven by
a measured modeling limitation—such as temporal drift, rare-hero coverage,
or confidence-interval width—not by dataset size alone.

## 12. Completion boundary and remaining scope

The original 19-partition campaign plan remains historically useful, but this
publication includes only its first nine contiguous quarters:

- published: `2022-Q1` through `2024-Q1`;
- incomplete and unpublished: `2024-Q2`;
- unstarted: `2024-Q3` through `2026-Q2`; and
- separately complete but excluded after the gap: the July 2026 pilot.

There are 37 attempts left under the original 100-attempt campaign ceiling.
No request is authorized by this report. If the project later resumes
historical acquisition, it must first approve an explicit `2024-Q2` recovery
plan, preserve the eight cached pages, address the ambiguous `21m38` value
without inference, and re-enter the same raw → normalized → supervised
validation gates.

Milestone 3.5 is complete as a **bounded historical dataset publication**.
It is not complete as a full-window acquisition campaign. No database,
backend, frontend, feature implementation, model training, or inference
service was started as part of this finalization.
