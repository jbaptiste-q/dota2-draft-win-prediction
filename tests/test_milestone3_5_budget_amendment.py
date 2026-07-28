"""Offline tests for the approved 2024-Q1 budget amendment."""

from __future__ import annotations

import json
import shlex
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts.backfill_liquipedia_history import (
    make_config as make_backfill_config,
)
from scripts.backfill_liquipedia_history import (
    parse_args as parse_backfill_args,
)
from src.liquipedia_backfill.amendment import (
    Q1_2024_AMENDED_CONFIG_HASH,
    Q1_2024_AMENDED_RUN_ID,
    Q1_2024_AMENDED_TOTAL_PAGE_SLOTS,
    Q1_2024_MAX_NEW_HTTP_ATTEMPTS,
    Q1_2024_PARTITION_ID,
    create_2024_q1_budget_amendment,
    inspect_campaign_with_budget_amendment,
    write_budget_amendment_artifacts,
)
from src.liquipedia_backfill.cache import (
    CacheError,
    CacheStore,
    sha256_bytes,
)
from src.liquipedia_backfill.campaign import (
    CampaignConfig,
    PilotPageEvidence,
    check_partition_readiness,
    create_campaign_plan,
    ledger_request_row_count,
    with_pilot_evidence,
)
from src.liquipedia_backfill.client import HttpResponse
from src.liquipedia_backfill.runner import BackfillRunner
from src.liquipedia_backfill.state import StateError, StateStore


class FakeClock:
    """Deterministic clock with non-blocking rate-limit sleeps."""

    def __init__(self):
        self.value = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += timedelta(seconds=seconds)


