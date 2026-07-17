"""Train and evaluate simple Dota 2 draft-win baseline models."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, log_loss, roc_auc_score

if __package__:
    from .features import (
        DATE_COLUMN,
        SPLIT_ORDER,
        PreparedFeatures,
        prepare_features,
    )
else:
    from features import (
        DATE_COLUMN,
        SPLIT_ORDER,
        PreparedFeatures,
        prepare_features,
    )


RANDOM_STATE = 42


@dataclass(frozen=True)
class BaselineRun:
    """Models, metrics, and prepared data from one baseline run."""

    prepared: PreparedFeatures
    models: dict[str, Any]
    metrics: pd.DataFrame
    validation_gate_passed: bool


def evaluate_model(
    model: Any,
    X_values: csr_matrix,
    y_values: np.ndarray,
    model_name: str,
    split_name: str,
) -> dict[str, float | str]:
    """Calculate the three metrics used in the baseline notebook."""

    probabilities = model.predict_proba(X_values)[:, 1]
    predictions = (probabilities >= 0.5).astype(np.int8)
    return {
        "model": model_name,
        "split": split_name,
        "accuracy": accuracy_score(y_values, predictions),
        "roc_auc": roc_auc_score(y_values, probabilities),
        "log_loss": log_loss(y_values, probabilities, labels=[0, 1]),
    }


def train_baselines(
    prepared: PreparedFeatures,
    random_state: int = RANDOM_STATE,
    evaluate_test: bool = True,
) -> BaselineRun:
    """Fit models on train rows, validate them, and optionally evaluate test."""

    X_all = csr_matrix(prepared.features.to_numpy(dtype=np.float32))
    y_all = prepared.target.to_numpy(dtype=np.int8)
    split_positions = {
        split_name: np.flatnonzero(
            prepared.frame["split"].eq(split_name).to_numpy()
        )
        for split_name in SPLIT_ORDER
    }

    empty_splits = [
        split_name
        for split_name, positions in split_positions.items()
        if len(positions) == 0
    ]
    if empty_splits:
        empty_text = ", ".join(empty_splits)
        raise ValueError(f"The following data splits are empty: {empty_text}")

    X_split = {
        split_name: X_all[positions]
        for split_name, positions in split_positions.items()
    }
    y_split = {
        split_name: y_all[positions]
        for split_name, positions in split_positions.items()
    }

    if len(np.unique(y_split["train"])) < 2:
        raise ValueError("The training target must contain both classes.")
    single_class_evaluation_splits = [
        split_name
        for split_name in ("validation", "test")
        if len(np.unique(y_split[split_name])) < 2
    ]
    if single_class_evaluation_splits:
        split_text = ", ".join(single_class_evaluation_splits)
        raise ValueError(
            f"ROC-AUC requires both target classes in these splits: {split_text}"
        )

    models = {
        "Dummy prior": DummyClassifier(
            strategy="prior",
            random_state=random_state,
        ),
        "Logistic regression": LogisticRegression(
            C=1.0,
            solver="liblinear",
            max_iter=1000,
            random_state=random_state,
        ),
    }

    for model in models.values():
        model.fit(X_split["train"], y_split["train"])

    metric_records = []
    for model_name, model in models.items():
        for split_name in ("train", "validation"):
            metric_records.append(
                evaluate_model(
                    model,
                    X_split[split_name],
                    y_split[split_name],
                    model_name,
                    split_name,
                )
            )

    validation_metrics = {
        record["model"]: record
        for record in metric_records
        if record["split"] == "validation"
    }
    logistic_validation = validation_metrics["Logistic regression"]
    dummy_validation = validation_metrics["Dummy prior"]
    validation_gate_passed = bool(
        logistic_validation["roc_auc"] > 0.5
        and logistic_validation["log_loss"] <= dummy_validation["log_loss"]
    )

    if evaluate_test and validation_gate_passed:
        for model_name, model in models.items():
            metric_records.append(
                evaluate_model(
                    model,
                    X_split["test"],
                    y_split["test"],
                    model_name,
                    "test",
                )
            )

    metrics = pd.DataFrame(metric_records)
    return BaselineRun(
        prepared=prepared,
        models=models,
        metrics=metrics,
        validation_gate_passed=validation_gate_passed,
    )


def run_training(
    data_path: Path,
    evaluate_test: bool = True,
) -> BaselineRun:
    """Load a CSV file and run the complete baseline workflow."""

    if not data_path.exists():
        raise FileNotFoundError(f"Data file not found: {data_path}")

    frame = pd.read_csv(data_path, parse_dates=[DATE_COLUMN])
    prepared = prepare_features(frame)
    return train_baselines(prepared, evaluate_test=evaluate_test)


def build_argument_parser() -> argparse.ArgumentParser:
    """Create the command-line interface."""

    project_root = Path(__file__).resolve().parents[1]
    default_data_path = (
        project_root / "data" / "processed" / "dota2_matches_sample_30000.csv"
    )

    parser = argparse.ArgumentParser(
        description="Train leakage-aware Dota 2 baseline models."
    )
    parser.add_argument(
        "--data",
        type=Path,
        default=default_data_path,
        help="Path to the processed match CSV.",
    )
    parser.add_argument(
        "--metrics-output",
        type=Path,
        default=None,
        help="Optional path for saving metrics as CSV.",
    )
    parser.add_argument(
        "--skip-test",
        action="store_true",
        help="Train and validate without evaluating the test split.",
    )
    return parser


def print_run_summary(run: BaselineRun) -> None:
    """Print a concise, readable summary for command-line use."""

    split_counts = (
        run.prepared.frame["split"]
        .value_counts()
        .reindex(SPLIT_ORDER)
        .rename_axis("split")
        .reset_index(name="matches")
    )
    metrics = run.metrics.copy()
    metrics[["accuracy", "roc_auc", "log_loss"]] = metrics[
        ["accuracy", "roc_auc", "log_loss"]
    ].round(4)

    print("\nData splits")
    print(split_counts.to_string(index=False))
    print(
        f"\nFeature matrix: {run.prepared.features.shape[0]:,} rows x "
        f"{run.prepared.features.shape[1]:,} columns"
    )
    print(
        f"Train-only vocabularies: "
        f"{len(run.prepared.builder.hero_vocabulary_)} heroes, "
        f"{len(run.prepared.builder.patch_vocabulary_)} patches"
    )
    print("\nMetrics")
    print(metrics.to_string(index=False))
    print(
        "\nValidation gate: "
        + ("PASS" if run.validation_gate_passed else "STOP")
    )

    if not run.validation_gate_passed:
        print("The test split was not evaluated because validation did not pass.")
    elif not run.metrics["split"].eq("test").any():
        print("The test split was not evaluated because --skip-test was used.")


def main() -> int:
    """Run the command-line training workflow."""

    parser = build_argument_parser()
    args = parser.parse_args()
    run = run_training(args.data, evaluate_test=not args.skip_test)
    print_run_summary(run)

    if args.metrics_output is not None:
        args.metrics_output.parent.mkdir(parents=True, exist_ok=True)
        run.metrics.to_csv(args.metrics_output, index=False)
        print(f"\nSaved metrics: {args.metrics_output.resolve()}")

    return 0 if run.validation_gate_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
