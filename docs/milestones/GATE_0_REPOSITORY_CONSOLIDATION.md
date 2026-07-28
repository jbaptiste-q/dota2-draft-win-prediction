# Gate 0: Repository Consolidation

Status: **complete; approved for commit with documented roadmap debt**

Report date: 2026-07-28

Authenticated API requests: **0**

Model training runs: **0**

Raw cache changes: **0**

## 1. Objective

Make the repository accurately represent the official-Liquipedia-based Dota 2
Draft AI before Milestone 3.6, without redesigning or modifying the validated
Milestones 1–3.5 architecture.

The canonical product story is now:

```text
Official Liquipedia API
  -> immutable acquisition and provenance
  -> normalized and versioned datasets
  -> drift-aware modeling
  -> recommendation engine
  -> inference API
  -> interactive web application
```

## 2. Initial Git state

| Item | Initial value |
| --- | --- |
| Branch | `main` |
| Upstream | `origin/main` |
| Ahead / behind | `0 / 0` |
| HEAD | `ed4b50f3da2345e65fcaa71b0c5166009d76ab5a` |
| Local `origin/main` | `ed4b50f3da2345e65fcaa71b0c5166009d76ab5a` |
| Staged changes | none |
| Modified tracked files | `.gitignore`, `README.md`, `data/README.md` |
| Untracked files | 74 |
| Tracked project state | 21 files, primarily the older Kaggle baseline |

The official Liquipedia packages, scripts, tests, milestone documentation,
campaign evidence, and release evidence existed locally but were not in the
Git index.

The local ref for `origin/main` was inspected without fetching. Gate 0 made no
network request.

## 3. Repository classification

### Canonical

- `src/liquipedia_pipeline/`: immutable loading, parsing, normalization,
  relational datasets, quality observations, and export.
- `src/liquipedia_backfill/`: guarded client, request planning, immutable
  cache, SQLite state, campaign coordination, assembly, reports, and
  publication.
- `src/draft_training_dataset/`: canonical supervised schema and builder.
- The seven existing Liquipedia validation, acquisition, build, planning, and
  publication scripts.
- The official offline test suite and Milestones 1–4 documentation.
- Credential-free campaign configuration, request hashes, summaries, release
  aliases, manifests, and compact coverage evidence.

### Deprecated and archived

The original Kaggle baseline was moved, without content deletion, to
`archive/kaggle_baseline/`:

- feature and training modules;
- data download and sample-build scripts;
- their unit tests;
- three notebooks;
- source-column and leakage documentation; and
- the tracked raw previews, patch mapping, sample, and sample metadata.

It has its own README, dependencies, and Python package marker. It is excluded
from root test collection and is not an active data or model path.

### Generated and local-only

- `.venv/`, pytest/bytecode/tool caches, and operating-system metadata;
- authenticated discovery and validation responses;
- raw Liquipedia backfill cache;
- SQLite ledgers, checkpoints, run assemblies, and local plans;
- normalized and supervised content-addressed builds;
- model artifacts; and
- the ignored full Kaggle Parquet source remaining in existing local clones.

These files were not moved, rewritten, staged, or read as training inputs.

### Sensitive

`.secrets/liquipedia_api_key` exists locally with file mode `0600` under an
ignored `.secrets/` directory. Its value was never read or printed. No
credential-like path was found in the reachable Git history.

### Resolved ambiguity

`data/backfill/campaigns/` and `data/releases/dota_draft_historical/` are
generated artifacts, but the selected contents are small, credential-free,
immutable reproducibility evidence. They are intentionally versioned.
Authenticated bodies, local state, and large normalized/training builds remain
ignored.

## 4. Architecture decisions

1. Preserve the existing `src.*` namespace and three independent official
   packages. Renaming or merging them would introduce risk before Milestone
   3.6 without resolving a real duplication.
2. Treat `dota-draft-supervised-v1` as the canonical boundary between data
   engineering and future model-specific transformations.
3. Archive the Kaggle baseline rather than delete it, while removing its
   modules, scripts, tests, notebooks, and data from active paths.
4. Keep compact release Parquet coverage tables in Git because the complete
   public release evidence is only about 68 KB and contains no authenticated
   payload.
5. Enforce offline tests technically through an autouse socket/DNS blocker,
   rather than relying only on convention.
6. Use a dependency-free repository-hygiene script instead of introducing a
   new secret-scanning dependency during consolidation.

## 5. Changes made

- Archived 16 Kaggle paths with 100% Git rename detection.
- Added the archive README, dependencies, and package marker.
- Added the complete official Liquipedia source, scripts, tests,
  documentation, campaign evidence, and release evidence to the index.
