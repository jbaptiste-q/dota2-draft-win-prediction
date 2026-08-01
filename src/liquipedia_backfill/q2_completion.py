"""Focused, restart-safe completion of the frozen 2026-Q2 partition.

This module adds one bounded successor authorization around the existing
Milestone 3.6 acquisition runner.  It deliberately delegates HTTP, caching,
checkpointing, parsing, normalization, supervised-dataset construction, and
quality validation to the already validated project layers.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .cache import CacheStore, atomic_write
from .campaign import CampaignError, PILOT_RUN_ID, _sha256_json
from .completion import (
    DEFAULT_NEW_HTTP_ATTEMPT_CEILING,
    CompletionPartition,
    CompletionPlan,
    create_completion_plan,
)
from .completion_execution import (
    _verify_baseline_ledger,
    _verify_new_cache_lineage,
    _verify_pilot_cache,
    _verify_postbaseline_attempts,
    _verify_q2_prefix,
    campaign_execution_lock,
    load_approved_preflight,
    run_offline_test_suite,
    verify_completed_prefix,
    verify_public_plan_artifact,
)
from .completion_validation import (
    PartitionValidationMetrics,
    validate_completed_partition,
)
from .envelope import response_record_count
from .planner import request_spec
from .runner import BackfillRunner
from .state import StateStore, is_no_response_transport_failure


CONTINUATION_PLAN_SCHEMA_VERSION = "liquipedia-2026-q2-continuation-plan-v1"
CONTINUATION_REPORT_SCHEMA_VERSION = (
    "liquipedia-2026-q2-continuation-report-v1"
)
READ_TIMEOUT_RECOVERY_SCHEMA_VERSION = (
    "liquipedia-2026-q2-read-timeout-recovery-v1"
)

PARTITION_ID = "2026-Q2"
RUN_ID = "m3_20260401_20260701_f73ba01f2767"
CONFIG_HASH = "f73ba01f2767edf144776d532b3fbf6a0a7ee8151f39f4e0e96f23586a1ddc31"

PREDECESSOR_AUTHORIZATION_ID = "m3.6-completion-80bf4dc4fa31810d"
PREDECESSOR_PLAN_FINGERPRINT = (
    "80bf4dc4fa31810dca0d1b8d3f1ece37779e0560dc1eeaeccd435e05e6ebbde0"
)
PREDECESSOR_PREFLIGHT_FINGERPRINT = (
    "2255aa5979e0743ebba28a95ca453bcca5c4cd48d6f7e6608bca621f91033280"
)
PREDECESSOR_BASELINE_REQUEST_ID = 65
PREDECESSOR_MAXIMUM_NEW_ATTEMPTS = 80

SUCCESSOR_BASELINE_REQUEST_ID = 145
SUCCESSOR_BASELINE_TOTAL_ATTEMPTS = 145
SUCCESSOR_BASELINE_EXPANSION_ATTEMPTS = 143
SUCCESSOR_MAXIMUM_NEW_ATTEMPTS = 12

PREFIX_PAGE_COUNT = 8
PREFIX_RECORD_COUNT = 800
RESUME_SEQUENCE = 9
RESUME_OFFSET = 800
TOTAL_PAGE_SLOTS = 20

EXPECTED_PREFIX_RESPONSE_HASHES = (
    "86826788ecb3964390b6b15444aaec60bd5dc214aafb3dd211a932b712646cad",
    "8acf0b1156b3332005846c3d74633384273c18cbc262207c6211c208942020b0",
    "155e866729ddeaa388b4b1155bccd95e1e6165398faf3c352a2a9c338e39f11a",
    "782abfce4a7987bf2f841080196cb11e4f07fe979f2f9a78e2098b8a6de95701",
    "c5bd440f7c3fcf34bd1d66e5978099f3af095da20f32502917f02a43c1ed9706",
    "744b84f5b923c45c01c5afa7ba8fd0b1af718c0944bceb3ae94d4004641f9cb2",
    "54ce6c6401fa73c8ca9a2958ba6d7cf573600cfe5a4626d1232a2fce99026d40",
    "d8f81ea540d3690389e0a16234e48375015788b5e50cbdc5c5db939c5e87a1eb",
)


@dataclass(frozen=True, slots=True)
class Q2ContinuationPlan:
    """Credential-free identity of the one approved continuation."""

    repository_root: Path
    completion_plan: CompletionPlan
    partition: CompletionPartition

    def identity_payload(self) -> dict[str, object]:
        specs = self.partition.request_specs
        return {
            "continuation_plan_schema_version": (
                CONTINUATION_PLAN_SCHEMA_VERSION
            ),
            "predecessor_authorization": {
                "authorization_id": PREDECESSOR_AUTHORIZATION_ID,
                "plan_fingerprint": PREDECESSOR_PLAN_FINGERPRINT,
                "preflight_fingerprint": (
                    PREDECESSOR_PREFLIGHT_FINGERPRINT
                ),
                "baseline_request_id": PREDECESSOR_BASELINE_REQUEST_ID,
                "maximum_new_attempts": (
                    PREDECESSOR_MAXIMUM_NEW_ATTEMPTS
                ),
                "required_state": "exactly_exhausted",
            },
            "successor_authorization": {
                "baseline_request_id": SUCCESSOR_BASELINE_REQUEST_ID,
                "baseline_total_attempts": (
                    SUCCESSOR_BASELINE_TOTAL_ATTEMPTS
                ),
                "baseline_expansion_attempts": (
                    SUCCESSOR_BASELINE_EXPANSION_ATTEMPTS
                ),
                "baseline_excluded_run_ids": [PILOT_RUN_ID],
                "maximum_new_attempts": SUCCESSOR_MAXIMUM_NEW_ATTEMPTS,
                "allowed_runs": {
                    self.partition.config.run_id: (
                        SUCCESSOR_MAXIMUM_NEW_ATTEMPTS
                    )
                },
            },
            "partition": {
                "partition_id": self.partition.partition_id,
                "run_id": self.partition.config.run_id,
                "config_hash": self.partition.config.config_hash,
                "scope": self.partition.config.scope_payload(),
                "required_prefix": {
                    "pages": PREFIX_PAGE_COUNT,
                    "records": PREFIX_RECORD_COUNT,
                    "next_sequence": RESUME_SEQUENCE,
                    "next_offset": RESUME_OFFSET,
                    "pages_evidence": [
                        {
                            "sequence": spec.sequence,
                            "offset": spec.offset,
                            "request_hash": spec.request_hash,
                            "response_sha256": response_hash,
                            "record_count": (
                                self.partition.config.page_size
                            ),
                            "is_final_page": False,
                        }
                        for spec, response_hash in zip(
                            specs[:PREFIX_PAGE_COUNT],
                            EXPECTED_PREFIX_RESPONSE_HASHES,
                            strict=True,
                        )
                    ],
                },
                "conditional_request_slots": [
                    {
                        "sequence": spec.sequence,
                        "offset": spec.offset,
                        "request_hash": spec.request_hash,
                    }
                    for spec in specs[PREFIX_PAGE_COUNT:]
                ],
            },
            "execution_policy": {
                "official_api_only": True,
                "html_scraping": False,
                "automatic_retries": 0,
                "request_interval_seconds": (
                    self.partition.config.request_interval_seconds
                ),
                "hourly_request_limit": (
                    self.partition.config.hourly_request_limit
                ),
                "runner_cumulative_attempt_ceiling": TOTAL_PAGE_SLOTS,
                "credential_value_printed_or_persisted": False,
            },
            "post_acquisition": {
                "reuse_existing_partition_validator": True,
                "run_complete_offline_test_suite": True,
                "model_fitting": False,
            },
        }

    @property
    def fingerprint(self) -> str:
        """Return a deterministic, path-independent continuation identity."""
        return _sha256_json(self.identity_payload())

    @property
    def authorization_id(self) -> str:
        """Return the stable successor authorization identifier."""
        return f"m3.6-2026-q2-{self.fingerprint[:16]}"

    @property
    def output_directory(self) -> Path:
        """Return the local credential-free report directory."""
        return (
            self.completion_plan.output_directory
            / "2026_q2_continuation"
        )

    def public_payload(self) -> dict[str, object]:
        """Return the complete portable continuation plan."""
        return {
            **self.identity_payload(),
            "continuation_plan_fingerprint": self.fingerprint,
            "successor_authorization_id": self.authorization_id,
            "authenticated_requests_performed_by_planning": 0,
            "api_key_read_by_planning": False,
        }


@dataclass(frozen=True, slots=True)
class Q2ContinuationGate:
    """Credential-free successor budget and checkpoint state."""

    authorization_id: str
    plan_fingerprint: str
    new_attempts_used: int
    new_attempts_remaining: int
    total_request_count: int
    records_seen: int
    accepted_page_count: int
    next_sequence: int
    next_offset: int
    run_status: str
    successful_new_pages: int = 0
    transport_failure_attempt_id: int | None = None
    gateway_timeout_attempt_id: int | None = None
    retry_pending: bool = False

    @property
    def complete(self) -> bool:
        return self.run_status == "complete"

    def payload(self) -> dict[str, object]:
        return {
            "authorization_id": self.authorization_id,
            "continuation_plan_fingerprint": self.plan_fingerprint,
            "request_accounting": {
                "successor_attempts_used": self.new_attempts_used,
                "successor_attempts_remaining": self.new_attempts_remaining,
                "successor_attempt_ceiling": (
                    SUCCESSOR_MAXIMUM_NEW_ATTEMPTS
                ),
                "successful_new_pages": self.successful_new_pages,
                "transport_failure_attempt_id": (
                    self.transport_failure_attempt_id
                ),
                "gateway_timeout_attempt_id": (
                    self.gateway_timeout_attempt_id
                ),
                "retry_pending": self.retry_pending,
                "ledger_attempts_total": (
                    SUCCESSOR_BASELINE_TOTAL_ATTEMPTS
                    + self.new_attempts_used
                ),
            },
            "partition": {
                "partition_id": PARTITION_ID,
                "run_id": RUN_ID,
                "status": self.run_status,
                "request_count": self.total_request_count,
                "records_seen": self.records_seen,
                "accepted_page_count": self.accepted_page_count,
                "next_sequence": self.next_sequence,
                "next_offset": self.next_offset,
            },
        }


def create_q2_continuation_plan(
    repository_root: Path,
) -> Q2ContinuationPlan:
    """Build the exact continuation without reading runtime state."""
    completion = create_completion_plan(
        repository_root,
        maximum_new_http_attempts=DEFAULT_NEW_HTTP_ATTEMPT_CEILING,
    )
    if completion.plan_fingerprint != PREDECESSOR_PLAN_FINGERPRINT:
        raise CampaignError("The reviewed predecessor plan changed.")
    partition = next(
        (
            item
            for item in completion.partitions
            if item.partition_id == PARTITION_ID
        ),
        None,
    )
    if partition is None:
        raise CampaignError("The completion plan lacks 2026-Q2.")
    if (
        partition.config.run_id != RUN_ID
        or partition.config.config_hash != CONFIG_HASH
        or partition.config.max_requests != TOTAL_PAGE_SLOTS
        or partition.maximum_new_http_attempts != TOTAL_PAGE_SLOTS
    ):
        raise CampaignError("The reviewed 2026-Q2 acquisition identity changed.")
    specs = partition.request_specs
    if (
        len(specs) != TOTAL_PAGE_SLOTS
        or [item.sequence for item in specs]
        != list(range(1, TOTAL_PAGE_SLOTS + 1))
        or [item.offset for item in specs]
        != list(range(0, TOTAL_PAGE_SLOTS * 100, 100))
    ):
        raise CampaignError("The reviewed 2026-Q2 request slots changed.")
    return Q2ContinuationPlan(
        repository_root=repository_root.resolve(),
        completion_plan=completion,
        partition=partition,
    )


def _json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CampaignError(f"Cannot read {label}: {path}.") from error
    if not isinstance(value, dict):
        raise CampaignError(f"{label} must be a JSON object.")
    return value


def _checkpoint(plan: Q2ContinuationPlan) -> dict[str, Any]:
    return _json_object(
        plan.partition.config.run_directory / "checkpoint.json",
        label="2026-Q2 checkpoint",
    )


def _verify_prefix(
    plan: Q2ContinuationPlan,
    checkpoint: Mapping[str, Any],
) -> None:
    pages = checkpoint.get("pages")
    if not isinstance(pages, list) or len(pages) < PREFIX_PAGE_COUNT:
        raise CampaignError("2026-Q2 lacks the certified eight-page prefix.")
    cache = CacheStore(plan.partition.config.cache_directory)
    for index in range(PREFIX_PAGE_COUNT):
        sequence = index + 1
        page = pages[index]
        if not isinstance(page, Mapping):
            raise CampaignError("A certified prefix page is malformed.")
        spec = request_spec(plan.partition.config, sequence)
        expected_response_hash = EXPECTED_PREFIX_RESPONSE_HASHES[index]
        if (
            int(page.get("sequence", -1)) != sequence
            or str(page.get("request_hash", "")) != spec.request_hash
            or str(page.get("response_sha256", ""))
            != expected_response_hash
            or int(page.get("record_count", -1))
            != plan.partition.config.page_size
            or bool(page.get("is_final_page"))
            or page.get("source_kind") != "network"
        ):
            raise CampaignError(
                f"Certified 2026-Q2 prefix page {sequence} changed."
            )
        cached = cache.get(spec)
        if (
            cached is None
            or cached.response_sha256 != expected_response_hash
            or cached.record_count != plan.partition.config.page_size
            or response_record_count(cached.body)
            != plan.partition.config.page_size
        ):
            raise CampaignError(
                f"Certified 2026-Q2 cache page {sequence} changed."
            )


def _verify_initial_checkpoint(plan: Q2ContinuationPlan) -> None:
    checkpoint = _checkpoint(plan)
    _verify_prefix(plan, checkpoint)
    run = checkpoint.get("run")
    requests = checkpoint.get("requests")
    if not isinstance(run, Mapping) or not isinstance(requests, list):
        raise CampaignError("The 2026-Q2 checkpoint structure changed.")
    expected = {
        "run_id": RUN_ID,
        "config_hash": CONFIG_HASH,
        "status": "budget_exhausted",
        "request_count": PREFIX_PAGE_COUNT,
        "cache_hit_count": 0,
        "records_seen": PREFIX_RECORD_COUNT,
        "next_sequence": RESUME_SEQUENCE,
        "next_offset": RESUME_OFFSET,
    }
    if any(run.get(key) != value for key, value in expected.items()):
        raise CampaignError(
            "2026-Q2 is not at the reviewed sequence-9 resume checkpoint."
        )
    if len(requests) != PREFIX_PAGE_COUNT or any(
        not isinstance(row, Mapping)
        or int(row.get("request_id", -1))
        != SUCCESSOR_BASELINE_REQUEST_ID - PREFIX_PAGE_COUNT + index
        or int(row.get("sequence", -1)) != index
        or int(row.get("offset_value", -1)) != (index - 1) * 100
        or row.get("outcome") != "success"
        or int(row.get("http_status") or 0) != 200
        for index, row in enumerate(requests, start=1)
    ):
        raise CampaignError("The certified 2026-Q2 request ledger changed.")


def inspect_predecessor(
    plan: Q2ContinuationPlan,
) -> dict[str, object]:
    """Verify the exhausted predecessor and exact frozen Q2 checkpoint."""
    verify_public_plan_artifact(plan.completion_plan)
    preflight = load_approved_preflight(
        plan.completion_plan,
        expected_fingerprint=PREDECESSOR_PREFLIGHT_FINGERPRINT,
    )
    _verify_baseline_ledger(plan.completion_plan)
    q2_2024_pages = _verify_q2_prefix(plan.completion_plan, preflight)
    pilot_pages = _verify_pilot_cache(plan.completion_plan)
    verify_completed_prefix(plan.completion_plan)
    (
        used,
        unresolved,
        recoverable_attempt_ids,
        recoverable_run_ids,
    ) = _verify_postbaseline_attempts(plan.completion_plan)
    _verify_new_cache_lineage(plan.completion_plan)
    with StateStore(plan.partition.config.state_path) as state:
        predecessor = state.campaign_request_budget(
            PREDECESSOR_AUTHORIZATION_ID
        )
        accounting = state.campaign_request_budget_accounting(
            PREDECESSOR_AUTHORIZATION_ID
        )
    if (
        predecessor is None
        or not predecessor["is_active"]
        or predecessor["plan_fingerprint"]
        != PREDECESSOR_PLAN_FINGERPRINT
        or int(predecessor["baseline_request_id"])
        != PREDECESSOR_BASELINE_REQUEST_ID
        or int(predecessor["maximum_new_attempts"])
        != PREDECESSOR_MAXIMUM_NEW_ATTEMPTS
        or accounting is None
        or int(accounting["new_attempts_used"])
        != PREDECESSOR_MAXIMUM_NEW_ATTEMPTS
        or int(accounting["remaining_new_attempts"]) != 0
        or int(accounting["cumulative_expansion_attempts"])
        != SUCCESSOR_BASELINE_EXPANSION_ATTEMPTS
        or int(accounting["total_attempts"])
        != SUCCESSOR_BASELINE_TOTAL_ATTEMPTS
        or int(accounting["unresolved_started_attempts"]) != 0
        or used != PREDECESSOR_MAXIMUM_NEW_ATTEMPTS
        or unresolved != 0
        or recoverable_attempt_ids
        or recoverable_run_ids
    ):
        raise CampaignError(
            "The predecessor authorization is not exactly exhausted at Q2."
        )
    _verify_initial_checkpoint(plan)
    return {
        "status": "ready_to_activate",
        "predecessor": {
            "authorization_id": PREDECESSOR_AUTHORIZATION_ID,
            "plan_fingerprint": PREDECESSOR_PLAN_FINGERPRINT,
            "new_attempts_used": used,
            "new_attempts_remaining": 0,
            "cumulative_expansion_attempts": (
                SUCCESSOR_BASELINE_EXPANSION_ATTEMPTS
            ),
            "total_ledger_attempts": SUCCESSOR_BASELINE_TOTAL_ATTEMPTS,
            "verified_2024_q2_prefix_pages": q2_2024_pages,
            "verified_pilot_pages": pilot_pages,
            "unresolved_attempts": unresolved,
        },
        "continuation_plan_fingerprint": plan.fingerprint,
        "successor_authorization_id": plan.authorization_id,
        "authenticated_requests_performed": 0,
        "api_key_read": False,
    }


def activate_successor_budget(
    plan: Q2ContinuationPlan,
) -> Q2ContinuationGate:
    """Atomically supersede the exhausted budget without reading a key."""
    inspect_predecessor(plan)
    with StateStore(plan.partition.config.state_path) as state:
        state.supersede_campaign_request_budget(
            predecessor_authorization_id=PREDECESSOR_AUTHORIZATION_ID,
            authorization_id=plan.authorization_id,
            plan_fingerprint=plan.fingerprint,
            baseline_request_id=SUCCESSOR_BASELINE_REQUEST_ID,
            baseline_total_attempts=SUCCESSOR_BASELINE_TOTAL_ATTEMPTS,
            baseline_expansion_attempts=(
                SUCCESSOR_BASELINE_EXPANSION_ATTEMPTS
            ),
            maximum_new_attempts=SUCCESSOR_MAXIMUM_NEW_ATTEMPTS,
            allowed_runs={RUN_ID: SUCCESSOR_MAXIMUM_NEW_ATTEMPTS},
            baseline_excluded_run_ids=(PILOT_RUN_ID,),
        )
    return verify_successor_budget(plan)


def _successor_attempt_rows(
    state_path: Path,
) -> list[dict[str, Any]]:
    connection = sqlite3.connect(
        f"file:{state_path.resolve()}?mode=ro",
        uri=True,
    )
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT request_id, run_id, request_hash, sequence, offset_value,
                   outcome, http_status, response_sha256, response_path,
                   record_count, error_text
            FROM requests
            WHERE request_id > ?
            ORDER BY request_id
            """,
            (SUCCESSOR_BASELINE_REQUEST_ID,),
        ).fetchall()
    finally:
        connection.close()
    return [dict(row) for row in rows]


