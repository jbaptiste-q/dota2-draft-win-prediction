"""Offline tests for the bounded Liquipedia sample-discovery plan."""

from datetime import date
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from scripts.discover_liquipedia_samples import (
    CATEGORY_EXCEPTION,
    CATEGORY_OLDER,
    CATEGORY_RECENT,
    CATEGORY_SIDE_CHANGE,
    CATEGORY_UPCOMING,
    DISCOVERY_REQUEST_COUNT,
    build_discovery_queries,
    build_discovery_url,
    plan_payload,
    select_candidates,
)
from scripts.validate_liquipedia_api import resolve_match_ids


def rich_game(*, team1side: str, team2side: str, winner: int) -> dict:
    """Return enough observed nested data to satisfy the draft gate."""
    return {
        "match2gameid": f"game-{winner}-{team1side}",
        "winner": winner,
        "length": 2400,
        "extradata": {
            "team1side": team1side,
            "team2side": team2side,
            **{
                f"team1hero{slot}": f"team1-hero-{slot}"
                for slot in range(1, 6)
            },
            **{
                f"team2hero{slot}": f"team2-hero-{slot}"
                for slot in range(1, 6)
            },
            **{
                f"team1ban{slot}": f"team1-ban-{slot}"
                for slot in range(1, 8)
            },
            **{
                f"team2ban{slot}": f"team2-ban-{slot}"
                for slot in range(1, 8)
            },
        },
    }


def test_plan_has_four_bounded_non_paginated_requests() -> None:
    plan = plan_payload(date(2026, 7, 27))

    assert plan["live_requests_in_this_phase"] == DISCOVERY_REQUEST_COUNT == 4
    assert plan["automatic_retries"] == 0
    assert plan["pagination_requests"] == 0
    assert plan["total_gate_requests_if_all_categories_resolve"] == 5
    assert len(plan["queries"]) == 4

    for item in plan["queries"]:
        parsed = urlparse(item["url_without_credentials"])
        query = parse_qs(parsed.query)
        assert parsed.path.endswith("/api/v3/match")
        assert query["wiki"] == ["dota2"]
        assert query["offset"] == ["0"]
        assert int(query["limit"][0]) <= 8
        assert "Authorization" not in item["url_without_credentials"]


def test_plan_uses_documented_top_level_filters() -> None:
    queries = {
        query.name: query for query in build_discovery_queries(date(2026, 7, 27))
    }

    recent = queries["recent_completed_candidates"].conditions
    assert "[[liquipediatier::1]]" in recent
    assert "[[liquipediatier::2]]" in recent
    assert "[[finished::1]]" in recent
    assert "[[bestof::>1]]" in recent
    assert "[[date::>2026-04-28 00:00:00]]" in recent

    older = queries["older_completed_candidates"].conditions
    assert "[[date::>2018-01-01 00:00:00]]" in older
    assert "[[date::<2019-01-01 00:00:00]]" in older

    upcoming = queries["upcoming_candidates"].conditions
    assert "[[finished::0]]" in upcoming
    assert "[[date::<2026-10-25 00:00:00]]" in upcoming

    exceptional = queries["exceptional_result_candidates"].conditions
    for condition in (
        "[[walkover::ff]]",
        "[[walkover::dq]]",
        "[[walkover::l]]",
        "[[resulttype::default]]",
        "[[resulttype::np]]",
        "[[status::notplayed]]",
    ):
        assert condition in exceptional


def test_selection_requires_observed_shapes_within_each_record() -> None:
    recent = {
        "match2id": "Recent_1",
        "date": "2026-07-20 10:00:00",
        "finished": True,
        "bestof": 3,
        "match2games": [
            rich_game(team1side="radiant", team2side="dire", winner=1),
            rich_game(team1side="dire", team2side="radiant", winner=2),
        ],
    }
    older = {
        "match2id": "Older_1",
        "date": "2018-08-10 10:00:00",
        "finished": 1,
        "bestof": 3,
    }
    upcoming = {
        "match2id": "Upcoming_1",
        "date": "2026-08-10 10:00:00",
        "finished": False,
    }
    exceptional = {
        "match2id": "Exceptional_1",
        "date": "2026-01-01 10:00:00",
        "finished": True,
        "resulttype": "np",
    }

    selections = select_candidates(
        {
            "recent_completed_candidates": [recent],
            "older_completed_candidates": [older],
            "upcoming_candidates": [upcoming],
            "exceptional_result_candidates": [exceptional],
        }
    )

    assert selections[CATEGORY_RECENT]["match2id"] == "Recent_1"
    assert selections[CATEGORY_SIDE_CHANGE]["match2id"] == "Recent_1"
    assert selections[CATEGORY_OLDER]["match2id"] == "Older_1"
    assert selections[CATEGORY_UPCOMING]["match2id"] == "Upcoming_1"
    assert selections[CATEGORY_EXCEPTION]["match2id"] == "Exceptional_1"


def test_validator_has_no_implicit_match_id_fallback() -> None:
    with pytest.raises(ValueError, match="No match IDs selected"):
        resolve_match_ids(SimpleNamespace(match_ids=None, selection_file=None))


def test_build_discovery_url_projects_only_approved_fields() -> None:
    query = build_discovery_queries(date(2026, 7, 27))[0]
    parsed = parse_qs(urlparse(build_discovery_url(query)).query)

    assert "match2games" in parsed["query"][0]
    assert "match2opponents" in parsed["query"][0]
    assert parsed["limit"] == ["8"]
