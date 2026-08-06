# Documentation index

This is an engineering log, not documentation meant to be read start to
finish. Each entry below is a decision record frozen at the time it was
written, including the entries that record a negative or partial result —
none are edited after the fact. For the current state of the product, see
[`../README.md`](../README.md).

## Design documents (pre-milestone-numbering)

- [Milestone 1: Liquipedia Field Contract](MILESTONE_1_LIQUIPEDIA_FIELD_CONTRACT.md) — acquisition field contract
- [Milestone 1: Product Data Architecture](MILESTONE_1_PRODUCT_DATA_ARCHITECTURE.md) — data architecture design
- [Milestone 2: Data Pipeline](MILESTONE_2_DATA_PIPELINE.md) — parsing and normalization pipeline design
- [Milestone 3: Historical Backfill](MILESTONE_3_HISTORICAL_BACKFILL.md) — backfill acquisition design
- [Milestone 3.5: Historical Expansion Design](MILESTONE_3_5_HISTORICAL_EXPANSION_DESIGN.md) — expanded historical acquisition design
- [Milestone 4: Draft AI Modeling Plan](MILESTONE_4_DRAFT_AI_MODELING_PLAN.md) — modeling roadmap

## Milestones — acquisition and dataset construction

- [Gate 0: Repository Consolidation](milestones/GATE_0_REPOSITORY_CONSOLIDATION.md) — approved for commit with documented roadmap debt
- [3.5 Stage A: Offline Campaign Planning](milestones/MILESTONE_3_5_STAGE_A_OFFLINE_CAMPAIGN_PLANNING.md) — complete; Stage B awaiting separate approval
- [3.5 Stage B: Historical Canary](milestones/MILESTONE_3_5_STAGE_B_HISTORICAL_CANARY.md) — data canary complete; Stage C blocked pending review
- [3.5 Stage C: Duration Compatibility and Budget Proposal](milestones/MILESTONE_3_5_STAGE_C_DURATION_COMPATIBILITY_AND_BUDGET_PROPOSAL.md) — review complete; no change implemented
- [3.5 Stage C: Duration Eligibility Policy Update](milestones/MILESTONE_3_5_STAGE_C_DURATION_ELIGIBILITY_POLICY_UPDATE.md) — completed-partition rebuild and validation passed
- [3.5 Stage C: Historical Acquisition Campaign](milestones/MILESTONE_3_5_STAGE_C_HISTORICAL_ACQUISITION_CAMPAIGN.md) — halted at the 2024-Q1 recovery gates
- [3.5: Bounded Historical Dataset Publication](milestones/MILESTONE_3_5_BOUNDED_HISTORICAL_DATASET_PUBLICATION.md) — bounded finalization complete; full campaign window incomplete
- [3.6: Offline Dataset-Completion Readiness](milestones/MILESTONE_3_6_OFFLINE_READINESS.md) — complete; authenticated execution not started

## Milestones — modeling

- [4A: Modeling Infrastructure](milestones/MILESTONE_4A_MODELING_INFRASTRUCTURE.md) — complete
- [4B.1: Draft Baseline Backtesting](milestones/MILESTONE_4B_1_BASELINE_BACKTESTING.md) — honest negative baseline result
- [4B.2: B1 Regularization and Recency](milestones/MILESTONE_4B_2_RECENCY_REGULARIZATION.md) — development candidate frozen
- [4B.3: Frozen B1 Probability Calibration](milestones/MILESTONE_4B_3_CALIBRATION.md) — calibration policy frozen; readiness gate failed
- [4B.4: Draft Interaction Recovery Gate](milestones/MILESTONE_4B_4_DRAFT_INTERACTIONS.md) — no interaction candidate qualified
- [4B.5: Team Context Recovery Gate](milestones/MILESTONE_4B_5_TEAM_CONTEXT.md) — hypothesis confirmed; Q4 readiness failed
- [8: Hero Embeddings with Low-Rank Interactions](milestones/MILESTONE_8_HERO_EMBEDDINGS.md) — no candidate promoted
- [9: Patch Note Semantic Alignment](milestones/MILESTONE_9_PATCH_ALIGNMENT.md) — Phase 3 full labelling pass complete; Phase 4 pending

## Milestones — product

- [5: Draft Assistant Vertical Slice](milestones/MILESTONE_5_DRAFT_ASSISTANT_VERTICAL_SLICE.md) — runnable experimental product slice
- [5.1: Portfolio Demo Readiness](milestones/MILESTONE_5_1_PORTFOLIO_DEMO_READINESS.md) — complete
- [5.2: Completed-Draft Replacement Explorer](milestones/MILESTONE_5_2_COMPLETED_DRAFT_REPLACEMENT_EXPLORER.md) — complete
- [5.3: Product Contract Freeze](milestones/MILESTONE_5_3_PRODUCT_CONTRACT_FREEZE.md) — Draft Assistant v1 scope frozen
- [6: Production Release and Deployment](milestones/MILESTONE_6_PRODUCTION_DEPLOYMENT.md) — public deployment verified
- [7: Portfolio Release and Final Acceptance](milestones/MILESTONE_7_PORTFOLIO_RELEASE.md) — in progress; GitHub publication pending

## Other logs

- [`incidents/`](incidents/) — sealed-window boundary touches, recorded
  plainly rather than defended
- [`findings/`](findings/) — methodology findings that changed scope
  (e.g. dropping the magnitude label)
