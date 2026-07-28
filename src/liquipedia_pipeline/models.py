"""Typed immutable models used between Liquipedia pipeline stages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path


class TeamSide(StrEnum):
    """Dota map side as represented by Liquipedia."""

    RADIANT = "radiant"
    DIRE = "dire"


class DraftKind(StrEnum):
    """Supported per-team draft value types."""

    PICK = "pick"
    BAN = "ban"


@dataclass(frozen=True, slots=True)
class RawApiDocument:
    """Immutable bytes loaded from one saved official API response."""

    path: Path
    sha256: str
    content: bytes


@dataclass(frozen=True, slots=True)
class ParsedPlayer:
    """Player identity attached to a series opponent."""

    player_slot: int
    source_name: str | None
    display_name: str | None
    flag: str | None
    publisher_id: str | None


@dataclass(frozen=True, slots=True)
class ParsedTeam:
    """One series opponent, retaining its source team slot."""

    team_slot: int
    source_name: str | None
    template: str | None
    score: int | None
    status: str | None
    players: tuple[ParsedPlayer, ...]


@dataclass(frozen=True, slots=True)
class ParsedDraftValue:
    """One hero value from an explicit per-team pick or ban slot."""

    kind: DraftKind
    team_slot: int
    slot: int
    hero_source_name: str
    source_json_path: str


@dataclass(frozen=True, slots=True)
class ParsedGame:
    """One game object as represented in match2games."""

    game_index: int
    source_game_id: str | None
    date_text: str | None
    timestamp: int | None
    patch: str | None
    duration_text: str | None
    winner_team_slot: int | None
    status: str | None
    result_type: str | None
    walkover: str | None
    team1_side: str | None
    team2_side: str | None
    picks: tuple[ParsedDraftValue, ...]
    bans: tuple[ParsedDraftValue, ...]


@dataclass(frozen=True, slots=True)
class ParsedMatch:
    """Typed series record parsed from one immutable source document."""

    source_document_sha256: str
    source_match_id: str
    date_text: str | None
    timestamp: int | None
    timezone_offset: str | None
    patch: str | None
    liquipedia_tier: str | None
    tournament: str | None
    parent: str | None
    series: str | None
    best_of: int | None
    finished: bool
    winner_team_slot: int | None
    status: str | None
    result_type: str | None
    walkover: str | None
    teams: tuple[ParsedTeam, ...]
    games: tuple[ParsedGame, ...]


@dataclass(frozen=True, slots=True)
class NormalizedHero:
    """Deterministic hero identity without unsupported alias inference."""

    hero_key: str
    source_name: str


@dataclass(frozen=True, slots=True)
class NormalizedDraftValue:
    """One normalized hero value with source provenance."""

    kind: DraftKind
    team_slot: int
    slot: int
    hero: NormalizedHero
    source_json_path: str


@dataclass(frozen=True, slots=True)
class NormalizedPlayer:
    """Normalized series-level player identity."""

    player_slot: int
    player_key: str | None
    source_name: str | None
    display_name: str | None
    flag: str | None
    publisher_id: str | None


@dataclass(frozen=True, slots=True)
class NormalizedTeam:
    """Normalized series-level team identity."""

    team_slot: int
    team_key: str | None
    source_name: str | None
    template: str | None
    score: int | None
    status: str | None
    players: tuple[NormalizedPlayer, ...]


@dataclass(frozen=True, slots=True)
class NormalizedGame:
    """Game-level record after deterministic type normalization."""

    game_key: str
    game_index: int
    source_game_id: str | None
    start_time_utc: datetime | None
    source_date_text: str | None
    patch: str | None
    duration_seconds: int | None
    winner_team_slot: int | None
    status: str | None
    result_type: str | None
    walkover: str | None
    team1_side: TeamSide | None
    team2_side: TeamSide | None
    picks: tuple[NormalizedDraftValue, ...]
    bans: tuple[NormalizedDraftValue, ...]


@dataclass(frozen=True, slots=True)
class NormalizedMatch:
    """Normalized series and all its nested games."""

    source_document_sha256: str
    source_match_id: str
    start_time_utc: datetime | None
    source_date_text: str | None
    patch: str | None
    liquipedia_tier: str | None
    tournament: str | None
    parent: str | None
    series: str | None
    best_of: int | None
    finished: bool
    winner_team_slot: int | None
    status: str | None
    result_type: str | None
    walkover: str | None
    teams: tuple[NormalizedTeam, ...]
    games: tuple[NormalizedGame, ...]
