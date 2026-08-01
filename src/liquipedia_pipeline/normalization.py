"""Deterministic normalization of parsed Liquipedia domain objects."""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime, timedelta, timezone
from typing import Iterable

from .models import (
    DraftKind,
    NormalizedDraftValue,
    NormalizedGame,
    NormalizedHero,
    NormalizedMatch,
    NormalizedPlayer,
    NormalizedTeam,
    ParsedDraftValue,
    ParsedGame,
    ParsedMatch,
    ParsedPlayer,
    ParsedTeam,
    TeamSide,
)


DURATION_PATTERN = re.compile(
    r"^(?:(?P<hours>\d+)h)?(?:(?P<minutes>\d+)m)?(?:(?P<seconds>\d+)s)?$"
)
OFFSET_PATTERN = re.compile(r"^(?P<sign>[+-])(?P<hours>\d{1,2}):(?P<minutes>\d{2})$")

DURATION_COMPATIBILITY_UNUSED_SLOT = "unplayed_game_slot_placeholder"
DURATION_COMPATIBILITY_SOURCE_ANOMALY = "source_duration_7m04_anomaly"
DURATION_COMPATIBILITY_SOURCE_ANOMALY_21M38 = (
    "source_duration_21m38_anomaly"
)
DURATION_COMPATIBILITY_INELIGIBLE_ANOMALY = (
    "unsupported_duration_on_preexisting_ineligible_game"
)

# These are occurrence-level compatibility decisions, not additions to the
# generic Liquipedia duration grammar. Each source occurrence was reviewed
# against its immutable API payload before being admitted here.
_APPROVED_UNUSED_GAME_SLOTS = {
    ("D8VM7QJos8_R04-M001", "3", "<s>Game 3</s>"): (3, 2, (0, 2)),
    ("D8VM7QJos8_R04-M003", "3", "<s>Game 3</s>"): (3, 1, (2, 0)),
    ("D8VM7QJos8_R06-M001", "5", "<s>Game 5</s>"): (5, 1, (3, 1)),
}
_APPROVED_DURATION_SOURCE_ANOMALIES = {
    ("D8VM7QJos8_R05-M002", "3", "7m04"): (3, 1, (2, 1)),
}
_APPROVED_DURATION_SOURCE_ANOMALY_21M38 = (
    "ubD8YXh91K_R02-M001",
    "2",
    "21m38",
)
_APPROVED_21M38_TEAM1_PICKS = (
    (1, "Vengeful Spirit"),
    (2, "Beastmaster"),
    (3, "Bane"),
    (4, "Lifestealer"),
    (5, "Tiny"),
)
_APPROVED_21M38_TEAM2_PICKS = (
    (1, "Disruptor"),
    (2, "Jakiro"),
    (3, "Centaur Warrunner"),
    (4, "Invoker"),
    (5, "Juggernaut"),
)
_APPROVED_21M38_TEAM1_BANS = (
    (1, "Phoenix"),
    (2, "Templar Assassin"),
    (3, "Weaver"),
    (4, "Winter Wyvern"),
    (5, "Shadow Fiend"),
    (6, "Gyrocopter"),
    (7, "Troll Warlord"),
)
_APPROVED_21M38_TEAM2_BANS = (
    (1, "Storm Spirit"),
    (2, "Chen"),
    (3, "Night Stalker"),
    (4, "Axe"),
    (5, "Venomancer"),
    (6, "Slardar"),
    (7, "Outworld Destroyer"),
)
# Fail-closed copy of the existing pre-duration eligibility contract. If the
# feature policy gains a new reason, unsupported durations continue to raise
# until that reason is deliberately reviewed for this fallback.
_PRE_DURATION_INVALID_RESULT_TYPES = frozenset({"default", "np"})
_PRE_DURATION_INVALID_STATUSES = frozenset({"notplayed"})
_PRE_DURATION_PICK_SLOTS = frozenset(range(1, 6))
_PRE_DURATION_BAN_SLOTS = frozenset(range(1, 8))


class NormalizationError(ValueError):
    """Raised when a source value cannot be normalized without guessing."""


def identity_key(value: str) -> str:
    """Create a stable Unicode-aware key without applying semantic aliases."""
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    normalized = normalized.replace("&", " and ").replace("_", " ")
    normalized = re.sub(r"[^\w]+", "-", normalized, flags=re.UNICODE)
    normalized = normalized.strip("-")
    if not normalized:
        raise NormalizationError(f"Identity has no normalizable characters: {value!r}")
    return normalized


