"""Validate Dota 2 match-field availability in the official LiquipediaDB API.

This is a deliberately narrow pre-implementation audit. It performs one
filtered GET request for an explicitly approved list of representative match2
IDs, preserves the response body locally, inventories nested JSON paths, and
reports whether the fields required by the proposed product are present in the
samples.

The script never writes or prints the API key.
"""

from __future__ import annotations

import argparse
import getpass
import gzip
import hashlib
import json
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
API_URL = "https://api.liquipedia.net/api/v3/match"
OUTPUT_ROOT = ROOT / "data" / "validation" / "liquipedia" / "runs"
USER_AGENT = "Dota2AIAnalyticsValidation/0.1"

MATCH_FIELD_PROJECTION = (
    "pageid",
    "pagename",
    "namespace",
    "objectname",
    "match2id",
    "status",
    "winner",
    "walkover",
    "resulttype",
    "finished",
    "patch",
    "date",
    "dateexact",
    "bestof",
    "tournament",
    "parent",
    "series",
    "liquipediatier",
    "extradata",
    "match2games",
    "match2opponents",
)

MATCH_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
TEAM_HERO_SLOT_PATTERN = re.compile(r"^team([12])hero([1-5])$")
TEAM_BAN_SLOT_PATTERN = re.compile(r"^team([12])ban([1-7])$")
GLOBAL_DRAFT_ORDER_KEYS = {
    "draftactions",
    "draftorder",
    "draftsequence",
    "globaldraftorder",
    "pickorder",
}


@dataclass(frozen=True)
class Leaf:
    """One normalized JSON leaf and its structural path."""

    path: str
    value: Any

    @property
    def key(self) -> str:
        """Return a comparison-friendly final path component."""
        component = self.path.rsplit(".", maxsplit=1)[-1]
        return re.sub(r"[^a-z0-9]+", "", component.lower())


@dataclass(frozen=True)
class Capability:
    """One product requirement and the paths that support it."""

    name: str
    label: str
    present: bool
    paths: tuple[str, ...]
    interpretation: str


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the narrow validation command-line interface."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--match-id",
        action="append",
        dest="match_ids",
        help=(
            "Exact LPDB match2 ID. Repeat for multiple IDs. "
            "Required unless --selection-file is supplied."
        ),
    )
    parser.add_argument(
        "--selection-file",
        type=Path,
        help=(
            "Reviewed discovery-selection JSON produced by "
            "discover_liquipedia_samples.py."
        ),
    )
    parser.add_argument(
        "--api-key-file",
        type=Path,
        help=(
            "Ignored local file containing either the raw key or "
            "LIQUIPEDIA_API_KEY=<key>."
        ),
    )
    parser.add_argument(
        "--prompt-api-key",
        action="store_true",
        help="Read the key interactively without echoing it.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=OUTPUT_ROOT,
        help="Root directory for timestamped validation runs.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=30.0,
        help="Timeout for the single API request.",
    )
    parser.add_argument(
        "--analyze-response",
        type=Path,
        help=(
            "Analyze an existing response JSON without making an API request. "
            "Useful for tests and repeatable local review."
        ),
    )
    return parser.parse_args(argv)


