# Milestone 3.5 Stage A: Offline Campaign Planning and Coordination

> Generated Definition-of-Done artifact — do not hand-edit.

Report schema: `milestone-report-v1`
Status: **complete; Stage B awaiting separate approval**
Campaign ID: `m3_5_20220101_20260727_e2c4c37a9792`
Configuration fingerprint: `e2c4c37a9792cfa3e724d6bfee1173feb1c1ec880644ef43b159c73a2ca52774`
Campaign plan fingerprint: `b443f0910d40dfdb0f6986b17b76b582cc738c7c9f162d42317ef632c3759b9b`
Campaign state fingerprint: `e368de4dbcbe24b89cb932b7d7b5927d201bedc18b644d257d2510b0efeda542`

## 1. Definition-of-Done outcome

Stage A is complete. The fixed 2022–2026 campaign has been planned
as 19 deterministic partitions, the existing pilot ledger and cache
have been verified, resume and budget decisions are derived without
mutating acquisition state, and all offline tests pass.

Authenticated requests performed by Stage A: **0**.

## 2. Scope boundary

Included:

- immutable campaign configuration and fingerprints;
- exact secret-free request specifications and cache/checkpoint paths;
- read-only SQLite/cache preflight and deterministic resume resolution;
- campaign-level request accounting and boundary enforcement;
- machine-readable and Markdown planning artifacts; and
- comprehensive offline tests.

Excluded:

- the 2022-Q1 authenticated canary;
- any historical acquisition request;
- raw-data parsing or normalization changes;
- supervised-dataset construction changes;
- feature engineering, splitting, modeling, backend, and frontend work.

## 3. Implementation map

| File | Responsibility |
| --- | --- |
| `src/liquipedia_backfill/campaign.py` | Fixed campaign contract, partition composition, fingerprints, read-only state/cache inspection, resume policy, and budget/readiness gate. |
| `src/liquipedia_backfill/campaign_reports.py` | Immutable JSON publication, Markdown planning reports, preflight evidence, and generated Definition-of-Done report. |
| `src/liquipedia_backfill/envelope.py` | Pure response-envelope validation shared by the live runner and offline cache verifier. |
| `src/liquipedia_backfill/runner.py` | Uses the extracted pure envelope validator; HTTP behavior is otherwise unchanged. |
| `src/liquipedia_backfill/__init__.py` | Exposes the campaign planning contract. |
| `scripts/plan_liquipedia_history_campaign.py` | Offline-only planning CLI and completion-report gate. |
| `tests/test_milestone3_5_campaign.py` | Boundaries, hashes, state, budgets, cache reuse, reports, and zero-request tests. |
| `docs/milestones/MILESTONE_3_5_STAGE_A_OFFLINE_CAMPAIGN_PLANNING.md` | Mandatory generated completion evidence. |
| `README.md`, `data/README.md`, and milestone design documents | Current status, artifact layout, and corrected approval boundaries. |
| `.gitignore` | Keeps authenticated data local while allowing credential-free campaign evidence to be versioned. |

## 4. Architecture decisions

The coordinator composes `BackfillConfig` and `create_plan()` for every
partition. It does not construct API queries independently and does
not expose an HTTP client.

Campaign state is a read-only projection of the existing SQLite
partition ledger plus checksum-verified cache entries. No campaign
tables or second state database were added. The existing
`BackfillRunner` remains the only live acquisition path.

Immutable plan/configuration identity excludes local paths, timestamps,
and mutable state. Preflight state has its own fingerprint.

## 5. Campaign request accounting

- Logical partitions: **19**
- New full-quarter partitions: **18**
- Cached July 2026 pilot partitions: **1**
- Conditional request specifications: **148** (144 new + 4 pilot)
- Estimated successful pages: **75–95**
- Maximum additional HTTP attempts: **100**
- Additional attempts used at Stage A completion: **0**

The 148 specifications are conditional pagination slots, not an
authorization to make 148 calls. The campaign hard ceiling remains
100 additional attempts.

## 6. Ordered partitions

