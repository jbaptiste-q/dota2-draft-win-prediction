# Milestone 3.5 Stage C: Duration Eligibility Policy Update

> Mandatory Definition-of-Done artifact for the approved duration-eligibility
> policy change and cache-only historical rebuild.

Status: **completed-partition rebuild and validation passed; Stage C not resumed**
Report date: 2026-07-28
Campaign: `m3_5_20220101_20260727_e2c4c37a9792`
Validation result: `PASS_COMPLETED_PARTITIONS`
Source: existing immutable official Liquipedia API cache only
Authenticated requests made by this update: **0**
Stage D: **not started**

## 1. Outcome

The supervised-dataset eligibility policy now requires a normalized game
duration. A game whose `duration_seconds` is null is ineligible even when its
winner, sides, picks, and bans are otherwise complete.

The change is intentionally narrow:

- the official Liquipedia duration sentinel `Default` continues to normalize
  to `None`;
- an absent or blank source duration also remains `None`;
- no missing duration is replaced with zero or inferred;
- no additional duration format is accepted;
- no other eligibility criterion changed;
- duration remains excluded from model features; and
- the new reason `missing_game_duration` is appended last in the existing
  deterministic first-reason ordering.

All eight completed historical partitions were rebuilt from immutable cache
through normalized Parquet and `dota-draft-supervised-v1`. The cached July
2026 pilot was also rebuilt for lineage consistency. The completed-partition
validator returned `PASS_COMPLETED_PARTITIONS`.

The update made no HTTP request and did not alter the request ledger. The
ledger remains at 48 total historical attempts, including the two earlier
Milestone 3 pilot attempts.

## 2. Approved eligibility contract

The normalized eligibility function records only the first applicable
exclusion reason. `missing_game_duration` is deliberately checked after all
pre-existing conditions.

This ordering has two useful properties:

1. a previously eligible game with no duration becomes ineligible as
   `missing_game_duration`; and
2. a game that was already invalid for a higher-priority reason retains that
   reason, avoiding unrelated diagnostic churn.

For example, the Q2 2022 `Default` placeholder remains
`missing_or_invalid_sides` because its side failure occurs earlier. By
contrast, an otherwise complete draft with `Default`, a blank duration, or an
absent duration is now `missing_game_duration`.

Within this policy, a valid duration means a non-null value produced by the
existing strict duration normalizer. The update does not introduce a minimum,
maximum, coercion, or inference rule.

Duration is eligibility metadata, not a predictive input. It remains in the
supervised schema's forbidden-column set and is absent from every canonical
training row.

## 3. Implementation boundary

The policy is implemented in the established normalized eligibility function
in `src/liquipedia_pipeline/features.py`. No acquisition, HTTP, cache,
checkpoint, raw-loader, parser, identity, side, draft-slot, or target logic
was changed.

The independent supervised builder now has a stale-lineage fail-fast check in
`src/draft_training_dataset/builder.py`. After applying dataset scope, it
rejects any normalized input that simultaneously has:

- `is_trainable_draft == True`; and
- a null `duration_seconds`.

The builder does not silently repair or reclassify stale normalized data. It
requires that such inputs be rebuilt through the current normalized
eligibility contract.

This preserves the approved architecture:

```text
immutable official API cache
  -> normalized eligibility decision
  -> normalized Parquet
  -> independent supervised contract validation
  -> dota-draft-supervised-v1
```

The normalized and supervised column schemas remain unchanged. New
content-addressed fingerprints record the policy and source-code changes.
Earlier builds remain immutable historical artifacts.

## 4. Exact historical effect

Across the eight completed historical quarters, 29 games have a null
normalized duration. Twenty-eight were already excluded by a higher-priority
existing reason. Exactly one game changed eligibility:

| Field | Value |
| --- | --- |
| Partition | `2023-Q1` |
| Source match ID | `7vCFkekwDr_0003` |
| Source game ID | `2` |
| Zero-based game index | `1` |
| Source duration | blank string |
| Normalized duration | null |
| Winner | team slot 1 |
| Sides | team 1 Dire; team 2 Radiant |
| Draft | 10 picks and 14 bans |
| Previous status | eligible |
| New status | excluded |
| New reason | `missing_game_duration` |

Because team slot 1 was Dire, this row was previously a Radiant loss. Its
removal changes the class count but does not alter any target derivation rule.

## 5. Rebuilt partition results

| Partition | Matches | Games | Eligible | Excluded | Supervised fingerprint |
| --- | ---: | ---: | ---: | ---: | --- |
| 2022-Q1 | 353 | 787 | 779 | 8 | `2e6069c5df66b203741c04cd34a4a80173937ee666f2769bafd7c1c66a8bcad2` |
| 2022-Q2 | 357 | 764 | 754 | 10 | `fa6980d55e2913451e7ce175802c823c0749c792b18be18851e5410361891c60` |
| 2022-Q3 | 446 | 969 | 964 | 5 | `fa87a75ea1f87b6b84a77e7d3c1fa935f0c80170b229b8164ee614e44ef25d3e` |
| 2022-Q4 | 265 | 578 | 573 | 5 | `cf2e6c8888c618eb322a11140def1f33adf0cb4d7546596c8c3a695915391f34` |
| 2023-Q1 | 551 | 1,224 | 1,222 | 2 | `46939cef4ac0f1c325c36c2cec5b175f5ab78fc77da64bda770732c2501a8d79` |
| 2023-Q2 | 546 | 1,171 | 1,166 | 5 | `57c335f94a28ac3771668f5409ffc3f813efcffabcf75ca299012e89ce6b5c9f` |
| 2023-Q3 | 421 | 943 | 921 | 22 | `825269301734ee9c09d2c09b1dbcba3f0d7006c8e68833b3721d53d55bf18be9` |
| 2023-Q4 | 428 | 826 | 811 | 15 | `5f3ee4637103fa679f02a08c98a7ecf2ecefd26ebc92a6d10bd5cf7c9a994042` |

