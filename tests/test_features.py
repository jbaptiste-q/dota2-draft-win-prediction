"""Tests for chronological splitting and draft feature engineering."""

import pandas as pd
import pytest

from src.features import (
    FORBIDDEN_FEATURE_COLUMNS,
    DraftFeatureBuilder,
    add_chronological_split,
    prepare_features,
    validate_feature_matrix,
)


def make_match(
    match_time: str,
    radiant_win: int,
    radiant_heroes: list[int] | None = None,
    dire_heroes: list[int] | None = None,
    patch_id: int = 1,
) -> dict[str, int | str]:
    """Create one minimal valid match row for tests."""

    radiant_heroes = radiant_heroes or [1, 2, 3, 4, 5]
    dire_heroes = dire_heroes or [6, 7, 8, 9, 10]
    row: dict[str, int | str] = {
        "match_start_date_time": match_time,
        "game_version_id": patch_id,
        "radiant_win": radiant_win,
    }

    for slot, hero_id in enumerate(radiant_heroes, start=1):
        row[f"radiant_player_{slot}_hero_id"] = hero_id
    for slot, hero_id in enumerate(dire_heroes, start=1):
        row[f"dire_player_{slot}_hero_id"] = hero_id
    return row


def test_chronological_split_includes_boundary_rows() -> None:
    frame = pd.DataFrame(
        {
            "match_start_date_time": [
                "2022-11-10 23:59:59",
                "2022-11-11 00:00:00",
                "2022-11-11 00:00:01",
                "2023-11-19 08:14:29",
                "2023-11-19 08:14:30",
            ]
        }
    )

    result = add_chronological_split(frame)

    assert result["split"].tolist() == [
        "train",
        "train",
        "validation",
        "validation",
        "test",
    ]


def test_builder_uses_train_only_vocabularies_and_unknown_features() -> None:
    frame = pd.DataFrame(
        [
            make_match("2022-01-01", radiant_win=1),
            make_match(
                "2023-01-01",
                radiant_win=1,
                radiant_heroes=[1, 2, 3, 4, 99],
                patch_id=2,
            ),
        ]
    )
    builder = DraftFeatureBuilder().fit(frame.iloc[[0]])

    features = builder.transform(frame)
    validate_feature_matrix(features, builder)

    assert features.loc[0, "hero_1"] == 1
    assert features.loc[0, "hero_6"] == -1
    assert features.loc[1, "unknown_radiant_hero_count"] == 1
    assert features.loc[1, "unknown_dire_hero_count"] == 0
    assert features.loc[0, "patch_1"] == 1
    assert features.loc[1, "patch_1"] == 0
    assert features.loc[1, "patch_unknown"] == 1
    assert "hero_99" not in features.columns
    assert "patch_2" not in features.columns


def test_prepare_features_excludes_leakage_columns() -> None:
    frame = pd.DataFrame(
        [
            make_match("2022-01-01", radiant_win=1),
            make_match("2022-01-02", radiant_win=0),
            make_match("2023-01-01", radiant_win=1),
            make_match("2024-01-01", radiant_win=0),
        ]
    )
    frame["match_id"] = [101, 102, 103, 104]
    frame["winner_id"] = [1, 2, 1, 2]

    prepared = prepare_features(frame)

    assert FORBIDDEN_FEATURE_COLUMNS.isdisjoint(prepared.features.columns)
    assert prepared.features.index.equals(prepared.target.index)
    assert prepared.frame["split"].tolist() == [
        "train",
        "train",
        "validation",
        "test",
    ]


def test_builder_reports_missing_input_columns() -> None:
    incomplete_frame = pd.DataFrame({"game_version_id": [1]})

    with pytest.raises(ValueError, match="missing required columns"):
        DraftFeatureBuilder().fit(incomplete_frame)
