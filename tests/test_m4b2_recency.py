"""Offline tests for deterministic M4B.2 recency policies."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.draft_ai_modeling.recency import (
    EXPONENTIAL_HALF_LIFE_DAYS,
    RecencyPolicy,
    RecencyPolicyError,
    recency_policy_fingerprint,
    select_training_rows,
)


CUTOFF = pd.Timestamp("2025-07-01T00:00:00Z")


def training_frame(
    timestamps: list[pd.Timestamp | str],
    *,
    roles: list[str] | None = None,
    indices: list[str] | None = None,
) -> pd.DataFrame:
    role_values = roles or ["train"] * len(timestamps)
    index_values = indices or [
        f"row-{position}" for position in range(len(timestamps))
    ]
    return pd.DataFrame(
        {
            "sample_id": index_values,
            "match_start_utc": timestamps,
            "split_role": role_values,
        },
        index=index_values,
    )


def test_full_uniform_selects_every_strictly_past_training_row() -> None:
    frame = training_frame(
        [
            "2022-01-01T00:00:00Z",
            "2025-06-30T23:59:59Z",
            "2025-07-01T00:00:00Z",
            "2025-11-01T00:00:00Z",
            "2026-02-01T00:00:00Z",
        ],
        roles=[
            "train",
            "train",
            "tuning",
            "calibration",
            "locked_test",
        ],
        indices=["old", "latest", "cutoff", "calibration", "locked"],
    )
    original = frame.copy(deep=True)

    result = select_training_rows(
        frame,
        policy=RecencyPolicy.FULL_UNIFORM,
        train_cutoff_utc=CUTOFF,
    )

    assert result.source_indices == ("old", "latest")
    assert result.frame.index.tolist() == ["old", "latest"]
    assert result.frame["match_start_utc"].lt(CUTOFF).all()
    np.testing.assert_array_equal(result.sample_weights, [1.0, 1.0])
    assert result.audit.rows == 2
    assert result.audit.weight_mean == pytest.approx(1.0)
    assert result.audit.weight_sum == pytest.approx(2.0)
    assert result.audit.effective_sample_size == pytest.approx(2.0)
    assert result.audit.window_start_utc_inclusive is None
    assert result.audit.start_utc == pd.Timestamp(
        "2022-01-01T00:00:00Z"
    ).to_pydatetime()
    assert result.audit.end_utc == pd.Timestamp(
        "2025-06-30T23:59:59Z"
    ).to_pydatetime()
    pd.testing.assert_frame_equal(frame, original)


def test_full_exp180_uses_exact_cutoff_and_mean_one_weights() -> None:
    ages = np.asarray([360.0, 180.0, 1.0])
    timestamps = [
        CUTOFF - pd.Timedelta(days=float(age))
        for age in ages
    ]
    frame = training_frame(timestamps)

    result = select_training_rows(
        frame,
        policy="full_exp180",
        train_cutoff_utc=CUTOFF,
    )

    raw = np.exp2(-ages / EXPONENTIAL_HALF_LIFE_DAYS)
    expected = raw / raw.mean()
    np.testing.assert_allclose(result.sample_weights, expected)
    assert np.isfinite(result.sample_weights).all()
    assert (result.sample_weights > 0).all()
    assert result.sample_weights.mean() == pytest.approx(1.0)
    assert result.sample_weights.sum() == pytest.approx(3.0)
    assert result.sample_weights[0] < result.sample_weights[1]
    assert result.sample_weights[1] < result.sample_weights[2]
    assert result.audit.raw_weight_min == pytest.approx(raw.min())
    assert result.audit.raw_weight_max == pytest.approx(raw.max())
    assert result.audit.effective_sample_size < 3.0
    with pytest.raises(ValueError):
        result.sample_weights[0] = 0


def test_trailing365_uses_exact_half_open_day_boundaries() -> None:
    window_start = CUTOFF - pd.Timedelta(days=365)
    one_nanosecond = pd.Timedelta(nanoseconds=1)
    frame = training_frame(
        [
            window_start - one_nanosecond,
            window_start,
            CUTOFF - one_nanosecond,
            CUTOFF,
            CUTOFF + pd.Timedelta(days=1),
        ],
        roles=["train", "train", "train", "tuning", "calibration"],
        indices=["before", "start", "end", "cutoff", "future"],
    )

    result = select_training_rows(
        frame,
        policy="trailing365_uniform",
        train_cutoff_utc=CUTOFF,
    )

    assert result.source_indices == ("start", "end")
    np.testing.assert_array_equal(result.sample_weights, [1.0, 1.0])
    assert result.audit.window_start_utc_inclusive == (
        window_start.to_pydatetime()
    )
    assert result.audit.cutoff_utc_exclusive == CUTOFF.to_pydatetime()
    assert result.frame["match_start_utc"].ge(window_start).all()
    assert result.frame["match_start_utc"].lt(CUTOFF).all()


@pytest.mark.parametrize(
    ("roles", "message"),
    [
        (["calibration"], "reserved roles"),
        (["locked_test"], "reserved roles"),
        (["tuning"], "non-training roles"),
    ],
)
def test_effective_rows_reject_non_training_roles(
    roles: list[str],
    message: str,
) -> None:
    frame = training_frame(
        ["2025-06-01T00:00:00Z"],
        roles=roles,
    )

    with pytest.raises(RecencyPolicyError, match=message):
        select_training_rows(
            frame,
            policy="full_uniform",
            train_cutoff_utc=CUTOFF,
        )


def test_invalid_or_empty_training_selections_fail_closed() -> None:
    with pytest.raises(RecencyPolicyError, match="no effective"):
        select_training_rows(
            training_frame(["2025-07-01T00:00:00Z"]),
            policy="full_uniform",
            train_cutoff_utc=CUTOFF,
        )

    with pytest.raises(RecencyPolicyError, match="timezone-aware"):
        select_training_rows(
            training_frame(["2025-06-01T00:00:00"]),
            policy="full_uniform",
            train_cutoff_utc=CUTOFF,
        )

    with pytest.raises(RecencyPolicyError, match="timezone-aware"):
        select_training_rows(
            training_frame(["2025-06-01T00:00:00Z"]),
            policy="full_uniform",
            train_cutoff_utc="2025-07-01T00:00:00",
        )

    duplicate_index = training_frame(
        ["2025-05-01T00:00:00Z", "2025-06-01T00:00:00Z"],
    )
    duplicate_index.index = ["duplicate", "duplicate"]
    with pytest.raises(RecencyPolicyError, match="indices must be unique"):
        select_training_rows(
            duplicate_index,
            policy="full_uniform",
            train_cutoff_utc=CUTOFF,
        )


def test_policy_fingerprints_are_deterministic_and_cutoff_specific() -> None:
    first = recency_policy_fingerprint(
        RecencyPolicy.FULL_EXP180,
        train_cutoff_utc=CUTOFF,
    )
    repeated = recency_policy_fingerprint(
        "full_exp180",
        train_cutoff_utc="2025-07-01T08:00:00+08:00",
    )
    other_policy = recency_policy_fingerprint(
        "full_uniform",
        train_cutoff_utc=CUTOFF,
    )
    other_cutoff = recency_policy_fingerprint(
        "full_exp180",
        train_cutoff_utc=CUTOFF + pd.Timedelta(days=1),
    )

    assert first == repeated
    assert len(first) == 64
    assert first != other_policy
    assert first != other_cutoff
