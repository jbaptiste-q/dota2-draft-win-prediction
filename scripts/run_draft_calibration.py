#!/usr/bin/env python3
"""Run the bounded M4B.3 calibration gate without opening the locked test."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.draft_ai_modeling.calibration import CalibrationError  # noqa: E402
from src.draft_ai_modeling.calibration_config import (  # noqa: E402
    CalibrationConfigError,
)
from src.draft_ai_modeling.calibration_experiment import (  # noqa: E402
    CalibrationExperimentError,
    run_calibration_experiment,
)
from src.draft_ai_modeling.loader import CorpusValidationError  # noqa: E402
from src.draft_ai_modeling.model_bundle import ModelBundleError  # noqa: E402


DEFAULT_EXPERIMENT_CONFIG = Path("configs/modeling/m4b3_calibration.json")
DEFAULT_OUTPUT_ROOT = Path("models/m4b3")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Refit the frozen B1 candidate on Train + Tuning, compare raw, "
            "sigmoid, and isotonic on grouped Q4 calibration folds, and seal "
            "a bundle without predicting 2026-Q1."
        )
    )
    parser.add_argument(
        "--experiment-config",
        type=Path,
        default=DEFAULT_EXPERIMENT_CONFIG,
        help="Credential-free M4B.3 calibration contract.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Ignored local root for content-addressed calibration artifacts.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = run_calibration_experiment(
            args.experiment_config,
            output_root=args.output_root,
        )
    except (
        CalibrationConfigError,
        CalibrationError,
        CalibrationExperimentError,
        CorpusValidationError,
        ModelBundleError,
        FileNotFoundError,
        ValueError,
    ) as error:
        print(f"Milestone 4B.3 calibration failed: {error}", file=sys.stderr)
        return 1

    manifest = result.manifest_path
    print("Milestone 4B.3 calibration completed.")
    print(f"Build fingerprint: {result.build_fingerprint}")
    print(f"Manifest: {manifest}")
    print("Locked-test predictions: 0")
    print("Authenticated API requests: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
