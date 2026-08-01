"""Offline contract tests for the focused 2026-Q2 continuation."""

from __future__ import annotations

import json
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.complete_2026_q2 import main as q2_main
from src.liquipedia_backfill.campaign import CampaignError, PILOT_RUN_ID
from src.liquipedia_backfill.client import ApiRequestError, request_page
from src.liquipedia_backfill.config import BackfillConfig
from src.liquipedia_backfill.q2_completion import (
    CONFIG_HASH,
    PARTITION_ID,
    PREFIX_PAGE_COUNT,
    PREFIX_RECORD_COUNT,
    PREDECESSOR_AUTHORIZATION_ID,
    RESUME_OFFSET,
    RESUME_SEQUENCE,
    RUN_ID,
    SUCCESSOR_BASELINE_EXPANSION_ATTEMPTS,
    SUCCESSOR_BASELINE_REQUEST_ID,
    SUCCESSOR_BASELINE_TOTAL_ATTEMPTS,
    SUCCESSOR_MAXIMUM_NEW_ATTEMPTS,
    Q2ContinuationGate,
    _verify_successor_attempts,
    activate_successor_budget,
    create_q2_continuation_plan,
    execute_q2_continuation,
    recover_unresolved_read_timeout,
    write_plan_artifacts,
)
from src.liquipedia_backfill.runner import BackfillRunner
from src.liquipedia_backfill.state import StateStore


def gate(
    plan,
    *,
    used: int = 0,
    status: str = "budget_exhausted",
    records: int = PREFIX_RECORD_COUNT,
    pages: int = PREFIX_PAGE_COUNT,
) -> Q2ContinuationGate:
    """Return compact successor state for orchestration tests."""
    return Q2ContinuationGate(
        authorization_id=plan.authorization_id,
        plan_fingerprint=plan.fingerprint,
        new_attempts_used=used,
        new_attempts_remaining=SUCCESSOR_MAXIMUM_NEW_ATTEMPTS - used,
        total_request_count=PREFIX_PAGE_COUNT + used,
        records_seen=records,
        accepted_page_count=pages,
        next_sequence=RESUME_SEQUENCE + used,
        next_offset=RESUME_OFFSET + used * 100,
        run_status=status,
        successful_new_pages=pages - PREFIX_PAGE_COUNT,
    )


def test_plan_is_deterministic_path_independent_and_exact(tmp_path: Path) -> None:
    first = create_q2_continuation_plan(tmp_path / "one")
    second = create_q2_continuation_plan(tmp_path / "two")

    assert first.fingerprint == second.fingerprint
    assert first.authorization_id == second.authorization_id
    assert first.partition.partition_id == PARTITION_ID
    assert first.partition.config.run_id == RUN_ID
    assert first.partition.config.config_hash == CONFIG_HASH

    payload = first.identity_payload()
    successor = payload["successor_authorization"]
    assert successor == {
        "baseline_request_id": SUCCESSOR_BASELINE_REQUEST_ID,
        "baseline_total_attempts": SUCCESSOR_BASELINE_TOTAL_ATTEMPTS,
        "baseline_expansion_attempts": (
            SUCCESSOR_BASELINE_EXPANSION_ATTEMPTS
        ),
        "baseline_excluded_run_ids": [PILOT_RUN_ID],
        "maximum_new_attempts": SUCCESSOR_MAXIMUM_NEW_ATTEMPTS,
        "allowed_runs": {RUN_ID: SUCCESSOR_MAXIMUM_NEW_ATTEMPTS},
    }
    prefix = payload["partition"]["required_prefix"]
    assert prefix["pages"] == PREFIX_PAGE_COUNT
    assert prefix["records"] == PREFIX_RECORD_COUNT
    assert prefix["next_sequence"] == RESUME_SEQUENCE
    assert prefix["next_offset"] == RESUME_OFFSET
    assert len(prefix["pages_evidence"]) == PREFIX_PAGE_COUNT
    assert [
        value["sequence"]
        for value in payload["partition"]["conditional_request_slots"]
    ] == list(range(9, 21))


def test_response_read_timeout_is_redacted_api_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = create_q2_continuation_plan(tmp_path)
    secret = "LOCAL-TIMEOUT-SECRET"

    class TimeoutResponse:
        headers: dict[str, str] = {}
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self) -> bytes:
            raise TimeoutError(secret)

    monkeypatch.setattr(
        "src.liquipedia_backfill.client.urlopen",
        lambda *args, **kwargs: TimeoutResponse(),
    )
    with pytest.raises(ApiRequestError) as raised:
        request_page(
            plan.partition.request_specs[8],
            api_key=secret,
        )

    assert raised.value.status is None
    assert str(raised.value) == (
        "Liquipedia API request failed: response read timed out"
    )
    assert secret not in str(raised.value)


