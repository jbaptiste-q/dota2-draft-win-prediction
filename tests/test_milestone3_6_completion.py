"""Offline contract tests for Milestone 3.6 completion planning."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.complete_liquipedia_history import main as completion_main
from src.liquipedia_backfill.campaign import CampaignError
from src.liquipedia_backfill.completion import (
    DEFAULT_NEW_HTTP_ATTEMPT_CEILING,
    FINAL_RELEASE_ALIAS,
    Q2_2024_AMENDED_RUN_ID,
    Q2_2024_PARTITION_ID,
    certify_completion_preflight,
    create_completion_plan,
    write_completion_artifacts,
)


def partition(plan, partition_id: str):
    """Return one logical completion partition."""
    return next(
        item
        for item in plan.partitions
        if item.partition_id == partition_id
    )


def valid_preflight(plan) -> dict[str, object]:
    """Build a minimal already-verified M3.5 state for pure gate tests."""
    q2 = partition(plan, Q2_2024_PARTITION_ID)
    return {
        "campaign_plan_fingerprint": (
            plan.base_campaign.plan_fingerprint
        ),
        "campaign_state_fingerprint": "state-fingerprint",
        "request_accounting": {
            "m3_5_additional_attempts_used": 63,
        },
        "partitions": [
            {
                "partition_id": "2024-Q1",
                "run_id": "m3_20240101_20240401_2c59812252db",
                "ledger_status": "complete",
                "effective_status": "complete",
            },
            {
                "partition_id": "2024-Q2",
                "run_id": "m3_20240401_20240701_6575003bb769",
                "ledger_status": "budget_exhausted",
                "effective_status": "blocked",
                "request_count": 8,
                "accepted_page_count": 8,
                "records_seen": 800,
                "next_sequence": 9,
                "next_offset": 800,
                "verified_pages": [
                    {
                        "sequence": sequence,
                        "record_count": 100,
                        "is_final_page": False,
                        "source_kind": "network",
                        "request_hash": q2.request_specs[
                            sequence - 1
                        ].request_hash,
                        "response_sha256": f"{sequence:064x}",
                    }
                    for sequence in range(1, 9)
                ],
            },
        ],
        "resume": {
            "blocking_reason": "2024-Q2:partition_budget_exhausted",
        },
        "pilot_reuse": {
            "verified": True,
            "run_id": "m3_20260701_20260727_0b40ae8811d6",
            "network_request_required": False,
        },
    }


def test_completion_plan_is_root_independent_and_preserves_boundaries(
    tmp_path: Path,
) -> None:
    first = create_completion_plan(tmp_path / "one")
    second = create_completion_plan(tmp_path / "two")

    assert first.plan_fingerprint == second.plan_fingerprint
    assert len(first.partitions) == 19
    assert first.maximum_new_http_attempts == (
        DEFAULT_NEW_HTTP_ATTEMPT_CEILING
    )
    assert first.cumulative_expansion_attempt_ceiling == 143
    assert first.identity_payload()["final_publication"]["alias"] == (
        FINAL_RELEASE_ALIAS
    )

    for previous, current in zip(
        first.partitions,
        first.partitions[1:],
        strict=False,
    ):
        assert previous.config.end_utc == current.config.start_utc
    assert first.partitions[0].partition_id == "2022-Q1"
    assert first.partitions[-1].partition_id == "2026-07-pilot"


def test_completion_plan_reuses_q2_prefix_and_bounds_new_slots(
    tmp_path: Path,
) -> None:
    plan = create_completion_plan(tmp_path)
    q2 = partition(plan, Q2_2024_PARTITION_ID)
    base_q2 = next(
        item
        for item in plan.base_campaign.partitions
        if item.partition_id == Q2_2024_PARTITION_ID
    )

    assert q2.config.run_id == Q2_2024_AMENDED_RUN_ID
    assert q2.config.max_requests == 20
    assert q2.required_cache_prefix_pages == 8
    assert q2.maximum_new_http_attempts == 12
    assert [item.sequence for item in q2.request_specs[8:]] == list(
        range(9, 21)
    )
    assert [item.offset for item in q2.request_specs[8:]] == list(
        range(800, 2000, 100)
    )
    assert [
        item.request_hash for item in q2.request_specs[:8]
    ] == [
        item.request_hash for item in base_q2.request_specs
    ]
    assert q2.request_specs[8].request_hash == (
        "b9180afeb42f5af39906dfbd4096f4f5c2601f479b0d8212d6619907e9a9ec54"
    )

    for partition_id in (
        "2024-Q3",
        "2024-Q4",
        "2025-Q1",
        "2025-Q2",
        "2025-Q3",
        "2025-Q4",
        "2026-Q1",
        "2026-Q2",
    ):
        item = partition(plan, partition_id)
        assert item.config.max_requests == 20
        assert item.maximum_new_http_attempts == 20
        assert item.required_cache_prefix_pages == 0


def test_preflight_certifies_exact_state_and_is_deterministic(
    tmp_path: Path,
) -> None:
    plan = create_completion_plan(tmp_path)
    source = valid_preflight(plan)

    first = certify_completion_preflight(
        plan,
        amended_campaign_preflight=source,
        ledger_attempt_count=65,
    )
    second = certify_completion_preflight(
        plan,
        amended_campaign_preflight=source,
        ledger_attempt_count=65,
    )

    assert first == second
    assert first["status"] == "ready_for_authenticated_approval"
    assert first["q2_cache_prefix"]["verified_pages"] == 8
    assert first["q2_cache_prefix"]["records"] == 800
    assert first["q2_cache_prefix"]["maximum_new_http_attempts"] == 12
    assert len(first["q2_cache_prefix"]["verified_prefix_hashes"]) == 8
    assert first["authorization"]["new_http_attempt_ceiling"] == 80
    assert first["authorization"][
        "cumulative_expansion_attempt_ceiling"
    ] == 143
    assert first["authenticated_requests_performed_by_preflight"] == 0
    assert first["api_key_read_by_preflight"] is False


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("ledger", "65-attempt ledger"),
        ("attempts", "63-attempt expansion"),
        ("prefix_hash", "request hashes changed"),
        ("terminal_page", "contiguous full"),
        ("response_hash", "response hashes"),
        ("pilot", "pilot is not reusable"),
    ],
)
def test_preflight_fails_closed_on_campaign_drift(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    plan = create_completion_plan(tmp_path)
    source = valid_preflight(plan)
    ledger_attempts = 65
    if mutation == "ledger":
        ledger_attempts = 66
    elif mutation == "attempts":
        source["request_accounting"]["m3_5_additional_attempts_used"] = 64
    elif mutation == "prefix_hash":
        source["partitions"][1]["verified_pages"][0][
            "request_hash"
        ] = "0" * 64
    elif mutation == "terminal_page":
        source["partitions"][1]["verified_pages"][0][
            "is_final_page"
        ] = True
    elif mutation == "response_hash":
        source["partitions"][1]["verified_pages"][0][
            "response_sha256"
        ] = "not-a-sha256"
    else:
        source["pilot_reuse"]["network_request_required"] = True

    with pytest.raises(CampaignError, match=message):
        certify_completion_preflight(
            plan,
            amended_campaign_preflight=source,
            ledger_attempt_count=ledger_attempts,
        )


def test_plan_artifacts_are_credential_free_and_immutable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = "LOCAL-SECRET-MUST-NOT-APPEAR"
    monkeypatch.setenv("LIQUIPEDIA_API_KEY", marker)
    plan = create_completion_plan(tmp_path)
    preflight = certify_completion_preflight(
        plan,
        amended_campaign_preflight=valid_preflight(plan),
        ledger_attempt_count=65,
    )

    first = write_completion_artifacts(plan, preflight=preflight)
    before = {
        path: path.read_bytes()
        for path in (
            first.plan_json,
            first.plan_markdown,
            first.preflight_json,
            first.preflight_markdown,
        )
    }
    second = write_completion_artifacts(plan, preflight=preflight)

    assert second.plan_fingerprint == first.plan_fingerprint
    assert second.preflight_fingerprint == first.preflight_fingerprint
    assert {
        path: path.read_bytes() for path in before
    } == before
    combined = b"".join(before.values()).decode("utf-8")
    assert marker not in combined
    assert "Apikey" not in combined
    assert ".secrets" not in combined
    assert str(tmp_path.resolve()) not in combined


def test_execute_boundary_requires_exact_artifact_fingerprints_before_credentials(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = completion_main(
        [
            "--execute",
            "--max-additional-network-attempts",
            "80",
            "--confirm-live-request-budget",
            "80",
        ]
    )

    assert result == 1
    captured = capsys.readouterr()
    assert "--confirm-plan-fingerprint" in captured.err
    assert "API key" not in captured.out
