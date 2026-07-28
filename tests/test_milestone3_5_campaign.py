"""Offline tests for Milestone 3.5 campaign planning and coordination."""

from __future__ import annotations

import ast
import json
import shlex
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.liquipedia_backfill.cache import CacheStore, sha256_bytes
from src.liquipedia_backfill.campaign import (
    CAMPAIGN_MAX_ADDITIONAL_REQUESTS,
    PILOT_CONFIG_HASH,
    PILOT_RUN_ID,
    STAGE_B_COMMAND,
    CampaignConfig,
    CampaignError,
    PartitionRuntimeState,
    PilotPageEvidence,
    check_partition_readiness,
    create_campaign_plan,
    inspect_campaign,
    ledger_request_row_count,
    resolve_resume,
    with_pilot_evidence,
)
from src.liquipedia_backfill.campaign_reports import (
    VerificationEvidence,
    generate_campaign_artifacts,
)
from src.liquipedia_backfill.planner import request_spec
from src.liquipedia_backfill.state import StateStore
from scripts.backfill_liquipedia_history import (
    make_config as make_backfill_config,
)
from scripts.backfill_liquipedia_history import (
    parse_args as parse_backfill_args,
)


CANARY_CONFIG_HASH = (
    "36bbf248c8cfc2fe9c7505af9eabedcb2c39f31a9dbe7c424eb57e9b2257f477"
)
CANARY_REQUEST_HASHES = (
    "a1d14b750bc61ccb403aa57ecb1276e0aeefffebfbbb9ee84435c810fafcf621",
    "6fdcd3580cd1eb1ad6ce121e1367036cb723de488f4d5d92bebded1e1ea6d36a",
    "7eec2a674958ad83cd0a7e6f1417d5c33f9b5e2619a138bd58f69aeb2d204381",
    "67987592fcc87df00a8afcdc02698878fa4646c8f5bd90c0de9d05aa49875495",
    "9f559c7e03fa2d1471459f1903ec422eb466982160d2e247b1052b9ed37d6bce",
    "20c240d58cca2db084ea90beae848160429a8fafcb7ae5ed9f3326457b313a5a",
    "3b4c3c53cbcc9ed84441daee250b961b2dd117abda1b95402f1507e3448b5d2f",
    "394052143206af4d4136bc94db222da4dc05003ffb64c31a4f91e4edeeb20190",
)


def response_body(prefix: str, count: int) -> bytes:
    """Return one deterministic valid cached API response."""
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


def synthetic_campaign(
    tmp_path: Path,
) -> tuple[CampaignConfig, tuple[bytes, bytes]]:
    """Create a portable campaign whose pilot evidence uses test cache bytes."""
    base = CampaignConfig(repository_root=tmp_path)
    pilot = create_campaign_plan(base).partitions[-1]
    bodies = (
        response_body("pilot-page-1", 100),
        response_body("pilot-page-2", 8),
    )
    evidence = tuple(
        PilotPageEvidence(
            sequence=index,
            request_hash=pilot.request_specs[index - 1].request_hash,
            response_sha256=sha256_bytes(body),
            record_count=100 if index == 1 else 8,
            is_final_page=index == 2,
        )
        for index, body in enumerate(bodies, start=1)
    )
    return with_pilot_evidence(base, evidence), bodies


