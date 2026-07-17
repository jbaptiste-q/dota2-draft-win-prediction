"""Create the reproducible, leakage-aware 30,000-match sample.

The workflow reads the raw Kaggle Parquet file, deduplicates matches, removes
rows without a valid winner or complete draft, and selects matches
deterministically.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import duckdb


ROOT = Path(__file__).resolve().parents[1]
RAW_MATCHES = ROOT / "data" / "raw" / "dota2_matches.parquet"
VERSIONS = ROOT / "data" / "raw" / "dota2_versions.csv"
OUTPUT = ROOT / "data" / "processed" / "dota2_matches_sample_30000.csv"
METADATA = ROOT / "data" / "processed" / "sample_metadata.json"
INVENTORY = ROOT / "docs" / "column_inventory.csv"
SAMPLE_SIZE = 30_000


def sql_path(path: Path) -> str:
    """Return a safely quoted SQL string literal for a local path."""
    return "'" + str(path).replace("'", "''") + "'"


def classify_column(column: str) -> tuple[str, str, str]:
    """Assign each raw column a project role and concise rationale."""
    if column == "winner_id":
        return (
            "target source",
            "target_derivation_only",
            "Directly identifies the winner; use it only to create radiant_win, then remove it.",
        )
    if column in {"radiant_team_id", "dire_team_id"}:
        return (
            "target mapping",
            "target_derivation_only",
            "Needed to map winner_id to Radiant or Dire; excluded from the draft-only model.",
        )
    if column == "match_id":
        return (
            "identifier",
            "tracking_only",
            "Useful for deduplication and tracing a row, but an arbitrary ID is not a feature.",
        )
    if column == "match_start_date_time":
        return (
            "time",
            "split_only",
            "Use for the chronological split, not as a direct model feature.",
        )
    if column == "game_version_id":
        return (
            "pre-match context",
            "use_feature",
            "The game patch is known before the match and changes hero balance.",
        )
    if column.endswith("_hero_id"):
        return (
            "draft",
            "use_feature",
            "The selected hero is known when the draft ends and is a primary model input.",
        )
    if column.endswith("_hero"):
        return (
            "draft label",
            "display_only",
            "Human-readable duplicate of hero_id; keep for inspection, not as a second model feature.",
        )
    if column in {
        "match_duration_seconds",
        "first_blood_time_seconds",
        "radiant_kills",
        "dire_kills",
    } or column.endswith(("_kills", "_deaths", "_assists", "_networth")):
        return (
            "post-match result",
            "exclude_leakage",
            "Created during or after the match and would reveal information unavailable at draft time.",
        )
    if column.endswith(("_position", "_lane", "_role")):
        return (
            "role assignment",
            "exclude_leakage_risk",
            "May be assigned or inferred using match play; exclude until its timestamp and origin are verified.",
        )
    if "player_" in column and column.endswith(("_id", "_name")):
        return (
            "player identity",
            "exclude_scope",
            "Potentially known before the match, but high-cardinality identity features complicate a simple draft model.",
        )
    if column in {"radiant_team_name", "dire_team_name"}:
        return (
            "team identity",
            "exclude_scope",
            "Known before the match, but excluded so the baseline measures draft information rather than team reputation.",
        )
    if column.startswith("league_") or column in {
        "league",
        "series_id",
        "series_type",
    }:
        return (
            "competition metadata",
            "exclude_scope",
            "Mostly available before the match, but not necessary for the smallest useful draft-only baseline.",
        )
    return (
        "other",
        "review_before_use",
        "Outside the baseline scope; verify availability before considering it as a feature.",
    )


def create_sample(connection: duckdb.DuckDBPyConnection) -> None:
    hero_id_list = ", ".join(
        f"{side}_player_{slot}_hero_id"
        for side in ("radiant", "dire")
        for slot in range(1, 6)
    )
    hero_complete = " AND ".join(
        (
            f"{side}_player_{slot}_hero_id > 0 AND "
            f"{side}_player_{slot}_hero IS NOT NULL"
        )
        for side in ("radiant", "dire")
        for slot in range(1, 6)
    )
    hero_columns = ",\n                ".join(
        f"m.{side}_player_{slot}_hero_id, m.{side}_player_{slot}_hero"
        for side in ("radiant", "dire")
        for slot in range(1, 6)
    )

    query = f"""
        COPY (
            WITH eligible AS (
                SELECT
                    *,
                    ROW_NUMBER() OVER (
                        PARTITION BY match_id
                        ORDER BY match_start_date_time DESC, game_version_id DESC NULLS LAST
                    ) AS duplicate_rank
                FROM read_parquet({sql_path(RAW_MATCHES)})
                WHERE winner_id IN (radiant_team_id, dire_team_id)
                  AND game_version_id IS NOT NULL
                  AND {hero_complete}
                  AND list_unique([{hero_id_list}]) = 10
            ),
            selected_ids AS (
                SELECT match_id
                FROM eligible
                WHERE duplicate_rank = 1
                ORDER BY md5(CAST(match_id AS VARCHAR))
                LIMIT {SAMPLE_SIZE}
            )
            SELECT
                m.match_id,
                m.match_start_date_time,
                m.game_version_id,
                v.name AS game_version,
                {hero_columns},
                CASE
                    WHEN m.winner_id = m.radiant_team_id THEN TRUE
                    WHEN m.winner_id = m.dire_team_id THEN FALSE
                END AS radiant_win
            FROM eligible AS m
            INNER JOIN selected_ids USING (match_id)
            LEFT JOIN read_csv_auto({sql_path(VERSIONS)}) AS v
                ON m.game_version_id = v.id
            WHERE m.duplicate_rank = 1
            ORDER BY m.match_start_date_time, m.match_id
        ) TO {sql_path(OUTPUT)} (HEADER, DELIMITER ',', QUOTE '"', ESCAPE '"')
    """
    connection.execute(query)


def create_inventory(connection: duckdb.DuckDBPyConnection) -> None:
    schema = connection.execute(
        f"DESCRIBE SELECT * FROM read_parquet({sql_path(RAW_MATCHES)})"
    ).fetchall()
    columns = [row[0] for row in schema]
    null_expressions = ", ".join(
        f'SUM(CASE WHEN "{column}" IS NULL THEN 1 ELSE 0 END)'
        for column in columns
    )
    null_counts = connection.execute(
        f"SELECT {null_expressions} FROM read_parquet({sql_path(RAW_MATCHES)})"
    ).fetchone()
    total_rows = connection.execute(
        f"SELECT COUNT(*) FROM read_parquet({sql_path(RAW_MATCHES)})"
    ).fetchone()[0]

    with INVENTORY.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "column",
                "duckdb_type",
                "null_count",
                "null_percent",
                "column_group",
                "v1_decision",
                "reason",
            ]
        )
        for schema_row, null_count in zip(schema, null_counts):
            column, data_type = schema_row[0], schema_row[1]
            group, decision, reason = classify_column(column)
            writer.writerow(
                [
                    column,
                    data_type,
                    null_count,
                    round(100 * null_count / total_rows, 2),
                    group,
                    decision,
                    reason,
                ]
            )


def create_metadata(connection: duckdb.DuckDBPyConnection) -> None:
    raw_stats = connection.execute(
        f"""
        SELECT
            COUNT(*) AS row_count,
            COUNT(DISTINCT match_id) AS unique_match_count,
            MIN(match_start_date_time) AS min_match_time,
            MAX(match_start_date_time) AS max_match_time
        FROM read_parquet({sql_path(RAW_MATCHES)})
        """
    ).fetchone()
    sample_stats = connection.execute(
        f"""
        SELECT
            COUNT(*) AS row_count,
            COUNT(DISTINCT match_id) AS unique_match_count,
            MIN(match_start_date_time) AS min_match_time,
            MAX(match_start_date_time) AS max_match_time,
            AVG(CAST(radiant_win AS INTEGER)) AS radiant_win_rate
        FROM read_csv_auto({sql_path(OUTPUT)})
        """
    ).fetchone()
    header = next(csv.reader(OUTPUT.open(encoding="utf-8")))
    checksum = hashlib.sha256(OUTPUT.read_bytes()).hexdigest()

    metadata = {
        "source": {
            "kaggle_dataset": "darianogina/dota-2-matches-pro-leagues",
            "url": "https://www.kaggle.com/datasets/darianogina/dota-2-matches-pro-leagues",
            "raw_rows": raw_stats[0],
            "raw_unique_matches": raw_stats[1],
            "raw_date_min": str(raw_stats[2]),
            "raw_date_max": str(raw_stats[3]),
        },
        "sample": {
            "requested_rows": SAMPLE_SIZE,
            "actual_rows": sample_stats[0],
            "unique_matches": sample_stats[1],
            "date_min": str(sample_stats[2]),
            "date_max": str(sample_stats[3]),
            "radiant_win_rate": round(float(sample_stats[4]), 6),
            "sha256": checksum,
            "columns": header,
        },
        "selection": {
            "deduplication": "Keep one row per match_id.",
            "eligibility": "Valid winner, non-null patch ID, and ten distinct positive hero IDs with names.",
            "sampling": "Take the first 30,000 matches after ordering by md5(match_id).",
            "output_order": "Sort selected rows chronologically by match time, then match_id.",
        },
    }
    METADATA.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    missing = [path for path in (RAW_MATCHES, VERSIONS) if not path.exists()]
    if missing:
        missing_text = ", ".join(str(path) for path in missing)
        raise FileNotFoundError(f"Missing source file(s): {missing_text}")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    INVENTORY.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    try:
        create_sample(connection)
        create_inventory(connection)
        create_metadata(connection)
    finally:
        connection.close()

    print(f"Created {OUTPUT.relative_to(ROOT)}")
    print(f"Created {METADATA.relative_to(ROOT)}")
    print(f"Created {INVENTORY.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
