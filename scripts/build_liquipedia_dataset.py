#!/usr/bin/env python3
"""Build normalized and ML-ready datasets from saved Liquipedia responses."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.liquipedia_pipeline.pipeline import run_pipeline


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the offline dataset-build command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        action="append",
        required=True,
        help="Saved official Liquipedia response JSON. Repeat as needed.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=ROOT / "data" / "processed" / "liquipedia",
        help="Root directory for content-addressed dataset builds.",
    )
    parser.add_argument(
        "--csv",
        action="store_true",
        help="Also export CSV copies alongside preferred Parquet files.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the deterministic offline pipeline."""
    args = parse_args(argv)
    try:
        result = run_pipeline(
            args.input,
            output_root=args.output_root,
            include_csv=args.csv,
        )
    except (OSError, ValueError) as error:
        print(f"Pipeline failed: {error}", file=sys.stderr)
        return 1

    print(f"Dataset build: {result.export.output_directory}")
    print(f"Build fingerprint: {result.export.build_fingerprint}")
    print(f"Parsed matches: {len(result.parsed_matches)}")
    print(f"Normalized games: {len(result.tables.games)}")
    print(f"Trainable draft games: {len(result.tables.ml_draft_games)}")
    print(f"Manifest: {result.export.manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
