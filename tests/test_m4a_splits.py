"""Offline tests for the Milestone 4A modeling and temporal split contracts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from src.draft_ai_modeling.contracts import (
    BASELINE_CONTRACT_VERSION,
    CORPUS_CONTRACT_VERSION,
    CURRENT_BASELINE_FRAMEWORK,
    CURRENT_FEATURE_CONTRACT,
    CURRENT_TEMPORAL_SPLIT,
    CURRENT_WORKING_CORPUS,
    FEATURE_CONTRACT_VERSION,
    PRIMARY_SPLIT_TEST,
    PRIMARY_SPLIT_TRAIN,
    PRIMARY_SPLIT_VALIDATION,
    SPLIT_CONTRACT_VERSION,
    SPLIT_ROLE_CALIBRATION,
    SPLIT_ROLE_LOCKED_TEST,
    SPLIT_ROLE_TRAIN,
    SPLIT_ROLE_TUNING,
    ModelingContractError,
    SplitIntervalContract,
    TemporalSplitContract,
)
from src.draft_ai_modeling.splits import (
    SplitContractError,
    build_split_manifest,
    render_split_report_markdown,
)


def utc(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=UTC)


def synthetic_contract(
    *,
    expected_rows_per_role: int | None = 1,
) -> TemporalSplitContract:
    boundaries = (
        utc(2025, 1, 1),
        utc(2025, 4, 1),
        utc(2025, 7, 1),
        utc(2025, 10, 1),
        utc(2026, 1, 1),
    )
    definitions = (
        ("train", PRIMARY_SPLIT_TRAIN, SPLIT_ROLE_TRAIN),
        (
            "validation_tuning",
            PRIMARY_SPLIT_VALIDATION,
            SPLIT_ROLE_TUNING,
        ),
        (
            "validation_calibration",
            PRIMARY_SPLIT_VALIDATION,
            SPLIT_ROLE_CALIBRATION,
        ),
        ("locked_test", PRIMARY_SPLIT_TEST, SPLIT_ROLE_LOCKED_TEST),
    )
    intervals = tuple(
        SplitIntervalContract(
            interval_id=interval_id,
            primary_split=primary,
            role=role,
            start_utc=boundaries[index],
            end_utc=boundaries[index + 1],
            expected_rows=expected_rows_per_role,
            expected_source_matches=expected_rows_per_role,
            expected_radiant_wins=(
                1 if expected_rows_per_role is not None else None
            ),
            expected_radiant_losses=(
                expected_rows_per_role - 1
                if expected_rows_per_role is not None
                else None
            ),
        )
        for index, (interval_id, primary, role) in enumerate(definitions)
    )
    return TemporalSplitContract(
        contract_version="synthetic-split-v1",
        corpus_id="synthetic-corpus",
        intervals=intervals,
    )


def frame_at_boundaries() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "sample_id": "train-1",
                "source_match_id": "match-train",
                "match_start_utc": "2025-01-01T00:00:00Z",
                "radiant_win": True,
            },
            {
                "sample_id": "tuning-1",
                "source_match_id": "match-tuning",
                "match_start_utc": "2025-04-01T00:00:00+00:00",
                "radiant_win": True,
            },
            {
                "sample_id": "calibration-1",
                "source_match_id": "match-calibration",
                "match_start_utc": pd.Timestamp(
                    "2025-07-01T00:00:00",
                    tz="UTC",
                ),
                "radiant_win": True,
            },
            {
                "sample_id": "test-1",
                "source_match_id": "match-test",
                "match_start_utc": datetime(2025, 10, 1, tzinfo=UTC),
                "radiant_win": True,
            },
        ]
    )


def test_current_contract_pins_the_approved_working_corpus() -> None:
    assert CURRENT_WORKING_CORPUS.contract_version == CORPUS_CONTRACT_VERSION
    assert CURRENT_TEMPORAL_SPLIT.contract_version == SPLIT_CONTRACT_VERSION
    assert CURRENT_FEATURE_CONTRACT.contract_version == FEATURE_CONTRACT_VERSION
    assert (
        CURRENT_BASELINE_FRAMEWORK.contract_version
        == BASELINE_CONTRACT_VERSION
    )
    assert CURRENT_WORKING_CORPUS.start_utc == utc(2022, 1, 1)
    assert CURRENT_WORKING_CORPUS.end_utc == utc(2026, 4, 1)
    assert CURRENT_WORKING_CORPUS.expected_rows == 23_123
    assert CURRENT_WORKING_CORPUS.expected_source_matches == 11_664
    assert CURRENT_WORKING_CORPUS.expected_radiant_wins == 11_762
    assert CURRENT_WORKING_CORPUS.expected_radiant_losses == 11_361
    assert sum(
        component.expected_rows
        for component in CURRENT_WORKING_CORPUS.components
    ) == 23_123


def test_current_temporal_split_reconciles_corpus_totals() -> None:
    intervals = CURRENT_TEMPORAL_SPLIT.intervals
    assert [interval.role for interval in intervals] == [
        SPLIT_ROLE_TRAIN,
        SPLIT_ROLE_TUNING,
        SPLIT_ROLE_CALIBRATION,
        SPLIT_ROLE_LOCKED_TEST,
    ]
    assert sum(interval.expected_rows or 0 for interval in intervals) == 23_123
    assert sum(
        interval.expected_source_matches or 0 for interval in intervals
    ) == 11_664
    assert sum(
        interval.expected_radiant_wins or 0 for interval in intervals
    ) == 11_762
    assert intervals[-1].start_utc == utc(2026, 1, 1)
    assert intervals[-1].end_utc == utc(2026, 4, 1)


def test_half_open_boundaries_and_validation_roles_are_exact() -> None:
    result = build_split_manifest(
        frame_at_boundaries(),
        synthetic_contract(),
    )

    observed = result.manifest.set_index("sample_id")
    assert observed.loc["train-1", "primary_split"] == "train"
    assert observed.loc["train-1", "split_role"] == "train"
    assert observed.loc["tuning-1", "primary_split"] == "validation"
    assert observed.loc["tuning-1", "split_role"] == "tuning"
    assert observed.loc["calibration-1", "split_role"] == "calibration"
    assert observed.loc["test-1", "primary_split"] == "test"
    assert observed.loc["test-1", "split_role"] == "locked_test"
    assert len(result.fingerprint) == 64


def test_row_at_exclusive_corpus_end_is_rejected() -> None:
    frame = frame_at_boundaries()
    frame.loc[3, "match_start_utc"] = "2026-01-01T00:00:00Z"

    with pytest.raises(SplitContractError, match="outside"):
        build_split_manifest(
            frame,
            synthetic_contract(),
            verify_expected=False,
        )


def test_source_match_cannot_cross_tuning_and_calibration_roles() -> None:
    frame = frame_at_boundaries()
    frame.loc[2, "source_match_id"] = "match-tuning"

    with pytest.raises(SplitContractError, match="cross temporal split roles"):
        build_split_manifest(
            frame,
            synthetic_contract(),
            verify_expected=False,
        )


def test_split_fingerprint_is_independent_of_input_order_and_extra_columns() -> None:
    frame = frame_at_boundaries()
    first = build_split_manifest(frame, synthetic_contract())
    reordered = frame.sample(frac=1, random_state=17).reset_index(drop=True)
    reordered["irrelevant_debug_column"] = ["a", "b", "c", "d"]
    second = build_split_manifest(reordered, synthetic_contract())

    assert first.fingerprint == second.fingerprint
    pd.testing.assert_frame_equal(first.manifest, second.manifest)


def test_duplicate_sample_id_fails_closed() -> None:
    frame = frame_at_boundaries()
    frame.loc[1, "sample_id"] = "train-1"

    with pytest.raises(SplitContractError, match="Duplicate sample_id"):
        build_split_manifest(
            frame,
            synthetic_contract(),
            verify_expected=False,
        )


@pytest.mark.parametrize("invalid_time", [None, "not-a-timestamp"])
def test_missing_or_invalid_event_time_fails_closed(
    invalid_time: object,
) -> None:
    frame = frame_at_boundaries()
    frame.loc[0, "match_start_utc"] = invalid_time

    with pytest.raises(SplitContractError, match="valid non-missing"):
        build_split_manifest(
            frame,
            synthetic_contract(),
            verify_expected=False,
        )


def test_feature_contract_rejects_leakage_and_unknown_source_columns() -> None:
    picks = CURRENT_FEATURE_CONTRACT.radiant_pick_columns
    assert CURRENT_FEATURE_CONTRACT.validate_source_feature_columns(picks) == picks

    for forbidden in (
        "radiant_win",
        "source_match_id",
        "sample_id",
        "match_start_utc",
        "duration_seconds",
        "first_pick",
    ):
        with pytest.raises(ModelingContractError, match="Leakage-prohibited"):
            CURRENT_FEATURE_CONTRACT.validate_source_feature_columns(
                [picks[0], forbidden]
            )

    with pytest.raises(ModelingContractError, match="Unsupported"):
        CURRENT_FEATURE_CONTRACT.validate_source_feature_columns(
            [picks[0], "invented_global_order"]
        )


def test_context_columns_require_an_explicit_ablation() -> None:
    with pytest.raises(ModelingContractError, match="Unsupported"):
        CURRENT_FEATURE_CONTRACT.validate_source_feature_columns(["patch"])

    assert CURRENT_FEATURE_CONTRACT.validate_source_feature_columns(
        ["patch"],
        allow_context=True,
    ) == ("patch",)


def test_expected_count_mismatch_fails_the_split_gate() -> None:
    contract = synthetic_contract(expected_rows_per_role=2)

    with pytest.raises(SplitContractError, match="reconciliation failed"):
        build_split_manifest(frame_at_boundaries(), contract)


def test_split_report_is_complete_and_human_renderable() -> None:
    result = build_split_manifest(
        frame_at_boundaries(),
        synthetic_contract(),
    )
    assert result.report["rows"] == 4
    assert result.report["unique_samples"] == 4
    assert result.report["source_matches"] == 4
    assert result.report["group_crossings"] == 0
    assert [row["role"] for row in result.report["by_role"]] == [
        "train",
        "tuning",
        "calibration",
        "locked_test",
    ]

    markdown = render_split_report_markdown(result.report)
    assert markdown.startswith("# Draft AI Temporal Split Report")
    assert result.fingerprint in markdown
    assert "| locked_test |" in markdown


def test_baseline_contract_prepares_framework_without_training() -> None:
    assert [
        baseline.baseline_id
        for baseline in CURRENT_BASELINE_FRAMEWORK.baselines
    ] == ["B0", "B1", "B2", "B3"]
    assert not CURRENT_BASELINE_FRAMEWORK.final_model_training_allowed
    assert CURRENT_BASELINE_FRAMEWORK.primary_metric == "log_loss"
    assert CURRENT_BASELINE_FRAMEWORK.baselines[0].family == "empirical_prior"
    assert CURRENT_BASELINE_FRAMEWORK.baselines[-1].slot_aware


def test_split_contract_rejects_gaps() -> None:
    intervals = list(synthetic_contract().intervals)
    second = intervals[1]
    intervals[1] = SplitIntervalContract(
        interval_id=second.interval_id,
        primary_split=second.primary_split,
        role=second.role,
        start_utc=second.start_utc + timedelta(days=1),
        end_utc=second.end_utc,
    )

    with pytest.raises(ModelingContractError, match="contiguous"):
        TemporalSplitContract(
            contract_version="invalid",
            corpus_id="invalid",
            intervals=tuple(intervals),
        )
