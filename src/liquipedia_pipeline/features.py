"""Leakage-aware extraction of ML-ready draft-game rows."""

from __future__ import annotations

from typing import Any, Iterable

import pandas as pd

from .models import DraftKind, NormalizedDraftValue, NormalizedGame, NormalizedMatch


PICK_SLOTS = tuple(range(1, 6))
BAN_SLOTS = tuple(range(1, 8))
INVALID_RESULT_TYPES = {"default", "np"}
INVALID_STATUSES = {"notplayed"}


def values_by_slot(
    values: Iterable[NormalizedDraftValue],
    *,
    kind: DraftKind,
    team_slot: int,
) -> dict[int, NormalizedDraftValue]:
    """Index explicit per-team values and reject duplicate slots."""
    result: dict[int, NormalizedDraftValue] = {}
    for value in values:
        if value.kind != kind or value.team_slot != team_slot:
            continue
        if value.slot in result:
            raise ValueError(
                f"Duplicate {kind} slot for team {team_slot}: {value.slot}."
            )
        result[value.slot] = value
    return result


def exclusion_reason(match: NormalizedMatch, game: NormalizedGame) -> str | None:
    """Return the first deterministic reason a game cannot train a draft model."""
    match_result_type = (match.result_type or "").casefold()
    match_status = (match.status or "").casefold()
    game_result_type = (game.result_type or "").casefold()
    game_status = (game.status or "").casefold()

    if (
        match.walkover
        or match_result_type in INVALID_RESULT_TYPES
        or match_status in INVALID_STATUSES
    ):
        return "invalid_series_result"
    if not match.finished:
        return "match_not_finished"
    if (
        game.walkover
        or game_result_type in INVALID_RESULT_TYPES
        or game_status in INVALID_STATUSES
    ):
        return "invalid_game_result"
    if game.winner_team_slot not in (1, 2):
        return "missing_game_winner"
    if (
        game.team1_side is None
        or game.team2_side is None
        or game.team1_side == game.team2_side
    ):
        return "missing_or_invalid_sides"

    for team_slot in (1, 2):
        picks = values_by_slot(
            game.picks,
            kind=DraftKind.PICK,
            team_slot=team_slot,
        )
        if set(picks) != set(PICK_SLOTS):
            return f"incomplete_team{team_slot}_picks"
        bans = values_by_slot(
            game.bans,
            kind=DraftKind.BAN,
            team_slot=team_slot,
        )
        if set(bans) != set(BAN_SLOTS):
            return f"incomplete_team{team_slot}_bans"

    picked_heroes = [value.hero.hero_key for value in game.picks]
    if len(picked_heroes) != len(set(picked_heroes)):
        return "duplicate_picked_hero"
    if game.duration_seconds is None:
        return "missing_game_duration"
    return None


def team_by_slot(match: NormalizedMatch, team_slot: int):
    """Return a team by source slot without positional assumptions."""
    return next(
        (team for team in match.teams if team.team_slot == team_slot),
        None,
    )