def _verify_successor_attempts(
    plan: Q2ContinuationPlan,
    rows: list[dict[str, Any]],
) -> tuple[int, int | None, int | None, bool]:
    specs = plan.partition.request_specs[PREFIX_PAGE_COUNT:]
    if len(rows) > SUCCESSOR_MAXIMUM_NEW_ATTEMPTS:
        raise CampaignError("The Q2 successor request ceiling was exceeded.")
    successful_pages = 0
    failure_attempt_id: int | None = None
    gateway_timeout_attempt_id: int | None = None
    retry_pending = False
    index = 0
    while index < len(rows):
        row = rows[index]
        if successful_pages >= len(specs):
            raise CampaignError("The Q2 successor page slots were exceeded.")
        spec = specs[successful_pages]
        if (
            int(row["request_id"])
            != SUCCESSOR_BASELINE_REQUEST_ID + index + 1
            or row["run_id"] != RUN_ID
            or int(row["sequence"]) != spec.sequence
            or int(row["offset_value"]) != spec.offset
            or row["request_hash"] != spec.request_hash
        ):
            raise CampaignError(
                "A successor attempt is failed, unresolved, or outside the "
                "exact Q2 request sequence."
            )
        if (
            row["outcome"] == "success"
            and int(row["http_status"] or 0) == 200
            and isinstance(row["response_sha256"], str)
            and len(row["response_sha256"]) == 64
        ):
            successful_pages += 1
            index += 1
            continue
        if (
            failure_attempt_id is not None
            or not is_no_response_transport_failure(row)
        ):
            raise CampaignError(
                "Only one no-response Q2 transport failure is recoverable."
            )
        failure_attempt_id = int(row["request_id"])
        index += 1
        if index == len(rows):
            retry_pending = True
            break

        retry = rows[index]
        is_gateway_timeout = (
            int(retry["request_id"])
            == SUCCESSOR_BASELINE_REQUEST_ID + index + 1
            and retry["run_id"] == RUN_ID
            and int(retry["sequence"]) == spec.sequence
            and int(retry["offset_value"]) == spec.offset
            and retry["request_hash"] == spec.request_hash
            and retry["outcome"] == "http_error"
            and int(retry["http_status"] or 0) == 504
            and retry["response_sha256"] is None
            and retry["response_path"] is None
            and retry["record_count"] is None
            and str(retry["error_text"] or "").startswith(
                "Liquipedia API returned HTTP 504:"
            )
        )
        if is_gateway_timeout:
            gateway_timeout_attempt_id = int(retry["request_id"])
            index += 1
            if index == len(rows):
                retry_pending = True
                break
            retry = rows[index]
        if (
            int(retry["request_id"])
            != SUCCESSOR_BASELINE_REQUEST_ID + index + 1
            or retry["run_id"] != RUN_ID
            or int(retry["sequence"]) != spec.sequence
            or int(retry["offset_value"]) != spec.offset
            or retry["request_hash"] != spec.request_hash
            or retry["outcome"] != "success"
            or int(retry["http_status"] or 0) != 200
            or not isinstance(retry["response_sha256"], str)
            or len(retry["response_sha256"]) != 64
        ):
            raise CampaignError(
                "The one Q2 transport failure was not followed by an exact "
                "successful manual retry."
            )
        successful_pages += 1
        index += 1
    return (
        successful_pages,
        failure_attempt_id,
        gateway_timeout_attempt_id,
        retry_pending,
    )