def seed_pages(
    partition,
    bodies: tuple[bytes, ...],
    *,
    record_network_attempts: bool,
) -> None:
    """Seed cache and SQLite through the existing validated state APIs."""
    clock = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
    cache = CacheStore(partition.config.cache_directory)
    with StateStore(partition.config.state_path) as state:
        state.initialize_run(partition.config, now=clock)
        for index, body in enumerate(bodies, start=1):
            spec = request_spec(partition.config, index)
            count = len(json.loads(body)["result"])
            cached = cache.put_success(
                spec,
                body=body,
                record_count=count,
                response_metadata={
                    "status": 200,
                    "content_type": "application/json",
                    "content_encoding": "gzip",
                },
                acquired_at_utc=clock.isoformat(),
            )
            if record_network_attempts:
                request_id = state.start_network_attempt(
                    partition.config.run_id,
                    spec,
                    attempted_at=clock,
                )
                state.finish_network_attempt(
                    request_id,
                    outcome="success",
                    http_status=200,
                    response_sha256=cached.response_sha256,
                    response_path=cached.response_path,
                    record_count=count,
                )
            state.accept_page(
                partition.config.run_id,
                spec,
                source_kind=(
                    "network" if record_network_attempts else "cache"
                ),
                response_sha256=cached.response_sha256,
                response_path=cached.response_path,
                record_count=count,
                is_final_page=count < partition.config.page_size,
                now=clock,
            )
            clock += timedelta(seconds=67)


def seeded_campaign(
    tmp_path: Path,
) -> tuple[CampaignConfig, object]:
    """Return a campaign with a complete, checksum-verified pilot."""
    campaign, pilot_bodies = synthetic_campaign(tmp_path)
    plan = create_campaign_plan(campaign)
    seed_pages(
        plan.partitions[-1],
        pilot_bodies,
        record_network_attempts=True,
    )
    return campaign, plan


def runtime_state(
    ordinal: int,
    partition_id: str,
    *,
    status: str,
    request_count: int = 0,
    next_sequence: int = 1,
    remaining_ceiling: int = 8,
    blocking_reason: str | None = None,
) -> PartitionRuntimeState:
    """Build compact deterministic state for pure resume-policy tests."""
    return PartitionRuntimeState(
        ordinal=ordinal,
        partition_id=partition_id,
        kind="historical_quarter",
        run_id=f"run-{partition_id}",
        ledger_status=status,
        effective_status=(
            "pending" if status in {"not_started", "planned"} else status
        ),
        request_count=request_count,
        cache_hit_count=0,
        records_seen=0,
        accepted_page_count=max(0, next_sequence - 1),
        next_sequence=next_sequence,
        next_offset=max(0, next_sequence - 1) * 100,
        remaining_request_ceiling=remaining_ceiling,
        verified_pages=(),
        next_request_cached=False,
        blocking_reason=blocking_reason,
    )


def test_campaign_has_exact_contiguous_19_partitions(tmp_path: Path) -> None:
    campaign = CampaignConfig(repository_root=tmp_path)
    partitions = create_campaign_plan(campaign).partitions

    assert len(partitions) == 19
    assert [partition.partition_id for partition in partitions[:-1]] == [
        f"{year}-Q{quarter}"
        for year in range(2022, 2027)
        for quarter in range(1, 5)
        if not (year == 2026 and quarter > 2)
    ]
    assert partitions[-1].partition_id == "2026-07-pilot"
    assert partitions[0].config.start_utc == datetime(
        2022, 1, 1, tzinfo=UTC
    )
    assert partitions[-1].config.end_utc == datetime(
        2026, 7, 27, tzinfo=UTC
    )
    assert all(
        left.config.end_utc == right.config.start_utc
        for left, right in zip(partitions, partitions[1:], strict=False)
    )
    assert all(
        partition.config.end_utc.month
        in {1, 4, 7, 10}
        for partition in partitions[:-1]
    )


