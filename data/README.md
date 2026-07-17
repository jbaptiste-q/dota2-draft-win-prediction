# Data folders

## `raw/`

Files downloaded from Kaggle live here and should remain unchanged. Treat raw data as evidence: processing code reads it, but never edits it. The large Parquet file is ignored by Git because GitHub repositories should not store replaceable bulk data.

## `processed/`

Files created by `scripts/make_sample.py` live here. They are reproducible outputs rather than manually edited data.

- `dota2_matches_sample_30000.csv` is the compact version-one dataset.
- `sample_metadata.json` is an audit record describing exactly how that sample was created.

If the processing logic changes, rerun the script instead of editing the CSV by hand.

