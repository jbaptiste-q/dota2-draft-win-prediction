"""Tests for the official Liquipedia API validation gate."""

import json
from urllib.parse import parse_qs, urlparse

import pytest

from scripts.validate_liquipedia_api import (
    analyze_payload,
    build_request_url,
    detect_capabilities,
    flatten_leaves,
    read_api_key,
    validate_match_ids,
)


def representative_record() -> dict:
    """Build a compact synthetic representation of a rich Dota match."""
    return {
        "match2id": "Example_0001",
        "match2games": [
            {
                "match2gameid": "Example_0001_m2g_001",
                "winner": 1,
                "length": 2400,
                "patch": "7.41c",
                "extradata": {
                    "team1side": "radiant",
                    "team2side": "dire",
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
                "participants": {
                    "1_1": {
                        "hero": "axe",
                        "kills": 8,
                        "deaths": 2,
                        "assists": 12,
                        "damage": 22000,
                        "last_hits": 300,
                        "denies": 12,
                        "gpm": 650,
                        "xpm": 720,
                        "net_worth": 28000,
                        "item1": "blink_dagger",
                    }
                },
            }
        ],
    }


def test_request_combines_all_matches_into_one_filtered_call() -> None:
    url = build_request_url(["Match_A", "Match-B"])
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    assert parsed.path.endswith("/api/v3/match")
    assert query["wiki"] == ["dota2"]
    assert query["limit"] == ["20"]
    assert "[[match2id::Match_A]]" in query["conditions"][0]
    assert "[[match2id::Match-B]]" in query["conditions"][0]
    assert query["query"][0].startswith("pageid,pagename")
    assert "Authorization" not in url


def test_match_ids_are_deduplicated_and_reject_query_syntax() -> None:
    assert validate_match_ids(["A_1", "A_1", "B-2"]) == ("A_1", "B-2")

    with pytest.raises(ValueError, match="Unsafe match2 ID"):
        validate_match_ids(["A]] OR [[winner::1"])


def test_nested_json_strings_are_inventoried() -> None:
    leaves = flatten_leaves(
        {"match2games": json.dumps([{"winner": 1, "patch": "7.41c"}])}
    )
    paths = {leaf.path for leaf in leaves}

    assert "match2games[].winner" in paths
    assert "match2games[].patch" in paths


def test_observed_schema_satisfies_per_team_draft_and_player_detectors() -> None:
    capabilities = {
        item.name: item for item in detect_capabilities([representative_record()])
    }

    for name in (
        "individual_game_id",
        "individual_game_winner",
        "individual_game_duration",
        "individual_game_patch",
        "radiant_dire",
        "ordered_picks",
        "ordered_bans",
        "complete_per_team_draft",
        "hero_identity",
        "player_hero_assignment",
        "player_kda",
        "hero_damage",
        "last_hits_denies",
        "gpm_xpm_networth",
        "items",
    ):
        assert capabilities[name].present, name

    assert not capabilities["first_pick"].present
    assert not capabilities["global_draft_order"].present
    assert not capabilities["spatial_telemetry"].present


def test_draft_gate_records_unavailable_fields_without_inference() -> None:
    report = analyze_payload(
        {"result": [representative_record()]},
        requested_match_ids=["Example_0001"],
    )

    draft_verdict = report["product_verdicts"]["ai_draft_assistant"]
    assert draft_verdict["status"] == "verified_with_documented_limitations"
    assert draft_verdict["missing_capabilities"] == []
    assert draft_verdict["documented_unavailable_capabilities"] == [
        "first_pick",
        "global_draft_order",
    ]

    capabilities = {item["name"]: item for item in report["capabilities"]}
    assert capabilities["ordered_picks"]["status"] == (
        "present_after_detector_correction"
    )
    assert capabilities["first_pick"]["status"] == (
        "unavailable_in_validated_api_payloads"
    )
    assert report["draft_schema_validation"]["complete_draft_game_count"] == 1
    assert (
        report["normalized_draft_schema"]["intentionally_unpopulated"][
            "first_pick_team_slot"
        ]
        == "Unavailable in validated payloads; never infer."
    )


def test_missing_fields_keep_product_gates_blocked() -> None:
    report = analyze_payload(
        {"result": [{"match2id": "Sparse_1", "winner": "1"}]},
        requested_match_ids=["Sparse_1"],
    )

    assert report["product_verdicts"]["ai_draft_assistant"]["status"] == "blocked"
    assert (
        report["product_verdicts"]["player_performance_analytics"]["status"]
        == "blocked"
    )
    assert report["missing_match_ids"] == []


def test_api_key_can_be_read_from_ignored_file(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("LIQUIPEDIA_API_KEY", raising=False)
    key_file = tmp_path / "key"
    key_file.write_text('LIQUIPEDIA_API_KEY="secret-value"\n', encoding="utf-8")

    assert read_api_key(api_key_file=key_file) == "secret-value"