def _verify_runtime_checkpoint(
    plan: Q2ContinuationPlan,
    *,
    successor_attempts: int,
    successful_new_pages: int,
    transport_failure_attempt_id: int | None,
    gateway_timeout_attempt_id: int | None,
    retry_pending: bool,
) -> Q2ContinuationGate:
    checkpoint = _checkpoint(plan)
    _verify_prefix(plan, checkpoint)
    run = checkpoint.get("run")
    pages = checkpoint.get("pages")
    requests = checkpoint.get("requests")
    if (
        not isinstance(run, Mapping)
        or not isinstance(pages, list)
        or not isinstance(requests, list)
    ):
        raise CampaignError("The Q2 runtime checkpoint is malformed.")
    if (
        run.get("run_id") != RUN_ID
        or run.get("config_hash") != CONFIG_HASH
        or int(run.get("request_count", -1))
        != PREFIX_PAGE_COUNT + successor_attempts
        or int(run.get("cache_hit_count", -1)) != 0
        or len(requests) != PREFIX_PAGE_COUNT + successor_attempts
        or len(pages) != PREFIX_PAGE_COUNT + successful_new_pages
    ):
        raise CampaignError("The Q2 runtime checkpoint does not reconcile.")
    sequences = [
        int(page.get("sequence", -1))
        for page in pages
        if isinstance(page, Mapping)
    ]
    if sequences != list(range(1, len(pages) + 1)):
        raise CampaignError("The Q2 accepted pages are not contiguous.")
    final_flags = [
        bool(page.get("is_final_page"))
        for page in pages
        if isinstance(page, Mapping)
    ]
    status = str(run.get("status"))
    if status == "complete":
        if (
            retry_pending
            or not final_flags
            or final_flags != [False] * (len(final_flags) - 1) + [True]
            or int(pages[-1].get("record_count", -1))
            >= plan.partition.config.page_size
        ):
            raise CampaignError("The completed Q2 terminal page is invalid.")
    else:
        if any(final_flags):
            raise CampaignError("An incomplete Q2 checkpoint has a terminal page.")
        if (retry_pending and status != "failed") or (
            not retry_pending and status == "failed"
        ):
            raise CampaignError(
                "Q2 failed status must correspond exactly to the pending "
                "manual timeout retry."
            )
        expected_sequence = RESUME_SEQUENCE + successful_new_pages
        expected_offset = RESUME_OFFSET + successful_new_pages * 100
        if (
            int(run.get("next_sequence", -1)) != expected_sequence
            or int(run.get("next_offset", -1)) != expected_offset
            or status not in {"budget_exhausted", "failed", "running"}
        ):
            raise CampaignError("The Q2 resume cursor changed unexpectedly.")
    records_seen = sum(
        int(page.get("record_count", -1))
        for page in pages
        if isinstance(page, Mapping)
    )
    if records_seen != int(run.get("records_seen", -1)):
        raise CampaignError("The Q2 record count does not reconcile.")
    return Q2ContinuationGate(
        authorization_id=plan.authorization_id,
        plan_fingerprint=plan.fingerprint,
        new_attempts_used=successor_attempts,
        new_attempts_remaining=(
            SUCCESSOR_MAXIMUM_NEW_ATTEMPTS - successor_attempts
        ),
        total_request_count=int(run["request_count"]),
        records_seen=records_seen,
        accepted_page_count=len(pages),
        next_sequence=int(run["next_sequence"]),
        next_offset=int(run["next_offset"]),
        run_status=status,
        successful_new_pages=successful_new_pages,
        transport_failure_attempt_id=transport_failure_attempt_id,
        gateway_timeout_attempt_id=gateway_timeout_attempt_id,
        retry_pending=retry_pending,
    )


