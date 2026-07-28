"""Coverage and data-quality reports derived from normalized Parquet tables."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from .assembly import write_parquet


def read_parquet(path: Path) -> pd.DataFrame:
    """Read a Parquet file without requiring PyArrow."""
    with duckdb.connect() as connection:
        return connection.execute(
            "SELECT * FROM read_parquet(?)",
            [str(path.resolve())],
        ).fetchdf()


def percentage(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """Calculate a deterministic percentage with zero-safe denominators."""
    result = numerator.astype("float64").div(
        denominator.replace(0, pd.NA).astype("Float64")
    )
    return (result * 100).round(6).fillna(0.0)


def aggregate_dimension(
    games: pd.DataFrame,
    *,
    dimension: str,
    values: pd.Series,
) -> pd.DataFrame:
    """Aggregate consistent coverage metrics for one grouping dimension."""
    working = games.copy()
    working["dimension_value"] = values.astype("string").fillna("<unknown>")
    rows = []
    for value, group in working.groupby(
        "dimension_value",
        dropna=False,
        sort=True,
    ):
        game_count = len(group)
        rows.append(
            {
                "dimension": dimension,
                "dimension_value": str(value),
                "match_count": group["source_match_id"].nunique(),
                "game_count": game_count,
                "trainable_game_count": int(group["is_trainable_draft"].sum()),
                "winner_known_count": int(group["winner_known"].sum()),
                "sides_known_count": int(group["sides_known"].sum()),
                "complete_picks_count": int(group["complete_picks"].sum()),
                "complete_bans_count": int(group["complete_bans"].sum()),
                "patch_known_count": int(group["patch_known"].sum()),
            }
        )
    columns = (
        "dimension",
        "dimension_value",
        "match_count",
        "game_count",
        "trainable_game_count",
        "winner_known_count",
        "sides_known_count",
        "complete_picks_count",
        "complete_bans_count",
        "patch_known_count",
    )
    frame = pd.DataFrame(rows, columns=columns)
    if frame.empty:
        for column in columns[:2]:
            frame[column] = frame[column].astype("string")
        for column in columns[2:]:
            frame[column] = frame[column].astype("Int64")
    else:
        frame[["dimension", "dimension_value"]] = frame[
            ["dimension", "dimension_value"]
        ].astype("string")
        for column in columns[2:]:
            frame[column] = frame[column].astype("Int64")
    for numerator in (
        "trainable_game_count",
        "winner_known_count",
        "sides_known_count",
        "complete_picks_count",
        "complete_bans_count",
        "patch_known_count",
    ):
        frame[numerator.replace("_count", "_pct")] = percentage(
            frame[numerator],
            frame["game_count"],
        )
    return frame


def prepare_game_quality(normalized_build: Path) -> pd.DataFrame:
    """Join normalized tables into one quality-audit row per game."""
    games = read_parquet(normalized_build / "games.parquet")
    matches = read_parquet(normalized_build / "matches.parquet")
    picks = read_parquet(normalized_build / "draft_picks.parquet")
    bans = read_parquet(normalized_build / "draft_bans.parquet")

    match_context = matches[
        [
            "source_match_id",
            "liquipedia_tier",
            "tournament",
            "series",
        ]
    ].drop_duplicates("source_match_id")
    quality = games.merge(
        match_context,
        how="left",
        on="source_match_id",
        validate="many_to_one",
    )
    pick_counts = picks.groupby("game_key").size()
    ban_counts = bans.groupby("game_key").size()
    quality["pick_count"] = (
        quality["game_key"].map(pick_counts).fillna(0).astype("Int64")
    )
    quality["ban_count"] = (
        quality["game_key"].map(ban_counts).fillna(0).astype("Int64")
    )
    quality["winner_known"] = quality["winner_team_slot"].isin([1, 2])
    quality["sides_known"] = (
        quality["team1_side"].isin(["radiant", "dire"])
        & quality["team2_side"].isin(["radiant", "dire"])
        & quality["team1_side"].ne(quality["team2_side"])
    )
    quality["complete_picks"] = quality["pick_count"].eq(10)
    quality["complete_bans"] = quality["ban_count"].eq(14)
    quality["patch_known"] = quality["patch"].notna() & quality["patch"].ne("")
    quality["start_time_utc"] = pd.to_datetime(
        quality["start_time_utc"],
        utc=True,
    )
    return quality


def generate_coverage_reports(
    normalized_build: Path,
    *,
    output_directory: Path,
) -> dict[str, Any]:
    """Generate requested coverage reports from one normalized build."""
    output_directory.mkdir(parents=True, exist_ok=True)
    games = prepare_game_quality(normalized_build)
    matches = read_parquet(normalized_build / "matches.parquet")
    year_values = games["start_time_utc"].dt.year.astype("Int64").astype("string")
    dimensions = {
        "year": year_values,
        "patch": games["patch"],
        "tier": games["liquipedia_tier"],
        "tournament": games["tournament"],
    }
    output_files: dict[str, str] = {}
    for name, values in dimensions.items():
        frame = aggregate_dimension(games, dimension=name, values=values)
        path = output_directory / f"coverage_by_{name}.parquet"
        write_parquet(frame, path)
        output_files[f"coverage_by_{name}"] = path.name

    failure = (
        games.assign(
            eligibility_failure=games["exclusion_reason"].fillna("<trainable>")
        )
        .groupby("eligibility_failure", dropna=False, sort=True)
        .size()
        .rename("game_count")
        .reset_index()
    )
    failure["eligibility_failure"] = failure[
        "eligibility_failure"
    ].astype("string")
    failure["game_count"] = failure["game_count"].astype("Int64")
    failure_path = output_directory / "eligibility_failures.parquet"
    write_parquet(failure, failure_path)
    output_files["eligibility_failures"] = failure_path.name

    total_games = len(games)
    trainable_games = int(games["is_trainable_draft"].sum())
    total_matches = len(matches)
    matches_with_games = int(games["source_match_id"].nunique())
    summary = {
        "normalized_build": str(normalized_build.resolve()),
        "match_count": total_matches,
        "matches_with_games": matches_with_games,
        "matches_without_games": total_matches - matches_with_games,
        "game_count": total_games,
        "trainable_game_count": trainable_games,
        "trainable_game_pct": (
            round(trainable_games / total_games * 100, 6)
            if total_games
            else 0.0
        ),
        "winner_known_count": int(games["winner_known"].sum()),
        "sides_known_count": int(games["sides_known"].sum()),
        "complete_picks_count": int(games["complete_picks"].sum()),
        "complete_bans_count": int(games["complete_bans"].sum()),
        "patch_known_count": int(games["patch_known"].sum()),
        "eligibility_failures": {
            str(row["eligibility_failure"]): int(row["game_count"])
            for _, row in failure.iterrows()
        },
        "files": output_files,
    }
    (output_directory / "coverage_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown = [
        "# Historical Dataset Coverage",
        "",
        f"- Matches: **{summary['match_count']}**",
        f"- Matches represented by games: **{summary['matches_with_games']}**",
        f"- Matches without game objects: **{summary['matches_without_games']}**",
        f"- Games: **{total_games}**",
        f"- Trainable draft games: **{trainable_games}**",
        f"- Trainable percentage: **{summary['trainable_game_pct']}%**",
        f"- Known winners: **{summary['winner_known_count']}**",
        f"- Known sides: **{summary['sides_known_count']}**",
        f"- Complete pick sets: **{summary['complete_picks_count']}**",
        f"- Complete ban sets: **{summary['complete_bans_count']}**",
        f"- Known patches: **{summary['patch_known_count']}**",
        "",
        "## Eligibility Outcomes",
        "",
    ]
    markdown.extend(
        f"- `{reason}`: {count}"
        for reason, count in summary["eligibility_failures"].items()
    )
    (output_directory / "coverage_summary.md").write_text(
        "\n".join(markdown) + "\n",
        encoding="utf-8",
    )
    return summary
