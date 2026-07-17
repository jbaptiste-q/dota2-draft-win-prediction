# Dota 2 Draft Win Prediction

An end-to-end machine learning project that estimates whether Radiant will win a professional Dota 2 match using only the completed draft and game patch.

## Overview

I built this project to explore a practical question:

> How much information about the final result is already present when the draft ends?

The source dataset contains 193,773 professional matches from 2011 to 2024. I prepared a reproducible sample of 30,000 matches, designed features that are available before gameplay begins, and evaluated a logistic-regression baseline with a chronological split.

The project emphasizes reproducibility, leakage prevention, honest evaluation, and clear separation between analysis and reusable code.

## Project highlights

- 30,000 professional matches sampled from a 193,773-match Kaggle dataset
- 262 sparse features representing hero sides, game patches, and unknown categories
- Chronological train, validation, and test split
- Dummy baseline and logistic-regression comparison
- Reusable feature and training modules
- Six automated tests covering feature integrity and evaluation rules

## Results

| Split | Accuracy | ROC-AUC | Log Loss |
| --- | ---: | ---: | ---: |
| Validation | 0.5318 | 0.5441 | 0.6928 |
| Test | 0.5247 | 0.5321 | 0.6949 |

The class-prior baseline achieved 0.5000 ROC-AUC on the test set. Logistic regression captured a small amount of ranking signal, but its test Log Loss did not improve on the baseline. The result is useful as a transparent benchmark rather than a production-ready predictor.

## Method

1. **Prepare the data:** select matches with a valid result, known patch, and ten distinct hero picks.
2. **Split by time:** train on older matches and evaluate on newer matches to reflect patch and meta changes.
3. **Encode the draft:** represent Radiant heroes as `+1`, Dire heroes as `-1`, and game patches as categorical features.
4. **Handle new categories:** count heroes unseen during training and group unseen patches into an unknown category.
5. **Train baselines:** compare a class-prior predictor with regularized logistic regression.
6. **Evaluate:** report Accuracy, ROC-AUC, Log Loss, confusion matrices, ROC curves, and model coefficients.

## Leakage policy

The prediction point is immediately after the draft and before gameplay starts. Inputs therefore exclude:

- the winner and target columns
- kills, deaths, assists, net worth, match duration, and other match outcomes
- player roles or positions that may be inferred from gameplay
- match IDs and other tracking fields

Hero and patch vocabularies are learned from the training period only. The test set is evaluated only after the model passes the validation criteria.

## Repository structure

| Path | Purpose |
| --- | --- |
| `notebooks/01_eda.ipynb` | Explores data quality, target balance, time coverage, patches, and hero picks. |
| `notebooks/02_feature_engineering.ipynb` | Builds chronological splits and leakage-aware draft features. |
| `notebooks/03_baseline_model.ipynb` | Trains and evaluates the baseline models and interprets coefficients. |
| `src/features.py` | Provides reusable splitting, encoding, target, and feature-validation logic. |
| `src/train_baseline.py` | Runs the baseline training and evaluation workflow from the command line. |
| `tests/` | Tests split boundaries, feature integrity, unknown categories, and evaluation gating. |
| `scripts/download_data.py` | Downloads the public Kaggle source files. |
| `scripts/make_sample.py` | Rebuilds the processed sample and metadata. |
| `data/processed/` | Contains the 30,000-match sample and its metadata. |
| `docs/` | Documents source columns, feature decisions, and leakage risks. |

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m src.train_baseline
```

Run the tests with:

```bash
python -m pytest -q
```

## Rebuild the dataset

The processed sample is included in the repository. To rebuild it from the source data:

```bash
python scripts/download_data.py
python scripts/make_sample.py
```

The full raw Parquet file is excluded from Git because it can be downloaded again from the public source.

## Dataset

[Dota 2 Matches (Pro Leagues) on Kaggle](https://www.kaggle.com/datasets/darianogina/dota-2-matches-pro-leagues)

The dataset covers professional matches from 2011-06-19 through 2024-10-15 and includes teams, players, hero selections, patches, match results, and post-match statistics.

## Limitations

- The model uses professional matches and may not generalize to public matchmaking.
- Hero interactions are represented only through linear side-aware features.
- New patches are grouped together, which limits adaptation to major balance changes.
- The baseline has weak predictive power and should not be used for betting or competitive decisions.

## Possible extensions

- Add explicit hero-pair and team-composition interactions.
- Compare models using validation data without repeatedly inspecting the test set.
- Evaluate probability calibration across patches.
- Build a small local draft-analysis interface.
