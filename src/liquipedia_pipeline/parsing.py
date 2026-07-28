"""Parse immutable Liquipedia JSON bytes into typed source models."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from typing import Any, Iterable

from .models import (
    DraftKind,
    ParsedDraftValue,
    ParsedGame,
    ParsedMatch,
    ParsedPlayer,
    ParsedTeam,
    RawApiDocument,
)


TEAM_HERO_PATTERN = re.compile(r"^team([12])hero([1-5])$")
TEAM_BAN_PATTERN = re.compile(r"^team([12])ban([1-7])$")


class ParseError(ValueError):
    """Raised when a raw response violates the accepted source contract."""


def decode_nested_json(value: Any) -> Any:
    """Decode JSON-encoded containers while leaving ordinary strings intact."""
    if isinstance(value, str):
        stripped = value.strip()
        if (
            len(stripped) >= 2
            and stripped[0] in "[{"
            and stripped[-1] in "]}"
        ):
            try:
                return decode_nested_json(json.loads(stripped))
            except json.JSONDecodeError:
                return value
        return value
    if isinstance(value, list):
        return [decode_nested_json(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): decode_nested_json(item)
            for key, item in value.items()
        }
    return value


def optional_string(value: Any) -> str | None:
    """Normalize a scalar source value to a nullable stripped string."""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        raise ParseError(f"Expected scalar string value, got {type(value).__name__}.")
    result = str(value).strip()
    return result or None


def optional_int(value: Any) -> int | None:
    """Normalize an integer-like source value."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return int(value)
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise ParseError(f"Expected integer-like value, got {value!r}.") from error


def parse_bool(value: Any) -> bool:
    """Parse the documented Liquipedia boolean encodings strictly."""
    if value in (True, 1, "1", "true", "True"):
        return True
    if value in (False, 0, "0", "false", "False", None, ""):
        return False
    raise ParseError(f"Expected boolean-like value, got {value!r}.")


def winner_slot(value: Any) -> int | None:
    """Return only valid opponent slots; draws and missing values become null."""
    parsed = optional_int(value)
    return parsed if parsed in (1, 2) else None


def parse_players(value: Any) -> tuple[ParsedPlayer, ...]:
    """Parse the match-time player list while preserving source order."""
    decoded = decode_nested_json(value)
    if decoded in (None, ""):
        return ()
    if not isinstance(decoded, list):
        raise ParseError("match2players must be an array.")

    players: list[ParsedPlayer] = []
    for index, item in enumerate(decoded, start=1):
        if not isinstance(item, dict):
            raise ParseError("Every match2players entry must be an object.")
        extradata = decode_nested_json(item.get("extradata", {}))
        publisher_id = None
        if isinstance(extradata, dict):
            publisher_id = optional_string(
                extradata.get("publisherId", extradata.get("publisherid"))
            )
        players.append(
            ParsedPlayer(
                player_slot=optional_int(item.get("id")) or index,
                source_name=optional_string(item.get("name")),
                display_name=optional_string(item.get("displayname")),
                flag=optional_string(item.get("flag")),
                publisher_id=publisher_id,
            )
        )
    return tuple(players)


def parse_teams(value: Any) -> tuple[ParsedTeam, ...]:
    """Parse exactly the opponent objects returned for a series."""
    decoded = decode_nested_json(value)
    if decoded in (None, ""):
        return ()
    if not isinstance(decoded, list):
        raise ParseError("match2opponents must be an array.")

    teams: list[ParsedTeam] = []
    for index, item in enumerate(decoded, start=1):
        if not isinstance(item, dict):
            raise ParseError("Every match2opponents entry must be an object.")
        slot = optional_int(item.get("id")) or index
        if slot not in (1, 2):
            raise ParseError(f"Unsupported opponent slot: {slot}.")
        teams.append(
            ParsedTeam(
                team_slot=slot,
                source_name=optional_string(item.get("name")),
                template=optional_string(item.get("template")),
                score=optional_int(item.get("score")),
                status=optional_string(item.get("status")),
                players=parse_players(item.get("match2players", [])),
            )
        )
    team_slots = [team.team_slot for team in teams]
    if len(team_slots) != len(set(team_slots)):
        raise ParseError("match2opponents contains duplicate team slots.")
    return tuple(sorted(teams, key=lambda team: team.team_slot))


