"""Offline planning and coordination for the Milestone 3.5 campaign.

This module deliberately has no HTTP execution surface. It composes the
validated partition planner, reads the existing SQLite ledger without
modifying it, verifies immutable cache entries, and publishes deterministic
campaign artifacts.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .cache import CacheError, CacheStore
from .config import BackfillConfig, canonical_json, utc_datetime
from .contract import (
    ACQUISITION_VERSION,
    API_URL,
    DEFAULT_HOURLY_REQUEST_LIMIT,
    DEFAULT_PAGE_SIZE,
    DEFAULT_REQUEST_INTERVAL_SECONDS,
    MATCH_FIELD_PROJECTION,
    WIKI,
)
from .envelope import ResponseEnvelopeError, response_record_count
from .planner import RequestSpec, create_plan, request_spec


CAMPAIGN_SCHEMA_VERSION = "liquipedia-history-campaign-v1"
CAMPAIGN_PLAN_SCHEMA_VERSION = "liquipedia-history-campaign-plan-v1"
CAMPAIGN_PREFLIGHT_SCHEMA_VERSION = "liquipedia-history-campaign-preflight-v1"
MILESTONE_REPORT_SCHEMA_VERSION = "milestone-report-v1"

FIXED_START_UTC = datetime(2022, 1, 1, tzinfo=UTC)
FIXED_END_UTC = datetime(2026, 7, 27, tzinfo=UTC)
PILOT_START_UTC = datetime(2026, 7, 1, tzinfo=UTC)
PILOT_END_UTC = FIXED_END_UTC

HISTORICAL_PARTITION_MAX_REQUESTS = 8
PILOT_PARTITION_MAX_REQUESTS = 4
CAMPAIGN_MAX_ADDITIONAL_REQUESTS = 100
EXPECTED_SUCCESSFUL_PAGES_MIN = 75
EXPECTED_SUCCESSFUL_PAGES_MAX = 95
EXPECTED_QUARTER_REQUESTS_MIN = 3
EXPECTED_QUARTER_REQUESTS_MAX = 6

PILOT_RUN_ID = "m3_20260701_20260727_0b40ae8811d6"
PILOT_CONFIG_HASH = (
    "0b40ae8811d6140590657c976ed350d44ab98c9d8289bde8c1d6a57221610258"
)

STAGE_B_COMMAND = (
    ".venv/bin/python scripts/plan_liquipedia_history_campaign.py \\\n"
    "  --check-partition-readiness 2022-Q1 && \\\n"
    ".venv/bin/python scripts/backfill_liquipedia_history.py \\\n"
    "  --start 2022-01-01T00:00:00Z \\\n"
    "  --end 2022-04-01T00:00:00Z \\\n"
    "  --tier 1 \\\n"
    "  --tier 2 \\\n"
    "  --page-size 100 \\\n"
    "  --max-requests 8 \\\n"
    "  --hourly-limit 54 \\\n"
    "  --request-interval-seconds 67 \\\n"
    "  --timeout-seconds 30 \\\n"
    "  --execute \\\n"
    "  --confirm-live-request-budget 8"
)


class CampaignError(ValueError):
    """Raised when a campaign plan or its local evidence is inconsistent."""


@dataclass(frozen=True, slots=True)
class PilotPageEvidence:
    """Expected immutable evidence for one accepted pilot page."""

    sequence: int
    request_hash: str
    response_sha256: str
    record_count: int
    is_final_page: bool

    def payload(self) -> dict[str, object]:
        """Return a deterministic JSON-compatible representation."""
        return {
            "sequence": self.sequence,
            "request_hash": self.request_hash,
            "response_sha256": self.response_sha256,
            "record_count": self.record_count,
            "is_final_page": self.is_final_page,
        }


VERIFIED_PILOT_PAGES = (
    PilotPageEvidence(
        sequence=1,
        request_hash=(
            "9f0b310bee831a6c921fb568cdb5e71a979ebe9832f3e22b29c4e2afa21371c6"
        ),
        response_sha256=(
            "bc5ab9f31516795b0b8011ac796ed266a5effc2c41a88957cea350a8f3dce06e"
        ),
        record_count=100,
        is_final_page=False,
    ),
    PilotPageEvidence(
        sequence=2,
        request_hash=(
            "0060ee0181d4b51e1c477ee857c41e08b8b9a0b40c8e04f65b924b47b98bfd66"
        ),
        response_sha256=(
            "2f15aa68c77c5b6b258ba9cd5063cbbfcfc480a94b92d65bc2437b382765ed81"
        ),
        record_count=8,
        is_final_page=True,
    ),
)


def _quarter_after(value: datetime) -> datetime:
    """Return the next UTC calendar-quarter boundary."""
    month_index = value.year * 12 + value.month - 1 + 3
    return datetime(
        month_index // 12,
        month_index % 12 + 1,
        1,
        tzinfo=UTC,
    )


def _quarter_id(value: datetime) -> str:
    """Return a readable stable quarter identifier."""
    return f"{value.year}-Q{((value.month - 1) // 3) + 1}"


def _sha256_json(payload: object) -> str:
    """Hash a JSON-compatible value using the project canonical form."""
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _display_path(path: Path, repository_root: Path) -> str:
    """Render repository-local paths without workstation-specific prefixes."""
    resolved = path.resolve()
    try:
        return resolved.relative_to(repository_root.resolve()).as_posix()
    except ValueError:
        return str(resolved)


@dataclass(frozen=True, slots=True)
class CampaignConfig:
    """Path-independent campaign contract plus local artifact roots."""

    repository_root: Path
    start_utc: datetime = FIXED_START_UTC
    end_utc: datetime = FIXED_END_UTC
    pilot_start_utc: datetime = PILOT_START_UTC
    pilot_end_utc: datetime = PILOT_END_UTC
    tiers: tuple[str, ...] = ("1", "2")
    patches: tuple[str, ...] = ()
    page_size: int = DEFAULT_PAGE_SIZE
    historical_partition_max_requests: int = HISTORICAL_PARTITION_MAX_REQUESTS
    pilot_partition_max_requests: int = PILOT_PARTITION_MAX_REQUESTS
    max_additional_requests: int = CAMPAIGN_MAX_ADDITIONAL_REQUESTS
    hourly_request_limit: int = DEFAULT_HOURLY_REQUEST_LIMIT
    request_interval_seconds: float = DEFAULT_REQUEST_INTERVAL_SECONDS
    projection: tuple[str, ...] = MATCH_FIELD_PROJECTION
    expected_successful_pages_min: int = EXPECTED_SUCCESSFUL_PAGES_MIN
    expected_successful_pages_max: int = EXPECTED_SUCCESSFUL_PAGES_MAX
    pilot_required_pages: tuple[PilotPageEvidence, ...] = VERIFIED_PILOT_PAGES

    def __post_init__(self) -> None:
        start = utc_datetime(self.start_utc)
        end = utc_datetime(self.end_utc)
        pilot_start = utc_datetime(self.pilot_start_utc)
        pilot_end = utc_datetime(self.pilot_end_utc)
        tiers = tuple(sorted({str(value).strip() for value in self.tiers}))
        patches = tuple(sorted({str(value).strip() for value in self.patches}))

        if start >= pilot_start or pilot_start >= pilot_end or pilot_end != end:
            raise ValueError(
                "Campaign bounds must end with one non-empty pilot partition."
            )
        if start.day != 1 or start.month not in {1, 4, 7, 10}:
            raise ValueError("Campaign start must be a calendar-quarter boundary.")
        if pilot_start.day != 1 or pilot_start.month not in {1, 4, 7, 10}:
            raise ValueError("Pilot start must be a calendar-quarter boundary.")
        if not tiers or any(not value for value in tiers):
            raise ValueError("At least one non-empty tier is required.")
        if not 1 <= self.page_size <= 1000:
            raise ValueError("Page size must be between 1 and 1000.")
        if self.historical_partition_max_requests < 1:
            raise ValueError("Historical partition budget must be positive.")
        if self.pilot_partition_max_requests < 1:
            raise ValueError("Pilot partition budget must be positive.")
        if self.max_additional_requests < 1:
            raise ValueError("Campaign request budget must be positive.")
        if not 1 <= self.hourly_request_limit <= 60:
            raise ValueError("Hourly request limit must be between 1 and 60.")
        if (
            self.request_interval_seconds
            < 3600 / self.hourly_request_limit
        ):
            raise ValueError("Request interval is too short for the hourly limit.")
        if self.expected_successful_pages_min < 0 or (
            self.expected_successful_pages_min
            > self.expected_successful_pages_max
        ):
            raise ValueError("Expected page range is invalid.")
        if not self.projection:
            raise ValueError("Projection must not be empty.")
        if not self.pilot_required_pages:
            raise ValueError("Pilot cache evidence must not be empty.")

        sequences = [page.sequence for page in self.pilot_required_pages]
        if sequences != list(range(1, len(sequences) + 1)):
            raise ValueError("Pilot evidence sequences must be contiguous.")
        if not self.pilot_required_pages[-1].is_final_page:
            raise ValueError("Pilot evidence must end with a terminal page.")
        if any(page.is_final_page for page in self.pilot_required_pages[:-1]):
            raise ValueError("Only the final pilot evidence page may be terminal.")

        object.__setattr__(self, "repository_root", self.repository_root.resolve())
        object.__setattr__(self, "start_utc", start)
        object.__setattr__(self, "end_utc", end)
        object.__setattr__(self, "pilot_start_utc", pilot_start)
        object.__setattr__(self, "pilot_end_utc", pilot_end)
        object.__setattr__(self, "tiers", tiers)
        object.__setattr__(self, "patches", patches)

    @property
    def raw_root(self) -> Path:
        """Return the existing acquisition raw root."""
        return self.repository_root / "data" / "raw" / "liquipedia" / "backfill"

    @property
    def run_root(self) -> Path:
        """Return the existing partition-run root."""
        return self.repository_root / "data" / "backfill" / "runs"

    @property
    def partition_plan_root(self) -> Path:
        """Return the existing individual partition-plan root."""
        return self.repository_root / "data" / "backfill" / "plans"

    @property
    def campaign_root(self) -> Path:
        """Return the Stage A generated campaign-artifact root."""
        return self.repository_root / "data" / "backfill" / "campaigns"

    @property
    def state_path(self) -> Path:
        """Return the shared existing SQLite request ledger."""
        return self.raw_root / "state.sqlite3"

    def identity_payload(self) -> dict[str, object]:
        """Return path-independent immutable campaign configuration."""
        return {
            "campaign_schema_version": CAMPAIGN_SCHEMA_VERSION,
            "acquisition_version": ACQUISITION_VERSION,
            "source": {
                "endpoint": API_URL,
                "wiki": WIKI,
                "official_api_only": True,
                "html_scraping": False,
            },
            "scope": {
                "start_utc_inclusive": self.start_utc.isoformat(),
                "end_utc_exclusive": self.end_utc.isoformat(),
                "tiers": list(self.tiers),
                "finished_matches_only": True,
                "patches": list(self.patches),
                "patch_filter_stage": "normalized_training_dataset",
            },
            "partitioning": {
                "strategy": "calendar_quarter_half_open",
                "historical_partition_max_requests": (
                    self.historical_partition_max_requests
                ),
                "pilot_start_utc": self.pilot_start_utc.isoformat(),
                "pilot_end_utc": self.pilot_end_utc.isoformat(),
                "pilot_partition_max_requests": (
                    self.pilot_partition_max_requests
                ),
                "pilot_execution_policy": "verified_cache_only",
            },
            "request_contract": {
                "page_size": self.page_size,
                "ordering": "date ASC, match2id ASC",
                "projection": list(self.projection),
                "rawstreams": "false",
                "streamurls": "false",
                "automatic_retries": 0,
                "hourly_request_limit": self.hourly_request_limit,
                "request_interval_seconds": self.request_interval_seconds,
            },
            "campaign_request_budget": {
                "max_additional_http_attempts": self.max_additional_requests,
                "all_http_outcomes_count": True,
                "cache_hits_count": False,
                "pilot_historical_attempts_count_against_expansion": False,
            },
            "request_estimate": {
                "successful_pages_min": self.expected_successful_pages_min,
                "successful_pages_max": self.expected_successful_pages_max,
                "planning_range_not_success_gate": True,
            },
            "pilot_request_identity": {
                "run_id": PILOT_RUN_ID,
                "config_hash": PILOT_CONFIG_HASH,
                "required_request_hashes": [
                    page.request_hash
                    for page in self.pilot_required_pages
                ],
                "terminal_sequence": self.pilot_required_pages[-1].sequence,
            },
        }

    @property
    def config_fingerprint(self) -> str:
        """Return the path-independent immutable configuration fingerprint."""
        return _sha256_json(self.identity_payload())

    @property
    def campaign_id(self) -> str:
        """Return a readable deterministic campaign identity."""
        return (
            f"m3_5_{self.start_utc:%Y%m%d}_{self.end_utc:%Y%m%d}_"
            f"{self.config_fingerprint[:12]}"
        )

    @property
    def output_directory(self) -> Path:
        """Return the deterministic generated campaign directory."""
        return self.campaign_root / self.campaign_id


@dataclass(frozen=True, slots=True)
class CampaignPartition:
    """One ordered logical partition backed by a standard BackfillConfig."""

    ordinal: int
    partition_id: str
    kind: str
    config: BackfillConfig
    campaign_network_budget: int
    expected_requests_min: int
    expected_requests_max: int

    @property
    def is_pilot(self) -> bool:
        """Return whether this is the cache-only Milestone 3 pilot."""
        return self.kind == "cached_pilot"

    @property
    def request_specs(self) -> tuple[RequestSpec, ...]:
        """Delegate exact request construction to the validated planner."""
        return create_plan(self.config).requests


@dataclass(frozen=True, slots=True)
class CampaignPlan:
    """Immutable campaign configuration and exact conditional request plan."""

    config: CampaignConfig
    partitions: tuple[CampaignPartition, ...]
    plan_fingerprint: str

    @property
    def total_request_specs(self) -> int:
        """Return all conditional request slots across all partitions."""
        return sum(len(partition.request_specs) for partition in self.partitions)

    @property
    def new_partition_request_specs(self) -> int:
        """Return conditional slots excluding the cached pilot."""
        return sum(
            len(partition.request_specs)
            for partition in self.partitions
            if not partition.is_pilot
        )

    def payload(self) -> dict[str, object]:
        """Return the complete public, credential-free campaign plan."""
        config = self.config
        partition_payloads: list[dict[str, object]] = []
        for partition in self.partitions:
            request_payloads: list[dict[str, object]] = []
            for request in partition.request_specs:
                cache_directory = (
                    partition.config.cache_directory / request.request_hash
                )
                request_payload = request.public_payload()
                request_payload["cache_paths"] = {
                    "directory": _display_path(
                        cache_directory,
                        config.repository_root,
                    ),
                    "response": _display_path(
                        cache_directory / "response.json",
                        config.repository_root,
                    ),
                    "metadata": _display_path(
                        cache_directory / "metadata.json",
                        config.repository_root,
                    ),
                }
                request_payloads.append(request_payload)

            partition_payloads.append(
                {
                    "ordinal": partition.ordinal,
                    "partition_id": partition.partition_id,
                    "kind": partition.kind,
                    "start_utc_inclusive": (
                        partition.config.start_utc.isoformat()
                    ),
                    "end_utc_exclusive": partition.config.end_utc.isoformat(),
                    "run_id": partition.config.run_id,
                    "config_hash": partition.config.config_hash,
                    "request_slots": len(partition.request_specs),
                    "partition_max_requests": partition.config.max_requests,
                    "campaign_network_budget": partition.campaign_network_budget,
                    "expected_requests": {
                        "minimum": partition.expected_requests_min,
                        "maximum": partition.expected_requests_max,
                    },
                    "execution_policy": (
                        "verified_cache_only"
                        if partition.is_pilot
                        else "separate_explicit_live_approval_required"
                    ),
                    "paths": {
                        "checkpoint": _display_path(
                            partition.config.run_directory / "checkpoint.json",
                            config.repository_root,
                        ),
                        "run_directory": _display_path(
                            partition.config.run_directory,
                            config.repository_root,
                        ),
                        "legacy_partition_plan": _display_path(
                            (
                                config.partition_plan_root
                                / partition.config.run_id
                                / "plan.json"
                            ),
                            config.repository_root,
                        ),
                        "cache_directory": _display_path(
                            partition.config.cache_directory,
                            config.repository_root,
                        ),
                    },
                    "requests": request_payloads,
                }
            )

        return {
            "campaign_plan_schema_version": CAMPAIGN_PLAN_SCHEMA_VERSION,
            "campaign_id": config.campaign_id,
            "configuration_fingerprint": config.config_fingerprint,
            "campaign_plan_fingerprint": self.plan_fingerprint,
            "configuration": config.identity_payload(),
            "path_base": "repository_root",
            "paths": {
                "campaign_directory": _display_path(
                    config.output_directory,
                    config.repository_root,
                ),
                "sqlite_request_ledger": _display_path(
                    config.state_path,
                    config.repository_root,
                ),
                "global_cache": _display_path(
                    config.raw_root / "cache",
                    config.repository_root,
                ),
                "partition_runs": _display_path(
                    config.run_root,
                    config.repository_root,
                ),
            },
            "request_accounting": {
                "logical_partitions": len(self.partitions),
                "new_historical_partitions": sum(
                    not partition.is_pilot
                    for partition in self.partitions
                ),
                "cached_pilot_partitions": sum(
                    partition.is_pilot
                    for partition in self.partitions
                ),
                "conditional_request_specs_total": self.total_request_specs,
                "conditional_request_specs_new_partitions": (
                    self.new_partition_request_specs
                ),
                "conditional_request_specs_pilot": (
                    self.total_request_specs
                    - self.new_partition_request_specs
                ),
                "max_additional_http_attempts": (
                    config.max_additional_requests
                ),
                "expected_successful_pages": {
                    "minimum": config.expected_successful_pages_min,
                    "maximum": config.expected_successful_pages_max,
                },
                "pilot_additional_http_budget": 0,
                "automatic_retries": 0,
            },
            "partitions": partition_payloads,
            "resume_policy": {
                "state_source": "existing_sqlite_ledger_and_verified_cache",
                "campaign_tables_added": False,
                "first_incomplete_partition_wins": True,
                "failed_or_budget_exhausted_blocks": True,
                "unresolved_started_attempt_blocks": True,
                "out_of_order_progress_blocks": True,
                "partition_launch_requires_remaining_campaign_budget": True,
            },
            "stage_b": {
                "partition_id": "2022-Q1",
                "requires_separate_approval": True,
                "proposed_command_not_executed": STAGE_B_COMMAND,
            },
            "authenticated_requests_performed_by_planning": 0,
        }


def _partition_config(
    campaign: CampaignConfig,
    *,
    start_utc: datetime,
    end_utc: datetime,
    max_requests: int,
) -> BackfillConfig:
    """Create one partition using the existing acquisition configuration."""
    return BackfillConfig(
        start_utc=start_utc,
        end_utc=end_utc,
        tiers=campaign.tiers,
        patches=campaign.patches,
        page_size=campaign.page_size,
        max_requests=max_requests,
        hourly_request_limit=campaign.hourly_request_limit,
        request_interval_seconds=campaign.request_interval_seconds,
        raw_root=campaign.raw_root,
        run_root=campaign.run_root,
        normalized_output_root=(
            campaign.repository_root / "data" / "processed" / "liquipedia"
        ),
        projection=campaign.projection,
    )


def create_partitions(
    campaign: CampaignConfig,
) -> tuple[CampaignPartition, ...]:
    """Create contiguous full quarters followed by the exact cached pilot."""
    partitions: list[CampaignPartition] = []
    cursor = campaign.start_utc
    ordinal = 1
    while cursor < campaign.pilot_start_utc:
        end = _quarter_after(cursor)
        if end > campaign.pilot_start_utc:
            raise CampaignError(
                "Full-quarter partitions do not align with the pilot start."
            )
        partitions.append(
            CampaignPartition(
                ordinal=ordinal,
                partition_id=_quarter_id(cursor),
                kind="historical_quarter",
                config=_partition_config(
                    campaign,
                    start_utc=cursor,
                    end_utc=end,
                    max_requests=(
                        campaign.historical_partition_max_requests
                    ),
                ),
                campaign_network_budget=(
                    campaign.historical_partition_max_requests
                ),
                expected_requests_min=EXPECTED_QUARTER_REQUESTS_MIN,
                expected_requests_max=EXPECTED_QUARTER_REQUESTS_MAX,
            )
        )
        ordinal += 1
        cursor = end

    pilot = CampaignPartition(
        ordinal=ordinal,
        partition_id="2026-07-pilot",
        kind="cached_pilot",
        config=_partition_config(
            campaign,
            start_utc=campaign.pilot_start_utc,
            end_utc=campaign.pilot_end_utc,
            max_requests=campaign.pilot_partition_max_requests,
        ),
        campaign_network_budget=0,
        expected_requests_min=0,
        expected_requests_max=0,
    )
    partitions.append(pilot)

    for previous, current in zip(partitions, partitions[1:], strict=False):
        if previous.config.end_utc != current.config.start_utc:
            raise CampaignError("Campaign partitions contain a gap or overlap.")
    if partitions[0].config.start_utc != campaign.start_utc:
        raise CampaignError("Campaign partitions do not start at scope start.")
    if partitions[-1].config.end_utc != campaign.end_utc:
        raise CampaignError("Campaign partitions do not end at scope end.")

    pilot_request_hashes = tuple(
        request.request_hash
        for request in pilot.request_specs[:len(campaign.pilot_required_pages)]
    )
    expected_pilot_hashes = tuple(
        page.request_hash
        for page in campaign.pilot_required_pages
    )
    if pilot_request_hashes != expected_pilot_hashes:
        raise CampaignError(
            "Pilot evidence does not match the validated request planner."
        )

    if (
        campaign.start_utc == FIXED_START_UTC
        and campaign.end_utc == FIXED_END_UTC
        and len(partitions) != 19
    ):
        raise CampaignError("The fixed campaign must contain 19 partitions.")
    if (
        pilot.config.run_id != PILOT_RUN_ID
        or pilot.config.config_hash != PILOT_CONFIG_HASH
    ):
        raise CampaignError("The fixed pilot identity has changed.")
    return tuple(partitions)


def _semantic_plan_payload(
    campaign: CampaignConfig,
    partitions: tuple[CampaignPartition, ...],
) -> dict[str, object]:
    """Return the path-independent request plan used for fingerprinting."""
    return {
        "campaign_plan_schema_version": CAMPAIGN_PLAN_SCHEMA_VERSION,
        "configuration_fingerprint": campaign.config_fingerprint,
        "partitions": [
            {
                "ordinal": partition.ordinal,
                "partition_id": partition.partition_id,
                "kind": partition.kind,
                "run_id": partition.config.run_id,
                "config_hash": partition.config.config_hash,
                "campaign_network_budget": partition.campaign_network_budget,
                "expected_requests_min": partition.expected_requests_min,
                "expected_requests_max": partition.expected_requests_max,
                "requests": [
                    {
                        "sequence": request.sequence,
                        "offset": request.offset,
                        "request_hash": request.request_hash,
                        "canonical_request": request.canonical_payload,
                    }
                    for request in partition.request_specs
                ],
            }
            for partition in partitions
        ],
    }


def create_campaign_plan(campaign: CampaignConfig) -> CampaignPlan:
    """Create the complete immutable campaign plan without local I/O."""
    partitions = create_partitions(campaign)
    request_hashes = [
        request.request_hash
        for partition in partitions
        for request in partition.request_specs
    ]
    if len(request_hashes) != len(set(request_hashes)):
        raise CampaignError("Campaign request hashes must be globally unique.")
    semantic_payload = _semantic_plan_payload(campaign, partitions)
    return CampaignPlan(
        config=campaign,
        partitions=partitions,
        plan_fingerprint=_sha256_json(semantic_payload),
    )


@dataclass(frozen=True, slots=True)
class PartitionRuntimeState:
    """Read-only derived status for one planned partition."""

    ordinal: int
    partition_id: str
    kind: str
    run_id: str
    ledger_status: str
    effective_status: str
    request_count: int
    cache_hit_count: int
    records_seen: int
    accepted_page_count: int
    next_sequence: int
    next_offset: int
    remaining_request_ceiling: int
    verified_pages: tuple[dict[str, object], ...]
    next_request_cached: bool
    blocking_reason: str | None

    def semantic_payload(self) -> dict[str, object]:
        """Return mutable state without timestamps or workstation paths."""
        return {
            "ordinal": self.ordinal,
            "partition_id": self.partition_id,
            "kind": self.kind,
            "run_id": self.run_id,
            "ledger_status": self.ledger_status,
            "effective_status": self.effective_status,
            "request_count": self.request_count,
            "cache_hit_count": self.cache_hit_count,
            "records_seen": self.records_seen,
            "accepted_page_count": self.accepted_page_count,
            "next_sequence": self.next_sequence,
            "next_offset": self.next_offset,
            "remaining_request_ceiling": self.remaining_request_ceiling,
            "verified_pages": list(self.verified_pages),
            "next_request_cached": self.next_request_cached,
            "blocking_reason": self.blocking_reason,
        }


def _open_read_only_state(
    path: Path,
) -> sqlite3.Connection | None:
    """Open the existing ledger read-only without creating any local state."""
    resolved = path.resolve()
    if not resolved.is_file():
        return None
    connection = sqlite3.connect(
        f"{resolved.as_uri()}?mode=ro",
        uri=True,
    )
    connection.row_factory = sqlite3.Row
    return connection


def ledger_request_row_count(path: Path) -> int:
    """Count existing attempts without creating or modifying the ledger."""
    connection = _open_read_only_state(path)
    if connection is None:
        return 0
    try:
        row = connection.execute(
            "SELECT COUNT(*) AS request_count FROM requests"
        ).fetchone()
        return int(row["request_count"])
    except sqlite3.DatabaseError as error:
        raise CampaignError(f"Cannot read request ledger: {error}") from error
    finally:
        connection.close()


def _rows(
    connection: sqlite3.Connection,
    query: str,
    parameters: tuple[object, ...],
) -> list[dict[str, Any]]:
    """Return deterministic SQLite query rows as ordinary dictionaries."""
    return [
        dict(row)
        for row in connection.execute(query, parameters).fetchall()
    ]


def _future_cache_network_ceiling(
    partition: CampaignPartition,
    *,
    next_sequence: int,
    remaining_attempt_budget: int,
) -> tuple[bool, int]:
    """Return next-page cache state and worst-case uncached attempts.

    Every existing cache entry is checksum- and envelope-verified. Missing
    pages are conservatively assumed full until a verified cached terminal
    page proves traversal ends.
    """
    cache = CacheStore(partition.config.cache_directory)
    next_request_cached = False
    missing_pages = 0
    for sequence in range(
        next_sequence,
        partition.config.max_requests + 1,
    ):
        spec = request_spec(partition.config, sequence)
        try:
            cached = cache.get(spec)
        except (CacheError, OSError, ValueError) as error:
            raise CampaignError(
                f"{partition.partition_id}: future cache page is invalid: {error}"
            ) from error
        if cached is None:
            missing_pages += 1
            continue
        try:
            cached_count = response_record_count(cached.body)
        except ResponseEnvelopeError as error:
            raise CampaignError(
                f"{partition.partition_id}: future cached response is invalid."
            ) from error
        if cached_count != cached.record_count:
            raise CampaignError(
                f"{partition.partition_id}: future cache count mismatch."
            )
        if sequence == next_sequence:
            next_request_cached = True
        if cached_count < partition.config.page_size:
            break
    return (
        next_request_cached,
        min(missing_pages, remaining_attempt_budget),
    )


def _inspect_partition(
    partition: CampaignPartition,
    *,
    connection: sqlite3.Connection | None,
) -> PartitionRuntimeState:
    """Validate one partition's ledger and accepted cache evidence."""
    config = partition.config
    if connection is None:
        run_row = None
    else:
        try:
            run = connection.execute(
                "SELECT * FROM runs WHERE run_id = ?",
                (config.run_id,),
            ).fetchone()
        except sqlite3.DatabaseError as error:
            raise CampaignError(f"Cannot read run ledger: {error}") from error
        run_row = dict(run) if run is not None else None

    if run_row is None:
        next_cached, network_ceiling = _future_cache_network_ceiling(
            partition,
            next_sequence=1,
            remaining_attempt_budget=config.max_requests,
        )
        return PartitionRuntimeState(
            ordinal=partition.ordinal,
            partition_id=partition.partition_id,
            kind=partition.kind,
            run_id=config.run_id,
            ledger_status="not_started",
            effective_status="pending",
            request_count=0,
            cache_hit_count=0,
            records_seen=0,
            accepted_page_count=0,
            next_sequence=1,
            next_offset=0,
            remaining_request_ceiling=network_ceiling,
            verified_pages=(),
            next_request_cached=next_cached,
            blocking_reason=None,
        )

    if run_row["config_hash"] != config.config_hash:
        raise CampaignError(
            f"{partition.partition_id}: ledger configuration hash mismatch."
        )
    if run_row["config_json"] != canonical_json(config.scope_payload()):
        raise CampaignError(
            f"{partition.partition_id}: ledger configuration payload mismatch."
        )

    requests = _rows(
        connection,  # type: ignore[arg-type]
        "SELECT * FROM requests WHERE run_id = ? ORDER BY request_id",
        (config.run_id,),
    )
    pages = _rows(
        connection,  # type: ignore[arg-type]
        "SELECT * FROM pages WHERE run_id = ? ORDER BY sequence",
        (config.run_id,),
    )
    request_count = int(run_row["request_count"])
    if request_count != len(requests):
        raise CampaignError(
            f"{partition.partition_id}: request count does not reconcile."
        )
    if request_count > config.max_requests:
        raise CampaignError(
            f"{partition.partition_id}: partition request budget was exceeded."
        )

    specs = {
        request.sequence: request
        for request in partition.request_specs
    }
    unresolved = False
    unsuccessful_outcomes: list[str] = []
    for attempt in requests:
        sequence = int(attempt["sequence"])
        spec = specs.get(sequence)
        if spec is None:
            raise CampaignError(
                f"{partition.partition_id}: attempt is outside the request plan."
            )
        if (
            attempt["request_hash"] != spec.request_hash
            or int(attempt["offset_value"]) != spec.offset
        ):
            raise CampaignError(
                f"{partition.partition_id}: request ledger conflicts with plan."
            )
        outcome = str(attempt["outcome"])
        if outcome not in {
            "started",
            "success",
            "http_error",
            "invalid_response",
        }:
            raise CampaignError(
                f"{partition.partition_id}: unsupported request outcome."
            )
        if outcome == "started":
            unresolved = True
        elif outcome in {"http_error", "invalid_response"}:
            unsuccessful_outcomes.append(outcome)
        elif outcome == "success":
            try:
                cached_attempt = CacheStore(
                    config.cache_directory
                ).get(spec)
            except (CacheError, OSError, ValueError) as error:
                raise CampaignError(
                    f"{partition.partition_id}: successful attempt cache "
                    f"verification failed: {error}"
                ) from error
            if cached_attempt is None:
                raise CampaignError(
                    f"{partition.partition_id}: successful attempt lacks cache."
                )
            if (
                int(attempt["http_status"]) != 200
                or attempt["response_sha256"]
                != cached_attempt.response_sha256
                or attempt["response_path"]
                != str(cached_attempt.response_path.resolve())
                or int(attempt["record_count"])
                != cached_attempt.record_count
            ):
                raise CampaignError(
                    f"{partition.partition_id}: successful attempt metadata "
                    "does not reconcile with cache."
                )

    expected_sequences = list(range(1, len(pages) + 1))
    if [int(page["sequence"]) for page in pages] != expected_sequences:
        raise CampaignError(
            f"{partition.partition_id}: accepted pages are not contiguous."
        )

    cache = CacheStore(config.cache_directory)
    verified_pages: list[dict[str, object]] = []
    for page in pages:
        sequence = int(page["sequence"])
        spec = specs[sequence]
        if (
            page["request_hash"] != spec.request_hash
            or int(page["offset_value"]) != spec.offset
        ):
            raise CampaignError(
                f"{partition.partition_id}: accepted page conflicts with plan."
            )
        try:
            cached = cache.get(spec)
        except (CacheError, OSError, ValueError) as error:
            raise CampaignError(
                f"{partition.partition_id}: cache verification failed: {error}"
            ) from error
        if cached is None:
            raise CampaignError(
                f"{partition.partition_id}: accepted cache page is missing."
            )
        try:
            body_count = response_record_count(cached.body)
        except ResponseEnvelopeError as error:
            raise CampaignError(
                f"{partition.partition_id}: cached response is invalid: {error}"
            ) from error
        is_final = body_count < config.page_size
        expected_path = str(cached.response_path.resolve())
        if (
            page["response_sha256"] != cached.response_sha256
            or page["response_path"] != expected_path
            or int(page["record_count"]) != body_count
            or int(page["is_final_page"]) != int(is_final)
        ):
            raise CampaignError(
                f"{partition.partition_id}: cache and ledger page disagree."
            )
        if str(page["source_kind"]) == "network" and not any(
            attempt["outcome"] == "success"
            and int(attempt["sequence"]) == sequence
            and attempt["request_hash"] == spec.request_hash
            and attempt["response_sha256"] == cached.response_sha256
            and int(attempt["record_count"]) == body_count
            for attempt in requests
        ):
            raise CampaignError(
                f"{partition.partition_id}: network page lacks a successful "
                "request-ledger entry."
            )
        verified_pages.append(
            {
                "sequence": sequence,
                "request_hash": spec.request_hash,
                "response_sha256": cached.response_sha256,
                "record_count": body_count,
                "is_final_page": is_final,
                "source_kind": str(page["source_kind"]),
            }
        )

    if any(
        bool(page["is_final_page"])
        for page in verified_pages[:-1]
    ):
        raise CampaignError(
            f"{partition.partition_id}: terminal page is not last."
        )

    records_seen = int(run_row["records_seen"])
    if records_seen != sum(
        int(page["record_count"])
        for page in verified_pages
    ):
        raise CampaignError(
            f"{partition.partition_id}: record count does not reconcile."
        )
    expected_next_sequence = len(pages) + 1
    expected_next_offset = len(pages) * config.page_size
    if (
        int(run_row["next_sequence"]) != expected_next_sequence
        or int(run_row["next_offset"]) != expected_next_offset
    ):
        raise CampaignError(
            f"{partition.partition_id}: resume cursor conflicts with pages."
        )

    ledger_status = str(run_row["status"])
    allowed_statuses = {
        "planned",
        "running",
        "complete",
        "budget_exhausted",
        "failed",
    }
    if ledger_status not in allowed_statuses:
        raise CampaignError(
            f"{partition.partition_id}: unsupported ledger status."
        )
    last_is_final = bool(verified_pages[-1]["is_final_page"]) if pages else False
    if ledger_status == "complete" and (not pages or not last_is_final):
        raise CampaignError(
            f"{partition.partition_id}: complete run lacks a terminal page."
        )
    if ledger_status != "complete" and last_is_final:
        raise CampaignError(
            f"{partition.partition_id}: terminal page lacks complete status."
        )
    if ledger_status == "planned" and (
        pages or requests or records_seen
    ):
        raise CampaignError(
            f"{partition.partition_id}: planned run contains execution state."
        )

    next_sequence = expected_next_sequence
    remaining_attempt_budget = max(0, config.max_requests - request_count)
    if ledger_status == "complete":
        next_request_cached = False
        remaining_ceiling = 0
    else:
        next_request_cached, remaining_ceiling = (
            _future_cache_network_ceiling(
                partition,
                next_sequence=next_sequence,
                remaining_attempt_budget=remaining_attempt_budget,
            )
        )

    blocking_reason = None
    if unresolved:
        blocking_reason = "unresolved_started_request"
    elif ledger_status == "failed":
        blocking_reason = "partition_failed"
    elif ledger_status == "budget_exhausted":
        blocking_reason = "partition_budget_exhausted"
    elif unsuccessful_outcomes:
        blocking_reason = (
            "unreviewed_unsuccessful_request:"
            + ",".join(sorted(set(unsuccessful_outcomes)))
        )

    effective_status = {
        "planned": "pending",
        "running": "running",
        "complete": "complete",
        "failed": "blocked",
        "budget_exhausted": "blocked",
    }[ledger_status]
    if unresolved:
        effective_status = "blocked"

    return PartitionRuntimeState(
        ordinal=partition.ordinal,
        partition_id=partition.partition_id,
        kind=partition.kind,
        run_id=config.run_id,
        ledger_status=ledger_status,
        effective_status=effective_status,
        request_count=request_count,
        cache_hit_count=int(run_row["cache_hit_count"]),
        records_seen=records_seen,
        accepted_page_count=len(pages),
        next_sequence=next_sequence,
        next_offset=expected_next_offset,
        remaining_request_ceiling=remaining_ceiling,
        verified_pages=tuple(verified_pages),
        next_request_cached=next_request_cached,
        blocking_reason=blocking_reason,
    )