- Rewrote the root README and data README around the canonical product and
  public/local data boundary.
- Reduced active dependencies to `duckdb`, `pandas`, and `pytest`; historical
  notebook/model dependencies remain in the archive.
- Added `pytest.ini` so only `tests/` is collected.
- Added a repository-wide outbound-network blocker and explicit offline-policy
  tests.
- Added `scripts/check_repository_hygiene.py` for tracked-path, ignore-policy,
  and high-confidence credential-signature checks.
- Added `.github/workflows/offline-ci.yml` for Python 3.12 offline validation.
- Hardened ignore rules for credentials, environment files, caches, coverage,
  type/lint caches, generated datasets, model artifacts, and archived raw
  downloads.
- Applied whitespace-only cleanup to newly tracked source and milestone
  documents so the staged diff passes Git whitespace validation.

No HTTP client, parser behavior, normalization rule, schema, eligibility rule,
cache entry, checkpoint, raw response, or dataset artifact was modified.

## 6. Validation results

| Check | Result |
| --- | --- |
| `python -m compileall -q src scripts tests` | passed |
| `python scripts/check_repository_hygiene.py` | passed |
| `python -m pip check` | passed; local pip cache permission warning only |
| `git diff --cached --check` | passed |
| `python -m pytest -q` | **88 passed** |
| Authenticated/network requests | **0** |

The active suite includes parser, normalization, schema, acquisition planning,
cache, ledger, resume, request-budget, publication, lineage, tamper,
credential-free-plan, repository-hygiene, and no-network tests.

## 7. Intentionally deferred

- No formatter, linter, or type checker was selected because none was
  previously configured. That tool choice belongs in a separate reviewed
  developer-experience change.
- No Git commit, push, branch rewrite, history rewrite, or remote fetch was
  performed.
- No repository license was selected; that requires an explicit ownership and
  licensing decision.
- A history-wide third-party secret scanner was not added because no scanner
  is installed locally. GitHub secret scanning/push protection or a pinned
  `gitleaks` CI job can be enabled separately.
- A historical report reference to a `/private/tmp` validation helper remains
  unchanged as execution evidence; it is not presented as a current entry
  point.
- The ignored 32 MB legacy Kaggle Parquet file was left physically untouched.

## 8. Final pre-commit Git state

| Item | Final value |
| --- | --- |
| Branch | `main` |
| HEAD and local `origin/main` | `ed4b50f3da2345e65fcaa71b0c5166009d76ab5a` |
| Staged additions | 83 |
| Staged modifications | 5 |
| Staged renames | 16, all detected at 100% similarity |
| Unstaged tracked changes | 0 |
| Untracked non-ignored files | 0 |
| Commit or push at review checkpoint | no |

The staged diff contains 104 changed paths. Credential, cache, local-state,
environment, generated-build, and model-artifact probes are still ignored by
the final rules.

## 9. Recommended commit structure

1. `chore(repo): archive the legacy Kaggle baseline`
2. `feat(data): add the official Liquipedia pipeline and release evidence`
3. `ci: enforce offline tests and repository hygiene`
4. `docs: align the repository with the Draft AI roadmap`

The changes are staged together for safety and completeness, but can be
unstaged and committed in these reviewable groups.

## 10. Milestone 3.6 readiness

Gate 0 is complete. The canonical acquisition code, cache/ledger architecture,
normalization pipeline, supervised builder, contracts, tests, and campaign
evidence are present and protected by offline CI.

Milestone 3.6 can begin after the staged consolidation is reviewed and
committed. The public repository will not reflect this state until those
commits are pushed.

## 11. Accepted documentation debt

The final read-only Gate 0 review found no implementation, credential,
artifact, package, dependency, archive, CI, or validation blocker. It did find
historical documents whose milestone wording predates the approved roadmap.
The project owner accepted these items as non-blocking documentation debt and
authorized the Gate 0 commit and Milestone 3.6 start.

The Milestone 4 documentation restructuring must:

1. split model work into M4A development/pipeline validation and M4B final
   model selection on the completed 2026 corpus;
2. mark the provisional 2022-Q1 through 2024-Q1 modeling plan as development
   evidence rather than the final production evaluation contract;
3. add supersession notes to the historical M1 and M3.5 documents where their
   original recommendations conflict with validated field limitations or the
   approved M3.6 gate; and
4. preserve the original milestone reports as historical evidence instead of
   silently rewriting their contemporaneous decisions.

This debt does not change acquisition behavior, the normalized or supervised
schemas, eligibility, lineage, or the Milestone 3.6 execution boundary.
