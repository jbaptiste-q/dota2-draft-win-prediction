# Milestone 3.6: Offline Dataset-Completion Readiness

Status: **complete; authenticated execution not started**

## 1. Outcome

Milestone 3.6 has passed its offline readiness gate. The existing official
Liquipedia acquisition, immutable cache, SQLite ledger, finalizer,
normalization pipeline, supervised builder, and full-window publisher remain
the canonical implementation. No replacement data platform or duplicate HTTP
layer was introduced.

Gate 0 was committed first as:

```text
3c19df9 chore(repo): consolidate official Liquipedia project
```

The accepted historical-document wording issues remain recorded as Milestone
4 documentation debt. They do not alter the M3.6 data contract.

## 2. Certified starting state

| Item | Certified value |
| --- | --- |
| Base campaign | `m3_5_20220101_20260727_e2c4c37a9792` |
| Campaign configuration fingerprint | `e2c4c37a9792cfa3e724d6bfee1173feb1c1ec880644ef43b159c73a2ca52774` |
| Base campaign plan fingerprint | `b443f0910d40dfdb0f6986b17b76b582cc738c7c9f162d42317ef632c3759b9b` |
| Complete historical partitions | `2022-Q1` through `2024-Q1` |
| Next partition | `2024-Q2` |
| Expansion HTTP attempts already consumed | `63` |
| Total ledger attempts including the pilot | `65` |
| HTTP outcomes | `65` successful HTTP 200 responses; no recorded 403 or 429 |
| Immutable cache entries | `65` |
| July 2026 pilot | Complete and certified for cache-only reuse |

The SQLite file hash was
`2c81e23eb4d46e74f1f88eef2c60adc3e1edfb508e9db4fdc0f15d5c0a4a5df1`
before and after planning. Its request count remained `65`; the cache-entry
count also remained `65`.

## 3. Minimal compatibility decision

The cached `2024-Q2` prefix contains one otherwise-eligible game whose exact
official duration value is `21m38`:

| Field | Value |
| --- | --- |
| Source match | `ubD8YXh91K_R02-M001` |
| Source game | `2` |
| Patch | `7.36b` |
| Supporting publisher game ID in the raw evidence | `7783589011` |

The value is not added to the generic duration grammar and is not converted to
1,298 seconds. Only this exact reviewed occurrence, under its complete
match/game/draft context, normalizes to missing duration. The unchanged
eligibility policy then excludes it as `missing_game_duration`. Any context
mismatch for the reviewed key, or any unrelated otherwise-eligible `21m38`,
remains a strict normalization error. The pre-existing safe fallback may still
normalize an unsupported duration to missing when a game is already
ineligible for an earlier, independently established reason.

The publisher game ID is retained as supporting raw evidence; it is not a
normalizer predicate because `ParsedGame` deliberately does not retain that
field.

Raw source bytes are preserved unchanged.

## 4. Cached Q2 proof build

All eight immutable `2024-Q2` prefix pages were rebuilt offline through the
unchanged normalized and supervised layers:

| Metric | Result |
| --- | ---: |
| Cached matches | 800 |
| Normalized games | 1,588 |
| Eligible supervised games | 1,507 |
| Explicit exclusions | 81 |
| Eligibility | 94.90% |
| Radiant wins | 753 |
| Radiant losses | 754 |
| Hero vocabulary | 124 |

Observed exclusion reasons were already understood:

- `duplicate_picked_hero`;
- `incomplete_team1_bans`;
- `incomplete_team1_picks`;
- `incomplete_team2_bans`;
- `invalid_game_result`;
- `invalid_series_result`;
- `missing_game_duration`; and
- `missing_or_invalid_sides`.

No new unexplained exclusion reason or systemic schema incompatibility
appeared.

## 5. Immutable M3.6 plan

The plan preserves the original 100-attempt M3.5 authorization as historical
evidence. It proposes a separate M3.6 ceiling:

| Budget item | Value |
| --- | ---: |
| Existing expansion attempts | 63 |
| Expected remaining requests | 25–50 |
| Proposed maximum new M3.6 attempts | 80 |
| Proposed cumulative expansion ceiling | 143 |
| Page-slot ceiling for each unfinished quarter | 20 |
| Automatic retries | 0 |
| Rolling-hour limit | 54 |
| Minimum configured request interval | 67 seconds |

The 80-attempt value is a hard stop, not a forecast. Terminal short pages stop
each partition early, so unused slots do not become requests.

The effective plan contains the original 19 logical partitions:

