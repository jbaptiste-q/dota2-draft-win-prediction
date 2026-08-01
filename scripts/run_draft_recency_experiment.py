#!/usr/bin/env python3
"""Run the bounded M4B.2 B1 regularization and recency experiment."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.draft_ai_modeling.loader import CorpusValidationError  # noqa: E402
from src.draft_ai_modeling.recency_config import (  # noqa: E402
    RecencyConfigError,
)
from src.draft_ai_modeling.recency_experiment import (  # noqa: E402
    RecencyExperimentError,
    run_recency_experiment,
)


DEFAULT_EXPERIMENT_CONFIG = Path("configs/modeling/m4b2_recency.json")
DEFAULT_OUTPUT_ROOT = Path("models/m4b2")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare exactly nine B1 regularization/recency candidates on "
            "development windows only. Calibration and locked test are sealed."
        )
    )
    parser.add_argument(
        "--experiment-config",
        type=Path,
        default=DEFAULT_EXPERIMENT_CONFIG,
        help="Credential-free M4B.2 experiment contract.",
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
        result = run_recency_experiment(
            args.experiment_config,
            output_root=args.output_root,
        )
    except (
        CorpusValidationError,
        RecencyConfigError,
        RecencyExperimentError,
        FileNotFoundError,
        ValueError,
    ) as error:
        print(f"Milestone 4B.2 recency run failed: {error}", file=sys.stderr)
        return 1

    print("Milestone 4B.2 development experiment completed.")
    print(f"Build fingerprint: {result.build_fingerprint}")
    print(f"Output: {result.output_directory}")
    print("Calibration predictions: 0")
    print("Locked-test predictions: 0")
    print("Authenticated API requests: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
