#!/usr/bin/env python3
"""Run the fixed M4B.1 baselines on development data only."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.draft_ai_modeling.baseline_experiment import (  # noqa: E402
    BaselineExperimentError,
    run_baseline_experiment,
)
from src.draft_ai_modeling.loader import CorpusValidationError  # noqa: E402


DEFAULT_EXPERIMENT_CONFIG = Path("configs/modeling/m4b_baselines.json")
DEFAULT_OUTPUT_ROOT = Path("models/m4b")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fit B0-B3 on declared past-only development folds and tuning. "
            "Calibration and locked-test prediction are prohibited."
        )
    )
    parser.add_argument(
        "--experiment-config",
        type=Path,
        default=DEFAULT_EXPERIMENT_CONFIG,
        help="Credential-free M4B.1 experiment contract.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Ignored local root for content-addressed experiment artifacts.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = run_baseline_experiment(
            args.experiment_config,
            output_root=args.output_root,
        )
    except (
        BaselineExperimentError,
        CorpusValidationError,
        FileNotFoundError,
        ValueError,
    ) as error:
        print(f"Milestone 4B.1 baseline run failed: {error}", file=sys.stderr)
        return 1

    print("Milestone 4B.1 development baselines completed.")
    print(f"Build fingerprint: {result.build_fingerprint}")
    print(f"Output: {result.output_directory}")
    print("Calibration predictions: 0")
    print("Locked-test predictions: 0")
    print("Authenticated API requests: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
