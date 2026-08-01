#!/usr/bin/env python3
"""Plan, authorize, verify, or execute the bounded 2026-Q2 continuation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.liquipedia_backfill.campaign import CampaignError
from src.liquipedia_backfill.completion_execution import (
    campaign_execution_lock,
)
from src.liquipedia_backfill.q2_completion import (
    SUCCESSOR_MAXIMUM_NEW_ATTEMPTS,
    activate_successor_budget,
    create_q2_continuation_plan,
    execute_q2_continuation,
    recover_unresolved_read_timeout,
    verify_successor_budget,
    write_authorization_artifacts,
    write_plan_artifacts,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--activate-budget", action="store_true")
    mode.add_argument("--verify-budget", action="store_true")
    mode.add_argument("--recover-read-timeout", action="store_true")
    mode.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-continuation-fingerprint")
    parser.add_argument("--confirm-live-request-budget", type=int)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument(
        "--api-key-file",
        type=Path,
        default=ROOT / ".secrets" / "liquipedia_api_key",
    )
    return parser.parse_args(argv)


def _require_confirmation(args: argparse.Namespace, fingerprint: str) -> None:
    if args.confirm_continuation_fingerprint != fingerprint:
        raise ValueError(
            "--confirm-continuation-fingerprint must match the exact plan."
        )
    if (
        args.confirm_live_request_budget
        != SUCCESSOR_MAXIMUM_NEW_ATTEMPTS
    ):
        raise ValueError(
            "--confirm-live-request-budget must equal the 12-attempt "
            "successor ceiling."
        )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        plan = create_q2_continuation_plan(ROOT)
        if args.plan:
            paths = write_plan_artifacts(plan)
            print("Offline 2026-Q2 continuation plan generated.")
            print("Authenticated requests made: 0")
            print("API key read: no")
            print(f"Continuation fingerprint: {plan.fingerprint}")
            print(f"Plan JSON: {paths[0]}")
            print(f"Plan Markdown: {paths[1]}")
            return 0

        if args.verify_budget:
            with campaign_execution_lock(plan.completion_plan):
                gate = verify_successor_budget(plan)
            print("Offline 2026-Q2 successor gate verified.")
            print("Authenticated requests made: 0")
            print("API key read: no")
            print(f"Run status: {gate.run_status}")
            print(
                "Successor attempts: "
                f"{gate.new_attempts_used} used / "
                f"{gate.new_attempts_remaining} remaining"
            )
            return 0

        _require_confirmation(args, plan.fingerprint)
        if args.activate_budget:
            with campaign_execution_lock(plan.completion_plan):
                gate = activate_successor_budget(plan)
                paths = write_authorization_artifacts(plan, gate)
            print("Offline 2026-Q2 successor budget activated.")
            print("Authenticated requests made: 0")
            print("API key read: no")
            print(f"Authorization: {gate.authorization_id}")
            print(f"Authorization JSON: {paths[0]}")
            print(f"Authorization Markdown: {paths[1]}")
            return 0
        if args.recover_read_timeout:
            with campaign_execution_lock(plan.completion_plan):
                gate, paths = recover_unresolved_read_timeout(plan)
            print("Offline 2026-Q2 read-timeout recovery complete.")
            print("Authenticated requests made: 0")
            print("API key read: no")
            print(
                "The timeout attempt remains charged: "
                f"{gate.new_attempts_used} used / "
                f"{gate.new_attempts_remaining} remaining"
            )
            print(f"Recovered request: {gate.transport_failure_attempt_id}")
            print(f"Recovery JSON: {paths[0]}")
            print(f"Recovery Markdown: {paths[1]}")
            return 0

        def load_api_key() -> str:
            from scripts.backfill_liquipedia_history import read_api_key

            return read_api_key(args.api_key_file)

        gate, validation, tests, report_paths = execute_q2_continuation(
            plan,
            api_key_loader=load_api_key,
            timeout_seconds=args.timeout_seconds,
        )
        print("2026-Q2 acquisition and validation complete.")
        print(
            "Successor attempts: "
            f"{gate.new_attempts_used} used / "
            f"{gate.new_attempts_remaining} remaining"
        )
        print(f"Partition records: {gate.records_seen}")
        print(f"Normalized matches: {validation.normalized_matches}")
        print(f"Normalized games: {validation.normalized_games}")
        print(f"Eligible games: {validation.eligible_games}")
        print(f"Excluded games: {validation.excluded_games}")
        print(f"Offline tests: {tests['summary']}")
        print(f"Report JSON: {report_paths[0]}")
        print(f"Report Markdown: {report_paths[1]}")
        print("No model fitting was performed.")
        return 0
    except (CampaignError, OSError, RuntimeError, ValueError) as error:
        print(f"2026-Q2 continuation failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
