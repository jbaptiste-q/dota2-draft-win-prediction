# Data Boundaries

The active project uses the official Liquipedia API only. This directory
separates immutable source material, local reproducible builds, and compact
public provenance evidence.

## Version-controlled evidence

| Path | Contents |
| --- | --- |
| `validation/liquipedia/README.md` | Validation workflow and local-artifact contract; authenticated responses are excluded. |
| `backfill/campaigns/<campaign-id>/` | Selected credential-free campaign configuration, request hashes, plans, preflight evidence, amendments, and summaries. |
| `releases/dota_draft_historical/` | Immutable aliases, release manifests, and compact aggregate coverage evidence. |

These artifacts contain no API key or authenticated response body. They make
the dataset scope, request identities, source hashes, row counts, exclusions,
and lineage independently auditable.

## Local-only official data

| Path | Contents | Git policy |
| --- | --- | --- |
| `validation/liquipedia/runs/` | Authenticated exact-ID validation responses and reports. | Ignored |
| `validation/liquipedia/discovery/` | Authenticated bounded discovery responses and selection reports. | Ignored |
| `raw/liquipedia/backfill/` | Immutable response bytes, cache metadata, and request state. | Ignored |
| `backfill/runs/` | Checkpoints, SQLite ledgers, accepted-record snapshots, quarantine, and partition reports. | Ignored |
| `backfill/plans/` | Local pilot plans outside the selected public campaign evidence. | Ignored |
| `processed/liquipedia/build_*/` | Content-addressed normalized relational Parquet datasets. | Ignored |
| `training/dota_draft_supervised/build_*/` | Canonical supervised rows, exclusions, vocabulary, schema, data card, and manifest. | Ignored |

These directories are reproducible but can contain authenticated payloads,
large derived data, local paths, or transient campaign state. They remain
local and must not be staged.

## Current provisional release

```text
releases/dota_draft_historical/
├── aliases/m3.5-tier1-tier2-2022q1-2024q1-provisional-v1.json
└── build_a485f713ffaf94f7/
    ├── manifest.json
    └── coverage/
```

The release covers completed Tier 1 and Tier 2 professional matches in
`[2022-01-01, 2024-04-01)`. It points to:

- normalized fingerprint
  `6f44f771e75eabffb393f2a3a2bbe27097d4c882d38fbfd10b476fa66dfcae1f`;
- supervised fingerprint
  `c1ea1d31968eb4c9c6fc4cd8dd7812ca2189694ca94ace48b1aae676e146acd9`;
- 10,014 normalized games;
- 9,700 eligible supervised games; and
- 314 explicit exclusions.

The `provisional` label is intentional. Milestone 3.6 will fill the historical
gap and extend the campaign through 2026-07-27.

## Offline build commands

Normalize one or more saved responses:

```bash
python scripts/build_liquipedia_dataset.py \
  --input data/validation/liquipedia/runs/<run-id>/response.json
```

Build the canonical supervised dataset from a normalized build:

```bash
python scripts/build_draft_training_dataset.py \
  --normalized-build data/processed/liquipedia/<build-id>
```

Neither command reads credentials or makes a request.

## Archived Kaggle data

The tracked Kaggle sample, preview, patch mapping, and metadata moved to
`archive/kaggle_baseline/data/` with the rest of the historical experiment.
They are not active project inputs.

An ignored `data/raw/dota2_matches.parquet` may remain in older local clones.
Gate 0 deliberately left that 32 MB local file untouched. No canonical source,
script, test, or CI command references it.
