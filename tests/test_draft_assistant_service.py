"""Offline product-contract tests for completed-draft analysis."""

from __future__ import annotations

import json
import math

import pytest
from pydantic import ValidationError

from src.draft_ai_assistant.contracts import (
    AnalyzeDraftRequest,
    ReplacementComparisonRequest,
)
from src.draft_ai_assistant.service import (
    DraftAssistantService,
    UnsupportedHeroError,
)


RADIANT_PICKS = ("axe", "bane", "chen", "doom", "invoker")
DIRE_PICKS = ("lina", "lion", "puck", "tiny", "zeus")
EXPECTED_MODEL_CARD = {
    "schema_version": "draft-assistant-model-card-v1",
    "status": "development_candidate",
    "candidate_id": "b1_full_uniform_c0p01",
    "artifact_fingerprint": (
        "69730a62f42cda234337e8cbf152fb50fcb7ae02faf38367955c267fbe714442"
    ),
    "fit": {
        "rows": 20_087,
        "cutoff_utc_exclusive": "2025-10-01T00:00:00Z",
        "hero_count": 125,
        "representation": "unordered_side_relative_completed_picks",
    },
    "evaluation": {
        "period": "2025-Q4",
        "rows": 1_089,
        "reference": "train_tuning_empirical_prior",
        "candidate": {
            "log_loss": 0.6982455480507083,
            "brier_score": 0.2524500613459483,
        },
        "reference_metrics": {
            "log_loss": 0.6931146429704167,
            "brier_score": 0.24998372976923464,
        },
        "readiness_gate_passed": False,
        "locked_test_evaluated": False,
        "conclusion": "candidate_did_not_beat_reference",
    },
    "capabilities": {
        "completed_draft_probability": True,
        "local_hero_contributions": True,
        "bans": False,
        "partial_drafts": False,
        "recommendations": False,
        "first_pick": False,
        "global_draft_order": False,
    },
    "limitations": [
        "Experimental development candidate: the 2025-Q4 readiness gate "
        "failed.",
        "The sealed 2026-Q1 test set has not been evaluated.",
        "The model uses completed Radiant and Dire hero picks only.",
        "Bans, pick order, first pick, patch, teams, and player context are "
        "not model inputs.",
        "Hero contributions are associative logistic coefficients, not "
        "causal effects.",
        "Recommendations and partial-draft scoring are not available in "
        "this slice.",
    ],
}


@pytest.fixture(scope="module")
def service() -> DraftAssistantService:
    return DraftAssistantService.from_default_snapshot()


def _request(
    radiant: tuple[str, ...] = RADIANT_PICKS,
    dire: tuple[str, ...] = DIRE_PICKS,
) -> AnalyzeDraftRequest:
    return AnalyzeDraftRequest(
        radiant_picks=radiant,
        dire_picks=dire,
    )


def _replacement_request(
    *,
    radiant: tuple[str, ...] = RADIANT_PICKS,
    dire: tuple[str, ...] = DIRE_PICKS,
    side: str = "radiant",
    hero_to_replace: str = "axe",
    replacement_hero: str = "abaddon",
) -> ReplacementComparisonRequest:
    return ReplacementComparisonRequest(
        radiant_picks=radiant,
        dire_picks=dire,
        side=side,
        hero_to_replace=hero_to_replace,
        replacement_hero=replacement_hero,
    )


@pytest.mark.parametrize(
    ("field", "heroes"),
    [
        ("radiant_picks", RADIANT_PICKS[:-1]),
        ("radiant_picks", (*RADIANT_PICKS, "abaddon")),
        ("dire_picks", DIRE_PICKS[:-1]),
        ("dire_picks", (*DIRE_PICKS, "abaddon")),
    ],
)
def test_request_requires_exactly_five_picks_per_side(
    field: str,
    heroes: tuple[str, ...],
) -> None:
    payload = {
        "radiant_picks": RADIANT_PICKS,
        "dire_picks": DIRE_PICKS,
    }
    payload[field] = heroes

    with pytest.raises(ValidationError):
        AnalyzeDraftRequest.model_validate(payload)