def test_exact_plans_delegate_to_existing_partition_planner(
    tmp_path: Path,
) -> None:
    plan = create_campaign_plan(CampaignConfig(repository_root=tmp_path))
    canary = plan.partitions[0]
    pilot = plan.partitions[-1]

    assert plan.total_request_specs == 148
    assert plan.new_partition_request_specs == 144
    assert len(
        {
            request.request_hash
            for partition in plan.partitions
            for request in partition.request_specs
        }
    ) == 148
    assert canary.config.run_id == "m3_20220101_20220401_36bbf248c8cf"
    assert canary.config.config_hash == CANARY_CONFIG_HASH
    assert tuple(
        request.request_hash for request in canary.request_specs
    ) == CANARY_REQUEST_HASHES
    assert [request.offset for request in canary.request_specs] == list(
        range(0, 800, 100)
    )
    assert pilot.config.run_id == PILOT_RUN_ID
    assert pilot.config.config_hash == PILOT_CONFIG_HASH
    assert len(pilot.request_specs) == 4
    assert pilot.campaign_network_budget == 0
    assert all(
        request.parameters["order"] == "date ASC, match2id ASC"
        and request.parameters["limit"] == 100
        and request.parameters["rawstreams"] == "false"
        and request.parameters["streamurls"] == "false"
        for partition in plan.partitions
        for request in partition.request_specs
    )


def test_campaign_fingerprints_are_stable_and_path_independent(
    tmp_path: Path,
) -> None:
    first = CampaignConfig(repository_root=tmp_path / "one")
    second = CampaignConfig(repository_root=tmp_path / "two")
    first_plan = create_campaign_plan(first)
    second_plan = create_campaign_plan(second)

    assert first.config_fingerprint == second.config_fingerprint
    assert first.campaign_id == second.campaign_id
    assert first_plan.plan_fingerprint == second_plan.plan_fingerprint
    assert canonical_public(first_plan) == canonical_public(second_plan)

    different_estimate = replace(first, expected_successful_pages_min=74)
    smaller_budget = replace(first, max_additional_requests=99)
    assert different_estimate.config_fingerprint != first.config_fingerprint
    assert (
        create_campaign_plan(different_estimate).plan_fingerprint
        != first_plan.plan_fingerprint
    )
    assert smaller_budget.config_fingerprint != first.config_fingerprint
    assert (
        create_campaign_plan(smaller_budget).plan_fingerprint
        != first_plan.plan_fingerprint
    )


def canonical_public(plan) -> str:
    """Return stable JSON for a public campaign plan."""
    return json.dumps(plan.payload(), sort_keys=True, separators=(",", ":"))


def test_pilot_preflight_verifies_cache_and_selects_canary(
    tmp_path: Path,
) -> None:
    campaign, plan = seeded_campaign(tmp_path)
    before = ledger_request_row_count(campaign.state_path)
    first = inspect_campaign(plan)
    second = inspect_campaign(plan)
    after = ledger_request_row_count(campaign.state_path)

    assert first == second
    assert before == after == 2
    assert first["pilot_reuse"]["verified"] is True
    assert first["pilot_reuse"]["network_request_required"] is False
    assert first["pilot_reuse"]["records"] == 108
    assert first["request_accounting"]["m3_5_additional_attempts_used"] == 0
    assert first["resume"]["campaign_status"] == "ready_for_canary"
    assert first["resume"]["next_partition_id"] == "2022-Q1"
    assert first["resume"]["next_sequence"] == 1
    assert first["resume"]["additional_attempts_remaining"] == 100
    readiness = check_partition_readiness(first, "2022-Q1")
    assert readiness["ready"] is True
    with pytest.raises(CampaignError, match="not the deterministic next"):
        check_partition_readiness(first, "2022-Q2")


def test_completed_pilot_cache_is_reverified_and_tampering_blocks(
    tmp_path: Path,
) -> None:
    campaign, plan = seeded_campaign(tmp_path)
    pilot = plan.partitions[-1]
    first_spec = pilot.request_specs[0]
    response_path = (
        pilot.config.cache_directory
        / first_spec.request_hash
        / "response.json"
    )
    response_path.write_bytes(response_body("tampered", 100))

    with pytest.raises(CampaignError, match="cache verification failed"):
        inspect_campaign(plan)