def read_selection_file(path: Path) -> tuple[str, ...]:
    """Read reviewed category selections from the discovery artifact."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    selections = payload.get("selections")
    if not isinstance(selections, dict):
        raise ValueError("Selection file must contain an object named 'selections'.")

    unresolved = [
        category
        for category, selection in selections.items()
        if not isinstance(selection, dict) or not selection.get("match2id")
    ]
    if unresolved:
        raise ValueError(
            "Selection file contains unresolved categories: "
            + ", ".join(sorted(unresolved))
        )

    return validate_match_ids(
        str(selection["match2id"]) for selection in selections.values()
    )


def resolve_match_ids(args: argparse.Namespace) -> tuple[str, ...]:
    """Resolve explicit IDs and prevent an accidental hard-coded live query."""
    supplied = list(args.match_ids or [])
    if args.selection_file is not None:
        supplied.extend(read_selection_file(args.selection_file))
    if not supplied:
        raise ValueError(
            "No match IDs selected. Run discover_liquipedia_samples.py, review "
            "its selections, then pass --selection-file or explicit --match-id "
            "values."
        )
    return validate_match_ids(supplied)


def read_api_key(
    *,
    api_key_file: Path | None = None,
    prompt: bool = False,
) -> str:
    """Load a key without ever logging it."""
    key = os.environ.get("LIQUIPEDIA_API_KEY", "").strip()

    if not key and api_key_file is not None:
        content = api_key_file.read_text(encoding="utf-8").strip()
        if content.startswith("LIQUIPEDIA_API_KEY="):
            content = content.split("=", maxsplit=1)[1].strip()
            if (
                len(content) >= 2
                and content[0] == content[-1]
                and content[0] in {'"', "'"}
            ):
                content = content[1:-1]
        key = content

    if not key and prompt:
        key = getpass.getpass("Liquipedia API key: ").strip()

    if not key:
        raise ValueError(
            "No API key found. Set LIQUIPEDIA_API_KEY, pass --api-key-file, "
            "or use --prompt-api-key."
        )
    if any(character.isspace() for character in key):
        raise ValueError("The Liquipedia API key must not contain whitespace.")
    return key


def validate_match_ids(match_ids: Iterable[str]) -> tuple[str, ...]:
    """Validate and deduplicate exact match2 IDs without reordering them."""
    validated: list[str] = []
    seen: set[str] = set()
    for match_id in match_ids:
        value = match_id.strip()
        if not MATCH_ID_PATTERN.fullmatch(value):
            raise ValueError(
                f"Unsafe match2 ID {value!r}; expected letters, numbers, _ or -."
            )
        if value not in seen:
            validated.append(value)
            seen.add(value)

    if not validated:
        raise ValueError("At least one match2 ID is required.")
    if len(validated) > 8:
        raise ValueError("The validation gate is capped at eight match2 IDs.")
    return tuple(validated)


def build_request_url(match_ids: Iterable[str]) -> str:
    """Build one projected, filtered match request for all sample IDs."""
    validated = validate_match_ids(match_ids)
    clauses = " OR ".join(
        f"[[match2id::{match_id}]]" for match_id in validated
    )
    parameters = {
        "wiki": "dota2",
        "conditions": f"({clauses})",
        "query": ",".join(MATCH_FIELD_PROJECTION),
        # Allow duplicate source records without needing a second request.
        "limit": min(50, max(20, len(validated) * 4)),
        "offset": 0,
        "order": "match2id ASC",
    }
    return f"{API_URL}?{urlencode(parameters)}"


def request_once(
    *,
    url: str,
    api_key: str,
    timeout_seconds: float,
) -> tuple[bytes, dict[str, str]]:
    """Perform exactly one official API request and return decompressed bytes."""
    request = Request(
        url,
        method="GET",
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "Authorization": f"Apikey {api_key}",
            "User-Agent": USER_AGENT,
        },
    )

    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read()
            headers = {key.lower(): value for key, value in response.headers.items()}
            if headers.get("content-encoding", "").lower() == "gzip":
                body = gzip.decompress(body)
            return body, {
                "status": str(response.status),
                "content_type": headers.get("content-type", ""),
                "content_encoding": headers.get("content-encoding", ""),
            }
    except HTTPError as error:
        response_body = error.read()
        if error.headers.get("Content-Encoding", "").lower() == "gzip":
            response_body = gzip.decompress(response_body)
        message = response_body.decode("utf-8", errors="replace")[:500]
        if api_key:
            message = message.replace(api_key, "<redacted-api-key>")
        retry_after = error.headers.get("Retry-After")
        suffix = f"; Retry-After={retry_after}" if retry_after else ""
        raise RuntimeError(
            f"Liquipedia API returned HTTP {error.code}{suffix}: {message}"
        ) from error
    except URLError as error:
        raise RuntimeError(f"Liquipedia API request failed: {error.reason}") from error


def decode_nested_json(value: Any) -> Any:
    """Recursively decode JSON strings while preserving ordinary strings."""
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


def flatten_leaves(value: Any, path: str = "") -> list[Leaf]:
    """Flatten nested dictionaries/lists while retaining stable array paths."""
    normalized = decode_nested_json(value)
    leaves: list[Leaf] = []

    if isinstance(normalized, dict):
        for key, item in normalized.items():
            child_path = f"{path}.{key}" if path else key
            leaves.extend(flatten_leaves(item, child_path))
    elif isinstance(normalized, list):
        child_path = f"{path}[]" if path else "[]"
        for item in normalized:
            leaves.extend(flatten_leaves(item, child_path))
    else:
        leaves.append(Leaf(path=path or "$", value=normalized))
    return leaves


def unique_paths(leaves: Iterable[Leaf]) -> tuple[str, ...]:
    """Return sorted unique evidence paths with a bounded report size."""
    return tuple(sorted({leaf.path for leaf in leaves})[:50])


def matches_key(leaves: Iterable[Leaf], keys: set[str]) -> list[Leaf]:
    """Find leaves whose normalized final key is in a known set."""
    return [leaf for leaf in leaves if leaf.key in keys]


def paths_containing(leaves: Iterable[Leaf], *terms: str) -> list[Leaf]:
    """Find leaves whose normalized path contains every supplied term."""
    normalized_terms = tuple(
        re.sub(r"[^a-z0-9]+", "", term.lower()) for term in terms
    )
    result = []
    for leaf in leaves:
        normalized_path = re.sub(r"[^a-z0-9]+", "", leaf.path.lower())
        if all(term in normalized_path for term in normalized_terms):
            result.append(leaf)
    return result


def record_games(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Return decoded game objects from the documented match2games container."""
    decoded = decode_nested_json(record.get("match2games", []))
    if isinstance(decoded, dict):
        decoded = list(decoded.values())
    if not isinstance(decoded, list):
        return []
    return [game for game in decoded if isinstance(game, dict)]


