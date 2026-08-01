#!/usr/bin/env python3
"""Plan, authorize, verify, or execute Milestone 3.6 dataset completion."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.liquipedia_backfill.campaign import CampaignError
from src.liquipedia_backfill.completion import (
    DEFAULT_NEW_HTTP_ATTEMPT_CEILING,
    create_completion_plan,
    inspect_completion_preflight,
    write_completion_artifacts,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the deliberately offline-only M3.6 command."""
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--plan",
        action="store_true",
        help="Generate the immutable credential-free completion plan.",
    )
    mode.add_argument(
        "--preflight",
        action="store_true",
        help="Verify current ledger/cache evidence without mutation.",
    )
    mode.add_argument(
        "--execute",
        action="store_true",
        help="Execute the approved restart-safe authenticated campaign.",
    )
    mode.add_argument(
        "--activate-budget",
        action="store_true",
        help=(
            "Persist the approved global request ceiling after credential-free "
            "baseline verification. Makes no HTTP request and reads no key."
        ),
    )
    mode.add_argument(
        "--verify-execution-gate",
        action="store_true",
        help=(
            "Reverify the active persistent ceiling, cache, ledger, order, "
            "and resume state without reading credentials."
        ),
    )
    parser.add_argument(
        "--max-additional-network-attempts",
        type=int,
        default=DEFAULT_NEW_HTTP_ATTEMPT_CEILING,
    )
    parser.add_argument("--confirm-live-request-budget", type=int)
    parser.add_argument("--confirm-plan-fingerprint")
    parser.add_argument("--confirm-preflight-fingerprint")
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument(
        "--api-key-file",
        type=Path,
        default=ROOT / ".secrets" / "liquipedia_api_key",
        help=(
            "Ignored local key file. This path and its value are never "
            "included in reports."
        ),
    )
    return parser.parse_args(argv)


def _require_execution_confirmation(
    args: argparse.Namespace,
    *,
    plan_fingerprint: str,
) -> str:
    """Bind a mutating/live command to the exact reviewed artifacts."""
    if args.confirm_live_request_budget != (
        args.max_additional_network_attempts
    ):
        raise ValueError(
            "--confirm-live-request-budget must exactly match "
            "--max-additional-network-attempts."
        )
    if args.confirm_plan_fingerprint != plan_fingerprint:
        raise ValueError(
            "--confirm-plan-fingerprint must match the generated plan."
        )
    if not args.confirm_preflight_fingerprint:
        raise ValueError(
            "--confirm-preflight-fingerprint is required."
        )
    return str(args.confirm_preflight_fingerprint)


def _existing_partition_results(plan) -> list[dict[str, object]]:
    """Load prior credential-free progress for a safe process restart."""
    path = plan.output_directory / "execution_progress.json"
    if not path.is_file():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("plan_fingerprint") != plan.plan_fingerprint:
        raise ValueError("Existing M3.6 progress belongs to another plan.")
    values = payload.get("partitions", [])
    if not isinstance(values, list) or any(
        not isinstance(value, dict) for value in values
    ):
        raise ValueError("Existing M3.6 partition progress is malformed.")
    return [dict(value) for value in values]


def _partition_result_payload(
    validation,
    *,
    gate,
    tests: dict[str, object],
    attempts_this_invocation: int,
) -> dict[str, object]:
    """Flatten key metrics while retaining the complete validation evidence."""
    return {
        "partition_id": validation.partition_id,
        "run_id": validation.run_id,
        "status": "complete_validated",
        "http_attempts": validation.request_count,
        "cache_hits": validation.cache_hit_count,
        "http_attempts_this_invocation": attempts_this_invocation,
        "matches": validation.normalized_matches,
        "games": validation.normalized_games,
        "eligible_games": validation.eligible_games,
        "excluded_games": validation.excluded_games,
        "eligibility_pct": validation.eligibility_percentage,
        "duplicate_matches": validation.duplicate_matches,
        "duplicate_games": validation.duplicate_games,
        "quarantined_records": validation.quarantined_records,
        "validation": validation.to_payload(),
        "global_attempts_used": gate.new_attempts_used,
        "global_attempts_remaining": gate.new_attempts_remaining,
        "offline_tests": tests,
    }