def parse_draft_values(
    extradata: dict[str, Any],
    *,
    game_index: int,
) -> tuple[tuple[ParsedDraftValue, ...], tuple[ParsedDraftValue, ...]]:
    """Parse only the validated explicit hero and ban slot conventions."""
    picks: list[ParsedDraftValue] = []
    bans: list[ParsedDraftValue] = []

    for raw_key, raw_value in extradata.items():
        key = re.sub(r"[^a-z0-9]+", "", str(raw_key).lower())
        pick_match = TEAM_HERO_PATTERN.fullmatch(key)
        ban_match = TEAM_BAN_PATTERN.fullmatch(key)
        if not pick_match and not ban_match:
            continue
        hero_name = optional_string(raw_value)
        if hero_name is None:
            continue
        if pick_match:
            team_slot, slot = map(int, pick_match.groups())
            picks.append(
                ParsedDraftValue(
                    kind=DraftKind.PICK,
                    team_slot=team_slot,
                    slot=slot,
                    hero_source_name=hero_name,
                    source_json_path=(
                        f"match2games[{game_index}].extradata.{raw_key}"
                    ),
                )
            )
        elif ban_match:
            team_slot, slot = map(int, ban_match.groups())
            bans.append(
                ParsedDraftValue(
                    kind=DraftKind.BAN,
                    team_slot=team_slot,
                    slot=slot,
                    hero_source_name=hero_name,
                    source_json_path=(
                        f"match2games[{game_index}].extradata.{raw_key}"
                    ),
                )
            )

    identities = [
        (item.kind, item.team_slot, item.slot)
        for item in (*picks, *bans)
    ]
    if len(identities) != len(set(identities)):
        raise ParseError(
            f"Game {game_index} contains duplicate normalized draft slots."
        )

    ordering = lambda item: (item.team_slot, item.slot)
    return tuple(sorted(picks, key=ordering)), tuple(sorted(bans, key=ordering))


def parse_games(value: Any) -> tuple[ParsedGame, ...]:
    """Parse every game object, including incomplete placeholders."""
    decoded = decode_nested_json(value)
    if decoded in (None, ""):
        return ()
    if isinstance(decoded, dict):
        decoded = [
            decoded[key]
            for key in sorted(decoded, key=lambda item: str(item))
        ]
    if not isinstance(decoded, list):
        raise ParseError("match2games must be an array or object.")

    games: list[ParsedGame] = []
    for game_index, item in enumerate(decoded):
        if not isinstance(item, dict):
            raise ParseError("Every match2games entry must be an object.")
        raw_extradata = decode_nested_json(item.get("extradata", {}))
        extradata = raw_extradata if isinstance(raw_extradata, dict) else {}
        picks, bans = parse_draft_values(extradata, game_index=game_index)
        games.append(
            ParsedGame(
                game_index=game_index,
                source_game_id=optional_string(item.get("match2gameid")),
                date_text=optional_string(item.get("date")),
                timestamp=optional_int(extradata.get("timestamp")),
                patch=optional_string(item.get("patch")),
                duration_text=optional_string(item.get("length")),
                winner_team_slot=winner_slot(item.get("winner")),
                status=optional_string(item.get("status")),
                result_type=optional_string(item.get("resulttype")),
                walkover=optional_string(item.get("walkover")),
                team1_side=optional_string(extradata.get("team1side")),
                team2_side=optional_string(extradata.get("team2side")),
                picks=picks,
                bans=bans,
            )
        )
    game_ids = [
        game.source_game_id
        for game in games
        if game.source_game_id is not None
    ]
    if len(game_ids) != len(set(game_ids)):
        raise ParseError("match2games contains duplicate non-null game IDs.")
    return tuple(games)


