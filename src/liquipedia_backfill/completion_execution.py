"""Restart-safe execution coordination for Milestone 3.6.

The coordinator is intentionally thin.  It binds the approved completion
plan to persistent request-budget state, verifies immutable prerequisite
evidence, delegates HTTP work to :class:`BackfillRunner`, and delegates all
post-acquisition data work to the existing finalization and validation
layers.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from .cache import CacheStore, atomic_write
from .campaign import (
    PILOT_RUN_ID,
    VERIFIED_PILOT_PAGES,
    CampaignError,
    _sha256_json,
)
from .completion import (
    EXPECTED_EXISTING_EXPANSION_ATTEMPTS,
    EXPECTED_LEDGER_ATTEMPTS_WITH_PILOT,
    FINAL_RELEASE_ALIAS,
    Q2_2024_PARTITION_ID,
    Q2_2024_PREFIX_PAGE_COUNT,
    CompletionPartition,
    CompletionPlan,
)
from .envelope import response_record_count
from .planner import request_spec
from .publication import (
    PartitionRun,
    PublicationMode,
    verify_partition,
    verify_partition_sequence,
)
from .runner import BackfillRunner, default_fetcher
from .state import StateStore, is_no_response_transport_failure


EXECUTION_AUTHORIZATION_SCHEMA_VERSION = (
    "liquipedia-history-completion-authorization-v1"
)
EXECUTION_PROGRESS_SCHEMA_VERSION = (
    "liquipedia-history-completion-progress-v1"
)
BASELINE_REQUEST_ID = EXPECTED_LEDGER_ATTEMPTS_WITH_PILOT
AUTHORIZATION_ID_PREFIX = "m3.6-completion"
APPROVED_EXCLUSION_REASONS = frozenset(
    {
        "invalid_series_result",
        "match_not_finished",
        "invalid_game_result",
        "missing_game_winner",
        "missing_or_invalid_sides",
        "incomplete_team1_picks",
        "incomplete_team2_picks",
        "incomplete_team1_bans",
        "incomplete_team2_bans",
        "duplicate_picked_hero",
        "missing_game_duration",
    }
)


@dataclass(frozen=True, slots=True)
class ExecutionGate:
    """Credential-free evidence available before an API key is read."""

    authorization_id: str
    plan_fingerprint: str
    preflight_fingerprint: str
    baseline_ledger_attempts: int
    baseline_expansion_attempts: int
    new_attempts_used: int
    new_attempts_remaining: int
    cumulative_expansion_attempts: int
    cumulative_expansion_ceiling: int
    next_partition_id: str | None
    q2_cached_pages_verified: int
    pilot_cached_pages_verified: int
    unresolved_attempts: int
    recoverable_no_response_attempt_ids: tuple[int, ...]

    def payload(self) -> dict[str, object]:
        """Return a secret-free, path-independent report payload."""
        return {
            "execution_authorization_schema_version": (
                EXECUTION_AUTHORIZATION_SCHEMA_VERSION
            ),
            "authorization_id": self.authorization_id,
            "plan_fingerprint": self.plan_fingerprint,
            "preflight_fingerprint": self.preflight_fingerprint,
            "baseline": {
                "ledger_http_attempts": self.baseline_ledger_attempts,
                "expansion_http_attempts": self.baseline_expansion_attempts,
            },
            "budget": {
                "new_http_attempts_used": self.new_attempts_used,
                "new_http_attempts_remaining": self.new_attempts_remaining,
                "cumulative_expansion_attempts": (
                    self.cumulative_expansion_attempts
                ),
                "cumulative_expansion_ceiling": (
                    self.cumulative_expansion_ceiling
                ),
            },
            "resume": {
                "next_partition": self.next_partition_id,
                "unresolved_attempts": self.unresolved_attempts,
                "recoverable_no_response_attempt_ids": list(
                    self.recoverable_no_response_attempt_ids
                ),
            },
            "cache_reuse": {
                "q2_verified_prefix_pages": self.q2_cached_pages_verified,
                "q2_prefix_requires_new_http_attempts": False,
                "pilot_verified_pages": self.pilot_cached_pages_verified,
                "pilot_requires_new_http_attempts": False,
            },
            "credential_policy": {
                "credential_value_printed": False,
                "credential_value_persisted": False,
                "credential_path_persisted": False,
            },
        }


def authorization_id(plan: CompletionPlan) -> str:
    """Return the stable identifier for the one approved global budget."""
    return f"{AUTHORIZATION_ID_PREFIX}-{plan.plan_fingerprint[:16]}"


def live_partitions(
    plan: CompletionPlan,
) -> tuple[CompletionPartition, ...]:
    """Return exactly the partitions authorized to create new HTTP attempts."""
    return tuple(
        partition
        for partition in plan.partitions
        if partition.maximum_new_http_attempts > 0
    )


def allowed_run_budgets(plan: CompletionPlan) -> dict[str, int]:
    """Return the exact run allowlist and cumulative per-run attempt caps."""
    return {
        partition.config.run_id: partition.maximum_new_http_attempts
        for partition in live_partitions(plan)
    }


def _completion_artifact_path(plan: CompletionPlan, name: str) -> Path:
    return plan.output_directory / name


def load_approved_preflight(
    plan: CompletionPlan,
    *,
    expected_fingerprint: str,
) -> dict[str, Any]:
    """Load and cryptographically verify the reviewed preflight artifact."""
    path = _completion_artifact_path(plan, "completion_preflight.json")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CampaignError(
            f"Cannot read the approved M3.6 preflight: {path}"
        ) from error
    if not isinstance(payload, dict):
        raise CampaignError("The approved M3.6 preflight is not an object.")
    actual = str(payload.get("completion_preflight_fingerprint", ""))
    if actual != expected_fingerprint:
        raise CampaignError("The approved M3.6 preflight fingerprint changed.")
    semantic = dict(payload)
    semantic.pop("completion_preflight_fingerprint", None)
    if _sha256_json(semantic) != actual:
        raise CampaignError("The approved M3.6 preflight content changed.")
    if payload.get("completion_plan_fingerprint") != plan.plan_fingerprint:
        raise CampaignError("Preflight and completion-plan identities differ.")
    return payload


def verify_public_plan_artifact(plan: CompletionPlan) -> None:
    """Verify that the checked-in credential-free plan matches code."""
    path = _completion_artifact_path(plan, "completion_plan.json")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CampaignError(
            f"Cannot read the approved M3.6 plan: {path}"
        ) from error
    if payload != plan.public_payload():
        raise CampaignError("The approved M3.6 plan artifact changed.")


def _read_only_connection(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise CampaignError(f"Request ledger is missing: {path}")
    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _verify_baseline_ledger(
    plan: CompletionPlan,
) -> None:
    """Recheck the immutable 65-attempt starting ledger without mutation."""
    with _read_only_connection(
        plan.base_campaign.config.state_path
    ) as connection:
        rows = connection.execute(
            """
            SELECT request_id, run_id, outcome, http_status
            FROM requests
            WHERE request_id <= ?
            ORDER BY request_id
            """,
            (BASELINE_REQUEST_ID,),
        ).fetchall()
    if [int(row["request_id"]) for row in rows] != list(
        range(1, BASELINE_REQUEST_ID + 1)
    ):
        raise CampaignError("The certified baseline ledger is not contiguous.")
    if any(
        row["outcome"] != "success" or int(row["http_status"] or 0) != 200
        for row in rows
    ):
        raise CampaignError(
            "A certified baseline HTTP outcome is no longer successful."
        )
    expansion = sum(row["run_id"] != PILOT_RUN_ID for row in rows)
    if expansion != EXPECTED_EXISTING_EXPANSION_ATTEMPTS:
        raise CampaignError("The certified expansion baseline changed.")


def _verify_q2_prefix(
    plan: CompletionPlan,
    preflight: Mapping[str, Any],
) -> int:
    """Reverify all eight pinned Q2 responses from immutable cache."""
    q2 = next(
        item
        for item in plan.partitions
        if item.partition_id == Q2_2024_PARTITION_ID
    )
    evidence = preflight.get("q2_cache_prefix")
    if not isinstance(evidence, Mapping):
        raise CampaignError("The preflight lacks Q2 cache evidence.")
    pinned = evidence.get("verified_prefix_hashes")
    if not isinstance(pinned, list) or len(pinned) != (
        Q2_2024_PREFIX_PAGE_COUNT
    ):
        raise CampaignError("The Q2 preflight cache prefix is incomplete.")
    cache = CacheStore(q2.config.cache_directory)
    for sequence, item in enumerate(pinned, start=1):
        if not isinstance(item, Mapping):
            raise CampaignError("Malformed Q2 cache-prefix evidence.")
        spec = request_spec(q2.config, sequence)
        cached = cache.get(spec)
        if cached is None:
            raise CampaignError(f"Q2 cached page {sequence} is missing.")
        if (
            int(item.get("sequence", -1)) != sequence
            or item.get("request_hash") != spec.request_hash
            or item.get("response_sha256") != cached.response_sha256
            or cached.record_count != q2.config.page_size
            or response_record_count(cached.body) != cached.record_count
        ):
            raise CampaignError(
                f"Q2 cached page {sequence} no longer matches preflight."
            )
    return len(pinned)


def _verify_pilot_cache(plan: CompletionPlan) -> int:
    """Reverify the exact July 2026 pilot without network access."""
    pilot = plan.partitions[-1]
    if pilot.config.run_id != PILOT_RUN_ID:
        raise CampaignError("The completion plan no longer ends in the pilot.")
    cache = CacheStore(pilot.config.cache_directory)
    for expected in VERIFIED_PILOT_PAGES:
        spec = request_spec(pilot.config, expected.sequence)
        cached = cache.get(spec)
        if cached is None:
            raise CampaignError(
                f"Pilot cached page {expected.sequence} is missing."
            )
        if (
            spec.request_hash != expected.request_hash
            or cached.response_sha256 != expected.response_sha256
            or cached.record_count != expected.record_count
            or response_record_count(cached.body) != expected.record_count
        ):
            raise CampaignError(
                f"Pilot cached page {expected.sequence} changed."
            )
    return len(VERIFIED_PILOT_PAGES)


def _completed_prefix_selections(
    plan: CompletionPlan,
    *,
    include_live: bool,
) -> tuple[PartitionRun, ...]:
    """Return the manifest-backed chronological prefix currently on disk."""
    selections: list[PartitionRun] = []
    for partition in plan.partitions:
        if partition.kind == "cached_pilot":
            break
        manifest = partition.config.run_directory / "manifest.json"
        if not manifest.is_file():
            if (
                not include_live
                and partition.maximum_new_http_attempts > 0
            ):
                break
            break
        selections.append(
            PartitionRun(
                partition_id=partition.partition_id,
                run_id=partition.config.run_id,
            )
        )
    return tuple(selections)


def verify_completed_prefix(plan: CompletionPlan) -> tuple[PartitionRun, ...]:
    """Reverify the complete, contiguous, manifest-backed historical prefix."""
    selections = _completed_prefix_selections(plan, include_live=True)
    if len(selections) < 9:
        raise CampaignError(
            "The reviewed completed prefix through 2024-Q1 is missing."
        )
    verified = tuple(
        verify_partition(
            selection,
            run_root=plan.base_campaign.config.run_root,
        )
        for selection in selections
    )
    verify_partition_sequence(
        verified,
        mode=PublicationMode.PROVISIONAL_PREFIX,
        repository_root=plan.repository_root,
    )
    return selections


def _run_rows(
    state_path: Path,
) -> tuple[dict[str, Any], ...]:
    with _read_only_connection(state_path) as connection:
        rows = connection.execute(
            "SELECT * FROM runs ORDER BY started_at_utc, run_id"
        ).fetchall()
    return tuple(dict(row) for row in rows)


def _attempt_rows(
    state_path: Path,
) -> tuple[dict[str, Any], ...]:
    with _read_only_connection(state_path) as connection:
        rows = connection.execute(
            "SELECT * FROM requests ORDER BY request_id"
        ).fetchall()
    return tuple(dict(row) for row in rows)


def _next_live_partition(
    plan: CompletionPlan,
    *,
    recoverable_run_ids: frozenset[str] = frozenset(),
) -> CompletionPartition | None:
    """Derive the one legal next partition from persistent run state."""
    rows = {str(row["run_id"]): row for row in _run_rows(
        plan.base_campaign.config.state_path
    )}
    found_incomplete = False
    next_partition: CompletionPartition | None = None
    for partition in live_partitions(plan):
        row = rows.get(partition.config.run_id)
        if row is None:
            if next_partition is None:
                next_partition = partition
                found_incomplete = True
            continue
        status = str(row["status"])
        if not found_incomplete and status == "complete":
            if (partition.config.run_directory / "manifest.json").is_file():
                continue
            return partition
        if next_partition is None:
            next_partition = partition
            found_incomplete = True
        if next_partition.partition_id != partition.partition_id:
            raise CampaignError(
                "A later M3.6 partition has state before its predecessor "
                "completed."
            )
        if status in {"failed", "budget_exhausted"}:
            if (
                status == "failed"
                and partition.config.run_id in recoverable_run_ids
            ):
                return partition
            raise CampaignError(
                f"{partition.partition_id} has terminal status {status}."
            )
        if status not in {"planned", "running"}:
            raise CampaignError(
                f"{partition.partition_id} has unexpected status {status}."
            )
    return next_partition


def _verify_postbaseline_attempts(
    plan: CompletionPlan,
) -> tuple[int, int, tuple[int, ...], frozenset[str]]:
    """Reject unresolved, failed, duplicated, or out-of-plan attempts."""
    attempts = _attempt_rows(plan.base_campaign.config.state_path)
    post = [
        row for row in attempts if int(row["request_id"]) > BASELINE_REQUEST_ID
    ]
    expected_ids = list(
        range(
            BASELINE_REQUEST_ID + 1,
            BASELINE_REQUEST_ID + len(post) + 1,
        )
    )
    if [int(row["request_id"]) for row in post] != expected_ids:
        raise CampaignError("Post-baseline request IDs are not contiguous.")
    allowed = allowed_run_budgets(plan)
    if any(str(row["run_id"]) not in allowed for row in post):
        raise CampaignError("The post-baseline ledger contains an unknown run.")
    unresolved = sum(row["outcome"] == "started" for row in post)
    if unresolved:
        raise CampaignError(
            "An unresolved started HTTP attempt requires manual review."
        )

    by_slot: dict[tuple[str, int, int], list[dict[str, Any]]] = {}
    request_hash_slots: dict[tuple[str, str], tuple[int, int]] = {}
    for row in post:
        run_id = str(row["run_id"])
        sequence = int(row["sequence"])
        offset = int(row["offset_value"])
        request_hash = str(row["request_hash"])
        slot = (sequence, offset)
        hash_key = (run_id, request_hash)
        previous_slot = request_hash_slots.setdefault(hash_key, slot)
        if previous_slot != slot:
            raise CampaignError(
                "One request hash appears in multiple page slots."
            )
        by_slot.setdefault((run_id, sequence, offset), []).append(row)

    pending: list[dict[str, Any]] = []
    for (run_id, sequence, offset), rows in sorted(by_slot.items()):
        hashes = {str(row["request_hash"]) for row in rows}
        if len(hashes) != 1 or len(rows) > 2:
            raise CampaignError(
                "A post-baseline page slot has incompatible attempt "
                f"history: {run_id} sequence {sequence} offset {offset}."
            )
        first = rows[0]
        if len(rows) == 1:
            if (
                first["outcome"] == "success"
                and int(first["http_status"] or 0) == 200
            ):
                continue
            if is_no_response_transport_failure(first):
                pending.append(first)
                continue
        elif (
            is_no_response_transport_failure(first)
            and rows[1]["outcome"] == "success"
            and int(rows[1]["http_status"] or 0) == 200
        ):
            continue
        row = rows[-1]
        raise CampaignError(
            "A previous M3.6 HTTP attempt is not safely recoverable: "
            f"request_id={row['request_id']}, "
            f"outcome={row['outcome']}, http_status={row['http_status']}."
        )
    if len(pending) > 1:
        raise CampaignError(
            "Multiple no-response transport failures require review."
        )
    if pending and int(pending[0]["request_id"]) != int(post[-1]["request_id"]):
        raise CampaignError(
            "A no-response transport failure is not the latest attempt."
        )
    pending_ids = tuple(int(row["request_id"]) for row in pending)
    pending_runs = frozenset(str(row["run_id"]) for row in pending)
    return len(post), unresolved, pending_ids, pending_runs


def _verify_new_cache_lineage(plan: CompletionPlan) -> None:
    """Require every non-baseline cache page to have one successful ledger row."""
    attempts = _attempt_rows(plan.base_campaign.config.state_path)
    evidence = {
        (str(row["run_id"]), str(row["request_hash"])): row
        for row in attempts
        if int(row["request_id"]) > BASELINE_REQUEST_ID
    }
    for partition in live_partitions(plan):
        cache = CacheStore(partition.config.cache_directory)
        for spec in partition.request_specs:
            cached = cache.get(spec)
            if cached is None:
                continue
            if (
                partition.partition_id == Q2_2024_PARTITION_ID
                and spec.sequence <= Q2_2024_PREFIX_PAGE_COUNT
            ):
                continue
            row = evidence.get((partition.config.run_id, spec.request_hash))
            if (
                row is None
                or row["outcome"] != "success"
                or row["response_sha256"] != cached.response_sha256
            ):
                raise CampaignError(
                    "A post-baseline cache page lacks matching successful "
                    f"ledger evidence: {partition.partition_id} "
                    f"sequence {spec.sequence}."
                )


@contextmanager
def campaign_execution_lock(plan: CompletionPlan) -> Iterator[Path]:
    """Hold one nonblocking process-wide lock for the entire live command."""
    path = (
        plan.base_campaign.config.raw_root
        / "m3_6_completion_execution.lock"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise CampaignError(
                "Another M3.6 completion executor already holds the lock."
            ) from error
        try:
            yield path
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def activate_global_budget(
    plan: CompletionPlan,
    *,
    preflight_fingerprint: str,
) -> ExecutionGate:
    """Persist the approved hard ceiling after all baseline checks pass."""
    verify_public_plan_artifact(plan)
    preflight = load_approved_preflight(
        plan,
        expected_fingerprint=preflight_fingerprint,
    )
    _verify_baseline_ledger(plan)
    q2_pages = _verify_q2_prefix(plan, preflight)
    pilot_pages = _verify_pilot_cache(plan)
    verify_completed_prefix(plan)
    with StateStore(plan.base_campaign.config.state_path) as state:
        state.activate_campaign_request_budget(
            authorization_id=authorization_id(plan),
            plan_fingerprint=plan.plan_fingerprint,
            baseline_request_id=BASELINE_REQUEST_ID,
            baseline_total_attempts=EXPECTED_LEDGER_ATTEMPTS_WITH_PILOT,
            baseline_expansion_attempts=(
                EXPECTED_EXISTING_EXPANSION_ATTEMPTS
            ),
            maximum_new_attempts=plan.maximum_new_http_attempts,
            allowed_runs=allowed_run_budgets(plan),
            baseline_excluded_run_ids=(PILOT_RUN_ID,),
        )
    return verify_execution_gate(
        plan,
        preflight_fingerprint=preflight_fingerprint,
        expected_q2_pages=q2_pages,
        expected_pilot_pages=pilot_pages,
    )


def verify_execution_gate(
    plan: CompletionPlan,
    *,
    preflight_fingerprint: str,
    expected_q2_pages: int = Q2_2024_PREFIX_PAGE_COUNT,
    expected_pilot_pages: int = len(VERIFIED_PILOT_PAGES),
) -> ExecutionGate:
    """Reconstruct and verify the persistent execution state on every resume."""
    verify_public_plan_artifact(plan)
    preflight = load_approved_preflight(
        plan,
        expected_fingerprint=preflight_fingerprint,
    )
    _verify_baseline_ledger(plan)
    q2_pages = _verify_q2_prefix(plan, preflight)
    pilot_pages = _verify_pilot_cache(plan)
    if q2_pages != expected_q2_pages or pilot_pages != expected_pilot_pages:
        raise CampaignError("Certified cache-page counts changed.")
    verify_completed_prefix(plan)
    (
        used,
        unresolved,
        recoverable_attempt_ids,
        recoverable_run_ids,
    ) = _verify_postbaseline_attempts(plan)
    _verify_new_cache_lineage(plan)
    with StateStore(plan.base_campaign.config.state_path) as state:
        budget = state.campaign_request_budget(authorization_id(plan))
        accounting = state.campaign_request_budget_accounting(
            authorization_id(plan)
        )
    if budget is None or accounting is None:
        raise CampaignError(
            "The approved persistent M3.6 request budget is not active."
        )
    if budget["plan_fingerprint"] != plan.plan_fingerprint:
        raise CampaignError("Persistent budget and completion plan differ.")
    if int(budget["baseline_request_id"]) != BASELINE_REQUEST_ID:
        raise CampaignError("Persistent budget baseline changed.")
    if int(budget["maximum_new_attempts"]) != (
        plan.maximum_new_http_attempts
    ):
        raise CampaignError("Persistent global HTTP ceiling changed.")
    if {
        str(key): int(value)
        for key, value in accounting["allowed_runs"].items()
    } != allowed_run_budgets(plan):
        raise CampaignError("Persistent allowed-run budgets changed.")
    if int(accounting["new_attempts_used"]) != used:
        raise CampaignError("Persistent request accounting does not reconcile.")
    if int(accounting["unresolved_started_attempts"]) != unresolved:
        raise CampaignError("Persistent unresolved-attempt count changed.")
    if used > plan.maximum_new_http_attempts:
        raise CampaignError("The global M3.6 HTTP ceiling was exceeded.")
    next_partition = _next_live_partition(
        plan,
        recoverable_run_ids=recoverable_run_ids,
    )
    return ExecutionGate(
        authorization_id=authorization_id(plan),
        plan_fingerprint=plan.plan_fingerprint,
        preflight_fingerprint=preflight_fingerprint,
        baseline_ledger_attempts=EXPECTED_LEDGER_ATTEMPTS_WITH_PILOT,
        baseline_expansion_attempts=EXPECTED_EXISTING_EXPANSION_ATTEMPTS,
        new_attempts_used=used,
        new_attempts_remaining=plan.maximum_new_http_attempts - used,
        cumulative_expansion_attempts=(
            EXPECTED_EXISTING_EXPANSION_ATTEMPTS + used
        ),
        cumulative_expansion_ceiling=(
            plan.cumulative_expansion_attempt_ceiling
        ),
        next_partition_id=(
            next_partition.partition_id if next_partition else None
        ),
        q2_cached_pages_verified=q2_pages,
        pilot_cached_pages_verified=pilot_pages,
        unresolved_attempts=unresolved,
        recoverable_no_response_attempt_ids=recoverable_attempt_ids,
    )


def partition_attempt_count(
    plan: CompletionPlan,
    partition: CompletionPartition,
) -> int:
    """Return the cumulative HTTP attempts already charged to one run."""
    with _read_only_connection(
        plan.base_campaign.config.state_path
    ) as connection:
        row = connection.execute(
            """
            SELECT COUNT(*) AS attempts
            FROM requests
            WHERE run_id = ? AND request_id > ?
            """,
            (partition.config.run_id, BASELINE_REQUEST_ID),
        ).fetchone()
    return int(row["attempts"])


def runner_attempt_ceiling(
    plan: CompletionPlan,
    partition: CompletionPartition,
    gate: ExecutionGate,
) -> int:
    """Derive the existing runner's cumulative per-run ceiling safely."""
    run_used = partition_attempt_count(plan, partition)
    partition_remaining = (
        partition.maximum_new_http_attempts - run_used
    )
    additional_allowed = min(
        gate.new_attempts_remaining,
        partition_remaining,
    )
    if additional_allowed <= 0:
        raise CampaignError(
            "No HTTP attempt remains before the next required page."
        )
    return run_used + additional_allowed