def _verify_pilot(
    campaign: CampaignConfig,
    partition: CampaignPartition,
    state: PartitionRuntimeState,
) -> dict[str, object]:
    """Require the exact completed pilot ledger and immutable cache chain."""
    if (
        partition.config.run_id != PILOT_RUN_ID
        or partition.config.config_hash != PILOT_CONFIG_HASH
    ):
        raise CampaignError("Validated pilot identity changed.")
    if state.ledger_status != "complete":
        raise CampaignError("Cached pilot run is not complete in SQLite.")
    if state.request_count != len(campaign.pilot_required_pages):
        raise CampaignError("Cached pilot attempt count changed.")
    if state.accepted_page_count != len(campaign.pilot_required_pages):
        raise CampaignError("Cached pilot accepted-page count changed.")

    actual = tuple(
        (
            int(page["sequence"]),
            str(page["request_hash"]),
            str(page["response_sha256"]),
            int(page["record_count"]),
            bool(page["is_final_page"]),
        )
        for page in state.verified_pages
    )
    expected = tuple(
        (
            page.sequence,
            page.request_hash,
            page.response_sha256,
            page.record_count,
            page.is_final_page,
        )
        for page in campaign.pilot_required_pages
    )
    if actual != expected:
        raise CampaignError("Cached pilot evidence differs from the baseline.")
    return {
        "verified": True,
        "run_id": partition.config.run_id,
        "config_hash": partition.config.config_hash,
        "ledger_status": state.ledger_status,
        "historical_http_attempts": state.request_count,
        "m3_5_additional_http_budget": 0,
        "records": state.records_seen,
        "verified_cached_pages": list(state.verified_pages),
        "unused_conditional_requests": [
            {
                "sequence": request.sequence,
                "offset": request.offset,
                "request_hash": request.request_hash,
                "reason": "not_required_after_terminal_cached_page",
            }
            for request in partition.request_specs[
                len(campaign.pilot_required_pages):
            ]
        ],
        "network_request_required": False,
    }