def _execute_campaign(
    args: argparse.Namespace,
    *,
    plan,
    preflight_fingerprint: str,
) -> int:
    """Run all remaining partitions chronologically under one process lock."""
    from scripts.backfill_liquipedia_history import read_api_key
    from src.liquipedia_backfill.completion_execution import (
        campaign_execution_lock,
        execute_one_partition,
        live_partitions,
        run_offline_test_suite,
        verify_execution_gate,
        write_progress_evidence,
    )
    from src.liquipedia_backfill.completion_validation import (
        validate_completed_partition,
    )

    partition_results = _existing_partition_results(plan)
    by_id = {
        item.partition_id: item for item in live_partitions(plan)
    }
    with campaign_execution_lock(plan):
        gate = verify_execution_gate(
            plan,
            preflight_fingerprint=preflight_fingerprint,
        )
        if gate.new_attempts_remaining <= 0 and (
            gate.next_partition_id is not None
        ):
            raise ValueError(
                "The global 80-attempt ceiling is exhausted before the next "
                "required page. The API key was not read."
            )
        print("Persistent execution gate verified.", flush=True)
        print(
            "Request accounting before credential read: "
            f"{gate.new_attempts_used} used / "
            f"{gate.new_attempts_remaining} remaining; "
            f"cumulative expansion "
            f"{gate.cumulative_expansion_attempts}/"
            f"{gate.cumulative_expansion_ceiling}.",
            flush=True,
        )
        print(
            "Q2 cache reuse verified: "
            f"{gate.q2_cached_pages_verified} pages; "
            "July 2026 pilot reuse verified: "
            f"{gate.pilot_cached_pages_verified} pages.",
            flush=True,
        )
        if gate.recoverable_no_response_attempt_ids:
            print(
                "Charged no-response transport failure approved for one "
                "manual resume: request_id="
                + ",".join(
                    str(value)
                    for value in gate.recoverable_no_response_attempt_ids
                )
                + ".",
                flush=True,
            )
        recorded_ids = {
            str(item.get("partition_id")) for item in partition_results
        }
        next_ordinal = (
            by_id[gate.next_partition_id].ordinal
            if gate.next_partition_id is not None
            else 10_000
        )
        for completed in live_partitions(plan):
            if (
                completed.ordinal >= next_ordinal
                or completed.partition_id in recorded_ids
                or not (
                    completed.config.run_directory / "manifest.json"
                ).is_file()
            ):
                continue
            validation = validate_completed_partition(
                partition_id=completed.partition_id,
                config=completed.config,
                completed_prefix=tuple(
                    (
                        item.partition_id,
                        item.config.run_id,
                    )
                    for item in plan.partitions
                    if (
                        item.kind != "cached_pilot"
                        and item.ordinal <= completed.ordinal
                    )
                ),
                repository_root=plan.repository_root,
            )
            tests = run_offline_test_suite(plan.repository_root)
            gate = verify_execution_gate(
                plan,
                preflight_fingerprint=preflight_fingerprint,
            )
            partition_results.append(
                _partition_result_payload(
                    validation,
                    gate=gate,
                    tests=tests,
                    attempts_this_invocation=0,
                )
            )
            recorded_ids.add(completed.partition_id)
            write_progress_evidence(
                plan,
                gate=gate,
                partition_results=partition_results,
                stop_reason=None,
            )
            print(
                f"Recovered and revalidated completed partition "
                f"{completed.partition_id} from local evidence.",
                flush=True,
            )
        if gate.next_partition_id is None:
            write_progress_evidence(
                plan,
                gate=gate,
                partition_results=partition_results,
                stop_reason=None,
            )
            print("All authorized historical partitions are complete.")
            print("API key read: no")
            return 0

        api_key = read_api_key(args.api_key_file)
        try:
            while gate.next_partition_id is not None:
                partition = by_id.get(gate.next_partition_id)
                if partition is None:
                    raise ValueError(
                        "The derived next partition is not live-authorized."
                    )
                before_used = gate.new_attempts_used
                result = execute_one_partition(
                    plan,
                    partition,
                    gate=gate,
                    api_key=api_key,
                    timeout_seconds=args.timeout_seconds,
                )
                if result.status != "complete":
                    raise ValueError(
                        f"{partition.partition_id} stopped with acquisition "
                        f"status {result.status}."
                    )
                validation = validate_completed_partition(
                    partition_id=partition.partition_id,
                    config=partition.config,
                    completed_prefix=tuple(
                        (
                            item.partition_id,
                            item.config.run_id,
                        )
                        for item in plan.partitions
                        if (
                            item.kind != "cached_pilot"
                            and item.ordinal <= partition.ordinal
                        )
                    ),
                    repository_root=plan.repository_root,
                )
                tests = run_offline_test_suite(plan.repository_root)
                gate = verify_execution_gate(
                    plan,
                    preflight_fingerprint=preflight_fingerprint,
                )
                payload = _partition_result_payload(
                    validation,
                    gate=gate,
                    tests=tests,
                    attempts_this_invocation=(
                        gate.new_attempts_used - before_used
                    ),
                )
                partition_results = [
                    item
                    for item in partition_results
                    if item.get("partition_id")
                    != partition.partition_id
                ]
                partition_results.append(payload)
                write_progress_evidence(
                    plan,
                    gate=gate,
                    partition_results=partition_results,
                    stop_reason=None,
                )
                print(
                    f"Partition {partition.partition_id} passed: "
                    f"{payload['matches']} matches, "
                    f"{payload['games']} games, "
                    f"{payload['eligible_games']} eligible, "
                    f"{payload['excluded_games']} excluded; "
                    f"{payload['eligibility_pct']}% eligible.",
                    flush=True,
                )
                print(
                    f"Global attempts: {gate.new_attempts_used} used / "
                    f"{gate.new_attempts_remaining} remaining.",
                    flush=True,
                )
        finally:
            api_key = ""

    print("M3.6 authenticated acquisition and partition validation complete.")
    print("No model training, commit, or push was performed.")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Keep planning offline and make execution explicitly fingerprint-bound."""
    args = parse_args(argv)
    try:
        plan = create_completion_plan(
            ROOT,
            maximum_new_http_attempts=(
                args.max_additional_network_attempts
            ),
        )
        if args.activate_budget or args.verify_execution_gate or args.execute:
            preflight_fingerprint = _require_execution_confirmation(
                args,
                plan_fingerprint=plan.plan_fingerprint,
            )
            from src.liquipedia_backfill.completion_execution import (
                activate_global_budget,
                campaign_execution_lock,
                verify_execution_gate,
                write_authorization_evidence,
            )

            if args.activate_budget:
                with campaign_execution_lock(plan):
                    gate = activate_global_budget(
                        plan,
                        preflight_fingerprint=preflight_fingerprint,
                    )
                    paths = write_authorization_evidence(plan, gate)
                print("Persistent M3.6 request budget activated.")
                print("Authenticated requests made: 0")
                print("API key read: no")
                print(
                    "New HTTP attempts: "
                    f"{gate.new_attempts_used} used / "
                    f"{gate.new_attempts_remaining} remaining"
                )
                print(
                    "Cumulative expansion attempts: "
                    f"{gate.cumulative_expansion_attempts}/"
                    f"{gate.cumulative_expansion_ceiling}"
                )
                print(
                    "Q2 cache prefix: "
                    f"{gate.q2_cached_pages_verified} pages verified"
                )
                print(f"Next partition: {gate.next_partition_id}")
                print(f"Authorization JSON: {paths[0]}")
                print(f"Authorization Markdown: {paths[1]}")
                return 0
            if args.verify_execution_gate:
                with campaign_execution_lock(plan):
                    gate = verify_execution_gate(
                        plan,
                        preflight_fingerprint=preflight_fingerprint,
                    )
                print("Persistent M3.6 execution gate verified.")
                print("Authenticated requests made: 0")
                print("API key read: no")
                print(
                    "New HTTP attempts: "
                    f"{gate.new_attempts_used} used / "
                    f"{gate.new_attempts_remaining} remaining"
                )
                print(
                    "Cumulative expansion attempts: "
                    f"{gate.cumulative_expansion_attempts}/"
                    f"{gate.cumulative_expansion_ceiling}"
                )
                print(f"Next partition: {gate.next_partition_id}")
                return 0
            return _execute_campaign(
                args,
                plan=plan,
                preflight_fingerprint=preflight_fingerprint,
            )
        preflight = (
            inspect_completion_preflight(plan)
            if args.preflight
            else None
        )
        artifacts = write_completion_artifacts(
            plan,
            preflight=preflight,
        )
    except (
        CampaignError,
        OSError,
        RuntimeError,
        ValueError,
    ) as error:
        print(f"Milestone 3.6 command failed: {error}", file=sys.stderr)
        return 1

    print("Milestone 3.6 offline planning complete.")
    print("Authenticated requests made: 0")
    print("API key read: no")
    print(f"Plan fingerprint: {artifacts.plan_fingerprint}")
    print(f"Plan JSON: {artifacts.plan_json}")
    print(f"Plan Markdown: {artifacts.plan_markdown}")
    if artifacts.preflight_fingerprint is not None:
        print(
            "Preflight fingerprint: "
            f"{artifacts.preflight_fingerprint}"
        )
        print(f"Preflight JSON: {artifacts.preflight_json}")
        print(f"Preflight Markdown: {artifacts.preflight_markdown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