def ml_row(match: NormalizedMatch, game: NormalizedGame) -> dict[str, Any]:
    """Build one pre-game feature row plus its supervised target."""
    reason = exclusion_reason(match, game)
    if reason is not None:
        raise ValueError(f"Game {game.game_key} is not trainable: {reason}.")

    team1 = team_by_slot(match, 1)
    team2 = team_by_slot(match, 2)
    team1_picks = values_by_slot(
        game.picks,
        kind=DraftKind.PICK,
        team_slot=1,
    )
    team2_picks = values_by_slot(
        game.picks,
        kind=DraftKind.PICK,
        team_slot=2,
    )
    team1_bans = values_by_slot(
        game.bans,
        kind=DraftKind.BAN,
        team_slot=1,
    )
    team2_bans = values_by_slot(
        game.bans,
        kind=DraftKind.BAN,
        team_slot=2,
    )

    radiant_team_slot = 1 if game.team1_side.value == "radiant" else 2
    dire_team_slot = 2 if radiant_team_slot == 1 else 1
    radiant_picks = team1_picks if radiant_team_slot == 1 else team2_picks
    dire_picks = team2_picks if dire_team_slot == 2 else team1_picks
    radiant_bans = team1_bans if radiant_team_slot == 1 else team2_bans
    dire_bans = team2_bans if dire_team_slot == 2 else team1_bans

    row: dict[str, Any] = {
        "game_key": game.game_key,
        "source_match_id": match.source_match_id,
        "source_game_id": game.source_game_id,
        "game_index": game.game_index,
        "match_start_utc": game.start_time_utc,
        "patch": game.patch,
        "liquipedia_tier": match.liquipedia_tier,
        "tournament": match.tournament,
        "series": match.series,
        "team1_key": team1.team_key if team1 else None,
        "team2_key": team2.team_key if team2 else None,
        "team1_side": game.team1_side.value,
        "team2_side": game.team2_side.value,
        "radiant_team_slot": radiant_team_slot,
        "dire_team_slot": dire_team_slot,
        "radiant_win": game.winner_team_slot == radiant_team_slot,
    }
    for slot in PICK_SLOTS:
        row[f"team1_pick_slot_{slot}_hero_key"] = team1_picks[slot].hero.hero_key
        row[f"team2_pick_slot_{slot}_hero_key"] = team2_picks[slot].hero.hero_key
        row[f"radiant_pick_slot_{slot}_hero_key"] = (
            radiant_picks[slot].hero.hero_key
        )
        row[f"dire_pick_slot_{slot}_hero_key"] = dire_picks[slot].hero.hero_key
    for slot in BAN_SLOTS:
        row[f"team1_ban_slot_{slot}_hero_key"] = team1_bans[slot].hero.hero_key
        row[f"team2_ban_slot_{slot}_hero_key"] = team2_bans[slot].hero.hero_key
        row[f"radiant_ban_slot_{slot}_hero_key"] = (
            radiant_bans[slot].hero.hero_key
        )
        row[f"dire_ban_slot_{slot}_hero_key"] = dire_bans[slot].hero.hero_key
    return row


def ml_feature_columns() -> tuple[str, ...]:
    """Return the stable column order for the wide ML dataset."""
    columns = [
        "game_key",
        "source_match_id",
        "source_game_id",
        "game_index",
        "match_start_utc",
        "patch",
        "liquipedia_tier",
        "tournament",
        "series",
        "team1_key",
        "team2_key",
        "team1_side",
        "team2_side",
        "radiant_team_slot",
        "dire_team_slot",
        "radiant_win",
    ]
    for slot in PICK_SLOTS:
        columns.extend(
            [
                f"team1_pick_slot_{slot}_hero_key",
                f"team2_pick_slot_{slot}_hero_key",
                f"radiant_pick_slot_{slot}_hero_key",
                f"dire_pick_slot_{slot}_hero_key",
            ]
        )
    for slot in BAN_SLOTS:
        columns.extend(
            [
                f"team1_ban_slot_{slot}_hero_key",
                f"team2_ban_slot_{slot}_hero_key",
                f"radiant_ban_slot_{slot}_hero_key",
                f"dire_ban_slot_{slot}_hero_key",
            ]
        )
    return tuple(columns)


def build_ml_feature_frame(matches: Iterable[NormalizedMatch]) -> pd.DataFrame:
    """Build a deterministic one-row-per-trainable-game dataset."""
    rows = [
        ml_row(match, game)
        for match in matches
        for game in match.games
        if exclusion_reason(match, game) is None
    ]
    frame = pd.DataFrame(rows, columns=ml_feature_columns())
    if not frame.empty:
        frame = frame.sort_values(
            ["match_start_utc", "source_match_id", "game_index"],
            kind="mergesort",
            na_position="last",
        ).reset_index(drop=True)
    string_columns = [
        column
        for column in frame.columns
        if column
        not in {
            "game_index",
            "match_start_utc",
            "radiant_team_slot",
            "dire_team_slot",
            "radiant_win",
        }
    ]
    frame[string_columns] = frame[string_columns].astype("string")
    frame["game_index"] = frame["game_index"].astype("int64")
    frame["radiant_team_slot"] = frame["radiant_team_slot"].astype("int8")
    frame["dire_team_slot"] = frame["dire_team_slot"].astype("int8")
    frame["radiant_win"] = frame["radiant_win"].astype("boolean")
    frame["match_start_utc"] = pd.to_datetime(
        frame["match_start_utc"],
        utc=True,
    ).astype("datetime64[us, UTC]")
    return frame
