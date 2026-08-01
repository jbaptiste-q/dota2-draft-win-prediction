#!/usr/bin/env python3
"""Run the bounded M4B.5 team-context recovery experiment offline."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.draft_ai_modeling.loader import CorpusValidationError  # noqa: E402
from src.draft_ai_modeling.team_context_config import (  # noqa: E402
    TeamContextConfigError,
)
from src.draft_ai_modeling.team_context_experiment import (  # noqa: E402
    TeamContextExperimentError,
    run_team_context_experiment,
)
from src.draft_ai_modeling.team_context_selection import (  # noqa: E402
    TeamContextSelectionError,
)
from src.draft_ai_modeling.team_strength import (  # noqa: E402
    TeamStrengthError,
)


DEFAULT_CONFIG = Path("configs/modeling/m4b5_team_context.json")
DEFAULT_OUTPUT_ROOT = Path("models/m4b5")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate exactly one B1-plus-pre-series-Elo candidate. "
            "2025-Q4 opens only after development qualification; "
            "2026-Q1 remains physically unopened."
        )
    )
    parser.add_argument(
        "--experiment-config",
        type=Path,
        default=DEFAULT_CONFIG,
        help="Credential-free fixed experiment contract.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Ignored root for content-addressed local outputs.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = run_team_context_experiment(
            args.experiment_config,
            output_root=args.output_root,
        )
    except (
        CorpusValidationError,
        TeamContextConfigError,
        TeamContextExperimentError,
        TeamContextSelectionError,
        TeamStrengthError,
        FileNotFoundError,
        ValueError,
    ) as error:
        print(f"M4B.5 team-context run failed: {error}", file=sys.stderr)
        return 1

    print("Milestone 4B.5 team-context experiment completed.")
    print(f"Build fingerprint: {result.build_fingerprint}")
    print(f"Development qualified: {result.development_qualified}")
    print(f"2025-Q4 opened: {result.q4_opened}")
    print(f"2025-Q4 readiness passed: {result.q4_readiness_passed}")
    print("2026-Q1 locked component opened: False")
    print("Authenticated API requests: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
