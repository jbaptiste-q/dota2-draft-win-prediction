"""Build normalized relational tables from normalized domain models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import pandas as pd

from .features import build_ml_feature_frame, exclusion_reason
from .models import DraftKind, NormalizedMatch


SCHEMA_VERSION = "liquipedia-dota-draft-v1"


@dataclass(frozen=True)
class DatasetTables:
    """All deterministic outputs of the dataset-construction stage."""

    matches: pd.DataFrame
    match_teams: pd.DataFrame
    match_players: pd.DataFrame
    games: pd.DataFrame
    heroes: pd.DataFrame
    draft_picks: pd.DataFrame
    draft_bans: pd.DataFrame
    ml_draft_games: pd.DataFrame

    def ordered(self) -> tuple[tuple[str, pd.DataFrame], ...]:
        """Return tables in stable export order."""
        return (
            ("matches", self.matches),
            ("match_teams", self.match_teams),
            ("match_players", self.match_players),
            ("games", self.games),
            ("heroes", self.heroes),
            ("draft_picks", self.draft_picks),
            ("draft_bans", self.draft_bans),
            ("ml_draft_games", self.ml_draft_games),
        )


def typed_frame(
    rows: list[dict[str, Any]],
    *,
    columns: tuple[str, ...],
    string_columns: tuple[str, ...] = (),
    integer_columns: tuple[str, ...] = (),
    boolean_columns: tuple[str, ...] = (),
    datetime_columns: tuple[str, ...] = (),
    sort_by: tuple[str, ...] = (),
) -> pd.DataFrame:
    """Create a stable nullable-schema frame from zero or more rows."""
    frame = pd.DataFrame(rows, columns=columns)
    for column in string_columns:
        frame[column] = frame[column].astype("string")
    for column in integer_columns:
        frame[column] = frame[column].astype("Int64")
    for column in boolean_columns:
        frame[column] = frame[column].astype("boolean")
    for column in datetime_columns:
        frame[column] = pd.to_datetime(
            frame[column],
            utc=True,
        ).astype("datetime64[us, UTC]")
    if sort_by and not frame.empty:
        frame = frame.sort_values(
            list(sort_by),
            kind="mergesort",
            na_position="last",
        ).reset_index(drop=True)
    return frame


def build_matches_table(matches: tuple[NormalizedMatch, ...]) -> pd.DataFrame:
    """Build one typed row per Liquipedia series."""
    rows = [
        {
            "schema_version": SCHEMA_VERSION,
            "source_document_sha256": match.source_document_sha256,
            "source_match_id": match.source_match_id,
            "start_time_utc": match.start_time_utc,
            "source_date_text": match.source_date_text,
            "patch": match.patch,
            "liquipedia_tier": match.liquipedia_tier,
            "tournament": match.tournament,
            "parent": match.parent,
            "series": match.series,
            "best_of": match.best_of,
            "finished": match.finished,
            "winner_team_slot": match.winner_team_slot,
            "status": match.status,
            "result_type": match.result_type,
            "walkover": match.walkover,
        }
        for match in matches
    ]
    columns = (
        "schema_version",
        "source_document_sha256",
        "source_match_id",
        "start_time_utc",
        "source_date_text",
        "patch",
        "liquipedia_tier",
        "tournament",
        "parent",
        "series",
        "best_of",
        "finished",
        "winner_team_slot",
        "status",
        "result_type",
        "walkover",
    )
    return typed_frame(
        rows,
        columns=columns,
        string_columns=tuple(
            column
            for column in columns
            if column
            not in {
                "start_time_utc",
                "best_of",
                "finished",
                "winner_team_slot",
            }
        ),
        integer_columns=("best_of", "winner_team_slot"),
        boolean_columns=("finished",),
        datetime_columns=("start_time_utc",),
        sort_by=("source_match_id",),
    )


def build_match_teams_table(matches: tuple[NormalizedMatch, ...]) -> pd.DataFrame:
    """Build one row per source match/team slot."""
    rows = [
        {
            "source_match_id": match.source_match_id,
            "team_slot": team.team_slot,
            "team_key": team.team_key,
            "source_name": team.source_name,
            "template": team.template,
            "score": team.score,
            "status": team.status,
        }
        for match in matches
        for team in match.teams
    ]
    columns = (
        "source_match_id",
        "team_slot",
        "team_key",
        "source_name",
        "template",
        "score",
        "status",
    )
    return typed_frame(
        rows,
        columns=columns,
        string_columns=(
            "source_match_id",
            "team_key",
            "source_name",
            "template",
            "status",
        ),
        integer_columns=("team_slot", "score"),
        sort_by=("source_match_id", "team_slot"),
    )


def build_match_players_table(matches: tuple[NormalizedMatch, ...]) -> pd.DataFrame:
    """Build series-level player identities without claiming game statistics."""
    rows = [
        {
            "source_match_id": match.source_match_id,
            "team_slot": team.team_slot,
            "player_slot": player.player_slot,
            "player_key": player.player_key,
            "source_name": player.source_name,
            "display_name": player.display_name,
            "flag": player.flag,
            "publisher_id": player.publisher_id,
        }
        for match in matches
        for team in match.teams
        for player in team.players
    ]
    columns = (
        "source_match_id",
        "team_slot",
        "player_slot",
        "player_key",
        "source_name",
        "display_name",
        "flag",
        "publisher_id",
    )
    return typed_frame(
        rows,
        columns=columns,
        string_columns=(
            "source_match_id",
            "player_key",
            "source_name",
            "display_name",
            "flag",
            "publisher_id",
        ),
        integer_columns=("team_slot", "player_slot"),
        sort_by=("source_match_id", "team_slot", "player_slot"),
    )


def build_games_table(matches: tuple[NormalizedMatch, ...]) -> pd.DataFrame:
    """Build all games and retain deterministic ML exclusion reasons."""
    rows = []
    for match in matches:
        for game in match.games:
            reason = exclusion_reason(match, game)
            rows.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "game_key": game.game_key,
                    "source_document_sha256": match.source_document_sha256,
                    "source_match_id": match.source_match_id,
                    "source_game_id": game.source_game_id,
                    "game_index": game.game_index,
                    "start_time_utc": game.start_time_utc,
                    "source_date_text": game.source_date_text,
                    "patch": game.patch,
                    "duration_seconds": game.duration_seconds,
                    "winner_team_slot": game.winner_team_slot,
                    "team1_side": game.team1_side.value if game.team1_side else None,
                    "team2_side": game.team2_side.value if game.team2_side else None,
                    "status": game.status,
                    "result_type": game.result_type,
                    "walkover": game.walkover,
                    "is_trainable_draft": reason is None,
                    "exclusion_reason": reason,
                }
            )
    columns = (
        "schema_version",
        "game_key",
        "source_document_sha256",
        "source_match_id",
        "source_game_id",
        "game_index",
        "start_time_utc",
        "source_date_text",
        "patch",
        "duration_seconds",
        "winner_team_slot",
        "team1_side",
        "team2_side",
        "status",
        "result_type",
        "walkover",
        "is_trainable_draft",
        "exclusion_reason",
    )
    return typed_frame(
        rows,
        columns=columns,
        string_columns=tuple(
            column
            for column in columns
            if column
            not in {
                "game_index",
                "start_time_utc",
                "duration_seconds",
                "winner_team_slot",
                "is_trainable_draft",
            }
        ),
        integer_columns=("game_index", "duration_seconds", "winner_team_slot"),
        boolean_columns=("is_trainable_draft",),
        datetime_columns=("start_time_utc",),
        sort_by=("source_match_id", "game_index"),
    )


def build_heroes_table(matches: tuple[NormalizedMatch, ...]) -> pd.DataFrame:
    """Build the observed hero vocabulary without inventing catalog IDs."""
    observed = {
        (value.hero.hero_key, value.hero.source_name)
        for match in matches
        for game in match.games
        for value in (*game.picks, *game.bans)
    }
    rows = [
        {"hero_key": hero_key, "source_name": source_name}
        for hero_key, source_name in sorted(observed)
    ]
    return typed_frame(
        rows,
        columns=("hero_key", "source_name"),
        string_columns=("hero_key", "source_name"),
        sort_by=("hero_key", "source_name"),
    )


def build_draft_table(
    matches: tuple[NormalizedMatch, ...],
    *,
    kind: DraftKind,
) -> pd.DataFrame:
    """Build normalized long-form pick or ban rows."""
    rows = [
        {
            "game_key": game.game_key,
            "source_match_id": match.source_match_id,
            "game_index": game.game_index,
            "team_slot": value.team_slot,
            "slot": value.slot,
            "hero_key": value.hero.hero_key,
            "hero_source_name": value.hero.source_name,
            "source_json_path": value.source_json_path,
        }
        for match in matches
        for game in match.games
        for value in (game.picks if kind == DraftKind.PICK else game.bans)
    ]
    columns = (
        "game_key",
        "source_match_id",
        "game_index",
        "team_slot",
        "slot",
        "hero_key",
        "hero_source_name",
        "source_json_path",
    )
    return typed_frame(
        rows,
        columns=columns,
        string_columns=(
            "game_key",
            "source_match_id",
            "hero_key",
            "hero_source_name",
            "source_json_path",
        ),
        integer_columns=("game_index", "team_slot", "slot"),
        sort_by=("source_match_id", "game_index", "team_slot", "slot"),
    )


def build_dataset_tables(
    matches: Iterable[NormalizedMatch],
) -> DatasetTables:
    """Build every relational and ML-ready table from normalized objects."""
    normalized = tuple(sorted(matches, key=lambda item: item.source_match_id))
    return DatasetTables(
        matches=build_matches_table(normalized),
        match_teams=build_match_teams_table(normalized),
        match_players=build_match_players_table(normalized),
        games=build_games_table(normalized),
        heroes=build_heroes_table(normalized),
        draft_picks=build_draft_table(normalized, kind=DraftKind.PICK),
        draft_bans=build_draft_table(normalized, kind=DraftKind.BAN),
        ml_draft_games=build_ml_feature_frame(normalized),
    )
