# Milestone 6: Production Release and Deployment

Status: **in progress — deployment evidence pending**

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
| Public Draft Lab URL | **Pending successful production deployment** |
| Deployment provider | **Pending observed deployment record** |
| Deployment/project ID | **Pending observed deployment record** |
| Deployment version ID | **Pending observed deployment record** |
| Source commit SHA | **Pending reviewed release commit** |
| Source branch | **Pending reviewed release commit** |
| Deployment timestamp | **Pending successful production deployment** |
| Product release version | **Pending M7 release decision** |
| Inference snapshot SHA-256 | `bfb7fc8d907e77057cafaef8109a4aec8085915c9215f0dc43cc15ff61dc1a61` |
| Inference artifact fingerprint | `69730a62f42cda234337e8cbf152fb50fcb7ae02faf38367955c267fbe714442` |

The deployment URL, IDs, commit, and timestamp remain pending until the
production result is inspected. A saved plan or local preview is not
deployment evidence.

## Required production verification

| Check | Result |
| --- | --- |
| Production deployment reached a terminal successful state | **Pending** |
| Public URL loads without authentication | **Pending** |
| One-click example completes successfully | **Pending** |
| Manual completed-draft analysis completes successfully | **Pending** |
| What-if replacement completes successfully | **Pending** |
| Probability and contribution values match the reviewed local contract | **Pending** |
| Failed readiness and sealed-test disclosures remain visible | **Pending** |
| `recommendation: false` and non-causal replacement semantics remain visible | **Pending** |
| Responsive desktop and mobile layouts pass visual inspection | **Pending** |
| Keyboard interaction and accessible names pass inspection | **Pending** |
| Browser console contains no unexpected errors | **Pending** |
| No Liquipedia credential is included in the deployment | **Pending** |
| No authenticated payload, local database, or generated training data is included | **Pending** |
| No runtime request is made to Liquipedia | **Pending** |

Observed commands, browser steps, response values, and deployment inspection
results should be recorded when these checks run.

## Offline release validation

| Check | Result |
| --- | --- |
| Complete active offline test suite | **Pending final observed run** |
| Python compilation | **Pending final observed run** |
| Dependency consistency | **Pending final observed run** |
| Repository hygiene | **Pending final observed run** |
| Credential-pattern review | **Pending final observed run** |
| JavaScript or site build checks | **Pending final observed run** |
| Working-tree whitespace validation | **Pending final observed run** |
| Authenticated Liquipedia requests | **0 authorized for M6** |
| Model training or optimization | **0 authorized for M6** |
| Locked 2026-Q1 evaluation access | **0 authorized for M6** |

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
| Deployment deviations | **Pending deployment; none recorded yet** |
| Compatibility findings | **Pending deployment; none recorded yet** |
| Non-blocking warnings | **Pending final validation** |
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
