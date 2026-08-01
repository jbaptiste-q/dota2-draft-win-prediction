"""Leakage-safe pre-series team-strength features for the Draft AI.

The policy is deliberately narrow.  Ratings are learned from completed
training series in chronological order, all games in a series share the same
pre-series ratings, and series with identical timestamps are updated as one
batch.  Evaluation features are generated from a frozen state and never
require or inspect a target column.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd


TEAM_STRENGTH_CONTRACT_VERSION = "dota-draft-team-strength-v1"
INITIAL_RATING = 1500.0
RATING_SCALE = 400.0
K_FACTOR = 32.0
ELO_LOGIT_MULTIPLIER = math.log(10.0) / RATING_SCALE

SAMPLE_COLUMN = "sample_id"
SERIES_COLUMN = "source_match_id"
TIME_COLUMN = "match_start_utc"
RADIANT_TEAM_COLUMN = "radiant_team_key"
DIRE_TEAM_COLUMN = "dire_team_key"
TARGET_COLUMN = "radiant_win"
FEATURE_COLUMNS = (
    SAMPLE_COLUMN,
    "elo_logit",
    "radiant_rating",
    "dire_rating",
)
CONTEXT_COLUMNS = (
    SAMPLE_COLUMN,
    SERIES_COLUMN,
    TIME_COLUMN,
    RADIANT_TEAM_COLUMN,
    DIRE_TEAM_COLUMN,
)


class TeamStrengthError(ValueError):
    """Raised when team-strength inputs or state violate the fixed contract."""


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _sha256_payload(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _iso_utc(value: pd.Timestamp | None) -> str | None:
    if value is None:
        return None
    return value.tz_convert("UTC").isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class TeamStrengthPolicy:
    """The single pre-registered M4B.5 Elo policy."""

    initial_rating: float = INITIAL_RATING
    rating_scale: float = RATING_SCALE
    k_factor: float = K_FACTOR

    def __post_init__(self) -> None:
        actual = (
            float(self.initial_rating),
            float(self.rating_scale),
            float(self.k_factor),
        )
        expected = (INITIAL_RATING, RATING_SCALE, K_FACTOR)
        if actual != expected:
            raise TeamStrengthError(
                "The team-strength policy is fixed at initial=1500, "
                "scale=400, and K=32."
            )

    def to_payload(self) -> dict[str, object]:
        """Return the complete credential-free policy contract."""

        return {
            "contract_version": TEAM_STRENGTH_CONTRACT_VERSION,
            "algorithm": "elo",
            "initial_rating": self.initial_rating,
            "rating_scale": self.rating_scale,
            "k_factor": self.k_factor,
            "home_or_side_advantage": None,
            "rating_decay": None,
            "series_identity": SERIES_COLUMN,
            "series_team_pair": (
                "lexically_sorted_stable_unordered_pair"
            ),
            "series_timestamp": (
                "all_games_must_share_match_start_utc"
            ),
            "series_score": "mean_team_a_game_outcome",
            "series_update": "one_k_update_per_series",
            "same_timestamp_policy": (
                "calculate_all_deltas_from_pre_batch_ratings_then_apply"
            ),
            "training_feature_point": "pre_series",
            "evaluation_policy": "frozen_no_target_no_updates",
            "expected_score_formula": (
                "1/(1+10**((rating_b-rating_a)/400))"
            ),
            "elo_logit_formula": (
                "ln(10)/400*(radiant_rating-dire_rating)"
            ),
            "feature_columns": list(FEATURE_COLUMNS),
        }

    @property
    def fingerprint(self) -> str:
        """SHA-256 of the exact policy definition."""

        return _sha256_payload(self.to_payload())


@dataclass(frozen=True, slots=True)
class TeamStrengthState:
    """Immutable fitted ratings and their chronological boundary."""

    policy_fingerprint: str
    ratings: tuple[tuple[str, float], ...]
    completed_series: int
    completed_through_utc: pd.Timestamp | None

    def __post_init__(self) -> None:
        if len(self.policy_fingerprint) != 64:
            raise TeamStrengthError("State policy fingerprint is invalid.")
        if self.completed_series < 0:
            raise TeamStrengthError(
                "State completed-series count cannot be negative."
            )
        keys = tuple(team_key for team_key, _ in self.ratings)
        if keys != tuple(sorted(keys)) or len(set(keys)) != len(keys):
            raise TeamStrengthError(
                "State ratings must have unique, lexically sorted team keys."
            )
        for team_key, rating in self.ratings:
            if not isinstance(team_key, str) or not team_key:
                raise TeamStrengthError(
                    "State team keys must be non-empty strings."
                )
            if not math.isfinite(float(rating)):
                raise TeamStrengthError("State ratings must be finite.")
        if self.completed_through_utc is not None:
            timestamp = pd.Timestamp(self.completed_through_utc)
            if pd.isna(timestamp) or timestamp.tzinfo is None:
                raise TeamStrengthError(
                    "State completion timestamp must be timezone-aware."
                )
            object.__setattr__(
                self,
                "completed_through_utc",
                timestamp.tz_convert("UTC"),
            )

    @classmethod
    def from_ratings(
        cls,
        *,
        policy: TeamStrengthPolicy,
        ratings: dict[str, float],
        completed_series: int,
        completed_through_utc: pd.Timestamp | None,
    ) -> "TeamStrengthState":
        """Build canonical immutable state from a mutable rating mapping."""

        return cls(
            policy_fingerprint=policy.fingerprint,
            ratings=tuple(
                (team_key, float(ratings[team_key]))
                for team_key in sorted(ratings)
            ),
            completed_series=completed_series,
            completed_through_utc=completed_through_utc,
        )

    def ratings_dict(self) -> dict[str, float]:
        """Return an independent mutable copy of the fitted ratings."""

        return dict(self.ratings)

    def to_payload(self) -> dict[str, object]:
        """Return a stable, JSON-ready state representation."""

        return {
            "contract_version": TEAM_STRENGTH_CONTRACT_VERSION,
            "policy_fingerprint": self.policy_fingerprint,
            "ratings": [
                {
                    "team_key": team_key,
                    "rating": round(rating, 12),
                }
                for team_key, rating in self.ratings
            ],
            "completed_series": self.completed_series,
            "completed_through_utc": _iso_utc(
                self.completed_through_utc
            ),
        }

    @property
    def fingerprint(self) -> str:
        """SHA-256 of the complete canonical state."""

        return _sha256_payload(self.to_payload())


@dataclass(frozen=True, slots=True)
class TeamStrengthAudit:
    """Deterministic reconciliation evidence for one feature pass."""

    mode: Literal["training", "frozen_evaluation"]
    rows: int
    series: int
    timestamp_batches: int
    rating_updates: int
    observed_team_count: int
    defaulted_team_keys: tuple[str, ...]
    start_utc: pd.Timestamp
    end_utc: pd.Timestamp
    policy_fingerprint: str
    state_before_fingerprint: str
    state_after_fingerprint: str
    output_fingerprint: str

    def to_payload(self) -> dict[str, object]:
        """Return stable audit evidence."""

        return {
            "contract_version": TEAM_STRENGTH_CONTRACT_VERSION,
            "mode": self.mode,
            "rows": self.rows,
            "series": self.series,
            "timestamp_batches": self.timestamp_batches,
            "rating_updates": self.rating_updates,
            "observed_team_count": self.observed_team_count,
            "defaulted_team_keys": list(self.defaulted_team_keys),
            "start_utc": _iso_utc(self.start_utc),
            "end_utc": _iso_utc(self.end_utc),
            "policy_fingerprint": self.policy_fingerprint,
            "state_before_fingerprint": self.state_before_fingerprint,
            "state_after_fingerprint": self.state_after_fingerprint,
            "output_fingerprint": self.output_fingerprint,
        }

    @property
    def fingerprint(self) -> str:
        """SHA-256 of the complete audit."""

        return _sha256_payload(self.to_payload())


@dataclass(frozen=True, slots=True)
class TeamStrengthResult:
    """Aligned feature rows, resulting immutable state, and audit."""

    features: pd.DataFrame
    state: TeamStrengthState
    audit: TeamStrengthAudit


@dataclass(frozen=True, slots=True)
class _SeriesRecord:
    series_id: str
    timestamp: pd.Timestamp
    team_a: str
    team_b: str
    positions: tuple[int, ...]
    radiant_teams: tuple[str, ...]
    team_a_score: float | None


def _normalized_timestamp(value: object) -> pd.Timestamp:
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError) as error:
        raise TeamStrengthError(
            f"{TIME_COLUMN} contains an invalid timestamp."
        ) from error
    if pd.isna(timestamp) or timestamp.tzinfo is None:
        raise TeamStrengthError(
            f"{TIME_COLUMN} must contain timezone-aware timestamps."
        )
    return timestamp.tz_convert("UTC")


def _validate_string_column(
    frame: pd.DataFrame,
    *,
    column: str,
) -> None:
    invalid = frame[column].map(
        lambda value: not isinstance(value, str) or not value
    )
    if invalid.any():
        raise TeamStrengthError(
            f"{column} must contain non-empty strings."
        )


def _normalized_input(
    frame: pd.DataFrame,
    *,
    require_target: bool,
) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("Team-strength input must be a pandas DataFrame.")
    if frame.empty:
        raise TeamStrengthError("Team-strength input cannot be empty.")
    if frame.columns.duplicated().any():
        raise TeamStrengthError(
            "Team-strength input contains duplicate column names."
        )
    required = (*CONTEXT_COLUMNS, *((TARGET_COLUMN,) if require_target else ()))
    missing = sorted(set(required).difference(frame.columns))
    if missing:
        raise TeamStrengthError(
            "Team-strength input is missing required columns: "
            + ", ".join(missing)
        )
    if not frame.index.is_unique:
        raise TeamStrengthError(
            "Team-strength input indices must be unique."
        )

    # Selecting only the declared columns is intentional: frozen evaluation
    # must not read or interpret a target even if an unrelated target-named
    # column happens to be present.
    normalized = frame.loc[:, list(required)].copy()
    normalized["__position"] = np.arange(len(normalized), dtype=np.int64)
    for column in (
        SAMPLE_COLUMN,
        SERIES_COLUMN,
        RADIANT_TEAM_COLUMN,
        DIRE_TEAM_COLUMN,
    ):
        _validate_string_column(normalized, column=column)
    if normalized[SAMPLE_COLUMN].duplicated().any():
        raise TeamStrengthError("sample_id values must be unique.")
    same_team = (
        normalized[RADIANT_TEAM_COLUMN]
        == normalized[DIRE_TEAM_COLUMN]
    )
    if same_team.any():
        raise TeamStrengthError(
            "Radiant and Dire team keys must differ in every row."
        )
    normalized[TIME_COLUMN] = [
        _normalized_timestamp(value)
        for value in normalized[TIME_COLUMN].tolist()
    ]
    if require_target:
        invalid_target = normalized[TARGET_COLUMN].map(
            lambda value: not isinstance(value, (bool, np.bool_))
        )
        if invalid_target.any():
            raise TeamStrengthError(
                f"{TARGET_COLUMN} must contain only booleans."
            )
        normalized[TARGET_COLUMN] = normalized[TARGET_COLUMN].astype(bool)
    return normalized


def _series_records(
    frame: pd.DataFrame,
    *,
    require_target: bool,
) -> tuple[_SeriesRecord, ...]:
    records: list[_SeriesRecord] = []
    for series_id, group in frame.groupby(SERIES_COLUMN, sort=True):
        timestamps = tuple(sorted(set(group[TIME_COLUMN].tolist())))
        if len(timestamps) != 1:
            raise TeamStrengthError(
                f"Series {series_id!r} has multiple timestamps."
            )
        pairs = {
            tuple(
                sorted(
                    (
                        row[RADIANT_TEAM_COLUMN],
                        row[DIRE_TEAM_COLUMN],
                    )
                )
            )
            for _, row in group.iterrows()
        }
        if len(pairs) != 1:
            raise TeamStrengthError(
                f"Series {series_id!r} does not have one stable team pair."
            )
        team_a, team_b = next(iter(pairs))
        positions = tuple(
            int(value) for value in group["__position"].tolist()
        )
        radiant_teams = tuple(
            str(value)
            for value in group[RADIANT_TEAM_COLUMN].tolist()
        )
        team_a_score: float | None = None
        if require_target:
            outcomes: list[float] = []
            for _, row in group.iterrows():
                radiant_won = bool(row[TARGET_COLUMN])
                team_a_is_radiant = (
                    row[RADIANT_TEAM_COLUMN] == team_a
                )
                outcomes.append(
                    float(
                        radiant_won
                        if team_a_is_radiant
                        else not radiant_won
                    )
                )
            team_a_score = float(np.mean(outcomes))
        records.append(
            _SeriesRecord(
                series_id=str(series_id),
                timestamp=pd.Timestamp(timestamps[0]),
                team_a=team_a,
                team_b=team_b,
                positions=positions,
                radiant_teams=radiant_teams,
                team_a_score=team_a_score,
            )
        )
    return tuple(
        sorted(records, key=lambda item: (item.timestamp, item.series_id))
    )


def _initial_state(policy: TeamStrengthPolicy) -> TeamStrengthState:
    return TeamStrengthState.from_ratings(
        policy=policy,
        ratings={},
        completed_series=0,
        completed_through_utc=None,
    )


def _expected_score(
    rating_a: float,
    rating_b: float,
    *,
    policy: TeamStrengthPolicy,
) -> float:
    return 1.0 / (
        1.0
        + 10.0 ** ((rating_b - rating_a) / policy.rating_scale)
    )


def _features_frame(
    normalized: pd.DataFrame,
    *,
    elo_logits: np.ndarray,
    radiant_ratings: np.ndarray,
    dire_ratings: np.ndarray,
) -> pd.DataFrame:
    features = pd.DataFrame(
        {
            SAMPLE_COLUMN: normalized[SAMPLE_COLUMN].to_numpy(copy=True),
            "elo_logit": elo_logits,
            "radiant_rating": radiant_ratings,
            "dire_rating": dire_ratings,
        },
        index=normalized.index.copy(),
    )
    return features.loc[:, list(FEATURE_COLUMNS)]


def _output_fingerprint(features: pd.DataFrame) -> str:
    records = [
        {
            "sample_id": str(row[SAMPLE_COLUMN]),
            "elo_logit": float(row["elo_logit"]).hex(),
            "radiant_rating": float(row["radiant_rating"]).hex(),
            "dire_rating": float(row["dire_rating"]).hex(),
        }
        for _, row in features.sort_values(SAMPLE_COLUMN).iterrows()
    ]
    return _sha256_payload(
        {
            "contract_version": TEAM_STRENGTH_CONTRACT_VERSION,
            "features": records,
        }
    )


def _audit(
    *,
    mode: Literal["training", "frozen_evaluation"],
    normalized: pd.DataFrame,
    records: tuple[_SeriesRecord, ...],
    rating_updates: int,
    defaulted_team_keys: set[str],
    policy: TeamStrengthPolicy,
    state_before: TeamStrengthState,
    state_after: TeamStrengthState,
    features: pd.DataFrame,
) -> TeamStrengthAudit:
    observed_teams = {
        team
        for record in records
        for team in (record.team_a, record.team_b)
    }
    timestamps = normalized[TIME_COLUMN]
    return TeamStrengthAudit(
        mode=mode,
        rows=len(normalized),
        series=len(records),
        timestamp_batches=len({record.timestamp for record in records}),
        rating_updates=rating_updates,
        observed_team_count=len(observed_teams),
        defaulted_team_keys=tuple(sorted(defaulted_team_keys)),
        start_utc=pd.Timestamp(timestamps.min()),
        end_utc=pd.Timestamp(timestamps.max()),
        policy_fingerprint=policy.fingerprint,
        state_before_fingerprint=state_before.fingerprint,
        state_after_fingerprint=state_after.fingerprint,
        output_fingerprint=_output_fingerprint(features),
    )


def build_training_team_strength(
    frame: pd.DataFrame,
    *,
    policy: TeamStrengthPolicy | None = None,
) -> TeamStrengthResult:
    """Build pre-series training features and the final fitted Elo state.

    Each series contributes exactly one update using its mean team-A game
    outcome.  All updates at the same timestamp are calculated from the same
    pre-batch rating state, so input row order cannot affect the result.
    """

    resolved = policy or TeamStrengthPolicy()
    normalized = _normalized_input(frame, require_target=True)
    records = _series_records(normalized, require_target=True)
    state_before = _initial_state(resolved)
    ratings: dict[str, float] = {}
    elo_logits = np.empty(len(normalized), dtype=np.float64)
    radiant_ratings = np.empty(len(normalized), dtype=np.float64)
    dire_ratings = np.empty(len(normalized), dtype=np.float64)
    defaulted_team_keys: set[str] = set()

    batches: defaultdict[pd.Timestamp, list[_SeriesRecord]] = defaultdict(list)
    for record in records:
        batches[record.timestamp].append(record)

    for timestamp in sorted(batches):
        deltas: defaultdict[str, float] = defaultdict(float)
        batch_records = sorted(
            batches[timestamp],
            key=lambda item: item.series_id,
        )
        for record in batch_records:
            if record.team_a not in ratings:
                defaulted_team_keys.add(record.team_a)
            if record.team_b not in ratings:
                defaulted_team_keys.add(record.team_b)
            rating_a = ratings.get(
                record.team_a,
                resolved.initial_rating,
            )
            rating_b = ratings.get(
                record.team_b,
                resolved.initial_rating,
            )
            for position, radiant_team in zip(
                record.positions,
                record.radiant_teams,
                strict=True,
            ):
                if radiant_team == record.team_a:
                    radiant_rating = rating_a
                    dire_rating = rating_b
                else:
                    radiant_rating = rating_b
                    dire_rating = rating_a
                radiant_ratings[position] = radiant_rating
                dire_ratings[position] = dire_rating
                elo_logits[position] = (
                    ELO_LOGIT_MULTIPLIER
                    * (radiant_rating - dire_rating)
                )
            if record.team_a_score is None:
                raise TeamStrengthError(
                    "Training series is missing its target-derived score."
                )
            expected_a = _expected_score(
                rating_a,
                rating_b,
                policy=resolved,
            )
            delta_a = resolved.k_factor * (
                record.team_a_score - expected_a
            )
            deltas[record.team_a] += delta_a
            deltas[record.team_b] -= delta_a

        observed_in_batch = {
            team
            for record in batch_records
            for team in (record.team_a, record.team_b)
        }
        for team_key in observed_in_batch:
            ratings.setdefault(team_key, resolved.initial_rating)
        for team_key in sorted(deltas):
            ratings[team_key] += deltas[team_key]

    state_after = TeamStrengthState.from_ratings(
        policy=resolved,
        ratings=ratings,
        completed_series=len(records),
        completed_through_utc=max(record.timestamp for record in records),
    )
    features = _features_frame(
        normalized,
        elo_logits=elo_logits,
        radiant_ratings=radiant_ratings,
        dire_ratings=dire_ratings,
    )
    return TeamStrengthResult(
        features=features,
        state=state_after,
        audit=_audit(
            mode="training",
            normalized=normalized,
            records=records,
            rating_updates=len(records),
            defaulted_team_keys=defaulted_team_keys,
            policy=resolved,
            state_before=state_before,
            state_after=state_after,
            features=features,
        ),
    )


def transform_frozen_team_strength(
    frame: pd.DataFrame,
    state: TeamStrengthState,
    *,
    policy: TeamStrengthPolicy | None = None,
) -> TeamStrengthResult:
    """Transform later rows with immutable ratings and no target access.

    ``radiant_win`` is neither required nor selected from ``frame``.  The
    fitted state is returned unchanged and no evaluation outcome can update it.
    """

    if not isinstance(state, TeamStrengthState):
        raise TypeError("state must be a TeamStrengthState.")
    resolved = policy or TeamStrengthPolicy()
    if state.policy_fingerprint != resolved.fingerprint:
        raise TeamStrengthError(
            "State and requested team-strength policy fingerprints differ."
        )
    normalized = _normalized_input(frame, require_target=False)
    records = _series_records(normalized, require_target=False)
    if (
        state.completed_through_utc is not None
        and min(record.timestamp for record in records)
        <= state.completed_through_utc
    ):
        raise TeamStrengthError(
            "Frozen evaluation timestamps must be strictly later than the "
            "fitted state boundary."
        )

    ratings = state.ratings_dict()
    elo_logits = np.empty(len(normalized), dtype=np.float64)
    radiant_ratings = np.empty(len(normalized), dtype=np.float64)
    dire_ratings = np.empty(len(normalized), dtype=np.float64)
    defaulted_team_keys: set[str] = set()
    for record in records:
        if record.team_a not in ratings:
            defaulted_team_keys.add(record.team_a)
        if record.team_b not in ratings:
            defaulted_team_keys.add(record.team_b)
        rating_a = ratings.get(record.team_a, resolved.initial_rating)
        rating_b = ratings.get(record.team_b, resolved.initial_rating)
        for position, radiant_team in zip(
            record.positions,
            record.radiant_teams,
            strict=True,
        ):
            if radiant_team == record.team_a:
                radiant_rating = rating_a
                dire_rating = rating_b
            else:
                radiant_rating = rating_b
                dire_rating = rating_a
            radiant_ratings[position] = radiant_rating
            dire_ratings[position] = dire_rating
            elo_logits[position] = (
                ELO_LOGIT_MULTIPLIER
                * (radiant_rating - dire_rating)
            )

    features = _features_frame(
        normalized,
        elo_logits=elo_logits,
        radiant_ratings=radiant_ratings,
        dire_ratings=dire_ratings,
    )
    return TeamStrengthResult(
        features=features,
        state=state,
        audit=_audit(
            mode="frozen_evaluation",
            normalized=normalized,
            records=records,
            rating_updates=0,
            defaulted_team_keys=defaulted_team_keys,
            policy=resolved,
            state_before=state,
            state_after=state,
            features=features,
        ),
    )
