# Data

This directory separates source files from the compact dataset used by the project.

## `raw/`

| File | Purpose |
| --- | --- |
| `dota2_matches.parquet` | Full professional-match table downloaded from Kaggle. It is kept locally and excluded from Git. |
| `dota2_matches_PREVIEW.csv` | Small source preview for quick schema checks. |
| `dota2_versions.csv` | Maps game-version IDs to patch names and release dates. |

Raw files remain unchanged so the processing workflow can be reproduced from a stable source.

## `processed/`

| File | Purpose |
| --- | --- |
| `dota2_matches_sample_30000.csv` | Analysis-ready sample containing 30,000 valid matches and 25 selected columns. |
| `sample_metadata.json` | Records sample criteria, summary statistics, column order, and checksum. |

Rebuild the processed files with:

```bash
python scripts/make_sample.py
```
