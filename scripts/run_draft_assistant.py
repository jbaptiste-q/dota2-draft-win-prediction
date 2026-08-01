#!/usr/bin/env python3
"""Run the local completed-draft product slice without external API access."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import uvicorn


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the local Dota 2 Draft Assistant product slice."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 1 <= args.port <= 65535:
        raise SystemExit("--port must be between 1 and 65535")
    uvicorn.run(
        "src.draft_ai_assistant.api:app",
        host=args.host,
        port=args.port,
        reload=False,
        app_dir=str(PROJECT_ROOT),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