def test_response_read_timeout_is_closed_in_runner_ledger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class TimeoutResponse:
        headers: dict[str, str] = {}
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self) -> bytes:
            raise TimeoutError("socket detail must stay redacted")

    monkeypatch.setattr(
        "src.liquipedia_backfill.client.urlopen",
        lambda *args, **kwargs: TimeoutResponse(),
    )
    config = BackfillConfig(
        start_utc=datetime(2026, 4, 1, tzinfo=UTC),
        end_utc=datetime(2026, 7, 1, tzinfo=UTC),
        tiers=("1", "2"),
        page_size=100,
        max_requests=1,
        raw_root=tmp_path / "raw",
        run_root=tmp_path / "runs",
        normalized_output_root=tmp_path / "normalized",
    )

    with pytest.raises(ApiRequestError, match="response read timed out"):
        BackfillRunner().run(config, api_key="not-a-real-key")

    with StateStore(config.state_path) as state:
        attempts = state.request_attempts(config.run_id)
        run = state.run(config.run_id)
    assert len(attempts) == 1
    assert attempts[0]["outcome"] == "http_error"
    assert attempts[0]["http_status"] is None
    assert attempts[0]["response_sha256"] is None
    assert attempts[0]["response_path"] is None
    assert attempts[0]["record_count"] is None
    assert attempts[0]["error_text"] == (
        "Liquipedia API request failed: response read timed out"
    )
    assert run["status"] == "failed"


def successor_row(
    plan,
    *,
    request_id: int,
    sequence: int,
    outcome: str,
) -> dict[str, object]:
    spec = plan.partition.request_specs[sequence - 1]
    success = outcome == "success"
    return {
        "request_id": request_id,
        "run_id": RUN_ID,
        "request_hash": spec.request_hash,
        "sequence": sequence,
        "offset_value": spec.offset,
        "outcome": outcome,
        "http_status": 200 if success else None,
        "response_sha256": "a" * 64 if success else None,
        "response_path": "cache/response.json" if success else None,
        "record_count": 100 if success else None,
        "error_text": (
            None
            if success
            else (
                "Liquipedia API request failed: response body read timed out "
                "before any response metadata or payload was persisted"
            )
        ),
    }


def test_successor_allows_one_charged_timeout_and_exact_manual_retry(
    tmp_path: Path,
) -> None:
    plan = create_q2_continuation_plan(tmp_path)
    timeout = successor_row(
        plan,
        request_id=146,
        sequence=9,
        outcome="http_error",
    )

    assert _verify_successor_attempts(plan, [timeout]) == (
        0,
        146,
        None,
        True,
    )

    retry = successor_row(
        plan,
        request_id=147,
        sequence=9,
        outcome="success",
    )
    page_ten = successor_row(
        plan,
        request_id=148,
        sequence=10,
        outcome="success",
    )
    assert _verify_successor_attempts(
        plan,
        [timeout, retry, page_ten],
    ) == (2, 146, None, False)

    second_timeout = successor_row(
        plan,
        request_id=148,
        sequence=10,
        outcome="http_error",
    )
    with pytest.raises(CampaignError, match="Only one"):
        _verify_successor_attempts(
            plan,
            [timeout, retry, second_timeout],
        )


def test_exact_504_history_allows_only_one_final_slot_nine_retry(
    tmp_path: Path,
) -> None:
    plan = create_q2_continuation_plan(tmp_path)
    timeout = successor_row(
        plan,
        request_id=146,
        sequence=9,
        outcome="http_error",
    )
    gateway = {
        **successor_row(
            plan,
            request_id=147,
            sequence=9,
            outcome="http_error",
        ),
        "http_status": 504,
        "error_text": "Liquipedia API returned HTTP 504: gateway timeout",
    }

    assert _verify_successor_attempts(plan, [timeout, gateway]) == (
        0,
        146,
        147,
        True,
    )

    final_retry = successor_row(
        plan,
        request_id=148,
        sequence=9,
        outcome="success",
    )
    assert _verify_successor_attempts(
        plan,
        [timeout, gateway, final_retry],
    ) == (1, 146, 147, False)

    failed_final_retry = {
        **successor_row(
            plan,
            request_id=148,
            sequence=9,
            outcome="http_error",
        ),
        "http_status": 504,
        "error_text": "Liquipedia API returned HTTP 504: gateway timeout",
    }
    with pytest.raises(CampaignError, match="not followed by an exact"):
        _verify_successor_attempts(
            plan,
            [timeout, gateway, failed_final_retry],
        )

    fourth_attempt = successor_row(
        plan,
        request_id=149,
        sequence=9,
        outcome="success",
    )
    with pytest.raises(CampaignError, match="exact Q2 request sequence"):
        _verify_successor_attempts(
            plan,
            [timeout, gateway, final_retry, fourth_attempt],
        )