def verify_successor_budget(
    plan: Q2ContinuationPlan,
) -> Q2ContinuationGate:
    """Reconstruct the successor gate across process restarts."""
    with StateStore(plan.partition.config.state_path) as state:
        predecessor = state.campaign_request_budget(
            PREDECESSOR_AUTHORIZATION_ID
        )
        successor = state.campaign_request_budget(plan.authorization_id)
        accounting = state.campaign_request_budget_accounting(
            plan.authorization_id
        )
    if (
        predecessor is None
        or predecessor["is_active"]
        or predecessor["plan_fingerprint"]
        != PREDECESSOR_PLAN_FINGERPRINT
        or int(predecessor["maximum_new_attempts"])
        != PREDECESSOR_MAXIMUM_NEW_ATTEMPTS
    ):
        raise CampaignError(
            "The exhausted predecessor authorization was not preserved."
        )
    if (
        successor is None
        or not successor["is_active"]
        or successor["plan_fingerprint"] != plan.fingerprint
        or int(successor["baseline_request_id"])
        != SUCCESSOR_BASELINE_REQUEST_ID
        or int(successor["baseline_total_attempts"])
        != SUCCESSOR_BASELINE_TOTAL_ATTEMPTS
        or int(successor["baseline_expansion_attempts"])
        != SUCCESSOR_BASELINE_EXPANSION_ATTEMPTS
        or int(successor["maximum_new_attempts"])
        != SUCCESSOR_MAXIMUM_NEW_ATTEMPTS
        or successor["baseline_excluded_run_ids"] != [PILOT_RUN_ID]
        or successor["allowed_runs"]
        != {RUN_ID: SUCCESSOR_MAXIMUM_NEW_ATTEMPTS}
        or accounting is None
    ):
        raise CampaignError("The Q2 successor authorization changed.")
    used = int(accounting["new_attempts_used"])
    if (
        int(accounting["remaining_new_attempts"])
        != SUCCESSOR_MAXIMUM_NEW_ATTEMPTS - used
        or int(accounting["unresolved_started_attempts"]) != 0
        or accounting["per_run_attempts"] != {RUN_ID: used}
    ):
        raise CampaignError("The Q2 successor request accounting changed.")
    rows = _successor_attempt_rows(plan.partition.config.state_path)
    if len(rows) != used:
        raise CampaignError("The Q2 successor ledger count does not reconcile.")
    (
        successful_new_pages,
        transport_failure_attempt_id,
        gateway_timeout_attempt_id,
        retry_pending,
    ) = _verify_successor_attempts(plan, rows)
    gate = _verify_runtime_checkpoint(
        plan,
        successor_attempts=used,
        successful_new_pages=successful_new_pages,
        transport_failure_attempt_id=transport_failure_attempt_id,
        gateway_timeout_attempt_id=gateway_timeout_attempt_id,
        retry_pending=retry_pending,
    )
    if gate.complete and gate.new_attempts_used == 0:
        raise CampaignError("Q2 cannot complete without a terminal successor page.")
    return gate