def resolve_resume(
    campaign: CampaignConfig,
    states: tuple[PartitionRuntimeState, ...],
) -> dict[str, object]:
    """Resolve one deterministic next action and enforce campaign budget."""
    new_states = tuple(state for state in states if state.kind != "cached_pilot")
    additional_attempts_used = sum(state.request_count for state in new_states)
    remaining_budget = campaign.max_additional_requests - additional_attempts_used
    if remaining_budget < 0:
        return {
            "campaign_status": "blocked",
            "blocking_reason": "campaign_request_budget_exceeded",
            "next_partition_id": None,
            "additional_attempts_used": additional_attempts_used,
            "additional_attempts_remaining": remaining_budget,
        }

    blocking = [
        state
        for state in new_states
        if state.blocking_reason is not None
    ]
    if blocking:
        first = blocking[0]
        return {
            "campaign_status": "blocked",
            "blocking_reason": (
                f"{first.partition_id}:{first.blocking_reason}"
            ),
            "next_partition_id": None,
            "additional_attempts_used": additional_attempts_used,
            "additional_attempts_remaining": remaining_budget,
        }

    running = [
        state
        for state in new_states
        if state.effective_status == "running"
    ]
    if len(running) > 1:
        return {
            "campaign_status": "blocked",
            "blocking_reason": "multiple_running_partitions",
            "next_partition_id": None,
            "additional_attempts_used": additional_attempts_used,
            "additional_attempts_remaining": remaining_budget,
        }

    first_incomplete_index = next(
        (
            index
            for index, state in enumerate(new_states)
            if state.effective_status != "complete"
        ),
        len(new_states),
    )
    if any(
        state.effective_status in {"complete", "running"}
        for state in new_states[first_incomplete_index + 1:]
    ):
        return {
            "campaign_status": "blocked",
            "blocking_reason": "out_of_order_partition_progress",
            "next_partition_id": None,
            "additional_attempts_used": additional_attempts_used,
            "additional_attempts_remaining": remaining_budget,
        }

    if first_incomplete_index == len(new_states):
        return {
            "campaign_status": "complete",
            "blocking_reason": None,
            "next_partition_id": None,
            "additional_attempts_used": additional_attempts_used,
            "additional_attempts_remaining": remaining_budget,
        }

    next_state = new_states[first_incomplete_index]
    required_ceiling = next_state.remaining_request_ceiling
    if remaining_budget < required_ceiling:
        return {
            "campaign_status": "blocked",
            "blocking_reason": "insufficient_campaign_budget_for_partition",
            "next_partition_id": next_state.partition_id,
            "next_run_id": next_state.run_id,
            "next_sequence": next_state.next_sequence,
            "next_offset": next_state.next_offset,
            "partition_remaining_request_ceiling": required_ceiling,
            "additional_attempts_used": additional_attempts_used,
            "additional_attempts_remaining": remaining_budget,
        }

    status = (
        "ready_for_canary"
        if next_state.partition_id == "2022-Q1"
        and next_state.next_sequence == 1
        else "ready_to_resume"
    )
    return {
        "campaign_status": status,
        "blocking_reason": None,
        "next_partition_id": next_state.partition_id,
        "next_run_id": next_state.run_id,
        "next_sequence": next_state.next_sequence,
        "next_offset": next_state.next_offset,
        "next_request_cached": next_state.next_request_cached,
        "partition_remaining_request_ceiling": required_ceiling,
        "additional_attempts_used": additional_attempts_used,
        "additional_attempts_remaining": remaining_budget,
        "budget_authorizes_partition_boundary": True,
    }


