#!/usr/bin/env python3
"""Publish a verified aggregate historical dataset without API access."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.liquipedia_backfill.publication import (
    PublicationConfig,
    PublicationError,
    PublicationMode,
    parse_partition_mapping,
    publish_historical_dataset,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the explicit offline publication command."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--partition",
        action="append",
        required=True,
        metavar="PARTITION_ID=RUN_ID",
        help=(
            "Ordered logical-partition to completed-run mapping. "
            "Repeat once per contiguous partition."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=[mode.value for mode in PublicationMode],
        required=True,
        help=(
            "Use full-window only for all 19 partitions; otherwise publish "
            "a clearly labeled contiguous prefix."
        ),
    )
    parser.add_argument(
        "--alias",
        help=(
            "Immutable logical alias. A scope-specific default is generated "
            "when omitted."
        ),
    )
    parser.add_argument(
        "--run-root",
        type=Path,
        default=Path("data/backfill/runs"),
    )
    parser.add_argument(
        "--normalized-output-root",
        type=Path,
        default=Path("data/processed/liquipedia"),
    )
    parser.add_argument(
        "--training-output-root",
        type=Path,
        default=Path("data/training/dota_draft_supervised"),
    )
    parser.add_argument(
        "--release-root",
        type=Path,
        default=Path("data/releases/dota_draft_historical"),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Verify and publish using only immutable local artifacts."""
    args = parse_args(argv)
    try:
        partition_runs = tuple(
            parse_partition_mapping(value) for value in args.partition
        )
        result = publish_historical_dataset(
            PublicationConfig(
                repository_root=ROOT,
                partition_runs=partition_runs,
                mode=PublicationMode(args.mode),
                alias=args.alias,
                run_root=args.run_root,
                normalized_output_root=args.normalized_output_root,
                training_output_root=args.training_output_root,
                release_root=args.release_root,
            )
        )
    except (OSError, ValueError, PublicationError) as error:
        print(f"Historical publication failed: {error}", file=sys.stderr)
        return 1

    print("Offline historical publication complete.")
    print("Authenticated requests made: 0")
    print(f"Release status: {result.release_status}")
    print(f"Release fingerprint: {result.release_fingerprint}")
    print(f"Release manifest: {result.release_manifest_path}")
    print(f"Alias: {result.alias}")
    print(f"Alias artifact: {result.alias_path}")
    print(f"Normalized build: {result.normalized_build}")
    print(f"Supervised build: {result.supervised_build}")
    print(f"Normalized games: {result.normalized_games}")
    print(f"Eligible games: {result.eligible_games}")
    print(f"Excluded games: {result.excluded_games}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
