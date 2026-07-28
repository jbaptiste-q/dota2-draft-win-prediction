#!/usr/bin/env python3
"""Discover representative Dota 2 match samples through LiquipediaDB API v3.

The command has an offline planning mode and an explicit authenticated
discovery mode. Discovery performs exactly four bounded, non-paginated
``GET /api/v3/match`` requests, saves every raw response, and selects candidates
locally. It never performs the final exact-ID validation request.

No HTML pages are requested or parsed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time as datetime_time, timedelta
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlencode

if __package__:
    from .validate_liquipedia_api import (
        API_URL,
        MATCH_FIELD_PROJECTION,
        USER_AGENT,
        decode_nested_json,
        flatten_leaves,
        read_api_key,
        request_once,
        validate_match_ids,
        write_json,
    )
else:
    from validate_liquipedia_api import (
        API_URL,
        MATCH_FIELD_PROJECTION,
        USER_AGENT,
        decode_nested_json,
        flatten_leaves,
        read_api_key,
        request_once,
        validate_match_ids,
        write_json,
    )


ROOT = Path(__file__).resolve().parents[1]
DISCOVERY_OUTPUT_ROOT = (
    ROOT / "data" / "validation" / "liquipedia" / "discovery"
)
DISCOVERY_REQUEST_COUNT = 4
REQUEST_INTERVAL_SECONDS = 61.0
RECENT_LOOKBACK_DAYS = 90
UPCOMING_LOOKAHEAD_DAYS = 90
OLDER_WINDOW_START = date(2018, 1, 1)
OLDER_WINDOW_END = date(2019, 1, 1)
RECENT_PICKS_PER_TEAM = 5
RECENT_BANS_PER_TEAM = 7

CATEGORY_RECENT = "recent_completed_full_draft"
CATEGORY_OLDER = "older_completed"
CATEGORY_UPCOMING = "incomplete_or_upcoming"
CATEGORY_EXCEPTION = "walkover_forfeit_cancelled_or_unplayed"
CATEGORY_SIDE_CHANGE = "multi_game_side_change"


@dataclass(frozen=True)
class DiscoveryQuery:
    """One bounded official API query and the categories it can satisfy."""

    name: str
    categories: tuple[str, ...]
    conditions: str
    order: str
    limit: int
    rationale: str


def utc_midnight(value: date) -> datetime:
    """Return an aware UTC midnight used for reproducible date conditions."""
    return datetime.combine(value, datetime_time.min, tzinfo=UTC)


def lpdb_datetime(value: datetime) -> str:
    """Format a LiquipediaDB exact-date condition without locale dependence."""
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")


def build_discovery_queries(as_of_date: date) -> tuple[DiscoveryQuery, ...]:
    """Build the fixed four-query discovery plan."""
    today = utc_midnight(as_of_date)
    tomorrow = today + timedelta(days=1)
    recent_start = today - timedelta(days=RECENT_LOOKBACK_DAYS)
    upcoming_end = today + timedelta(days=UPCOMING_LOOKAHEAD_DAYS)
    older_start = utc_midnight(OLDER_WINDOW_START)
    older_end = utc_midnight(OLDER_WINDOW_END)

    return (
        DiscoveryQuery(
            name="recent_completed_candidates",
            categories=(CATEGORY_RECENT, CATEGORY_SIDE_CHANGE),
            conditions=(
                "([[liquipediatier::1]] OR [[liquipediatier::2]])"
                " AND [[finished::1]] AND [[bestof::>1]]"
                f" AND [[date::>{lpdb_datetime(recent_start)}]]"
                f" AND [[date::<{lpdb_datetime(tomorrow)}]]"
            ),
            order="date DESC",
            limit=8,
            rationale=(
                "A 90-day, Tier 1-or-2, completed, best-of-series window "
                "supplies recent professional candidates without limiting the "
                "sample to only the latest Tier 1 matches. Nested match2games "
                "is inspected locally for full drafts and side changes."
            ),
        ),
        DiscoveryQuery(
            name="older_completed_candidates",
            categories=(CATEGORY_OLDER,),
            conditions=(
                "[[finished::1]] AND [[bestof::>1]]"
                f" AND [[date::>{lpdb_datetime(older_start)}]]"
                f" AND [[date::<{lpdb_datetime(older_end)}]]"
            ),
            order="date DESC",
            limit=8,
            rationale=(
                "A fixed 2018 window finds a genuinely older completed "
                "best-of series without assuming that age implies a distinct "
                "legacy schema."
            ),
        ),
        DiscoveryQuery(
            name="upcoming_candidates",
            categories=(CATEGORY_UPCOMING,),
            conditions=(
                "[[finished::0]]"
                f" AND [[date::>{lpdb_datetime(today)}]]"
                f" AND [[date::<{lpdb_datetime(upcoming_end)}]]"
            ),
            order="date ASC",
            limit=5,
            rationale=(
                "The next 90 days is a bounded window for unfinished scheduled "
                "matches; the earliest candidate is preferred."
            ),
        ),
        DiscoveryQuery(
            name="exceptional_result_candidates",
            categories=(CATEGORY_EXCEPTION,),
            conditions=(
                "([[walkover::ff]] OR [[walkover::dq]] OR [[walkover::l]]"
                " OR [[resulttype::default]] OR [[resulttype::np]]"
                " OR [[status::notplayed]])"
            ),
            order="date DESC",
            limit=8,
            rationale=(
                "Only documented exceptional-result values are queried; no "
                "date scan or pagination is used."
            ),
        ),
    )


def build_discovery_url(query: DiscoveryQuery) -> str:
    """Build one projected and bounded official API request URL."""
    parameters = {
        "wiki": "dota2",
        "conditions": query.conditions,
        "query": ",".join(MATCH_FIELD_PROJECTION),
        "limit": query.limit,
        "offset": 0,
        "order": query.order,
    }
    return f"{API_URL}?{urlencode(parameters)}"


def plan_payload(as_of_date: date) -> dict[str, Any]:
    """Return a secret-free description of the complete discovery phase."""
    queries = build_discovery_queries(as_of_date)
    return {
        "api_version": "v3",
        "wiki": "dota2",
        "endpoint": API_URL,
        "http_method": "GET",
        "live_requests_in_this_phase": DISCOVERY_REQUEST_COUNT,
        "automatic_retries": 0,
        "pagination_requests": 0,
        "minimum_seconds_between_requests": REQUEST_INTERVAL_SECONDS,
        "final_exact_id_validation_requests": 1,
        "total_gate_requests_if_all_categories_resolve": (
            DISCOVERY_REQUEST_COUNT + 1
        ),
        "as_of_date": as_of_date.isoformat(),
        "query_fields": list(MATCH_FIELD_PROJECTION),
        "queries": [
            {
                **asdict(query),
                "url_without_credentials": build_discovery_url(query),
            }
            for query in queries
        ],
        "limitations": [
            (
                "LiquipediaDB exposes no documented legacy-schema flag. The "
                "older sample is selected by a fixed historical date window; "
                "its observed nested shape is reported, not presumed."
            ),
            (
                "Full draft data and per-game side assignments are nested JSON "
                "without guaranteed v3 subkeys. They cannot be filtered "
                "reliably and are verified locally in the bounded candidates."
            ),
            (
                "If a category is unresolved, discovery stops without guessing "
                "or issuing an extra request. A fallback ID must have documented "
                "official-API provenance and be approved separately."
            ),
        ],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the discovery command line with safe offline behavior by default."""
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--show-plan",
        action="store_true",
        help="Print the zero-request discovery plan (the default).",
    )
    mode.add_argument(
        "--execute-discovery",
        action="store_true",
        help="Make exactly four authenticated discovery requests.",
    )
    parser.add_argument(
        "--as-of-date",
        type=date.fromisoformat,
        default=datetime.now(UTC).date(),
        help="UTC planning date in YYYY-MM-DD form.",
    )
    parser.add_argument("--api-key-file", type=Path)
    parser.add_argument("--prompt-api-key", action="store_true")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DISCOVERY_OUTPUT_ROOT,
    )
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    return parser.parse_args(argv)


