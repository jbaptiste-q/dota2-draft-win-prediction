"""Framework-independent completed-draft analysis and faithful explanation."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from .contracts import (
    ANALYSIS_SCHEMA_VERSION,
    HEALTH_SCHEMA_VERSION,
    HEROES_SCHEMA_VERSION,
    MODEL_CARD_SCHEMA_VERSION,
    REPLACEMENT_COMPARISON_SCHEMA_VERSION,
    AnalyzeDraftRequest,
    AnalyzeDraftResponse,
    DraftEcho,
    HealthResponse,
    HeroCatalogResponse,
    HeroContribution,
    HeroRecord,
    LocalExplanation,
    ModelCardCapabilities,
    ModelCardEvaluation,
    ModelCardFit,
    ModelCardMetrics,
    ModelCardResponse,
    ModelDisclosure,
    ProbabilityResult,
    ReplacementComparisonRequest,
    ReplacementComparisonResponse,
    ReplacementProbabilityDelta,
    ReplacementScenario,
)
from .snapshot import (
    DEFAULT_SNAPSHOT_SHA256,
    InferenceSnapshot,
    default_snapshot_path,
    load_inference_snapshot,
)


class UnsupportedHeroError(ValueError):
    """Raised when a request cannot be faithfully represented by the model."""

    def __init__(self, hero_keys: tuple[str, ...]):
        self.hero_keys = hero_keys
        joined = ", ".join(hero_keys)
        super().__init__(f"Unsupported hero keys: {joined}.")


def _sigmoid(log_odds: float) -> float:
    if log_odds >= 0:
        inverse = math.exp(-log_odds)
        return 1.0 / (1.0 + inverse)
    exponential = math.exp(log_odds)
    return exponential / (1.0 + exponential)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


class DraftAssistantService:
    """Analyze legal completed drafts using one immutable public snapshot."""

    def __init__(self, snapshot: InferenceSnapshot):
        self.snapshot = snapshot
        self._display_names = {
            hero.hero_key: hero.display_name
            for hero in snapshot.heroes
        }

    @classmethod
    def from_snapshot(
        cls,
        path: Path,
        *,
        expected_sha256: str,
    ) -> "DraftAssistantService":
        return cls(
            load_inference_snapshot(
                path,
                expected_sha256=expected_sha256,
            )
        )

    @classmethod
    def from_default_snapshot(cls) -> "DraftAssistantService":
        return cls.from_snapshot(
            default_snapshot_path(),
            expected_sha256=DEFAULT_SNAPSHOT_SHA256,
        )

    def health(self) -> HealthResponse:
        return HealthResponse(
            schema_version=HEALTH_SCHEMA_VERSION,
            status="ok",
            model_loaded=True,
            model_status=self.snapshot.status,
            candidate_id=self.snapshot.source.candidate_id,
            artifact_fingerprint=self.snapshot.artifact_fingerprint,
        )

    def heroes(self) -> HeroCatalogResponse:
        records = tuple(
            HeroRecord(
                hero_key=hero.hero_key,
                display_name=hero.display_name,
            )
            for hero in self.snapshot.heroes
        )
        return HeroCatalogResponse(
            schema_version=HEROES_SCHEMA_VERSION,
            heroes=records,
            count=len(records),
        )

    def model_card(self) -> ModelCardResponse:
        evidence = self.snapshot.evidence
        source = self.snapshot.source
        return ModelCardResponse(
            schema_version=MODEL_CARD_SCHEMA_VERSION,
            status=self.snapshot.status,
            candidate_id=source.candidate_id,
            artifact_fingerprint=self.snapshot.artifact_fingerprint,
            fit=ModelCardFit(
                rows=source.fit_rows,
                cutoff_utc_exclusive=source.fit_cutoff_utc_exclusive,
                hero_count=len(self.snapshot.heroes),
                representation="unordered_side_relative_completed_picks",
            ),
            evaluation=ModelCardEvaluation(
                period="2025-Q4",
                rows=evidence.q4_rows,
                reference=evidence.readiness_reference,
                candidate=ModelCardMetrics(
                    log_loss=evidence.candidate_log_loss,
                    brier_score=evidence.candidate_brier_score,
                ),
                reference_metrics=ModelCardMetrics(
                    log_loss=evidence.reference_log_loss,
                    brier_score=evidence.reference_brier_score,
                ),
                readiness_gate_passed=evidence.readiness_gate_passed,
                locked_test_evaluated=evidence.locked_test_evaluated,
                conclusion="candidate_did_not_beat_reference",
            ),
            capabilities=ModelCardCapabilities(
                completed_draft_probability=True,
                local_hero_contributions=True,
                bans=False,
                partial_drafts=False,
                recommendations=False,
                first_pick=False,
                global_draft_order=False,
            ),
            limitations=self.snapshot.limitations,
        )

    def analyze(self, request: AnalyzeDraftRequest) -> AnalyzeDraftResponse:
        radiant = tuple(sorted(request.radiant_picks))
        dire = tuple(sorted(request.dire_picks))
        unsupported = tuple(
            sorted(
                set((*radiant, *dire)).difference(self._display_names)
            )
        )
        if unsupported:
            raise UnsupportedHeroError(unsupported)

        model = self.snapshot.model
        contributions = [
            self._contribution(
                hero_key=hero_key,
                side="radiant",
                coefficient=model.radiant_hero_log_odds[hero_key],
            )
            for hero_key in radiant
        ]
        contributions.extend(
            self._contribution(
                hero_key=hero_key,
                side="dire",
                coefficient=model.dire_hero_log_odds[hero_key],
            )
            for hero_key in dire
        )
        contributions.sort(
            key=lambda item: (
                -abs(item.coefficient_log_odds),
                item.side,
                item.hero_key,
            )
        )

        draft_log_odds = math.fsum(
            (
                model.intercept_log_odds,
                *(item.coefficient_log_odds for item in contributions),
            )
        )
        radiant_probability = _sigmoid(draft_log_odds)
        dire_probability = 1.0 - radiant_probability
        favored_side = (
            "radiant"
            if radiant_probability > 0.5
            else "dire"
            if radiant_probability < 0.5
            else "even"
        )
        reconstruction = (
            model.intercept_log_odds
            + sum(item.coefficient_log_odds for item in contributions)
        )
        draft_payload = {
            "radiant_picks": radiant,
            "dire_picks": dire,
            "artifact_fingerprint": self.snapshot.artifact_fingerprint,
        }
        prediction_id = hashlib.sha256(
            _canonical_json(draft_payload).encode("utf-8")
        ).hexdigest()

        return AnalyzeDraftResponse(
            schema_version=ANALYSIS_SCHEMA_VERSION,
            prediction_id=prediction_id,
            draft=DraftEcho(
                representation="unordered_side_relative_completed_picks",
                radiant_picks=radiant,
                dire_picks=dire,
            ),
            probability=ProbabilityResult(
                radiant_win=radiant_probability,
                dire_win=dire_probability,
                favored_side=favored_side,
                method=model.probability_method,
            ),
            explanation=LocalExplanation(
                surface="base_estimator_log_odds",
                interpretation="associative_not_causal",
                baseline_log_odds=model.intercept_log_odds,
                baseline_radiant_win_probability=_sigmoid(
                    model.intercept_log_odds
                ),
                draft_log_odds=draft_log_odds,
                reconstruction_error=abs(draft_log_odds - reconstruction),
                contributions=tuple(contributions),
            ),
            model=ModelDisclosure(
                status=self.snapshot.status,
                readiness_gate_passed=(
                    self.snapshot.evidence.readiness_gate_passed
                ),
                locked_test_evaluated=(
                    self.snapshot.evidence.locked_test_evaluated
                ),
                candidate_id=self.snapshot.source.candidate_id,
                candidate_fingerprint=(
                    self.snapshot.source.candidate_fingerprint
                ),
                artifact_fingerprint=self.snapshot.artifact_fingerprint,
                source_bundle_fingerprint=(
                    self.snapshot.source.source_bundle_fingerprint
                ),
                fit_cutoff_utc_exclusive=(
                    self.snapshot.source.fit_cutoff_utc_exclusive
                ),
                fit_rows=self.snapshot.source.fit_rows,
                probability_method=model.probability_method,
            ),
            limitations=self.snapshot.limitations,
        )

    def compare_replacement(
        self,
        request: ReplacementComparisonRequest,
    ) -> ReplacementComparisonResponse:
        """Compare two completed drafts after one user-directed replacement."""

        baseline_request = AnalyzeDraftRequest(
            radiant_picks=request.radiant_picks,
            dire_picks=request.dire_picks,
        )
        baseline = self.analyze(baseline_request)

        radiant = list(request.radiant_picks)
        dire = list(request.dire_picks)
        selected_side = radiant if request.side == "radiant" else dire
        outgoing_index = selected_side.index(request.hero_to_replace)
        selected_side[outgoing_index] = request.replacement_hero
        replacement_request = AnalyzeDraftRequest(
            radiant_picks=tuple(radiant),
            dire_picks=tuple(dire),
        )
        replacement = self.analyze(replacement_request)

        radiant_delta = (
            replacement.probability.radiant_win
            - baseline.probability.radiant_win
        )
        dire_delta = (
            replacement.probability.dire_win
            - baseline.probability.dire_win
        )
        selected_side_delta = (
            radiant_delta if request.side == "radiant" else dire_delta
        )
        comparison_payload = {
            "schema_version": REPLACEMENT_COMPARISON_SCHEMA_VERSION,
            "side": request.side,
            "hero_to_replace": request.hero_to_replace,
            "replacement_hero": request.replacement_hero,
            "baseline_prediction_id": baseline.prediction_id,
            "replacement_prediction_id": replacement.prediction_id,
            "artifact_fingerprint": self.snapshot.artifact_fingerprint,
        }
        comparison_id = hashlib.sha256(
            _canonical_json(comparison_payload).encode("utf-8")
        ).hexdigest()
        comparison_limitations = (
            "This is a user-directed one-for-one comparison of two "
            "completed drafts, not a recommendation.",
            "The change is an associative model comparison, not a causal "
            "estimate.",
            "The additive model does not evaluate hero synergy, counters, "
            "roles, lanes, bans, pick order, patch, teams, or players.",
            *self.snapshot.limitations,
        )

        return ReplacementComparisonResponse(
            schema_version=REPLACEMENT_COMPARISON_SCHEMA_VERSION,
            comparison_id=comparison_id,
            interpretation="associative_model_comparison_not_causal",
            recommendation=False,
            side=request.side,
            outgoing=HeroRecord(
                hero_key=request.hero_to_replace,
                display_name=self._display_names[
                    request.hero_to_replace
                ],
            ),
            incoming=HeroRecord(
                hero_key=request.replacement_hero,
                display_name=self._display_names[
                    request.replacement_hero
                ],
            ),
            baseline=ReplacementScenario(
                prediction_id=baseline.prediction_id,
                draft=baseline.draft,
                probability=baseline.probability,
            ),
            replacement=ReplacementScenario(
                prediction_id=replacement.prediction_id,
                draft=replacement.draft,
                probability=replacement.probability,
            ),
            delta=ReplacementProbabilityDelta(
                radiant_win=radiant_delta,
                dire_win=dire_delta,
                selected_side_win=selected_side_delta,
            ),
            model=baseline.model,
            limitations=comparison_limitations,
        )

    def _contribution(
        self,
        *,
        hero_key: str,
        side: str,
        coefficient: float,
    ) -> HeroContribution:
        supports = (
            "radiant"
            if coefficient > 0
            else "dire"
            if coefficient < 0
            else "neutral"
        )
        return HeroContribution(
            hero_key=hero_key,
            display_name=self._display_names[hero_key],
            side=side,
            coefficient_log_odds=coefficient,
            odds_multiplier=math.exp(coefficient),
            supports=supports,
        )


__all__ = [
    "DraftAssistantService",
    "UnsupportedHeroError",
]