@pytest.mark.parametrize(
    ("radiant", "dire", "message"),
    [
        (
            ("axe", "axe", "chen", "doom", "invoker"),
            DIRE_PICKS,
            "Radiant must contain five unique heroes",
        ),
        (
            RADIANT_PICKS,
            ("lina", "lina", "puck", "tiny", "zeus"),
            "Dire must contain five unique heroes",
        ),
        (
            RADIANT_PICKS,
            ("axe", "lion", "puck", "tiny", "zeus"),
            "cannot appear on both sides",
        ),
    ],
)
def test_request_rejects_duplicate_and_cross_side_heroes(
    radiant: tuple[str, ...],
    dire: tuple[str, ...],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        _request(radiant, dire)


def test_request_is_strict_about_extra_fields_and_exact_hero_keys() -> None:
    payload = {
        "radiant_picks": RADIANT_PICKS,
        "dire_picks": DIRE_PICKS,
        "first_pick": "radiant",
    }
    with pytest.raises(ValidationError, match="Extra inputs"):
        AnalyzeDraftRequest.model_validate(payload)

    payload.pop("first_pick")
    payload["radiant_picks"] = (
        " axe",
        *RADIANT_PICKS[1:],
    )
    with pytest.raises(ValidationError, match="exact catalog identifiers"):
        AnalyzeDraftRequest.model_validate(payload)

    payload["radiant_picks"] = (1, *RADIANT_PICKS[1:])
    with pytest.raises(ValidationError):
        AnalyzeDraftRequest.model_validate(payload)


def test_service_rejects_out_of_vocabulary_heroes_deterministically(
    service: DraftAssistantService,
) -> None:
    request = _request(
        ("brand-new-hero", *RADIANT_PICKS[1:]),
        DIRE_PICKS,
    )

    with pytest.raises(UnsupportedHeroError) as captured:
        service.analyze(request)

    assert captured.value.hero_keys == ("brand-new-hero",)
    assert str(captured.value) == (
        "Unsupported hero keys: brand-new-hero."
    )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {
                "side": "radiant",
                "hero_to_replace": "lina",
            },
            "outgoing hero must belong to the selected side",
        ),
        (
            {
                "hero_to_replace": "axe",
                "replacement_hero": "axe",
            },
            "incoming hero must differ from the outgoing hero",
        ),
        (
            {"replacement_hero": "lina"},
            "incoming hero must be absent from the completed draft",
        ),
    ],
)
def test_replacement_request_enforces_user_directed_completed_draft(
    overrides: dict[str, str],
    message: str,
) -> None:
    payload: dict[str, object] = {
        "radiant_picks": RADIANT_PICKS,
        "dire_picks": DIRE_PICKS,
        "side": "radiant",
        "hero_to_replace": "axe",
        "replacement_hero": "abaddon",
    }
    payload.update(overrides)

    with pytest.raises(ValidationError, match=message):
        ReplacementComparisonRequest.model_validate(payload)


def test_replacement_comparison_matches_two_direct_analyses_and_deltas(
    service: DraftAssistantService,
) -> None:
    request = _replacement_request()
    result = service.compare_replacement(request)
    baseline = service.analyze(_request())
    replacement = service.analyze(
        _request(
            ("abaddon", *RADIANT_PICKS[1:]),
            DIRE_PICKS,
        )
    )

    assert result.schema_version == (
        "draft-assistant-replacement-comparison-v1"
    )
    assert result.interpretation == (
        "associative_model_comparison_not_causal"
    )
    assert result.recommendation is False
    assert result.side == "radiant"
    assert result.outgoing.model_dump() == {
        "hero_key": "axe",
        "display_name": "Axe",
    }
    assert result.incoming.model_dump() == {
        "hero_key": "abaddon",
        "display_name": "Abaddon",
    }
    assert result.baseline.prediction_id == baseline.prediction_id
    assert result.baseline.draft == baseline.draft
    assert result.baseline.probability == baseline.probability
    assert result.replacement.prediction_id == replacement.prediction_id
    assert result.replacement.draft == replacement.draft
    assert result.replacement.probability == replacement.probability
    assert result.delta.radiant_win == pytest.approx(
        replacement.probability.radiant_win
        - baseline.probability.radiant_win,
        abs=1e-15,
    )
    assert result.delta.dire_win == pytest.approx(
        replacement.probability.dire_win
        - baseline.probability.dire_win,
        abs=1e-15,
    )
    assert result.delta.selected_side_win == pytest.approx(
        result.delta.radiant_win,
        abs=1e-15,
    )
    assert result.delta.radiant_win + result.delta.dire_win == pytest.approx(
        0.0,
        abs=1e-15,
    )
    assert result.model == baseline.model
    assert result.model.readiness_gate_passed is False
    assert result.model.locked_test_evaluated is False
    limitations = " ".join(result.limitations).casefold()
    assert "not a recommendation" in limitations
    assert "not a causal" in limitations
    assert "synergy" in limitations
    assert "2026-q1" in limitations