def normalize_side(value: str | None) -> TeamSide | None:
    """Normalize only explicit radiant/dire values."""
    if value is None:
        return None
    normalized = value.strip().casefold()
    if normalized == TeamSide.RADIANT:
        return TeamSide.RADIANT
    if normalized == TeamSide.DIRE:
        return TeamSide.DIRE
    raise NormalizationError(f"Unsupported Dota side: {value!r}")


def _team_scores(match: ParsedMatch) -> tuple[int | None, int | None]:
    """Return source scores in opponent-slot order."""
    scores = {
        team.team_slot: team.score
        for team in match.teams
    }
    return scores.get(1), scores.get(2)


def _single_hero_pick_slots(game: ParsedGame) -> bool:
    """Identify the two one-on-one hero slots in the reviewed payloads."""
    slots = {
        (value.team_slot, value.slot)
        for value in game.picks
        if value.kind == DraftKind.PICK
    }
    return (
        slots == {(1, 1), (2, 1)}
        and len(game.picks) == 2
        and not game.bans
    )


def _unused_slot_context_is_exact(
    game: ParsedGame,
    *,
    match: ParsedMatch,
    best_of: int,
    match_winner: int,
    scores: tuple[int, int],
) -> bool:
    """Verify the reviewed unplayed-slot evidence without parsing markup."""
    completed_games = sum(
        nested.winner_team_slot in (1, 2)
        for nested in match.games
    )
    return (
        match.finished
        and match.best_of == best_of
        and match.winner_team_slot == match_winner
        and _team_scores(match) == scores
        and completed_games == sum(scores)
        and game.game_index == len(match.games) - 1
        and game.winner_team_slot is None
        and game.team1_side is None
        and game.team2_side is None
        and game.status is None
        and game.result_type is None
        and game.walkover is None
        and _single_hero_pick_slots(game)
    )


def _source_anomaly_context_is_exact(
    game: ParsedGame,
    *,
    match: ParsedMatch,
    best_of: int,
    match_winner: int,
    scores: tuple[int, int],
) -> bool:
    """Verify the individually reviewed played-game source anomaly."""
    completed_games = sum(
        nested.winner_team_slot in (1, 2)
        for nested in match.games
    )
    return (
        match.finished
        and match.best_of == best_of
        and match.winner_team_slot == match_winner
        and _team_scores(match) == scores
        and completed_games == sum(scores)
        and game.game_index == len(match.games) - 1
        and game.winner_team_slot == 1
        and game.team1_side == "radiant"
        and game.team2_side == "dire"
        and game.status is None
        and game.result_type is None
        and game.walkover is None
        and _single_hero_pick_slots(game)
        and all(
            value.hero_source_name == "Puck"
            for value in game.picks
        )
    )


def _draft_signature(
    values: Iterable[ParsedDraftValue],
    *,
    kind: DraftKind,
    team_slot: int,
) -> tuple[tuple[int, str], ...]:
    """Return an ordered slot/name signature for an exact reviewed context."""
    return tuple(
        sorted(
            (
                (value.slot, value.hero_source_name)
                for value in values
                if value.kind == kind and value.team_slot == team_slot
            ),
            key=lambda item: item[0],
        )
    )