def inspect_unresolved_read_timeout(
    plan: Q2ContinuationPlan,
) -> dict[str, object]:
    """Verify the exact orphaned sequence-9 attempt without mutation."""
    _verify_initial_checkpoint(plan)
    spec = plan.partition.request_specs[PREFIX_PAGE_COUNT]
    cache = CacheStore(plan.partition.config.cache_directory)
    if cache.get(spec) is not None:
        raise CampaignError(
            "Sequence 9 has cache data; offline timeout recovery is unsafe."
        )
    with StateStore(plan.partition.config.state_path) as state:
        predecessor = state.campaign_request_budget(
            PREDECESSOR_AUTHORIZATION_ID
        )
        successor = state.campaign_request_budget(plan.authorization_id)
        accounting = state.campaign_request_budget_accounting(
            plan.authorization_id
        )
        run = state.run(RUN_ID)
        accepted_pages = state.accepted_pages(RUN_ID)
    if (
        predecessor is None
        or predecessor["is_active"]
        or predecessor["plan_fingerprint"]
        != PREDECESSOR_PLAN_FINGERPRINT
        or successor is None
        or not successor["is_active"]
        or successor["plan_fingerprint"] != plan.fingerprint
        or int(successor["baseline_request_id"])
        != SUCCESSOR_BASELINE_REQUEST_ID
        or int(successor["maximum_new_attempts"])
        != SUCCESSOR_MAXIMUM_NEW_ATTEMPTS
        or successor["allowed_runs"]
        != {RUN_ID: SUCCESSOR_MAXIMUM_NEW_ATTEMPTS}
        or accounting is None
        or int(accounting["new_attempts_used"]) != 1
        or int(accounting["remaining_new_attempts"])
        != SUCCESSOR_MAXIMUM_NEW_ATTEMPTS - 1
        or int(accounting["unresolved_started_attempts"]) != 1
        or accounting["per_run_attempts"] != {RUN_ID: 1}
        or run["status"] != "budget_exhausted"
        or int(run["request_count"]) != PREFIX_PAGE_COUNT + 1
        or int(run["records_seen"]) != PREFIX_RECORD_COUNT
        or int(run["next_sequence"]) != RESUME_SEQUENCE
        or int(run["next_offset"]) != RESUME_OFFSET
        or len(accepted_pages) != PREFIX_PAGE_COUNT
    ):
        raise CampaignError(
            "The live ledger is not the exact recoverable Q2 timeout state."
        )
    rows = _successor_attempt_rows(plan.partition.config.state_path)
    if len(rows) != 1:
        raise CampaignError(
            "Timeout recovery requires exactly one successor attempt."
        )
    row = rows[0]
    if (
        int(row["request_id"]) != SUCCESSOR_BASELINE_REQUEST_ID + 1
        or row["run_id"] != RUN_ID
        or row["request_hash"] != spec.request_hash
        or int(row["sequence"]) != spec.sequence
        or int(row["offset_value"]) != spec.offset
        or row["outcome"] != "started"
        or any(
            row[name] is not None
            for name in (
                "http_status",
                "response_sha256",
                "response_path",
                "record_count",
                "error_text",
            )
        )
    ):
        raise CampaignError(
            "Request 146 is not the exact no-payload sequence-9 attempt."
        )
    return {
        "status": "ready_for_offline_recovery",
        "continuation_plan_fingerprint": plan.fingerprint,
        "authorization_id": plan.authorization_id,
        "request_id": int(row["request_id"]),
        "run_id": RUN_ID,
        "sequence": spec.sequence,
        "offset": spec.offset,
        "request_hash": spec.request_hash,
        "cache_entry_present": False,
        "response_metadata_or_payload_persisted": False,
        "attempt_remains_charged": True,
        "authenticated_requests_performed": 0,
        "api_key_read": False,
    }


