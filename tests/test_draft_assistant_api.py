"""In-process FastAPI tests for the offline Draft Assistant slice."""

from __future__ import annotations

from collections.abc import Iterator
import json

import pytest
from fastapi.testclient import TestClient

from src.draft_ai_assistant.api import create_app
from src.draft_ai_assistant.service import DraftAssistantService


RADIANT_PICKS = ["axe", "bane", "chen", "doom", "invoker"]
DIRE_PICKS = ["lina", "lion", "puck", "tiny", "zeus"]
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
def client() -> Iterator[TestClient]:
    app = create_app(DraftAssistantService.from_default_snapshot())
    with TestClient(app) as test_client:
        yield test_client


def test_openapi_description_freezes_the_v1_product_boundary(
    client: TestClient,
) -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    description = response.json()["info"]["description"]
    for disclosure in (
        "completed 5v5 pick-only probability analysis",
        "exact additive hero contributions",
        "user-directed one-for-one scenario comparison",
        "failed its readiness gate",
        "partial drafts",
        "hero rankings",
        "recommendations",
        "ban effects",
        "live Liquipedia calls",
    ):
        assert disclosure in description


def test_health_endpoint_discloses_development_model(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "schema_version": "draft-assistant-health-v1",
        "status": "ok",
        "model_loaded": True,
        "model_status": "development_candidate",
        "candidate_id": "b1_full_uniform_c0p01",
        "artifact_fingerprint": (
            "69730a62f42cda234337e8cbf152fb50fcb7ae02faf38367955c267fbe714442"
        ),
    }