def _source_anomaly_21m38_context_is_exact(
    game: ParsedGame,
    *,
    match: ParsedMatch,
) -> bool:
    """Verify the one reviewed otherwise-eligible ``21m38`` occurrence."""
    completed_games = sum(
        nested.winner_team_slot in (1, 2)
        for nested in match.games
    )
    team_signature = tuple(
        sorted(
            (
                (team.team_slot, team.source_name, team.score)
                for team in match.teams
            ),
            key=lambda item: item[0],
        )
    )
    return (
        match.finished
        and match.date_text == "2024-06-08 03:00:00"
        and match.timestamp == 1717815600
        and match.timezone_offset == "+8:00"
        and match.patch == "7.36b"
        and match.liquipedia_tier == "1"
        and match.tournament
        == "The International 2024: China Open Qualifier #2"
        and match.parent == "The_International/2024/China/Open_Qualifier/2"
        and match.series == "The International"
        and match.best_of == 2
        and match.winner_team_slot == 1
        and _team_scores(match) == (2, 0)
        and team_signature
        == (
            (1, "ToLight Team", 2),
            (2, "PAL Gaming", 0),
        )
        and len(match.games) == 2
        and completed_games == 2
        and tuple(
            (
                nested.source_game_id,
                nested.winner_team_slot,
                nested.duration_text,
            )
            for nested in match.games
        )
        == (
            ("1", 1, "19m44s"),
            ("2", 1, "21m38"),
        )
        and game.game_index == 1
        and game.source_game_id == "2"
        and game.date_text == "2024-06-08 03:00:00"
        and game.timestamp == 1717815600
        and game.patch == "7.36b"
        and game.winner_team_slot == 1
        and game.team1_side == "radiant"
        and game.team2_side == "dire"
        and game.status is None
        and game.result_type is None
        and game.walkover is None
        and _draft_signature(
            game.picks,
            kind=DraftKind.PICK,
            team_slot=1,
        )
        == _APPROVED_21M38_TEAM1_PICKS
        and _draft_signature(
            game.picks,
            kind=DraftKind.PICK,
            team_slot=2,
        )
        == _APPROVED_21M38_TEAM2_PICKS
        and _draft_signature(
            game.bans,
            kind=DraftKind.BAN,
            team_slot=1,
        )
        == _APPROVED_21M38_TEAM1_BANS
        and _draft_signature(
            game.bans,
            kind=DraftKind.BAN,
            team_slot=2,
        )
        == _APPROVED_21M38_TEAM2_BANS
    )


def pre_duration_ineligibility_reason(
    game: ParsedGame,
    *,
    match: ParsedMatch,
) -> str | None:
    """Return a safe existing exclusion reason before duration is considered.

    Unsupported side values and duplicate heroes deliberately do not qualify:
    both require their existing strict validation rather than being masked by
    an unrelated duration anomaly.
    """
    match_result_type = (match.result_type or "").casefold()
    match_status = (match.status or "").casefold()
    game_result_type = (game.result_type or "").casefold()
    game_status = (game.status or "").casefold()

    if (
        match.walkover
        or match_result_type in _PRE_DURATION_INVALID_RESULT_TYPES
        or match_status in _PRE_DURATION_INVALID_STATUSES
    ):
        return "invalid_series_result"
    if not match.finished:
        return "match_not_finished"
    if (
        game.walkover
        or game_result_type in _PRE_DURATION_INVALID_RESULT_TYPES
        or game_status in _PRE_DURATION_INVALID_STATUSES
    ):
        return "invalid_game_result"
    if game.winner_team_slot not in (1, 2):
        return "missing_game_winner"

    if game.team1_side is None or game.team2_side is None:
        return "missing_or_invalid_sides"
    team1_side = game.team1_side.casefold()
    team2_side = game.team2_side.casefold()
    valid_sides = {TeamSide.RADIANT.value, TeamSide.DIRE.value}
    if team1_side not in valid_sides or team2_side not in valid_sides:
        return None
    if team1_side == team2_side:
        return "missing_or_invalid_sides"

    for team_slot in (1, 2):
        pick_slots = {
            value.slot
            for value in game.picks
            if value.kind == DraftKind.PICK
            and value.team_slot == team_slot
        }
        if pick_slots != _PRE_DURATION_PICK_SLOTS:
            return f"incomplete_team{team_slot}_picks"
        ban_slots = {
            value.slot
            for value in game.bans
            if value.kind == DraftKind.BAN
            and value.team_slot == team_slot
        }
        if ban_slots != _PRE_DURATION_BAN_SLOTS:
            return f"incomplete_team{team_slot}_bans"
    return None


