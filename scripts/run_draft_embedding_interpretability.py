#!/usr/bin/env python3
"""Run the bounded M8 Phase 4 hero-embedding interpretability export."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.draft_ai_modeling.embedding_config import (  # noqa: E402
    EmbeddingConfigError,
)
from src.draft_ai_modeling.embedding_experiment import (  # noqa: E402
    EmbeddingExperimentError,
)
from src.draft_ai_modeling.embedding_interpretability import (  # noqa: E402
    EmbeddingInterpretabilityError,
    run_embedding_interpretability,
)
from src.draft_ai_modeling.loader import CorpusValidationError  # noqa: E402


DEFAULT_EXPERIMENT_CONFIG = Path("configs/modeling/m8_embeddings.json")
DEFAULT_OUTPUT_ROOT = Path("models/m8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Export Part A main-effect and collapse-analysis artifacts "
            "plus Part B descriptive-only visualization artifacts for the "
            "M8 hero-embedding experiment. Calibration and locked test are "
            "sealed; Part B never influences selection."
        )
    )
    parser.add_argument(
        "--experiment-config",
        type=Path,
        default=DEFAULT_EXPERIMENT_CONFIG,
        help="Credential-free M8 experiment contract.",
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
        result = run_embedding_interpretability(
            args.experiment_config,
            output_root=args.output_root,
        )
    except (
        CorpusValidationError,
        EmbeddingConfigError,
        EmbeddingExperimentError,
        EmbeddingInterpretabilityError,
        FileNotFoundError,
        ValueError,
    ) as error:
        print(
            f"Milestone 8 interpretability export failed: {error}",
            file=sys.stderr,
        )
        return 1

    print("Milestone 8 interpretability export completed.")
    print(f"Output: {result.output_directory}")
    print("Part B artifacts are descriptive-only and not a qualifying candidate.")
    print("Calibration predictions: 0")
    print("Locked-test predictions: 0")
    print("Authenticated API requests: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
