"""Tests for the reusable baseline training workflow."""

import pandas as pd

from src.features import prepare_features
from src.train_baseline import train_baselines


def make_signal_match(
    match_time: pd.Timestamp,
    radiant_win: int,
) -> dict[str, int | pd.Timestamp]:
    """Create a match whose side-aware hero encoding has a clear signal."""

    if radiant_win == 1:
        radiant_heroes = [1, 2, 3, 4, 5]
        dire_heroes = [6, 7, 8, 9, 10]
    else:
        radiant_heroes = [6, 7, 8, 9, 10]
        dire_heroes = [1, 2, 3, 4, 5]

    row: dict[str, int | pd.Timestamp] = {
        "match_start_date_time": match_time,
        "game_version_id": 1,
        "radiant_win": radiant_win,
    }
    for slot, hero_id in enumerate(radiant_heroes, start=1):
        row[f"radiant_player_{slot}_hero_id"] = hero_id
    for slot, hero_id in enumerate(dire_heroes, start=1):
        row[f"dire_player_{slot}_hero_id"] = hero_id
    return row


def make_signal_dataset() -> pd.DataFrame:
    """Build small train, validation, and test periods."""

    rows = []
    for start_date, row_count in (
        ("2022-01-01", 40),
        ("2023-01-01", 20),
        ("2024-01-01", 20),
    ):
        dates = pd.date_range(start_date, periods=row_count, freq="D")
        for row_number, match_time in enumerate(dates):
            rows.append(make_signal_match(match_time, row_number % 2))
    return pd.DataFrame(rows)


def test_training_workflow_evaluates_test_after_validation_passes() -> None:
    prepared = prepare_features(make_signal_dataset())

    run = train_baselines(prepared)

    assert run.validation_gate_passed
    assert set(run.models) == {"Dummy prior", "Logistic regression"}
    assert set(run.metrics["split"]) == {"train", "validation", "test"}

    validation_row = run.metrics[
        run.metrics["model"].eq("Logistic regression")
        & run.metrics["split"].eq("validation")
    ].iloc[0]
    test_row = run.metrics[
        run.metrics["model"].eq("Logistic regression")
        & run.metrics["split"].eq("test")
    ].iloc[0]

    assert validation_row["roc_auc"] > 0.99
    assert test_row["roc_auc"] > 0.99


def test_training_workflow_skips_test_when_validation_fails() -> None:
    frame = make_signal_dataset()
    validation_mask = frame["match_start_date_time"].between(
        "2023-01-01",
        "2023-12-31",
    )
    frame.loc[validation_mask, "radiant_win"] = (
        1 - frame.loc[validation_mask, "radiant_win"]
    )
    prepared = prepare_features(frame)

    run = train_baselines(prepared)

    assert not run.validation_gate_passed
    assert "test" not in set(run.metrics["split"])