def test_plan_artifacts_are_portable_and_credential_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = "LOCAL-SECRET-MUST-NOT-APPEAR"
    monkeypatch.setenv("LIQUIPEDIA_API_KEY", marker)
    plan = create_q2_continuation_plan(tmp_path)

    json_path, markdown_path = write_plan_artifacts(plan)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    combined = json_path.read_text() + markdown_path.read_text()

    assert payload["authenticated_requests_performed_by_planning"] == 0
    assert payload["api_key_read_by_planning"] is False
    assert marker not in combined
    assert ".secrets" not in combined
    assert str(tmp_path.resolve()) not in combined


def test_execute_cli_requires_exact_confirmation_before_key_read(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    key_read = False

    def forbidden_key_read(path: Path) -> str:
        nonlocal key_read
        key_read = True
        raise AssertionError(path)

    monkeypatch.setattr(
        "scripts.backfill_liquipedia_history.read_api_key",
        forbidden_key_read,
    )
    result = q2_main(["--execute"])

    assert result == 1
    assert key_read is False
    assert "--confirm-continuation-fingerprint" in capsys.readouterr().err


def test_activation_delegates_only_exact_successor_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = create_q2_continuation_plan(tmp_path)
    observed: dict[str, object] = {}
    expected_gate = gate(plan)

    class FakeState:
        def __init__(self, path: Path):
            observed["state_path"] = path

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def supersede_campaign_request_budget(self, **kwargs):
            observed["successor"] = kwargs
            return {}

    monkeypatch.setattr(
        "src.liquipedia_backfill.q2_completion.inspect_predecessor",
        lambda value: {"status": "ready_to_activate"},
    )
    monkeypatch.setattr(
        "src.liquipedia_backfill.q2_completion.StateStore",
        FakeState,
    )
    monkeypatch.setattr(
        "src.liquipedia_backfill.q2_completion.verify_successor_budget",
        lambda value: expected_gate,
    )

    assert activate_successor_budget(plan) == expected_gate
    assert observed["state_path"] == plan.partition.config.state_path
    assert observed["successor"] == {
        "predecessor_authorization_id": PREDECESSOR_AUTHORIZATION_ID,
        "authorization_id": plan.authorization_id,
        "plan_fingerprint": plan.fingerprint,
        "baseline_request_id": SUCCESSOR_BASELINE_REQUEST_ID,
        "baseline_total_attempts": SUCCESSOR_BASELINE_TOTAL_ATTEMPTS,
        "baseline_expansion_attempts": (
            SUCCESSOR_BASELINE_EXPANSION_ATTEMPTS
        ),
        "maximum_new_attempts": SUCCESSOR_MAXIMUM_NEW_ATTEMPTS,
        "allowed_runs": {RUN_ID: SUCCESSOR_MAXIMUM_NEW_ATTEMPTS},
        "baseline_excluded_run_ids": (PILOT_RUN_ID,),
    }


def test_offline_timeout_recovery_delegates_exact_request_146(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = create_q2_continuation_plan(tmp_path)
    spec = plan.partition.request_specs[8]
    observed: dict[str, object] = {}
    recovered_gate = Q2ContinuationGate(
        authorization_id=plan.authorization_id,
        plan_fingerprint=plan.fingerprint,
        new_attempts_used=1,
        new_attempts_remaining=11,
        total_request_count=9,
        records_seen=800,
        accepted_page_count=8,
        next_sequence=9,
        next_offset=800,
        run_status="failed",
        successful_new_pages=0,
        transport_failure_attempt_id=146,
        retry_pending=True,
    )

    class FakeState:
        def __init__(self, path: Path):
            observed["state_path"] = path

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def recover_latest_started_read_timeout(self, **kwargs):
            observed["recovery"] = kwargs
            return {}

        def write_checkpoint(self, config):
            observed["checkpoint_config"] = config

    monkeypatch.setattr(
        "src.liquipedia_backfill.q2_completion.inspect_unresolved_read_timeout",
        lambda value: {
            "request_id": 146,
            "sequence": 9,
            "offset": 800,
            "request_hash": spec.request_hash,
        },
    )
    monkeypatch.setattr(
        "src.liquipedia_backfill.q2_completion.StateStore",
        FakeState,
    )
    monkeypatch.setattr(
        "src.liquipedia_backfill.q2_completion.verify_successor_budget",
        lambda value: recovered_gate,
    )

    gate_result, paths = recover_unresolved_read_timeout(plan)

    assert gate_result == recovered_gate
    assert observed["recovery"] == {
        "request_id": 146,
        "run_id": RUN_ID,
        "sequence": 9,
        "offset_value": 800,
        "request_hash": spec.request_hash,
    }
    assert observed["checkpoint_config"] == plan.partition.config
    report = json.loads(paths[0].read_text(encoding="utf-8"))
    assert report["handling"]["attempt_remains_charged"] is True
    assert report["handling"]["manual_retry_pending"] is True
    assert report["authenticated_requests_performed_by_recovery"] == 0


def test_execute_reuses_runner_validator_and_offline_tests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = create_q2_continuation_plan(tmp_path)
    before = Q2ContinuationGate(
        authorization_id=plan.authorization_id,
        plan_fingerprint=plan.fingerprint,
        new_attempts_used=2,
        new_attempts_remaining=10,
        total_request_count=10,
        records_seen=800,
        accepted_page_count=8,
        next_sequence=9,
        next_offset=800,
        run_status="failed",
        successful_new_pages=0,
        transport_failure_attempt_id=146,
        gateway_timeout_attempt_id=147,
        retry_pending=True,
    )
    after = Q2ContinuationGate(
        authorization_id=plan.authorization_id,
        plan_fingerprint=plan.fingerprint,
        new_attempts_used=3,
        new_attempts_remaining=9,
        total_request_count=11,
        records_seen=947,
        accepted_page_count=9,
        next_sequence=10,
        next_offset=900,
        run_status="complete",
        successful_new_pages=1,
        transport_failure_attempt_id=146,
        gateway_timeout_attempt_id=147,
        retry_pending=False,
    )
    verified = iter((before, after))
    monkeypatch.setattr(
        "src.liquipedia_backfill.q2_completion.campaign_execution_lock",
        lambda value: nullcontext(),
    )
    monkeypatch.setattr(
        "src.liquipedia_backfill.q2_completion.verify_successor_budget",
        lambda value: next(verified),
    )
    monkeypatch.setattr(
        "src.liquipedia_backfill.q2_completion._successor_attempt_rows",
        lambda value: [
            {"outcome": "http_error"},
            {"outcome": "http_error"},
            {"outcome": "success"},
        ],
    )

    runner_calls: dict[str, object] = {}

    class FakeRunner:
        def run(self, config, **kwargs):
            runner_calls["config"] = config
            runner_calls.update(kwargs)
            return SimpleNamespace(status="complete")

    validation = SimpleNamespace(
        normalized_matches=471,
        normalized_games=903,
        eligible_games=812,
        excluded_games=91,
        eligibility_percentage=89.922481,
        to_payload=lambda: {"status": "passed"},
    )
    validator_calls: dict[str, object] = {}

    def validator(**kwargs):
        validator_calls.update(kwargs)
        return validation

    key_loads = 0

    def key_loader() -> str:
        nonlocal key_loads
        key_loads += 1
        return "not-a-real-key"

    result = execute_q2_continuation(
        plan,
        api_key_loader=key_loader,
        runner=FakeRunner(),
        validator=validator,
        test_runner=lambda root: {
            "passed": True,
            "summary": "130 passed",
            "network_enabled": False,
            "credentials_available_to_tests": False,
        },
    )

    assert result[0] == after
    assert key_loads == 1
    assert runner_calls["config"] == plan.partition.config
    assert runner_calls["max_network_attempts"] == 20
    assert runner_calls["required_cache_prefix_pages"] == 8
    assert validator_calls["partition_id"] == PARTITION_ID
    assert len(validator_calls["completed_prefix"]) == 18
    assert validator_calls["completed_prefix"][-1] == (
        PARTITION_ID,
        RUN_ID,
    )
    report = json.loads(result[3][0].read_text(encoding="utf-8"))
    assert report["http_attempts_this_execution"] == 1
    assert report["http_attempts_since_successor_activation"] == 3
    assert report["http_outcome_counts_since_successor_activation"] == {
        "http_error": 2,
        "success": 1,
    }
    assert report["records_collected_this_execution"] == 147
    assert report["accepted_pages_total"] == 9
    assert report["model_fitting_performed"] is False
    assert report["credential_policy"]["credential_value_printed"] is False


def test_execute_fails_before_key_when_successor_is_exhausted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = create_q2_continuation_plan(tmp_path)
    monkeypatch.setattr(
        "src.liquipedia_backfill.q2_completion.campaign_execution_lock",
        lambda value: nullcontext(),
    )
    monkeypatch.setattr(
        "src.liquipedia_backfill.q2_completion.verify_successor_budget",
        lambda value: gate(
            plan,
            used=SUCCESSOR_MAXIMUM_NEW_ATTEMPTS,
        ),
    )
    key_read = False

    def key_loader() -> str:
        nonlocal key_read
        key_read = True
        return "not-a-real-key"

    with pytest.raises(CampaignError, match="ceiling is exhausted"):
        execute_q2_continuation(
            plan,
            api_key_loader=key_loader,
        )
    assert key_read is False
