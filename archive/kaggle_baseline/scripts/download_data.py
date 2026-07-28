"""Download and extract the public Kaggle source dataset.

Run this script from any directory. Existing raw files are preserved unless
--force is supplied.
"""

from __future__ import annotations

import argparse
import shutil
import urllib.request
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
ARCHIVE = RAW_DIR / "dota2-pro-leagues.zip"
DATASET_URL = (
    "https://www.kaggle.com/api/v1/datasets/download/"
    "darianogina/dota-2-matches-pro-leagues"
)
EXPECTED_FILES = {
    "dota2_matches.parquet",
    "dota2_matches_PREVIEW.csv",
    "dota2_versions.csv",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Download again even when all expected raw files already exist.",
    )
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    existing = {path.name for path in RAW_DIR.iterdir() if path.is_file()}
    if EXPECTED_FILES.issubset(existing) and not args.force:
        print("Raw dataset already exists; nothing downloaded. Use --force to replace it.")
        return

    request = urllib.request.Request(
        DATASET_URL,
        headers={"User-Agent": "dota2-ml-portfolio-data-setup/1.0"},
    )
    print(f"Downloading {DATASET_URL}")
    try:
        with urllib.request.urlopen(request) as response, ARCHIVE.open("wb") as output:
            shutil.copyfileobj(response, output)
        with zipfile.ZipFile(ARCHIVE) as archive:
            archive.extractall(RAW_DIR)
    finally:
        ARCHIVE.unlink(missing_ok=True)

    missing = EXPECTED_FILES - {path.name for path in RAW_DIR.iterdir()}
    if missing:
        raise RuntimeError(f"Download finished but expected files are missing: {sorted(missing)}")
    print(f"Extracted {len(EXPECTED_FILES)} files into {RAW_DIR}")


if __name__ == "__main__":
    main()