The cache-only July 2026 pilot supervised fingerprint is:

`eda834e2a06f721e03fb0252cb327f07369fe2926be3b0acca9a115f5fcaf481`

### Completed historical scope

For Stage B plus the completed Stage C partitions, `2022-Q1` through
`2023-Q4`:

| Metric | Result |
| --- | ---: |
| Matches | 3,367 |
| Games | 7,262 |
| Eligible supervised games | 7,190 |
| Excluded games | 72 |
| Eligibility | **99.008538%** |
| Newly excluded by this policy | 1 |

### Completed Stage C scope

For `2022-Q2` through `2023-Q4`:

| Metric | Result |
| --- | ---: |
| Matches | 3,014 |
| Games | 6,475 |
| Eligible supervised games | 6,411 |
| Excluded games | 64 |
| Eligibility | **99.011583%** |
| Newly excluded by this policy | 1 |

Lineage catalog fingerprints:

| Scope | Fingerprint |
| --- | --- |
| Stage C completed partitions | `b63aad432598b4725508e4a20922125e89f5e2d481d9d42e45cd419a2d0dea8b` |
| Completed historical scope | `1de36d811a6b7d396bb7a29b9eb49f37d78eec2d0c018c5f39e0e0af9e135e81` |
| Completed history plus pilot | `04e33e299d132bbb6ccb67229309774be335ad4356943c12be85835d2b7ea855` |

## 6. Offline validation

The completed-partition gate verified:

- immutable raw cache and acquisition accounting;
- unchanged assembly inputs and accepted-record identities;
- normalized table hashes and manifests;
- the new duration eligibility condition;
- the stale-normalized-input fail-fast behavior;
- normalized-game reconciliation to eligible or excluded supervised rows;
- `missing_game_duration` as an approved exclusion reason;
- absence of `duration_seconds` from supervised training columns;
- supervised artifact hashes and raw → normalized → supervised lineage; and
- aggregate row counts and fingerprints.

Result:

```text
PASS_COMPLETED_PARTITIONS
```

Final complete offline test-suite result:

```text
.........................................................                [100%]
57 passed in 6.19s
```

The command was `.venv/bin/python -m pytest -q`. An earlier direct
`.venv/bin/pytest -q` invocation failed during collection because that
launcher did not place the repository root on `sys.path`; the module-based
project command above is authoritative and passed.

## 7. Request and cache accounting

| Control | Result |
| --- | ---: |
| Authenticated HTTP attempts during this update | 0 |
| Cache-only completed partitions rebuilt | 8 |
| Cache-only pilot rebuilt | 1 |
| SQLite ledger attempts before update | 48 |
| SQLite ledger attempts after update | 48 |
| Raw response bodies modified | 0 |
| API credential read or exposed | no |

The acquisition configuration, request hashes, immutable response bytes,
response hashes, assembly snapshots, and SQLite ledger were not rewritten by
the eligibility-policy rebuild.

## 8. 2024-Q1 readiness and strict compatibility findings

Campaign readiness for `2024-Q1` still fails with:

```text
partition_budget_exhausted
```

The partition previously consumed its approved 8-request limit and cached
eight full pages without reaching a terminal page. This policy update did not
resume the partition and made no request for `2024-Q1`, `2024-Q2`, or any
later quarter.

A read-only inspection of cached page sequence 8 at offset 700 also found four
unsupported non-null duration strings:

| Match | Game ID | Game index | Cached JSON path | Value | Winner | Sides | Draft |
| --- | --- | ---: | --- | --- | --- | --- | --- |
| `D8VM7QJos8_R04-M001` | `3` | 2 | `result[92].match2games[2].length` | `<s>Game 3</s>` | missing | missing | 2 picks, 0 bans |
| `D8VM7QJos8_R04-M003` | `3` | 2 | `result[93].match2games[2].length` | `<s>Game 3</s>` | missing | missing | 2 picks, 0 bans |
| `D8VM7QJos8_R05-M002` | `3` | 2 | `result[96].match2games[2].length` | `7m04` | team slot 1 | Radiant/Dire | 2 picks, 0 bans |
| `D8VM7QJos8_R06-M001` | `5` | 4 | `result[97].match2games[4].length` | `<s>Game 5</s>` | missing | missing | 2 picks, 0 bans |

These values are not the approved `Default` sentinel. The strict normalizer
continues to reject them. It does not strip markup, infer that `7m04` means
`7m04s`, or allow eligibility to hide a normalization error.

Accordingly, the duration eligibility policy passes for every completed
partition, but it does not resolve the separate 2024-Q1 acquisition-budget
or strict-format compatibility gates.

## 9. Deviations and limitations

- The policy changes row eligibility, not feature semantics or target
  derivation.
- The single-reason audit format records the first failure. It does not claim
  that every null-duration game is counted under `missing_game_duration`.
- Missing duration is not imputed and is not exported as a model feature.
- Four unsupported 2024-Q1 duration strings remain strict normalization
  errors.
- The known near-67-second ledger timing observation is unchanged; this
  cache-only update introduced no timing event.
- This report supplements the Stage C acquisition report and its updated
  machine-readable summary.

## 10. Approval boundary

The approved duration eligibility policy is implemented and the completed
historical partitions pass the offline raw → normalized → supervised
validation chain.

Stage C was **not resumed** because `2024-Q1` remains
`partition_budget_exhausted`. The four strict-format duration values are also
recorded for a separate compatibility decision.

No Stage D publication, aggregate canonical dataset, feature engineering,
model training, backend, or frontend work was started.