| # | Partition | Range | Run ID | Config hash | Slots | Network budget |
| ---: | --- | --- | --- | --- | ---: | ---: |
| 1 | `2022-Q1` | `2022-01-01T00:00:00+00:00` → `2022-04-01T00:00:00+00:00` | `m3_20220101_20220401_36bbf248c8cf` | `36bbf248c8cfc2fe9c7505af9eabedcb2c39f31a9dbe7c424eb57e9b2257f477` | 8 | 8 |
| 2 | `2022-Q2` | `2022-04-01T00:00:00+00:00` → `2022-07-01T00:00:00+00:00` | `m3_20220401_20220701_60f8944a646a` | `60f8944a646a7a390039d9c4b69fa394aa1dca4d2a598ed7ee33f1c27ee283f3` | 8 | 8 |
| 3 | `2022-Q3` | `2022-07-01T00:00:00+00:00` → `2022-10-01T00:00:00+00:00` | `m3_20220701_20221001_19a8d74f1c5b` | `19a8d74f1c5bed697445b546f3fdd6d27d2c677c53657ca1966840b6ed6ec0e2` | 8 | 8 |
| 4 | `2022-Q4` | `2022-10-01T00:00:00+00:00` → `2023-01-01T00:00:00+00:00` | `m3_20221001_20230101_ef93d0bbe56b` | `ef93d0bbe56b3acb38674e503541d1fc107f6405adaf22e589af05e1dd5829f6` | 8 | 8 |
| 5 | `2023-Q1` | `2023-01-01T00:00:00+00:00` → `2023-04-01T00:00:00+00:00` | `m3_20230101_20230401_f0eaf0202083` | `f0eaf02020834b358b061df339f92422bd66bc4d72671a838208978b7ca727a4` | 8 | 8 |
| 6 | `2023-Q2` | `2023-04-01T00:00:00+00:00` → `2023-07-01T00:00:00+00:00` | `m3_20230401_20230701_5d5756ba4fd9` | `5d5756ba4fd9df0fd6a610c37bbe67691aea6a35c5c0b339891ac0533b9f1d89` | 8 | 8 |
| 7 | `2023-Q3` | `2023-07-01T00:00:00+00:00` → `2023-10-01T00:00:00+00:00` | `m3_20230701_20231001_3914e6822405` | `3914e6822405be757288e5fcf1c01ea374c4f7cead9abcad888e76f757e2b6cc` | 8 | 8 |
| 8 | `2023-Q4` | `2023-10-01T00:00:00+00:00` → `2024-01-01T00:00:00+00:00` | `m3_20231001_20240101_5afa75ba56fa` | `5afa75ba56fa1a6a6ea4b7dc1692795dadb9a82d21d365fdd2c921b4e42e1069` | 8 | 8 |
| 9 | `2024-Q1` | `2024-01-01T00:00:00+00:00` → `2024-04-01T00:00:00+00:00` | `m3_20240101_20240401_4aa59da8deab` | `4aa59da8deab0748102a63a09c21d1b9bc10dfeb317bf57b7633d2ea0014a051` | 8 | 8 |
| 10 | `2024-Q2` | `2024-04-01T00:00:00+00:00` → `2024-07-01T00:00:00+00:00` | `m3_20240401_20240701_6575003bb769` | `6575003bb7696a42a2ceb6f0a09ff0e6f4d81267a578912b64fdbe6cc9e45bad` | 8 | 8 |
| 11 | `2024-Q3` | `2024-07-01T00:00:00+00:00` → `2024-10-01T00:00:00+00:00` | `m3_20240701_20241001_5bf5f710c335` | `5bf5f710c335fa9226d613938d53b124db710f820f0ae2445ae68cb1f6df8a88` | 8 | 8 |
| 12 | `2024-Q4` | `2024-10-01T00:00:00+00:00` → `2025-01-01T00:00:00+00:00` | `m3_20241001_20250101_2c32e33d5a98` | `2c32e33d5a9875e31c66c100266c725982306812b6f7397f8c854c8eba3eb64d` | 8 | 8 |
| 13 | `2025-Q1` | `2025-01-01T00:00:00+00:00` → `2025-04-01T00:00:00+00:00` | `m3_20250101_20250401_cd59ec2f0029` | `cd59ec2f00299e5b02ef9fd756039b01968dfadc418abfee9fc9140cfa8a5660` | 8 | 8 |
| 14 | `2025-Q2` | `2025-04-01T00:00:00+00:00` → `2025-07-01T00:00:00+00:00` | `m3_20250401_20250701_2c1023c34f35` | `2c1023c34f355e7a85f4292abaa6d98c349c2d7dc0b8fb59dc0fbad25a21fa0b` | 8 | 8 |
| 15 | `2025-Q3` | `2025-07-01T00:00:00+00:00` → `2025-10-01T00:00:00+00:00` | `m3_20250701_20251001_c63b3c6d9770` | `c63b3c6d9770fbbc8ed1ff548ef7492a5db10106e5a2bcfdef5298aa4d0bad2c` | 8 | 8 |
| 16 | `2025-Q4` | `2025-10-01T00:00:00+00:00` → `2026-01-01T00:00:00+00:00` | `m3_20251001_20260101_e3f82e8aca4b` | `e3f82e8aca4bbbe2e639c633497e16d298cde6719d964cc6be27632157bdc2de` | 8 | 8 |
| 17 | `2026-Q1` | `2026-01-01T00:00:00+00:00` → `2026-04-01T00:00:00+00:00` | `m3_20260101_20260401_a7d332ca2bbc` | `a7d332ca2bbc68e65243408ae350a2e48b055e0a5f7ad2ab9994cd1aef9a54b9` | 8 | 8 |
| 18 | `2026-Q2` | `2026-04-01T00:00:00+00:00` → `2026-07-01T00:00:00+00:00` | `m3_20260401_20260701_452fe5854253` | `452fe5854253ea5176458199a10f3ff4e442d6be7110cd0ccc7ee971f7ce06fa` | 8 | 8 |
| 19 | `2026-07-pilot` | `2026-07-01T00:00:00+00:00` → `2026-07-27T00:00:00+00:00` | `m3_20260701_20260727_0b40ae8811d6` | `0b40ae8811d6140590657c976ed350d44ab98c9d8289bde8c1d6a57221610258` | 4 | 0 |

