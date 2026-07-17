# Dota 2 Draft Win Prediction

This repository is a small end-to-end machine learning portfolio project. Version one predicts whether Radiant wins using only information available when the draft finishes. A logistic-regression baseline is trained and evaluated in the third notebook; no deployment API or model artifact is included yet.

## Dataset

Source: [Dota 2 Matches (Pro Leagues) on Kaggle](https://www.kaggle.com/datasets/darianogina/dota-2-matches-pro-leagues)

The downloaded source has 193,773 rows and 130 columns covering professional matches from 2011-06-19 through 2024-10-15. The raw table contains match metadata, both teams, ten players and heroes, game patch, the winner, and many post-match statistics.

## Version-one question

> Given the ten selected heroes and the game patch, can we estimate the probability that Radiant wins?

This is deliberately narrow. A small, clearly defined project is easier to finish, test, explain in an interview, and improve later.

## Project structure and every project file

```text
dota2-ml-portfolio/
├── .gitignore
├── README.md
├── requirements.txt
├── src/
│   ├── __init__.py
│   ├── features.py
│   └── train_baseline.py
├── tests/
│   ├── test_features.py
│   └── test_train_baseline.py
├── data/
│   ├── README.md
│   ├── raw/
│   │   ├── dota2_matches.parquet
│   │   ├── dota2_matches_PREVIEW.csv
│   │   └── dota2_versions.csv
│   └── processed/
│       ├── dota2_matches_sample_30000.csv
│       └── sample_metadata.json
├── docs/
│   ├── DATA_GUIDE.md
│   └── column_inventory.csv
├── notebooks/
│   ├── README.md
│   ├── 01_eda.ipynb
│   ├── 02_feature_engineering.ipynb
│   └── 03_baseline_model.ipynb
└── scripts/
    ├── download_data.py
    └── make_sample.py
```

- `.gitignore`: excludes the local virtual environment, Python cache files, future model artifacts, and the full raw Parquet file. The reproducible 30,000-match sample is intentionally not ignored.
- `README.md`: the project overview, setup instructions, file map, and version-one goal.
- `requirements.txt`: pins DuckDB, pandas, plotting, scikit-learn, and notebook-execution dependencies for reproducibility.
- `src/__init__.py`: marks the reusable project code as a Python package.
- `src/features.py`: implements chronological splitting, train-only hero and patch vocabularies, side-aware feature encoding, unknown-category handling, target creation, and structural validation.
- `src/train_baseline.py`: provides reusable training and evaluation functions plus a command-line interface. Both models fit only the training split, and test evaluation is gated by validation performance.
- `tests/test_features.py`: checks split boundaries, side-aware encoding, unknown categories, leakage prevention, and missing-column errors.
- `tests/test_train_baseline.py`: checks the complete training workflow and verifies that the test split is skipped when the validation gate fails.
- `data/README.md`: explains the difference between immutable raw data and reproducible processed data.
- `data/raw/dota2_matches.parquet`: the full Kaggle match table. Keep it unchanged and do not commit it to GitHub.
- `data/raw/dota2_matches_PREVIEW.csv`: a small preview supplied by the dataset author for quick inspection.
- `data/raw/dota2_versions.csv`: maps `game_version_id` values to human-readable Dota 2 patch names and patch start dates.
- `data/processed/dota2_matches_sample_30000.csv`: the clean 30,000-match version-one sample with 25 columns.
- `data/processed/sample_metadata.json`: records source counts, sample dates, win rate, selection rules, columns, and a SHA-256 checksum.
- `docs/DATA_GUIDE.md`: junior-friendly explanation of the sample columns and the leakage policy.
- `docs/column_inventory.csv`: all 130 raw columns, data types, missingness, version-one decision, and reason.
- `notebooks/README.md`: explains the purpose and naming convention of the notebook folder.
- `notebooks/01_eda.ipynb`: executed, Chinese-language exploratory analysis covering data quality, target balance, time coverage, patches, hero picks, leakage, and a proposed chronological split.
- `notebooks/02_feature_engineering.ipynb`: executed, Chinese-language explanation with English-only code for chronological splitting, train-only vocabularies, side-aware hero encoding, patch encoding, unknown-category handling, and feature validation. It does not train a model.
- `notebooks/03_baseline_model.ipynb`: executed, Chinese-language explanation with English-only code that compares a majority-class baseline with logistic regression, evaluates validation and test metrics, and inspects hero coefficients.
- `scripts/download_data.py`: downloads and extracts the three public Kaggle source files; it preserves existing files unless `--force` is supplied.
- `scripts/make_sample.py`: reproducibly rebuilds the sample, metadata, and column inventory from the raw data.

The local `.venv/` folder is development tooling rather than a repository artifact. It contains the isolated Python dependencies used by the project and is ignored by Git.

## Rebuild the sample

From the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/download_data.py
python scripts/make_sample.py
```

The sampling rule is deterministic: matches must have a valid winner, a known patch, and ten distinct positive hero IDs with names. Eligible unique matches are ordered by the MD5 hash of `match_id`, the first 30,000 are selected, and the output is then sorted by match time. Running the script against the same raw data and DuckDB version should reproduce the same file.

## Run the notebooks

Open the numbered notebooks in VS Code or Jupyter and select the Python interpreter at `.venv/bin/python`. The notebooks are already executed, so their verified outputs are visible before rerunning them.

## Run the reusable pipeline

From the project root:

```bash
python -m src.train_baseline
```

This command rebuilds the features in memory, trains the dummy and logistic-regression baselines on the training split, checks validation performance, and prints the verified metrics. It does not save a model artifact.

To validate the code:

```bash
python -m pytest -q
```

The tests use small synthetic matches, so they check the important rules without repeatedly training on the full dataset.

## Baseline results

The chronological validation set contains 4,496 matches and the held-out test set contains 4,500 matches. The fixed logistic-regression baseline produced:

| Split | Accuracy | ROC-AUC | Log Loss |
| --- | ---: | ---: | ---: |
| Validation | 0.5318 | 0.5441 | 0.6928 |
| Test | 0.5247 | 0.5321 | 0.6949 |

On the test set, the class-prior dummy baseline achieved 0.5098 accuracy, 0.5000 ROC-AUC, and 0.6930 Log Loss. Logistic regression therefore learned a small amount of ranking signal, but its test probability quality did not beat the dummy baseline. This is a deliberately modest and honest version-one result, not a production-quality predictor.

## What comes later

The next sensible step is to update the notebooks to import the reusable feature code, add a small metrics report, and decide whether a local inference demo adds enough portfolio value. An API is optional.