def response_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract unique match records from one official response."""
    result = payload.get("result", [])
    if not isinstance(result, list):
        raise ValueError("API response field 'result' is not an array.")

    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in result:
        if not isinstance(item, dict):
            continue
        match2id = str(item.get("match2id", "")).strip()
        if not match2id or match2id in seen:
            continue
        validate_match_ids([match2id])
        seen.add(match2id)
        records.append(item)
    return records


def truthy_finished(value: Any) -> bool:
    """Interpret the documented boolean field defensively."""
    return value is True or str(value).strip().lower() in {"1", "true"}


def game_list(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Return decoded game objects from the documented JSON container."""
    decoded = decode_nested_json(record.get("match2games", []))
    if isinstance(decoded, dict):
        decoded = list(decoded.values())
    if not isinstance(decoded, list):
        return []
    return [game for game in decoded if isinstance(game, dict)]


def full_draft_evidence(record: dict[str, Any]) -> dict[str, Any] | None:
    """Find one recent game with complete ordered pick and ban slot counts."""
    slot_patterns = {
        "team1_picks": re.compile(r"^team1hero([1-5])$"),
        "team2_picks": re.compile(r"^team2hero([1-5])$"),
        "team1_bans": re.compile(r"^team1ban([1-7])$"),
        "team2_bans": re.compile(r"^team2ban([1-7])$"),
    }
    for game_index, game in enumerate(game_list(record), start=1):
        raw_extradata = decode_nested_json(game.get("extradata", {}))
        extradata = raw_extradata if isinstance(raw_extradata, dict) else {}
        sides = {
            str(extradata.get("team1side", "")).strip().lower(),
            str(extradata.get("team2side", "")).strip().lower(),
        }
        if not str(game.get("winner", "")).strip() or sides != {"radiant", "dire"}:
            continue

        keys = {leaf.key for leaf in flatten_leaves(game)}
        slots = {
            name: sorted(
                {
                    int(match.group(1))
                    for key in keys
                    if (match := pattern.fullmatch(key))
                }
            )
            for name, pattern in slot_patterns.items()
        }
        required_picks = set(range(1, RECENT_PICKS_PER_TEAM + 1))
        required_bans = set(range(1, RECENT_BANS_PER_TEAM + 1))
        if (
            required_picks.issubset(slots["team1_picks"])
            and required_picks.issubset(slots["team2_picks"])
            and required_bans.issubset(slots["team1_bans"])
            and required_bans.issubset(slots["team2_bans"])
        ):
            return {"game_index": game_index, **slots}
    return None


