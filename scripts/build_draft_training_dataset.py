#!/usr/bin/env python3
"""Build the canonical supervised draft dataset from normalized Parquet."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.draft_training_dataset import (
    TrainingDatasetConfig,
    build_training_dataset,
)


def parse_utc_datetime(value: str) -> datetime:
    """Parse an explicitly timezone-aware ISO-8601 timestamp."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Training timestamps must include a timezone.")
    return parsed.astimezone(UTC)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the independent offline supervised-dataset command."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--normalized-build",
        type=Path,
        required=True,
        help="A verified Milestone 2 normalized build directory.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=ROOT / "data" / "training" / "dota_draft_supervised",
    )
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--tier", action="append", default=[])
    parser.add_argument("--patch", action="append", default=[])
    parser.add_argument("--tournament", action="append", default=[])
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Build, fingerprint, and report the canonical training dataset."""
    args = parse_args(argv)
    try:
        config = TrainingDatasetConfig(
            normalized_build=args.normalized_build,
            output_root=args.output_root,
            start_utc=parse_utc_datetime(args.start) if args.start else None,
            end_utc=parse_utc_datetime(args.end) if args.end else None,
            tiers=tuple(args.tier),
            patches=tuple(args.patch),
            tournaments=tuple(args.tournament),
        )
        result = build_training_dataset(config)
    except (OSError, ValueError) as error:
        print(f"Training dataset build failed: {error}", file=sys.stderr)
        return 1
    print(f"Dataset build: {result.output_directory}")
    print(f"Build fingerprint: {result.build_fingerprint}")
    print(f"Training rows: {result.training_rows}")
    print(f"Excluded rows: {result.excluded_rows}")
    print(f"Manifest: {result.manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
