#!/usr/bin/env python3
"""Milestone 9 Phase 2, Step 3: join committed labels back to raw text.

Reads data/derived/patch_labels/labels.json (committed -- no raw_text)
and re-derives raw_text from the local raw patch-note cache via
flatten_patch_changes(). The output always contains raw_text, which is
Valve's content, so this script refuses to write anywhere that
`git check-ignore` does not confirm is ignored.

Offline -- reads only local files already on disk, no network.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.patch_alignment.change_flattening import flatten_patch_changes  # noqa: E402
from src.patch_alignment.path_guard import assert_path_is_gitignored  # noqa: E402

DEFAULT_LABELS_PATH = Path("data/derived/patch_labels/labels.json")
DEFAULT_OUTPUT_PATH = Path("data/derived/patch_labels/review/labels_with_text.csv")

REVIEW_FIELDNAMES = [
    "change_uid", "patch", "hero_key", "scope", "json_path", "raw_text",
    "direction", "magnitude", "change_type", "confidence",
    "model_id", "prompt_version",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels-path", type=Path, default=DEFAULT_LABELS_PATH)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    return parser.parse_args()


def build_review_rows(labels: list[dict]) -> tuple[list[dict], list[str]]:
    labels_by_uid = {item["change_uid"]: item for item in labels}
    changes = flatten_patch_changes()

    rows: list[dict] = []
    missing_labels: list[str] = []
    for change in changes:
        label = labels_by_uid.get(change.change_uid)
        if label is None:
            missing_labels.append(change.change_uid)
            continue
        rows.append(
            {
                "change_uid": change.change_uid,
                "patch": change.patch,
                "hero_key": change.hero_key or "",
                "scope": change.scope,
                "json_path": change.json_path,
                "raw_text": change.raw_text,
                "direction": label["direction"],
                "magnitude": label["magnitude"],
                "change_type": label["change_type"],
                "confidence": label["confidence"],
                "model_id": label["model_id"],
                "prompt_version": label["prompt_version"],
            }
        )
    return rows, missing_labels


def main() -> int:
    args = parse_args()
    assert_path_is_gitignored(args.output_path)

    labels = json.loads(args.labels_path.read_text(encoding="utf-8"))
    rows, missing_labels = build_review_rows(labels)

    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    with args.output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Review sheet written: {args.output_path}")
    print(f"Rows: {len(rows)}  Changes with no committed label: {len(missing_labels)}")
    if missing_labels:
        print("First few unlabeled change_uids:", missing_labels[:10])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