def classify_duration_compatibility(
    game: ParsedGame,
    *,
    match: ParsedMatch,
) -> str | None:
    """Classify reviewed values and safely excludable source anomalies.

    Returning a code authorizes normalization to a missing duration without
    adding a format to the duration grammar. A reviewed occurrence with
    mismatched context, or any unreviewed anomaly on an otherwise-eligible
    record, remains an error.
    """
    value = game.duration_text
    key = (match.source_match_id, game.source_game_id, value)
    unused_context = _APPROVED_UNUSED_GAME_SLOTS.get(key)
    if unused_context is not None:
        if _unused_slot_context_is_exact(
            game,
            match=match,
            best_of=unused_context[0],
            match_winner=unused_context[1],
            scores=unused_context[2],
        ):
            return DURATION_COMPATIBILITY_UNUSED_SLOT
        raise NormalizationError(
            "Unapproved or context-mismatched duration compatibility value "
            f"{value!r} for match {match.source_match_id!r}, "
            f"game {game.source_game_id!r}."
        )

    anomaly_context = _APPROVED_DURATION_SOURCE_ANOMALIES.get(key)
    if anomaly_context is not None:
        if _source_anomaly_context_is_exact(
            game,
            match=match,
            best_of=anomaly_context[0],
            match_winner=anomaly_context[1],
            scores=anomaly_context[2],
        ):
            return DURATION_COMPATIBILITY_SOURCE_ANOMALY
        raise NormalizationError(
            "Unapproved or context-mismatched duration compatibility value "
            f"{value!r} for match {match.source_match_id!r}, "
            f"game {game.source_game_id!r}."
        )

    if key == _APPROVED_DURATION_SOURCE_ANOMALY_21M38:
        if _source_anomaly_21m38_context_is_exact(game, match=match):
            return DURATION_COMPATIBILITY_SOURCE_ANOMALY_21M38
        raise NormalizationError(
            "Unapproved or context-mismatched duration compatibility value "
            f"{value!r} for match {match.source_match_id!r}, "
            f"game {game.source_game_id!r}."
        )

    try:
        parse_duration_seconds(value)
    except NormalizationError:
        if pre_duration_ineligibility_reason(game, match=match) is not None:
            return DURATION_COMPATIBILITY_INELIGIBLE_ANOMALY
        raise
    return None


def parse_duration_seconds(value: str | None) -> int | None:
    """Parse durations, preserving blank and observed exact Default values."""
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    if stripped == "Default":
        return None

    match = DURATION_PATTERN.fullmatch(stripped)
    if match and any(match.groupdict().values()):
        hours = int(match.group("hours") or 0)
        minutes = int(match.group("minutes") or 0)
        seconds = int(match.group("seconds") or 0)
        if (match.group("hours") is not None and minutes >= 60) or seconds >= 60:
            raise NormalizationError(f"Invalid duration: {value!r}")
        return hours * 3600 + minutes * 60 + seconds

    if re.fullmatch(r"\d{1,2}:\d{2}(?::\d{2})?", stripped):
        parts = [int(part) for part in stripped.split(":")]
        if len(parts) == 2:
            minutes, seconds = parts
            hours = 0
        else:
            hours, minutes, seconds = parts
        if (len(parts) == 3 and minutes >= 60) or seconds >= 60:
            raise NormalizationError(f"Invalid duration: {value!r}")
        return hours * 3600 + minutes * 60 + seconds
    raise NormalizationError(f"Unsupported duration format: {value!r}")


def normalize_game_duration(
    game: ParsedGame,
    *,
    match: ParsedMatch,
) -> int | None:
    """Normalize a duration after applying reviewed occurrence-level policy."""
    compatibility = classify_duration_compatibility(game, match=match)
    if compatibility is not None:
        return None
    return parse_duration_seconds(game.duration_text)


def parse_timezone_offset(value: str | None) -> timezone | None:
    """Parse source offsets such as +8:00 or +03:00."""
    if value is None:
        return None
    match = OFFSET_PATTERN.fullmatch(value.strip())
    if not match:
        raise NormalizationError(f"Unsupported timezone offset: {value!r}")
    hours = int(match.group("hours"))
    minutes = int(match.group("minutes"))
    if hours > 23 or minutes > 59:
        raise NormalizationError(f"Invalid timezone offset: {value!r}")
    delta = timedelta(hours=hours, minutes=minutes)
    if match.group("sign") == "-":
        delta = -delta
    return timezone(delta)


def normalize_datetime(
    *,
    timestamp: int | None,
    date_text: str | None,
    timezone_offset: str | None,
) -> datetime | None:
    """Prefer the source Unix timestamp; otherwise use an explicit offset."""
    if timestamp is not None:
        return datetime.fromtimestamp(timestamp, tz=UTC)
    if date_text is None:
        return None
    source_timezone = parse_timezone_offset(timezone_offset)
    if source_timezone is None:
        return None
    try:
        local_time = datetime.strptime(date_text, "%Y-%m-%d %H:%M:%S")
    except ValueError as error:
        raise NormalizationError(f"Unsupported date format: {date_text!r}") from error
    return local_time.replace(tzinfo=source_timezone).astimezone(UTC)


def normalize_hero(value: ParsedDraftValue) -> NormalizedDraftValue:
    """Normalize a hero name while preserving source text and path."""
    return NormalizedDraftValue(
        kind=value.kind,
        team_slot=value.team_slot,
        slot=value.slot,
        hero=NormalizedHero(
            hero_key=identity_key(value.hero_source_name),
            source_name=value.hero_source_name,
        ),
        source_json_path=value.source_json_path,
    )


