# Notebooks

The notebooks present the analysis in the order a reviewer would follow the project.

| Notebook | Focus |
| --- | --- |
| `01_eda.ipynb` | Examines data quality, target balance, time coverage, patch history, and hero-pick patterns. |
| `02_feature_engineering.ipynb` | Creates chronological splits and side-aware hero and patch features without leaking match outcomes. |
| `03_baseline_model.ipynb` | Compares a class-prior baseline with logistic regression and evaluates performance over time. |

The notebooks contain exploration and interpretation. Reusable feature and training logic lives in `src/`, with automated checks in `tests/`.