def _observed_fetcher(spec, api_key: str, timeout_seconds: float):
    """Emit credential-free request progress around the existing client."""
    print(
        "HTTP attempt starting: "
        f"sequence={spec.sequence} offset={spec.offset} "
        f"request_hash={spec.request_hash}",
        flush=True,
    )
    response = default_fetcher(spec, api_key, timeout_seconds)
    print(
        f"HTTP response accepted: status={response.status} "
        f"sequence={spec.sequence}",
        flush=True,
    )
    return response


def execute_one_partition(
    plan: CompletionPlan,
    partition: CompletionPartition,
    *,
    gate: ExecutionGate,
    api_key: str,
    timeout_seconds: float,
) -> object:
    """Run one chronological partition through the existing acquisition runner."""
    if gate.next_partition_id != partition.partition_id:
        raise CampaignError(
            f"{partition.partition_id} is not the derived next partition."
        )
    ceiling = runner_attempt_ceiling(plan, partition, gate)
    print(
        f"Partition {partition.partition_id}: run={partition.config.run_id}; "
        f"cumulative run ceiling={ceiling}; "
        f"global remaining={gate.new_attempts_remaining}; "
        f"required cache prefix={partition.required_cache_prefix_pages}",
        flush=True,
    )
    return BackfillRunner(fetcher=_observed_fetcher).run(
        partition.config,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
        max_network_attempts=ceiling,
        required_cache_prefix_pages=(
            partition.required_cache_prefix_pages
        ),
    )