def parse_record(
    record: dict[str, Any],
    *,
    source_document_sha256: str,
) -> ParsedMatch:
    """Parse one result object into an immutable typed match."""
    source_match_id = optional_string(record.get("match2id"))
    if source_match_id is None:
        raise ParseError("Every match record must contain match2id.")

    raw_extradata = decode_nested_json(record.get("extradata", {}))
    extradata = raw_extradata if isinstance(raw_extradata, dict) else {}
    return ParsedMatch(
        source_document_sha256=source_document_sha256,
        source_match_id=source_match_id,
        date_text=optional_string(record.get("date")),
        timestamp=optional_int(extradata.get("timestamp")),
        timezone_offset=optional_string(extradata.get("timezoneoffset")),
        patch=optional_string(record.get("patch")),
        liquipedia_tier=optional_string(record.get("liquipediatier")),
        tournament=optional_string(record.get("tournament")),
        parent=optional_string(record.get("parent")),
        series=optional_string(record.get("series")),
        best_of=optional_int(record.get("bestof")),
        finished=parse_bool(record.get("finished")),
        winner_team_slot=winner_slot(record.get("winner")),
        status=optional_string(record.get("status")),
        result_type=optional_string(record.get("resulttype")),
        walkover=optional_string(record.get("walkover")),
        teams=parse_teams(record.get("match2opponents", [])),
        games=parse_games(record.get("match2games", [])),
    )


def parse_document(document: RawApiDocument) -> tuple[ParsedMatch, ...]:
    """Parse one official response and reject API errors or duplicate IDs."""
    try:
        payload = json.loads(document.content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ParseError(f"Invalid UTF-8 JSON in {document.path.name}.") from error
    if not isinstance(payload, dict):
        raise ParseError("Liquipedia response root must be an object.")

    errors = payload.get("error", [])
    if errors:
        raise ParseError(f"Liquipedia response contains API errors: {errors!r}")
    result = payload.get("result")
    if not isinstance(result, list):
        raise ParseError("Liquipedia response result must be an array.")

    matches: list[ParsedMatch] = []
    seen: set[str] = set()
    for item in result:
        if not isinstance(item, dict):
            raise ParseError("Every Liquipedia result entry must be an object.")
        match = parse_record(
            item,
            source_document_sha256=document.sha256,
        )
        if match.source_match_id in seen:
            raise ParseError(
                f"Duplicate match2id in one response: {match.source_match_id}."
            )
        seen.add(match.source_match_id)
        matches.append(match)
    return tuple(sorted(matches, key=lambda item: item.source_match_id))


def parse_documents(
    documents: Iterable[RawApiDocument],
) -> tuple[ParsedMatch, ...]:
    """Parse multiple documents and deduplicate identical match records."""
    by_match_id: dict[str, ParsedMatch] = {}
    for document in documents:
        for match in parse_document(document):
            existing = by_match_id.get(match.source_match_id)
            if existing is not None:
                existing_content = replace(
                    existing,
                    source_document_sha256="",
                )
                match_content = replace(
                    match,
                    source_document_sha256="",
                )
                if existing_content != match_content:
                    raise ParseError(
                        "Conflicting records for match2id "
                        f"{match.source_match_id} across raw documents."
                    )
                # Keep provenance deterministic when identical records occur in
                # multiple independently checksummed source documents.
                match = replace(
                    match,
                    source_document_sha256=min(
                        existing.source_document_sha256,
                        match.source_document_sha256,
                    ),
                )
            by_match_id[match.source_match_id] = match
    return tuple(by_match_id[key] for key in sorted(by_match_id))