def test_missing_pilot_ledger_never_claims_cache_reuse(tmp_path: Path) -> None:
    campaign = CampaignConfig(repository_root=tmp_path)
    plan = create_campaign_plan(campaign)

    assert not campaign.state_path.exists()
    with pytest.raises(CampaignError, match="pilot run is not complete"):
        inspect_campaign(plan)
    assert not campaign.state_path.exists()
    assert not campaign.raw_root.exists()


def test_resume_uses_existing_partition_cursor_then_advances(
    tmp_path: Path,
) -> None:
    campaign, plan = seeded_campaign(tmp_path)
    canary = plan.partitions[0]
    seed_pages(
        canary,
        (response_body("canary-page-1", 100),),
        record_network_attempts=True,
    )

    running = inspect_campaign(plan)
    assert running["resume"]["campaign_status"] == "ready_to_resume"
    assert running["resume"]["next_partition_id"] == "2022-Q1"
    assert running["resume"]["next_sequence"] == 2
    assert running["resume"]["next_offset"] == 100
    assert running["resume"]["additional_attempts_used"] == 1

    seed_pages(
        canary,
        (
            response_body("canary-page-1", 100),
            response_body("canary-page-2", 7),
        ),
        record_network_attempts=False,
    )
    advanced = inspect_campaign(plan)
    assert advanced["resume"]["next_partition_id"] == "2022-Q2"
    assert advanced["resume"]["next_sequence"] == 1


def test_failed_and_unresolved_partitions_block_resume(
    tmp_path: Path,
) -> None:
    campaign, plan = seeded_campaign(tmp_path)
    canary = plan.partitions[0]
    now = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    with StateStore(canary.config.state_path) as state:
        state.initialize_run(canary.config, now=now)
        attempt_id = state.start_network_attempt(
            canary.config.run_id,
            canary.request_specs[0],
            attempted_at=now,
        )

    unresolved = inspect_campaign(plan)
    assert unresolved["resume"]["campaign_status"] == "blocked"
    assert "unresolved_started_request" in unresolved["resume"]["blocking_reason"]

    with StateStore(canary.config.state_path) as state:
        state.finish_network_attempt(
            attempt_id,
            outcome="http_error",
            http_status=403,
            error_text="redacted test error",
        )
        state.set_status(canary.config.run_id, "failed", now=now)

    failed = inspect_campaign(plan)
    assert failed["resume"]["campaign_status"] == "blocked"
    assert "partition_failed" in failed["resume"]["blocking_reason"]


def test_finished_error_outcome_blocks_even_before_status_update(
    tmp_path: Path,
) -> None:
    campaign, plan = seeded_campaign(tmp_path)
    canary = plan.partitions[0]
    now = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    with StateStore(canary.config.state_path) as state:
        state.initialize_run(canary.config, now=now)
        attempt_id = state.start_network_attempt(
            canary.config.run_id,
            canary.request_specs[0],
            attempted_at=now,
        )
        state.finish_network_attempt(
            attempt_id,
            outcome="http_error",
            http_status=429,
            error_text="redacted test rate-limit error",
        )

    preflight = inspect_campaign(plan)
    assert preflight["resume"]["campaign_status"] == "blocked"
    assert (
        "unreviewed_unsuccessful_request:http_error"
        in preflight["resume"]["blocking_reason"]
    )
    with pytest.raises(CampaignError, match="not ready"):
        check_partition_readiness(preflight, "2022-Q1")


