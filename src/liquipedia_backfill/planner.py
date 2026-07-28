"""Secret-free deterministic request planning for Liquipedia backfills."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlencode

from .config import BackfillConfig, canonical_json
from .contract import API_URL, USER_AGENT, WIKI


def lpdb_datetime(value) -> str:
    """Format a UTC datetime for LiquipediaDB conditions."""
    return value.strftime("%Y-%m-%d %H:%M:%S")


def build_conditions(config: BackfillConfig) -> str:
    """Build only documented top-level historical match conditions."""
    tier_clauses = " OR ".join(
        f"[[liquipediatier::{tier}]]"
        for tier in config.tiers
    )
    inclusive_start = config.start_utc - timedelta(seconds=1)
    return (
        f"({tier_clauses})"
        " AND [[finished::1]]"
        f" AND [[date::>{lpdb_datetime(inclusive_start)}]]"
        f" AND [[date::<{lpdb_datetime(config.end_utc)}]]"
    )


@dataclass(frozen=True, slots=True)
class RequestSpec:
    """One exact, credential-free API page request."""

    sequence: int
    offset: int
    endpoint: str
    parameters: dict[str, object]

    @property
    def canonical_payload(self) -> dict[str, object]:
        """Return the stable cache-key representation."""
        return {
            "method": "GET",
            "endpoint": self.endpoint,
            "parameters": self.parameters,
        }

    @property
    def request_hash(self) -> str:
        """Return a secret-free request identity."""
        return hashlib.sha256(
            canonical_json(self.canonical_payload).encode("utf-8")
        ).hexdigest()

    @property
    def url(self) -> str:
        """Return the exact request URL without credentials."""
        return f"{self.endpoint}?{urlencode(self.parameters)}"

    def public_payload(self) -> dict[str, object]:
        """Return a serializable request description for review."""
        return {
            "sequence": self.sequence,
            "offset": self.offset,
            "request_hash": self.request_hash,
            "method": "GET",
            "endpoint": self.endpoint,
            "parameters": self.parameters,
            "url_without_credentials": self.url,
            "execution_rule": (
                "First page."
                if self.sequence == 1
                else (
                    "Execute only if the previous page returned exactly "
                    f"{self.parameters['limit']} records."
                )
            ),
        }


def request_spec(config: BackfillConfig, sequence: int) -> RequestSpec:
    """Build one page request by one-based sequence number."""
    if not 1 <= sequence <= config.max_requests:
        raise ValueError("Request sequence exceeds the configured budget.")
    offset = (sequence - 1) * config.page_size
    parameters: dict[str, object] = {
        "wiki": WIKI,
        "conditions": build_conditions(config),
        "query": ",".join(config.projection),
        "limit": config.page_size,
        "offset": offset,
        "order": "date ASC, match2id ASC",
        "rawstreams": "false",
        "streamurls": "false",
    }
    return RequestSpec(
        sequence=sequence,
        offset=offset,
        endpoint=API_URL,
        parameters=parameters,
    )


@dataclass(frozen=True, slots=True)
class BackfillPlan:
    """Complete reviewable plan for a bounded acquisition run."""

    run_id: str
    config_hash: str
    requests: tuple[RequestSpec, ...]
    checkpoint_path: Path
    state_path: Path
    cache_directory: Path
    run_directory: Path
    expected_request_count_min: int
    expected_request_count_max: int

    def payload(self, config: BackfillConfig) -> dict[str, object]:
        """Return the complete secret-free plan."""
        return {
            "run_id": self.run_id,
            "config_hash": self.config_hash,
            "scope": config.scope_payload(),
            "endpoint": API_URL,
            "headers": {
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "Authorization": "Apikey <redacted-local-secret>",
                "User-Agent": USER_AGENT,
            },
            "expected_request_count": {
                "minimum": self.expected_request_count_min,
                "likely": "1-2",
                "hard_maximum": self.expected_request_count_max,
                "cache_hits_count_as_requests": False,
                "errors_count_against_budget": True,
                "automatic_retries": 0,
            },
            "checkpoint_path": str(self.checkpoint_path.resolve()),
            "state_path": str(self.state_path.resolve()),
            "cache_directory": str(self.cache_directory.resolve()),
            "run_directory": str(self.run_directory.resolve()),
            "requests": [
                request.public_payload()
                for request in self.requests
            ],
            "stop_conditions": [
                "Stop complete when result length is less than page size.",
                "Stop budget_exhausted when the final approved page is full.",
                "Stop failed on authentication, rate limit, or invalid envelope.",
            ],
            "patch_filter_policy": (
                "Configured patches are applied after normalization; no nested "
                "or top-level patch condition is added to API requests."
            ),
            "authenticated_requests_performed_by_plan": 0,
        }


def create_plan(config: BackfillConfig) -> BackfillPlan:
    """Create every possible request under the fixed budget."""
    requests = tuple(
        request_spec(config, sequence)
        for sequence in range(1, config.max_requests + 1)
    )
    return BackfillPlan(
        run_id=config.run_id,
        config_hash=config.config_hash,
        requests=requests,
        checkpoint_path=config.run_directory / "checkpoint.json",
        state_path=config.state_path,
        cache_directory=config.cache_directory,
        run_directory=config.run_directory,
        expected_request_count_min=1,
        expected_request_count_max=config.max_requests,
    )


def render_plan_markdown(payload: dict[str, object]) -> str:
    """Render a concise human-reviewable request plan."""
    scope = payload["scope"]
    count = payload["expected_request_count"]
    lines = [
        "# Liquipedia Historical Backfill Pilot Plan",
        "",
        f"**Run ID:** `{payload['run_id']}`",
        f"**Configuration hash:** `{payload['config_hash']}`",
        f"**Endpoint:** `{payload['endpoint']}`",
        f"**Date range:** `{scope['start_utc']}` to `{scope['end_utc']}`",
        f"**Tiers:** `{', '.join(scope['tiers'])}`",
        f"**Page size:** `{scope['page_size']}`",
        (
            "**Expected requests:** "
            f"`{count['likely']}`; hard maximum `{count['hard_maximum']}`"
        ),
        "**Authenticated requests made while generating this plan:** `0`",
        "",
        "## Local State",
        "",
        f"- Checkpoint: `{payload['checkpoint_path']}`",
        f"- SQLite state: `{payload['state_path']}`",
        f"- Cache: `{payload['cache_directory']}`",
        f"- Run artifacts: `{payload['run_directory']}`",
        "",
        "## Exact Request Sequence",
        "",
    ]
    for request in payload["requests"]:
        lines.extend(
            [
                f"### Request {request['sequence']}",
                "",
                f"- Offset: `{request['offset']}`",
                f"- Request hash: `{request['request_hash']}`",
                f"- Rule: {request['execution_rule']}",
                f"- URL without credentials: `{request['url_without_credentials']}`",
                "",
            ]
        )
    lines.extend(
        [
            "## Approval Boundary",
            "",
            "This plan is offline. Live execution requires an explicit command ",
            "and a separately approved request budget.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_plan(
    config: BackfillConfig,
    *,
    output_directory: Path,
) -> tuple[Path, Path]:
    """Write the deterministic JSON and Markdown plan artifacts."""
    plan = create_plan(config)
    payload = plan.payload(config)
    output_directory.mkdir(parents=True, exist_ok=True)
    json_path = output_directory / "plan.json"
    markdown_path = output_directory / "plan.md"
    json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(
        render_plan_markdown(payload),
        encoding="utf-8",
    )
    return json_path, markdown_path
