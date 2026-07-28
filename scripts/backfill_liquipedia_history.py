#!/usr/bin/env python3
"""Plan, execute, or finalize a bounded official Liquipedia match backfill."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.liquipedia_backfill.config import BackfillConfig, parse_utc_datetime
from src.liquipedia_backfill.finalize import finalize_completed_run
from src.liquipedia_backfill.planner import write_plan
from src.liquipedia_backfill.runner import BackfillRunner


PILOT_START = "2026-07-01T00:00:00Z"
PILOT_END = "2026-07-27T00:00:00Z"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse a safe-default command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--execute",
        action="store_true",
        help="Perform the bounded authenticated acquisition.",
    )
    mode.add_argument(
        "--finalize",
        action="store_true",
        help="Assemble and normalize an already completed acquisition.",
    )
    parser.add_argument("--start", default=PILOT_START)
    parser.add_argument("--end", default=PILOT_END)
    parser.add_argument(
        "--tier",
        action="append",
        dest="tiers",
        help="Liquipedia tier. Repeat as needed. Defaults to 1 and 2.",
    )
    parser.add_argument(
        "--patch",
        action="append",
        dest="patches",
        default=[],
        help="Post-normalization patch filter metadata. Repeat as needed.",
    )
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--max-requests", type=int, default=4)
    parser.add_argument(
        "--max-network-attempts",
        type=int,
        help=(
            "Optional cumulative HTTP-attempt ceiling for this run. It may "
            "be lower than --max-requests when verified cache pages occupy "
            "the earlier page slots."
        ),
    )
    parser.add_argument(
        "--require-cache-prefix-pages",
        type=int,
        default=0,
        help=(
            "Require this many leading pages to be present, checksum-valid, "
            "full, and nonterminal in immutable cache before state "
            "initialization or HTTP."
        ),
    )
    parser.add_argument("--hourly-limit", type=int, default=54)
    parser.add_argument("--request-interval-seconds", type=float, default=67.0)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument(
        "--api-key-file",
        type=Path,
        default=ROOT / ".secrets" / "liquipedia_api_key",
        help="Ignored local API key file. Read only in --execute mode.",
    )
    parser.add_argument(
        "--confirm-live-request-budget",
        type=int,
        help=(
            "Required with --execute and must exactly match the effective "
            "network-attempt ceiling (--max-network-attempts when provided, "
            "otherwise --max-requests). Prevents accidental live execution."
        ),
    )
    parser.add_argument(
        "--plan-output-root",
        type=Path,
        default=ROOT / "data" / "backfill" / "plans",
    )
    return parser.parse_args(argv)


def make_config(args: argparse.Namespace) -> BackfillConfig:
    """Build the approved configuration with repository-local artifact roots."""
    return BackfillConfig(
        start_utc=parse_utc_datetime(args.start),
        end_utc=parse_utc_datetime(args.end),
        tiers=tuple(args.tiers or ("1", "2")),
        patches=tuple(args.patches),
        page_size=args.page_size,
        max_requests=args.max_requests,
        hourly_request_limit=args.hourly_limit,
        request_interval_seconds=args.request_interval_seconds,
        raw_root=ROOT / "data" / "raw" / "liquipedia" / "backfill",
        run_root=ROOT / "data" / "backfill" / "runs",
        normalized_output_root=ROOT / "data" / "processed" / "liquipedia",
    )


def read_api_key(path: Path) -> str:
    """Read a local credential without printing or storing it."""
    key = os.environ.get("LIQUIPEDIA_API_KEY", "").strip()
    if not key:
        content = path.read_text(encoding="utf-8").strip()
        if content.startswith("LIQUIPEDIA_API_KEY="):
            content = content.split("=", maxsplit=1)[1].strip()
            if (
                len(content) >= 2
                and content[0] == content[-1]
                and content[0] in {'"', "'"}
            ):
                content = content[1:-1]
        key = content
    if not key or any(character.isspace() for character in key):
        raise ValueError("The local Liquipedia API key is missing or invalid.")
    return key


def main(argv: list[str] | None = None) -> int:
    """Use offline planning by default and require explicit live confirmation."""
    args = parse_args(argv)
    try:
        config = make_config(args)
        if args.execute:
            network_attempt_ceiling = (
                config.max_requests
                if args.max_network_attempts is None
                else args.max_network_attempts
            )
            if not 1 <= network_attempt_ceiling <= config.max_requests:
                raise ValueError(
                    "--max-network-attempts must be between 1 and "
                    f"--max-requests ({config.max_requests})."
                )
            if not (
                0
                <= args.require_cache_prefix_pages
                <= config.max_requests
            ):
                raise ValueError(
                    "--require-cache-prefix-pages must be between 0 and "
                    f"--max-requests ({config.max_requests})."
                )
            if args.confirm_live_request_budget != network_attempt_ceiling:
                raise ValueError(
                    "--confirm-live-request-budget must exactly match "
                    "the effective network-attempt ceiling "
                    f"({network_attempt_ceiling})."
                )
            api_key = read_api_key(args.api_key_file)
            try:
                result = BackfillRunner().run(
                    config,
                    api_key=api_key,
                    timeout_seconds=args.timeout_seconds,
                    max_network_attempts=network_attempt_ceiling,
                    required_cache_prefix_pages=(
                        args.require_cache_prefix_pages
                    ),
                )
            finally:
                api_key = ""
            print(f"Run ID: {result.run_id}")
            print(f"Status: {result.status}")
            print(f"API requests: {result.request_count}")
            print(f"Cache hits: {result.cache_hit_count}")
            print(f"Checkpoint: {result.checkpoint_path}")
            return 0 if result.status == "complete" else 2

        if args.finalize:
            result = finalize_completed_run(config)
            print(f"Acquisition fingerprint: {result.acquisition_fingerprint}")
            print(f"Assembly: {result.assembly.output_directory}")
            print(
                "Normalized build: "
                f"{result.normalized.export.output_directory}"
            )
            print(f"Manifest: {result.manifest_path}")
            return 0

        output_directory = args.plan_output_root / config.run_id
        json_path, markdown_path = write_plan(
            config,
            output_directory=output_directory,
        )
        print("Offline plan only. Authenticated requests made: 0")
        print(f"Run ID: {config.run_id}")
        print(f"JSON plan: {json_path}")
        print(f"Markdown plan: {markdown_path}")
        return 0
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Backfill command failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
