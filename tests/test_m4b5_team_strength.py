"""Focused tests for leakage-safe pre-series Elo features."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from src.draft_ai_modeling.team_strength import (
    ELO_LOGIT_MULTIPLIER,
    TeamStrengthError,
    TeamStrengthPolicy,
    build_training_team_strength,
    transform_frozen_team_strength,
)


def game(
    *,
    sample_id: str,
    series_id: str,
    timestamp: str,
    radiant: str,
    dire: str,
    radiant_win: bool,
) -> dict[str, object]:
    return {
        "sample_id": sample_id,
        "source_match_id": series_id,
        "match_start_utc": timestamp,
        "radiant_team_key": radiant,
        "dire_team_key": dire,
        "radiant_win": radiant_win,
    }


def single_training_series() -> pd.DataFrame:
    return pd.DataFrame(
        [
            game(
                sample_id="train-1",
                series_id="series-1",
                timestamp="2025-09-01T00:00:00Z",
                radiant="alpha",
                dire="beta",
                radiant_win=True,
            )
        ]
    )


def test_input_row_order_cannot_change_features_state_or_audit() -> None:
    frame = pd.DataFrame(
        [
            game(
                sample_id="later",
                series_id="series-2",
                timestamp="2025-09-02T00:00:00Z",
                radiant="beta",
                dire="gamma",
                radiant_win=True,
            ),
            game(
                sample_id="earlier",
                series_id="series-1",
                timestamp="2025-09-01T00:00:00Z",
                radiant="alpha",
                dire="beta",
                radiant_win=True,
            ),
        ],
        index=[12, 4],
    )
    first = build_training_team_strength(frame)
    second = build_training_team_strength(frame.iloc[::-1])

    pd.testing.assert_frame_equal(
        first.features.sort_values("sample_id").reset_index(drop=True),
        second.features.sort_values("sample_id").reset_index(drop=True),
    )
    assert first.state == second.state
    assert first.state.fingerprint == second.state.fingerprint
    assert first.audit.fingerprint == second.audit.fingerprint


def test_frozen_feature_changes_sign_when_sides_swap() -> None:
    trained = build_training_team_strength(single_training_series())
    evaluation = pd.DataFrame(
        [
            game(
                sample_id="same-side",
                series_id="future-1",
                timestamp="2025-10-01T00:00:00Z",
                radiant="alpha",
                dire="beta",
                radiant_win=False,
            ),
            game(
                sample_id="swapped-side",
                series_id="future-2",
                timestamp="2025-10-02T00:00:00Z",
                radiant="beta",
                dire="alpha",
                radiant_win=False,
            ),
        ]
    ).drop(columns=["radiant_win"])

    result = transform_frozen_team_strength(evaluation, trained.state)
    same = result.features.set_index("sample_id").loc["same-side"]
    swapped = result.features.set_index("sample_id").loc["swapped-side"]

    assert same["radiant_rating"] == swapped["dire_rating"]
    assert same["dire_rating"] == swapped["radiant_rating"]
    assert same["elo_logit"] == pytest.approx(-swapped["elo_logit"])
    assert same["elo_logit"] > 0


def test_every_game_in_bo3_uses_the_same_pre_series_ratings() -> None:
    frame = pd.DataFrame(
        [
            game(
                sample_id="g1",
                series_id="bo3",
                timestamp="2025-09-01T00:00:00Z",
                radiant="alpha",
                dire="beta",
                radiant_win=True,
            ),
            game(
                sample_id="g2",
                series_id="bo3",
                timestamp="2025-09-01T00:00:00Z",
                radiant="beta",
                dire="alpha",
                radiant_win=False,
            ),
            game(
                sample_id="g3",
                series_id="bo3",
                timestamp="2025-09-01T00:00:00Z",
                radiant="alpha",
                dire="beta",
                radiant_win=False,
            ),
        ]
    )

    result = build_training_team_strength(frame)

    assert result.features["radiant_rating"].tolist() == [1500.0] * 3
    assert result.features["dire_rating"].tolist() == [1500.0] * 3
    assert result.features["elo_logit"].tolist() == [0.0] * 3


def test_same_timestamp_series_are_batched_before_updates() -> None:
    frame = pd.DataFrame(
        [
            game(
                sample_id="alpha-beats-beta",
                series_id="series-a",
                timestamp="2025-09-01T00:00:00Z",
                radiant="alpha",
                dire="beta",
                radiant_win=True,
            ),
            game(
                sample_id="alpha-loses-gamma",
                series_id="series-b",
                timestamp="2025-09-01T00:00:00Z",
                radiant="alpha",
                dire="gamma",
                radiant_win=False,
            ),
        ]
    )

    result = build_training_team_strength(frame)
    ratings = result.state.ratings_dict()

    assert result.features["elo_logit"].tolist() == [0.0, 0.0]
    assert ratings == {
        "alpha": 1500.0,
        "beta": 1484.0,
        "gamma": 1516.0,
    }
    assert result.audit.timestamp_batches == 1
    assert result.audit.rating_updates == 2


def test_bo3_uses_mean_score_and_exactly_one_k_update() -> None:
    frame = pd.DataFrame(
        [
            game(
                sample_id="g1",
                series_id="bo3",
                timestamp="2025-09-01T00:00:00Z",
                radiant="alpha",
                dire="beta",
                radiant_win=True,
            ),
            game(
                sample_id="g2",
                series_id="bo3",
                timestamp="2025-09-01T00:00:00Z",
                radiant="beta",
                dire="alpha",
                radiant_win=False,
            ),
            game(
                sample_id="g3",
                series_id="bo3",
                timestamp="2025-09-01T00:00:00Z",
                radiant="alpha",
                dire="beta",
                radiant_win=False,
            ),
        ]
    )

    result = build_training_team_strength(frame)
    ratings = result.state.ratings_dict()
    expected_delta = 32.0 * ((2.0 / 3.0) - 0.5)

    assert ratings["alpha"] == pytest.approx(1500.0 + expected_delta)
    assert ratings["beta"] == pytest.approx(1500.0 - expected_delta)
    assert result.audit.rating_updates == 1
    assert result.state.completed_series == 1


def test_unseen_evaluation_teams_use_initial_rating_without_state_change() -> None:
    trained = build_training_team_strength(single_training_series())
    state_fingerprint = trained.state.fingerprint
    evaluation = pd.DataFrame(
        [
            game(
                sample_id="known-new",
                series_id="future-1",
                timestamp="2025-10-01T00:00:00Z",
                radiant="alpha",
                dire="newcomer",
                radiant_win=True,
            ),
            game(
                sample_id="new-new",
                series_id="future-2",
                timestamp="2025-10-02T00:00:00Z",
                radiant="stranger",
                dire="newcomer",
                radiant_win=False,
            ),
        ]
    ).drop(columns=["radiant_win"])

    result = transform_frozen_team_strength(evaluation, trained.state)
    features = result.features.set_index("sample_id")

    assert features.loc["known-new", "radiant_rating"] == 1516.0
    assert features.loc["known-new", "dire_rating"] == 1500.0
    assert features.loc["known-new", "elo_logit"] == pytest.approx(
        16.0 * ELO_LOGIT_MULTIPLIER
    )
    assert features.loc["new-new", "elo_logit"] == 0.0
    assert result.audit.defaulted_team_keys == ("newcomer", "stranger")
    assert result.audit.rating_updates == 0
    assert result.state.fingerprint == state_fingerprint
    assert "newcomer" not in result.state.ratings_dict()


def test_frozen_evaluation_neither_requires_nor_interprets_target() -> None:
    trained = build_training_team_strength(single_training_series())
    target_free = pd.DataFrame(
        [
            game(
                sample_id="future",
                series_id="future-series",
                timestamp="2025-10-01T00:00:00Z",
                radiant="alpha",
                dire="beta",
                radiant_win=True,
            )
        ]
    ).drop(columns=["radiant_win"])
    with_irrelevant_target = target_free.assign(
        radiant_win=object(),
    )

    target_free_result = transform_frozen_team_strength(
        target_free,
        trained.state,
    )
    irrelevant_result = transform_frozen_team_strength(
        with_irrelevant_target,
        trained.state,
    )

    pd.testing.assert_frame_equal(
        target_free_result.features,
        irrelevant_result.features,
    )
    assert target_free_result.audit.mode == "frozen_evaluation"
    assert target_free_result.audit.state_before_fingerprint == (
        target_free_result.audit.state_after_fingerprint
    )


def test_policy_contract_and_fingerprints_are_deterministic() -> None:
    first = build_training_team_strength(single_training_series())
    second = build_training_team_strength(single_training_series())
    policy = TeamStrengthPolicy()

    assert policy.initial_rating == 1500.0
    assert policy.rating_scale == 400.0
    assert policy.k_factor == 32.0
    assert policy.to_payload()["home_or_side_advantage"] is None
    assert policy.to_payload()["rating_decay"] is None
    assert len(policy.fingerprint) == 64
    assert first.state.fingerprint == second.state.fingerprint
    assert first.audit.fingerprint == second.audit.fingerprint
    assert first.audit.policy_fingerprint == policy.fingerprint


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda frame: frame.drop(columns=["radiant_team_key"]),
            "missing required columns",
        ),
        (
            lambda frame: frame.assign(
                match_start_utc="2025-09-01T00:00:00"
            ),
            "timezone-aware",
        ),
        (
            lambda frame: frame.assign(dire_team_key="alpha"),
            "must differ",
        ),
        (
            lambda frame: pd.concat(
                [
                    frame,
                    frame.assign(
                        sample_id="train-2",
                        radiant_team_key="gamma",
                    ),
                ],
                ignore_index=True,
            ),
            "stable team pair",
        ),
        (
            lambda frame: frame.assign(radiant_win=1),
            "only booleans",
        ),
    ],
)
def test_invalid_training_inputs_fail_closed(mutator, message: str) -> None:
    with pytest.raises(TeamStrengthError, match=message):
        build_training_team_strength(mutator(single_training_series()))


def test_frozen_evaluation_rejects_non_future_rows() -> None:
    trained = build_training_team_strength(single_training_series())
    same_time = single_training_series().drop(columns=["radiant_win"])

    with pytest.raises(TeamStrengthError, match="strictly later"):
        transform_frozen_team_strength(same_time, trained.state)


def test_fixed_policy_cannot_be_silently_retuned() -> None:
    with pytest.raises(TeamStrengthError, match="fixed"):
        TeamStrengthPolicy(k_factor=16.0)

    assert math.isclose(
        ELO_LOGIT_MULTIPLIER,
        math.log(10.0) / 400.0,
    )