def indexed_slot_values(
    extradata: dict[str, Any],
    pattern: re.Pattern[str],
) -> dict[int, dict[int, Any]]:
    """Group non-empty observed draft values by team and slot."""
    slots: dict[int, dict[int, Any]] = {1: {}, 2: {}}
    for raw_key, value in extradata.items():
        key = re.sub(r"[^a-z0-9]+", "", str(raw_key).lower())
        match = pattern.fullmatch(key)
        if match and str(value).strip():
            slots[int(match.group(1))][int(match.group(2))] = value
    return slots


def analyze_draft_schema(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate the observed Dota draft shape without inferring missing fields."""
    required_pick_slots = set(range(1, 6))
    required_ban_slots = set(range(1, 8))
    matches: list[dict[str, Any]] = []
    total_game_objects = 0
    complete_draft_games = 0

    for record in records:
        match2id = str(record.get("match2id", "")).strip()
        games_report: list[dict[str, Any]] = []
        for game_index, game in enumerate(record_games(record)):
            total_game_objects += 1
            raw_extradata = decode_nested_json(game.get("extradata", {}))
            extradata = raw_extradata if isinstance(raw_extradata, dict) else {}
            picks = indexed_slot_values(extradata, TEAM_HERO_SLOT_PATTERN)
            bans = indexed_slot_values(extradata, TEAM_BAN_SLOT_PATTERN)
            team1side = str(extradata.get("team1side", "")).strip().lower()
            team2side = str(extradata.get("team2side", "")).strip().lower()
            winner = str(game.get("winner", "")).strip()

            picks_complete = all(
                required_pick_slots.issubset(set(picks[team]))
                for team in (1, 2)
            )
            bans_complete = all(
                required_ban_slots.issubset(set(bans[team]))
                for team in (1, 2)
            )
            sides_complete = {team1side, team2side} == {"radiant", "dire"}
            complete = bool(
                winner
                and picks_complete
                and bans_complete
                and sides_complete
            )
            if complete:
                complete_draft_games += 1

            games_report.append(
                {
                    "game_index": game_index,
                    "match2gameid": game.get("match2gameid"),
                    "winner_present": bool(winner),
                    "team1_pick_slots": sorted(picks[1]),
                    "team2_pick_slots": sorted(picks[2]),
                    "team1_ban_slots": sorted(bans[1]),
                    "team2_ban_slots": sorted(bans[2]),
                    "team1_side": team1side or None,
                    "team2_side": team2side or None,
                    "complete_per_team_draft": complete,
                    "first_pick": None,
                    "global_draft_order": None,
                }
            )

        matches.append(
            {
                "match2id": match2id or None,
                "game_object_count": len(games_report),
                "complete_draft_game_count": sum(
                    item["complete_per_team_draft"] for item in games_report
                ),
                "games": games_report,
            }
        )

    return {
        "observed_schema": {
            "pick_paths": (
                "match2games[].extradata.team{1|2}hero{1..5}"
            ),
            "ban_paths": "match2games[].extradata.team{1|2}ban{1..7}",
            "side_paths": [
                "match2games[].extradata.team1side",
                "match2games[].extradata.team2side",
            ],
            "winner_path": "match2games[].winner",
        },
        "total_game_objects": total_game_objects,
        "complete_draft_game_count": complete_draft_games,
        "matches": matches,
        "unavailable_fields": {
            "first_pick": {
                "status": "unavailable_in_validated_api_payloads",
                "reason": (
                    "No explicit first-pick field was observed. It is not "
                    "inferred from hero slot numbers or side."
                ),
            },
            "global_draft_order": {
                "status": "unavailable_in_validated_api_payloads",
                "reason": (
                    "No globally interleaved pick/ban event sequence was "
                    "observed. Per-team slot numbers are preserved only as "
                    "per-team order."
                ),
            },
        },
    }


def normalized_draft_schema() -> dict[str, Any]:
    """Return the approved normalization target supported by observed fields."""
    return {
        "games": {
            "primary_key": "game_id",
            "fields": [
                "game_id",
                "source_match2id",
                "source_match2gameid",
                "game_index",
                "team1_id",
                "team2_id",
                "team1_side",
                "team2_side",
                "winner_team_slot",
                "patch",
                "duration_seconds",
                "raw_payload_id",
            ],
        },
        "game_draft_picks": {
            "primary_key": ["game_id", "team_slot", "pick_slot"],
            "fields": [
                "game_id",
                "team_slot",
                "pick_slot",
                "hero_source_name",
                "hero_id",
                "source_json_path",
            ],
            "constraints": [
                "team_slot in (1, 2)",
                "pick_slot between 1 and 5",
            ],
        },
        "game_draft_bans": {
            "primary_key": ["game_id", "team_slot", "ban_slot"],
            "fields": [
                "game_id",
                "team_slot",
                "ban_slot",
                "hero_source_name",
                "hero_id",
                "source_json_path",
            ],
            "constraints": [
                "team_slot in (1, 2)",
                "ban_slot between 1 and 7",
            ],
        },
        "intentionally_unpopulated": {
            "first_pick_team_slot": (
                "Unavailable in validated payloads; never infer."
            ),
            "global_draft_sequence": (
                "Unavailable in validated payloads; never reconstruct from "
                "per-team slot numbers."
            ),
        },
    }


def detect_capabilities(records: list[dict[str, Any]]) -> list[Capability]:
    """Detect required product fields and retain their exact observed paths."""
    leaves = flatten_leaves(records)
    lower_value = lambda leaf: str(leaf.value).strip().lower()
    draft_schema = analyze_draft_schema(records)

    game_ids = matches_key(
        leaves,
        {"match2gameid", "gameid", "externalmatchid", "dotamatchid"},
    )
    game_winners = [
        leaf
        for leaf in matches_key(leaves, {"winner"})
        if "match2games" in leaf.path.lower()
        and str(leaf.value).strip()
    ]
    game_durations = [
        leaf
        for leaf in matches_key(leaves, {"length", "duration", "durationseconds"})
        if "match2games" in leaf.path.lower()
    ]

    sides = [
        leaf
        for leaf in leaves
        if leaf.key in {"team1side", "team2side"}
        and "match2games" in leaf.path.lower()
        and lower_value(leaf) in {"radiant", "dire"}
    ]
    first_pick = [
        leaf
        for leaf in leaves
        if "firstpick" in leaf.key
        or ("first" in leaf.key and "pick" in leaf.key)
    ]

    picks = [
        leaf
        for leaf in leaves
        if TEAM_HERO_SLOT_PATTERN.fullmatch(leaf.key)
        and "match2games" in leaf.path.lower()
        and str(leaf.value).strip()
    ]
    bans = [
        leaf
        for leaf in leaves
        if TEAM_BAN_SLOT_PATTERN.fullmatch(leaf.key)
        and "match2games" in leaf.path.lower()
        and str(leaf.value).strip()
    ]
    global_draft_order = [
        leaf
        for leaf in leaves
        if leaf.key in GLOBAL_DRAFT_ORDER_KEYS
        or ("draft" in leaf.key and "order" in leaf.key)
    ]
    complete_draft = (
        [Leaf(path="match2games[].extradata", value=True)]
        if draft_schema["complete_draft_game_count"]
        else []
    )

    player_heroes = [
        leaf
        for leaf in leaves
        if leaf.key in {"hero", "heroid", "character", "characterid"}
        and any(
            container in leaf.path.lower()
            for container in ("participant", "player")
        )
    ]
    kda = matches_key(
        leaves,
        {"kda", "kill", "kills", "death", "deaths", "assist", "assists"},
    )
    damage = matches_key(
        leaves,
        {"damage", "dmg", "herodamage", "damagetoheroes"},
    )
    farm = matches_key(
        leaves,
        {"lh", "lasthits", "denies", "deny", "lhdeny", "lhdn"},
    )
    economy = matches_key(
        leaves,
        {"gpm", "xpm", "net", "networth", "goldperminute", "xpperminute"},
    )
    items = [
        leaf
        for leaf in leaves
        if leaf.key.startswith("item")
        or "inventory" in leaf.key
    ]
    team_stats = [
        leaf
        for leaf in leaves
        if leaf.key
        in {
            "teamkills",
            "teamgold",
            "towers",
            "barracks",
            "roshan",
            "roshans",
        }
    ]
    coordinates = [
        leaf
        for leaf in leaves
        if leaf.key in {"x", "y", "xcoordinate", "ycoordinate", "coordinates"}
        and any(
            context in leaf.path.lower()
            for context in ("event", "position", "timeline", "ward", "kill")
        )
    ]
    patch_fields = [
        leaf
        for leaf in matches_key(leaves, {"patch"})
        if "match2games" in leaf.path.lower()
    ]
    hero_identity = picks + player_heroes

    def capability(
        name: str,
        label: str,
        evidence: list[Leaf],
        interpretation: str,
    ) -> Capability:
        return Capability(
            name=name,
            label=label,
            present=bool(evidence),
            paths=unique_paths(evidence),
            interpretation=interpretation,
        )

    return [
        capability(
            "individual_game_id",
            "Individual game ID",
            game_ids,
            "Required for stable game-level joins and deduplication.",
        ),
        capability(
            "individual_game_winner",
            "Individual game winner",
            game_winners,
            "Required as the Draft Assistant training label.",
        ),
        capability(
            "individual_game_duration",
            "Individual game duration",
            game_durations,
            "Supports game-level Match Analytics.",
        ),
        capability(
            "individual_game_patch",
            "Individual game patch",
            patch_fields,
            "Preferred over a series-level patch when available.",
        ),
        capability(
            "radiant_dire",
            "Radiant/Dire assignment",
            sides,
            "Required to construct side-aware draft features.",
        ),
        capability(
            "first_pick",
            "Explicit first-pick assignment",
            first_pick,
            "Unavailable when no explicit source field is observed; never inferred.",
        ),
        capability(
            "ordered_picks",
            "Per-team ordered hero slots",
            picks,
            (
                "Observed team1hero1..5/team2hero1..5 slots. These preserve "
                "per-team order, not a global interleaved draft sequence."
            ),
        ),
        capability(
            "ordered_bans",
            "Per-team ordered ban slots",
            bans,
            (
                "Observed team1ban1..7/team2ban1..7 slots. These preserve "
                "per-team order only."
            ),
        ),
        capability(
            "global_draft_order",
            "Global interleaved draft order",
            global_draft_order,
            "Unavailable when no explicit event sequence is observed; never inferred.",
        ),
        capability(
            "complete_per_team_draft",
            "Complete per-team draft in one game",
            complete_draft,
            (
                "Strictly requires one game with winner, both sides, five "
                "non-empty hero slots per team, and seven non-empty ban slots "
                "per team."
            ),
        ),
        capability(
            "hero_identity",
            "Picked hero identity",
            hero_identity,
            "Required for model features and hero-level analytics.",
        ),
        capability(
            "player_hero_assignment",
            "Player-to-hero assignment",
            player_heroes,
            "Required for player hero-pool and performance analytics.",
        ),
        capability(
            "player_kda",
            "Player K/D/A",
            kda,
            "Required for detailed Player Analytics.",
        ),
        capability(
            "hero_damage",
            "Player hero damage",
            damage,
            "Optional detailed Player Analytics metric.",
        ),
        capability(
            "last_hits_denies",
            "Last hits and denies",
            farm,
            "Optional farm-performance metric.",
        ),
        capability(
            "gpm_xpm_networth",
            "GPM/XPM/net worth",
            economy,
            "Optional economy-performance metrics.",
        ),
        capability(
            "items",
            "Player items/inventory",
            items,
            "Optional Match and Player Analytics fields.",
        ),
        capability(
            "team_game_stats",
            "Team game statistics",
            team_stats,
            "Optional kills, gold, objectives, and structure statistics.",
        ),
        capability(
            "spatial_telemetry",
            "Spatial telemetry",
            coordinates,
            "Required for in-game map heatmaps.",
        ),
    ]


def build_path_inventory(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Inventory normalized nested paths without copying source values."""
    values_by_path: dict[str, list[Any]] = defaultdict(list)
    for leaf in flatten_leaves(records):
        values_by_path[leaf.path].append(leaf.value)

    inventory = []
    for path, values in sorted(values_by_path.items()):
        types = sorted({type(value).__name__ for value in values})
        inventory.append(
            {
                "path": path,
                "types": types,
                "occurrences": len(values),
                "non_null_occurrences": sum(value is not None for value in values),
            }
        )
    return inventory


def deduplicate_records(
    records: Iterable[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Deduplicate by match2id while retaining unidentifiable records."""
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    duplicate_count = 0

    for record in records:
        match_id = str(record.get("match2id", "")).strip()
        if match_id and match_id in seen:
            duplicate_count += 1
            continue
        if match_id:
            seen.add(match_id)
        output.append(record)
    return output, duplicate_count


def product_verdicts(capabilities: list[Capability]) -> dict[str, dict[str, Any]]:
    """Compute conservative feature-gate decisions."""
    availability = {item.name: item.present for item in capabilities}

    def verdict(
        required: tuple[str, ...],
        *,
        documented_limitations: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        missing = [name for name in required if not availability.get(name, False)]
        unavailable = [
            name for name in documented_limitations if not availability.get(name, False)
        ]
        if missing:
            status = "blocked"
        elif unavailable:
            status = "verified_with_documented_limitations"
        else:
            status = "verified"
        return {
            "status": status,
            "required_capabilities": list(required),
            "missing_capabilities": missing,
            "documented_unavailable_capabilities": unavailable,
        }

    return {
        "ai_draft_assistant": verdict(
            (
                "individual_game_winner",
                "radiant_dire",
                "ordered_picks",
                "ordered_bans",
                "hero_identity",
                "complete_per_team_draft",
            ),
            documented_limitations=("first_pick", "global_draft_order"),
        ),
        "player_performance_analytics": verdict(
            (
                "individual_game_winner",
                "player_hero_assignment",
                "player_kda",
            )
        ),
        "game_level_match_analytics": verdict(
            (
                "individual_game_id",
                "individual_game_winner",
                "individual_game_duration",
            )
        ),
        "draft_heatmaps": verdict(
            (
                "individual_game_winner",
                "radiant_dire",
                "ordered_picks",
                "ordered_bans",
                "hero_identity",
            )
        ),
        "spatial_heatmaps": verdict(("spatial_telemetry",)),
    }


def analyze_payload(
    payload: dict[str, Any],
    *,
    requested_match_ids: Iterable[str],
) -> dict[str, Any]:
    """Analyze one parsed API payload without mutating the raw data."""
    errors = payload.get("error", [])
    warnings = payload.get("warning", [])
    result = payload.get("result", [])
    if not isinstance(result, list):
        raise ValueError("API response field 'result' is not an array.")

    records = [item for item in result if isinstance(item, dict)]
    records, duplicate_count = deduplicate_records(records)
    requested = validate_match_ids(requested_match_ids)
    returned_ids = sorted(
        {
            str(record.get("match2id"))
            for record in records
            if record.get("match2id")
        }
    )
    capabilities = detect_capabilities(records)
    draft_schema = analyze_draft_schema(records)

    unavailable_names = {"first_pick", "global_draft_order"}
    corrected_names = {"ordered_picks"}

    def capability_status(item: Capability) -> str:
        if item.present and item.name in corrected_names:
            return "present_after_detector_correction"
        if item.present:
            return "present_in_official_api_samples"
        if item.name in unavailable_names:
            return "unavailable_in_validated_api_payloads"
        return "absent_in_samples"

    return {
        "contract_version": "0.2",
        "api_version": "v3",
        "wiki": "dota2",
        "requested_match_ids": list(requested),
        "returned_match_ids": returned_ids,
        "missing_match_ids": [
            match_id for match_id in requested if match_id not in returned_ids
        ],
        "raw_result_count": len(result),
        "deduplicated_record_count": len(records),
        "duplicate_count": duplicate_count,
        "non_object_result_count": len(result) - sum(
            isinstance(item, dict) for item in result
        ),
        "api_errors": errors if isinstance(errors, list) else [str(errors)],
        "api_warnings": warnings if isinstance(warnings, list) else [str(warnings)],
        "capabilities": [
            {
                "name": item.name,
                "label": item.label,
                "present": item.present,
                "status": capability_status(item),
                "paths": list(item.paths),
                "interpretation": item.interpretation,
            }
            for item in capabilities
        ],
        "detector_corrections": {
            "ordered_picks": {
                "previous_status": "missed",
                "corrected_status": "present",
                "observed_pattern": (
                    "match2games[].extradata.team{1|2}hero{1..5}"
                ),
            },
            "ordered_bans": {
                "previous_status": "partially_detected_by_generic_fallback",
                "corrected_status": "strict_slot_validation",
                "observed_pattern": (
                    "match2games[].extradata.team{1|2}ban{1..7}"
                ),
            },
        },
        "draft_schema_validation": draft_schema,
        "normalized_draft_schema": normalized_draft_schema(),
        "product_verdicts": product_verdicts(capabilities),
        "path_inventory": build_path_inventory(records),
    }


def render_markdown(report: dict[str, Any], manifest: dict[str, Any]) -> str:
    """Render the human-readable audit report."""
    lines = [
        "# Liquipedia Dota 2 API Validation Report",
        "",
        f"**Run timestamp:** {manifest['requested_at']}",
        f"**Official endpoint:** `{manifest['endpoint']}`",
        f"**API requests made:** {manifest['request_count']}",
        f"**Requested matches:** {len(report['requested_match_ids'])}",
        f"**Returned unique matches:** {report['deduplicated_record_count']}",
        f"**Response SHA-256:** `{manifest['response_sha256']}`",
        "",
        "## Product Gate Verdicts",
        "",
        "| Capability | Verdict | Missing requirements | Documented limitations |",
        "| --- | --- | --- | --- |",
    ]

    for name, verdict in report["product_verdicts"].items():
        missing = ", ".join(verdict["missing_capabilities"]) or "None"
        limitations = (
            ", ".join(verdict["documented_unavailable_capabilities"]) or "None"
        )
        lines.append(
            f"| `{name}` | **{verdict['status']}** | {missing} | {limitations} |"
        )

    lines.extend(
        [
            "",
            "## Required Field Evidence",
            "",
            "| Requirement | Status | Observed paths |",
            "| --- | --- | --- |",
        ]
    )
    for capability in report["capabilities"]:
        paths = "<br>".join(f"`{path}`" for path in capability["paths"])
        paths = paths or "—"
        lines.append(
            f"| {capability['label']} | **{capability['status']}** | {paths} |"
        )

    draft = report["draft_schema_validation"]
    lines.extend(
        [
            "",
            "## Strict Draft-Shape Validation",
            "",
            (
                f"- Game objects inspected: {draft['total_game_objects']}"
            ),
            (
                "- Games with winner, both sides, five picks per team, and "
                f"seven bans per team: {draft['complete_draft_game_count']}"
            ),
            "- Explicit first pick: **unavailable in validated API payloads**",
            "- Global interleaved draft order: **unavailable in validated API payloads**",
            "- No first-pick or global-order value was inferred.",
            "",
            "| Match ID | Game objects | Complete per-team drafts |",
            "| --- | ---: | ---: |",
        ]
    )
    for match in draft["matches"]:
        lines.append(
            f"| `{match['match2id']}` | {match['game_object_count']} | "
            f"{match['complete_draft_game_count']} |"
        )

    lines.extend(
        [
            "",
            "## ML Feature Suitability",
            "",
            "| Field group | Suitability | Policy |",
            "| --- | --- | --- |",
            (
                "| Per-team hero slots 1-5 | **Suitable** | Encode as team-aware "
                "categorical/set features; preserve slot numbers. |"
            ),
            (
                "| Per-team ban slots 1-7 | **Suitable** | Encode as team-aware "
                "categorical features; preserve slot numbers. |"
            ),
            (
                "| Radiant/Dire assignment | **Suitable** | Required side-aware "
                "feature. |"
            ),
            (
                "| Per-game winner | **Suitable** | Supervised-learning label "
                "after excluding unplayed/default results. |"
            ),
            (
                "| Patch and match date | **Suitable when present** | Use for "
                "temporal splits and patch-aware features. |"
            ),
            (
                "| First pick | **Unavailable** | Do not synthesize or impute "
                "from side or slot numbers. |"
            ),
            (
                "| Global draft sequence | **Unavailable** | Per-team slot order "
                "must not be represented as global event order. |"
            ),
            (
                "| Player performance statistics | **Not validated here** | Use "
                "only if independently observed by the field capability report. |"
            ),
            "",
            "## Normalized Draft Storage Contract",
            "",
            "### `games`",
            "",
            "`game_id`, `source_match2id`, `source_match2gameid`, `game_index`, "
            "`team1_id`, `team2_id`, `team1_side`, `team2_side`, "
            "`winner_team_slot`, `patch`, `duration_seconds`, `raw_payload_id`",
            "",
            "### `game_draft_picks`",
            "",
            "`game_id`, `team_slot`, `pick_slot`, `hero_source_name`, `hero_id`, "
            "`source_json_path`",
            "",
            "Primary key: `(game_id, team_slot, pick_slot)`; `team_slot` is 1 or "
            "2 and `pick_slot` is 1 through 5.",
            "",
            "### `game_draft_bans`",
            "",
            "`game_id`, `team_slot`, `ban_slot`, `hero_source_name`, `hero_id`, "
            "`source_json_path`",
            "",
            "Primary key: `(game_id, team_slot, ban_slot)`; `team_slot` is 1 or "
            "2 and `ban_slot` is 1 through 7.",
            "",
            "The contract intentionally does not populate `first_pick_team_slot` "
            "or `global_draft_sequence`.",
        ]
    )

    lines.extend(
        [
            "",
            "## Sample Coverage",
            "",
            f"- Requested IDs: `{', '.join(report['requested_match_ids'])}`",
            f"- Returned IDs: `{', '.join(report['returned_match_ids']) or 'none'}`",
            f"- Missing IDs: `{', '.join(report['missing_match_ids']) or 'none'}`",
            f"- Duplicate records removed: {report['duplicate_count']}",
            f"- API warnings: {json.dumps(report['api_warnings'], ensure_ascii=False)}",
            f"- API errors: {json.dumps(report['api_errors'], ensure_ascii=False)}",
            "",
            "## Nested Path Inventory",
            "",
            "| JSON path | Types | Occurrences | Non-null |",
            "| --- | --- | ---: | ---: |",
        ]
    )
    for item in report["path_inventory"]:
        lines.append(
            f"| `{item['path']}` | {', '.join(item['types'])} | "
            f"{item['occurrences']} | {item['non_null_occurrences']} |"
        )

    lines.extend(
        [
            "",
            "## Interpretation Rule",
            "",
            "`present_in_official_api_samples` and "
            "`present_after_detector_correction` mean the field was observed in "
            "authenticated official API responses. Nested JSON subkeys remain "
            "sample-validated rather than guaranteed by the v3 schema. "
            "`unavailable_in_validated_api_payloads` means no explicit source "
            "field was found and the value must not be inferred. "
            "`absent_in_samples` is not proof that Liquipedia never stores a field; "
            "it cannot be approved as a dependency from this evidence.",
            "",
        ]
    )
    return "\n".join(lines)


def new_run_directory(output_root: Path) -> tuple[Path, str]:
    """Create one UTC timestamped run directory."""
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_directory = output_root / timestamp
    run_directory.mkdir(parents=True, exist_ok=False)
    return run_directory, timestamp


def write_json(path: Path, value: Any) -> None:
    """Write deterministic, readable UTF-8 JSON."""
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def run_live_validation(args: argparse.Namespace) -> Path:
    """Execute one request and write the complete validation artifact set."""
    match_ids = resolve_match_ids(args)
    api_key = read_api_key(
        api_key_file=args.api_key_file,
        prompt=args.prompt_api_key,
    )
    request_url = build_request_url(match_ids)
    run_directory, timestamp = new_run_directory(args.output_root)
    requested_at = datetime.now(UTC).isoformat()

    try:
        response_bytes, response_metadata = request_once(
            url=request_url,
            api_key=api_key,
            timeout_seconds=args.timeout_seconds,
        )
        # Discard the only in-memory reference as soon as the request completes.
        api_key = ""

        response_path = run_directory / "response.json"
        response_path.write_bytes(response_bytes)
        payload = json.loads(response_bytes.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("The API response root is not a JSON object.")

        manifest = {
            "api_version": "v3",
            "content_encoding": response_metadata["content_encoding"],
            "content_type": response_metadata["content_type"],
            "endpoint": API_URL,
            "http_status": int(response_metadata["status"]),
            "query_fields": list(MATCH_FIELD_PROJECTION),
            "request_count": 1,
            "requested_at": requested_at,
            "requested_match_ids": list(match_ids),
            "response_file": response_path.name,
            "response_sha256": hashlib.sha256(response_bytes).hexdigest(),
            "run_id": timestamp,
            "wiki": "dota2",
        }
        report = analyze_payload(payload, requested_match_ids=match_ids)
        write_json(run_directory / "manifest.json", manifest)
        write_json(run_directory / "field_report.json", report)
        (run_directory / "field_report.md").write_text(
            render_markdown(report, manifest),
            encoding="utf-8",
        )
        return run_directory
    except Exception:
        # Preserve no secret-bearing request object or authorization metadata.
        api_key = ""
        raise


def analyze_existing_response(args: argparse.Namespace) -> Path:
    """Analyze an existing raw response without consuming API quota."""
    match_ids = resolve_match_ids(args)
    response_bytes = args.analyze_response.read_bytes()
    payload = json.loads(response_bytes.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("The response root is not a JSON object.")

    run_directory, timestamp = new_run_directory(args.output_root)
    local_response = run_directory / "response.json"
    local_response.write_bytes(response_bytes)
    manifest = {
        "api_version": "v3",
        "content_encoding": "",
        "content_type": "application/json",
        "endpoint": "local-analysis",
        "http_status": None,
        "query_fields": list(MATCH_FIELD_PROJECTION),
        "request_count": 0,
        "requested_at": datetime.now(UTC).isoformat(),
        "requested_match_ids": list(match_ids),
        "response_file": local_response.name,
        "response_sha256": hashlib.sha256(response_bytes).hexdigest(),
        "run_id": timestamp,
        "wiki": "dota2",
    }
    report = analyze_payload(payload, requested_match_ids=match_ids)
    write_json(run_directory / "manifest.json", manifest)
    write_json(run_directory / "field_report.json", report)
    (run_directory / "field_report.md").write_text(
        render_markdown(report, manifest),
        encoding="utf-8",
    )
    return run_directory


def main(argv: list[str] | None = None) -> int:
    """Run the validation gate."""
    args = parse_args(argv)
    try:
        if args.analyze_response is not None:
            run_directory = analyze_existing_response(args)
        else:
            run_directory = run_live_validation(args)
    except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as error:
        print(f"Validation failed: {error}", file=sys.stderr)
        return 1

    print(f"Validation artifacts: {run_directory}")
    print(f"Markdown report: {run_directory / 'field_report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
