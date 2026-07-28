#!/usr/bin/env python3
"""Plan Milestone 3.5 offline and optionally certify Stage A completion."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.liquipedia_backfill.campaign import (
    CampaignConfig,
    check_partition_readiness,
    create_campaign_plan,
    inspect_campaign,
    ledger_request_row_count,
)
from src.liquipedia_backfill.campaign_reports import (
    VerificationEvidence,
    generate_campaign_artifacts,
)
from src.liquipedia_backfill.amendment import (
    Q1_2024_PARTITION_ID,
    create_2024_q1_budget_amendment,
    inspect_campaign_with_budget_amendment,
    write_budget_amendment_artifacts,
)


DEFAULT_REPORT = (
    ROOT
    / "docs"
    / "milestones"
    / "MILESTONE_3_5_STAGE_A_OFFLINE_CAMPAIGN_PLANNING.md"
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the offline-only command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--complete-stage-a",
        action="store_true",
        help=(
            "Run the full offline test suite and generate the mandatory "
            "Definition-of-Done report."
        ),
    )
    parser.add_argument(
        "--check-partition-readiness",
        metavar="PARTITION_ID",
        help=(
            "Offline-only order and campaign-budget gate for a separately "
            "approved partition command."
        ),
    )
    parser.add_argument(
        "--plan-budget-amendment",
        metavar="PARTITION_ID",
        help=(
            "Generate the approved credential-free partition budget "
            "amendment without invoking network or credential code."
        ),
    )
    parser.add_argument(
        "--include-approved-amendment",
        metavar="PARTITION_ID",
        help=(
            "Apply the approved amendment while deriving chronological "
            "partition readiness."
        ),
    )
    return parser.parse_args(argv)


def _run_offline_tests() -> VerificationEvidence:
    """Run the repository test suite and capture completion evidence."""
    command = [sys.executable, "-m", "pytest", "-q"]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    combined = "\n".join(
        part.strip()
        for part in (completed.stdout, completed.stderr)
        if part.strip()
    )
    if completed.returncode != 0:
        if combined:
            print(combined, file=sys.stderr)
        raise RuntimeError("Offline test suite failed; report not generated.")
    matches = re.findall(r"(\d+) passed", combined)
    if not matches:
        raise RuntimeError("Could not determine the passing test count.")
    passed_tests = int(matches[-1])
    summary_line = next(
        (
            line.strip()
            for line in reversed(combined.splitlines())
            if " passed" in line
        ),
        f"{passed_tests} passed",
    )
    return VerificationEvidence(
        command=".venv/bin/python -m pytest -q",
        summary=summary_line,
        passed_tests=passed_tests,
        passed=True,
    )


def main(argv: list[str] | None = None) -> int:
    """Generate plans without importing or invoking any HTTP client."""
    args = parse_args(argv)
    campaign = CampaignConfig(repository_root=ROOT)
    before = ledger_request_row_count(campaign.state_path)
    try:
        plan = create_campaign_plan(campaign)
        if args.plan_budget_amendment:
            if args.plan_budget_amendment != Q1_2024_PARTITION_ID:
                raise ValueError(
                    "Only the approved 2024-Q1 budget amendment is "
                    "supported."
                )
            amendment = create_2024_q1_budget_amendment(plan)
            artifacts = write_budget_amendment_artifacts(amendment)
            after = ledger_request_row_count(campaign.state_path)
            if after != before:
                raise RuntimeError(
                    "Budget-amendment planning changed the request ledger."
                )
            print("Offline partition budget amendment planned.")
            print("Authenticated requests made: 0")
            print("API key read: no")
            print(f"Partition: {amendment.partition_id}")
            print(f"Amended Run ID: {amendment.amended_config.run_id}")
            print(
                "Amendment fingerprint: "
                f"{artifacts.amendment_fingerprint}"
            )
            print(
                "Effective plan fingerprint: "
                f"{artifacts.effective_plan_fingerprint}"
            )
            print(f"JSON plan: {artifacts.json_path}")
            print(f"Markdown plan: {artifacts.markdown_path}")
            return 0
        if args.check_partition_readiness:
            if (
                args.include_approved_amendment
                and args.include_approved_amendment
                != Q1_2024_PARTITION_ID
            ):
                raise ValueError(
                    "Only the approved 2024-Q1 budget amendment is "
                    "supported."
                )
            preflight = inspect_campaign(plan)
            amendment = None
            if args.include_approved_amendment:
                amendment = create_2024_q1_budget_amendment(plan)
                preflight = inspect_campaign_with_budget_amendment(
                    plan,
                    amendment,
                )
            readiness = check_partition_readiness(
                preflight,
                args.check_partition_readiness,
            )
            after = ledger_request_row_count(campaign.state_path)
            if after != before:
                raise RuntimeError(
                    "Readiness check changed the request ledger."
                )
            print("Offline partition readiness check passed.")
            print("Authenticated requests made: 0")
            print(f"Partition: {readiness['partition_id']}")
            print(f"Run ID: {readiness['run_id']}")
            if amendment is not None:
                print(
                    "Budget amendment fingerprint: "
                    f"{amendment.amendment_fingerprint}"
                )
                print(
                    "Effective plan fingerprint: "
                    f"{amendment.effective_plan_fingerprint}"
                )
            print(
                "Remaining campaign attempts: "
                f"{readiness['remaining_campaign_attempts']}"
            )
            return 0
        if args.include_approved_amendment:
            raise ValueError(
                "--include-approved-amendment requires "
                "--check-partition-readiness."
            )
        verification = (
            _run_offline_tests()
            if args.complete_stage_a
            else None
        )
        artifacts = generate_campaign_artifacts(
            campaign,
            verification=verification,
            milestone_report_path=(
                DEFAULT_REPORT
                if args.complete_stage_a
                else None
            ),
            ledger_rows_before_stage_a=before,
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Campaign planning failed: {error}", file=sys.stderr)
        return 1

    after = ledger_request_row_count(campaign.state_path)
    if after != before:
        print(
            "Campaign planning failed: request ledger changed.",
            file=sys.stderr,
        )
        return 1

    print("Offline campaign planning complete.")
    print("Authenticated requests made: 0")
    print("API key read: no")
    print(f"Campaign ID: {artifacts.campaign_id}")
    print(
        "Configuration fingerprint: "
        f"{artifacts.configuration_fingerprint}"
    )
    print(
        "Campaign plan fingerprint: "
        f"{artifacts.campaign_plan_fingerprint}"
    )
    print(f"Plan: {artifacts.plan_json_path}")
    print(f"Preflight: {artifacts.preflight_json_path}")
    if artifacts.milestone_report_path is not None:
        print(f"Milestone report: {artifacts.milestone_report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