def test_campaign_budget_is_enforced_at_partition_boundary(
    tmp_path: Path,
) -> None:
    campaign = CampaignConfig(repository_root=tmp_path)
    states_at_92 = tuple(
        [
            runtime_state(
                ordinal,
                f"P{ordinal}",
                status="complete",
                request_count=(8 if ordinal <= 11 else 4),
                next_sequence=9,
                remaining_ceiling=0,
            )
            for ordinal in range(1, 13)
        ]
        + [
            runtime_state(
                13,
                "P13",
                status="not_started",
                remaining_ceiling=8,
            )
        ]
    )
    allowed = resolve_resume(campaign, states_at_92)
    assert allowed["additional_attempts_used"] == 92
    assert allowed["additional_attempts_remaining"] == 8
    assert allowed["budget_authorizes_partition_boundary"] is True

    states_at_93 = (
        *states_at_92[:11],
        replace(states_at_92[11], request_count=5),
        *states_at_92[12:],
    )
    blocked = resolve_resume(campaign, states_at_93)
    assert blocked["additional_attempts_used"] == 93
    assert blocked["additional_attempts_remaining"] == 7
    assert blocked["campaign_status"] == "blocked"
    assert (
        blocked["blocking_reason"]
        == "insufficient_campaign_budget_for_partition"
    )
    assert CAMPAIGN_MAX_ADDITIONAL_REQUESTS == 100


def test_cached_terminal_page_requires_zero_campaign_attempt_budget(
    tmp_path: Path,
) -> None:
    campaign, plan = seeded_campaign(tmp_path)
    canary = plan.partitions[0]
    body = response_body("cached-canary-terminal", 7)
    CacheStore(canary.config.cache_directory).put_success(
        canary.request_specs[0],
        body=body,
        record_count=7,
        response_metadata={
            "status": 200,
            "content_type": "application/json",
            "content_encoding": "gzip",
        },
        acquired_at_utc="2026-07-28T12:00:00+00:00",
    )

    preflight = inspect_campaign(plan)
    canary_state = preflight["partitions"][0]
    assert canary_state["next_request_cached"] is True
    assert canary_state["remaining_request_ceiling"] == 0

    spent_states = tuple(
        [
            runtime_state(
                ordinal,
                f"P{ordinal}",
                status="complete",
                request_count=(8 if ordinal <= 12 else 4),
                next_sequence=9,
                remaining_ceiling=0,
            )
            for ordinal in range(1, 14)
        ]
        + [
            runtime_state(
                14,
                "cached-next",
                status="not_started",
                remaining_ceiling=0,
            )
        ]
    )
    resolution = resolve_resume(campaign, spent_states)
    assert resolution["additional_attempts_used"] == 100
    assert resolution["additional_attempts_remaining"] == 0
    assert resolution["budget_authorizes_partition_boundary"] is True


def test_completed_run_with_prior_error_requires_review(
    tmp_path: Path,
) -> None:
    campaign, plan = seeded_campaign(tmp_path)
    canary = plan.partitions[0]
    now = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    with StateStore(canary.config.state_path) as state:
        state.initialize_run(canary.config, now=now)
        failed_id = state.start_network_attempt(
            canary.config.run_id,
            canary.request_specs[0],
            attempted_at=now,
        )
        state.finish_network_attempt(
            failed_id,
            outcome="http_error",
            http_status=429,
            error_text="redacted test rate-limit error",
        )

    seed_pages(
        canary,
        (response_body("canary-after-error", 7),),
        record_network_attempts=True,
    )
    preflight = inspect_campaign(plan)
    assert preflight["resume"]["campaign_status"] == "blocked"
    assert (
        "unreviewed_unsuccessful_request:http_error"
        in preflight["resume"]["blocking_reason"]
    )


def test_out_of_order_and_multiple_running_state_blocks(
    tmp_path: Path,
) -> None:
    campaign = CampaignConfig(repository_root=tmp_path)
    out_of_order = (
        runtime_state(1, "P1", status="not_started"),
        runtime_state(2, "P2", status="complete", remaining_ceiling=0),
    )
    assert (
        resolve_resume(campaign, out_of_order)["blocking_reason"]
        == "out_of_order_partition_progress"
    )

    multiple = (
        runtime_state(1, "P1", status="running"),
        runtime_state(2, "P2", status="running"),
    )
    assert (
        resolve_resume(campaign, multiple)["blocking_reason"]
        == "multiple_running_partitions"
    )


