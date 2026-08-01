"""Emit canonical FastAPI responses for offline Worker parity tests."""

from __future__ import annotations

import json
from pathlib import Path
import sys

from fastapi.testclient import TestClient


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT))

from src.draft_ai_assistant.api import create_app  # noqa: E402
from src.draft_ai_assistant.service import DraftAssistantService  # noqa: E402


RADIANT = ["axe", "bane", "chen", "doom", "invoker"]
DIRE = ["lina", "lion", "puck", "tiny", "zeus"]
NEGATIVE_RADIANT = [
    "hoodwink",
    "dawnbreaker",
    "death-prophet",
    "drow-ranger",
    "snapfire",
]
NEGATIVE_DIRE = ["chen", "enigma", "bane", "naga-siren", "mirana"]


def main() -> None:
    app = create_app(DraftAssistantService.from_default_snapshot())
    with TestClient(app) as client:
        payload = {
            "health": client.get("/api/v1/health").json(),
            "heroes": client.get("/api/v1/heroes").json(),
            "model_card": client.get("/api/v1/model-card").json(),
            "analysis": client.post(
                "/api/v1/analyze",
                json={
                    "radiant_picks": RADIANT,
                    "dire_picks": DIRE,
                },
            ).json(),
            "permuted_analysis": client.post(
                "/api/v1/analyze",
                json={
                    "radiant_picks": list(reversed(RADIANT)),
                    "dire_picks": list(reversed(DIRE)),
                },
            ).json(),
            "replacement": client.post(
                "/api/v1/replacement-comparisons",
                json={
                    "radiant_picks": RADIANT,
                    "dire_picks": DIRE,
                    "side": "radiant",
                    "hero_to_replace": "axe",
                    "replacement_hero": "abaddon",
                },
            ).json(),
            "negative_analysis": client.post(
                "/api/v1/analyze",
                json={
                    "radiant_picks": NEGATIVE_RADIANT,
                    "dire_picks": NEGATIVE_DIRE,
                },
            ).json(),
            "dire_replacement": client.post(
                "/api/v1/replacement-comparisons",
                json={
                    "radiant_picks": NEGATIVE_RADIANT,
                    "dire_picks": NEGATIVE_DIRE,
                    "side": "dire",
                    "hero_to_replace": "chen",
                    "replacement_hero": "abaddon",
                },
            ).json(),
            "unsupported": client.post(
                "/api/v1/analyze",
                json={
                    "radiant_picks": [
                        "brand-new-hero",
                        *RADIANT[1:],
                    ],
                    "dire_picks": DIRE,
                },
            ).json(),
        }
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
