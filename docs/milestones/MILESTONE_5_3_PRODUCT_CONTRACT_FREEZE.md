# Milestone 5.3: Product Contract Freeze

Status: **complete — Draft Assistant v1 scope frozen**

Milestone 5.3 closes product-definition drift before deployment. It changes
no model, inference behavior, API schema, dataset, or acquisition component.
It records one stable, evidence-aligned product that can be deployed and
explained without reopening modeling research.

## Frozen v1 objective

Draft Assistant v1 helps a user inspect a completed professional Dota 2 draft
through three connected capabilities:

1. model-estimated Radiant and Dire win probability for exactly five Radiant
   and five Dire hero picks;
2. exact additive hero log-odds contributions for that estimate; and
3. a user-directed comparison between the original completed draft and one
   completed draft with a single selected hero replaced.

The replacement comparison reports a change in model output. It does not
search candidates, rank heroes, choose a replacement, or claim causal match
effects.

## Supported contract

| Capability | Frozen behavior |
| --- | --- |
| Draft input | Five unique supported Radiant picks and five unique supported Dire picks |
| Representation | Unordered, side-relative, completed picks only |
| Probability | Complementary raw Radiant and Dire estimates from the pinned development snapshot |
| Explanation | Exact signed additive log-odds contribution for every active hero |
| What-if comparison | One outgoing and one incoming hero selected by the user; both completed drafts use the same analyzer |
| Model evidence | Failed 2025-Q4 readiness gate, pre-Q4 fit cutoff, and sealed 2026-Q1 status remain visible |
| Runtime data | Tracked JSON snapshot only; no credential, authenticated payload, ignored dataset, executable model binary, or live Liquipedia call |

The existing versioned contracts remain unchanged:

- `draft-assistant-analysis-v1`;
- `draft-assistant-model-card-v1`;
- `draft-assistant-replacement-comparison-v1`;
- `draft-assistant-heroes-v1`; and
- `draft-assistant-health-v1`.

## Explicitly unsupported

Draft Assistant v1 does not support:

- incomplete or partial drafts;
- automatic hero ranking;
- next-pick or strategic recommendations;
- ban effects;
- first-pick or globally interleaved draft order;
- synergy, counter, role, or lane effects;
- patch, team, player, or tournament conditioning;
- causal claims;
- readiness-approved or production-quality probability claims; or
- live or browser-side Liquipedia access.

These are contract boundaries rather than a list of promised follow-up
features.

## Evidence and deployment semantics

The frozen candidate is `b1_full_uniform_c0p01`. It failed to beat the
empirical-prior reference on the 2025-Q4 readiness period, was not promoted,
and did not open the sealed 2026-Q1 evaluation.

That result blocks readiness-approved model promotion. It does not block an
experimental portfolio deployment whose interface and API disclose the
failure, preserve the sealed-test status, and avoid production-quality claims.
M6 therefore deploys this exact contract as a demonstration of applied AI
engineering, not as a betting, coaching, or competitive prediction service.

## Modeling closure

M4A through M4B.5 are complete. M4B.5 was the final approved bounded modeling
hypothesis: the team-context candidate qualified on rolling development data
but failed its Q4 gate and was not promoted. No additional acquisition,
feature engineering, candidate family, calibration, optimization, or locked
test evaluation is required by the remaining roadmap.

A recommendation engine is optional and outside v1. It requires explicit
approval because context-sensitive partial-draft ranking would reopen modeling
research and needs its own evidence.

## Remaining required roadmap

1. **M6 — Production release and deployment:** package and deploy the frozen
   experimental contract with reproducible configuration and health
   verification.
2. **M7 — Portfolio release and final acceptance:** publish the recruiter-facing
   case study, walkthrough, reproducibility instructions, tagged release, and
   final acceptance evidence.

No other product capability is required for completion.

## Changes in this milestone

- aligned the repository overview and active roadmap with the implemented v1
  product;
- marked the M4 research phase closed after the M4B.5 negative result;
- distinguished readiness-approved promotion from transparent experimental
  portfolio deployment;
- removed language that implied recommendations were an expected v1 follow-up;
- replaced causal-sounding contribution ordering language with exact
  contribution terminology; and
- clarified the FastAPI description without changing its version or routes.

## Validation

| Check | Result |
| --- | --- |
| Focused Draft Assistant tests | **54 passed** |
| Python compilation | **Passed** for `src`, `scripts`, and `tests` |
| Dependency consistency | **Passed** — no broken requirements |
| JavaScript syntax | **Passed** |
| Repository hygiene | **Passed** |
| Complete active offline suite | **410 passed; 16 known Joblib/NumPy deprecation warnings** |
| Working-tree whitespace validation | **Passed** |
| Authenticated Liquipedia requests | **0** |
| Model training or optimization | **0** |
| Locked 2026-Q1 evaluation access | **0** |

The full results were observed on the M6 release candidate. The warnings arise
from Joblib assigning NumPy array shapes during existing bundle compatibility
tests; they do not change assertions or release behavior.

## Completion criteria

M5.3 is complete when the README, milestone records, API description, and
Draft Lab copy agree on the frozen supported and unsupported capabilities;
the remaining required roadmap is M6 then M7; and the offline validation
checks pass without changing model or acquisition behavior.
