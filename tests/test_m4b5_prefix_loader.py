"""Focused tests for whole-component, pre-boundary corpus loading."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from src.draft_ai_modeling import loader
from src.draft_ai_modeling.loader import (
    AggregateExpectations,
    CorpusComponent,
    CorpusValidationError,
    TimeScope,
    WorkingCorpusConfig,
    load_working_corpus_prefix,
)
from src.draft_training_dataset.schema import TRAINING_COLUMNS


def _utc(month: int, day: int = 1) -> datetime:
    return datetime(2024, month, day, tzinfo=UTC)


def _component(
    component_id: str,
    *,
    start_month: int,
    end_month: int,
    training_rows: int = 1,
) -> CorpusComponent:
    return CorpusComponent(
        component_id=component_id,
        scope=TimeScope(_utc(start_month), _utc(end_month)),
        manifest_path=Path(f"/not-opened/{component_id}/manifest.json"),
        manifest_sha256="a" * 64,
        build_fingerprint="b" * 64,
        training_path=Path(f"/not-opened/{component_id}/training.parquet"),
        training_sha256="c" * 64,
        training_rows=training_rows,
        excluded_rows=0,
    )


def _config(*, first_rows: int = 1) -> WorkingCorpusConfig:
    components = (
        _component(
            "2024-01",
            start_month=1,
            end_month=2,
            training_rows=first_rows,
        ),
        _component("2024-02", start_month=2, end_month=3),
        _component("2024-03", start_month=3, end_month=4),
    )
    expected = AggregateExpectations(
        scope=TimeScope(_utc(1), _utc(4)),
        training_rows=first_rows + 2,
        excluded_rows=0,
        source_match_groups=3,
        radiant_win_true=2,
        radiant_win_false=1,
        minimum_match_start_utc=_utc(1, 10),
        maximum_match_start_utc=_utc(3, 10),
        null_counts=(),
        year_row_counts=((2024, first_rows + 2),),
        unique_sample_ids=first_rows + 2,
        unique_game_keys=first_rows + 2,
        duplicate_match_source_game_pairs=0,
        duplicate_match_game_index_pairs=0,
        cross_component_match_groups=0,
        multi_patch_match_groups=0,
        side_assignment_change_match_groups=0,
    )
    return WorkingCorpusConfig(
        config_path=Path("/credential-free/working.json"),
        repository_root=Path("/credential-free"),
        corpus_id="prefix-test",
        schema_sha256="d" * 64,
        components=components,
        expected=expected,
    )


def _frame(component: CorpusComponent) -> pd.DataFrame:
    match_id = f"match-{component.component_id}"
    game_key = f"{match_id}:game:1"
    row: dict[str, object] = {
        column: f"{column}-{component.component_id}"
        for column in TRAINING_COLUMNS
    }
    row.update(
        {
            "sample_id": game_key,
            "game_key": game_key,
            "source_game_id": "1",
            "game_index": 1,
            "source_match_id": match_id,
            "match_start_utc": pd.Timestamp(component.scope.start_utc)
            + pd.Timedelta(days=10),
            "patch": "7.35",
            "liquipedia_tier": "1",
            "tournament": "Prefix Loader Test",
            "series": "Group Stage",
            "radiant_team_key": f"radiant-{component.component_id}",
            "dire_team_key": f"dire-{component.component_id}",
            "radiant_win": True,
        }
    )
    frame = pd.DataFrame([row], columns=TRAINING_COLUMNS)
    string_columns = [
        column
        for column in TRAINING_COLUMNS
        if column not in {"game_index", "match_start_utc", "radiant_win"}
    ]
    frame[string_columns] = frame[string_columns].astype("string")
    frame["game_index"] = frame["game_index"].astype("Int64")
    frame["match_start_utc"] = pd.to_datetime(
        frame["match_start_utc"],
        utc=True,
    ).astype("datetime64[us, UTC]")
    frame["radiant_win"] = frame["radiant_win"].astype("boolean")
    frame["__component_id"] = component.component_id
    return frame


def test_prefix_touches_only_components_through_the_exact_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config()
    verified: list[str] = []
    read: list[str] = []

    def verify(
        received_config: WorkingCorpusConfig,
        component: CorpusComponent,
    ) -> None:
        assert received_config is config
        assert component.component_id != "2024-03"
        verified.append(component.component_id)

    def read_frame(component: CorpusComponent) -> pd.DataFrame:
        assert component.component_id != "2024-03"
        read.append(component.component_id)
        return _frame(component)

    monkeypatch.setattr(loader, "_verify_component", verify)
    monkeypatch.setattr(loader, "_read_frame", read_frame)

    loaded = load_working_corpus_prefix(config, end_utc=_utc(3))

    assert verified == ["2024-01", "2024-02"]
    assert read == ["2024-01", "2024-02"]
    assert loaded.verified_component_ids == ("2024-01", "2024-02")
    assert loaded.scope == TimeScope(_utc(1), _utc(3))
    assert loaded.expected_training_rows == 2
    assert tuple(loaded.frame.columns) == TRAINING_COLUMNS
    assert loaded.frame["match_start_utc"].is_monotonic_increasing


def test_non_boundary_cutoff_rejects_before_artifacts_are_touched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config()

    def unexpected(*args: object, **kwargs: object) -> None:
        pytest.fail("No component artifact should be touched.")

    monkeypatch.setattr(loader, "_verify_component", unexpected)
    monkeypatch.setattr(loader, "_read_frame", unexpected)

    with pytest.raises(CorpusValidationError, match="exact component boundary"):
        load_working_corpus_prefix(config, end_utc=_utc(2, 15))


def test_naive_cutoff_is_rejected() -> None:
    with pytest.raises(CorpusValidationError, match="timezone-aware"):
        load_working_corpus_prefix(
            _config(),
            end_utc=datetime(2024, 3, 1),
        )


def test_prefix_row_count_must_reconcile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(first_rows=2)
    monkeypatch.setattr(loader, "_verify_component", lambda *args: None)
    monkeypatch.setattr(loader, "_read_frame", _frame)

    with pytest.raises(CorpusValidationError, match="row count"):
        load_working_corpus_prefix(config, end_utc=_utc(3))


def test_prefix_duplicate_identity_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config()
    first = _frame(config.components[0])

    def duplicate_frame(component: CorpusComponent) -> pd.DataFrame:
        frame = _frame(component)
        if component.component_id == "2024-02":
            for column in (
                "sample_id",
                "game_key",
                "source_game_id",
                "source_match_id",
            ):
                frame[column] = first.iloc[0][column]
            frame["game_index"] = first.iloc[0]["game_index"]
        return frame

    monkeypatch.setattr(loader, "_verify_component", lambda *args: None)
    monkeypatch.setattr(loader, "_read_frame", duplicate_frame)

    with pytest.raises(CorpusValidationError, match="duplicate identities"):
        load_working_corpus_prefix(config, end_utc=_utc(3))