def write_read_timeout_recovery_artifacts(
    plan: Q2ContinuationPlan,
    gate: Q2ContinuationGate,
) -> tuple[Path, Path]:
    """Write credential-free evidence of the exact offline recovery."""
    payload = {
        "read_timeout_recovery_schema_version": (
            READ_TIMEOUT_RECOVERY_SCHEMA_VERSION
        ),
        "continuation_plan_fingerprint": plan.fingerprint,
        "successor_authorization_id": plan.authorization_id,
        "recovered_at_utc": datetime.now(UTC).isoformat(),
        "request_id": SUCCESSOR_BASELINE_REQUEST_ID + 1,
        "handling": {
            "outcome": "http_error",
            "http_status": None,
            "response_sha256": None,
            "response_path": None,
            "record_count": None,
            "attempt_remains_charged": True,
            "automatic_retry_performed": False,
            "manual_retry_pending": True,
        },
        "gate": gate.payload(),
        "authenticated_requests_performed_by_recovery": 0,
        "api_key_read_by_recovery": False,
        "credential_value_printed_or_persisted": False,
    }
    lines = [
        "# 2026-Q2 Response-Read Timeout Recovery",
        "",
        f"- Continuation fingerprint: `{plan.fingerprint}`",
        f"- Recovered request: `{SUCCESSOR_BASELINE_REQUEST_ID + 1}`",
        "- Outcome: `http_error` with no persisted response metadata or payload",
        "- Attempt remains charged: `yes`",
        "- Automatic retry performed: `no`",
        "- Manual retry pending: `yes`",
        "- Authenticated requests made by recovery: `0`",
        "- API key read: `no`",
        "",
    ]
    return _write_json_markdown(
        plan.output_directory / "read_timeout_recovery.json",
        plan.output_directory / "read_timeout_recovery.md",
        payload,
        "\n".join(lines),
    )


