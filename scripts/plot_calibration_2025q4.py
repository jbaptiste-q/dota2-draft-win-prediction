#!/usr/bin/env python3
"""Regenerate docs/assets/calibration_2025q4.png.

Pure aggregation of the already-computed, pinned M4B.5 Q4 predictions —
nothing is re-fit and no new predictions are made. Reads
``frozen_b1_probability`` (the frozen draft-only candidate) and
``radiant_win`` from the pinned ``q4_predictions.parquet`` build artifact.

Binning: 6 equal-frequency (quantile) bins rather than equal-width. With
1,089 predictions concentrated in a narrow band, equal-width bins put as
few as ~44 rows in a tail bin and ~580 in the middle one; the swing that
produced in the previous version of this figure was mostly a sample-size
artifact, not evidence of miscalibration. Quantile bins hold each bin's n
close to constant (~181-182 here), so every point on the curve carries
comparable statistical power and the 95% Wilson interval widths are
directly comparable across the curve.
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.draft_ai_modeling.evaluation import reliability_bins  # noqa: E402
from src.draft_ai_modeling.loader import sha256_file  # noqa: E402


Q4_PREDICTIONS_PATH = (
    REPO_ROOT
    / "models/m4b5/build_d90302404883e5ba7283c00e88d7d922f2b76e771630013acf9632ac20639e8b"
    / "q4_predictions.parquet"
)
Q4_PREDICTIONS_SHA256 = (
    "476552017fddd84bd2732c333ecaa77c6380572c2128cb64a120dea5a63eecd2"
)
EXPECTED_ROWS = 1089
OUTPUT_PATH = REPO_ROOT / "docs/assets/calibration_2025q4.png"

N_QUANTILE_BINS = 6
ECE_EQUAL_WIDTH_BINS = 10
CONFIDENCE_Z = 1.959963985  # 97.5th percentile of the standard normal

FIG_FACECOLOR = "#fcfcfb"
GRID_COLOR = "#e5e4df"
TEXT_COLOR = "#52514e"
MODEL_COLOR = "#1f6f8b"
PRIOR_COLOR = "#c1440e"
AXIS_PAD = 0.02


def _wilson_interval(successes: int, n: int, *, z: float = CONFIDENCE_Z) -> tuple[float, float]:
    phat = successes / n
    denominator = 1 + z**2 / n
    center = (phat + z**2 / (2 * n)) / denominator
    margin = z * np.sqrt(phat * (1 - phat) / n + z**2 / (4 * n**2)) / denominator
    return center - margin, center + margin


def load_q4_predictions() -> pd.DataFrame:
    if (
        not Q4_PREDICTIONS_PATH.is_file()
        or sha256_file(Q4_PREDICTIONS_PATH) != Q4_PREDICTIONS_SHA256
    ):
        raise SystemExit(
            "The pinned M4B.5 Q4 predictions artifact changed or is missing."
        )
    with duckdb.connect() as connection:
        frame = connection.execute(
            "SELECT sample_id, radiant_win, frozen_b1_probability "
            "FROM read_parquet(?) ORDER BY sample_id",
            [str(Q4_PREDICTIONS_PATH)],
        ).fetchdf()
    if len(frame) != EXPECTED_ROWS:
        raise SystemExit("The pinned Q4 row count changed.")
    return frame


def quantile_bin_records(
    probabilities: np.ndarray,
    targets: np.ndarray,
    *,
    n_bins: int,
) -> list[dict[str, float | int]]:
    bin_index = pd.qcut(probabilities, q=n_bins, labels=False, duplicates="drop")
    records = []
    for bin_id in sorted(pd.unique(bin_index)):
        mask = bin_index == bin_id
        n = int(mask.sum())
        wins = int(targets[mask].sum())
        lower, upper = _wilson_interval(wins, n)
        mean_pred = float(probabilities[mask].mean())
        obs_rate = wins / n
        records.append(
            {
                "n": n,
                "mean_predicted": mean_pred,
                "observed_rate": obs_rate,
                "ci_lower": lower,
                "ci_upper": upper,
            }
        )
    return records


def main() -> None:
    frame = load_q4_predictions()
    probabilities = frame["frozen_b1_probability"].to_numpy(dtype=np.float64)
    targets = frame["radiant_win"].to_numpy(dtype=np.int64)
    observed_q4_base_rate = float(targets.mean())

    records = quantile_bin_records(probabilities, targets, n_bins=N_QUANTILE_BINS)
    _, ece = reliability_bins(targets, probabilities, n_bins=ECE_EQUAL_WIDTH_BINS)

    x = np.asarray([r["mean_predicted"] for r in records])
    y = np.asarray([r["observed_rate"] for r in records])
    y_lower = np.asarray([r["ci_lower"] for r in records])
    y_upper = np.asarray([r["ci_upper"] for r in records])
    ns = [r["n"] for r in records]

    axis_min = min(probabilities.min(), y_lower.min()) - AXIS_PAD
    axis_max = max(probabilities.max(), y_upper.max()) + AXIS_PAD

    plt.rcParams.update(
        {
            "figure.facecolor": FIG_FACECOLOR,
            "axes.facecolor": FIG_FACECOLOR,
            "axes.edgecolor": GRID_COLOR,
            "axes.labelcolor": TEXT_COLOR,
            "text.color": TEXT_COLOR,
            "xtick.color": TEXT_COLOR,
            "ytick.color": TEXT_COLOR,
            "font.size": 12,
        }
    )
    fig, (ax_rel, ax_hist) = plt.subplots(
        2,
        1,
        figsize=(9, 10),
        gridspec_kw={"height_ratios": [2.2, 1]},
        sharex=True,
    )

    ax_rel.plot(
        [axis_min, axis_max],
        [axis_min, axis_max],
        linestyle="--",
        color="#a6a6a4",
        linewidth=1.3,
        label="Perfect calibration",
        zorder=1,
    )
    ax_rel.axhline(
        observed_q4_base_rate,
        linestyle="--",
        color=PRIOR_COLOR,
        linewidth=1.5,
        label=f"Empirical prior (observed Q4 base rate = {observed_q4_base_rate:.3f})",
        zorder=1,
    )
    ax_rel.errorbar(
        x,
        y,
        yerr=[y - y_lower, y_upper - y],
        fmt="o-",
        color=MODEL_COLOR,
        ecolor=MODEL_COLOR,
        elinewidth=1.3,
        capsize=4,
        markersize=7,
        linewidth=1.6,
        label="Draft model (Frozen B1), 95% Wilson CI",
        zorder=3,
    )
    for xi, yi, n in zip(x, y_upper, ns, strict=True):
        ax_rel.annotate(
            f"n={n}",
            (xi, yi),
            textcoords="offset points",
            xytext=(0, 8),
            ha="center",
            fontsize=9,
            color=TEXT_COLOR,
        )
    ax_rel.annotate(
        f"ECE = {ece:.4f} ({ECE_EQUAL_WIDTH_BINS} equal-width bins)",
        xy=(0.02, 0.96),
        xycoords="axes fraction",
        fontsize=10,
        color=TEXT_COLOR,
        va="top",
    )
    ax_rel.set_xlim(axis_min, axis_max)
    ax_rel.set_ylim(axis_min, axis_max)
    ax_rel.set_ylabel("Observed Radiant win rate")
    ax_rel.set_title(f"Calibration on the 2025-Q4 readiness gate (n={EXPECTED_ROWS:,})")
    ax_rel.grid(color=GRID_COLOR, linewidth=0.8)
    ax_rel.set_axisbelow(True)
    ax_rel.legend(loc="lower right", frameon=False, fontsize=9.5)

    ax_hist.hist(
        probabilities,
        bins=30,
        range=(axis_min, axis_max),
        color=MODEL_COLOR,
        alpha=0.55,
        edgecolor=FIG_FACECOLOR,
    )
    ax_hist.axvline(
        observed_q4_base_rate,
        linestyle="--",
        color=PRIOR_COLOR,
        linewidth=1.5,
    )
    ax_hist.set_xlim(axis_min, axis_max)
    ax_hist.set_xlabel("Mean predicted probability (Radiant win)")
    ax_hist.set_ylabel("Games")
    ax_hist.grid(color=GRID_COLOR, linewidth=0.8)
    ax_hist.set_axisbelow(True)

    fig.text(
        0.01,
        0.018,
        f"{N_QUANTILE_BINS} equal-frequency bins (~{EXPECTED_ROWS // N_QUANTILE_BINS} rows "
        "each); error bars are 95% Wilson score intervals.",
        fontsize=8.5,
        color="#9a9a9a",
        style="italic",
    )
    fig.text(
        0.01,
        0.002,
        "Binned directly from the pinned M4B.5 build's q4_predictions.parquet; "
        "nothing is re-fit.",
        fontsize=8.5,
        color="#9a9a9a",
        style="italic",
    )

    fig.tight_layout(rect=(0, 0.045, 1, 1))
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUTPUT_PATH, dpi=300)
    print(f"Wrote {OUTPUT_PATH}")
    print(f"Observed Q4 base rate: {observed_q4_base_rate:.6f}")
    print(f"ECE ({ECE_EQUAL_WIDTH_BINS} equal-width bins): {ece:.6f}")
    for record in records:
        print(record)


if __name__ == "__main__":
    main()