## 7. Cached pilot reuse proof

- Run ID: `m3_20260701_20260727_0b40ae8811d6`
- Configuration hash: `0b40ae8811d6140590657c976ed350d44ab98c9d8289bde8c1d6a57221610258`
- SQLite status: `complete`
- Historical attempts, excluded from Stage 3.5 budget: `2`
- Verified records: `108`
- Additional pilot requests required: `0`

| Page | Request hash | Response SHA-256 | Records | Final |
| ---: | --- | --- | ---: | --- |
| 1 | `9f0b310bee831a6c921fb568cdb5e71a979ebe9832f3e22b29c4e2afa21371c6` | `bc5ab9f31516795b0b8011ac796ed266a5effc2c41a88957cea350a8f3dce06e` | 100 | false |
| 2 | `0060ee0181d4b51e1c477ee857c41e08b8b9a0b40c8e04f65b924b47b98bfd66` | `2f15aa68c77c5b6b258ba9cd5063cbbfcfc480a94b92d65bc2437b382765ed81` | 8 | true |

Page 2 is terminal, so the pilot's conditional request slots 3 and
4 are correctly classified as not required. The coordinator
assigns the pilot a zero network budget.

## 8. Resume and budget decision

- Campaign status: `ready_for_canary`
- Next partition: `2022-Q1`
- Next run ID: `m3_20220101_20220401_36bbf248c8cf`
- Next sequence and offset: `1` / `0`
- Additional attempt budget remaining: `100`
- Next-partition remaining ceiling: `8`

A failed, exhausted, unresolved, corrupt, or out-of-order
partition blocks the campaign. A partition is authorized at a
boundary only when the campaign can cover its conservative
remaining request ceiling.

## 9. Offline verification

- Command: `.venv/bin/python -m pytest -q`
- Result: **53 passed in 5.39s**
- Passing tests: **53**
- API key read: **no**
- Authenticated request delta: **0**
- Acquisition ledger rows created: **0**

## 10. Generated artifact checksums

| Artifact | SHA-256 | Bytes |
| --- | --- | ---: |
| `data/backfill/campaigns/m3_5_20220101_20260727_e2c4c37a9792/campaign_config.json` | `9e52e198ebccb8bf738fec33a53cf743cc1082cc94ac1ef2acf49d20b8b64255` | 2586 |
| `data/backfill/campaigns/m3_5_20220101_20260727_e2c4c37a9792/campaign_plan.json` | `c42cb290ef94fee00c1dc105016a860fa008855d6271dab391a8f69c731ebacc` | 328476 |
| `data/backfill/campaigns/m3_5_20220101_20260727_e2c4c37a9792/campaign_plan.md` | `ba408717f7ea59b92ec8efb48e770785dc8ef576cff5af808b31f769ab3da882` | 41283 |
| `data/backfill/campaigns/m3_5_20220101_20260727_e2c4c37a9792/campaign_preflight.json` | `c8001e99c2a7e0de8e524fbe3b5f112aaa811c0279812e1f4ba00b2327dba6df` | 13831 |
| `data/backfill/campaigns/m3_5_20220101_20260727_e2c4c37a9792/campaign_preflight.md` | `8fed2d9dabbe6a179ff5d3c3590b74e4bd3148b2214c11788496b8a406390a29` | 1667 |

## 11. Deviations, warnings, and limitations

- No design deviation was required.
- Request estimates remain planning ranges rather than quotas or
  dataset-size guarantees.
- The campaign coordinator enforces the 100-attempt ceiling at
  partition boundaries; the existing runner continues to enforce
  each partition's eight-attempt ceiling.
- Stage A does not prove 2022 payload compatibility. That is the
  purpose of the separately approved historical canary.

## 12. Stage B approval boundary

The proposed command below targets only 2022-Q1 through the
existing validated acquisition runner. It was not executed:

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

Stage B remains blocked pending separate approval.
