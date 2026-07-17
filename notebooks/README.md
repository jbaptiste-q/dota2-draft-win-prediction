# Notebooks

Notebooks are numbered in the order a reviewer should read them.

- `01_eda.ipynb` performs exploratory data analysis and data-quality checks. It does not train a model.
- `02_feature_engineering.ipynb` creates chronological split labels and leakage-aware numeric features in memory. Its code is English-only, and it does not train a model or write model artifacts.
- `03_baseline_model.ipynb` trains a majority-class baseline and a logistic-regression model, evaluates chronological validation and test sets, and inspects coefficients. Its code is English-only.

Keeping notebooks separate from reusable code makes the repository easier to review: explanations and exploration belong here, while repeatable data preparation belongs in `scripts/`.