def response_body(prefix: str, count: int) -> bytes:
    """Return one deterministic valid Liquipedia envelope."""
    return (
        json.dumps(
            {
                "result": [
                    {"match2id": f"{prefix}-{index:03d}"}
                    for index in range(count)
                ],
                "error": [],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def seed_partition(
    partition,
    bodies: tuple[bytes, ...],
    *,
    terminal_status: str | None = None,
) -> None:
    """Seed network-backed cache and ledger evidence through public APIs."""
    clock = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
    cache = CacheStore(partition.config.cache_directory)
    with StateStore(partition.config.state_path) as state:
        state.initialize_run(partition.config, now=clock)
        for sequence, body in enumerate(bodies, start=1):
            request = partition.request_specs[sequence - 1]
            count = len(json.loads(body)["result"])
            cached = cache.put_success(
                request,
                body=body,
                record_count=count,
                response_metadata={
                    "status": 200,
                    "content_type": "application/json",
                    "content_encoding": "gzip",
                },
                acquired_at_utc=clock.isoformat(),
            )
            attempt_id = state.start_network_attempt(
                partition.config.run_id,
                request,
                attempted_at=clock,
            )
            state.finish_network_attempt(
                attempt_id,
                outcome="success",
                http_status=200,
                response_sha256=cached.response_sha256,
                response_path=cached.response_path,
                record_count=count,
            )
            state.accept_page(
                partition.config.run_id,
                request,
                source_kind="network",
                response_sha256=cached.response_sha256,
                response_path=cached.response_path,
                record_count=count,
                is_final_page=count < partition.config.page_size,
                now=clock,
            )
            clock += timedelta(seconds=67)
        if terminal_status is not None:
            state.set_status(
                partition.config.run_id,
                terminal_status,
                now=clock,
            )
        state.write_checkpoint(partition.config)


def prepared_campaign(tmp_path: Path):
    """Create completed predecessors, exhausted Q1, and verified pilot."""
    base = CampaignConfig(repository_root=tmp_path)
    initial_plan = create_campaign_plan(base)
    pilot = initial_plan.partitions[-1]
    pilot_bodies = (
        response_body("pilot-1", 100),
        response_body("pilot-2", 8),
    )
    evidence = tuple(
        PilotPageEvidence(
            sequence=sequence,
            request_hash=pilot.request_specs[sequence - 1].request_hash,
            response_sha256=sha256_bytes(body),
            record_count=len(json.loads(body)["result"]),
            is_final_page=sequence == 2,
        )
        for sequence, body in enumerate(pilot_bodies, start=1)
    )
    campaign = with_pilot_evidence(base, evidence)
    plan = create_campaign_plan(campaign)

    for partition in plan.partitions[:8]:
        seed_partition(
            partition,
            (response_body(partition.partition_id, 1),),
        )

    q1 = plan.partitions[8]
    seed_partition(
        q1,
        tuple(
            response_body(f"q1-page-{sequence}", 100)
            for sequence in range(1, 9)
        ),
        terminal_status="budget_exhausted",
    )
    seed_partition(plan.partitions[-1], pilot_bodies)
    return campaign, plan


def scope_without_page_ceiling(config) -> dict[str, object]:
    """Return config identity excluding the sole amended value."""
    payload = config.scope_payload()
    payload.pop("max_requests")
    return payload


def test_amendment_is_deterministic_read_only_and_changes_only_budget(
    tmp_path: Path,
) -> None:
    campaign, plan = prepared_campaign(tmp_path)
    before = ledger_request_row_count(campaign.state_path)

    first = create_2024_q1_budget_amendment(plan)
    second = create_2024_q1_budget_amendment(plan)
    preflight = inspect_campaign_with_budget_amendment(plan, first)

    assert ledger_request_row_count(campaign.state_path) == before
    assert first.amendment_fingerprint == second.amendment_fingerprint
    assert first.effective_plan_fingerprint == second.effective_plan_fingerprint
    assert first.partition_id == Q1_2024_PARTITION_ID
    assert first.amended_config.run_id == Q1_2024_AMENDED_RUN_ID
    assert first.amended_config.config_hash == Q1_2024_AMENDED_CONFIG_HASH
    assert (
        first.amended_config.max_requests
        == Q1_2024_AMENDED_TOTAL_PAGE_SLOTS
    )
    assert (
        len(first.conditional_requests)
        == Q1_2024_MAX_NEW_HTTP_ATTEMPTS
    )
    assert [item.sequence for item in first.conditional_requests] == list(
        range(9, 21)
    )
    assert [item.offset for item in first.conditional_requests] == list(
        range(800, 2000, 100)
    )
    predecessor = plan.partitions[8].config
    assert (
        scope_without_page_ceiling(first.amended_config)
        == scope_without_page_ceiling(predecessor)
    )
    assert not first.amended_config.run_directory.exists()

    resume = preflight["resume"]
    assert resume["campaign_status"] == "ready_to_resume"
    assert resume["next_partition_id"] == "2024-Q1"
    assert resume["next_run_id"] == Q1_2024_AMENDED_RUN_ID
    assert resume["next_sequence"] == 9
    assert resume["next_offset"] == 800
    assert resume["partition_remaining_request_ceiling"] == 12
    assert (
        preflight["request_accounting"][
            "predecessor_http_attempts_carried_forward"
        ]
        == 8
    )
    assert preflight["request_accounting"]["amended_run_http_attempts"] == 0


def test_amended_runner_reuses_prefix_and_hard_stops_after_twelve_new_attempts(
    tmp_path: Path,
) -> None:
    _, plan = prepared_campaign(tmp_path)
    amendment = create_2024_q1_budget_amendment(plan)
    calls: list[int] = []

    def fetch(request, api_key, timeout):
        calls.append(request.sequence)
        return HttpResponse(
            body=response_body(f"live-{request.sequence}", 100),
            status=200,
            content_type="application/json",
            content_encoding="gzip",
        )

    result = BackfillRunner(
        fetcher=fetch,
        clock=FakeClock(),
        sleeper=FakeClock().sleep,
    ).run(
        amendment.amended_config,
        api_key="offline-test-key",
        max_network_attempts=amendment.maximum_new_http_attempts,
        required_cache_prefix_pages=8,
    )

    assert calls == list(range(9, 21))
    assert result.status == "budget_exhausted"
    assert result.request_count == 12
    assert result.cache_hit_count == 8
    assert result.accepted_page_count == 20

    with StateStore(amendment.amended_config.state_path) as state:
        predecessor = state.run(amendment.predecessor_run_id)
        amended = state.run(amendment.amended_config.run_id)
    assert predecessor["status"] == "budget_exhausted"
    assert predecessor["request_count"] == 8
    assert amended["request_count"] == 12

    preflight = inspect_campaign_with_budget_amendment(plan, amendment)
    assert preflight["resume"]["campaign_status"] == "blocked"
    assert preflight["resume"]["blocking_reason"] == (
        "2024-Q1:partition_budget_exhausted"
    )


def test_completed_amendment_advances_chronologically_and_counts_only_http(
    tmp_path: Path,
) -> None:
    _, plan = prepared_campaign(tmp_path)
    amendment = create_2024_q1_budget_amendment(plan)
    calls: list[int] = []
    clock = FakeClock()

    def fetch(request, api_key, timeout):
        calls.append(request.sequence)
        count = 100 if request.sequence == 9 else 7
        return HttpResponse(
            body=response_body(f"live-{request.sequence}", count),
            status=200,
            content_type="application/json",
            content_encoding="gzip",
        )

    result = BackfillRunner(
        fetcher=fetch,
        clock=clock,
        sleeper=clock.sleep,
    ).run(
        amendment.amended_config,
        api_key="offline-test-key",
        max_network_attempts=amendment.maximum_new_http_attempts,
        required_cache_prefix_pages=8,
    )
    assert result.status == "complete"
    assert calls == [9, 10]
    assert result.request_count == 2
    assert result.cache_hit_count == 8

    preflight = inspect_campaign_with_budget_amendment(plan, amendment)
    accounting = preflight["request_accounting"]
    assert accounting["amended_run_http_attempts"] == 2
    assert accounting["amended_run_cache_hits"] == 8
    assert accounting["m3_5_additional_attempts_used"] == 18
    assert accounting["m3_5_additional_attempts_remaining"] == 82
    assert preflight["resume"]["next_partition_id"] == "2024-Q2"
    readiness = check_partition_readiness(preflight, "2024-Q2")
    assert readiness["ready"] is True

    q2 = plan.partitions[9]
    seed_partition(q2, (response_body("q2-complete", 1),))
    later_amendment = create_2024_q1_budget_amendment(plan)
    assert (
        later_amendment.amendment_fingerprint
        == amendment.amendment_fingerprint
    )
    later = inspect_campaign_with_budget_amendment(plan, amendment)
    assert later["resume"]["next_partition_id"] == "2024-Q3"


def test_amendment_artifacts_and_command_are_secret_free_and_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    campaign, plan = prepared_campaign(tmp_path)
    amendment = create_2024_q1_budget_amendment(plan)
    marker = "LOCAL-SECRET-MUST-NOT-APPEAR"
    monkeypatch.setenv("LIQUIPEDIA_API_KEY", marker)
    before = ledger_request_row_count(campaign.state_path)

    first = write_budget_amendment_artifacts(amendment)
    first_json = first.json_path.read_bytes()
    first_markdown = first.markdown_path.read_bytes()
    second = write_budget_amendment_artifacts(amendment)

    assert ledger_request_row_count(campaign.state_path) == before
    assert second.json_path.read_bytes() == first_json
    assert second.markdown_path.read_bytes() == first_markdown
    combined = (first_json + first_markdown).decode("utf-8")
    assert marker not in combined
    assert "Apikey" not in combined
    assert ".secrets" not in combined
    assert "--max-requests 20" in combined
    assert "--max-network-attempts 12" in combined
    assert "--require-cache-prefix-pages 8" in combined
    assert "--confirm-live-request-budget 12" in combined

    flattened = amendment.recovery_command.replace("\\\n", " ")
    readiness_command, acquisition_command = flattened.split("&&", maxsplit=1)
    assert shlex.split(readiness_command)[-4:] == [
        "--check-partition-readiness",
        "2024-Q1",
        "--include-approved-amendment",
        "2024-Q1",
    ]
    tokens = shlex.split(acquisition_command)
    args = parse_backfill_args(tokens[2:])
    config = make_backfill_config(args)
    assert config.run_id == Q1_2024_AMENDED_RUN_ID
    assert config.config_hash == Q1_2024_AMENDED_CONFIG_HASH
    assert args.max_network_attempts == 12
    assert args.require_cache_prefix_pages == 8
    assert args.confirm_live_request_budget == 12


def test_runner_rejects_network_ceiling_above_page_slots(
    tmp_path: Path,
) -> None:
    _, plan = prepared_campaign(tmp_path)
    amendment = create_2024_q1_budget_amendment(plan)
    called = False

    def fetch(request, api_key, timeout):
        nonlocal called
        called = True
        raise AssertionError("fetch must not be called")

    with pytest.raises(ValueError, match="page-slot ceiling"):
        BackfillRunner(fetcher=fetch).run(
            amendment.amended_config,
            api_key="offline-test-key",
            max_network_attempts=21,
        )
    assert called is False


@pytest.mark.parametrize("failure_kind", ["missing", "tampered"])
def test_required_cache_prefix_fails_before_state_or_http(
    tmp_path: Path,
    failure_kind: str,
) -> None:
    campaign, plan = prepared_campaign(tmp_path)
    amendment = create_2024_q1_budget_amendment(plan)
    first = amendment.prefix_pages[0]
    response_path = (
        amendment.amended_config.cache_directory
        / first.request_hash
        / "response.json"
    )
    if failure_kind == "missing":
        response_path.unlink()
    else:
        response_path.write_bytes(response_body("tampered", 100))
    before = ledger_request_row_count(campaign.state_path)
    called = False

    def fetch(request, api_key, timeout):
        nonlocal called
        called = True
        raise AssertionError("fetch must not be called")

    with pytest.raises(CacheError):
        BackfillRunner(fetcher=fetch).run(
            amendment.amended_config,
            api_key="offline-test-key",
            max_network_attempts=12,
            required_cache_prefix_pages=8,
        )

    assert called is False
    assert ledger_request_row_count(campaign.state_path) == before
    with StateStore(campaign.state_path) as state:
        with pytest.raises(StateError, match="Unknown run"):
            state.run(amendment.amended_config.run_id)
