# Milestone 3.5 Campaign Preflight

Generated artifact — do not hand-edit.

- Campaign ID: `m3_5_20220101_20260727_e2c4c37a9792`
- Campaign state fingerprint: `e5d766da94e41715de6b934ed5ed0614f1d4f6e507ec9f1cd002b6c7e06d0490`
- Campaign status: `ready_to_resume`
- Stage A authenticated request delta: `0`
- API key read by Stage A: `false`

## Request Accounting

- Historical pilot attempts, excluded from expansion budget: `2`
- Milestone 3.5 additional attempts used: `4`
- Milestone 3.5 additional attempts remaining: `96`
- Verified cached pilot pages: `2`

## Cached Pilot Proof

- Run ID: `m3_20260701_20260727_0b40ae8811d6`
- Configuration hash: `0b40ae8811d6140590657c976ed350d44ab98c9d8289bde8c1d6a57221610258`
- SQLite status: `complete`
- Records: `108`
- Additional HTTP request required: `false`

| Page | Request hash | Response SHA-256 | Records | Final |
| ---: | --- | --- | ---: | --- |
| 1 | `9f0b310bee831a6c921fb568cdb5e71a979ebe9832f3e22b29c4e2afa21371c6` | `bc5ab9f31516795b0b8011ac796ed266a5effc2c41a88957cea350a8f3dce06e` | 100 | false |
| 2 | `0060ee0181d4b51e1c477ee857c41e08b8b9a0b40c8e04f65b924b47b98bfd66` | `2f15aa68c77c5b6b258ba9cd5063cbbfcfc480a94b92d65bc2437b382765ed81` | 8 | true |

The two later pilot request specifications are not missing cache
entries: they are unreachable because page 2 is terminal.

## Deterministic Resume

- Next partition: `2022-Q2`
- Next run: `m3_20220401_20220701_60f8944a646a`
- Next sequence: `1`
- Next offset: `0`
- Remaining campaign budget: `96`
- Partition remaining request ceiling: `8`

No acquisition run, checkpoint, cache entry, or request-ledger
row was created by this preflight.