def run_offline_test_suite(repository_root: Path) -> dict[str, object]:
    """Run the complete active suite without exposing credentials or network."""
    environment = os.environ.copy()
    environment["LIQUIPEDIA_API_KEY"] = ""
    environment["NO_NETWORK_TESTS"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=repository_root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    output = "\n".join(
        value.strip()
        for value in (completed.stdout, completed.stderr)
        if value.strip()
    )
    if completed.returncode != 0:
        if output:
            print(output, file=sys.stderr)
        raise CampaignError("The complete offline test suite failed.")
    summary = next(
        (
            line.strip()
            for line in reversed(output.splitlines())
            if " passed" in line
        ),
        "passed",
    )
    return {
        "command": ".venv/bin/python -m pytest -q",
        "passed": True,
        "summary": summary,
        "network_enabled": False,
        "credentials_available_to_tests": False,
    }


def _safe_relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as error:
        raise CampaignError(
            "Public M3.6 evidence must use repository-relative paths."
        ) from error


def write_authorization_evidence(
    plan: CompletionPlan,
    gate: ExecutionGate,
) -> tuple[Path, Path]:
    """Write compact, credential-free proof of the active hard ceiling."""
    payload = {
        **gate.payload(),
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        "paths": {
            "request_ledger": _safe_relative(
                plan.base_campaign.config.state_path,
                plan.repository_root,
            ),
            "immutable_cache": _safe_relative(
                plan.base_campaign.config.raw_root / "cache",
                plan.repository_root,
            ),
        },
    }
    json_path = _completion_artifact_path(
        plan,
        "execution_authorization.json",
    )
    markdown_path = _completion_artifact_path(
        plan,
        "execution_authorization.md",
    )
    atomic_write(
        json_path,
        (
            json.dumps(payload, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8"),
    )
    markdown = "\n".join(
        [
            "# Milestone 3.6 Execution Authorization",
            "",
            "Generated credential-free evidence.",
            "",
            f"- Authorization: `{gate.authorization_id}`",
            f"- Plan fingerprint: `{gate.plan_fingerprint}`",
            f"- Preflight fingerprint: `{gate.preflight_fingerprint}`",
            (
                "- New HTTP attempts: "
                f"`{gate.new_attempts_used}` used / "
                f"`{gate.new_attempts_remaining}` remaining / "
                "`80` maximum"
            ),
            (
                "- Cumulative expansion: "
                f"`{gate.cumulative_expansion_attempts}` / "
                f"`{gate.cumulative_expansion_ceiling}`"
            ),
            (
                "- Certified Q2 cache reuse: "
                f"`{gate.q2_cached_pages_verified}` pages"
            ),
            (
                "- Certified pilot cache reuse: "
                f"`{gate.pilot_cached_pages_verified}` pages"
            ),
            f"- Derived next partition: `{gate.next_partition_id}`",
            "- Credential value printed: `no`",
            "- Credential value or path persisted: `no`",
            "",
        ]
    )
    atomic_write(markdown_path, markdown.encode("utf-8"))
    return json_path, markdown_path


def progress_fingerprint(payload: Mapping[str, Any]) -> str:
    """Return the deterministic semantic fingerprint for a progress report."""
    semantic = dict(payload)
    semantic.pop("progress_fingerprint", None)
    semantic.pop("recorded_at_utc", None)
    return _sha256_json(semantic)


def write_progress_evidence(
    plan: CompletionPlan,
    *,
    gate: ExecutionGate,
    partition_results: Sequence[Mapping[str, Any]],
    stop_reason: str | None,
) -> tuple[Path, Path]:
    """Atomically update the credential-free campaign progress evidence."""
    semantic: dict[str, Any] = {
        "execution_progress_schema_version": (
            EXECUTION_PROGRESS_SCHEMA_VERSION
        ),
        "plan_fingerprint": gate.plan_fingerprint,
        "preflight_fingerprint": gate.preflight_fingerprint,
        "authorization_id": gate.authorization_id,
        "request_accounting": {
            "baseline_expansion_attempts": (
                gate.baseline_expansion_attempts
            ),
            "new_attempts_used": gate.new_attempts_used,
            "new_attempts_remaining": gate.new_attempts_remaining,
            "cumulative_expansion_attempts": (
                gate.cumulative_expansion_attempts
            ),
            "cumulative_expansion_ceiling": (
                gate.cumulative_expansion_ceiling
            ),
        },
        "next_partition": gate.next_partition_id,
        "partitions": list(partition_results),
        "stop_reason": stop_reason,
        "release": {
            "alias": FINAL_RELEASE_ALIAS,
            "ready_to_publish": (
                gate.next_partition_id is None and stop_reason is None
            ),
            "published_by_this_command": False,
        },
        "credential_policy": {
            "credential_value_printed": False,
            "credential_value_persisted": False,
            "credential_path_persisted": False,
        },
    }
    payload = {
        **semantic,
        "progress_fingerprint": _sha256_json(semantic),
        "recorded_at_utc": datetime.now(UTC).isoformat(),
    }
    json_path = _completion_artifact_path(plan, "execution_progress.json")
    markdown_path = _completion_artifact_path(plan, "execution_progress.md")
    atomic_write(
        json_path,
        (
            json.dumps(payload, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8"),
    )
    lines = [
        "# Milestone 3.6 Execution Progress",
        "",
        "Generated credential-free evidence.",
        "",
        f"- Progress fingerprint: `{payload['progress_fingerprint']}`",
        (
            "- New HTTP attempts: "
            f"`{gate.new_attempts_used}` used / "
            f"`{gate.new_attempts_remaining}` remaining"
        ),
        f"- Next partition: `{gate.next_partition_id}`",
        f"- Stop reason: `{stop_reason}`",
        "- Credential value printed or persisted: `no`",
        "",
        "| Partition | Status | Requests | Matches | Games | Eligible | "
        "Excluded | Eligibility |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in partition_results:
        lines.append(
            f"| {item.get('partition_id')} | {item.get('status')} | "
            f"{item.get('http_attempts')} | {item.get('matches')} | "
            f"{item.get('games')} | {item.get('eligible_games')} | "
            f"{item.get('excluded_games')} | "
            f"{item.get('eligibility_pct')}% |"
        )
    atomic_write(
        markdown_path,
        ("\n".join(lines) + "\n").encode("utf-8"),
    )
    return json_path, markdown_path


def report_sha256(path: Path) -> str:
    """Return a streaming SHA-256 for final report evidence."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