def normalize_player(player: ParsedPlayer) -> NormalizedPlayer:
    """Normalize a player identity without merging aliases."""
    identity = player.source_name or player.display_name
    player_key = None
    if identity:
        try:
            player_key = identity_key(identity)
        except NormalizationError:
            # Dota handles may consist entirely of punctuation.  The source
            # text remains lossless and the official publisher ID remains the
            # stable identity; do not fabricate a text-derived alias.  Without
            # that source identity, retain the existing fail-closed behavior.
            if player.publisher_id is None:
                raise
    return NormalizedPlayer(
        player_slot=player.player_slot,
        player_key=player_key,
        source_name=player.source_name,
        display_name=player.display_name,
        flag=player.flag.casefold() if player.flag else None,
        publisher_id=player.publisher_id,
    )


def normalize_team(team: ParsedTeam) -> NormalizedTeam:
    """Normalize team and player identities."""
    identity = team.source_name or team.template
    return NormalizedTeam(
        team_slot=team.team_slot,
        team_key=identity_key(identity) if identity else None,
        source_name=team.source_name,
        template=team.template,
        score=team.score,
        status=team.status,
        players=tuple(normalize_player(player) for player in team.players),
    )


def normalize_game(
    game: ParsedGame,
    *,
    match: ParsedMatch,
) -> NormalizedGame:
    """Normalize one game without inferring unavailable draft fields."""
    source_component = game.source_game_id or str(game.game_index + 1)
    return NormalizedGame(
        game_key=f"lpdb:{match.source_match_id}:game:{source_component}",
        game_index=game.game_index,
        source_game_id=game.source_game_id,
        start_time_utc=normalize_datetime(
            timestamp=(
                game.timestamp
                if game.timestamp is not None
                else match.timestamp
            ),
            date_text=game.date_text or match.date_text,
            timezone_offset=match.timezone_offset,
        ),
        source_date_text=game.date_text or match.date_text,
        patch=game.patch or match.patch,
        duration_seconds=normalize_game_duration(game, match=match),
        winner_team_slot=game.winner_team_slot,
        status=game.status,
        result_type=game.result_type,
        walkover=game.walkover,
        team1_side=normalize_side(game.team1_side),
        team2_side=normalize_side(game.team2_side),
        picks=tuple(normalize_hero(value) for value in game.picks),
        bans=tuple(normalize_hero(value) for value in game.bans),
    )


def normalize_match(match: ParsedMatch) -> NormalizedMatch:
    """Normalize one parsed series and its nested objects."""
    return NormalizedMatch(
        source_document_sha256=match.source_document_sha256,
        source_match_id=match.source_match_id,
        start_time_utc=normalize_datetime(
            timestamp=match.timestamp,
            date_text=match.date_text,
            timezone_offset=match.timezone_offset,
        ),
        source_date_text=match.date_text,
        patch=match.patch,
        liquipedia_tier=match.liquipedia_tier,
        tournament=match.tournament,
        parent=match.parent,
        series=match.series,
        best_of=match.best_of,
        finished=match.finished,
        winner_team_slot=match.winner_team_slot,
        status=match.status,
        result_type=match.result_type,
        walkover=match.walkover,
        teams=tuple(normalize_team(team) for team in match.teams),
        games=tuple(normalize_game(game, match=match) for game in match.games),
    )


def validate_identity_collisions(matches: Iterable[NormalizedMatch]) -> None:
    """Reject silent merging of distinct hero names into the same key."""
    names_by_key: dict[str, set[str]] = {}
    for match in matches:
        for game in match.games:
            for value in (*game.picks, *game.bans):
                names_by_key.setdefault(value.hero.hero_key, set()).add(
                    value.hero.source_name
                )

    collisions = {
        key: sorted(names)
        for key, names in names_by_key.items()
        if len(names) > 1
    }
    if collisions:
        raise NormalizationError(
            "Hero normalization collisions require an explicit alias map: "
            f"{collisions!r}"
        )


def normalize_matches(
    matches: Iterable[ParsedMatch],
) -> tuple[NormalizedMatch, ...]:
    """Normalize and deterministically order all matches."""
    normalized = tuple(
        sorted(
            (normalize_match(match) for match in matches),
            key=lambda item: item.source_match_id,
        )
    )
    validate_identity_collisions(normalized)
    return normalized