def recover_unresolved_read_timeout(
    plan: Q2ContinuationPlan,
) -> tuple[Q2ContinuationGate, tuple[Path, Path]]:
    """Close only request 146 and retain it as a charged failed attempt."""
    evidence = inspect_unresolved_read_timeout(plan)
    with StateStore(plan.partition.config.state_path) as state:
        state.recover_latest_started_read_timeout(
            request_id=int(evidence["request_id"]),
            run_id=RUN_ID,
            sequence=int(evidence["sequence"]),
            offset_value=int(evidence["offset"]),
            request_hash=str(evidence["request_hash"]),
        )
        state.write_checkpoint(plan.partition.config)
    gate = verify_successor_budget(plan)
    if (
        gate.transport_failure_attempt_id
        != SUCCESSOR_BASELINE_REQUEST_ID + 1
        or not gate.retry_pending
        or gate.successful_new_pages != 0
        or gate.new_attempts_used != 1
    ):
        raise CampaignError("The offline Q2 timeout recovery did not reconcile.")
    paths = write_read_timeout_recovery_artifacts(plan, gate)
    return gate, paths


def _completed_historical_prefix(
    plan: Q2ContinuationPlan,
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (item.partition_id, item.config.run_id)
        for item in plan.completion_plan.partitions
        if (
            item.kind != "cached_pilot"
            and item.ordinal <= plan.partition.ordinal
        )
    )


