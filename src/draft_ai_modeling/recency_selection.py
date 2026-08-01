"""Development-only selection for the bounded Draft AI recency experiment.

The selector consumes already-generated predictions for the exact nine
approved candidates.  It neither fits a model nor reads calibration or locked
test rows.
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


HISTORY_POLICY_PREFERENCE = (
    "full_uniform",
    "full_exp180",
    "trailing365_uniform",
)
C_PREFERENCE = (0.01, 0.1, 1.0)
EXPECTED_CANDIDATE_COUNT = len(HISTORY_POLICY_PREFERENCE) * len(C_PREFERENCE)
DEFAULT_PRACTICAL_LOG_LOSS_TIE = 0.002

_REQUIRED_COLUMNS = (
    "candidate_id",
    "history_policy_id",
    "C",
    "evaluation_id",
    "sample_id",
    "source_match_id",
    "radiant_win",
    "candidate_probability",
    "policy_matched_b0_probability",
    "canonical_b0_probability",
)
_PROBABILITY_COLUMNS = (
    "candidate_probability",
    "policy_matched_b0_probability",
    "canonical_b0_probability",
)


class RecencySelectionError(ValueError):
    """Raised when candidate predictions violate the approved experiment."""


def _normalize_c(value: object) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise RecencySelectionError("Candidate C values must be numeric.") from error
    matches = [
        expected
        for expected in C_PREFERENCE
        if np.isclose(result, expected, rtol=0, atol=1e-12)
    ]
    if len(matches) != 1:
        raise RecencySelectionError(
            "Candidate C values must be exactly 0.01, 0.1, or 1.0."
        )
    return matches[0]


def _validated_predictions(predictions: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(predictions, pd.DataFrame):
        raise TypeError("Recency candidate predictions must be a DataFrame.")
    if predictions.columns.duplicated().any():
        raise RecencySelectionError(
            "Candidate predictions contain duplicate column names."
        )
    missing = sorted(set(_REQUIRED_COLUMNS).difference(predictions.columns))
    if missing:
        raise RecencySelectionError(
            "Candidate predictions are missing columns: " + ", ".join(missing)
        )
    if predictions.empty:
        raise RecencySelectionError("Candidate predictions cannot be empty.")

    result = predictions.loc[:, list(_REQUIRED_COLUMNS)].copy()
    string_columns = (
        "candidate_id",
        "history_policy_id",
        "evaluation_id",
        "sample_id",
        "source_match_id",
    )
    for column in string_columns:
        if result[column].isna().any():
            raise RecencySelectionError(
                f"Candidate predictions contain missing {column} values."
            )
        result[column] = result[column].astype("string").str.strip()
        if result[column].eq("").any():
            raise RecencySelectionError(
                f"Candidate predictions contain empty {column} values."
            )

    result["C"] = result["C"].map(_normalize_c)
    targets = pd.to_numeric(result["radiant_win"], errors="coerce")
    if targets.isna().any() or not set(targets.unique()).issubset({0, 1}):
        raise RecencySelectionError("radiant_win values must be binary.")
    result["radiant_win"] = targets.astype("int8")

    for column in _PROBABILITY_COLUMNS:
        values = pd.to_numeric(result[column], errors="coerce").to_numpy(
            dtype=np.float64
        )
        if not np.isfinite(values).all() or (
            (values < 0) | (values > 1)
        ).any():
            raise RecencySelectionError(
                f"{column} must contain finite probabilities in [0, 1]."
            )
        result[column] = values

    observed_folds = set(result["evaluation_id"].tolist())
    if observed_folds != set(RECENT_DEVELOPMENT_FOLDS):
        raise RecencySelectionError(
            "Selection input must contain only 2025-Q1 through 2025-Q3."
        )
    return result


def _candidate_contracts(
    predictions: pd.DataFrame,
) -> dict[str, tuple[str, float]]:
    contracts: dict[str, tuple[str, float]] = {}
    for candidate_id, rows in predictions.groupby(
        "candidate_id",
        sort=True,
    ):
        policies = rows["history_policy_id"].unique().tolist()
        c_values = rows["C"].unique().tolist()
        if len(policies) != 1 or len(c_values) != 1:
            raise RecencySelectionError(
                f"Candidate {candidate_id} maps to multiple configurations."
            )
        contracts[str(candidate_id)] = (str(policies[0]), float(c_values[0]))

    if len(contracts) != EXPECTED_CANDIDATE_COUNT:
        raise RecencySelectionError(
            f"Selection requires exactly {EXPECTED_CANDIDATE_COUNT} candidates."
        )
    expected = {
        (history_policy, c_value)
        for history_policy in HISTORY_POLICY_PREFERENCE
        for c_value in C_PREFERENCE
    }
    observed = set(contracts.values())
    if observed != expected:
        missing = sorted(expected.difference(observed))
        duplicates = len(contracts) - len(observed)
        details = []
        if missing:
            details.append(f"missing configuration {missing[0]}")
        if duplicates:
            details.append(f"{duplicates} duplicate configuration(s)")
        raise RecencySelectionError(
            "Candidate configurations do not form the approved grid: "
            + "; ".join(details)
        )
    return contracts


def _aligned_candidates(
    predictions: pd.DataFrame,
    contracts: dict[str, tuple[str, float]],
) -> dict[str, pd.DataFrame]:
    aligned: dict[str, pd.DataFrame] = {}
    reference_id = sorted(contracts)[0]
    reference: pd.DataFrame | None = None

    for candidate_id in sorted(contracts):
        rows = predictions[
            predictions["candidate_id"] == candidate_id
        ].sort_values("sample_id", kind="stable").reset_index(drop=True)
        if rows["sample_id"].duplicated().any():
            raise RecencySelectionError(
                f"Candidate {candidate_id} contains duplicate samples."
            )
        if set(rows["evaluation_id"]) != set(RECENT_DEVELOPMENT_FOLDS):
            raise RecencySelectionError(
                f"Candidate {candidate_id} does not cover all selected folds."
            )
        group_folds = rows.groupby(
            "source_match_id",
            sort=False,
        )["evaluation_id"].nunique()
        if (group_folds != 1).any():
            raise RecencySelectionError(
                f"Candidate {candidate_id} has a match crossing folds."
            )

        if candidate_id == reference_id:
            reference = rows
        elif reference is not None:
            if rows["sample_id"].tolist() != reference["sample_id"].tolist():
                raise RecencySelectionError(
                    f"Candidate {candidate_id} sample alignment differs."
                )
            for column in (
                "source_match_id",
                "evaluation_id",
                "radiant_win",
                "canonical_b0_probability",
            ):
                if not np.array_equal(
                    rows[column].to_numpy(),
                    reference[column].to_numpy(),
                ):
                    raise RecencySelectionError(
                        f"Candidate {candidate_id} {column} alignment differs."
                    )
        aligned[candidate_id] = rows

    for history_policy in HISTORY_POLICY_PREFERENCE:
        policy_candidates = [
            candidate_id
            for candidate_id, (policy, _) in contracts.items()
            if policy == history_policy
        ]
        policy_reference = aligned[sorted(policy_candidates)[0]]
        for candidate_id in policy_candidates[1:]:
            if not np.array_equal(
                aligned[candidate_id][
                    "policy_matched_b0_probability"
                ].to_numpy(),
                policy_reference[
                    "policy_matched_b0_probability"
                ].to_numpy(),
            ):
                raise RecencySelectionError(
                    f"Policy-matched B0 differs within {history_policy}."
                )
    return aligned


def _probability_metrics(
    targets: np.ndarray,
    probabilities: np.ndarray,
) -> dict[str, float]:
    return {
        "log_loss": float(log_loss(targets, probabilities, labels=[0, 1])),
        "brier_score": float(brier_score_loss(targets, probabilities)),
    }


def _evaluation_metrics(rows: pd.DataFrame) -> dict[str, Any]:
    result: dict[str, Any] = {}
    evaluation_scopes = (
        *(
            (fold, rows[rows["evaluation_id"] == fold])
            for fold in RECENT_DEVELOPMENT_FOLDS
        ),
        ("pooled", rows),
    )
    for evaluation_id, selected in evaluation_scopes:
        targets = selected["radiant_win"].to_numpy(dtype=np.int8)
        candidate = _probability_metrics(
            targets,
            selected["candidate_probability"].to_numpy(dtype=np.float64),
        )
        policy_reference = _probability_metrics(
            targets,
            selected[
                "policy_matched_b0_probability"
            ].to_numpy(dtype=np.float64),
        )
        canonical_reference = _probability_metrics(
            targets,
            selected["canonical_b0_probability"].to_numpy(dtype=np.float64),
        )
        gates = {
            metric: {
                "beats_policy_matched_b0": (
                    candidate[metric] < policy_reference[metric]
                ),
                "beats_canonical_b0": (
                    candidate[metric] < canonical_reference[metric]
                ),
            }
            for metric in ("log_loss", "brier_score")
        }
        result[evaluation_id] = {
            "rows": len(selected),
            "candidate": candidate,
            "policy_matched_b0": policy_reference,
            "canonical_b0": canonical_reference,
            "strict_improvement_gates": gates,
            "passes_all_strict_improvement_gates": all(
                check
                for metric_gates in gates.values()
                for check in metric_gates.values()
            ),
        }
    return result


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
        "policy_matched_b0_probability"
    ].to_numpy(dtype=np.float64)
    candidate = shared.copy()
    candidate["radiant_win_probability"] = rows[
        "candidate_probability"
    ].to_numpy(dtype=np.float64)
    return reference, candidate


def _rank_qualifying(
    candidates: list[dict[str, Any]],
    *,
    practical_tie: float,
) -> list[dict[str, Any]]:
    remaining = sorted(
        candidates,
        key=lambda item: (
            item["evaluations"]["pooled"]["candidate"]["log_loss"],
            item["candidate_id"],
        ),
    )
    ranked: list[dict[str, Any]] = []
    history_rank = {
        value: index
        for index, value in enumerate(HISTORY_POLICY_PREFERENCE)
    }
    c_rank = {value: index for index, value in enumerate(C_PREFERENCE)}

    while remaining:
        best_log_loss = remaining[0]["evaluations"]["pooled"][
            "candidate"
        ]["log_loss"]
        tie_group = [
            item
            for item in remaining
            if (
                item["evaluations"]["pooled"]["candidate"]["log_loss"]
                <= best_log_loss + practical_tie
            )
        ]
        tie_group.sort(
            key=lambda item: (
                history_rank[item["history_policy_id"]],
                c_rank[item["C"]],
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


def select_recency_candidate(
    predictions: pd.DataFrame,
    *,
    n_resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES,
    random_state: int = DEFAULT_BOOTSTRAP_RANDOM_STATE,
    confidence_level: float = DEFAULT_CONFIDENCE_LEVEL,
    practical_log_loss_tie: float = DEFAULT_PRACTICAL_LOG_LOSS_TIE,
) -> dict[str, Any]:
    """Apply the approved development gates to exactly nine candidates."""

    if practical_log_loss_tie < 0:
        raise RecencySelectionError(
            "Practical log-loss tie threshold cannot be negative."
        )
    validated = _validated_predictions(predictions)
    contracts = _candidate_contracts(validated)
    aligned = _aligned_candidates(validated, contracts)

    candidate_results: list[dict[str, Any]] = []
    for candidate_id in sorted(contracts):
        history_policy, c_value = contracts[candidate_id]
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
            raise RecencySelectionError(
                f"Paired evaluation failed for {candidate_id}: {error}"
            ) from error
        paired_gates = {
            metric: paired["metrics"][metric]["upper"] < 0
            for metric in ("log_loss", "brier_score")
        }
        strict_gates = all(
            evaluation[
                "passes_all_strict_improvement_gates"
            ]
            for evaluation in evaluations.values()
        )
        qualifies = strict_gates and all(paired_gates.values())
        candidate_results.append(
            {
                "candidate_id": candidate_id,
                "history_policy_id": history_policy,
                "C": c_value,
                "evaluations": evaluations,
                "paired_policy_b0_comparison": paired,
                "gate_results": {
                    "all_fold_and_pooled_strict_improvements": strict_gates,
                    "paired_log_loss_upper_below_zero": paired_gates[
                        "log_loss"
                    ],
                    "paired_brier_upper_below_zero": paired_gates[
                        "brier_score"
                    ],
                },
                "qualifies_as_development_candidate": qualifies,
            }
        )

    qualifying = [
        item
        for item in candidate_results
        if item["qualifies_as_development_candidate"]
    ]
    ranked = _rank_qualifying(
        qualifying,
        practical_tie=practical_log_loss_tie,
    )
    rank_by_id = {
        item["candidate_id"]: index
        for index, item in enumerate(ranked, start=1)
    }
    for item in candidate_results:
        item["selection_rank"] = rank_by_id.get(item["candidate_id"])

    selected = ranked[0] if ranked else None
    fold_rows = {
        fold: int(
            (
                aligned[sorted(aligned)[0]]["evaluation_id"]
                == fold
            ).sum()
        )
        for fold in RECENT_DEVELOPMENT_FOLDS
    }
    return {
        "selection_scope": "development_only_2025_q1_q3",
        "selection_status": (
            "development_candidate_selected"
            if selected is not None
            else "no_candidate_passed_all_development_gates"
        ),
        "selected_candidate_id": (
            selected["candidate_id"] if selected is not None else None
        ),
        "not_a_final_champion": True,
        "calibration_or_locked_test_used": False,
        "policy": {
            "strict_improvement_vs_references": (
                "candidate metric must be lower than both references "
                "in every fold and pooled"
            ),
            "paired_interval_reference": "policy_matched_b0",
            "paired_interval_gate": (
                "95% upper bound below zero for log loss and Brier"
            ),
            "practical_log_loss_tie": practical_log_loss_tie,
            "history_policy_preference": list(HISTORY_POLICY_PREFERENCE),
            "C_preference": list(C_PREFERENCE),
        },
        "audit": {
            "candidate_count": len(candidate_results),
            "expected_candidate_count": EXPECTED_CANDIDATE_COUNT,
            "qualifying_candidate_count": len(qualifying),
            "rows_per_candidate": len(aligned[sorted(aligned)[0]]),
            "source_matches_per_candidate": int(
                aligned[sorted(aligned)[0]][
                    "source_match_id"
                ].nunique()
            ),
            "fold_rows_per_candidate": fold_rows,
            "bootstrap_resamples_per_candidate": n_resamples,
            "bootstrap_random_state": random_state,
            "bootstrap_confidence_level": confidence_level,
            "probability_references": [
                "policy_matched_b0",
                "canonical_b0",
            ],
        },
        "qualifying_ranking": [
            item["candidate_id"] for item in ranked
        ],
        "candidates": candidate_results,
    }


__all__ = [
    "C_PREFERENCE",
    "DEFAULT_PRACTICAL_LOG_LOSS_TIE",
    "EXPECTED_CANDIDATE_COUNT",
    "HISTORY_POLICY_PREFERENCE",
    "RecencySelectionError",
    "select_recency_candidate",
]
