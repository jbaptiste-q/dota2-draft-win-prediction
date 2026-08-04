# Milestone 6: Production Release and Deployment

Status: **complete — public deployment verified**

Milestone 6 packages and deploys the frozen Draft Assistant v1 contract. It
does not change the model, reopen evaluation, add recommendations, acquire
data, or broaden the supported workflow.

## Objective

Make the completed-draft product publicly accessible from a stable URL and
prove that the deployed revision preserves the reviewed local behavior,
security boundary, and model disclosures.

The deployed experience must support only:

1. completed 5v5 draft probability analysis;
2. exact additive hero contribution explanations;
3. user-directed one-for-one completed-draft comparison; and
4. visible model evidence and limitations.

## Frozen release boundary

M6 deploys the contract recorded in
[Milestone 5.3](MILESTONE_5_3_PRODUCT_CONTRACT_FREEZE.md). In particular:

- the candidate remains `b1_full_uniform_c0p01`;
- the inference input remains unordered, side-relative completed picks;
- the existing versioned response schemas remain unchanged;
- replacement comparison remains non-causal and never a recommendation;
- the failed 2025-Q4 readiness result remains visible;
- 2026-Q1 remains unevaluated; and
- runtime inference remains independent of Liquipedia credentials,
  authenticated payloads, ignored datasets, and executable model
  serialization.

## Deployment identity

The following values must be copied from observed deployment and repository
state. They must not be inferred from local plans.

| Field | Verified value |
| --- | --- |
| Public Draft Lab URL | `https://dota2-draft-ai.qinxuwwi.chatgpt.site/` |
| Deployment provider | OpenAI Sites, Cloudflare Worker runtime |
| Deployment/project ID | `appgprj_6a6dcba596ec819185d607d19b7ea658` |
| Deployment version | `1` |
| Deployment version ID | `appgprj_6a6dcba596ec819185d607d19b7ea658~appgver_d7737cc3032081918da9c8522432aa5a` |
| Deployment ID | `appgdep_6a6dcf52b1c48191a344a103630da56f` |
| Source commit SHA | `831b0e2e60f44f7fc993665f72dc1c54a49ce913` |
| Source branch | `codex/portfolio-v1-release` |
| Deployment timestamp | `2026-08-01T10:54:58.465594+00:00` |
| Product release version | `v1.0.0` prepared for M7 publication |
| Inference snapshot SHA-256 | `bfb7fc8d907e77057cafaef8109a4aec8085915c9215f0dc43cc15ff61dc1a61` |
| Inference artifact fingerprint | `69730a62f42cda234337e8cbf152fb50fcb7ae02faf38367955c267fbe714442` |

> **Update:** the deployment has since moved off OpenAI Sites hosting to this
> repository's own Cloudflare account. The current live URL is
> `https://dota2-draft-lab.jbaptiste-q.workers.dev`. This table is left
> unchanged as the historical record of the M6 deployment it verified.

The recorded Sites deployment reached terminal status `succeeded` with public
access. The URL was then opened in the in-app browser and reported the expected
`Draft Lab — Completed Draft Analysis` title.

## Deployment adapter

FastAPI remains the canonical local API and contract reference. The selected
hosting runtime does not execute Python, so M6 adds one thin, parity-tested
Worker adapter rather than introducing a second backend or a separate hosting
provider. The adapter imports the canonical frontend and exact SHA-pinned JSON
snapshot at build time and mirrors only the five frozen public routes.

Golden tests generate responses from the Python service and compare the full
Worker payloads, deterministic identifiers, ordering, validation behavior, and
floating-point values. No persistence, authentication, live data source, or
new product capability is introduced.

## Required production verification

| Check | Result |
| --- | --- |
| Production deployment reached a terminal successful state | **Passed** |
| Public URL loads without authentication | **Passed — HTTP 200** |
| Root HTML and versioned static assets are served | **Passed — HTML, CSS, JavaScript, and social image** |
| Health, hero catalog, and model-card routes return their frozen schemas | **Passed — exact payload parity** |
| Example completed-draft API request succeeds | **Passed — exact canonical response** |
| User-directed replacement API request succeeds | **Passed — exact canonical response** |
| Probability and contribution values match the reviewed local contract | **Passed** |
| Failed readiness and sealed-test disclosures remain visible | **Passed** |
| `recommendation: false` and non-causal replacement semantics remain visible | **Passed** |
| Security headers preserve same-origin runtime access | **Passed — CSP, referrer, content-type, and framing policies** |
| Product-specific 1200×630 social preview is served | **Passed** |
| No Liquipedia credential is included in the deployment | **Passed** |
| No authenticated payload, local database, or generated training data is included | **Passed** |
| No runtime request is made to Liquipedia | **Passed** |

The production smoke test compared all three GET JSON contracts, one completed
draft analysis, one replacement comparison, and the stable unsupported-hero
error with responses from the canonical local Python service. It observed 125
supported heroes and all five published schema versions. Browser visual QA was
not part of this release gate because it was not requested; the canonical
frontend's existing offline accessibility and interaction assertions remain
in force.

## Offline release validation

| Check | Result |
| --- | --- |
| Complete active offline test suite | **410 passed; 16 known Joblib/NumPy deprecation warnings** |
| Python compilation | **Passed** |
| Dependency consistency | **Passed — no broken requirements** |
| Repository hygiene | **Passed** |
| Credential-pattern review | **Passed** |
| JavaScript or site build checks | **10/10 parity tests passed; type-check and lint passed** |
| Working-tree whitespace validation | **Passed** |
| Authenticated Liquipedia requests | **0** |
| Model training or optimization | **0** |
| Locked 2026-Q1 evaluation access | **0** |

Test counts and warnings must be copied from the final command output rather
than carried forward from an earlier milestone.

## Security and data handling

The production artifact must contain only source and compact credential-free
runtime assets required by Draft Assistant v1. It must not contain:

- `.secrets/` or environment files;
- a Liquipedia key;
- authenticated API response bodies;
- raw acquisition caches;
- SQLite ledgers or checkpoints;
- normalized or supervised dataset builds;
- local model bundles; or
- local filesystem paths.

The official Liquipedia API remains an offline acquisition source. It is not a
browser or deployed-runtime dependency.

## Deviations and limitations

| Item | Record |
| --- | --- |
| Deployment deviations | None from the frozen product contract |
| Compatibility findings | The hosting runtime does not execute Python; the thin Worker is guarded by full golden-response parity |
| Non-blocking warnings | 16 existing Joblib/NumPy deprecation warnings; one initial local production client connection timed out before the successful 60-second smoke run |
| Known product limitations | Frozen in M5.3 and shown in the product |

An implementation detail should be added here only if it affects
reproducibility, security, the deployed user experience, or the frozen product
contract.

## Completion criteria

M6 is complete only when:

1. the frozen Draft Assistant is available at a verified public URL;
2. the deployed source revision and artifact identity are recorded;
3. the primary analysis and replacement workflows pass production inspection;
4. model evidence and limitations remain visible;
5. secrets and local authenticated data are absent;
6. offline and deployment validation results are recorded above; and
7. no model, data, or recommendation scope was added.

After those facts are recorded, M7 may publish the exact reviewed deployment
as the portfolio release.
