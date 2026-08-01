"""Offline tests for persistent Milestone 3.6 request-budget enforcement."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.liquipedia_backfill.planner import RequestSpec
from src.liquipedia_backfill.state import (
    RECOVERED_READ_TIMEOUT_ERROR,
    StateError,
    StateStore,
    is_no_response_transport_failure,
)


AUTHORIZATION_ID = "m3.6-approved-live-request-budget-v1"
PLAN_FINGERPRINT = (
    "80bf4dc4fa31810dca0d1b8d3f1ece37779e0560dc1eeaeccd435e05e6ebbde0"
)
SUCCESSOR_AUTHORIZATION_ID = "m3.6-2026-q2-continuation-v1"
SUCCESSOR_PLAN_FINGERPRINT = "4" * 64
PILOT_RUN_ID = "m3_20260701_20260727_0b40ae8811d6"
BASELINE_RUN_ID = "m3-existing-expansion"
RUN_A = "m3_20240401_20240701_df05306783f7"
RUN_B = "m3_20240701_20241001_5659f531fd34"
RUN_C = "m3_20241001_20250101_ecd00b0cc3ce"
RUN_D = "m3_20250101_20250401_a776b95bd596"
RUN_E = "m3_20250401_20250701_1b756dc53f16"
RUN_F = "m3_20250701_20251001_08de1390c237"
RUN_G = "m3_20251001_20260101_00760b8766c9"
RUN_H = "m3_20260101_20260401_8405a550a09e"
RUN_I = "m3_20260401_20260701_f73ba01f2767"
UNAUTHORIZED_RUN = "m3-not-approved"
BASELINE_TIME = datetime(2026, 7, 29, 8, 25, tzinfo=UTC)
APPROVED_RUN_CAPS = {
    RUN_A: 12,
    RUN_B: 20,
    RUN_C: 20,
    RUN_D: 20,
    RUN_E: 20,
    RUN_F: 20,
    RUN_G: 20,
    RUN_H: 20,
    RUN_I: 20,
}


def insert_run(state: StateStore, run_id: str) -> None:
    """Insert the minimum deterministic run state needed by ledger tests."""
    timestamp = BASELINE_TIME.isoformat()
    with state.connection:
        state.connection.execute(
            """
            INSERT INTO runs (
                run_id, config_hash, config_json, status,
                next_sequence, next_offset, request_count,
                cache_hit_count, records_seen, started_at_utc, updated_at_utc
            ) VALUES (?, ?, '{}', 'planned', 1, 0, 0, 0, 0, ?, ?)
            """,
            (run_id, f"config-{run_id}", timestamp, timestamp),
        )


def seed_reviewed_baseline(state: StateStore) -> None:
    """Create the reviewed contiguous 65-attempt, 63-expansion baseline."""
    for run_id in (
        PILOT_RUN_ID,
        BASELINE_RUN_ID,
        RUN_A,
        RUN_B,
        UNAUTHORIZED_RUN,
    ):
        insert_run(state, run_id)

    rows = []
    for request_id in range(1, 66):
        run_id = PILOT_RUN_ID if request_id <= 2 else BASELINE_RUN_ID
        attempted = BASELINE_TIME + timedelta(seconds=request_id)
        rows.append(
            (
                run_id,
                f"{request_id:064x}",
                request_id,
                (request_id - 1) * 100,
                attempted.timestamp(),
                attempted.isoformat(),
            )
        )
    with state.connection:
        state.connection.executemany(
            """
            INSERT INTO requests (
                run_id, request_hash, sequence, offset_value,
                attempted_at_epoch, attempted_at_utc, outcome, http_status
            ) VALUES (?, ?, ?, ?, ?, ?, 'success', 200)
            """,
            rows,
        )
        state.connection.execute(
            "UPDATE runs SET request_count = 2 WHERE run_id = ?",
            (PILOT_RUN_ID,),
        )
        state.connection.execute(
            "UPDATE runs SET request_count = 63 WHERE run_id = ?",
            (BASELINE_RUN_ID,),
        )


def activate(
    state: StateStore,
    *,
    allowed_runs: dict[str, int] | None = None,
    maximum_new_attempts: int = 80,
) -> dict[str, object]:
    """Activate the exact reviewed baseline with configurable test caps."""
    return state.activate_campaign_request_budget(
        authorization_id=AUTHORIZATION_ID,
        plan_fingerprint=PLAN_FINGERPRINT,
        baseline_request_id=65,
        baseline_total_attempts=65,
        baseline_expansion_attempts=63,
        maximum_new_attempts=maximum_new_attempts,
        allowed_runs=allowed_runs or APPROVED_RUN_CAPS,
        baseline_excluded_run_ids=(PILOT_RUN_ID,),
        now=BASELINE_TIME,
    )


def request(sequence: int) -> RequestSpec:
    """Return one unique credential-free request specification."""
    return RequestSpec(
        sequence=sequence,
        offset=(sequence - 1) * 100,
        endpoint="https://api.liquipedia.net/api/v3/match",
        parameters={"limit": 100, "offset": (sequence - 1) * 100},
    )


def finish(state: StateStore, request_id: int, outcome: str = "success") -> None:
    """Finish one test attempt without touching a network or cache."""
    state.finish_network_attempt(
        request_id,
        outcome=outcome,
        http_status=200 if outcome == "success" else 500,
    )


def exhaust_authorization(
    state: StateStore,
    *,
    maximum_new_attempts: int = 2,
) -> None:
    """Spend and finish every attempt in a small predecessor budget."""
    activate(
        state,
        allowed_runs={RUN_A: maximum_new_attempts},
        maximum_new_attempts=maximum_new_attempts,
    )
    for sequence in range(1, maximum_new_attempts + 1):
        attempt_id = state.start_network_attempt(
            RUN_A,
            request(sequence),
            attempted_at=(
                BASELINE_TIME + timedelta(seconds=67 * sequence)
            ),
        )
        finish(state, attempt_id)


def supersede(
    state: StateStore,
    *,
    authorization_id: str = SUCCESSOR_AUTHORIZATION_ID,
    plan_fingerprint: str = SUCCESSOR_PLAN_FINGERPRINT,
    baseline_request_id: int = 67,
    baseline_total_attempts: int = 67,
    baseline_expansion_attempts: int = 65,
    maximum_new_attempts: int = 4,
    allowed_runs: dict[str, int] | None = None,
    baseline_excluded_run_ids: tuple[str, ...] = (PILOT_RUN_ID,),
) -> dict[str, object]:
    """Create the bounded successor used by handoff tests."""
    return state.supersede_campaign_request_budget(
        predecessor_authorization_id=AUTHORIZATION_ID,
        authorization_id=authorization_id,
        plan_fingerprint=plan_fingerprint,
        baseline_request_id=baseline_request_id,
        baseline_total_attempts=baseline_total_attempts,
        baseline_expansion_attempts=baseline_expansion_attempts,
        maximum_new_attempts=maximum_new_attempts,
        allowed_runs=allowed_runs or {RUN_A: 4},
        baseline_excluded_run_ids=baseline_excluded_run_ids,
        now=BASELINE_TIME + timedelta(hours=1),
    )


def test_existing_state_behavior_is_preserved_without_authorization(
    tmp_path: Path,
) -> None:
    """The legacy per-run ledger remains usable before budget activation."""
    with StateStore(tmp_path / "state.sqlite3") as state:
        insert_run(state, RUN_A)
        request_id = state.start_network_attempt(
            RUN_A,
            request(1),
            attempted_at=BASELINE_TIME,
        )

        assert request_id == 1
        assert state.request_attempts(RUN_A)[0]["outcome"] == "started"
        assert state.campaign_request_budget() is None


def test_activation_is_exact_idempotent_and_exposes_accounting(
    tmp_path: Path,
) -> None:
    """Activation binds the reviewed ledger and can only replay exactly."""
    with StateStore(tmp_path / "state.sqlite3") as state:
        seed_reviewed_baseline(state)
        activated = activate(state)
        replayed = activate(state)

        assert activated == replayed
        assert activated["authorization_id"] == AUTHORIZATION_ID
        assert activated["baseline_request_id"] == 65
        assert activated["baseline_total_attempts"] == 65
        assert activated["baseline_expansion_attempts"] == 63
        assert activated["maximum_new_attempts"] == 80
        assert activated["baseline_excluded_run_ids"] == [PILOT_RUN_ID]
        assert activated["allowed_runs"] == APPROVED_RUN_CAPS

        accounting = state.campaign_request_budget_accounting()
        assert accounting is not None
        assert accounting["new_attempts_used"] == 0
        assert accounting["remaining_new_attempts"] == 80
        assert accounting["cumulative_expansion_attempts"] == 63
        assert accounting["cumulative_expansion_attempt_ceiling"] == 143
        assert accounting["total_attempts"] == 65
        assert accounting["total_attempt_ceiling"] == 145
        assert accounting["ledger_contiguous"] is True

        tables = {
            row["name"]
            for row in state.connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert "campaign_request_budgets" in tables
        assert "campaign_request_budget_allowed_runs" in tables

        with pytest.raises(StateError, match="replay differs"):
            state.activate_campaign_request_budget(
                authorization_id=AUTHORIZATION_ID,
                plan_fingerprint=PLAN_FINGERPRINT,
                baseline_request_id=65,
                baseline_total_attempts=65,
                baseline_expansion_attempts=63,
                maximum_new_attempts=81,
                allowed_runs=APPROVED_RUN_CAPS,
                baseline_excluded_run_ids=(PILOT_RUN_ID,),
                now=BASELINE_TIME,
            )


def test_activation_rejects_mismatched_or_unfinished_baseline(
    tmp_path: Path,
) -> None:
    """Authorization cannot attach to a changed or unfinished request ledger."""
    with StateStore(tmp_path / "mismatch.sqlite3") as state:
        seed_reviewed_baseline(state)
        with pytest.raises(StateError, match="contiguous request ledger"):
            state.activate_campaign_request_budget(
                authorization_id=AUTHORIZATION_ID,
                plan_fingerprint=PLAN_FINGERPRINT,
                baseline_request_id=64,
                baseline_total_attempts=65,
                baseline_expansion_attempts=63,
                maximum_new_attempts=80,
                allowed_runs={RUN_A: 12},
                baseline_excluded_run_ids=(PILOT_RUN_ID,),
            )

    with StateStore(tmp_path / "unfinished.sqlite3") as state:
        seed_reviewed_baseline(state)
        with state.connection:
            state.connection.execute(
                "UPDATE requests SET outcome = 'started' WHERE request_id = 65"
            )
        with pytest.raises(StateError, match="zero unresolved"):
            activate(state)


def test_unauthorized_run_is_rejected_without_spending_budget(
    tmp_path: Path,
) -> None:
    """Only run IDs bound into the authorization may add request rows."""
    with StateStore(tmp_path / "state.sqlite3") as state:
        seed_reviewed_baseline(state)
        activate(state)

        with pytest.raises(StateError, match="is not authorized"):
            state.start_network_attempt(
                UNAUTHORIZED_RUN,
                request(1),
                attempted_at=BASELINE_TIME,
            )

        accounting = state.campaign_request_budget_accounting()
        assert accounting is not None
        assert accounting["new_attempts_used"] == 0
        assert state.run(UNAUTHORIZED_RUN)["request_count"] == 0


def test_started_and_failed_attempts_count_and_block_concurrent_start(
    tmp_path: Path,
) -> None:
    """Persisting 'started' spends budget even before its final outcome."""
    with StateStore(tmp_path / "state.sqlite3") as state:
        seed_reviewed_baseline(state)
        activate(state)
        request_id = state.start_network_attempt(
            RUN_A,
            request(1),
            attempted_at=BASELINE_TIME,
        )

        accounting = state.campaign_request_budget_accounting()
        assert accounting is not None
        assert accounting["new_attempts_used"] == 1
        assert accounting["remaining_new_attempts"] == 79
        assert accounting["unresolved_started_attempts"] == 1
        with pytest.raises(StateError, match="unresolved"):
            state.start_network_attempt(
                RUN_A,
                request(2),
                attempted_at=BASELINE_TIME + timedelta(seconds=67),
            )

        finish(state, request_id, outcome="http_error")
        accounting = state.campaign_request_budget_accounting()
        assert accounting is not None
        assert accounting["new_attempts_used"] == 1
        assert accounting["unresolved_started_attempts"] == 0
        assert activate(state)["authorization_id"] == AUTHORIZATION_ID


def test_duplicate_request_or_page_slot_cannot_spend_budget_twice(
    tmp_path: Path,
) -> None:
    """A missing cache cannot turn an already attempted page into a retry."""
    with StateStore(tmp_path / "state.sqlite3") as state:
        seed_reviewed_baseline(state)
        activate(state)
        original = request(1)
        attempt_id = state.start_network_attempt(
            RUN_A,
            original,
            attempted_at=BASELINE_TIME,
        )
        finish(state, attempt_id)

        with pytest.raises(StateError, match="not authorized"):
            state.start_network_attempt(
                RUN_A,
                original,
                attempted_at=BASELINE_TIME + timedelta(seconds=67),
            )

        changed_hash_same_slot = RequestSpec(
            sequence=original.sequence,
            offset=original.offset,
            endpoint=original.endpoint,
            parameters={
                **original.parameters,
                "contract-variant": "must-fail-closed",
            },
        )
        assert changed_hash_same_slot.request_hash != original.request_hash
        with pytest.raises(StateError, match="not authorized"):
            state.start_network_attempt(
                RUN_A,
                changed_hash_same_slot,
                attempted_at=BASELINE_TIME + timedelta(seconds=134),
            )

        accounting = state.campaign_request_budget_accounting()
        assert accounting is not None
        assert accounting["new_attempts_used"] == 1
        assert accounting["per_run_attempts"][RUN_A] == 1
        assert state.run(RUN_A)["request_count"] == 1
        assert len(state.request_attempts(RUN_A)) == 1


def test_one_charged_no_response_transport_failure_can_be_retried_once(
    tmp_path: Path,
) -> None:
    """A manual resume may recover one attempt that got no HTTP response."""
    with StateStore(tmp_path / "state.sqlite3") as state:
        seed_reviewed_baseline(state)
        activate(state)
        original = request(1)
        first_id = state.start_network_attempt(
            RUN_A,
            original,
            attempted_at=BASELINE_TIME,
        )
        state.finish_network_attempt(
            first_id,
            outcome="http_error",
            error_text=(
                "Liquipedia API request failed: temporary DNS failure"
            ),
        )

        retry_id = state.start_network_attempt(
            RUN_A,
            original,
            attempted_at=BASELINE_TIME + timedelta(seconds=67),
        )
        finish(state, retry_id)

        accounting = state.campaign_request_budget_accounting()
        assert accounting is not None
        assert accounting["new_attempts_used"] == 2
        assert accounting["per_run_attempts"][RUN_A] == 2
        assert state.run(RUN_A)["request_count"] == 2
        with pytest.raises(StateError, match="not authorized"):
            state.start_network_attempt(
                RUN_A,
                original,
                attempted_at=BASELINE_TIME + timedelta(seconds=134),
            )


def test_no_response_then_gateway_timeout_allows_one_final_attempt(
    tmp_path: Path,
) -> None:
    """Exactly [no response, HTTP 504] permits a third but no fourth call."""
    with StateStore(tmp_path / "state.sqlite3") as state:
        seed_reviewed_baseline(state)
        activate(
            state,
            allowed_runs={RUN_A: 4},
            maximum_new_attempts=4,
        )
        original = request(1)
        first_id = state.start_network_attempt(
            RUN_A,
            original,
            attempted_at=BASELINE_TIME,
        )
        state.finish_network_attempt(
            first_id,
            outcome="http_error",
            error_text=(
                "Liquipedia API request failed: temporary read timeout"
            ),
        )
        second_id = state.start_network_attempt(
            RUN_A,
            original,
            attempted_at=BASELINE_TIME + timedelta(seconds=67),
        )
        state.finish_network_attempt(
            second_id,
            outcome="http_error",
            http_status=504,
            error_text="Liquipedia API returned HTTP 504",
        )

        third_id = state.start_network_attempt(
            RUN_A,
            original,
            attempted_at=BASELINE_TIME + timedelta(seconds=134),
        )
        finish(state, third_id)

        with pytest.raises(StateError, match="not authorized"):
            state.start_network_attempt(
                RUN_A,
                original,
                attempted_at=BASELINE_TIME + timedelta(seconds=201),
            )

        attempts = state.request_attempts(RUN_A)
        assert [attempt["request_id"] for attempt in attempts] == [
            first_id,
            second_id,
            third_id,
        ]
        accounting = state.campaign_request_budget_accounting()
        assert accounting is not None
        assert accounting["new_attempts_used"] == 3
        assert accounting["remaining_new_attempts"] == 1


@pytest.mark.parametrize(
    ("second_status", "response_sha256", "record_count"),
    [
        (503, None, None),
        (504, "a" * 64, None),
        (504, None, 0),
    ],
)
def test_gateway_retry_rejects_any_nonexact_second_outcome(
    tmp_path: Path,
    second_status: int,
    response_sha256: str | None,
    record_count: int | None,
) -> None:
    """Other statuses or persisted response evidence do not widen retries."""
    with StateStore(tmp_path / "state.sqlite3") as state:
        seed_reviewed_baseline(state)
        activate(
            state,
            allowed_runs={RUN_A: 4},
            maximum_new_attempts=4,
        )
        original = request(1)
        first_id = state.start_network_attempt(
            RUN_A,
            original,
            attempted_at=BASELINE_TIME,
        )
        state.finish_network_attempt(
            first_id,
            outcome="http_error",
            error_text=(
                "Liquipedia API request failed: temporary read timeout"
            ),
        )
        second_id = state.start_network_attempt(
            RUN_A,
            original,
            attempted_at=BASELINE_TIME + timedelta(seconds=67),
        )
        state.finish_network_attempt(
            second_id,
            outcome="http_error",
            http_status=second_status,
            response_sha256=response_sha256,
            record_count=record_count,
            error_text=f"Liquipedia API returned HTTP {second_status}",
        )

        with pytest.raises(StateError, match="not authorized"):
            state.start_network_attempt(
                RUN_A,
                original,
                attempted_at=BASELINE_TIME + timedelta(seconds=134),
            )
        assert len(state.request_attempts(RUN_A)) == 2


def test_gateway_retry_requires_both_attempts_to_match_exact_slot(
    tmp_path: Path,
) -> None:
    """A changed hash in the two-row history blocks the final attempt."""
    with StateStore(tmp_path / "state.sqlite3") as state:
        seed_reviewed_baseline(state)
        activate(
            state,
            allowed_runs={RUN_A: 4},
            maximum_new_attempts=4,
        )
        original = request(1)
        first_id = state.start_network_attempt(
            RUN_A,
            original,
            attempted_at=BASELINE_TIME,
        )
        state.finish_network_attempt(
            first_id,
            outcome="http_error",
            error_text=(
                "Liquipedia API request failed: temporary read timeout"
            ),
        )
        second_id = state.start_network_attempt(
            RUN_A,
            original,
            attempted_at=BASELINE_TIME + timedelta(seconds=67),
        )
        state.finish_network_attempt(
            second_id,
            outcome="http_error",
            http_status=504,
            error_text="Liquipedia API returned HTTP 504",
        )
        with state.connection:
            state.connection.execute(
                """
                UPDATE requests
                SET request_hash = ?
                WHERE request_id = ?
                """,
                ("e" * 64, second_id),
            )

        with pytest.raises(StateError, match="not authorized"):
            state.start_network_attempt(
                RUN_A,
                original,
                attempted_at=BASELINE_TIME + timedelta(seconds=134),
            )
        assert len(state.request_attempts(RUN_A)) == 2


def test_gateway_timeout_without_preceding_no_response_is_not_retryable(
    tmp_path: Path,
) -> None:
    """A lone HTTP 504 does not receive the special final-attempt rule."""
    with StateStore(tmp_path / "state.sqlite3") as state:
        seed_reviewed_baseline(state)
        activate(
            state,
            allowed_runs={RUN_A: 4},
            maximum_new_attempts=4,
        )
        original = request(1)
        first_id = state.start_network_attempt(
            RUN_A,
            original,
            attempted_at=BASELINE_TIME,
        )
        state.finish_network_attempt(
            first_id,
            outcome="http_error",
            http_status=504,
            error_text="Liquipedia API returned HTTP 504",
        )

        with pytest.raises(StateError, match="not authorized"):
            state.start_network_attempt(
                RUN_A,
                original,
                attempted_at=BASELINE_TIME + timedelta(seconds=67),
            )
        assert len(state.request_attempts(RUN_A)) == 1


@pytest.mark.parametrize(
    ("outcome", "http_status", "error_text"),
    [
        ("http_error", 403, "Liquipedia API returned HTTP 403"),
        ("invalid_response", 200, "malformed JSON"),
    ],
)
def test_http_response_and_payload_failures_remain_nonretryable(
    tmp_path: Path,
    outcome: str,
    http_status: int,
    error_text: str,
) -> None:
    """Only transport failures with no HTTP response receive one recovery."""
    with StateStore(tmp_path / f"{outcome}.sqlite3") as state:
        seed_reviewed_baseline(state)
        activate(state)
        original = request(1)
        first_id = state.start_network_attempt(
            RUN_A,
            original,
            attempted_at=BASELINE_TIME,
        )
        state.finish_network_attempt(
            first_id,
            outcome=outcome,
            http_status=http_status,
            error_text=error_text,
        )

        with pytest.raises(StateError, match="not authorized"):
            state.start_network_attempt(
                RUN_A,
                original,
                attempted_at=BASELINE_TIME + timedelta(seconds=67),
            )


def test_per_run_and_campaign_caps_are_enforced_atomically(
    tmp_path: Path,
) -> None:
    """Per-run caps and the global 80-attempt ceiling cannot be exceeded."""
    with StateStore(tmp_path / "state.sqlite3") as state:
        seed_reviewed_baseline(state)
        activate(state, allowed_runs={RUN_A: 2, RUN_B: 80})
        clock = BASELINE_TIME

        for sequence in range(1, 3):
            attempt_id = state.start_network_attempt(
                RUN_A,
                request(sequence),
                attempted_at=clock,
            )
            finish(state, attempt_id)
            clock += timedelta(seconds=67)
        with pytest.raises(StateError, match="authorized request cap"):
            state.start_network_attempt(
                RUN_A,
                request(3),
                attempted_at=clock,
            )

        for sequence in range(1, 79):
            attempt_id = state.start_network_attempt(
                RUN_B,
                request(sequence),
                attempted_at=clock,
            )
            finish(state, attempt_id)
            clock += timedelta(seconds=67)

        accounting = state.campaign_request_budget_accounting()
        assert accounting is not None
        assert accounting["new_attempts_used"] == 80
        assert accounting["remaining_new_attempts"] == 0
        assert accounting["cumulative_expansion_attempts"] == 143
        assert accounting["total_attempts"] == 145
        with pytest.raises(StateError, match="campaign-wide maximum"):
            state.start_network_attempt(
                RUN_B,
                request(79),
                attempted_at=clock,
            )
        assert state.run(RUN_B)["request_count"] == 78


def test_deleted_request_row_causes_fail_closed_discontinuity(
    tmp_path: Path,
) -> None:
    """AUTOINCREMENT evidence makes even deletion of the newest row visible."""
    with StateStore(tmp_path / "state.sqlite3") as state:
        seed_reviewed_baseline(state)
        activate(state)
        attempt_id = state.start_network_attempt(
            RUN_A,
            request(1),
            attempted_at=BASELINE_TIME,
        )
        finish(state, attempt_id)
        with state.connection:
            state.connection.execute(
                "DELETE FROM requests WHERE request_id = ?",
                (attempt_id,),
            )

        with pytest.raises(StateError, match="discontinuous"):
            state.start_network_attempt(
                RUN_A,
                request(2),
                attempted_at=BASELINE_TIME + timedelta(seconds=67),
            )


def test_exhausted_authorization_handoff_is_atomic_and_idempotent(
    tmp_path: Path,
) -> None:
    """An exact exhausted predecessor becomes immutable inactive history."""
    with StateStore(tmp_path / "state.sqlite3") as state:
        seed_reviewed_baseline(state)
        exhaust_authorization(state)
        predecessor_before = state.campaign_request_budget(AUTHORIZATION_ID)

        successor = supersede(state)
        replayed = supersede(state)

        assert successor == replayed
        assert successor["authorization_id"] == SUCCESSOR_AUTHORIZATION_ID
        assert successor["baseline_request_id"] == 67
        assert successor["baseline_total_attempts"] == 67
        assert successor["baseline_expansion_attempts"] == 65
        assert successor["maximum_new_attempts"] == 4
        assert successor["allowed_runs"] == {RUN_A: 4}
        assert successor["is_active"] is True

        predecessor_after = state.campaign_request_budget(AUTHORIZATION_ID)
        assert predecessor_before is not None
        assert predecessor_after == {
            **predecessor_before,
            "is_active": False,
        }
        assert state.campaign_request_budget() == successor

        accounting = state.campaign_request_budget_accounting()
        assert accounting is not None
        assert accounting["baseline_request_id"] == 67
        assert accounting["new_attempts_used"] == 0
        assert accounting["remaining_new_attempts"] == 4
        assert accounting["cumulative_expansion_attempts"] == 65
        assert accounting["cumulative_expansion_attempt_ceiling"] == 69

        rows = state.connection.execute(
            """
            SELECT authorization_id, is_active
            FROM campaign_request_budgets
            ORDER BY authorization_id
            """
        ).fetchall()
        assert len(rows) == 2
        assert sum(int(row["is_active"]) for row in rows) == 1

        with pytest.raises(StateError, match="replay differs"):
            supersede(state, maximum_new_attempts=3)
        assert state.campaign_request_budget() == successor


def test_handoff_rejects_nonexhausted_and_unresolved_predecessors(
    tmp_path: Path,
) -> None:
    """A successor cannot replace remaining budget or an in-flight request."""
    with StateStore(tmp_path / "nonexhausted.sqlite3") as state:
        seed_reviewed_baseline(state)
        activate(
            state,
            allowed_runs={RUN_A: 2},
            maximum_new_attempts=2,
        )
        attempt_id = state.start_network_attempt(
            RUN_A,
            request(1),
            attempted_at=BASELINE_TIME + timedelta(seconds=67),
        )
        finish(state, attempt_id)

        with pytest.raises(StateError, match="exactly exhausted"):
            state.supersede_campaign_request_budget(
                predecessor_authorization_id=AUTHORIZATION_ID,
                authorization_id=SUCCESSOR_AUTHORIZATION_ID,
                plan_fingerprint=SUCCESSOR_PLAN_FINGERPRINT,
                baseline_request_id=66,
                baseline_total_attempts=66,
                baseline_expansion_attempts=64,
                maximum_new_attempts=4,
                allowed_runs={RUN_A: 4},
                baseline_excluded_run_ids=(PILOT_RUN_ID,),
            )
        assert state.campaign_request_budget(AUTHORIZATION_ID)["is_active"]
        assert (
            state.campaign_request_budget(SUCCESSOR_AUTHORIZATION_ID)
            is None
        )

    with StateStore(tmp_path / "unresolved.sqlite3") as state:
        seed_reviewed_baseline(state)
        activate(
            state,
            allowed_runs={RUN_A: 1},
            maximum_new_attempts=1,
        )
        state.start_network_attempt(
            RUN_A,
            request(1),
            attempted_at=BASELINE_TIME + timedelta(seconds=67),
        )

        with pytest.raises(StateError, match="unresolved request"):
            state.supersede_campaign_request_budget(
                predecessor_authorization_id=AUTHORIZATION_ID,
                authorization_id=SUCCESSOR_AUTHORIZATION_ID,
                plan_fingerprint=SUCCESSOR_PLAN_FINGERPRINT,
                baseline_request_id=66,
                baseline_total_attempts=66,
                baseline_expansion_attempts=64,
                maximum_new_attempts=4,
                allowed_runs={RUN_A: 4},
                baseline_excluded_run_ids=(PILOT_RUN_ID,),
            )
        assert state.campaign_request_budget(AUTHORIZATION_ID)["is_active"]


@pytest.mark.parametrize(
    "changes",
    [
        {"baseline_request_id": 66},
        {"baseline_total_attempts": 66},
        {"baseline_expansion_attempts": 64},
        {"baseline_excluded_run_ids": ()},
        {"allowed_runs": {RUN_B: 4}},
        {"plan_fingerprint": PLAN_FINGERPRINT},
        {"authorization_id": AUTHORIZATION_ID},
    ],
)
def test_handoff_rejects_mismatched_or_unsafe_contracts(
    tmp_path: Path,
    changes: dict[str, object],
) -> None:
    """The successor cannot move the boundary or broaden authorization."""
    with StateStore(tmp_path / "state.sqlite3") as state:
        seed_reviewed_baseline(state)
        exhaust_authorization(state)

        with pytest.raises(StateError):
            supersede(state, **changes)

        active = state.campaign_request_budget()
        assert active is not None
        assert active["authorization_id"] == AUTHORIZATION_ID
        assert active["is_active"] is True
        assert (
            state.campaign_request_budget(SUCCESSOR_AUTHORIZATION_ID)
            is None
        )


def test_handoff_rolls_back_if_successor_insert_fails(
    tmp_path: Path,
) -> None:
    """A database failure cannot leave the predecessor deactivated."""
    with StateStore(tmp_path / "state.sqlite3") as state:
        seed_reviewed_baseline(state)
        exhaust_authorization(state)
        with state.connection:
            state.connection.execute(
                f"""
                CREATE TRIGGER reject_test_successor
                BEFORE INSERT ON campaign_request_budgets
                WHEN NEW.authorization_id = '{SUCCESSOR_AUTHORIZATION_ID}'
                BEGIN
                    SELECT RAISE(ABORT, 'injected successor failure');
                END
                """
            )

        with pytest.raises(sqlite3.IntegrityError):
            supersede(state)

        predecessor = state.campaign_request_budget(AUTHORIZATION_ID)
        assert predecessor is not None
        assert predecessor["is_active"] is True
        assert state.campaign_request_budget() == predecessor
        assert (
            state.campaign_request_budget(SUCCESSOR_AUTHORIZATION_ID)
            is None
        )


def test_latest_started_read_timeout_is_recovered_atomically(
    tmp_path: Path,
) -> None:
    """The exact no-response timeout becomes a retryable charged failure."""
    with StateStore(tmp_path / "state.sqlite3") as state:
        seed_reviewed_baseline(state)
        activate(
            state,
            allowed_runs={RUN_A: 4},
            maximum_new_attempts=4,
        )
        spec = request(1)
        request_id = state.start_network_attempt(
            RUN_A,
            spec,
            attempted_at=BASELINE_TIME + timedelta(seconds=67),
        )

        recovered = state.recover_latest_started_read_timeout(
            request_id=request_id,
            run_id=RUN_A,
            sequence=spec.sequence,
            offset_value=spec.offset,
            request_hash=spec.request_hash,
            now=BASELINE_TIME + timedelta(seconds=70),
        )

        assert recovered["outcome"] == "http_error"
        assert recovered["error_text"] == RECOVERED_READ_TIMEOUT_ERROR
        assert recovered["http_status"] is None
        assert recovered["response_sha256"] is None
        assert recovered["response_path"] is None
        assert recovered["record_count"] is None
        assert is_no_response_transport_failure(recovered)
        assert state.run(RUN_A)["status"] == "failed"

        accounting = state.campaign_request_budget_accounting()
        assert accounting is not None
        assert accounting["new_attempts_used"] == 1
        assert accounting["unresolved_started_attempts"] == 0


def test_read_timeout_recovery_rejects_a_nonlatest_attempt(
    tmp_path: Path,
) -> None:
    """Even an exact older contract cannot be recovered after a later row."""
    with StateStore(tmp_path / "state.sqlite3") as state:
        seed_reviewed_baseline(state)
        activate(
            state,
            allowed_runs={RUN_A: 4},
            maximum_new_attempts=4,
        )
        older_spec = request(1)
        older_id = state.start_network_attempt(
            RUN_A,
            older_spec,
            attempted_at=BASELINE_TIME + timedelta(seconds=67),
        )
        finish(state, older_id)
        latest_spec = request(2)
        latest_id = state.start_network_attempt(
            RUN_A,
            latest_spec,
            attempted_at=BASELINE_TIME + timedelta(seconds=134),
        )

        with pytest.raises(StateError, match="latest request-ledger row"):
            state.recover_latest_started_read_timeout(
                request_id=older_id,
                run_id=RUN_A,
                sequence=older_spec.sequence,
                offset_value=older_spec.offset,
                request_hash=older_spec.request_hash,
            )

        assert state.request_attempts(RUN_A)[-1]["request_id"] == latest_id
        assert state.request_attempts(RUN_A)[-1]["outcome"] == "started"
        assert state.run(RUN_A)["status"] == "running"


def test_read_timeout_recovery_rejects_existing_response_metadata(
    tmp_path: Path,
) -> None:
    """A row with any response evidence requires manual review."""
    with StateStore(tmp_path / "state.sqlite3") as state:
        seed_reviewed_baseline(state)
        activate(
            state,
            allowed_runs={RUN_A: 4},
            maximum_new_attempts=4,
        )
        spec = request(1)
        request_id = state.start_network_attempt(
            RUN_A,
            spec,
            attempted_at=BASELINE_TIME + timedelta(seconds=67),
        )
        with state.connection:
            state.connection.execute(
                """
                UPDATE requests
                SET http_status = 200
                WHERE request_id = ?
                """,
                (request_id,),
            )

        with pytest.raises(StateError, match="response metadata"):
            state.recover_latest_started_read_timeout(
                request_id=request_id,
                run_id=RUN_A,
                sequence=spec.sequence,
                offset_value=spec.offset,
                request_hash=spec.request_hash,
            )

        attempt = state.request_attempts(RUN_A)[-1]
        assert attempt["outcome"] == "started"
        assert attempt["http_status"] == 200
        assert state.run(RUN_A)["status"] == "running"


@pytest.mark.parametrize(
    "changes",
    [
        {"request_id": 65},
        {"run_id": RUN_B},
        {"sequence": 2},
        {"offset_value": 100},
        {"request_hash": "f" * 64},
    ],
)
def test_read_timeout_recovery_rejects_wrong_request_contract(
    tmp_path: Path,
    changes: dict[str, object],
) -> None:
    """Every caller-supplied request identity field is fail-closed."""
    with StateStore(tmp_path / "state.sqlite3") as state:
        seed_reviewed_baseline(state)
        activate(
            state,
            allowed_runs={RUN_A: 4, RUN_B: 4},
            maximum_new_attempts=4,
        )
        spec = request(1)
        request_id = state.start_network_attempt(
            RUN_A,
            spec,
            attempted_at=BASELINE_TIME + timedelta(seconds=67),
        )
        contract: dict[str, object] = {
            "request_id": request_id,
            "run_id": RUN_A,
            "sequence": spec.sequence,
            "offset_value": spec.offset,
            "request_hash": spec.request_hash,
        }
        contract.update(changes)

        with pytest.raises(StateError):
            state.recover_latest_started_read_timeout(**contract)

        attempt = state.request_attempts(RUN_A)[-1]
        assert attempt["outcome"] == "started"
        assert attempt["error_text"] is None
        assert state.run(RUN_A)["status"] == "running"


def test_read_timeout_recovery_requires_active_authorization(
    tmp_path: Path,
) -> None:
    """Legacy unguarded rows cannot use the audited campaign recovery path."""
    with StateStore(tmp_path / "state.sqlite3") as state:
        insert_run(state, RUN_A)
        spec = request(1)
        request_id = state.start_network_attempt(
            RUN_A,
            spec,
            attempted_at=BASELINE_TIME,
        )

        with pytest.raises(StateError, match="active campaign"):
            state.recover_latest_started_read_timeout(
                request_id=request_id,
                run_id=RUN_A,
                sequence=spec.sequence,
                offset_value=spec.offset,
                request_hash=spec.request_hash,
            )

        assert state.request_attempts(RUN_A)[0]["outcome"] == "started"
