# Milestone 7: Portfolio Release and Final Acceptance

Status: **pending Milestone 6 acceptance**

Milestone 7 turns the verified deployment and repository into one finished,
recruiter-readable Applied AI case study. It adds no product capability and
does not reopen modeling research.

## Objective

Publish a stable release that lets a reviewer answer five questions quickly:

1. What user problem does Draft Lab address?
2. What can the product actually do?
3. How does data become a reproducible runtime prediction?
4. What evidence supports or limits the model?
5. Can the exact reviewed product be run, inspected, and verified?

## Final product statement

Draft Assistant v1 analyzes a completed professional Dota 2 draft. It returns
a model-estimated Radiant/Dire probability, reconstructable additive hero
contributions, and a user-directed comparison between two completed drafts.

It is an experimental Applied AI engineering demonstration. The selected
candidate failed its 2025-Q4 readiness gate, was not promoted, and did not open
the sealed 2026-Q1 evaluation. The product therefore does not claim
production-quality forecasting and does not rank or recommend heroes.

## Public release artifacts

| Artifact | Status |
| --- | --- |
| Recruiter-first repository README | **Prepared; deployment URL and release identity pending** |
| Accurate as-built architecture diagram | **Prepared in README** |
| Concise product walkthrough | **Prepared in README** |
| Product preview image | **Pending verified `site/public/og.png` artifact** |
| Public deployment record | **Pending M6 completion** |
| Final acceptance evidence | **Pending M6 completion and final validation** |
| Versioned source commit | **Pending reviewed commit** |
| Git tag | **Pending reviewed release commit** |
| GitHub release notes | **Pending reviewed release commit and tag** |

Historical milestone reports remain chronological engineering records. The
README, M5.3 contract, M6 deployment record, and this report define the final
public product story.

## Release identity

Values in this table must come from the exact reviewed and deployed revision.

| Field | Final value |
| --- | --- |
| Product version | **Pending release decision** |
| Git tag | **Pending successful tag creation** |
| Release commit SHA | **Pending reviewed release commit** |
| Public Draft Lab URL | **Pending verified M6 deployment** |
| Deployment version ID | **Pending verified M6 deployment** |
| Release date | **Pending release publication** |
| API version | `0.3.0` |
| Analysis schema | `draft-assistant-analysis-v1` |
| Model-card schema | `draft-assistant-model-card-v1` |
| Replacement schema | `draft-assistant-replacement-comparison-v1` |
| Snapshot SHA-256 | `bfb7fc8d907e77057cafaef8109a4aec8085915c9215f0dc43cc15ff61dc1a61` |
| Artifact fingerprint | `69730a62f42cda234337e8cbf152fb50fcb7ae02faf38367955c267fbe714442` |

API schema versions identify interface compatibility; they are not a
substitute for the product release tag.

## Acceptance evidence

| Gate | Final result |
| --- | --- |
| M5.3 product contract remains unchanged | **Pending final diff review** |
| Public deployment verified | **Pending M6 completion** |
| Production root, assets, and frozen API routes verified | **Pending M6 completion** |
| Example completed-draft API response verified | **Pending M6 completion** |
| User-directed replacement API response verified | **Pending M6 completion** |
| Product limitations and failed readiness evidence visible | **Pending M6 completion** |
| Full offline suite | **Pending final observed result** |
| Site build, golden parity, type, and lint checks | **Pending final observed result** |
| Canonical frontend interaction and accessibility assertions | **Pending final observed result** |
| Repository hygiene and credential checks | **Pending final observed result** |
| Reviewed release diff contains no local-only data | **Pending final Git review** |
| Authenticated Liquipedia requests during M5.3–M7 | **Pending final ledger statement; none authorized** |
| Model fits or optimization during M5.3–M7 | **Pending final audit; none authorized** |
| Locked 2026-Q1 access during M5.3–M7 | **Pending final audit; none authorized** |

Exact test counts, warnings, commands, and production observations belong here
only after they have been run against the release candidate.

## Reproducibility chain

The final release preserves this evidence path:

```text
Official Liquipedia API
  -> immutable authenticated data kept local
  -> credential-free request and provenance evidence
  -> normalized versioned relational datasets
  -> dota-draft-supervised-v1
  -> leakage-safe temporal modeling evidence
  -> reviewed JSON inference snapshot
  -> deterministic service and API contracts
  -> interactive Draft Lab deployment
```

The public repository intentionally contains compact lineage evidence rather
than authenticated source responses or generated training datasets.

## Known limitations

- The model accepts completed 5v5 hero picks only.
- Picks are unordered within a side.
- Bans, pick order, first pick, synergy, counters, roles, lanes, patch, teams,
  players, and tournament context are not modeled.
- Hero contributions are associative additive evidence, not causal effects.
- Replacement comparisons are chosen by the user and are not recommendations.
- The development candidate failed the 2025-Q4 readiness gate.
- The sealed 2026-Q1 test remains unevaluated.
- The product is not intended for betting, professional coaching, or
  competitive decision automation.

These limits are visible in the runtime product and structured API responses,
not only in repository documentation.

## Repository policy

No open-source license is granted for this release. Unless a later license file
states otherwise, all rights are reserved by the repository owner. Public
visibility permits inspection but does not grant permission to copy, modify,
or redistribute the work.

Secrets, authenticated API payloads, raw caches, local databases, checkpoints,
generated datasets, executable model bundles, virtual environments, and local
deployment state must remain outside the release.

## Release notes boundary

The first release notes should describe only:

- completed-draft probability analysis;
- exact additive explanations;
- user-directed completed-draft replacement comparison;
- public model evidence and limitations;
- reproducible official-API data lineage;
- the public deployment URL; and
- commands for local offline verification.

They must not advertise hero recommendations, partial-draft intelligence,
production-ready accuracy, or a successful locked-test evaluation.

## Completion criteria

M7 is complete only when:

1. M6 is complete and its public URL is verified;
2. all pending identity and acceptance fields above contain observed values;
3. the reviewed source and evidence are committed;
4. local-only and sensitive artifacts are absent from the release diff;
5. the exact deployed commit receives the approved release tag;
6. release notes link the demo, architecture, walkthrough, and acceptance
   evidence;
7. the final validation suite passes; and
8. the repository narrative consistently presents the frozen experimental v1
   product without reopening modeling or recommendation scope.

No additional data platform, model family, dashboard, recommendation engine,
account system, or monitoring platform is required for portfolio completion.