def test_replacement_comparison_is_deterministic_order_invariant_and_immutable(
    service: DraftAssistantService,
) -> None:
    request = _replacement_request()
    original_radiant = request.radiant_picks
    original_dire = request.dire_picks
    first = service.compare_replacement(request)
    reordered = service.compare_replacement(
        _replacement_request(
            radiant=tuple(reversed(RADIANT_PICKS)),
            dire=(
                DIRE_PICKS[2],
                DIRE_PICKS[4],
                DIRE_PICKS[0],
                DIRE_PICKS[3],
                DIRE_PICKS[1],
            ),
        )
    )
    repeated = service.compare_replacement(request)

    assert first == reordered
    assert first == repeated
    assert first.comparison_id == reordered.comparison_id
    assert request.radiant_picks == original_radiant
    assert request.dire_picks == original_dire
    assert "axe" in request.radiant_picks
    assert "abaddon" not in request.radiant_picks


def test_replacement_comparison_uses_dire_probability_for_dire_delta(
    service: DraftAssistantService,
) -> None:
    result = service.compare_replacement(
        _replacement_request(
            side="dire",
            hero_to_replace="lina",
            replacement_hero="abaddon",
        )
    )

    assert result.side == "dire"
    assert result.delta.selected_side_win == pytest.approx(
        result.delta.dire_win,
        abs=1e-15,
    )


def test_replacement_comparison_rejects_unsupported_incoming_hero(
    service: DraftAssistantService,
) -> None:
    request = _replacement_request(replacement_hero="brand-new-hero")

    with pytest.raises(UnsupportedHeroError) as captured:
        service.compare_replacement(request)

    assert captured.value.hero_keys == ("brand-new-hero",)


def test_analysis_is_deterministic_and_invariant_to_order_within_side(
    service: DraftAssistantService,
) -> None:
    first = service.analyze(_request())
    reordered = service.analyze(
        _request(
            tuple(reversed(RADIANT_PICKS)),
            (DIRE_PICKS[2], DIRE_PICKS[4], DIRE_PICKS[0], DIRE_PICKS[3], DIRE_PICKS[1]),
        )
    )
    repeated = service.analyze(_request())

    assert first == reordered
    assert first == repeated
    assert first.prediction_id == reordered.prediction_id
    assert first.draft.radiant_picks == tuple(sorted(RADIANT_PICKS))
    assert first.draft.dire_picks == tuple(sorted(DIRE_PICKS))
    assert first.draft.representation == (
        "unordered_side_relative_completed_picks"
    )


