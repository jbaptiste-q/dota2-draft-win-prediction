"""Versioned, leakage-aware contracts for Draft AI modeling.

This module is deliberately declarative.  It pins the working corpus and the
modeling boundaries without importing the acquisition, parsing, or
normalization layers.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from src.draft_training_dataset.schema import (
    CONTEXT_FEATURE_COLUMNS,
    DIRE_BAN_COLUMNS,
    DIRE_PICK_COLUMNS,
    DRAFT_FEATURE_COLUMNS,
    FORBIDDEN_COLUMNS,
    GROUP_IDENTIFIER_COLUMNS,
    IDENTIFIER_COLUMNS,
    RADIANT_BAN_COLUMNS,
    RADIANT_PICK_COLUMNS,
    SCHEMA_VERSION,
    TARGET_COLUMNS,
    TIME_COLUMNS,
)


CORPUS_CONTRACT_VERSION = "dota-draft-working-corpus-v1"
SPLIT_CONTRACT_VERSION = "dota-draft-temporal-split-v1"
FEATURE_CONTRACT_VERSION = "dota-draft-features-v1"
BASELINE_CONTRACT_VERSION = "dota-draft-baselines-v1"

WORKING_CORPUS_ID = "m4a-tier1-tier2-2022q1-2026q1-working-v1"
UNKNOWN_CATEGORY_TOKEN = "__UNKNOWN__"

PRIMARY_SPLIT_TRAIN = "train"
PRIMARY_SPLIT_VALIDATION = "validation"
PRIMARY_SPLIT_TEST = "test"

SPLIT_ROLE_TRAIN = "train"
SPLIT_ROLE_TUNING = "tuning"
SPLIT_ROLE_CALIBRATION = "calibration"
SPLIT_ROLE_LOCKED_TEST = "locked_test"


class ModelingContractError(ValueError):
    """Raised when a declared modeling contract is internally inconsistent."""


def utc_datetime(year: int, month: int, day: int) -> datetime:
    """Construct a midnight UTC contract boundary."""
    return datetime(year, month, day, tzinfo=UTC)


def _normalized_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None:
        raise ModelingContractError(f"{field_name} must be timezone-aware.")
    return value.astimezone(UTC)


def _validate_sha256(value: str, *, field_name: str) -> None:
    invalid_character = any(
        character not in "0123456789abcdef"
        for character in value
    )
    if len(value) != 64 or invalid_character:
        raise ModelingContractError(
            f"{field_name} must be a lowercase 64-character SHA-256 value."
        )


@dataclass(frozen=True, slots=True)
class CorpusComponentContract:
    """One immutable canonical-supervised component of the working corpus."""

    component_id: str
    start_utc: datetime
    end_utc: datetime
    supervised_build_fingerprint: str
    expected_rows: int

    def __post_init__(self) -> None:
        start = _normalized_utc(self.start_utc, field_name="component start")
        end = _normalized_utc(self.end_utc, field_name="component end")
        if start >= end:
            raise ModelingContractError(
                f"Invalid component interval for {self.component_id!r}."
            )
        if not self.component_id.strip():
            raise ModelingContractError("Corpus component ID cannot be empty.")
        _validate_sha256(
            self.supervised_build_fingerprint,
            field_name=f"{self.component_id} supervised build fingerprint",
        )
        if self.expected_rows <= 0:
            raise ModelingContractError(
                f"{self.component_id} expected rows must be positive."
            )
        object.__setattr__(self, "start_utc", start)
        object.__setattr__(self, "end_utc", end)


@dataclass(frozen=True, slots=True)
class WorkingCorpusContract:
    """Exact immutable inputs and reconciled totals for Milestone 4A."""

    contract_version: str
    corpus_id: str
    supervised_schema_version: str
    start_utc: datetime
    end_utc: datetime
    components: tuple[CorpusComponentContract, ...]
    expected_rows: int
    expected_source_matches: int
    expected_radiant_wins: int
    expected_radiant_losses: int
    source_tiers: tuple[str, ...] = ("1", "2")
    status: str = "working_contiguous_prefix"

    def __post_init__(self) -> None:
        start = _normalized_utc(self.start_utc, field_name="corpus start")
        end = _normalized_utc(self.end_utc, field_name="corpus end")
        if start >= end:
            raise ModelingContractError("Working corpus start must precede end.")
        if not self.components:
            raise ModelingContractError("Working corpus requires components.")
        ordered = tuple(sorted(self.components, key=lambda item: item.start_utc))
        if ordered != self.components:
            raise ModelingContractError(
                "Working corpus components must be in chronological order."
            )
        if ordered[0].start_utc != start or ordered[-1].end_utc != end:
            raise ModelingContractError(
                "Working corpus components must cover the declared boundaries."
            )
        for previous, current in zip(ordered, ordered[1:], strict=False):
            if previous.end_utc != current.start_utc:
                raise ModelingContractError(
                    "Working corpus components must form a contiguous prefix."
                )
        component_rows = sum(component.expected_rows for component in ordered)
        if component_rows != self.expected_rows:
            raise ModelingContractError(
                "Working corpus component rows do not reconcile with total rows."
            )
        if (
            self.expected_radiant_wins + self.expected_radiant_losses
            != self.expected_rows
        ):
            raise ModelingContractError(
                "Working corpus target counts do not reconcile with total rows."
            )
        if self.expected_source_matches <= 0:
            raise ModelingContractError(
                "Expected source-match count must be positive."
            )
        object.__setattr__(self, "start_utc", start)
        object.__setattr__(self, "end_utc", end)


@dataclass(frozen=True, slots=True)
class SplitIntervalContract:
    """One half-open temporal role within a primary dataset split."""

    interval_id: str
    primary_split: str
    role: str
    start_utc: datetime
    end_utc: datetime
    expected_rows: int | None = None
    expected_source_matches: int | None = None
    expected_radiant_wins: int | None = None
    expected_radiant_losses: int | None = None

    def __post_init__(self) -> None:
        start = _normalized_utc(self.start_utc, field_name="split start")
        end = _normalized_utc(self.end_utc, field_name="split end")
        if start >= end:
            raise ModelingContractError(
                f"Invalid split interval for {self.interval_id!r}."
            )
        if self.primary_split not in {
            PRIMARY_SPLIT_TRAIN,
            PRIMARY_SPLIT_VALIDATION,
            PRIMARY_SPLIT_TEST,
        }:
            raise ModelingContractError(
                f"Unsupported primary split: {self.primary_split!r}."
            )
        expected_values = (
            self.expected_rows,
            self.expected_source_matches,
            self.expected_radiant_wins,
            self.expected_radiant_losses,
        )
        if any(value is not None and value < 0 for value in expected_values):
            raise ModelingContractError("Expected split counts cannot be negative.")
        if (
            self.expected_rows is not None
            and self.expected_radiant_wins is not None
            and self.expected_radiant_losses is not None
            and self.expected_radiant_wins + self.expected_radiant_losses
            != self.expected_rows
        ):
            raise ModelingContractError(
                f"Target counts do not reconcile for {self.interval_id!r}."
            )
        object.__setattr__(self, "start_utc", start)
        object.__setattr__(self, "end_utc", end)


@dataclass(frozen=True, slots=True)
class TemporalSplitContract:
    """Chronological split policy with a series-group leakage barrier."""

    contract_version: str
    corpus_id: str
    intervals: tuple[SplitIntervalContract, ...]
    sample_id_column: str = "sample_id"
    group_column: str = "source_match_id"
    time_column: str = "match_start_utc"
    target_column: str = "radiant_win"
    timezone: str = "UTC"
    interval_semantics: str = "half_open"

    def __post_init__(self) -> None:
        if not self.intervals:
            raise ModelingContractError("Temporal split requires intervals.")
        ordered = tuple(sorted(self.intervals, key=lambda item: item.start_utc))
        if ordered != self.intervals:
            raise ModelingContractError(
                "Temporal split intervals must be chronological."
            )
        if len({interval.interval_id for interval in ordered}) != len(ordered):
            raise ModelingContractError("Split interval IDs must be unique.")
        if len({interval.role for interval in ordered}) != len(ordered):
            raise ModelingContractError("Split roles must be unique.")
        for previous, current in zip(ordered, ordered[1:], strict=False):
            if previous.end_utc != current.start_utc:
                raise ModelingContractError(
                    "Temporal split intervals must be contiguous."
                )
        if self.timezone != "UTC" or self.interval_semantics != "half_open":
            raise ModelingContractError(
                "The canonical temporal split must use half-open UTC intervals."
            )

    @property
    def start_utc(self) -> datetime:
        return self.intervals[0].start_utc

    @property
    def end_utc(self) -> datetime:
        return self.intervals[-1].end_utc


@dataclass(frozen=True, slots=True)
class FeatureContract:
    """Raw-column roles and transformation policies for M4A features."""

    contract_version: str
    default_profile: str
    unknown_category_token: str
    radiant_pick_columns: tuple[str, ...]
    dire_pick_columns: tuple[str, ...]
    radiant_ban_columns: tuple[str, ...]
    dire_ban_columns: tuple[str, ...]
    context_ablation_columns: tuple[str, ...]
    identifier_columns: tuple[str, ...]
    group_columns: tuple[str, ...]
    time_columns: tuple[str, ...]
    target_columns: tuple[str, ...]
    forbidden_columns: frozenset[str]
    vocabulary_fit_role: str = SPLIT_ROLE_TRAIN
    first_pick_supported: bool = False
    global_draft_order_supported: bool = False

    @property
    def draft_columns(self) -> tuple[str, ...]:
        return (
            *self.radiant_pick_columns,
            *self.dire_pick_columns,
            *self.radiant_ban_columns,
            *self.dire_ban_columns,
        )

    @property
    def leakage_columns(self) -> frozenset[str]:
        return frozenset(
            (
                *self.identifier_columns,
                *self.group_columns,
                *self.time_columns,
                *self.target_columns,
                *self.forbidden_columns,
            )
        )

    def validate_source_feature_columns(
        self,
        columns: Iterable[str],
        *,
        allow_context: bool = False,
    ) -> tuple[str, ...]:
        """Validate an explicit raw feature allowlist and preserve its order."""
        selected = tuple(columns)
        if len(set(selected)) != len(selected):
            raise ModelingContractError("Feature source columns must be unique.")
        leaked = sorted(set(selected).intersection(self.leakage_columns))
        if leaked:
            raise ModelingContractError(
                "Leakage-prohibited source columns requested: "
                + ", ".join(leaked)
            )
        allowed = set(self.draft_columns)
        if allow_context:
            allowed.update(self.context_ablation_columns)
        unsupported = sorted(set(selected).difference(allowed))
        if unsupported:
            raise ModelingContractError(
                "Unsupported source feature columns requested: "
                + ", ".join(unsupported)
            )
        return selected


@dataclass(frozen=True, slots=True)
class BaselineSpec:
    """Declarative baseline identity; it does not construct or fit a model."""

    baseline_id: str
    family: str
    feature_profile: str
    includes_picks: bool
    includes_bans: bool
    slot_aware: bool
    purpose: str


@dataclass(frozen=True, slots=True)
class BaselineFrameworkContract:
    """Ordered baseline families that M4A prepares for later training."""

    contract_version: str
    baselines: tuple[BaselineSpec, ...]
    primary_metric: str = "log_loss"
    probability_output: bool = True
    final_model_training_allowed: bool = False

    def __post_init__(self) -> None:
        identifiers = [baseline.baseline_id for baseline in self.baselines]
        if len(set(identifiers)) != len(identifiers):
            raise ModelingContractError("Baseline IDs must be unique.")


CURRENT_CORPUS_COMPONENTS = (
    CorpusComponentContract(
        component_id="2022-Q1_to_2024-Q1",
        start_utc=utc_datetime(2022, 1, 1),
        end_utc=utc_datetime(2024, 4, 1),
        supervised_build_fingerprint=(
            "c1ea1d31968eb4c9c6fc4cd8dd7812ca2189694ca94ace48b1aae676e146acd9"
        ),
        expected_rows=9_700,
    ),
    CorpusComponentContract(
        component_id="2024-Q2",
        start_utc=utc_datetime(2024, 4, 1),
        end_utc=utc_datetime(2024, 7, 1),
        supervised_build_fingerprint=(
            "c6fe7ef66a8a24a3cc8f7d22deb4b2b558f2cb4cc28ba7b661929d9543bcd7f2"
        ),
        expected_rows=1_712,
    ),
    CorpusComponentContract(
        component_id="2024-Q3",
        start_utc=utc_datetime(2024, 7, 1),
        end_utc=utc_datetime(2024, 10, 1),
        supervised_build_fingerprint=(
            "aa0d2820ee3923bdc23af6071b3f15fd4793fac3ec07f831539a4e8ff0d91f0a"
        ),
        expected_rows=1_837,
    ),
    CorpusComponentContract(
        component_id="2024-Q4",
        start_utc=utc_datetime(2024, 10, 1),
        end_utc=utc_datetime(2025, 1, 1),
        supervised_build_fingerprint=(
            "8860ca6c6bda60d29151ab43194b6ea729e6caaf563abcc0ec85f80e36a71d32"
        ),
        expected_rows=1_351,
    ),
    CorpusComponentContract(
        component_id="2025-Q1",
        start_utc=utc_datetime(2025, 1, 1),
        end_utc=utc_datetime(2025, 4, 1),
        supervised_build_fingerprint=(
            "2ca66e275ca5ff367b35bebd4214de6d63d04e648d40cf0036c9d4455d4d6453"
        ),
        expected_rows=2_209,
    ),
    CorpusComponentContract(
        component_id="2025-Q2",
        start_utc=utc_datetime(2025, 4, 1),
        end_utc=utc_datetime(2025, 7, 1),
        supervised_build_fingerprint=(
            "629ee14fcdf0ed824dffdb6cad6a56b96c9818a32cbccf34a7faa3d086a3b7ab"
        ),
        expected_rows=1_814,
    ),
    CorpusComponentContract(
        component_id="2025-Q3",
        start_utc=utc_datetime(2025, 7, 1),
        end_utc=utc_datetime(2025, 10, 1),
        supervised_build_fingerprint=(
            "d713108e4408046e6c91c669c1cd5d1a1582955e531f8121950027d2fa0887b9"
        ),
        expected_rows=1_464,
    ),
    CorpusComponentContract(
        component_id="2025-Q4",
        start_utc=utc_datetime(2025, 10, 1),
        end_utc=utc_datetime(2026, 1, 1),
        supervised_build_fingerprint=(
            "aa53bfcce98dc5a51de94fec0cbae1e01686754614b484745bde00f4e94e0dde"
        ),
        expected_rows=1_089,
    ),
    CorpusComponentContract(
        component_id="2026-Q1",
        start_utc=utc_datetime(2026, 1, 1),
        end_utc=utc_datetime(2026, 4, 1),
        supervised_build_fingerprint=(
            "f6172aeaf3895fe354b749066fd9e1c00f62580db185093b82b76a2cce6142ae"
        ),
        expected_rows=1_947,
    ),
)

CURRENT_WORKING_CORPUS = WorkingCorpusContract(
    contract_version=CORPUS_CONTRACT_VERSION,
    corpus_id=WORKING_CORPUS_ID,
    supervised_schema_version=SCHEMA_VERSION,
    start_utc=utc_datetime(2022, 1, 1),
    end_utc=utc_datetime(2026, 4, 1),
    components=CURRENT_CORPUS_COMPONENTS,
    expected_rows=23_123,
    expected_source_matches=11_664,
    expected_radiant_wins=11_762,
    expected_radiant_losses=11_361,
)

CURRENT_TEMPORAL_SPLIT = TemporalSplitContract(
    contract_version=SPLIT_CONTRACT_VERSION,
    corpus_id=WORKING_CORPUS_ID,
    intervals=(
        SplitIntervalContract(
            interval_id="train",
            primary_split=PRIMARY_SPLIT_TRAIN,
            role=SPLIT_ROLE_TRAIN,
            start_utc=utc_datetime(2022, 1, 1),
            end_utc=utc_datetime(2025, 7, 1),
            expected_rows=18_623,
            expected_source_matches=9_254,
            expected_radiant_wins=9_445,
            expected_radiant_losses=9_178,
        ),
        SplitIntervalContract(
            interval_id="validation_tuning",
            primary_split=PRIMARY_SPLIT_VALIDATION,
            role=SPLIT_ROLE_TUNING,
            start_utc=utc_datetime(2025, 7, 1),
            end_utc=utc_datetime(2025, 10, 1),
            expected_rows=1_464,
            expected_source_matches=781,
            expected_radiant_wins=761,
            expected_radiant_losses=703,
        ),
        SplitIntervalContract(
            interval_id="validation_calibration",
            primary_split=PRIMARY_SPLIT_VALIDATION,
            role=SPLIT_ROLE_CALIBRATION,
            start_utc=utc_datetime(2025, 10, 1),
            end_utc=utc_datetime(2026, 1, 1),
            expected_rows=1_089,
            expected_source_matches=523,
            expected_radiant_wins=550,
            expected_radiant_losses=539,
        ),
        SplitIntervalContract(
            interval_id="locked_test",
            primary_split=PRIMARY_SPLIT_TEST,
            role=SPLIT_ROLE_LOCKED_TEST,
            start_utc=utc_datetime(2026, 1, 1),
            end_utc=utc_datetime(2026, 4, 1),
            expected_rows=1_947,
            expected_source_matches=1_106,
            expected_radiant_wins=1_006,
            expected_radiant_losses=941,
        ),
    ),
)

CURRENT_FEATURE_CONTRACT = FeatureContract(
    contract_version=FEATURE_CONTRACT_VERSION,
    default_profile="side_relative_draft_presence",
    unknown_category_token=UNKNOWN_CATEGORY_TOKEN,
    radiant_pick_columns=RADIANT_PICK_COLUMNS,
    dire_pick_columns=DIRE_PICK_COLUMNS,
    radiant_ban_columns=RADIANT_BAN_COLUMNS,
    dire_ban_columns=DIRE_BAN_COLUMNS,
    context_ablation_columns=CONTEXT_FEATURE_COLUMNS,
    identifier_columns=IDENTIFIER_COLUMNS,
    group_columns=GROUP_IDENTIFIER_COLUMNS,
    time_columns=TIME_COLUMNS,
    target_columns=TARGET_COLUMNS,
    forbidden_columns=FORBIDDEN_COLUMNS,
)

if CURRENT_FEATURE_CONTRACT.draft_columns != DRAFT_FEATURE_COLUMNS:
    raise ModelingContractError(
        "M4A feature contract does not match dota-draft-supervised-v1."
    )

CURRENT_BASELINE_FRAMEWORK = BaselineFrameworkContract(
    contract_version=BASELINE_CONTRACT_VERSION,
    baselines=(
        BaselineSpec(
            baseline_id="B0",
            family="empirical_prior",
            feature_profile="none",
            includes_picks=False,
            includes_bans=False,
            slot_aware=False,
            purpose="Honest no-skill probability reference.",
        ),
        BaselineSpec(
            baseline_id="B1",
            family="regularized_logistic_regression",
            feature_profile="side_relative_pick_presence",
            includes_picks=True,
            includes_bans=False,
            slot_aware=False,
            purpose="Explainable pick-only draft baseline.",
        ),
        BaselineSpec(
            baseline_id="B2",
            family="regularized_logistic_regression",
            feature_profile="side_relative_pick_and_ban_presence",
            includes_picks=True,
            includes_bans=True,
            slot_aware=False,
            purpose="Measure whether bans add stable draft signal.",
        ),
        BaselineSpec(
            baseline_id="B3",
            family="regularized_logistic_regression",
            feature_profile="side_relative_slot_aware",
            includes_picks=True,
            includes_bans=True,
            slot_aware=True,
            purpose="Test source per-team slot information without global order.",
        ),
    ),
)
