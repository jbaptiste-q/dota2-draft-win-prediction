# Archived Kaggle Baseline

Status: **historical and deprecated**

This directory preserves the repository's original Kaggle-based draft-win
baseline as project history. It is not part of the active official-Liquipedia
pipeline, is not imported by the canonical packages, and is excluded from the
root test suite.

The snapshot includes:

- the original data download and sample-building scripts;
- leakage-aware feature and baseline-model modules;
- their unit tests;
- three analysis notebooks;
- the 30,000-row reproducible sample and metadata; and
- the original data and column documentation.

The active project lives at the repository root and uses only the official
Liquipedia API. Do not use this archive as a data source or model path for the
Draft AI product.

## Historical reproduction

The full Kaggle Parquet source remains intentionally untracked. To reproduce
this archived experiment independently:

```bash
cd archive/kaggle_baseline
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/download_data.py
python scripts/make_sample.py
python -m pytest -q tests
python -m src.train_baseline
```

This workflow is retained for provenance only and is not exercised by the
active repository CI.