def test_probability_and_all_ten_contributions_are_faithful(
    service: DraftAssistantService,
) -> None:
    result = service.analyze(_request())
    probability = result.probability
    explanation = result.explanation
    contributions = explanation.contributions

    assert probability.method == "raw_logistic"
    assert 0.0 <= probability.radiant_win <= 1.0
    assert 0.0 <= probability.dire_win <= 1.0
    assert probability.radiant_win + probability.dire_win == pytest.approx(
        1.0,
        abs=1e-15,
    )
    assert len(contributions) == 10
    assert {item.hero_key for item in contributions} == {
        *RADIANT_PICKS,
        *DIRE_PICKS,
    }
    assert {
        item.hero_key
        for item in contributions
        if item.side == "radiant"
    } == set(RADIANT_PICKS)
    assert {
        item.hero_key
        for item in contributions
        if item.side == "dire"
    } == set(DIRE_PICKS)

    reconstructed_logit = math.fsum(
        (
            explanation.baseline_log_odds,
            *(item.coefficient_log_odds for item in contributions),
        )
    )
    expected_probability = 1.0 / (
        1.0 + math.exp(-reconstructed_logit)
    )
    baseline_probability = 1.0 / (
        1.0 + math.exp(-explanation.baseline_log_odds)
    )

    assert explanation.surface == "base_estimator_log_odds"
    assert explanation.interpretation == "associative_not_causal"
    assert explanation.draft_log_odds == pytest.approx(
        reconstructed_logit,
        abs=1e-15,
    )
    assert explanation.reconstruction_error <= 1e-15
    assert probability.radiant_win == pytest.approx(
        expected_probability,
        abs=1e-15,
    )
    assert explanation.baseline_radiant_win_probability == pytest.approx(
        baseline_probability,
        abs=1e-15,
    )
    for contribution in contributions:
        assert contribution.odds_multiplier == pytest.approx(
            math.exp(contribution.coefficient_log_odds),
            rel=1e-15,
        )
        expected_support = (
            "radiant"
            if contribution.coefficient_log_odds > 0
            else "dire"
            if contribution.coefficient_log_odds < 0
            else "neutral"
        )
        assert contribution.supports == expected_support


def test_response_discloses_failed_readiness_and_sealed_locked_test(
    service: DraftAssistantService,
) -> None:
    result = service.analyze(_request())

    assert result.schema_version == "draft-assistant-analysis-v1"
    assert result.model.status == "development_candidate"
    assert result.model.readiness_gate_passed is False
    assert result.model.locked_test_evaluated is False
    assert result.model.candidate_id == "b1_full_uniform_c0p01"
    assert result.model.probability_method == "raw_logistic"
    assert result.model.fit_cutoff_utc_exclusive == (
        "2025-10-01T00:00:00Z"
    )
    assert result.model.fit_rows == 20_087
    limitations = " ".join(result.limitations).casefold()
    assert "readiness gate failed" in limitations
    assert "2026-q1" in limitations
    assert "not causal" in limitations
    assert "recommendations" in limitations


def test_model_card_publishes_exact_offline_evidence_without_local_paths(
    service: DraftAssistantService,
) -> None:
    payload = service.model_card().model_dump(mode="json")

    assert payload == EXPECTED_MODEL_CARD
    evaluation = payload["evaluation"]
    assert evaluation["candidate"]["log_loss"] > (
        evaluation["reference_metrics"]["log_loss"]
    )
    assert evaluation["candidate"]["brier_score"] > (
        evaluation["reference_metrics"]["brier_score"]
    )
    assert evaluation["readiness_gate_passed"] is False
    assert evaluation["locked_test_evaluated"] is False

    serialized = json.dumps(payload, sort_keys=True).casefold()
    for prohibited_value in (
        ".secrets",
        "liquipedia_api_key",
        "authorization",
        "apikey",
        "models/",
        "data/",
        ".joblib",
        ".parquet",
        ".sqlite",
        "/users/",
        "file://",
    ):
        assert prohibited_value not in serialized


def test_health_and_hero_catalog_expose_only_public_snapshot_metadata(
    service: DraftAssistantService,
) -> None:
    health = service.health()
    heroes = service.heroes()

    assert health.status == "ok"
    assert health.model_loaded is True
    assert health.model_status == "development_candidate"
    assert health.candidate_id == "b1_full_uniform_c0p01"
    assert heroes.schema_version == "draft-assistant-heroes-v1"
    assert heroes.count == 125
    assert heroes.count == len(heroes.heroes)
    hero_keys = tuple(item.hero_key for item in heroes.heroes)
    assert hero_keys == tuple(sorted(hero_keys))
    assert len(hero_keys) == len(set(hero_keys))
