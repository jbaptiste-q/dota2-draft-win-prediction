# Dota Draft Historical Releases

This directory contains credential-free publication metadata for verified
historical Draft AI datasets. Authenticated API responses and generated
normalized/training Parquet files remain local and are excluded from Git.

## Current release

Alias:
`m3.5-tier1-tier2-2022q1-2024q1-provisional-v1`

Scope:
`[2022-01-01T00:00:00Z, 2024-04-01T00:00:00Z)`, Liquipedia Tier 1 and
Tier 2 completed professional matches.

| Artifact | Identity |
| --- | --- |
| Release | `a485f713ffaf94f784ea1c770478be5c172d60285eb8369e294d34d9d447e7da` |
| Normalized dataset | `6f44f771e75eabffb393f2a3a2bbe27097d4c882d38fbfd10b476fa66dfcae1f` |
| Supervised dataset | `c1ea1d31968eb4c9c6fc4cd8dd7812ca2189694ca94ace48b1aae676e146acd9` |
| Supervised schema | `dota-draft-supervised-v1` |

The release contains 4,977 matches, 10,014 normalized games, 9,700 eligible
supervised rows, and 314 excluded audit rows.

The `provisional` label is intentional. The release is the largest completed
contiguous prefix of the approved campaign. The incomplete 2024-Q2 cache,
later historical partitions, and separate July 2026 pilot are excluded.

## Verification boundary

The release manifest verifies:

- completed acquisition checkpoints and exact half-open partition scopes;
- immutable response and snapshot hashes;
- empty quarantine and conflict counts;
- stable match, game, and supervised identifiers;
- normalized schema, table hashes, and row counts;
- supervised schema, artifact hashes, and normalized lineage; and
- exact `normalized games = eligible games + excluded games` reconciliation.

The alias is immutable and points to content-addressed normalized and
supervised builds. Re-running the publication command verifies and reuses the
same artifacts without an API request.

See the
[Milestone 3.5 bounded publication report](../../../docs/milestones/MILESTONE_3_5_BOUNDED_HISTORICAL_DATASET_PUBLICATION.md)
for the acquisition outcome, known anomalies, coverage, limitations, and
handoff to Milestone 4.