- existing completed runs are reused through `2024-Q1`;
- `2024-Q2` uses run
  `m3_20240401_20240701_df05306783f7`, requires its eight certified cache
  pages, and allows at most 12 new attempts;
- `2024-Q3` through `2026-Q2` remain chronological, each with 20 page slots;
  and
- the exact July 2026 pilot remains cache-only.

The intended final full-window alias remains the already designed
`m3.5-tier1-tier2-2022-2026-v1`. Milestone 3.6 completes the approved M3.5
campaign; changing the release alias would add no data or reproducibility
value.

## 6. Fingerprints and public evidence

| Artifact | Fingerprint |
| --- | --- |
| M3.6 completion plan | `80bf4dc4fa31810dca0d1b8d3f1ece37779e0560dc1eeaeccd435e05e6ebbde0` |
| Current M3.6 preflight | `2255aa5979e0743ebba28a95ca453bcca5c4cd48d6f7e6608bca621f91033280` |
| First conditional Q2 request | `b9180afeb42f5af39906dfbd4096f4f5c2601f479b0d8212d6619907e9a9ec54` |

Machine-readable and Markdown evidence is stored in:

```text
data/backfill/campaigns/
  m3_5_20220101_20260727_e2c4c37a9792/
    milestone_3_6/
```

These files contain exact request identities and repository-relative paths,
but no API key, authenticated response body, local database, checkpoint, or
absolute workstation path. The preflight also pins all eight Q2 prefix
request hashes and response SHA-256 values.

## 7. Offline commands executed

```bash
.venv/bin/python -m pytest -q tests/test_liquipedia_pipeline.py

.venv/bin/python scripts/build_liquipedia_dataset.py \
  --input <each of the eight immutable Q2 cached responses> \
  --output-root <temporary-directory>

.venv/bin/python scripts/build_draft_training_dataset.py \
  --normalized-build <temporary-normalized-build> \
  --output-root <temporary-directory>/training

.venv/bin/python scripts/complete_liquipedia_history.py \
  --plan \
  --max-additional-network-attempts 80

.venv/bin/python scripts/complete_liquipedia_history.py \
  --preflight \
  --max-additional-network-attempts 80
```

The final repository-wide validation commands and results are recorded at the
end of this report after execution.

## 8. Authenticated boundary

Planning and preflight made zero authenticated requests and did not read the
API key. The M3.6 command remains deliberately fail-closed in execute mode
until the proposed numeric ceiling receives explicit approval.

The first live partition action, after approval, will reuse the first eight
Q2 pages and permit no more than 12 new attempts:

```bash
.venv/bin/python scripts/backfill_liquipedia_history.py \
  --start 2024-04-01T00:00:00Z \
  --end 2024-07-01T00:00:00Z \
  --tier 1 \
  --tier 2 \
  --page-size 100 \
  --max-requests 20 \
  --max-network-attempts 12 \
  --require-cache-prefix-pages 8 \
  --hourly-limit 54 \
  --request-interval-seconds 67 \
  --timeout-seconds 30 \
  --execute \
  --confirm-live-request-budget 12
```

No authenticated command was executed during this sub-milestone.

## 9. Completion boundary

This report completes only the offline readiness sub-milestone. M3.6 itself is
complete only when:

1. every remaining quarter reaches a terminal page and passes its existing
   cache, ledger, checkpoint, normalization, supervised, lineage, and test
   gates;
2. all 19 partitions publish in full-window mode;
3. the normalized and `dota-draft-supervised-v1` fingerprints reconcile;
4. the final non-provisional coverage and anomaly evidence is versioned; and
5. the mandatory M3.6 completion report is generated.

Feature engineering, model training, backend, frontend, and deployment remain
out of scope until this dataset-completion gate finishes.

## 10. Final offline validation

| Check | Result |
| --- | --- |
| Python compilation | Passed |
| Dependency consistency | Passed: `No broken requirements found.` |
| Repository and credential hygiene | Passed |
| Staged/working-tree whitespace | Passed |
| Focused pipeline and M3.6 tests | Passed: `43` |
| Complete active offline suite | Passed: `102 passed in 11.44s` |
| Q2 prefix normalized fingerprint | `a2c2f4c668cea16f1e3eb67845de68d31a02aae2bb98c0d814de287898ef0c65` |
| Q2 prefix supervised fingerprint | `eff06e3810bcbc670702dd8da705344e55c417b7b6df12de5a27c7700e9baad6` |

The dependency check emitted only a local pip-cache ownership warning and
still reported no broken requirements. This is an environment warning, not a
repository or dataset defect.

All validation was offline. No authenticated request, model training, backend
work, frontend work, or deployment work occurred.
