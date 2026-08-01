"""Development-only selection for the bounded M4B.4 interaction gate.

The selector compares two already-generated pick-interaction candidates with
the frozen M4B.2 B1 development predictions and the canonical B0 reference.
It cannot fit models and its input contract excludes calibration and locked
test periods.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, log_loss

from .recency_evaluation import (
    DEFAULT_BOOTSTRAP_RANDOM_STATE,
    DEFAULT_BOOTSTRAP_RESAMPLES,
    DEFAULT_CONFIDENCE_LEVEL,
    RECENT_DEVELOPMENT_FOLDS,
    RecencyEvaluationError,
    paired_recent_development_comparison,
)


DEVELOPMENT_FOLDS = (
    "2024-Q1",
    "2024-Q2",
    "2024-Q3",
    "2024-Q4",
    "2025-Q1",
    "2025-Q2",
    "2025-Q3",
)
EXPECTED_CANDIDATES = {
    "c1_pick_interactions_c0p001": 0.001,
    "c1_pick_interactions_c0p01": 0.01,
}
MINIMUM_RECENT_LOG_LOSS_IMPROVEMENT = 0.002
DEFAULT_PRACTICAL_LOG_LOSS_TIE = 0.002
MAXIMUM_SINGLE_FOLD_LOG_LOSS_REGRESSION = 0.01

_REQUIRED_COLUMNS = (
    "candidate_id",
    "C",
    "evaluation_id",
    "sample_id",
    "source_match_id",
    "radiant_win",
    "candidate_probability",
    "frozen_b1_probability",
    "canonical_b0_probability",
)
_PROBABILITY_COLUMNS = (
    "candidate_probability",
    "frozen_b1_probability",
    "canonical_b0_probability",
)
_SELECTION_METRICS = ("log_loss", "brier_score")


class InteractionSelectionError(ValueError):
    """Raised when interaction predictions violate the frozen M4B.4 policy."""


def _validated_predictions(predictions: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(predictions, pd.DataFrame):
        raise TypeError("Interaction candidate predictions must be a DataFrame.")
    if predictions.columns.duplicated().any():
        raise InteractionSelectionError(
            "Interaction predictions contain duplicate column names."
        )
    missing = sorted(set(_REQUIRED_COLUMNS).difference(predictions.columns))
    if missing:
        raise InteractionSelectionError(
            "Interaction predictions are missing columns: "
            + ", ".join(missing)
        )
    if predictions.empty:
        raise InteractionSelectionError(
            "Interaction candidate predictions cannot be empty."
        )

    result = predictions.loc[:, list(_REQUIRED_COLUMNS)].copy()
    for column in (
        "candidate_id",
        "evaluation_id",
        "sample_id",
        "source_match_id",
    ):
        if result[column].isna().any():
            raise InteractionSelectionError(
                f"Interaction predictions contain missing {column} values."
            )
        result[column] = result[column].astype("string").str.strip()
        if result[column].eq("").any():
            raise InteractionSelectionError(
                f"Interaction predictions contain empty {column} values."
            )

    observed_candidates = set(result["candidate_id"].tolist())
    expected_candidates = set(EXPECTED_CANDIDATES)
    if observed_candidates != expected_candidates:
        missing_candidates = sorted(
            expected_candidates.difference(observed_candidates)
        )
        extra_candidates = sorted(
            observed_candidates.difference(expected_candidates)
        )
        details: list[str] = []
        if missing_candidates:
            details.append("missing " + missing_candidates[0])
        if extra_candidates:
            details.append("unexpected " + extra_candidates[0])
        raise InteractionSelectionError(
            "Selection requires exactly the two approved candidates: "
            + "; ".join(details)
        )

    c_values = pd.to_numeric(result["C"], errors="coerce").to_numpy(
        dtype=np.float64
    )
    if not np.isfinite(c_values).all():
        raise InteractionSelectionError(
            "Interaction candidate C values must be finite numbers."
        )
    result["C"] = c_values
    for candidate_id, expected_c in EXPECTED_CANDIDATES.items():
        observed = result.loc[
            result["candidate_id"] == candidate_id,
            "C",
        ].unique()
        if len(observed) != 1 or not np.isclose(
            float(observed[0]),
            expected_c,
            rtol=0,
            atol=1e-15,
        ):
            raise InteractionSelectionError(
                f"{candidate_id} must use C={expected_c}."
            )
        result.loc[result["candidate_id"] == candidate_id, "C"] = (
            expected_c
        )

    targets = pd.to_numeric(result["radiant_win"], errors="coerce")
    if targets.isna().any() or not set(targets.unique()).issubset({0, 1}):
        raise InteractionSelectionError("radiant_win values must be binary.")
    result["radiant_win"] = targets.astype("int8")

    for column in _PROBABILITY_COLUMNS:
        values = pd.to_numeric(result[column], errors="coerce").to_numpy(
            dtype=np.float64
        )
        if not np.isfinite(values).all() or (
            (values < 0) | (values > 1)
        ).any():
            raise InteractionSelectionError(
                f"{column} must contain finite probabilities in [0, 1]."
            )
        result[column] = values

    observed_folds = set(result["evaluation_id"].tolist())
    if observed_folds != set(DEVELOPMENT_FOLDS):
        raise InteractionSelectionError(
            "Selection input must contain exactly 2024-Q1 through 2025-Q3."
        )
    return result


def _aligned_candidates(
    predictions: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    aligned: dict[str, pd.DataFrame] = {}
    reference: pd.DataFrame | None = None
    reference_id = sorted(EXPECTED_CANDIDATES)[0]

    for candidate_id in sorted(EXPECTED_CANDIDATES):
        rows = predictions[
            predictions["candidate_id"] == candidate_id
        ].sort_values(
            ["evaluation_id", "sample_id"],
            kind="stable",
        ).reset_index(drop=True)
        if rows["sample_id"].duplicated().any():
            duplicate = rows.loc[
                rows["sample_id"].duplicated(keep=False),
                "sample_id",
            ].iloc[0]
            raise InteractionSelectionError(
                f"{candidate_id} contains duplicate sample_id: {duplicate}"
            )
        if set(rows["evaluation_id"].tolist()) != set(DEVELOPMENT_FOLDS):
            raise InteractionSelectionError(
                f"{candidate_id} does not cover all seven development folds."
            )
        match_folds = rows.groupby(
            "source_match_id",
            sort=False,
        )["evaluation_id"].nunique()
        crossing = match_folds[match_folds != 1]
        if not crossing.empty:
            raise InteractionSelectionError(
                f"{candidate_id} has a source match crossing folds: "
                + str(crossing.index[0])
            )

        if candidate_id == reference_id:
            reference = rows
        elif reference is not None:
            if rows["sample_id"].tolist() != reference["sample_id"].tolist():
                raise InteractionSelectionError(
                    f"{candidate_id} sample alignment differs."
                )
            for column in (
                "source_match_id",
                "evaluation_id",
                "radiant_win",
                "frozen_b1_probability",
                "canonical_b0_probability",
            ):
                if not np.array_equal(
                    rows[column].to_numpy(),
                    reference[column].to_numpy(),
                ):
                    raise InteractionSelectionError(
                        f"{candidate_id} {column} alignment differs."
                    )
        aligned[candidate_id] = rows
    return aligned


def _probability_metrics(
    targets: np.ndarray,
    probabilities: np.ndarray,
) -> dict[str, float]:
    return {
        "log_loss": float(log_loss(targets, probabilities, labels=[0, 1])),
        "brier_score": float(brier_score_loss(targets, probabilities)),
    }


def _scope_metrics(rows: pd.DataFrame) -> dict[str, Any]:
    targets = rows["radiant_win"].to_numpy(dtype=np.int8)
    candidate = _probability_metrics(
        targets,
        rows["candidate_probability"].to_numpy(dtype=np.float64),
    )
    frozen_b1 = _probability_metrics(
        targets,
        rows["frozen_b1_probability"].to_numpy(dtype=np.float64),
    )
    canonical_b0 = _probability_metrics(
        targets,
        rows["canonical_b0_probability"].to_numpy(dtype=np.float64),
    )
    return {
        "rows": len(rows),
        "source_matches": int(rows["source_match_id"].nunique()),
        "candidate": candidate,
        "frozen_b1": frozen_b1,
        "canonical_b0": canonical_b0,
        "candidate_minus_frozen_b1": {
            metric: candidate[metric] - frozen_b1[metric]
            for metric in _SELECTION_METRICS
        },
        "candidate_minus_canonical_b0": {
            metric: candidate[metric] - canonical_b0[metric]
            for metric in _SELECTION_METRICS
        },
    }


def _evaluation_metrics(rows: pd.DataFrame) -> dict[str, Any]:
    folds = {
        fold: _scope_metrics(rows[rows["evaluation_id"] == fold])
        for fold in DEVELOPMENT_FOLDS
    }
    recent = rows[
        rows["evaluation_id"].isin(RECENT_DEVELOPMENT_FOLDS)
    ]
    return {
        "folds": folds,
        "recent_pooled": _scope_metrics(recent),
    }


def _paired_frames(
    rows: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    shared = rows[
        [
            "sample_id",
            "source_match_id",
            "evaluation_id",
            "radiant_win",
        ]
    ]
    reference = shared.copy()
    reference["radiant_win_probability"] = rows[
        "frozen_b1_probability"
    ].to_numpy(dtype=np.float64)
    candidate = shared.copy()
    candidate["radiant_win_probability"] = rows[
        "candidate_probability"
    ].to_numpy(dtype=np.float64)
    return reference, candidate


def _candidate_gate_results(
    *,
    evaluations: dict[str, Any],
    paired: dict[str, Any],
    minimum_recent_log_loss_improvement: float,
    maximum_single_fold_log_loss_regression: float,
) -> tuple[dict[str, Any], dict[str, float]]:
    folds = evaluations["folds"]
    recent_fold_gates: dict[str, dict[str, bool]] = {}
    for fold in RECENT_DEVELOPMENT_FOLDS:
        metrics = folds[fold]
        recent_fold_gates[fold] = {
            "log_loss_below_frozen_b1": (
                metrics["candidate"]["log_loss"]
                < metrics["frozen_b1"]["log_loss"]
            ),
            "brier_below_frozen_b1": (
                metrics["candidate"]["brier_score"]
                < metrics["frozen_b1"]["brier_score"]
            ),
            "log_loss_below_canonical_b0": (
                metrics["candidate"]["log_loss"]
                < metrics["canonical_b0"]["log_loss"]
            ),
            "brier_below_canonical_b0": (
                metrics["candidate"]["brier_score"]
                < metrics["canonical_b0"]["brier_score"]
            ),
        }
    all_recent_fold_gates = all(
        passed
        for fold_gates in recent_fold_gates.values()
        for passed in fold_gates.values()
    )

    pooled = evaluations["recent_pooled"]
    pooled_log_loss_improvement = (
        pooled["frozen_b1"]["log_loss"]
        - pooled["candidate"]["log_loss"]
    )
    pooled_gates = {
        "minimum_log_loss_improvement_vs_frozen_b1": (
            pooled_log_loss_improvement
            >= minimum_recent_log_loss_improvement
        ),
        "brier_below_frozen_b1": (
            pooled["candidate"]["brier_score"]
            < pooled["frozen_b1"]["brier_score"]
        ),
        "log_loss_below_canonical_b0": (
            pooled["candidate"]["log_loss"]
            < pooled["canonical_b0"]["log_loss"]
        ),
        "brier_below_canonical_b0": (
            pooled["candidate"]["brier_score"]
            < pooled["canonical_b0"]["brier_score"]
        ),
    }
    paired_gates = {
        "log_loss_upper_below_zero": (
            float(paired["metrics"]["log_loss"]["upper"]) < 0
        ),
        "brier_upper_below_zero": (
            float(paired["metrics"]["brier_score"]["upper"]) < 0
        ),
    }

    candidate_fold_log_losses = [
        folds[fold]["candidate"]["log_loss"]
        for fold in DEVELOPMENT_FOLDS
    ]
    frozen_b1_fold_log_losses = [
        folds[fold]["frozen_b1"]["log_loss"]
        for fold in DEVELOPMENT_FOLDS
    ]
    mean_candidate_log_loss = float(np.mean(candidate_fold_log_losses))
    mean_frozen_b1_log_loss = float(np.mean(frozen_b1_fold_log_losses))
    fold_regressions = {
        fold: (
            folds[fold]["candidate"]["log_loss"]
            - folds[fold]["frozen_b1"]["log_loss"]
        )
        for fold in DEVELOPMENT_FOLDS
    }
    maximum_observed_regression = max(fold_regressions.values())
    seven_fold_gates = {
        "mean_log_loss_no_worse_than_frozen_b1": (
            mean_candidate_log_loss <= mean_frozen_b1_log_loss
        ),
        "maximum_single_fold_log_loss_regression_within_limit": (
            maximum_observed_regression
            <= maximum_single_fold_log_loss_regression
        ),
    }

    gates: dict[str, Any] = {
        "recent_per_fold": recent_fold_gates,
        "all_recent_per_fold_gates": all_recent_fold_gates,
        "pooled_recent": pooled_gates,
        "all_pooled_recent_gates": all(pooled_gates.values()),
        "paired_frozen_b1": paired_gates,
        "all_paired_frozen_b1_gates": all(paired_gates.values()),
        "seven_fold": seven_fold_gates,
        "all_seven_fold_gates": all(seven_fold_gates.values()),
    }
    summary = {
        "candidate_mean_log_loss": mean_candidate_log_loss,
        "frozen_b1_mean_log_loss": mean_frozen_b1_log_loss,
        "candidate_minus_frozen_b1_mean_log_loss": (
            mean_candidate_log_loss - mean_frozen_b1_log_loss
        ),
        "maximum_single_fold_log_loss_regression": (
            maximum_observed_regression
        ),
        "minimum_recent_log_loss_improvement": (
            minimum_recent_log_loss_improvement
        ),
        "observed_recent_log_loss_improvement": (
            pooled_log_loss_improvement
        ),
    }
    return gates, summary


def _rank_qualifying(
    candidates: list[dict[str, Any]],
    *,
    practical_log_loss_tie: float,
) -> list[dict[str, Any]]:
    remaining = sorted(
        candidates,
        key=lambda item: (
            item["evaluations"]["recent_pooled"]["candidate"]["log_loss"],
            item["candidate_id"],
        ),
    )
    c_preference = {0.001: 0, 0.01: 1}
    ranked: list[dict[str, Any]] = []
    while remaining:
        best_log_loss = remaining[0]["evaluations"]["recent_pooled"][
            "candidate"
        ]["log_loss"]
        tie_group = [
            item
            for item in remaining
            if (
                item["evaluations"]["recent_pooled"]["candidate"]["log_loss"]
                <= best_log_loss + practical_log_loss_tie
            )
        ]
        tie_group.sort(
            key=lambda item: (
                c_preference[item["C"]],
                item["candidate_id"],
            )
        )
        ranked.extend(tie_group)
        tied_ids = {item["candidate_id"] for item in tie_group}
        remaining = [
            item
            for item in remaining
            if item["candidate_id"] not in tied_ids
        ]
    return ranked


def select_interaction_candidate(
    predictions: pd.DataFrame,
    *,
    n_resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES,
    random_state: int = DEFAULT_BOOTSTRAP_RANDOM_STATE,
    confidence_level: float = DEFAULT_CONFIDENCE_LEVEL,
    minimum_recent_log_loss_improvement: float = (
        MINIMUM_RECENT_LOG_LOSS_IMPROVEMENT
    ),
    practical_log_loss_tie: float = DEFAULT_PRACTICAL_LOG_LOSS_TIE,
    maximum_single_fold_log_loss_regression: float = (
        MAXIMUM_SINGLE_FOLD_LOG_LOSS_REGRESSION
    ),
) -> dict[str, Any]:
    """Apply the frozen M4B.4 gates to exactly two interaction candidates."""

    if minimum_recent_log_loss_improvement < 0:
        raise InteractionSelectionError(
            "Minimum recent log-loss improvement cannot be negative."
        )
    if practical_log_loss_tie < 0:
        raise InteractionSelectionError(
            "Practical log-loss tie threshold cannot be negative."
        )
    if maximum_single_fold_log_loss_regression < 0:
        raise InteractionSelectionError(
            "Maximum single-fold regression cannot be negative."
        )

    validated = _validated_predictions(predictions)
    aligned = _aligned_candidates(validated)

    candidate_results: list[dict[str, Any]] = []
    for candidate_id in sorted(EXPECTED_CANDIDATES):
        rows = aligned[candidate_id]
        evaluations = _evaluation_metrics(rows)
        reference, candidate = _paired_frames(rows)
        try:
            paired = paired_recent_development_comparison(
                reference,
                candidate,
                n_resamples=n_resamples,
                random_state=random_state,
                confidence_level=confidence_level,
            )
        except RecencyEvaluationError as error:
            raise InteractionSelectionError(
                f"Paired evaluation failed for {candidate_id}: {error}"
            ) from error
        gates, seven_fold_summary = _candidate_gate_results(
            evaluations=evaluations,
            paired=paired,
            minimum_recent_log_loss_improvement=(
                minimum_recent_log_loss_improvement
            ),
            maximum_single_fold_log_loss_regression=(
                maximum_single_fold_log_loss_regression
            ),
        )
        qualifies = (
            gates["all_recent_per_fold_gates"]
            and gates["all_pooled_recent_gates"]
            and gates["all_paired_frozen_b1_gates"]
            and gates["all_seven_fold_gates"]
        )
        candidate_results.append(
            {
                "candidate_id": candidate_id,
                "C": EXPECTED_CANDIDATES[candidate_id],
                "evaluations": evaluations,
                "seven_fold_summary": seven_fold_summary,
                "paired_frozen_b1_comparison": paired,
                "gate_results": gates,
                "qualifies_as_development_candidate": bool(qualifies),
            }
        )

    qualifying = [
        item
        for item in candidate_results
        if item["qualifies_as_development_candidate"]
    ]
    ranked = _rank_qualifying(
        qualifying,
        practical_log_loss_tie=practical_log_loss_tie,
    )
    rank_by_id = {
        item["candidate_id"]: index
        for index, item in enumerate(ranked, start=1)
    }
    for item in candidate_results:
        item["selection_rank"] = rank_by_id.get(item["candidate_id"])

    selected = ranked[0] if ranked else None
    reference_rows = aligned[sorted(aligned)[0]]
    fold_rows = {
        fold: int((reference_rows["evaluation_id"] == fold).sum())
        for fold in DEVELOPMENT_FOLDS
    }
    return {
        "selection_scope": "development_only_2024_q1_2025_q3",
        "selection_status": (
            "interaction_development_candidate_selected"
            if selected is not None
            else "no_interaction_candidate_passed_all_development_gates"
        ),
        "selected_candidate_id": (
            selected["candidate_id"] if selected is not None else None
        ),
        "q4_or_locked_test_used": False,
        "stop_model_expansion_if_no_candidate_qualifies": True,
        "policy": {
            "evaluation_fold_ids": list(DEVELOPMENT_FOLDS),
            "selection_fold_ids": list(RECENT_DEVELOPMENT_FOLDS),
            "recent_strict_improvement_folds": list(
                RECENT_DEVELOPMENT_FOLDS
            ),
            "minimum_recent_log_loss_improvement_vs_frozen_b1": (
                minimum_recent_log_loss_improvement
            ),
            "paired_interval_reference": "frozen_b1",
            "paired_interval_gate": (
                "95% upper bound below zero for log loss and Brier"
            ),
            "seven_fold_mean_log_loss_gate": (
                "candidate must be no worse than frozen B1"
            ),
            "maximum_single_fold_log_loss_regression": (
                maximum_single_fold_log_loss_regression
            ),
            "ranking_metric": "pooled_recent_log_loss",
            "practical_log_loss_tie": practical_log_loss_tie,
            "C_preference": [0.001, 0.01],
        },
        "audit": {
            "candidate_count": len(candidate_results),
            "expected_candidate_count": len(EXPECTED_CANDIDATES),
            "rows_per_candidate": len(reference_rows),
            "source_matches_per_candidate": int(
                reference_rows["source_match_id"].nunique()
            ),
            "fold_rows_per_candidate": fold_rows,
            "bootstrap_resamples_per_candidate": n_resamples,
            "bootstrap_random_state": random_state,
            "bootstrap_confidence_level": confidence_level,
            "probability_references": ["frozen_b1", "canonical_b0"],
            "calibration_rows_used": 0,
            "locked_test_rows_used": 0,
        },
        "qualifying_ranking": [
            item["candidate_id"] for item in ranked
        ],
        "candidates": candidate_results,
    }


__all__ = [
    "DEFAULT_PRACTICAL_LOG_LOSS_TIE",
    "DEVELOPMENT_FOLDS",
    "EXPECTED_CANDIDATES",
    "InteractionSelectionError",
    "MAXIMUM_SINGLE_FOLD_LOG_LOSS_REGRESSION",
    "MINIMUM_RECENT_LOG_LOSS_IMPROVEMENT",
    "select_interaction_candidate",
]