def _write_json_markdown(
    json_path: Path,
    markdown_path: Path,
    payload: Mapping[str, Any],
    markdown: str,
) -> tuple[Path, Path]:
    atomic_write(
        json_path,
        (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
    )
    atomic_write(markdown_path, markdown.encode("utf-8"))
    return json_path, markdown_path


def write_plan_artifacts(
    plan: Q2ContinuationPlan,
) -> tuple[Path, Path]:
    """Write portable planning evidence without inspecting credentials."""
    payload = plan.public_payload()
    lines = [
        "# 2026-Q2 Continuation Plan",
        "",
        f"- Plan fingerprint: `{plan.fingerprint}`",
        f"- Successor authorization: `{plan.authorization_id}`",
        (
            f"- Existing prefix: `{PREFIX_PAGE_COUNT}` pages / "
            f"`{PREFIX_RECORD_COUNT}` records"
        ),
        f"- Resume cursor: sequence `{RESUME_SEQUENCE}`, offset `{RESUME_OFFSET}`",
        f"- Maximum new authenticated attempts: `{SUCCESSOR_MAXIMUM_NEW_ATTEMPTS}`",
        "- API key read: `no`",
        "- Authenticated requests made: `0`",
        "",
    ]
    return _write_json_markdown(
        plan.output_directory / "continuation_plan.json",
        plan.output_directory / "continuation_plan.md",
        payload,
        "\n".join(lines),
    )


def write_authorization_artifacts(
    plan: Q2ContinuationPlan,
    gate: Q2ContinuationGate,
) -> tuple[Path, Path]:
    """Record credential-free proof of the active successor ceiling."""
    payload = {
        "continuation_plan_fingerprint": plan.fingerprint,
        "successor_authorization_id": plan.authorization_id,
        "activated_at_utc": datetime.now(UTC).isoformat(),
        "gate": gate.payload(),
        "authenticated_requests_performed_by_activation": 0,
        "api_key_read_by_activation": False,
        "credential_value_printed_or_persisted": False,
    }
    lines = [
        "# 2026-Q2 Continuation Authorization",
        "",
        f"- Plan fingerprint: `{plan.fingerprint}`",
        f"- Authorization: `{plan.authorization_id}`",
        f"- New attempts used: `{gate.new_attempts_used}`",
        f"- New attempts remaining: `{gate.new_attempts_remaining}`",
        "- API key read: `no`",
        "- Authenticated requests made by activation: `0`",
        "",
    ]
    return _write_json_markdown(
        plan.output_directory / "continuation_authorization.json",
        plan.output_directory / "continuation_authorization.md",
        payload,
        "\n".join(lines),
    )


def write_completion_report(
    plan: Q2ContinuationPlan,
    *,
    before: Q2ContinuationGate,
    after: Q2ContinuationGate,
    validation: PartitionValidationMetrics,
    tests: Mapping[str, object],
) -> tuple[Path, Path]:
    """Write the final credential-free acquisition and validation report."""
    attempts = after.new_attempts_used - before.new_attempts_used
    attempt_rows = _successor_attempt_rows(
        plan.partition.config.state_path
    )
    outcome_counts: dict[str, int] = {}
    for row in attempt_rows:
        outcome = str(row["outcome"])
        outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1
    payload = {
        "continuation_report_schema_version": (
            CONTINUATION_REPORT_SCHEMA_VERSION
        ),
        "continuation_plan_fingerprint": plan.fingerprint,
        "successor_authorization_id": plan.authorization_id,
        "completed_at_utc": datetime.now(UTC).isoformat(),
        "http_attempts_this_execution": attempts,
        "http_attempts_since_successor_activation": (
            after.new_attempts_used
        ),
        "http_outcome_counts_since_successor_activation": dict(
            sorted(outcome_counts.items())
        ),
        "records_collected_this_execution": (
            after.records_seen - before.records_seen
        ),
        "accepted_pages_total": after.accepted_page_count,
        "accepted_records_total": after.records_seen,
        "before": before.payload(),
        "after": after.payload(),
        "validation": validation.to_payload(),
        "offline_tests": dict(tests),
        "credential_policy": {
            "credential_value_printed": False,
            "credential_value_persisted": False,
            "credential_path_persisted": False,
        },
        "model_fitting_performed": False,
    }
    semantic = dict(payload)
    semantic.pop("completed_at_utc")
    payload["report_fingerprint"] = _sha256_json(semantic)
    lines = [
        "# Milestone 3.6 — 2026-Q2 Completion",
        "",
        f"- Status: `complete_validated`",
        f"- Report fingerprint: `{payload['report_fingerprint']}`",
        f"- HTTP attempts in successful resume: `{attempts}`",
        (
            "- HTTP attempts since successor activation: "
            f"`{after.new_attempts_used}`"
        ),
        (
            "- HTTP outcomes since successor activation: "
            f"`{payload['http_outcome_counts_since_successor_activation']}`"
        ),
        (
            "- Records collected: "
            f"`{payload['records_collected_this_execution']}`"
        ),
        f"- Accepted pages: `{after.accepted_page_count}`",
        f"- Total partition records: `{after.records_seen}`",
        f"- Matches: `{validation.normalized_matches}`",
        f"- Games: `{validation.normalized_games}`",
        f"- Eligible supervised games: `{validation.eligible_games}`",
        f"- Excluded supervised games: `{validation.excluded_games}`",
        f"- Eligibility: `{validation.eligibility_percentage}%`",
        f"- Offline tests: `{tests.get('summary')}`",
        "- Credential value printed or persisted: `no`",
        "- Model fitting performed: `no`",
        "",
    ]
    return _write_json_markdown(
        plan.output_directory / "continuation_report.json",
        plan.output_directory / "continuation_report.md",
        payload,
        "\n".join(lines),
    )


def execute_q2_continuation(
    plan: Q2ContinuationPlan,
    *,
    api_key_loader: Callable[[], str],
    timeout_seconds: float = 30.0,
    runner: BackfillRunner | None = None,
    validator: Callable[..., PartitionValidationMetrics] = (
        validate_completed_partition
    ),
    test_runner: Callable[[Path], dict[str, object]] = (
        run_offline_test_suite
    ),
) -> tuple[
    Q2ContinuationGate,
    PartitionValidationMetrics,
    dict[str, object],
    tuple[Path, Path],
]:
    """Complete Q2, validate it, run tests, and write the final report."""
    with campaign_execution_lock(plan.completion_plan):
        before = verify_successor_budget(plan)
        if before.complete:
            raise CampaignError(
                "2026-Q2 is already complete; use offline verification."
            )
        if before.new_attempts_remaining <= 0:
            raise CampaignError(
                "The Q2 successor ceiling is exhausted before a terminal page."
            )

        api_key = api_key_loader()
        try:
            result = (runner or BackfillRunner()).run(
                plan.partition.config,
                api_key=api_key,
                timeout_seconds=timeout_seconds,
                max_network_attempts=TOTAL_PAGE_SLOTS,
                required_cache_prefix_pages=PREFIX_PAGE_COUNT,
            )
        finally:
            api_key = ""
        if result.status != "complete":
            raise CampaignError(
                "2026-Q2 did not reach a terminal page within the bounded "
                f"continuation: status={result.status}."
            )

        validation = validator(
            partition_id=PARTITION_ID,
            config=plan.partition.config,
            completed_prefix=_completed_historical_prefix(plan),
            repository_root=plan.repository_root,
        )
        tests = test_runner(plan.repository_root)
        after = verify_successor_budget(plan)
        if not after.complete:
            raise CampaignError(
                "Q2 lost terminal completion after offline validation."
            )
        report_paths = write_completion_report(
            plan,
            before=before,
            after=after,
            validation=validation,
            tests=tests,
        )
    return after, validation, tests, report_paths