def check_partition_readiness(
    preflight: dict[str, object],
    partition_id: str,
) -> dict[str, object]:
    """Require the requested partition to be the budget-authorized next step."""
    resume = preflight["resume"]
    if resume["campaign_status"] not in {
        "ready_for_canary",
        "ready_to_resume",
    }:
        raise CampaignError(
            "Campaign is not ready to execute a partition: "
            f"{resume.get('blocking_reason')}"
        )
    if resume.get("next_partition_id") != partition_id:
        raise CampaignError(
            f"Partition {partition_id} is not the deterministic next partition "
            f"({resume.get('next_partition_id')})."
        )
    if not resume.get("budget_authorizes_partition_boundary"):
        raise CampaignError(
            f"Campaign budget does not authorize partition {partition_id}."
        )
    return {
        "partition_id": partition_id,
        "run_id": resume["next_run_id"],
        "next_sequence": resume["next_sequence"],
        "next_offset": resume["next_offset"],
        "remaining_campaign_attempts": resume[
            "additional_attempts_remaining"
        ],
        "partition_remaining_request_ceiling": resume[
            "partition_remaining_request_ceiling"
        ],
        "ready": True,
    }


def inspect_campaign(
    plan: CampaignPlan,
) -> dict[str, object]:
    """Inspect existing state/cache read-only and derive deterministic resume."""
    campaign = plan.config
    connection = _open_read_only_state(campaign.state_path)
    try:
        states = tuple(
            _inspect_partition(partition, connection=connection)
            for partition in plan.partitions
        )
    finally:
        if connection is not None:
            connection.close()

    pilot_partition = next(
        partition for partition in plan.partitions if partition.is_pilot
    )
    pilot_state = next(
        state for state in states if state.kind == "cached_pilot"
    )
    pilot_reuse = _verify_pilot(
        campaign,
        pilot_partition,
        pilot_state,
    )
    resume = resolve_resume(campaign, states)
    semantic_state = {
        "campaign_id": campaign.campaign_id,
        "campaign_plan_fingerprint": plan.plan_fingerprint,
        "partitions": [
            state.semantic_payload()
            for state in states
        ],
        "pilot_reuse": pilot_reuse,
        "resume": resume,
    }
    state_fingerprint = _sha256_json(semantic_state)
    return {
        "campaign_preflight_schema_version": (
            CAMPAIGN_PREFLIGHT_SCHEMA_VERSION
        ),
        "campaign_id": campaign.campaign_id,
        "configuration_fingerprint": campaign.config_fingerprint,
        "campaign_plan_fingerprint": plan.plan_fingerprint,
        "campaign_state_fingerprint": state_fingerprint,
        "state_source": {
            "sqlite_request_ledger": _display_path(
                campaign.state_path,
                campaign.repository_root,
            ),
            "opened_read_only": True,
            "campaign_tables_added": False,
            "cache_directory": _display_path(
                campaign.raw_root / "cache",
                campaign.repository_root,
            ),
        },
        "partitions": [
            state.semantic_payload()
            for state in states
        ],
        "request_accounting": {
            "historical_pilot_http_attempts": pilot_state.request_count,
            "m3_5_additional_attempts_used": resume[
                "additional_attempts_used"
            ],
            "m3_5_additional_attempts_remaining": resume[
                "additional_attempts_remaining"
            ],
            "m3_5_additional_attempt_hard_maximum": (
                campaign.max_additional_requests
            ),
            "verified_cached_pilot_pages": (
                pilot_state.accepted_page_count
            ),
            "cache_hits_do_not_count_as_attempts": True,
            "all_http_outcomes_count_as_attempts": True,
        },
        "pilot_reuse": pilot_reuse,
        "resume": resume,
    }


def with_pilot_evidence(
    campaign: CampaignConfig,
    evidence: tuple[PilotPageEvidence, ...],
) -> CampaignConfig:
    """Return a campaign variant for deterministic portable cache tests."""
    return replace(campaign, pilot_required_pages=evidence)