def side_signature(game: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    """Extract comparable team-to-side evidence from one game."""
    def indexed_leaves(
        value: Any,
        path: str = "",
    ) -> Iterable[tuple[str, str, Any]]:
        normalized = decode_nested_json(value)
        if isinstance(normalized, dict):
            for key, item in normalized.items():
                child = f"{path}.{key}" if path else str(key)
                yield from indexed_leaves(item, child)
            return
        if isinstance(normalized, list):
            for index, item in enumerate(normalized):
                yield from indexed_leaves(item, f"{path}[{index}]")
            return
        key = path.rsplit(".", maxsplit=1)[-1]
        key = key.rsplit("[", maxsplit=1)[-1] if key.endswith("]") else key
        yield path, "".join(character for character in key.lower() if character.isalnum()), normalized

    evidence: list[tuple[str, str]] = []
    for path, key, raw_value in indexed_leaves(game):
        value = str(raw_value).strip().lower()
        if (
            ("side" in key and value in {"radiant", "dire"})
            or key in {"radiant", "dire", "radiantside", "direside"}
        ):
            evidence.append((path, value))
    return tuple(sorted(set(evidence)))


def has_side_change(record: dict[str, Any]) -> tuple[bool, int]:
    """Verify at least two games with different explicit side assignments."""
    games = game_list(record)
    signatures = [signature for game in games if (signature := side_signature(game))]
    return len(signatures) >= 2 and len(set(signatures)) >= 2, len(games)


def has_exceptional_result(record: dict[str, Any]) -> bool:
    """Verify documented exceptional values in the returned record."""
    if str(record.get("walkover", "")).strip().lower() in {"ff", "dq", "l"}:
        return True
    if str(record.get("resulttype", "")).strip().lower() in {"default", "np"}:
        return True
    if str(record.get("status", "")).strip().lower() == "notplayed":
        return True

    for leaf in flatten_leaves(record.get("match2opponents", [])):
        if leaf.key == "status" and str(leaf.value).strip().upper() in {
            "FF",
            "DQ",
            "L",
            "W",
        }:
            return True
    return False


def selection(
    record: dict[str, Any] | None,
    *,
    reason: str,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one reviewable category selection without copying raw payloads."""
    if record is None:
        return {
            "match2id": None,
            "status": "unresolved",
            "reason": reason,
            "evidence": evidence or {},
        }
    return {
        "match2id": str(record["match2id"]),
        "status": "selected_pending_review",
        "reason": reason,
        "evidence": {
            "date": record.get("date"),
            "finished": record.get("finished"),
            "bestof": record.get("bestof"),
            "status": record.get("status"),
            "resulttype": record.get("resulttype"),
            "walkover": record.get("walkover"),
            **(evidence or {}),
        },
    }


def select_candidates(
    records_by_query: dict[str, list[dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    """Select all five categories from four bounded response sets."""
    recent_records = records_by_query.get("recent_completed_candidates", [])
    older_records = records_by_query.get("older_completed_candidates", [])
    upcoming_records = records_by_query.get("upcoming_candidates", [])
    exceptional_records = records_by_query.get(
        "exceptional_result_candidates", []
    )

    recent = None
    recent_draft_evidence = None
    for record in recent_records:
        if not truthy_finished(record.get("finished")):
            continue
        evidence = full_draft_evidence(record)
        if evidence is not None:
            recent = record
            recent_draft_evidence = evidence
            break
    older = next(
        (
            record
            for record in older_records
            if truthy_finished(record.get("finished"))
        ),
        None,
    )
    upcoming = next(
        (
            record
            for record in upcoming_records
            if not truthy_finished(record.get("finished"))
        ),
        None,
    )
    exceptional = next(
        (record for record in exceptional_records if has_exceptional_result(record)),
        None,
    )

    side_change = None
    side_change_game_count = 0
    for record in recent_records:
        changed, game_count = has_side_change(record)
        if changed:
            side_change = record
            side_change_game_count = game_count
            break

    return {
        CATEGORY_RECENT: selection(
            recent,
            reason=(
                "Recent completed best-of candidate with all Draft Assistant "
                "capabilities observed in this record."
                if recent
                else "No recent candidate contained a complete observed draft."
            ),
            evidence=(
                {
                    "draft_gate": "verified",
                    "full_draft": recent_draft_evidence,
                }
                if recent
                else None
            ),
        ),
        CATEGORY_OLDER: selection(
            older,
            reason=(
                "Completed best-of candidate from the fixed 2018 window. It is "
                "an older sample; no undocumented legacy-schema claim is made."
                if older
                else "No completed candidate was returned from the 2018 window."
            ),
        ),
        CATEGORY_UPCOMING: selection(
            upcoming,
            reason=(
                "Earliest returned future candidate with finished=false."
                if upcoming
                else "No unfinished future candidate was returned."
            ),
        ),
        CATEGORY_EXCEPTION: selection(
            exceptional,
            reason=(
                "Returned record contains a documented walkover, default, "
                "not-played, or opponent-forfeit status."
                if exceptional
                else "No returned record contained a documented exceptional value."
            ),
        ),
        CATEGORY_SIDE_CHANGE: selection(
            side_change,
            reason=(
                "At least two games have explicit, different side-assignment "
                "signatures."
                if side_change
                else "No recent candidate proved an explicit side change."
            ),
            evidence=(
                {"game_count": side_change_game_count, "side_change": "verified"}
                if side_change
                else None
            ),
        ),
    }


def render_discovery_markdown(report: dict[str, Any]) -> str:
    """Render the concise approval artifact."""
    lines = [
        "# Liquipedia Match-Sample Discovery",
        "",
        f"**As-of date:** {report['as_of_date']}",
        f"**Official endpoint:** `{report['endpoint']}`",
        f"**API requests made:** {report['request_count']}",
        f"**Ready for exact-ID validation:** {report['ready_for_validation']}",
        "",
        "## Selections",
        "",
        "| Category | Match ID | Status | Reason |",
        "| --- | --- | --- | --- |",
    ]
    for category, item in report["selections"].items():
        match2id = item["match2id"] or "—"
        reason = str(item["reason"]).replace("|", "\\|")
        lines.append(
            f"| `{category}` | `{match2id}` | {item['status']} | {reason} |"
        )

    lines.extend(
        [
            "",
            "## Approval Boundary",
            "",
            "Discovery does not run the exact-ID field validation. Review these "
            "selections first, then pass `selection.json` to "
            "`validate_liquipedia_api.py`. That later command makes one request.",
            "",
        ]
    )
    return "\n".join(lines)


def create_run_directory(output_root: Path) -> tuple[Path, str]:
    """Create a timestamped discovery directory."""
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_directory = output_root / timestamp
    run_directory.mkdir(parents=True, exist_ok=False)
    return run_directory, timestamp


def execute_discovery(args: argparse.Namespace) -> Path:
    """Make exactly four bounded calls and stop before field validation."""
    api_key = read_api_key(
        api_key_file=args.api_key_file,
        prompt=args.prompt_api_key,
    )
    queries = build_discovery_queries(args.as_of_date)
    if len(queries) != DISCOVERY_REQUEST_COUNT:
        raise RuntimeError("Discovery request budget changed unexpectedly.")

    run_directory, run_id = create_run_directory(args.output_root)
    records_by_query: dict[str, list[dict[str, Any]]] = {}
    requests: list[dict[str, Any]] = []

    try:
        for index, query in enumerate(queries):
            if index:
                time.sleep(REQUEST_INTERVAL_SECONDS)
            response_bytes, metadata = request_once(
                url=build_discovery_url(query),
                api_key=api_key,
                timeout_seconds=args.timeout_seconds,
            )
            response_path = run_directory / f"{index + 1:02d}_{query.name}.json"
            response_path.write_bytes(response_bytes)
            payload = json.loads(response_bytes.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("The API response root is not a JSON object.")
            records = response_records(payload)
            records_by_query[query.name] = records
            requests.append(
                {
                    "sequence": index + 1,
                    "name": query.name,
                    "categories": list(query.categories),
                    "conditions": query.conditions,
                    "limit": query.limit,
                    "order": query.order,
                    "http_status": int(metadata["status"]),
                    "response_file": response_path.name,
                    "response_sha256": hashlib.sha256(response_bytes).hexdigest(),
                    "unique_record_count": len(records),
                }
            )
    finally:
        api_key = ""

    selections = select_candidates(records_by_query)
    ready = all(item["match2id"] for item in selections.values())
    report = {
        "contract_version": "0.2",
        "run_id": run_id,
        "as_of_date": args.as_of_date.isoformat(),
        "api_version": "v3",
        "wiki": "dota2",
        "endpoint": API_URL,
        "user_agent": USER_AGENT,
        "request_count": len(requests),
        "automatic_retries": 0,
        "pagination_requests": 0,
        "minimum_seconds_between_requests": REQUEST_INTERVAL_SECONDS,
        "requests": requests,
        "selections": selections,
        "ready_for_validation": ready,
    }
    write_json(run_directory / "selection.json", report)
    (run_directory / "selection.md").write_text(
        render_discovery_markdown(report),
        encoding="utf-8",
    )
    return run_directory


def main(argv: list[str] | None = None) -> int:
    """Show the plan by default; execute only behind an explicit flag."""
    args = parse_args(argv)
    if not args.execute_discovery:
        print(json.dumps(plan_payload(args.as_of_date), indent=2))
        return 0

    try:
        run_directory = execute_discovery(args)
    except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as error:
        print(f"Discovery failed: {error}", file=sys.stderr)
        return 1

    print(f"Discovery artifacts: {run_directory}")
    print(f"Review: {run_directory / 'selection.md'}")
    print("No exact-ID validation request was made.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
