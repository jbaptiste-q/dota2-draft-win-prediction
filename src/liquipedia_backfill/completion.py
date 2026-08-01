"""Credential-free planning for Milestone 3.6 dataset completion.

This module is deliberately an offline coordination layer.  It does not read
credentials, import the HTTP client, execute requests, normalize records, or
publish datasets.  The existing acquisition and publication entry points
remain authoritative for those responsibilities.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

from .amendment import (
    Q1_2024_AMENDED_RUN_ID,
    create_2024_q1_budget_amendment,
    inspect_campaign_with_budget_amendment,
)
from .cache import atomic_write
from .campaign import (
    CampaignConfig,
    CampaignError,
    CampaignPlan,
    _display_path,
    _sha256_json,
    create_campaign_plan,
    ledger_request_row_count,
)
from .config import BackfillConfig
from .planner import RequestSpec, create_plan


COMPLETION_PLAN_SCHEMA_VERSION = "liquipedia-history-completion-plan-v1"
COMPLETION_PREFLIGHT_SCHEMA_VERSION = (
    "liquipedia-history-completion-preflight-v1"
)
DEFAULT_NEW_HTTP_ATTEMPT_CEILING = 80
EFFECTIVE_PARTITION_PAGE_SLOTS = 20
EXPECTED_REMAINING_REQUESTS_MIN = 25
EXPECTED_REMAINING_REQUESTS_MAX = 50
EXPECTED_EXISTING_EXPANSION_ATTEMPTS = 63
EXPECTED_LEDGER_ATTEMPTS_WITH_PILOT = 65
FINAL_RELEASE_ALIAS = "m3.5-tier1-tier2-2022-2026-v1"

Q2_2024_PARTITION_ID = "2024-Q2"
Q2_2024_PREDECESSOR_RUN_ID = "m3_20240401_20240701_6575003bb769"
Q2_2024_PREFIX_PAGE_COUNT = 8
Q2_2024_PREFIX_RECORD_COUNT = 800
Q2_2024_AMENDED_RUN_ID = "m3_20240401_20240701_df05306783f7"


@dataclass(frozen=True, slots=True)
class CompletionPartition:
    """One logical partition in the effective completion plan."""

    ordinal: int
    partition_id: str
    kind: str
    disposition: str
    config: BackfillConfig
    required_cache_prefix_pages: int
    maximum_new_http_attempts: int

    @property
    def request_specs(self) -> tuple[RequestSpec, ...]:
        """Return the deterministic request slots for this partition."""
        return create_plan(self.config).requests

    def identity_payload(self) -> dict[str, object]:
        """Return a path-independent partition identity."""
        return {
            "ordinal": self.ordinal,
            "partition_id": self.partition_id,
            "kind": self.kind,
            "disposition": self.disposition,
            "run_id": self.config.run_id,
            "config_hash": self.config.config_hash,
            "scope": self.config.scope_payload(),
            "required_cache_prefix_pages": self.required_cache_prefix_pages,
            "maximum_new_http_attempts": self.maximum_new_http_attempts,
            "requests": [
                {
                    "sequence": request.sequence,
                    "offset": request.offset,
                    "request_hash": request.request_hash,
                    "canonical_request": request.canonical_payload,
                }
                for request in self.request_specs
            ],
        }


@dataclass(frozen=True, slots=True)
class CompletionPlan:
    """Immutable M3.6 authorization plan layered over the M3.5 campaign."""

    repository_root: Path
    base_campaign: CampaignPlan
    partitions: tuple[CompletionPartition, ...]
    maximum_new_http_attempts: int

    @property
    def cumulative_expansion_attempt_ceiling(self) -> int:
        """Return the old consumed attempts plus the new authorization."""
        return (
            EXPECTED_EXISTING_EXPANSION_ATTEMPTS
            + self.maximum_new_http_attempts
        )

    def identity_payload(self) -> dict[str, object]:
        """Return the complete credential-free completion identity."""
        return {
            "completion_plan_schema_version": COMPLETION_PLAN_SCHEMA_VERSION,
            "base_campaign": {
                "campaign_id": self.base_campaign.config.campaign_id,
                "configuration_fingerprint": (
                    self.base_campaign.config.config_fingerprint
                ),
                "plan_fingerprint": self.base_campaign.plan_fingerprint,
                "historical_attempt_ceiling_preserved": (
                    self.base_campaign.config.max_additional_requests
                ),
            },
            "scope": {
                "start_utc_inclusive": (
                    self.base_campaign.config.start_utc.isoformat()
                ),
                "end_utc_exclusive": (
                    self.base_campaign.config.end_utc.isoformat()
                ),
                "tiers": list(self.base_campaign.config.tiers),
                "finished_matches_only": True,
                "partition_count": len(self.partitions),
            },
            "completion_authorization": {
                "new_http_attempt_ceiling": self.maximum_new_http_attempts,
                "existing_expansion_attempts_preserved": (
                    EXPECTED_EXISTING_EXPANSION_ATTEMPTS
                ),
                "cumulative_expansion_attempt_ceiling": (
                    self.cumulative_expansion_attempt_ceiling
                ),
                "expected_remaining_requests_min": (
                    EXPECTED_REMAINING_REQUESTS_MIN
                ),
                "expected_remaining_requests_max": (
                    EXPECTED_REMAINING_REQUESTS_MAX
                ),
                "cache_hits_count_as_attempts": False,
                "all_http_outcomes_count_as_attempts": True,
            },
            "unchanged_acquisition_policy": {
                "official_api_only": True,
                "html_scraping": False,
                "page_size": self.base_campaign.config.page_size,
                "hourly_request_limit": (
                    self.base_campaign.config.hourly_request_limit
                ),
                "request_interval_seconds": (
                    self.base_campaign.config.request_interval_seconds
                ),
                "automatic_retries": 0,
                "chronological_partitions": True,
                "immutable_cache": True,
            },
            "final_publication": {
                "mode": "full-window",
                "alias": FINAL_RELEASE_ALIAS,
                "requires_all_19_partitions": True,
            },
            "partitions": [
                partition.identity_payload()
                for partition in self.partitions
            ],
        }

    @property
    def plan_fingerprint(self) -> str:
        """Return a deterministic path-independent plan fingerprint."""
        return _sha256_json(self.identity_payload())

    @property
    def output_directory(self) -> Path:
        """Return the public credential-free artifact directory."""
        return (
            self.repository_root
            / "data"
            / "backfill"
            / "campaigns"
            / self.base_campaign.config.campaign_id
            / "milestone_3_6"
        )

    def public_payload(self) -> dict[str, object]:
        """Return the plan plus repository-relative operational paths."""
        payload = self.identity_payload()
        payload.update(
            {
                "completion_plan_fingerprint": self.plan_fingerprint,
                "paths": {
                    "sqlite_request_ledger": _display_path(
                        self.base_campaign.config.state_path,
                        self.repository_root,
                    ),
                    "immutable_cache": _display_path(
                        self.base_campaign.config.raw_root / "cache",
                        self.repository_root,
                    ),
                    "partition_runs": _display_path(
                        self.base_campaign.config.run_root,
                        self.repository_root,
                    ),
                },
                "authenticated_requests_performed_by_planning": 0,
                "api_key_read_by_planning": False,
            }
        )
        return payload


@dataclass(frozen=True, slots=True)
class CompletionArtifacts:
    """Paths and fingerprints for generated planning evidence."""

    plan_fingerprint: str
    preflight_fingerprint: str | None
    plan_json: Path
    plan_markdown: Path
    preflight_json: Path | None
    preflight_markdown: Path | None


def _effective_partition(
    partition,
) -> CompletionPartition:
    """Create the M3.6 view without changing the base campaign."""
    if partition.kind == "cached_pilot":
        return CompletionPartition(
            ordinal=partition.ordinal,
            partition_id=partition.partition_id,
            kind=partition.kind,
            disposition="reuse_completed_pilot",
            config=partition.config,
            required_cache_prefix_pages=2,
            maximum_new_http_attempts=0,
        )
    if partition.partition_id < "2024-Q1":
        return CompletionPartition(
            ordinal=partition.ordinal,
            partition_id=partition.partition_id,
            kind=partition.kind,
            disposition="reuse_completed_partition",
            config=partition.config,
            required_cache_prefix_pages=0,
            maximum_new_http_attempts=0,
        )

    config = replace(
        partition.config,
        max_requests=EFFECTIVE_PARTITION_PAGE_SLOTS,
    )
    if partition.partition_id == "2024-Q1":
        disposition = "reuse_completed_budget_amendment"
        maximum_new = 0
        prefix_pages = 0
    elif partition.partition_id == Q2_2024_PARTITION_ID:
        disposition = "resume_certified_cache_prefix"
        maximum_new = (
            EFFECTIVE_PARTITION_PAGE_SLOTS
            - Q2_2024_PREFIX_PAGE_COUNT
        )
        prefix_pages = Q2_2024_PREFIX_PAGE_COUNT
    else:
        disposition = "acquire_chronologically"
        maximum_new = EFFECTIVE_PARTITION_PAGE_SLOTS
        prefix_pages = 0
    return CompletionPartition(
        ordinal=partition.ordinal,
        partition_id=partition.partition_id,
        kind=partition.kind,
        disposition=disposition,
        config=config,
        required_cache_prefix_pages=prefix_pages,
        maximum_new_http_attempts=maximum_new,
    )


def create_completion_plan(
    repository_root: Path,
    *,
    maximum_new_http_attempts: int = DEFAULT_NEW_HTTP_ATTEMPT_CEILING,
) -> CompletionPlan:
    """Create the static M3.6 plan without reading local campaign state."""
    if maximum_new_http_attempts < 1:
        raise ValueError("M3.6 HTTP-attempt ceiling must be positive.")
    base = create_campaign_plan(
        CampaignConfig(repository_root=repository_root)
    )
    partitions = tuple(
        _effective_partition(partition)
        for partition in base.partitions
    )
    q1 = next(
        item for item in partitions if item.partition_id == "2024-Q1"
    )
    q2 = next(
        item for item in partitions if item.partition_id == Q2_2024_PARTITION_ID
    )
    if q1.config.run_id != Q1_2024_AMENDED_RUN_ID:
        raise CampaignError("The effective 2024-Q1 run identity changed.")
    if q2.config.run_id != Q2_2024_AMENDED_RUN_ID:
        raise CampaignError("The effective 2024-Q2 run identity changed.")
    base_q2 = next(
        item
        for item in base.partitions
        if item.partition_id == Q2_2024_PARTITION_ID
    )
    if tuple(
        request.request_hash
        for request in q2.request_specs[:Q2_2024_PREFIX_PAGE_COUNT]
    ) != tuple(
        request.request_hash
        for request in base_q2.request_specs
    ):
        raise CampaignError(
            "The M3.6 Q2 plan does not preserve all predecessor cache keys."
        )
    return CompletionPlan(
        repository_root=repository_root.resolve(),
        base_campaign=base,
        partitions=partitions,
        maximum_new_http_attempts=maximum_new_http_attempts,
    )


def _partition_state(
    preflight: Mapping[str, Any],
    partition_id: str,
) -> Mapping[str, Any]:
    """Return one partition state from a campaign preflight."""
    for value in preflight.get("partitions", []):
        if value.get("partition_id") == partition_id:
            return value
    raise CampaignError(f"Campaign preflight lacks {partition_id}.")


def certify_completion_preflight(
    plan: CompletionPlan,
    *,
    amended_campaign_preflight: Mapping[str, Any],
    ledger_attempt_count: int,
) -> dict[str, object]:
    """Certify the current local state against the static M3.6 plan."""
    if amended_campaign_preflight.get("campaign_plan_fingerprint") != (
        plan.base_campaign.plan_fingerprint
    ):
        raise CampaignError("Base campaign plan fingerprint changed.")
    accounting = amended_campaign_preflight.get("request_accounting", {})
    used = int(accounting.get("m3_5_additional_attempts_used", -1))
    if used != EXPECTED_EXISTING_EXPANSION_ATTEMPTS:
        raise CampaignError(
            "M3.6 requires the reviewed 63-attempt expansion baseline."
        )
    if ledger_attempt_count != EXPECTED_LEDGER_ATTEMPTS_WITH_PILOT:
        raise CampaignError(
            "M3.6 requires the reviewed 65-attempt ledger baseline."
        )

    q1 = _partition_state(amended_campaign_preflight, "2024-Q1")
    if (
        q1.get("run_id") != Q1_2024_AMENDED_RUN_ID
        or q1.get("ledger_status") != "complete"
        or q1.get("effective_status") != "complete"
    ):
        raise CampaignError("The approved 2024-Q1 amendment is not complete.")

    q2 = _partition_state(
        amended_campaign_preflight,
        Q2_2024_PARTITION_ID,
    )
    verified_pages = list(q2.get("verified_pages", []))
    if (
        q2.get("run_id") != Q2_2024_PREDECESSOR_RUN_ID
        or q2.get("ledger_status") != "budget_exhausted"
        or int(q2.get("request_count", -1)) != Q2_2024_PREFIX_PAGE_COUNT
        or int(q2.get("accepted_page_count", -1))
        != Q2_2024_PREFIX_PAGE_COUNT
        or int(q2.get("records_seen", -1))
        != Q2_2024_PREFIX_RECORD_COUNT
        or int(q2.get("next_sequence", -1))
        != Q2_2024_PREFIX_PAGE_COUNT + 1
        or int(q2.get("next_offset", -1))
        != Q2_2024_PREFIX_RECORD_COUNT
        or len(verified_pages) != Q2_2024_PREFIX_PAGE_COUNT
    ):
        raise CampaignError(
            "The 2024-Q2 predecessor is not the reviewed eight-page prefix."
        )
    effective_q2 = next(
        item
        for item in plan.partitions
        if item.partition_id == Q2_2024_PARTITION_ID
    )
    expected_hashes = [
        request.request_hash
        for request in effective_q2.request_specs[:Q2_2024_PREFIX_PAGE_COUNT]
    ]
    actual_hashes: list[str] = []
    response_hashes: list[str] = []
    for sequence, page in enumerate(verified_pages, start=1):
        response_sha256 = str(page.get("response_sha256", ""))
        if (
            int(page.get("sequence", -1)) != sequence
            or int(page.get("record_count", -1))
            != plan.base_campaign.config.page_size
            or bool(page.get("is_final_page"))
            or page.get("source_kind") != "network"
            or len(response_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in response_sha256
            )
        ):
            raise CampaignError(
                "The 2024-Q2 cache prefix is not eight contiguous full "
                "network-certified pages with response hashes."
            )
        actual_hashes.append(str(page.get("request_hash")))
        response_hashes.append(response_sha256)
    if actual_hashes != expected_hashes:
        raise CampaignError("The 2024-Q2 cache-prefix request hashes changed.")
    if len(response_hashes) != len(set(response_hashes)):
        raise CampaignError("The 2024-Q2 response hashes are not unique.")

    resume = amended_campaign_preflight.get("resume", {})
    if resume.get("blocking_reason") != (
        "2024-Q2:partition_budget_exhausted"
    ):
        raise CampaignError("2024-Q2 is not the deterministic completion gate.")
    pilot = amended_campaign_preflight.get("pilot_reuse", {})
    if (
        not pilot.get("verified")
        or pilot.get("network_request_required") is not False
    ):
        raise CampaignError("The validated July 2026 pilot is not reusable.")

    semantic = {
        "completion_preflight_schema_version": (
            COMPLETION_PREFLIGHT_SCHEMA_VERSION
        ),
        "completion_plan_fingerprint": plan.plan_fingerprint,
        "base_campaign_state_fingerprint": (
            amended_campaign_preflight.get("campaign_state_fingerprint")
        ),
        "existing_state": {
            "ledger_http_attempts": ledger_attempt_count,
            "expansion_http_attempts": used,
            "completed_through_partition": "2024-Q1",
            "next_partition": Q2_2024_PARTITION_ID,
        },
        "q2_cache_prefix": {
            "predecessor_run_id": Q2_2024_PREDECESSOR_RUN_ID,
            "effective_run_id": effective_q2.config.run_id,
            "verified_pages": Q2_2024_PREFIX_PAGE_COUNT,
            "records": Q2_2024_PREFIX_RECORD_COUNT,
            "next_sequence": Q2_2024_PREFIX_PAGE_COUNT + 1,
            "next_offset": Q2_2024_PREFIX_RECORD_COUNT,
            "first_conditional_request_hash": (
                effective_q2.request_specs[
                    Q2_2024_PREFIX_PAGE_COUNT
                ].request_hash
            ),
            "verified_prefix_hashes": [
                {
                    "sequence": sequence,
                    "request_hash": request_hash,
                    "response_sha256": response_sha256,
                }
                for sequence, (request_hash, response_sha256) in enumerate(
                    zip(actual_hashes, response_hashes, strict=True),
                    start=1,
                )
            ],
            "maximum_new_http_attempts": (
                effective_q2.maximum_new_http_attempts
            ),
        },
        "pilot_reuse": {
            "verified": True,
            "run_id": pilot.get("run_id"),
            "network_request_required": False,
        },
        "authorization": {
            "new_http_attempt_ceiling": plan.maximum_new_http_attempts,
            "cumulative_expansion_attempt_ceiling": (
                plan.cumulative_expansion_attempt_ceiling
            ),
            "approval_required_before_execution": True,
        },
        "status": "ready_for_authenticated_approval",
        "authenticated_requests_performed_by_preflight": 0,
        "api_key_read_by_preflight": False,
    }
    return {
        **semantic,
        "completion_preflight_fingerprint": _sha256_json(semantic),
    }


def inspect_completion_preflight(
    plan: CompletionPlan,
) -> dict[str, object]:
    """Read and verify the current campaign ledger/cache without mutation."""
    before = ledger_request_row_count(plan.base_campaign.config.state_path)
    q1_amendment = create_2024_q1_budget_amendment(plan.base_campaign)
    current = inspect_campaign_with_budget_amendment(
        plan.base_campaign,
        q1_amendment,
    )
    result = certify_completion_preflight(
        plan,
        amended_campaign_preflight=current,
        ledger_attempt_count=before,
    )
    after = ledger_request_row_count(plan.base_campaign.config.state_path)
    if after != before:
        raise CampaignError("M3.6 preflight changed the request ledger.")
    return result


def _render_plan_markdown(plan: CompletionPlan) -> str:
    lines = [
        "# Milestone 3.6 Dataset Completion Plan",
        "",
        "Generated credential-free artifact — do not hand-edit.",
        "",
        f"- Plan fingerprint: `{plan.plan_fingerprint}`",
        (
            "- New HTTP-attempt ceiling pending approval: "
            f"`{plan.maximum_new_http_attempts}`"
        ),
        (
            "- Cumulative expansion ceiling: "
            f"`{plan.cumulative_expansion_attempt_ceiling}`"
        ),
        f"- Final release alias: `{FINAL_RELEASE_ALIAS}`",
        "- Authenticated requests made while planning: `0`",
        "",
        "| # | Partition | Disposition | Run ID | Slots | Cache prefix | "
        "Maximum new attempts |",
        "| ---: | --- | --- | --- | ---: | ---: | ---: |",
    ]
    for item in plan.partitions:
        lines.append(
            f"| {item.ordinal} | {item.partition_id} | "
            f"{item.disposition} | `{item.config.run_id}` | "
            f"{item.config.max_requests} | "
            f"{item.required_cache_prefix_pages} | "
            f"{item.maximum_new_http_attempts} |"
        )
    return "\n".join(lines) + "\n"


def _render_preflight_markdown(payload: Mapping[str, Any]) -> str:
    q2 = payload["q2_cache_prefix"]
    authorization = payload["authorization"]
    return "\n".join(
        [
            "# Milestone 3.6 Dataset Completion Preflight",
            "",
            "Generated credential-free artifact — do not hand-edit.",
            "",
            f"- Status: `{payload['status']}`",
            (
                "- Preflight fingerprint: "
                f"`{payload['completion_preflight_fingerprint']}`"
            ),
            (
                "- Completion plan fingerprint: "
                f"`{payload['completion_plan_fingerprint']}`"
            ),
            "- Current expansion attempts: `63`",
            "- Current ledger attempts including pilot: `65`",
            (
                "- New HTTP-attempt ceiling pending approval: "
                f"`{authorization['new_http_attempt_ceiling']}`"
            ),
            (
                "- 2024-Q2 certified prefix: "
                f"`{q2['verified_pages']}` pages / `{q2['records']}` records"
            ),
            (
                "- 2024-Q2 first conditional request: sequence `9`, "
                f"offset `800`, hash `{q2['first_conditional_request_hash']}`"
            ),
            "- July 2026 pilot: verified cache-only reuse",
            "- Authenticated requests made during preflight: `0`",
            "- API key read during preflight: `no`",
            "",
            "Execution remains blocked until the numeric live-request "
            "ceiling is explicitly approved.",
            "",
        ]
    )


def _write_immutable(path: Path, content: bytes) -> None:
    if path.exists():
        if not path.is_file() or path.read_bytes() != content:
            raise CampaignError(
                f"Immutable M3.6 artifact conflicts with existing file: {path}"
            )
        return
    atomic_write(path, content)


def write_completion_artifacts(
    plan: CompletionPlan,
    *,
    preflight: Mapping[str, Any] | None = None,
) -> CompletionArtifacts:
    """Write deterministic public plan and optional preflight evidence."""
    output = plan.output_directory
    plan_json = output / "completion_plan.json"
    plan_markdown = output / "completion_plan.md"
    _write_immutable(
        plan_json,
        (
            json.dumps(
                plan.public_payload(),
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            )
            + "\n"
        ).encode("utf-8"),
    )
    _write_immutable(
        plan_markdown,
        _render_plan_markdown(plan).encode("utf-8"),
    )

    preflight_json = None
    preflight_markdown = None
    preflight_fingerprint = None
    if preflight is not None:
        preflight_json = output / "completion_preflight.json"
        preflight_markdown = output / "completion_preflight.md"
        preflight_fingerprint = str(
            preflight["completion_preflight_fingerprint"]
        )
        _write_immutable(
            preflight_json,
            (
                json.dumps(
                    preflight,
                    indent=2,
                    sort_keys=True,
                    ensure_ascii=False,
                )
                + "\n"
            ).encode("utf-8"),
        )
        _write_immutable(
            preflight_markdown,
            _render_preflight_markdown(preflight).encode("utf-8"),
        )
    return CompletionArtifacts(
        plan_fingerprint=plan.plan_fingerprint,
        preflight_fingerprint=preflight_fingerprint,
        plan_json=plan_json,
        plan_markdown=plan_markdown,
        preflight_json=preflight_json,
        preflight_markdown=preflight_markdown,
    )
