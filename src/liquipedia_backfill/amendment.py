"""Immutable, cache-backed campaign budget amendments.

This module is a thin coordination layer. It does not implement HTTP,
parsing, normalization, or dataset construction. The existing
``BackfillRunner`` remains the only acquisition engine.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .cache import atomic_write
from .campaign import (
    CAMPAIGN_PREFLIGHT_SCHEMA_VERSION,
    CampaignError,
    CampaignPartition,
    CampaignPlan,
    PartitionRuntimeState,
    _display_path,
    _inspect_partition,
    _open_read_only_state,
    _sha256_json,
    _verify_pilot,
    resolve_resume,
)
from .config import BackfillConfig
from .planner import RequestSpec, create_plan


BUDGET_AMENDMENT_SCHEMA_VERSION = (
    "liquipedia-history-campaign-budget-amendment-v1"
)
AMENDED_PREFLIGHT_SCHEMA_VERSION = (
    "liquipedia-history-campaign-amended-preflight-v1"
)

Q1_2024_PARTITION_ID = "2024-Q1"
Q1_2024_PREDECESSOR_RUN_ID = "m3_20240101_20240401_4aa59da8deab"
Q1_2024_PREDECESSOR_CONFIG_HASH = (
    "4aa59da8deab0748102a63a09c21d1b9bc10dfeb317bf57b7633d2ea0014a051"
)
Q1_2024_PREFIX_PAGE_COUNT = 8
Q1_2024_AMENDED_TOTAL_PAGE_SLOTS = 20
Q1_2024_MAX_NEW_HTTP_ATTEMPTS = 12
Q1_2024_AMENDED_RUN_ID = "m3_20240101_20240401_2c59812252db"
Q1_2024_AMENDED_CONFIG_HASH = (
    "2c59812252db906c8b373ec33fbc9b5cec0bb3f06e7b7c3250eafd94e442d097"
)


@dataclass(frozen=True, slots=True)
class PrefixPageEvidence:
    """Immutable evidence for one verified predecessor cache page."""

    sequence: int
    offset: int
    request_hash: str
    response_sha256: str
    record_count: int

    def payload(self) -> dict[str, object]:
        """Return a deterministic JSON-compatible representation."""
        return {
            "sequence": self.sequence,
            "offset": self.offset,
            "request_hash": self.request_hash,
            "response_sha256": self.response_sha256,
            "record_count": self.record_count,
            "is_final_page": False,
        }


@dataclass(frozen=True, slots=True)
class PartitionBudgetAmendment:
    """One immutable extension of a previously exhausted partition."""

    repository_root: Path
    campaign_id: str
    campaign_configuration_fingerprint: str
    campaign_plan_fingerprint: str
    partition_id: str
    predecessor_run_id: str
    predecessor_config_hash: str
    predecessor_page_slot_ceiling: int
    predecessor_http_attempts: int
    predecessor_records_seen: int
    prefix_pages: tuple[PrefixPageEvidence, ...]
    amended_config: BackfillConfig
    maximum_new_http_attempts: int
    campaign_attempts_used_before_amendment: int
    campaign_attempts_remaining_before_amendment: int
    campaign_attempt_hard_maximum: int

    @property
    def first_conditional_sequence(self) -> int:
        """Return the first page not present in the verified prefix."""
        return len(self.prefix_pages) + 1

    @property
    def first_conditional_offset(self) -> int:
        """Return the first offset not present in the verified prefix."""
        return len(self.prefix_pages) * self.amended_config.page_size

    @property
    def conditional_requests(self) -> tuple[RequestSpec, ...]:
        """Return only request slots authorized by this amendment."""
        return create_plan(self.amended_config).requests[
            len(self.prefix_pages):
        ]

    def identity_payload(self) -> dict[str, object]:
        """Return the path-independent immutable amendment identity."""
        return {
            "budget_amendment_schema_version": (
                BUDGET_AMENDMENT_SCHEMA_VERSION
            ),
            "campaign": {
                "campaign_id": self.campaign_id,
                "configuration_fingerprint": (
                    self.campaign_configuration_fingerprint
                ),
                "plan_fingerprint": self.campaign_plan_fingerprint,
                "attempt_hard_maximum": (
                    self.campaign_attempt_hard_maximum
                ),
            },
            "partition_id": self.partition_id,
            "predecessor": {
                "run_id": self.predecessor_run_id,
                "config_hash": self.predecessor_config_hash,
                "page_slot_ceiling": self.predecessor_page_slot_ceiling,
                "http_attempts": self.predecessor_http_attempts,
                "records_seen": self.predecessor_records_seen,
                "terminal_status": "budget_exhausted",
                "verified_prefix_pages": [
                    page.payload() for page in self.prefix_pages
                ],
            },
            "amended_run": {
                "run_id": self.amended_config.run_id,
                "config_hash": self.amended_config.config_hash,
                "scope": self.amended_config.scope_payload(),
                "total_page_slot_ceiling": (
                    self.amended_config.max_requests
                ),
                "maximum_new_http_attempts": (
                    self.maximum_new_http_attempts
                ),
                "required_cache_prefix_pages": len(self.prefix_pages),
                "first_conditional_sequence": (
                    self.first_conditional_sequence
                ),
                "first_conditional_offset": self.first_conditional_offset,
                "conditional_requests": [
                    {
                        "sequence": request.sequence,
                        "offset": request.offset,
                        "request_hash": request.request_hash,
                        "canonical_request": request.canonical_payload,
                    }
                    for request in self.conditional_requests
                ],
            },
            "campaign_accounting_policy": {
                "attempt_hard_maximum": (
                    self.campaign_attempt_hard_maximum
                ),
                "predecessor_attempts_remain_counted": True,
                "cache_hits_count_as_attempts": False,
                "all_http_outcomes_count_as_attempts": True,
            },
            "unchanged_policy": {
                "date_range": True,
                "tiers": True,
                "finished_matches_only": True,
                "endpoint": True,
                "projection": True,
                "page_size": True,
                "ordering": True,
                "automatic_retries": 0,
                "request_interval_seconds": (
                    self.amended_config.request_interval_seconds
                ),
                "rolling_hour_limit": (
                    self.amended_config.hourly_request_limit
                ),
                "immutable_cache": True,
                "chronological_progression": True,
                "stop_gates": True,
            },
        }

    @property
    def amendment_fingerprint(self) -> str:
        """Return the deterministic identity of this amendment."""
        return _sha256_json(self.identity_payload())

    @property
    def effective_plan_fingerprint(self) -> str:
        """Link the immutable base plan to this exact amendment."""
        return _sha256_json(
            {
                "campaign_plan_fingerprint": (
                    self.campaign_plan_fingerprint
                ),
                "budget_amendment_fingerprint": (
                    self.amendment_fingerprint
                ),
            }
        )

    @property
    def output_directory(self) -> Path:
        """Return the credential-free amendment artifact directory."""
        return (
            self.repository_root
            / "data"
            / "backfill"
            / "campaigns"
            / self.campaign_id
            / "amendments"
            / self.partition_id
        )

    @property
    def recovery_command(self) -> str:
        """Return the exact separately executable recovery command."""
        return (
            ".venv/bin/python scripts/plan_liquipedia_history_campaign.py "
            "--check-partition-readiness 2024-Q1 "
            "--include-approved-amendment 2024-Q1 && \\\n"
            ".venv/bin/python scripts/backfill_liquipedia_history.py \\\n"
            "  --start 2024-01-01T00:00:00Z \\\n"
            "  --end 2024-04-01T00:00:00Z \\\n"
            "  --tier 1 \\\n"
            "  --tier 2 \\\n"
            "  --page-size 100 \\\n"
            "  --max-requests 20 \\\n"
            "  --max-network-attempts 12 \\\n"
            "  --require-cache-prefix-pages 8 \\\n"
            "  --hourly-limit 54 \\\n"
            "  --request-interval-seconds 67 \\\n"
            "  --timeout-seconds 30 \\\n"
            "  --execute \\\n"
            "  --confirm-live-request-budget 12"
        )

    @property
    def subsequent_resume_command(self) -> str:
        """Return the amended chronological readiness command."""
        return (
            ".venv/bin/python scripts/plan_liquipedia_history_campaign.py "
            "--check-partition-readiness 2024-Q2 "
            "--include-approved-amendment 2024-Q1"
        )

    def public_payload(self) -> dict[str, object]:
        """Return the complete credential-free amendment plan."""
        payload = self.identity_payload()
        payload.update(
            {
                "budget_amendment_fingerprint": (
                    self.amendment_fingerprint
                ),
                "effective_plan_fingerprint": (
                    self.effective_plan_fingerprint
                ),
                "campaign_accounting_at_planning": {
                    "attempts_used": (
                        self.campaign_attempts_used_before_amendment
                    ),
                    "attempts_remaining": (
                        self.campaign_attempts_remaining_before_amendment
                    ),
                    "attempt_hard_maximum": (
                        self.campaign_attempt_hard_maximum
                    ),
                },
                "paths": {
                    "predecessor_checkpoint": _display_path(
                        (
                            self.repository_root
                            / "data"
                            / "backfill"
                            / "runs"
                            / self.predecessor_run_id
                            / "checkpoint.json"
                        ),
                        self.repository_root,
                    ),
                    "amended_checkpoint": _display_path(
                        (
                            self.amended_config.run_directory
                            / "checkpoint.json"
                        ),
                        self.repository_root,
                    ),
                    "sqlite_request_ledger": _display_path(
                        self.amended_config.state_path,
                        self.repository_root,
                    ),
                    "cache": _display_path(
                        self.amended_config.cache_directory,
                        self.repository_root,
                    ),
                },
                "commands": {
                    "recovery": self.recovery_command,
                    "subsequent_chronological_readiness": (
                        self.subsequent_resume_command
                    ),
                },
                "authenticated_requests_performed_by_planning": 0,
            }
        )
        return payload


@dataclass(frozen=True, slots=True)
class AmendmentArtifacts:
    """Published credential-free amendment artifacts."""

    amendment_fingerprint: str
    effective_plan_fingerprint: str
    json_path: Path
    markdown_path: Path


def _scope_without_page_ceiling(
    config: BackfillConfig,
) -> dict[str, object]:
    """Return acquisition scope with only the mutable budget removed."""
    payload = config.scope_payload()
    payload.pop("max_requests")
    return payload


def create_2024_q1_budget_amendment(
    plan: CampaignPlan,
) -> PartitionBudgetAmendment:
    """Certify the exact exhausted Q1 prefix and build its amendment."""
    from .campaign import inspect_campaign

    preflight = inspect_campaign(plan)
    predecessor_partition = next(
        (
            partition
            for partition in plan.partitions
            if partition.partition_id == Q1_2024_PARTITION_ID
        ),
        None,
    )
    if predecessor_partition is None:
        raise CampaignError("The campaign does not contain 2024-Q1.")
    predecessor_state = next(
        (
            state
            for state in preflight["partitions"]
            if state["partition_id"] == Q1_2024_PARTITION_ID
        ),
        None,
    )
    if predecessor_state is None:
        raise CampaignError("The campaign preflight does not contain 2024-Q1.")

    predecessor_config = predecessor_partition.config
    if (
        predecessor_config.run_id != Q1_2024_PREDECESSOR_RUN_ID
        or predecessor_config.config_hash
        != Q1_2024_PREDECESSOR_CONFIG_HASH
        or predecessor_config.max_requests != Q1_2024_PREFIX_PAGE_COUNT
    ):
        raise CampaignError("The approved 2024-Q1 predecessor identity changed.")
    if preflight["resume"]["blocking_reason"] != (
        "2024-Q1:partition_budget_exhausted"
    ):
        raise CampaignError(
            "The approved amendment requires 2024-Q1 to be the first "
            "blocked partition with an exhausted budget."
        )
    if (
        predecessor_state["ledger_status"] != "budget_exhausted"
        or predecessor_state["request_count"]
        != Q1_2024_PREFIX_PAGE_COUNT
        or predecessor_state["accepted_page_count"]
        != Q1_2024_PREFIX_PAGE_COUNT
        or predecessor_state["next_sequence"]
        != Q1_2024_PREFIX_PAGE_COUNT + 1
        or predecessor_state["next_offset"]
        != (
            Q1_2024_PREFIX_PAGE_COUNT
            * predecessor_config.page_size
        )
    ):
        raise CampaignError(
            "The 2024-Q1 predecessor does not match the approved exhausted "
            "eight-page checkpoint."
        )

    prefix_pages: list[PrefixPageEvidence] = []
    for page in predecessor_state["verified_pages"]:
        sequence = int(page["sequence"])
        if (
            sequence != len(prefix_pages) + 1
            or int(page["record_count"]) != predecessor_config.page_size
            or bool(page["is_final_page"])
            or page["source_kind"] != "network"
        ):
            raise CampaignError(
                "The 2024-Q1 predecessor prefix is not eight contiguous "
                "full network pages."
            )
        prefix_pages.append(
            PrefixPageEvidence(
                sequence=sequence,
                offset=(sequence - 1) * predecessor_config.page_size,
                request_hash=str(page["request_hash"]),
                response_sha256=str(page["response_sha256"]),
                record_count=int(page["record_count"]),
            )
        )

    amended_config = replace(
        predecessor_config,
        max_requests=Q1_2024_AMENDED_TOTAL_PAGE_SLOTS,
    )
    if (
        amended_config.run_id != Q1_2024_AMENDED_RUN_ID
        or amended_config.config_hash != Q1_2024_AMENDED_CONFIG_HASH
    ):
        raise CampaignError("The deterministic amended run identity changed.")
    if (
        _scope_without_page_ceiling(predecessor_config)
        != _scope_without_page_ceiling(amended_config)
    ):
        raise CampaignError(
            "The amended run changed more than its page-slot ceiling."
        )
    amended_specs = create_plan(amended_config).requests
    if tuple(
        request.request_hash
        for request in amended_specs[:Q1_2024_PREFIX_PAGE_COUNT]
    ) != tuple(page.request_hash for page in prefix_pages):
        raise CampaignError(
            "The amended run does not reproduce the predecessor cache keys."
        )
    if (
        len(amended_specs) - len(prefix_pages)
        != Q1_2024_MAX_NEW_HTTP_ATTEMPTS
    ):
        raise CampaignError("The amended incremental attempt ceiling changed.")

    accounting = preflight["request_accounting"]
    attempts_remaining = int(
        accounting["m3_5_additional_attempts_remaining"]
    )

    return PartitionBudgetAmendment(
        repository_root=plan.config.repository_root,
        campaign_id=plan.config.campaign_id,
        campaign_configuration_fingerprint=(
            plan.config.config_fingerprint
        ),
        campaign_plan_fingerprint=plan.plan_fingerprint,
        partition_id=Q1_2024_PARTITION_ID,
        predecessor_run_id=predecessor_config.run_id,
        predecessor_config_hash=predecessor_config.config_hash,
        predecessor_page_slot_ceiling=predecessor_config.max_requests,
        predecessor_http_attempts=int(predecessor_state["request_count"]),
        predecessor_records_seen=int(predecessor_state["records_seen"]),
        prefix_pages=tuple(prefix_pages),
        amended_config=amended_config,
        maximum_new_http_attempts=Q1_2024_MAX_NEW_HTTP_ATTEMPTS,
        campaign_attempts_used_before_amendment=int(
            accounting["m3_5_additional_attempts_used"]
        ),
        campaign_attempts_remaining_before_amendment=attempts_remaining,
        campaign_attempt_hard_maximum=(
            plan.config.max_additional_requests
        ),
    )


def _validate_amended_runtime(
    amendment: PartitionBudgetAmendment,
    state: PartitionRuntimeState,
    *,
    connection,
) -> None:
    """Require cache-only adoption of the predecessor prefix."""
    if state.request_count > amendment.maximum_new_http_attempts:
        raise CampaignError(
            "The amended run exceeded its new-network-attempt ceiling."
        )
    if state.ledger_status == "not_started":
        return

    accepted_prefix = state.verified_pages[:len(amendment.prefix_pages)]
    expected_prefix = amendment.prefix_pages[:len(accepted_prefix)]
    for actual, expected in zip(
        accepted_prefix,
        expected_prefix,
        strict=True,
    ):
        if (
            int(actual["sequence"]) != expected.sequence
            or str(actual["request_hash"]) != expected.request_hash
            or str(actual["response_sha256"]) != expected.response_sha256
            or int(actual["record_count"]) != expected.record_count
            or bool(actual["is_final_page"])
            or str(actual["source_kind"]) != "cache"
        ):
            raise CampaignError(
                "The amended run did not adopt the certified predecessor "
                "prefix exclusively from immutable cache."
            )

    if state.accepted_page_count < len(amendment.prefix_pages):
        if state.request_count:
            raise CampaignError(
                "The amended run attempted HTTP before adopting the full "
                "certified cache prefix."
            )
        return

    attempts = [
        dict(row)
        for row in connection.execute(
            "SELECT sequence, offset_value, request_hash "
            "FROM requests WHERE run_id = ? ORDER BY request_id",
            (amendment.amended_config.run_id,),
        ).fetchall()
    ]
    if any(
        int(attempt["sequence"]) < amendment.first_conditional_sequence
        or int(attempt["offset_value"]) < amendment.first_conditional_offset
        for attempt in attempts
    ):
        raise CampaignError(
            "The amended run repeated an HTTP request from the certified "
            "cache prefix."
        )


def inspect_campaign_with_budget_amendment(
    plan: CampaignPlan,
    amendment: PartitionBudgetAmendment,
) -> dict[str, object]:
    """Inspect deterministic resume state with one approved amendment."""
    current = create_2024_q1_budget_amendment(plan)
    if (
        current.amendment_fingerprint
        != amendment.amendment_fingerprint
    ):
        raise CampaignError(
            "The approved budget amendment no longer matches predecessor "
            "ledger/cache evidence."
        )

    connection = _open_read_only_state(plan.config.state_path)
    try:
        if connection is None:
            raise CampaignError("The campaign request ledger is missing.")
        base_states = tuple(
            _inspect_partition(partition, connection=connection)
            for partition in plan.partitions
        )
        predecessor_partition = next(
            partition
            for partition in plan.partitions
            if partition.partition_id == amendment.partition_id
        )
        amended_partition = CampaignPartition(
            ordinal=predecessor_partition.ordinal,
            partition_id=predecessor_partition.partition_id,
            kind=predecessor_partition.kind,
            config=amendment.amended_config,
            campaign_network_budget=(
                amendment.maximum_new_http_attempts
            ),
            expected_requests_min=1,
            expected_requests_max=(
                amendment.maximum_new_http_attempts
            ),
        )
        amended_state = _inspect_partition(
            amended_partition,
            connection=connection,
        )
        _validate_amended_runtime(
            amendment,
            amended_state,
            connection=connection,
        )
    finally:
        if connection is not None:
            connection.close()

    predecessor_state = next(
        state
        for state in base_states
        if state.partition_id == amendment.partition_id
    )
    remaining_ceiling = min(
        amended_state.remaining_request_ceiling,
        max(
            0,
            amendment.maximum_new_http_attempts
            - amended_state.request_count,
        ),
    )
    prefix_adopted = min(
        amended_state.accepted_page_count,
        len(amendment.prefix_pages),
    )
    logical_next_sequence = max(
        amendment.first_conditional_sequence,
        amended_state.next_sequence,
    )
    effective_state = PartitionRuntimeState(
        ordinal=predecessor_state.ordinal,
        partition_id=predecessor_state.partition_id,
        kind=predecessor_state.kind,
        run_id=amended_state.run_id,
        ledger_status=amended_state.ledger_status,
        effective_status=amended_state.effective_status,
        request_count=(
            predecessor_state.request_count
            + amended_state.request_count
        ),
        cache_hit_count=amended_state.cache_hit_count,
        records_seen=(
            amended_state.records_seen
            if amended_state.accepted_page_count
            else predecessor_state.records_seen
        ),
        accepted_page_count=(
            amended_state.accepted_page_count
            if amended_state.accepted_page_count
            else predecessor_state.accepted_page_count
        ),
        next_sequence=logical_next_sequence,
        next_offset=(
            (logical_next_sequence - 1)
            * amendment.amended_config.page_size
        ),
        remaining_request_ceiling=remaining_ceiling,
        verified_pages=(
            amended_state.verified_pages
            if amended_state.verified_pages
            else predecessor_state.verified_pages
        ),
        next_request_cached=(
            amended_state.next_request_cached
            if amended_state.next_sequence
            >= amendment.first_conditional_sequence
            else False
        ),
        blocking_reason=amended_state.blocking_reason,
    )
    effective_states = tuple(
        (
            effective_state
            if state.partition_id == amendment.partition_id
            else state
        )
        for state in base_states
    )

    pilot_partition = next(
        partition for partition in plan.partitions if partition.is_pilot
    )
    pilot_state = next(
        state for state in effective_states if state.kind == "cached_pilot"
    )
    pilot_reuse = _verify_pilot(
        plan.config,
        pilot_partition,
        pilot_state,
    )
    resume = resolve_resume(plan.config, effective_states)
    semantic_state = {
        "campaign_id": plan.config.campaign_id,
        "campaign_plan_fingerprint": plan.plan_fingerprint,
        "budget_amendment_fingerprint": amendment.amendment_fingerprint,
        "effective_plan_fingerprint": amendment.effective_plan_fingerprint,
        "partitions": [
            state.semantic_payload() for state in effective_states
        ],
        "resume": resume,
    }
    return {
        "campaign_preflight_schema_version": (
            CAMPAIGN_PREFLIGHT_SCHEMA_VERSION
        ),
        "amended_preflight_schema_version": (
            AMENDED_PREFLIGHT_SCHEMA_VERSION
        ),
        "campaign_id": plan.config.campaign_id,
        "configuration_fingerprint": plan.config.config_fingerprint,
        "campaign_plan_fingerprint": plan.plan_fingerprint,
        "budget_amendment_fingerprint": amendment.amendment_fingerprint,
        "effective_plan_fingerprint": amendment.effective_plan_fingerprint,
        "campaign_state_fingerprint": _sha256_json(semantic_state),
        "state_source": {
            "sqlite_request_ledger": _display_path(
                plan.config.state_path,
                plan.config.repository_root,
            ),
            "opened_read_only": True,
            "campaign_tables_added": False,
            "cache_directory": _display_path(
                plan.config.raw_root / "cache",
                plan.config.repository_root,
            ),
        },
        "partitions": [
            state.semantic_payload() for state in effective_states
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
                plan.config.max_additional_requests
            ),
            "predecessor_http_attempts_carried_forward": (
                predecessor_state.request_count
            ),
            "amended_run_http_attempts": amended_state.request_count,
            "amended_run_cache_hits": amended_state.cache_hit_count,
            "verified_prefix_pages_adopted": prefix_adopted,
            "cache_hits_do_not_count_as_attempts": True,
            "all_http_outcomes_count_as_attempts": True,
        },
        "pilot_reuse": pilot_reuse,
        "budget_amendment": {
            **amendment.public_payload(),
            "runtime": {
                "ledger_status": amended_state.ledger_status,
                "accepted_page_count": (
                    amended_state.accepted_page_count
                ),
                "verified_prefix_pages_adopted": prefix_adopted,
                "new_http_attempts": amended_state.request_count,
                "new_http_attempts_remaining": max(
                    0,
                    amendment.maximum_new_http_attempts
                    - amended_state.request_count,
                ),
                "runner_next_sequence": amended_state.next_sequence,
                "first_live_sequence": logical_next_sequence,
            },
        },
        "resume": resume,
    }


def render_budget_amendment_markdown(
    amendment: PartitionBudgetAmendment,
) -> str:
    """Render a concise, reviewable amendment plan."""
    payload = amendment.public_payload()
    amended = payload["amended_run"]
    predecessor = payload["predecessor"]
    lines = [
        "# 2024-Q1 Partition Budget Amendment",
        "",
        "Generated credential-free artifact — do not hand-edit.",
        "",
        f"- Campaign: `{amendment.campaign_id}`",
        (
            "- Base campaign plan fingerprint: "
            f"`{amendment.campaign_plan_fingerprint}`"
        ),
        (
            "- Amendment fingerprint: "
            f"`{amendment.amendment_fingerprint}`"
        ),
        (
            "- Effective plan fingerprint: "
            f"`{amendment.effective_plan_fingerprint}`"
        ),
        f"- Preserved predecessor: `{predecessor['run_id']}`",
        f"- Amended run: `{amended['run_id']}`",
        (
            "- Page-slot ceiling: "
            f"`{predecessor['page_slot_ceiling']}` → "
            f"`{amended['total_page_slot_ceiling']}`"
        ),
        (
            "- Hard ceiling for new HTTP attempts: "
            f"`{amended['maximum_new_http_attempts']}`"
        ),
        "- Authenticated requests made while planning: `0`",
        "",
        "## Verified immutable prefix",
        "",
        "| Sequence | Offset | Request hash | Response SHA-256 | Records |",
        "| ---: | ---: | --- | --- | ---: |",
    ]
    for page in amendment.prefix_pages:
        lines.append(
            f"| {page.sequence} | {page.offset} | "
            f"`{page.request_hash}` | `{page.response_sha256}` | "
            f"{page.record_count} |"
        )
    lines.extend(
        [
            "",
            "## Conditional recovery requests",
            "",
            "| Sequence | Offset | Request hash |",
            "| ---: | ---: | --- |",
        ]
    )
    for request in amendment.conditional_requests:
        lines.append(
            f"| {request.sequence} | {request.offset} | "
            f"`{request.request_hash}` |"
        )
    lines.extend(
        [
            "",
            "## Separately executable recovery command",
            "",
            "```bash",
            amendment.recovery_command,
            "```",
            "",
            "## Chronological resume check after successful Q1 validation",
            "",
            "```bash",
            amendment.subsequent_resume_command,
            "```",
        ]
    )
    return "\n".join(lines) + "\n"


def write_budget_amendment_artifacts(
    amendment: PartitionBudgetAmendment,
) -> AmendmentArtifacts:
    """Publish immutable JSON and Markdown amendment plans."""
    output = amendment.output_directory
    json_path = output / "budget_amendment.json"
    markdown_path = output / "budget_amendment.md"
    contents = {
        json_path: (
            json.dumps(
                amendment.public_payload(),
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            )
            + "\n"
        ).encode("utf-8"),
        markdown_path: render_budget_amendment_markdown(
            amendment
        ).encode("utf-8"),
    }
    for path, content in contents.items():
        if path.exists():
            if not path.is_file() or path.read_bytes() != content:
                raise CampaignError(
                    "Immutable budget-amendment artifact conflicts with "
                    f"existing file: {path}"
                )
            continue
        atomic_write(path, content)
    return AmendmentArtifacts(
        amendment_fingerprint=amendment.amendment_fingerprint,
        effective_plan_fingerprint=amendment.effective_plan_fingerprint,
        json_path=json_path,
        markdown_path=markdown_path,
    )
