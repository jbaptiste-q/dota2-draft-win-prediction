"""Strict public contracts for the first Draft Assistant product slice."""

from __future__ import annotations

from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    field_validator,
    model_validator,
)


ANALYSIS_SCHEMA_VERSION = "draft-assistant-analysis-v1"
HEALTH_SCHEMA_VERSION = "draft-assistant-health-v1"
HEROES_SCHEMA_VERSION = "draft-assistant-heroes-v1"
MODEL_CARD_SCHEMA_VERSION = "draft-assistant-model-card-v1"
REPLACEMENT_COMPARISON_SCHEMA_VERSION = (
    "draft-assistant-replacement-comparison-v1"
)


class ProductContract(BaseModel):
    """Forbid silent request/response drift at the product boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class AnalyzeDraftRequest(ProductContract):
    """One legal completed draft represented as unordered, side-relative picks."""

    radiant_picks: tuple[StrictStr, ...] = Field(min_length=5, max_length=5)
    dire_picks: tuple[StrictStr, ...] = Field(min_length=5, max_length=5)

    @field_validator("radiant_picks", "dire_picks")
    @classmethod
    def validate_hero_keys(
        cls,
        values: tuple[str, ...],
    ) -> tuple[str, ...]:
        for value in values:
            if not value or value != value.strip():
                raise ValueError(
                    "Hero keys must be non-empty exact catalog identifiers."
                )
        return values

    @model_validator(mode="after")
    def validate_unique_completed_draft(self) -> "AnalyzeDraftRequest":
        combined = (*self.radiant_picks, *self.dire_picks)
        if len(set(self.radiant_picks)) != 5:
            raise ValueError("Radiant must contain five unique heroes.")
        if len(set(self.dire_picks)) != 5:
            raise ValueError("Dire must contain five unique heroes.")
        if len(set(combined)) != 10:
            raise ValueError(
                "A hero cannot appear on both sides of the same draft."
            )
        return self


class ReplacementComparisonRequest(AnalyzeDraftRequest):
    """One user-directed replacement within a legal completed draft."""

    side: Literal["radiant", "dire"]
    hero_to_replace: StrictStr
    replacement_hero: StrictStr

    @field_validator("hero_to_replace", "replacement_hero")
    @classmethod
    def validate_replacement_hero_keys(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError(
                "Replacement hero keys must be non-empty exact catalog "
                "identifiers."
            )
        return value

    @model_validator(mode="after")
    def validate_user_directed_replacement(
        self,
    ) -> "ReplacementComparisonRequest":
        selected_side = (
            self.radiant_picks
            if self.side == "radiant"
            else self.dire_picks
        )
        if self.hero_to_replace not in selected_side:
            raise ValueError(
                "The outgoing hero must belong to the selected side."
            )
        if self.replacement_hero == self.hero_to_replace:
            raise ValueError(
                "The incoming hero must differ from the outgoing hero."
            )
        if self.replacement_hero in {
            *self.radiant_picks,
            *self.dire_picks,
        }:
            raise ValueError(
                "The incoming hero must be absent from the completed draft."
            )
        return self


class HeroRecord(ProductContract):
    hero_key: str
    display_name: str


class HeroCatalogResponse(ProductContract):
    schema_version: Literal["draft-assistant-heroes-v1"]
    heroes: tuple[HeroRecord, ...]
    count: int


class HealthResponse(ProductContract):
    schema_version: Literal["draft-assistant-health-v1"]
    status: Literal["ok"]
    model_loaded: Literal[True]
    model_status: Literal["development_candidate"]
    candidate_id: str
    artifact_fingerprint: str


class ModelCardFit(ProductContract):
    rows: int = Field(gt=0)
    cutoff_utc_exclusive: str
    hero_count: int = Field(gt=0)
    representation: Literal["unordered_side_relative_completed_picks"]


class ModelCardMetrics(ProductContract):
    log_loss: float = Field(ge=0.0)
    brier_score: float = Field(ge=0.0, le=1.0)


class ModelCardEvaluation(ProductContract):
    period: Literal["2025-Q4"]
    rows: int = Field(gt=0)
    reference: Literal["train_tuning_empirical_prior"]
    candidate: ModelCardMetrics
    reference_metrics: ModelCardMetrics
    readiness_gate_passed: Literal[False]
    locked_test_evaluated: Literal[False]
    conclusion: Literal["candidate_did_not_beat_reference"]


class ModelCardCapabilities(ProductContract):
    completed_draft_probability: Literal[True]
    local_hero_contributions: Literal[True]
    bans: Literal[False]
    partial_drafts: Literal[False]
    recommendations: Literal[False]
    first_pick: Literal[False]
    global_draft_order: Literal[False]


class ModelCardResponse(ProductContract):
    schema_version: Literal["draft-assistant-model-card-v1"]
    status: Literal["development_candidate"]
    candidate_id: str
    artifact_fingerprint: str
    fit: ModelCardFit
    evaluation: ModelCardEvaluation
    capabilities: ModelCardCapabilities
    limitations: tuple[str, ...]


class DraftEcho(ProductContract):
    representation: Literal["unordered_side_relative_completed_picks"]
    radiant_picks: tuple[str, ...]
    dire_picks: tuple[str, ...]


class ProbabilityResult(ProductContract):
    radiant_win: float = Field(ge=0.0, le=1.0)
    dire_win: float = Field(ge=0.0, le=1.0)
    favored_side: Literal["radiant", "dire", "even"]
    method: Literal["raw_logistic"]


class HeroContribution(ProductContract):
    hero_key: str
    display_name: str
    side: Literal["radiant", "dire"]
    coefficient_log_odds: float
    odds_multiplier: float = Field(gt=0.0)
    supports: Literal["radiant", "dire", "neutral"]


class LocalExplanation(ProductContract):
    surface: Literal["base_estimator_log_odds"]
    interpretation: Literal["associative_not_causal"]
    baseline_log_odds: float
    baseline_radiant_win_probability: float = Field(ge=0.0, le=1.0)
    draft_log_odds: float
    reconstruction_error: float = Field(ge=0.0)
    contributions: tuple[HeroContribution, ...]


class ModelDisclosure(ProductContract):
    status: Literal["development_candidate"]
    readiness_gate_passed: Literal[False]
    locked_test_evaluated: Literal[False]
    candidate_id: str
    candidate_fingerprint: str
    artifact_fingerprint: str
    source_bundle_fingerprint: str
    fit_cutoff_utc_exclusive: str
    fit_rows: int = Field(gt=0)
    probability_method: Literal["raw_logistic"]


class AnalyzeDraftResponse(ProductContract):
    schema_version: Literal["draft-assistant-analysis-v1"]
    prediction_id: str
    draft: DraftEcho
    probability: ProbabilityResult
    explanation: LocalExplanation
    model: ModelDisclosure
    limitations: tuple[str, ...]


class ReplacementScenario(ProductContract):
    prediction_id: str
    draft: DraftEcho
    probability: ProbabilityResult


class ReplacementProbabilityDelta(ProductContract):
    radiant_win: float = Field(ge=-1.0, le=1.0)
    dire_win: float = Field(ge=-1.0, le=1.0)
    selected_side_win: float = Field(ge=-1.0, le=1.0)


class ReplacementComparisonResponse(ProductContract):
    schema_version: Literal[
        "draft-assistant-replacement-comparison-v1"
    ]
    comparison_id: str
    interpretation: Literal[
        "associative_model_comparison_not_causal"
    ]
    recommendation: Literal[False]
    side: Literal["radiant", "dire"]
    outgoing: HeroRecord
    incoming: HeroRecord
    baseline: ReplacementScenario
    replacement: ReplacementScenario
    delta: ReplacementProbabilityDelta
    model: ModelDisclosure
    limitations: tuple[str, ...]


__all__ = [
    "ANALYSIS_SCHEMA_VERSION",
    "HEALTH_SCHEMA_VERSION",
    "HEROES_SCHEMA_VERSION",
    "MODEL_CARD_SCHEMA_VERSION",
    "REPLACEMENT_COMPARISON_SCHEMA_VERSION",
    "AnalyzeDraftRequest",
    "AnalyzeDraftResponse",
    "DraftEcho",
    "HealthResponse",
    "HeroCatalogResponse",
    "HeroContribution",
    "HeroRecord",
    "LocalExplanation",
    "ModelCardCapabilities",
    "ModelCardEvaluation",
    "ModelCardFit",
    "ModelCardMetrics",
    "ModelCardResponse",
    "ModelDisclosure",
    "ProbabilityResult",
    "ReplacementComparisonRequest",
    "ReplacementComparisonResponse",
    "ReplacementProbabilityDelta",
    "ReplacementScenario",
]
