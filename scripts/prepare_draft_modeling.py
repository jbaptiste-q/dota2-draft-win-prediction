#!/usr/bin/env python3
"""Prepare deterministic Milestone 4A modeling infrastructure offline."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.draft_ai_modeling.preparation import (  # noqa: E402
    ModelingPreparationError,
    prepare_modeling_infrastructure,
)
from src.draft_ai_modeling.loader import CorpusValidationError  # noqa: E402


DEFAULT_CORPUS_CONFIG = Path(
    "configs/modeling/m4a_working_corpus.json"
)
DEFAULT_OUTPUT_ROOT = Path("models/m4a")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verify the frozen supervised corpus and prepare split, feature, "
            "and unfitted-baseline contracts. No model is trained."
        )
    )
    parser.add_argument(
        "--corpus-config",
        type=Path,
        default=DEFAULT_CORPUS_CONFIG,
        help="Credential-free M4A working-corpus manifest.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Ignored local root for content-addressed preparation artifacts.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = prepare_modeling_infrastructure(
            args.corpus_config,
            output_root=args.output_root,
        )
    except (
        CorpusValidationError,
        ModelingPreparationError,
        FileNotFoundError,
        ValueError,
    ) as error:
        print(f"Milestone 4A preparation failed: {error}", file=sys.stderr)
        return 1

    print("Milestone 4A modeling infrastructure prepared.")
    print(f"Build fingerprint: {result.build_fingerprint}")
    print(f"Output: {result.output_directory}")
    print("Estimator training performed: no")
    print("Authenticated API requests: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