def test_generated_json_markdown_and_report_are_secret_free_and_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    campaign, _ = seeded_campaign(tmp_path)
    marker = "SHOULD-NOT-BE-READ-OR-WRITTEN"
    monkeypatch.setenv("LIQUIPEDIA_API_KEY", marker)
    report_path = (
        tmp_path
        / "docs"
        / "milestones"
        / "MILESTONE_3_5_STAGE_A_OFFLINE_CAMPAIGN_PLANNING.md"
    )
    verification = VerificationEvidence(
        command=".venv/bin/python -m pytest -q",
        summary="tests passed",
        passed_tests=42,
        passed=True,
    )
    before = ledger_request_row_count(campaign.state_path)
    first = generate_campaign_artifacts(
        campaign,
        verification=verification,
        milestone_report_path=report_path,
    )
    first_bytes = {
        path: path.read_bytes()
        for path in (
            first.config_path,
            first.plan_json_path,
            first.plan_markdown_path,
            first.preflight_json_path,
            first.preflight_markdown_path,
            report_path,
        )
    }
    second = generate_campaign_artifacts(
        campaign,
        verification=verification,
        milestone_report_path=report_path,
    )
    after = ledger_request_row_count(campaign.state_path)

    assert before == after == 2
    assert first.authenticated_request_delta == 0
    assert second.authenticated_request_delta == 0
    assert all(path.read_bytes() == content for path, content in first_bytes.items())
    combined = b"\n".join(first_bytes.values()).decode("utf-8")
    assert marker not in combined
    assert "Apikey" not in combined
    assert ".secrets" not in combined
    assert "148" in combined
    assert "2022-Q1" in combined
    assert "Generated Definition-of-Done artifact" in report_path.read_text()
    assert STAGE_B_COMMAND in report_path.read_text()
    assert not (tmp_path / ".secrets").exists()


def test_immutable_plan_conflict_is_a_hard_failure(tmp_path: Path) -> None:
    campaign, _ = seeded_campaign(tmp_path)
    artifacts = generate_campaign_artifacts(campaign)
    artifacts.plan_json_path.write_text('{"conflict":true}\n', encoding="utf-8")

    with pytest.raises(CampaignError, match="Immutable campaign artifact"):
        generate_campaign_artifacts(campaign)


def test_campaign_script_has_no_live_or_credential_code_path() -> None:
    root = Path(__file__).resolve().parents[1]
    script = root / "scripts" / "plan_liquipedia_history_campaign.py"
    tree = ast.parse(script.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)

    assert not any(
        name.endswith((".client", ".runner"))
        for name in imported
    )
    source = script.read_text(encoding="utf-8")
    assert "read_api_key" not in source
    assert "BackfillRunner" not in source
    assert "--execute" not in source
    assert ".secrets" not in source


def test_stage_b_command_matches_exact_canary_configuration(
    tmp_path: Path,
) -> None:
    flattened = STAGE_B_COMMAND.replace("\\\n", " ")
    readiness_command, acquisition_command = flattened.split("&&", maxsplit=1)
    readiness_tokens = shlex.split(readiness_command)
    acquisition_tokens = shlex.split(acquisition_command)

    assert readiness_tokens[-2:] == [
        "--check-partition-readiness",
        "2022-Q1",
    ]
    assert acquisition_tokens[:2] == [
        ".venv/bin/python",
        "scripts/backfill_liquipedia_history.py",
    ]
    args = parse_backfill_args(acquisition_tokens[2:])
    config = make_backfill_config(args)
    planned = create_campaign_plan(
        CampaignConfig(repository_root=tmp_path)
    ).partitions[0].config
    assert config.scope_payload() == planned.scope_payload()
    assert config.run_id == planned.run_id
    assert config.config_hash == planned.config_hash
    assert args.execute is True
    assert args.confirm_live_request_budget == 8