def test_hero_catalog_endpoint_is_sorted_and_complete(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/heroes")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "draft-assistant-heroes-v1"
    assert payload["count"] == 125
    assert payload["count"] == len(payload["heroes"])
    keys = [item["hero_key"] for item in payload["heroes"]]
    assert keys == sorted(keys)
    assert len(keys) == len(set(keys))
    assert {"hero_key": "axe", "display_name": "Axe"} in payload["heroes"]


def test_model_card_endpoint_returns_only_the_published_evidence_contract(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/model-card")

    assert response.status_code == 200
    payload = response.json()
    assert payload == EXPECTED_MODEL_CARD
    assert set(payload) == {
        "schema_version",
        "status",
        "candidate_id",
        "artifact_fingerprint",
        "fit",
        "evaluation",
        "capabilities",
        "limitations",
    }
    assert set(payload["fit"]) == {
        "rows",
        "cutoff_utc_exclusive",
        "hero_count",
        "representation",
    }
    assert set(payload["evaluation"]) == {
        "period",
        "rows",
        "reference",
        "candidate",
        "reference_metrics",
        "readiness_gate_passed",
        "locked_test_evaluated",
        "conclusion",
    }
    assert set(payload["evaluation"]["candidate"]) == {
        "log_loss",
        "brier_score",
    }
    assert set(payload["evaluation"]["reference_metrics"]) == {
        "log_loss",
        "brier_score",
    }
    assert set(payload["capabilities"]) == {
        "completed_draft_probability",
        "local_hero_contributions",
        "bans",
        "partial_drafts",
        "recommendations",
        "first_pick",
        "global_draft_order",
    }

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


def test_root_and_static_assets_are_served_locally(
    client: TestClient,
) -> None:
    index = client.get("/")
    styles = client.get("/static/styles.css")
    script = client.get("/static/app.js")

    assert index.status_code == 200
    assert index.headers["content-type"].startswith("text/html")
    assert "Draft Lab" in index.text
    assert styles.status_code == 200
    assert styles.headers["content-type"].startswith("text/css")
    assert styles.text.strip()
    assert script.status_code == 200
    assert "javascript" in script.headers["content-type"]
    assert script.text.strip()


def test_analyze_endpoint_returns_probability_explanation_and_disclosure(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/analyze",
        json={
            "radiant_picks": RADIANT_PICKS,
            "dire_picks": DIRE_PICKS,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "draft-assistant-analysis-v1"
    assert payload["draft"] == {
        "representation": "unordered_side_relative_completed_picks",
        "radiant_picks": sorted(RADIANT_PICKS),
        "dire_picks": sorted(DIRE_PICKS),
    }
    assert payload["probability"]["method"] == "raw_logistic"
    assert (
        payload["probability"]["radiant_win"]
        + payload["probability"]["dire_win"]
    ) == pytest.approx(1.0, abs=1e-15)
    assert len(payload["explanation"]["contributions"]) == 10
    assert payload["explanation"]["interpretation"] == (
        "associative_not_causal"
    )
    assert payload["model"]["status"] == "development_candidate"
    assert payload["model"]["readiness_gate_passed"] is False
    assert payload["model"]["locked_test_evaluated"] is False


def test_replacement_comparison_endpoint_returns_a_non_recommendation(
    client: TestClient,
) -> None:
    request_payload = {
        "radiant_picks": RADIANT_PICKS,
        "dire_picks": DIRE_PICKS,
        "side": "radiant",
        "hero_to_replace": "axe",
        "replacement_hero": "abaddon",
    }
    response = client.post(
        "/api/v1/replacement-comparisons",
        json=request_payload,
    )
    baseline = client.post(
        "/api/v1/analyze",
        json={
            "radiant_picks": RADIANT_PICKS,
            "dire_picks": DIRE_PICKS,
        },
    )
    replacement = client.post(
        "/api/v1/analyze",
        json={
            "radiant_picks": [
                "abaddon",
                *RADIANT_PICKS[1:],
            ],
            "dire_picks": DIRE_PICKS,
        },
    )

    assert response.status_code == 200
    assert baseline.status_code == 200
    assert replacement.status_code == 200
    payload = response.json()
    baseline_payload = baseline.json()
    replacement_payload = replacement.json()
    assert set(payload) == {
        "schema_version",
        "comparison_id",
        "interpretation",
        "recommendation",
        "side",
        "outgoing",
        "incoming",
        "baseline",
        "replacement",
        "delta",
        "model",
        "limitations",
    }
    assert payload["schema_version"] == (
        "draft-assistant-replacement-comparison-v1"
    )
    assert payload["interpretation"] == (
        "associative_model_comparison_not_causal"
    )
    assert payload["recommendation"] is False
    assert payload["outgoing"] == {
        "hero_key": "axe",
        "display_name": "Axe",
    }
    assert payload["incoming"] == {
        "hero_key": "abaddon",
        "display_name": "Abaddon",
    }
    assert payload["baseline"] == {
        "prediction_id": baseline_payload["prediction_id"],
        "draft": baseline_payload["draft"],
        "probability": baseline_payload["probability"],
    }
    assert payload["replacement"] == {
        "prediction_id": replacement_payload["prediction_id"],
        "draft": replacement_payload["draft"],
        "probability": replacement_payload["probability"],
    }
    expected_radiant_delta = (
        replacement_payload["probability"]["radiant_win"]
        - baseline_payload["probability"]["radiant_win"]
    )
    expected_dire_delta = (
        replacement_payload["probability"]["dire_win"]
        - baseline_payload["probability"]["dire_win"]
    )
    assert payload["delta"]["radiant_win"] == pytest.approx(
        expected_radiant_delta,
        abs=1e-15,
    )
    assert payload["delta"]["dire_win"] == pytest.approx(
        expected_dire_delta,
        abs=1e-15,
    )
    assert payload["delta"]["selected_side_win"] == pytest.approx(
        expected_radiant_delta,
        abs=1e-15,
    )
    assert payload["model"]["readiness_gate_passed"] is False
    assert payload["model"]["locked_test_evaluated"] is False
    assert "not a recommendation" in (
        " ".join(payload["limitations"]).casefold()
    )


def test_replacement_comparison_rejects_unsupported_hero_stably(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/replacement-comparisons",
        json={
            "radiant_picks": RADIANT_PICKS,
            "dire_picks": DIRE_PICKS,
            "side": "radiant",
            "hero_to_replace": "axe",
            "replacement_hero": "brand-new-hero",
        },
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": {
            "code": "unsupported_hero",
            "message": "Unsupported hero keys: brand-new-hero.",
            "hero_keys": ["brand-new-hero"],
        }
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("hero_to_replace", "lina"),
        ("replacement_hero", "axe"),
        ("replacement_hero", "lina"),
    ],
)
def test_replacement_comparison_contract_errors_return_422(
    client: TestClient,
    field: str,
    value: str,
) -> None:
    payload = {
        "radiant_picks": RADIANT_PICKS,
        "dire_picks": DIRE_PICKS,
        "side": "radiant",
        "hero_to_replace": "axe",
        "replacement_hero": "abaddon",
    }
    payload[field] = value

    response = client.post(
        "/api/v1/replacement-comparisons",
        json=payload,
    )

    assert response.status_code == 422
    body = response.json()
    assert isinstance(body["detail"], list)
    assert body["detail"]


def test_openapi_contract_reports_m52_api_version(
    client: TestClient,
) -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["version"] == "0.3.0"


def test_unsupported_hero_returns_stable_product_error(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/analyze",
        json={
            "radiant_picks": [
                "brand-new-hero",
                *RADIANT_PICKS[1:],
            ],
            "dire_picks": DIRE_PICKS,
        },
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": {
            "code": "unsupported_hero",
            "message": "Unsupported hero keys: brand-new-hero.",
            "hero_keys": ["brand-new-hero"],
        }
    }


@pytest.mark.parametrize(
    "payload",
    [
        {
            "radiant_picks": RADIANT_PICKS[:-1],
            "dire_picks": DIRE_PICKS,
        },
        {
            "radiant_picks": RADIANT_PICKS,
            "dire_picks": [
                RADIANT_PICKS[0],
                *DIRE_PICKS[1:],
            ],
        },
        {
            "radiant_picks": RADIANT_PICKS,
            "dire_picks": DIRE_PICKS,
            "first_pick": "radiant",
        },
    ],
)
def test_request_contract_errors_return_422(
    client: TestClient,
    payload: dict[str, object],
) -> None:
    response = client.post("/api/v1/analyze", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert isinstance(body["detail"], list)
    assert body["detail"]
