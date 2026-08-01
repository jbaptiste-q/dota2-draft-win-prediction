"""Offline tests for the immutable Liquipedia dataset pipeline."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import duckdb
import pytest

from src.liquipedia_pipeline.dataset import build_dataset_tables
from src.liquipedia_pipeline.normalization import (
    DURATION_COMPATIBILITY_INELIGIBLE_ANOMALY,
    DURATION_COMPATIBILITY_SOURCE_ANOMALY,
    DURATION_COMPATIBILITY_SOURCE_ANOMALY_21M38,
    DURATION_COMPATIBILITY_UNUSED_SLOT,
    NormalizationError,
    classify_duration_compatibility,
    normalize_matches,
    normalize_player,
    parse_duration_seconds,
)
from src.liquipedia_pipeline.models import ParsedPlayer
from src.liquipedia_pipeline.parsing import ParseError, parse_documents
from src.liquipedia_pipeline.pipeline import run_pipeline
from src.liquipedia_pipeline.raw import load_raw_documents


def draft_fields() -> dict[str, str]:
    """Return one complete draft using the validated Liquipedia key schema."""
    fields: dict[str, str] = {
        "team1side": "dire",
        "team2side": "radiant",
        "timestamp": "1710000000",
    }
    fields.update(
        {
            f"team1hero{slot}": f"Dire Pick {slot}"
            for slot in range(1, 6)
        }
    )
    fields.update(
        {
            f"team2hero{slot}": f"Radiant Pick {slot}"
            for slot in range(1, 6)
        }
    )
    fields.update(
        {
            f"team1ban{slot}": f"Dire Ban {slot}"
            for slot in range(1, 8)
        }
    )
    fields.update(
        {
            f"team2ban{slot}": f"Radiant Ban {slot}"
            for slot in range(1, 8)
        }
    )
    return fields


def team(slot: int, name: str) -> dict:
    """Create a source-shaped match opponent with nested player JSON."""
    players = [
        {
            "id": player_slot,
            "name": f"{name} Player {player_slot}",
            "displayname": f"{name} P{player_slot}",
            "flag": "FR" if slot == 1 else "SE",
            "extradata": json.dumps(
                {"publisherId": f"{slot}{player_slot:02d}"},
                sort_keys=True,
            ),
        }
        for player_slot in range(1, 6)
    ]
    return {
        "id": slot,
        "name": name,
        "template": name.replace(" ", ""),
        "score": "1",
        "match2players": json.dumps(players, sort_keys=True),
    }


def representative_payload() -> dict:
    """Build complete, legacy, upcoming, and forfeit source shapes."""
    complete = {
        "match2id": "Test_Full_0001",
        "date": "2024-03-09 16:00:00",
        "extradata": json.dumps(
            {"timestamp": 1710000000, "timezoneoffset": "+01:00"},
            sort_keys=True,
        ),
        "patch": "7.35c",
        "liquipediatier": "1",
        "tournament": "Test Invitational",
        "series": "Grand Final",
        "bestof": "3",
        "finished": "1",
        "winner": "2",
        "match2opponents": [team(1, "Team Alpha"), team(2, "Team Beta")],
        "match2games": [
            {
                "match2gameid": "Test_Full_0001_m2g_001",
                "date": "2024-03-09 16:00:00",
                "patch": "7.35c",
                "length": "41m05s",
                "winner": "2",
                "extradata": draft_fields(),
            }
        ],
    }
    legacy = {
        "match2id": "Test_Legacy_0001",
        "date": "2014-07-20 12:00:00",
        "extradata": {"timestamp": 1405857600, "timezoneoffset": "+00:00"},
        "patch": "6.81",
        "liquipediatier": "1",
        "tournament": "Legacy Cup",
        "bestof": 1,
        "finished": 1,
        "winner": 1,
        "match2opponents": [team(1, "Old One"), team(2, "Old Two")],
        "match2games": [
            {
                "match2gameid": "Test_Legacy_0001_m2g_001",
                "length": "38:12",
                "winner": 1,
                "extradata": {
                    "team1side": "radiant",
                    "team2side": "dire",
                    **{
                        f"team1hero{slot}": f"Dire Pick {slot}"
                        for slot in range(1, 6)
                    },
                    **{
                        f"team2hero{slot}": f"Radiant Pick {slot}"
                        for slot in range(1, 6)
                    },
                },
            }
        ],
    }
    upcoming = {
        "match2id": "Test_Upcoming_0001",
        "date": "2030-01-01 18:00:00",
        "extradata": {"timezoneoffset": "+02:00"},
        "tournament": "Future Cup",
        "bestof": 3,
        "finished": 0,
        "winner": 0,
        "match2opponents": [team(1, "Future One"), team(2, "Future Two")],
        "match2games": [
            {
                "match2gameid": "Test_Upcoming_0001_m2g_001",
                "winner": 0,
                "extradata": {},
            }
        ],
    }
    forfeit = {
        "match2id": "Test_Forfeit_0001",
        "date": "2023-01-01 10:00:00",
        "extradata": {"timestamp": 1672567200, "timezoneoffset": "+00:00"},
        "tournament": "Walkover Cup",
        "bestof": 3,
        "finished": 1,
        "winner": 1,
        "resulttype": "default",
        "walkover": "1",
        "match2opponents": [team(1, "Present"), team(2, "Absent")],
        "match2games": [],
    }
    return {"result": [upcoming, forfeit, complete, legacy], "error": []}


def reviewed_duration_compatibility_payload(
    *,
    source_match_id: str,
    best_of: int,
    match_winner: int,
    team_scores: tuple[int, int],
    game_winners: list[int],
    duration_value: str,
    hero: str,
) -> dict:
    """Reproduce one individually reviewed solo-series payload shape."""
    games = []
    for game_id, winner in enumerate(game_winners, start=1):
        is_reviewed_game = game_id == len(game_winners)
        if is_reviewed_game and duration_value.startswith("<s>"):
            game_winner: int | str = ""
            extradata = {
                "team1hero1": hero,
                "team2hero1": hero,
                "timestamp": 1707564000,
            }
        else:
            game_winner = winner
            extradata = {
                "team1hero1": hero,
                "team2hero1": hero,
                "team1side": "radiant" if winner == 1 else "dire",
                "team2side": "dire" if winner == 1 else "radiant",
                "timestamp": 1707564000,
            }
        games.append(
            {
                "match2gameid": game_id,
                "date": "2024-02-10 11:20:00",
                "length": (
                    duration_value
                    if is_reviewed_game
                    else f"{game_id + 5}m00s"
                ),
                "winner": game_winner,
                "extradata": extradata,
            }
        )

    opponents = [team(1, "Solo One"), team(2, "Solo Two")]
    opponents[0]["score"] = team_scores[0]
    opponents[1]["score"] = team_scores[1]
    return {
        "result": [
            {
                "match2id": source_match_id,
                "date": "2024-02-10 11:20:00",
                "extradata": {
                    "timestamp": 1707564000,
                    "timezoneoffset": "+04:00",
                },
                "liquipediatier": "1",
                "tournament": "BetBoom Dacha Dubai 2024: 1x1",
                "bestof": best_of,
                "finished": 1,
                "winner": match_winner,
                "match2opponents": opponents,
                "match2games": games,
            }
        ]
    }


def reviewed_21m38_payload() -> dict:
    """Reproduce the reviewed complete-game context without repairing duration."""
    team1 = team(1, "ToLight Team")
    team2 = team(2, "PAL Gaming")
    team1["score"] = 2
    team2["score"] = 0
    game2_draft = {
        "team1side": "radiant",
        "team2side": "dire",
        "timestamp": 1717815600,
        "team1hero1": "Vengeful Spirit",
        "team1hero2": "Beastmaster",
        "team1hero3": "Bane",
        "team1hero4": "Lifestealer",
        "team1hero5": "Tiny",
        "team2hero1": "Disruptor",
        "team2hero2": "Jakiro",
        "team2hero3": "Centaur Warrunner",
        "team2hero4": "Invoker",
        "team2hero5": "Juggernaut",
        "team1ban1": "Phoenix",
        "team1ban2": "Templar Assassin",
        "team1ban3": "Weaver",
        "team1ban4": "Winter Wyvern",
        "team1ban5": "Shadow Fiend",
        "team1ban6": "Gyrocopter",
        "team1ban7": "Troll Warlord",
        "team2ban1": "Storm Spirit",
        "team2ban2": "Chen",
        "team2ban3": "Night Stalker",
        "team2ban4": "Axe",
        "team2ban5": "Venomancer",
        "team2ban6": "Slardar",
        "team2ban7": "Outworld Destroyer",
    }
    return {
        "result": [
            {
                "match2id": "ubD8YXh91K_R02-M001",
                "date": "2024-06-08 03:00:00",
                "extradata": {
                    "timestamp": 1717815600,
                    "timezoneoffset": "+8:00",
                },
                "patch": "7.36b",
                "liquipediatier": "1",
                "tournament": (
                    "The International 2024: China Open Qualifier #2"
                ),
                "parent": "The_International/2024/China/Open_Qualifier/2",
                "series": "The International",
                "bestof": 2,
                "finished": 1,
                "winner": 1,
                "status": "",
                "resulttype": "",
                "walkover": "",
                "match2opponents": [team1, team2],
                "match2games": [
                    {
                        "match2gameid": 1,
                        "date": "2024-06-08 03:00:00",
                        "patch": "7.36b",
                        "length": "19m44s",
                        "winner": 1,
                        "extradata": {
                            "timestamp": 1717815600,
                            **draft_fields(),
                        },
                    },
                    {
                        "match2gameid": 2,
                        "date": "2024-06-08 03:00:00",
                        "patch": "7.36b",
                        "length": "21m38",
                        "winner": 1,
                        "status": "",
                        "resulttype": "",
                        "walkover": "",
                        "extradata": game2_draft,
                    },
                ],
            }
        ],
        "error": [],
    }


def write_payload(
    path: Path,
    payload: dict,
    *,
    indent: int | None = None,
) -> bytes:
    """Write a deterministic synthetic raw response and return its bytes."""
    content = (
        json.dumps(
            payload,
            indent=indent,
            sort_keys=True,
            separators=None if indent else (",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    path.write_bytes(content)
    return content


def parsed_and_normalized(tmp_path: Path):
    """Return parsed and normalized synthetic records."""
    raw_path = tmp_path / "response.json"
    write_payload(raw_path, representative_payload())
    parsed = parse_documents(load_raw_documents([raw_path]))
    return parsed, normalize_matches(parsed)


def test_parser_uses_exact_validated_draft_paths_without_inference(
    tmp_path: Path,
) -> None:
    parsed, _ = parsed_and_normalized(tmp_path)
    match = next(
        item for item in parsed if item.source_match_id == "Test_Full_0001"
    )
    game = match.games[0]

    assert len(game.picks) == 10
    assert len(game.bans) == 14
    assert game.team1_side == "dire"
    assert game.team2_side == "radiant"
    assert game.winner_team_slot == 2
    assert game.picks[0].source_json_path == (
        "match2games[0].extradata.team1hero1"
    )
    assert game.bans[-1].source_json_path == (
        "match2games[0].extradata.team2ban7"
    )
    assert not hasattr(game, "first_pick_team_slot")
    assert not hasattr(game, "global_draft_order")


def test_normalization_is_typed_and_preserves_source_meaning(
    tmp_path: Path,
) -> None:
    _, normalized = parsed_and_normalized(tmp_path)
    match = next(
        item for item in normalized if item.source_match_id == "Test_Full_0001"
    )
    game = match.games[0]

    assert match.teams[0].team_key == "team-alpha"
    assert match.teams[0].players[0].publisher_id == "101"
    assert match.teams[0].players[0].flag == "fr"
    assert game.duration_seconds == 2465
    assert game.start_time_utc.isoformat() == "2024-03-09T16:00:00+00:00"
    assert game.picks[0].hero.hero_key == "dire-pick-1"


def test_symbol_only_player_handle_uses_missing_key_when_publisher_id_exists(
) -> None:
    player = ParsedPlayer(
        player_slot=5,
        source_name="^^!",
        display_name="^^!",
        flag="Peru",
        publisher_id="238858075",
    )

    normalized = normalize_player(player)

    assert normalized.player_key is None
    assert normalized.source_name == "^^!"
    assert normalized.display_name == "^^!"
    assert normalized.publisher_id == "238858075"


def test_symbol_only_player_handle_without_publisher_id_remains_fail_closed(
) -> None:
    player = ParsedPlayer(
        player_slot=5,
        source_name="^^!",
        display_name="^^!",
        flag="Peru",
        publisher_id=None,
    )

    with pytest.raises(
        NormalizationError,
        match="no normalizable characters",
    ):
        normalize_player(player)


def test_dataset_keeps_all_source_shapes_but_only_exports_valid_ml_rows(
    tmp_path: Path,
) -> None:
    _, normalized = parsed_and_normalized(tmp_path)
    tables = build_dataset_tables(normalized)
    games = tables.games.set_index("source_match_id")

    assert len(tables.matches) == 4
    assert len(tables.games) == 3
    assert len(tables.draft_picks) == 20
    assert len(tables.draft_bans) == 14
    assert bool(games.loc["Test_Full_0001", "is_trainable_draft"])
    assert games.loc["Test_Legacy_0001", "exclusion_reason"] == (
        "incomplete_team1_bans"
    )
    assert games.loc["Test_Upcoming_0001", "exclusion_reason"] == (
        "match_not_finished"
    )
    assert "Test_Forfeit_0001" in set(tables.matches["source_match_id"])

    ml = tables.ml_draft_games
    assert len(ml) == 1
    assert bool(ml.loc[0, "radiant_win"])
    assert ml.loc[0, "team1_pick_slot_1_hero_key"] == "dire-pick-1"
    assert ml.loc[0, "radiant_pick_slot_1_hero_key"] == "radiant-pick-1"
    assert "duration_seconds" not in ml.columns
    assert "winner_team_slot" not in ml.columns


def test_empty_ml_dataset_retains_stable_dtypes(tmp_path: Path) -> None:
    payload = representative_payload()
    payload["result"] = [
        record
        for record in payload["result"]
        if record["match2id"] == "Test_Upcoming_0001"
    ]
    raw_path = tmp_path / "upcoming.json"
    write_payload(raw_path, payload)
    normalized = normalize_matches(
        parse_documents(load_raw_documents([raw_path]))
    )

    frame = build_dataset_tables(normalized).ml_draft_games

    assert frame.empty
    assert str(frame.dtypes["game_index"]) == "int64"
    assert str(frame.dtypes["radiant_team_slot"]) == "int8"
    assert str(frame.dtypes["radiant_win"]) == "boolean"
    assert str(frame.dtypes["match_start_utc"]) == "datetime64[us, UTC]"


def test_duplicate_source_records_are_deterministic_across_input_order(
    tmp_path: Path,
) -> None:
    payload = representative_payload()
    compact_path = tmp_path / "compact.json"
    pretty_path = tmp_path / "pretty.json"
    write_payload(compact_path, payload)
    write_payload(pretty_path, payload, indent=2)
    documents = load_raw_documents([compact_path, pretty_path])

    forward = parse_documents(documents)
    reverse = parse_documents(reversed(documents))

    assert forward == reverse
    assert all(
        match.source_document_sha256 == min(
            document.sha256 for document in documents
        )
        for match in forward
    )


def test_conflicting_duplicate_match_records_are_rejected(tmp_path: Path) -> None:
    original = representative_payload()
    changed = deepcopy(original)
    changed["result"][2]["tournament"] = "Different Tournament"
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"
    write_payload(first_path, original)
    write_payload(second_path, changed)

    with pytest.raises(ParseError, match="Conflicting records"):
        parse_documents(load_raw_documents([first_path, second_path]))


def test_duplicate_normalized_draft_slots_are_rejected(tmp_path: Path) -> None:
    payload = representative_payload()
    payload["result"][2]["match2games"][0]["extradata"]["Team1Hero1"] = (
        "Conflicting Hero"
    )
    raw_path = tmp_path / "duplicate-draft-slot.json"
    write_payload(raw_path, payload)

    with pytest.raises(ParseError, match="duplicate normalized draft slots"):
        parse_documents(load_raw_documents([raw_path]))


def test_duration_normalization_is_strict() -> None:
    assert parse_duration_seconds("1h02m03s") == 3723
    assert parse_duration_seconds("59:52") == 3592
    assert parse_duration_seconds("90m00s") == 5400
    assert parse_duration_seconds("90:00") == 5400
    assert parse_duration_seconds("Default") is None
    assert parse_duration_seconds(" Default ") is None

    with pytest.raises(NormalizationError, match="Invalid duration"):
        parse_duration_seconds("1h60m00s")
    with pytest.raises(NormalizationError, match="Unsupported duration"):
        parse_duration_seconds("about forty minutes")
    with pytest.raises(NormalizationError, match="Unsupported duration"):
        parse_duration_seconds("default")
    with pytest.raises(NormalizationError, match="Unsupported duration"):
        parse_duration_seconds("N/A")
    with pytest.raises(NormalizationError, match="Unsupported duration"):
        parse_duration_seconds("<s>Game 3</s>")
    with pytest.raises(NormalizationError, match="Unsupported duration"):
        parse_duration_seconds("<s>Game 5</s>")
    with pytest.raises(NormalizationError, match="Unsupported duration"):
        parse_duration_seconds("7m04")
    with pytest.raises(NormalizationError, match="Unsupported duration"):
        parse_duration_seconds("21m38")


def test_reviewed_21m38_occurrence_becomes_missing_duration(
    tmp_path: Path,
) -> None:
    payload = reviewed_21m38_payload()
    raw_path = tmp_path / "reviewed-21m38.json"
    original = write_payload(raw_path, payload)
    parsed = parse_documents(load_raw_documents([raw_path]))
    parsed_game = parsed[0].games[1]

    assert parsed_game.duration_text == "21m38"
    assert classify_duration_compatibility(
        parsed_game,
        match=parsed[0],
    ) == DURATION_COMPATIBILITY_SOURCE_ANOMALY_21M38

    normalized = normalize_matches(parsed)
    tables = build_dataset_tables(normalized)

    assert raw_path.read_bytes() == original
    assert normalized[0].games[1].duration_seconds is None
    assert not bool(tables.games.iloc[1]["is_trainable_draft"])
    assert tables.games.iloc[1]["exclusion_reason"] == "missing_game_duration"


def test_reviewed_21m38_occurrence_fails_on_context_mismatch(
    tmp_path: Path,
) -> None:
    payload = reviewed_21m38_payload()
    payload["result"][0]["match2games"][1]["extradata"]["team2ban7"] = "Oracle"
    raw_path = tmp_path / "mismatched-21m38.json"
    write_payload(raw_path, payload)

    with pytest.raises(
        NormalizationError,
        match="context-mismatched duration compatibility",
    ):
        normalize_matches(parse_documents(load_raw_documents([raw_path])))


def test_arbitrary_21m38_remains_unsupported_for_eligible_game(
    tmp_path: Path,
) -> None:
    payload = reviewed_21m38_payload()
    payload["result"][0]["match2id"] = "Different_Match_0001"
    raw_path = tmp_path / "arbitrary-21m38.json"
    write_payload(raw_path, payload)

    with pytest.raises(
        NormalizationError,
        match="Unsupported duration format",
    ):
        normalize_matches(parse_documents(load_raw_documents([raw_path])))


@pytest.mark.parametrize(
    (
        "source_match_id",
        "best_of",
        "match_winner",
        "team_scores",
        "game_winners",
        "duration_value",
        "hero",
        "compatibility_code",
        "exclusion_reason",
    ),
    [
        (
            "D8VM7QJos8_R04-M001",
            3,
            2,
            (0, 2),
            [2, 2, 0],
            "<s>Game 3</s>",
            "Queen of Pain",
            DURATION_COMPATIBILITY_UNUSED_SLOT,
            "missing_game_winner",
        ),
        (
            "D8VM7QJos8_R04-M003",
            3,
            1,
            (2, 0),
            [1, 1, 0],
            "<s>Game 3</s>",
            "Crystal Maiden",
            DURATION_COMPATIBILITY_UNUSED_SLOT,
            "missing_game_winner",
        ),
        (
            "D8VM7QJos8_R05-M002",
            3,
            1,
            (2, 1),
            [1, 2, 1],
            "7m04",
            "Puck",
            DURATION_COMPATIBILITY_SOURCE_ANOMALY,
            "incomplete_team1_picks",
        ),
        (
            "D8VM7QJos8_R06-M001",
            5,
            1,
            (3, 1),
            [1, 2, 1, 1, 0],
            "<s>Game 5</s>",
            "Crystal Maiden",
            DURATION_COMPATIBILITY_UNUSED_SLOT,
            "missing_game_winner",
        ),
    ],
)
def test_reviewed_duration_values_are_context_gated_and_preserved(
    tmp_path: Path,
    source_match_id: str,
    best_of: int,
    match_winner: int,
    team_scores: tuple[int, int],
    game_winners: list[int],
    duration_value: str,
    hero: str,
    compatibility_code: str,
    exclusion_reason: str,
) -> None:
    payload = reviewed_duration_compatibility_payload(
        source_match_id=source_match_id,
        best_of=best_of,
        match_winner=match_winner,
        team_scores=team_scores,
        game_winners=game_winners,
        duration_value=duration_value,
        hero=hero,
    )
    raw_path = tmp_path / "reviewed-duration.json"
    original = write_payload(raw_path, payload)
    parsed = parse_documents(load_raw_documents([raw_path]))
    parsed_game = parsed[0].games[-1]

    assert parsed_game.duration_text == duration_value
    assert classify_duration_compatibility(
        parsed_game,
        match=parsed[0],
    ) == compatibility_code

    normalized = normalize_matches(parsed)
    tables = build_dataset_tables(normalized)
    normalized_game = normalized[0].games[-1]

    assert raw_path.read_bytes() == original
    assert normalized_game.duration_seconds is None
    assert not bool(
        tables.games.loc[
            tables.games["game_index"].eq(len(game_winners) - 1),
            "is_trainable_draft",
        ].iloc[0]
    )
    assert (
        tables.games.loc[
            tables.games["game_index"].eq(len(game_winners) - 1),
            "exclusion_reason",
        ].iloc[0]
        == exclusion_reason
    )


@pytest.mark.parametrize(
    (
        "source_match_id",
        "best_of",
        "match_winner",
        "team_scores",
        "game_winners",
        "duration_value",
        "hero",
    ),
    [
        (
            "D8VM7QJos8_R04-M001",
            3,
            2,
            (0, 2),
            [2, 2, 0],
            "<s>Game 3</s>",
            "Queen of Pain",
        ),
        (
            "D8VM7QJos8_R04-M003",
            3,
            1,
            (2, 0),
            [1, 1, 0],
            "<s>Game 3</s>",
            "Crystal Maiden",
        ),
        (
            "D8VM7QJos8_R05-M002",
            3,
            1,
            (2, 1),
            [1, 2, 1],
            "7m04",
            "Puck",
        ),
        (
            "D8VM7QJos8_R06-M001",
            5,
            1,
            (3, 1),
            [1, 2, 1, 1, 0],
            "<s>Game 5</s>",
            "Crystal Maiden",
        ),
    ],
)
def test_reviewed_duration_literal_fails_for_otherwise_eligible_game(
    tmp_path: Path,
    source_match_id: str,
    best_of: int,
    match_winner: int,
    team_scores: tuple[int, int],
    game_winners: list[int],
    duration_value: str,
    hero: str,
) -> None:
    payload = reviewed_duration_compatibility_payload(
        source_match_id=source_match_id,
        best_of=best_of,
        match_winner=match_winner,
        team_scores=team_scores,
        game_winners=game_winners,
        duration_value=duration_value,
        hero=hero,
    )
    reviewed_game = payload["result"][0]["match2games"][-1]
    reviewed_game["winner"] = 1
    reviewed_game["extradata"] = draft_fields()
    raw_path = tmp_path / "ambiguous-duration.json"
    write_payload(raw_path, payload)

    with pytest.raises(
        NormalizationError,
        match="context-mismatched duration compatibility",
    ):
        normalize_matches(parse_documents(load_raw_documents([raw_path])))


def test_unreviewed_known_literal_uses_only_safe_ineligibility_fallback(
    tmp_path: Path,
) -> None:
    payload = reviewed_duration_compatibility_payload(
        source_match_id="Different_Match_0001",
        best_of=3,
        match_winner=1,
        team_scores=(2, 1),
        game_winners=[1, 2, 1],
        duration_value="7m04",
        hero="Puck",
    )
    raw_path = tmp_path / "unreviewed-duration.json"
    write_payload(raw_path, payload)
    parsed = parse_documents(load_raw_documents([raw_path]))

    assert classify_duration_compatibility(
        parsed[0].games[-1],
        match=parsed[0],
    ) == DURATION_COMPATIBILITY_INELIGIBLE_ANOMALY
    normalized = normalize_matches(parsed)
    tables = build_dataset_tables(normalized)

    assert normalized[0].games[-1].duration_seconds is None
    assert tables.games.iloc[-1]["exclusion_reason"] == (
        "incomplete_team1_picks"
    )


@pytest.mark.parametrize(
    ("ineligibility_case", "expected_reason"),
    [
        ("invalid_series", "invalid_series_result"),
        ("unfinished_series", "match_not_finished"),
        ("invalid_game", "invalid_game_result"),
        ("missing_winner", "missing_game_winner"),
        ("missing_side", "missing_or_invalid_sides"),
        ("incomplete_draft", "incomplete_team1_bans"),
    ],
)
def test_arbitrary_unsupported_duration_is_safe_for_preexisting_exclusion(
    tmp_path: Path,
    ineligibility_case: str,
    expected_reason: str,
) -> None:
    payload = representative_payload()
    match = deepcopy(payload["result"][2])
    game = match["match2games"][0]
    game["length"] = "future-unrecognized-duration"

    if ineligibility_case == "invalid_series":
        match["resulttype"] = "default"
    elif ineligibility_case == "unfinished_series":
        match["finished"] = 0
    elif ineligibility_case == "invalid_game":
        game["resulttype"] = "np"
    elif ineligibility_case == "missing_winner":
        game["winner"] = ""
    elif ineligibility_case == "missing_side":
        game["extradata"].pop("team1side")
    elif ineligibility_case == "incomplete_draft":
        game["extradata"].pop("team1ban7")
    else:
        raise AssertionError(f"Unhandled test case: {ineligibility_case}")

    payload["result"] = [match]
    raw_path = tmp_path / f"{ineligibility_case}.json"
    original = write_payload(raw_path, payload)
    parsed = parse_documents(load_raw_documents([raw_path]))
    parsed_game = parsed[0].games[0]

    assert parsed_game.duration_text == "future-unrecognized-duration"
    assert classify_duration_compatibility(
        parsed_game,
        match=parsed[0],
    ) == DURATION_COMPATIBILITY_INELIGIBLE_ANOMALY

    normalized = normalize_matches(parsed)
    tables = build_dataset_tables(normalized)

    assert raw_path.read_bytes() == original
    assert normalized[0].games[0].duration_seconds is None
    assert tables.games.loc[0, "exclusion_reason"] == expected_reason
    assert not bool(tables.games.loc[0, "is_trainable_draft"])


def test_arbitrary_unsupported_duration_still_fails_eligible_record(
    tmp_path: Path,
) -> None:
    payload = representative_payload()
    complete_match = deepcopy(payload["result"][2])
    complete_match["match2games"][0]["length"] = (
        "future-unrecognized-duration"
    )
    payload["result"] = [complete_match]
    raw_path = tmp_path / "eligible-unsupported-duration.json"
    write_payload(raw_path, payload)

    with pytest.raises(
        NormalizationError,
        match="Unsupported duration format",
    ):
        normalize_matches(parse_documents(load_raw_documents([raw_path])))


def test_unsupported_side_is_not_masked_by_duration_fallback(
    tmp_path: Path,
) -> None:
    payload = representative_payload()
    complete_match = deepcopy(payload["result"][2])
    game = complete_match["match2games"][0]
    game["length"] = "future-unrecognized-duration"
    game["extradata"]["team1side"] = "unknown-side"
    payload["result"] = [complete_match]
    raw_path = tmp_path / "ambiguous-side-and-duration.json"
    write_payload(raw_path, payload)

    with pytest.raises(
        NormalizationError,
        match="Unsupported duration format",
    ):
        normalize_matches(parse_documents(load_raw_documents([raw_path])))


def test_default_duration_placeholder_remains_ineligible(
    tmp_path: Path,
) -> None:
    payload = representative_payload()
    placeholder_match = deepcopy(payload["result"][2])
    placeholder_game = placeholder_match["match2games"][0]
    placeholder_game["length"] = "Default"
    placeholder_game["extradata"] = {}
    payload["result"] = [placeholder_match]
    raw_path = tmp_path / "default-duration-placeholder.json"
    write_payload(raw_path, payload)

    normalized = normalize_matches(
        parse_documents(load_raw_documents([raw_path]))
    )
    game = normalized[0].games[0]
    tables = build_dataset_tables(normalized)

    assert game.duration_seconds is None
    assert not bool(tables.games.loc[0, "is_trainable_draft"])
    assert tables.games.loc[0, "exclusion_reason"] == (
        "missing_or_invalid_sides"
    )
    assert tables.ml_draft_games.empty


@pytest.mark.parametrize("duration_value", ["Default", None])
def test_missing_duration_excludes_otherwise_complete_draft(
    tmp_path: Path,
    duration_value: str | None,
) -> None:
    payload = representative_payload()
    complete_match = deepcopy(payload["result"][2])
    complete_game = complete_match["match2games"][0]
    if duration_value is None:
        complete_game.pop("length")
    else:
        complete_game["length"] = duration_value
    payload["result"] = [complete_match]
    raw_path = tmp_path / "missing-duration-complete-draft.json"
    write_payload(raw_path, payload)

    normalized = normalize_matches(
        parse_documents(load_raw_documents([raw_path]))
    )
    tables = build_dataset_tables(normalized)

    assert normalized[0].games[0].duration_seconds is None
    assert not bool(tables.games.loc[0, "is_trainable_draft"])
    assert tables.games.loc[0, "exclusion_reason"] == "missing_game_duration"
    assert tables.ml_draft_games.empty


def test_export_is_immutable_content_addressed_and_readable(
    tmp_path: Path,
) -> None:
    raw_path = tmp_path / "response.json"
    original = write_payload(raw_path, representative_payload())
    output_root = tmp_path / "processed"

    first = run_pipeline([raw_path], output_root=output_root)
    second = run_pipeline([raw_path], output_root=output_root)

    assert raw_path.read_bytes() == original
    assert hashlib.sha256(raw_path.read_bytes()).hexdigest() == (
        first.documents[0].sha256
    )
    assert first.export.output_directory == second.export.output_directory
    assert len(first.export.parquet_paths) == 8
    assert not first.export.csv_paths

    manifest = json.loads(
        first.export.manifest_path.read_text(encoding="utf-8")
    )
    assert manifest["export_formats"] == ["parquet"]
    assert manifest["source_documents"][0]["sha256"] == (
        first.documents[0].sha256
    )
    ml_table = next(
        table
        for table in manifest["tables"]
        if table["name"] == "ml_draft_games"
    )
    assert ml_table["rows"] == 1

    with duckdb.connect() as connection:
        count = connection.execute(
            "SELECT count(*) FROM read_parquet(?)",
            [str(first.export.output_directory / "ml_draft_games.parquet")],
        ).fetchone()[0]
    assert count == 1

    csv_build = run_pipeline(
        [raw_path],
        output_root=output_root,
        include_csv=True,
    )
    assert csv_build.export.output_directory != first.export.output_directory
    assert len(csv_build.export.csv_paths) == 8
