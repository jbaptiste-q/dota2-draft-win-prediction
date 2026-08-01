#!/usr/bin/env python3
"""Run the bounded pre-Q4 M4B.4 Draft AI interaction experiment."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.draft_ai_modeling.interaction_config import (  # noqa: E402
    InteractionConfigError,
)
from src.draft_ai_modeling.interaction_experiment import (  # noqa: E402
    InteractionExperimentError,
    run_interaction_experiment,
)
from src.draft_ai_modeling.interaction_selection import (  # noqa: E402
    InteractionSelectionError,
)
from src.draft_ai_modeling.loader import CorpusValidationError  # noqa: E402


DEFAULT_EXPERIMENT_CONFIG = Path("configs/modeling/m4b4_interactions.json")
DEFAULT_OUTPUT_ROOT = Path("models/m4b4")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare exactly two regularized pick-interaction candidates on "
            "development folds through 2025-Q3. Q4 and Q1 remain sealed."
        )
    )
    parser.add_argument(
        "--experiment-config",
        type=Path,
        default=DEFAULT_EXPERIMENT_CONFIG,
        help="Credential-free M4B.4 experiment contract.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Ignored root for content-addressed local experiment artifacts.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = run_interaction_experiment(
            args.experiment_config,
            output_root=args.output_root,
        )
    except (
        CorpusValidationError,
        InteractionConfigError,
        InteractionExperimentError,
        InteractionSelectionError,
        FileNotFoundError,
        ValueError,
    ) as error:
        print(
            f"Milestone 4B.4 interaction run failed: {error}",
            file=sys.stderr,
        )
        return 1

    print("Milestone 4B.4 development interaction experiment completed.")
    print(f"Build fingerprint: {result.build_fingerprint}")
    print(f"Output: {result.output_directory}")
    print("2025-Q4 predictions: 0")
    print("2026-Q1 locked-test predictions: 0")
    print("Authenticated API requests: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
