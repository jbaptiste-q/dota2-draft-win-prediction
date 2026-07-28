"""Build a canonical supervised draft dataset from normalized Parquet only."""

from __future__ import annotations

import hashlib
import json
import platform
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

import duckdb
import pandas as pd

from .schema import (
    DIRE_BAN_COLUMNS,
    DIRE_PICK_COLUMNS,
    DRAFT_FEATURE_COLUMNS,
    FORBIDDEN_COLUMNS,
    RADIANT_BAN_COLUMNS,
    RADIANT_PICK_COLUMNS,
    SCHEMA_VERSION,
    TRAINING_COLUMNS,
    schema_payload,
)


BUILDER_VERSION = "3.0.0"
REQUIRED_NORMALIZED_TABLES = (
    "matches",
    "match_teams",
    "games",
    "heroes",
    "draft_picks",
    "draft_bans",
)


class TrainingDatasetError(ValueError):
    """Raised when normalized inputs violate the supervised contract."""


def canonical_json(value: object) -> str:
    """Return a deterministic JSON encoding."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def sha256_file(path: Path) -> str:
    """Calculate a streaming SHA-256 checksum."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package_source_sha256() -> str:
    """Hash this independent supervised-dataset implementation."""
    root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for path in sorted(root.glob("*.py")):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    """Write deterministic compressed Parquet without a PyArrow dependency."""
    escaped = path.resolve().as_posix().replace("'", "''")
    with duckdb.connect() as connection:
        connection.register("source_frame", frame)
        connection.execute(
            "COPY (SELECT * FROM source_frame) "
            f"TO '{escaped}' "
            "(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000)"
        )


def read_parquet(path: Path) -> pd.DataFrame:
    """Read a normalized table without importing upstream implementation."""
    with duckdb.connect() as connection:
        return connection.execute(
            "SELECT * FROM read_parquet(?)",
            [str(path.resolve())],
        ).fetchdf()


def normalize_filter(values: Iterable[str]) -> tuple[str, ...]:
    """Return stable, non-empty exact-match filter values."""
    return tuple(sorted({value.strip() for value in values if value.strip()}))


@dataclass(frozen=True, slots=True)
class TrainingDatasetConfig:
    """Filters and output location for one canonical supervised build."""

    normalized_build: Path
    output_root: Path = Path("data/training/dota_draft_supervised")
    start_utc: datetime | None = None
    end_utc: datetime | None = None
    tiers: tuple[str, ...] = ()
    patches: tuple[str, ...] = ()
    tournaments: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        start = self.start_utc
        end = self.end_utc
        if start is not None:
            if start.tzinfo is None:
                raise ValueError("Training start timestamp must be timezone-aware.")
            start = start.astimezone(UTC)
        if end is not None:
            if end.tzinfo is None:
                raise ValueError("Training end timestamp must be timezone-aware.")
            end = end.astimezone(UTC)
        if start is not None and end is not None and start >= end:
            raise ValueError("Training start must be earlier than end.")
        object.__setattr__(self, "start_utc", start)
        object.__setattr__(self, "end_utc", end)
        object.__setattr__(self, "tiers", normalize_filter(self.tiers))
        object.__setattr__(self, "patches", normalize_filter(self.patches))
        object.__setattr__(
            self,
            "tournaments",
            normalize_filter(self.tournaments),
        )

    def filter_payload(self) -> dict[str, object]:
        """Return path-independent supervised row-selection rules."""
        return {
            "start_utc": self.start_utc.isoformat() if self.start_utc else None,
            "end_utc": self.end_utc.isoformat() if self.end_utc else None,
            "tiers": list(self.tiers),
            "patches": list(self.patches),
            "tournaments": list(self.tournaments),
        }


@dataclass(frozen=True, slots=True)
class TrainingBuildResult:
    """Identity and artifacts of one canonical supervised dataset."""

    build_fingerprint: str
    output_directory: Path
    training_path: Path
    exclusions_path: Path
    vocabulary_path: Path
    schema_path: Path
    manifest_path: Path
    quality_report_path: Path
    data_card_path: Path
    training_rows: int
    excluded_rows: int


def load_normalized_manifest(
    normalized_build: Path,
) -> tuple[dict[str, Any], dict[str, Path]]:
    """Verify the normalized manifest and required input table checksums."""
    root = normalized_build.resolve()
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(
            f"Normalized manifest not found: {manifest_path}"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    table_entries = {
        str(table["name"]): table
        for table in manifest.get("tables", [])
    }
    missing = [
        table
        for table in REQUIRED_NORMALIZED_TABLES
        if table not in table_entries
    ]
    if missing:
        raise TrainingDatasetError(
            "Normalized build is missing required tables: "
            + ", ".join(missing)
        )
    paths: dict[str, Path] = {}
    for name in REQUIRED_NORMALIZED_TABLES:
        entry = table_entries[name]
        path = root / str(entry["parquet_file"])
        if not path.is_file():
            raise FileNotFoundError(f"Normalized table not found: {path}")
        actual = sha256_file(path)
        if actual != entry["parquet_sha256"]:
            raise TrainingDatasetError(
                f"Normalized table checksum mismatch: {path}"
            )
        paths[name] = path
    return manifest, paths


def apply_scope(
    games: pd.DataFrame,
    config: TrainingDatasetConfig,
) -> pd.DataFrame:
    """Apply deterministic temporal and exact categorical filters."""
    scoped = games.copy()
    scoped["start_time_utc"] = pd.to_datetime(
        scoped["start_time_utc"],
        utc=True,
    )
    if config.start_utc is not None:
        scoped = scoped[scoped["start_time_utc"] >= config.start_utc]
    if config.end_utc is not None:
        scoped = scoped[scoped["start_time_utc"] < config.end_utc]
    if config.tiers:
        scoped = scoped[
            scoped["liquipedia_tier"].astype("string").isin(config.tiers)
        ]
    if config.patches:
        scoped = scoped[
            scoped["patch"].astype("string").isin(config.patches)
        ]
    if config.tournaments:
        scoped = scoped[
            scoped["tournament"].astype("string").isin(config.tournaments)
        ]
    return scoped.sort_values(
        ["start_time_utc", "source_match_id", "game_index"],
        kind="mergesort",
        na_position="last",
    ).reset_index(drop=True)


def index_drafts(frame: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
    """Index long-form normalized draft values by stable game key."""
    result: dict[str, list[dict[str, Any]]] = {}
    for row in frame.to_dict(orient="records"):
        result.setdefault(str(row["game_key"]), []).append(row)
    for values in result.values():
        values.sort(
            key=lambda item: (
                int(item["team_slot"]),
                int(item["slot"]),
            )
        )
    return result


def draft_slots(
    values: list[dict[str, Any]],
    *,
    expected_slots: range,
    game_key: str,
    kind: str,
) -> dict[int, dict[int, str]]:
    """Validate exact per-team slots and return normalized hero keys."""
    by_team: dict[int, dict[int, str]] = {1: {}, 2: {}}
    for value in values:
        team_slot = int(value["team_slot"])
        slot = int(value["slot"])
        if team_slot not in by_team:
            raise TrainingDatasetError(
                f"Unsupported team slot in {kind} for {game_key}: {team_slot}."
            )
        if slot in by_team[team_slot]:
            raise TrainingDatasetError(
                f"Duplicate {kind} slot for {game_key}: {team_slot}/{slot}."
            )
        by_team[team_slot][slot] = str(value["hero_key"])
    expected = set(expected_slots)
    for team_slot, slots in by_team.items():
        if set(slots) != expected:
            raise TrainingDatasetError(
                f"Incomplete {kind} slots for {game_key}/team{team_slot}."
            )
    return by_team


def typed_training_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Construct the stable supervised frame and enforce its exact schema."""
    frame = pd.DataFrame(rows, columns=TRAINING_COLUMNS)
    string_columns = [
        column
        for column in TRAINING_COLUMNS
        if column not in {"game_index", "match_start_utc", "radiant_win"}
    ]
    frame[string_columns] = frame[string_columns].astype("string")
    frame["game_index"] = frame["game_index"].astype("Int64")
    frame["match_start_utc"] = pd.to_datetime(
        frame["match_start_utc"],
        utc=True,
    ).astype("datetime64[us, UTC]")
    frame["radiant_win"] = frame["radiant_win"].astype("boolean")
    if not frame.empty:
        frame = frame.sort_values(
            ["match_start_utc", "source_match_id", "game_index"],
            kind="mergesort",
            na_position="last",
        ).reset_index(drop=True)
    return frame


def build_frames(
    config: TrainingDatasetConfig,
    table_paths: dict[str, Path],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Build training, exclusion, and observed-vocabulary tables."""
    matches = read_parquet(table_paths["matches"])
    teams = read_parquet(table_paths["match_teams"])
    games = read_parquet(table_paths["games"])
    heroes = read_parquet(table_paths["heroes"])
    picks = read_parquet(table_paths["draft_picks"])
    bans = read_parquet(table_paths["draft_bans"])

    matches_context = matches[
        [
            "source_match_id",
            "liquipedia_tier",
            "tournament",
            "series",
        ]
    ].drop_duplicates("source_match_id")
    game_context = games.merge(
        matches_context,
        on="source_match_id",
        how="left",
        validate="many_to_one",
    )
    scoped = apply_scope(game_context, config)
    validate_required_gameplay_metadata(scoped)
    scoped_keys = set(scoped["game_key"].astype(str))
    pick_scope = picks[picks["game_key"].astype(str).isin(scoped_keys)]
    ban_scope = bans[bans["game_key"].astype(str).isin(scoped_keys)]
    picks_by_game = index_drafts(pick_scope)
    bans_by_game = index_drafts(ban_scope)
    team_keys = {
        (str(row["source_match_id"]), int(row["team_slot"])): (
            None if pd.isna(row["team_key"]) else str(row["team_key"])
        )
        for row in teams.to_dict(orient="records")
    }

    training_rows: list[dict[str, Any]] = []
    for game in scoped[scoped["is_trainable_draft"]].to_dict(orient="records"):
        game_key = str(game["game_key"])
        pick_slots = draft_slots(
            picks_by_game.get(game_key, []),
            expected_slots=range(1, 6),
            game_key=game_key,
            kind="pick",
        )
        ban_slots = draft_slots(
            bans_by_game.get(game_key, []),
            expected_slots=range(1, 8),
            game_key=game_key,
            kind="ban",
        )
        team1_side = str(game["team1_side"])
        team2_side = str(game["team2_side"])
        if {team1_side, team2_side} != {"radiant", "dire"}:
            raise TrainingDatasetError(
                f"Trainable game has invalid sides: {game_key}."
            )
        radiant_slot = 1 if team1_side == "radiant" else 2
        dire_slot = 2 if radiant_slot == 1 else 1
        picked_heroes = [
            *pick_slots[radiant_slot].values(),
            *pick_slots[dire_slot].values(),
        ]
        if len(picked_heroes) != len(set(picked_heroes)):
            raise TrainingDatasetError(
                f"Trainable game contains duplicate picked heroes: {game_key}."
            )
        source_game_id = game["source_game_id"]
        row: dict[str, Any] = {
            "sample_id": game_key,
            "game_key": game_key,
            "source_game_id": (
                None if pd.isna(source_game_id) else str(source_game_id)
            ),
            "game_index": int(game["game_index"]),
            "source_match_id": str(game["source_match_id"]),
            "match_start_utc": game["start_time_utc"],
            "patch": None if pd.isna(game["patch"]) else str(game["patch"]),
            "liquipedia_tier": (
                None
                if pd.isna(game["liquipedia_tier"])
                else str(game["liquipedia_tier"])
            ),
            "tournament": (
                None
                if pd.isna(game["tournament"])
                else str(game["tournament"])
            ),
            "series": (
                None if pd.isna(game["series"]) else str(game["series"])
            ),
            "radiant_team_key": team_keys.get(
                (str(game["source_match_id"]), radiant_slot)
            ),
            "dire_team_key": team_keys.get(
                (str(game["source_match_id"]), dire_slot)
            ),
            "radiant_win": int(game["winner_team_slot"]) == radiant_slot,
        }
        for slot, column in enumerate(RADIANT_PICK_COLUMNS, start=1):
            row[column] = pick_slots[radiant_slot][slot]
        for slot, column in enumerate(DIRE_PICK_COLUMNS, start=1):
            row[column] = pick_slots[dire_slot][slot]
        for slot, column in enumerate(RADIANT_BAN_COLUMNS, start=1):
            row[column] = ban_slots[radiant_slot][slot]
        for slot, column in enumerate(DIRE_BAN_COLUMNS, start=1):
            row[column] = ban_slots[dire_slot][slot]
        training_rows.append(row)

    training = typed_training_frame(training_rows)
    pick_counts = pick_scope.groupby("game_key").size()
    ban_counts = ban_scope.groupby("game_key").size()
    excluded_source = scoped[~scoped["is_trainable_draft"]].copy()
    exclusions = pd.DataFrame(
        {
            "game_key": excluded_source["game_key"],
            "source_match_id": excluded_source["source_match_id"],
            "source_game_id": excluded_source["source_game_id"],
            "game_index": excluded_source["game_index"],
            "match_start_utc": excluded_source["start_time_utc"],
            "patch": excluded_source["patch"],
            "liquipedia_tier": excluded_source["liquipedia_tier"],
            "tournament": excluded_source["tournament"],
            "exclusion_reason": excluded_source["exclusion_reason"],
            "winner_available": excluded_source["winner_team_slot"].isin([1, 2]),
            "sides_available": (
                excluded_source["team1_side"].isin(["radiant", "dire"])
                & excluded_source["team2_side"].isin(["radiant", "dire"])
                & excluded_source["team1_side"].ne(
                    excluded_source["team2_side"]
                )
            ),
            "observed_pick_count": (
                excluded_source["game_key"].map(pick_counts).fillna(0)
            ),
            "observed_ban_count": (
                excluded_source["game_key"].map(ban_counts).fillna(0)
            ),
        }
    )
    for column in (
        "game_key",
        "source_match_id",
        "source_game_id",
        "patch",
        "liquipedia_tier",
        "tournament",
        "exclusion_reason",
    ):
        exclusions[column] = exclusions[column].astype("string")
    for column in ("game_index", "observed_pick_count", "observed_ban_count"):
        exclusions[column] = exclusions[column].astype("Int64")
    for column in ("winner_available", "sides_available"):
        exclusions[column] = exclusions[column].astype("boolean")
    exclusions["match_start_utc"] = pd.to_datetime(
        exclusions["match_start_utc"],
        utc=True,
    ).astype("datetime64[us, UTC]")
    if not exclusions.empty:
        exclusions = exclusions.sort_values(
            ["match_start_utc", "source_match_id", "game_index"],
            kind="mergesort",
            na_position="last",
        ).reset_index(drop=True)

    observed_heroes = {
        str(value)
        for column in DRAFT_FEATURE_COLUMNS
        for value in training[column].dropna().tolist()
    }
    vocabulary = heroes[
        heroes["hero_key"].astype(str).isin(observed_heroes)
    ][["hero_key", "source_name"]].copy()
    vocabulary["hero_key"] = vocabulary["hero_key"].astype("string")
    vocabulary["source_name"] = vocabulary["source_name"].astype("string")
    vocabulary = vocabulary.sort_values(
        ["hero_key", "source_name"],
        kind="mergesort",
    ).reset_index(drop=True)
    return training, exclusions, vocabulary


def validate_required_gameplay_metadata(games: pd.DataFrame) -> None:
    """Reject stale normalized inputs that violate the eligibility contract."""
    trainable = games["is_trainable_draft"].fillna(False).astype(bool)
    invalid = games[trainable & games["duration_seconds"].isna()]
    if invalid.empty:
        return
    game_keys = sorted(invalid["game_key"].astype(str).tolist())
    preview = ", ".join(game_keys[:5])
    raise TrainingDatasetError(
        "Normalized trainable games are missing required duration_seconds: "
        f"{preview}. Rebuild normalized data with the current eligibility "
        "contract."
    )


def validate_training_frame(frame: pd.DataFrame) -> None:
    """Fail fast on schema drift, duplicate samples, or leakage."""
    if tuple(frame.columns) != TRAINING_COLUMNS:
        raise TrainingDatasetError("Training columns do not match schema order.")
    leaked = FORBIDDEN_COLUMNS.intersection(frame.columns)
    if leaked:
        raise TrainingDatasetError(f"Forbidden leakage columns found: {leaked}")
    if frame["sample_id"].duplicated().any():
        raise TrainingDatasetError("Training sample IDs must be unique.")
    if frame[list(DRAFT_FEATURE_COLUMNS)].isna().any().any():
        raise TrainingDatasetError("Draft feature columns must not be null.")
    for _, row in frame.iterrows():
        picked = [
            row[column]
            for column in (*RADIANT_PICK_COLUMNS, *DIRE_PICK_COLUMNS)
        ]
        if len(picked) != len(set(picked)):
            raise TrainingDatasetError(
                f"Duplicate picked hero in sample {row['sample_id']}."
            )


def quality_payload(
    training: pd.DataFrame,
    exclusions: pd.DataFrame,
    vocabulary: pd.DataFrame,
) -> dict[str, Any]:
    """Build deterministic supervised data-quality statistics."""
    target_counts = (
        training["radiant_win"]
        .astype("string")
        .value_counts(dropna=False)
        .sort_index()
    )
    exclusion_counts = (
        exclusions["exclusion_reason"]
        .fillna("<unknown>")
        .value_counts(dropna=False)
        .sort_index()
    )
    return {
        "training_rows": len(training),
        "excluded_rows": len(exclusions),
        "hero_vocabulary_size": len(vocabulary),
        "minimum_match_start_utc": (
            training["match_start_utc"].min().isoformat()
            if not training.empty
            and pd.notna(training["match_start_utc"].min())
            else None
        ),
        "maximum_match_start_utc": (
            training["match_start_utc"].max().isoformat()
            if not training.empty
            and pd.notna(training["match_start_utc"].max())
            else None
        ),
        "target_class_counts": {
            str(key): int(value)
            for key, value in target_counts.items()
        },
        "null_counts": {
            column: int(training[column].isna().sum())
            for column in training.columns
        },
        "exclusion_counts": {
            str(key): int(value)
            for key, value in exclusion_counts.items()
        },
    }


def existing_result(target: Path, fingerprint: str) -> TrainingBuildResult | None:
    """Return a verified existing supervised build when available."""
    manifest_path = target / "manifest.json"
    if not manifest_path.is_file():
        return None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("build_fingerprint") != fingerprint:
        raise TrainingDatasetError(f"Existing manifest mismatch: {target}")
    for artifact in manifest["artifacts"].values():
        path = target / artifact["file"]
        if not path.is_file() or sha256_file(path) != artifact["sha256"]:
            raise TrainingDatasetError(
                f"Existing supervised artifact is incomplete: {path}"
            )
    return TrainingBuildResult(
        build_fingerprint=fingerprint,
        output_directory=target,
        training_path=target / "draft_training_games.parquet",
        exclusions_path=target / "excluded_games.parquet",
        vocabulary_path=target / "hero_vocabulary.parquet",
        schema_path=target / "schema.json",
        manifest_path=manifest_path,
        quality_report_path=target / "quality_report.json",
        data_card_path=target / "data_card.md",
        training_rows=int(manifest["row_counts"]["training"]),
        excluded_rows=int(manifest["row_counts"]["excluded"]),
    )


def build_training_dataset(
    config: TrainingDatasetConfig,
) -> TrainingBuildResult:
    """Build and atomically publish the canonical supervised dataset."""
    normalized_manifest, table_paths = load_normalized_manifest(
        config.normalized_build
    )
    training, exclusions, vocabulary = build_frames(config, table_paths)
    validate_training_frame(training)
    schema = schema_payload()
    quality = quality_payload(training, exclusions, vocabulary)
    identity = {
        "builder_version": BUILDER_VERSION,
        "schema_version": SCHEMA_VERSION,
        "builder_source_sha256": package_source_sha256(),
        "normalized_build_fingerprint": normalized_manifest[
            "build_fingerprint"
        ],
        "filters": config.filter_payload(),
        "ordered_sample_ids": training["sample_id"].astype(str).tolist(),
        "runtime_versions": {
            "python": platform.python_version(),
            "pandas": pd.__version__,
            "duckdb": duckdb.__version__,
        },
    }
    fingerprint = hashlib.sha256(
        canonical_json(identity).encode("utf-8")
    ).hexdigest()
    target = config.output_root.resolve() / f"build_{fingerprint[:16]}"
    cached = existing_result(target, fingerprint)
    if cached is not None:
        return cached

    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".training-dataset-",
        dir=target.parent,
    ) as temporary:
        staging = Path(temporary)
        write_parquet(training, staging / "draft_training_games.parquet")
        write_parquet(exclusions, staging / "excluded_games.parquet")
        write_parquet(vocabulary, staging / "hero_vocabulary.parquet")
        (staging / "schema.json").write_text(
            json.dumps(schema, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (staging / "quality_report.json").write_text(
            json.dumps(quality, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        data_card = [
            "# Canonical Dota 2 Draft Supervised Dataset",
            "",
            f"**Schema:** `{SCHEMA_VERSION}`",
            f"**Normalized source build:** `{normalized_manifest['build_fingerprint']}`",
            f"**Training rows:** `{len(training)}`",
            f"**Excluded rows:** `{len(exclusions)}`",
            "",
            "## Intended Use",
            "",
            "Canonical input for future professional Dota 2 draft outcome models.",
            "No model-specific encoding, splitting, or training is included.",
            "",
            "## Target",
            "",
            "`radiant_win` is derived only from explicit winner and side fields.",
            "",
            "## Known Limitations",
            "",
            "- Draft slots are per-team slots, not a global sequence.",
            "- First-pick information is unavailable and is never inferred.",
            "- Missing patch and team identities remain null.",
            "- Only games passing the strict normalized eligibility gate are included.",
            "",
            "## Source and License",
            "",
            "Source: Liquipedia. Content is subject to CC-BY-SA 3.0 and the ",
            "Liquipedia API Terms of Use.",
        ]
        (staging / "data_card.md").write_text(
            "\n".join(data_card) + "\n",
            encoding="utf-8",
        )
        artifact_names = (
            "draft_training_games.parquet",
            "excluded_games.parquet",
            "hero_vocabulary.parquet",
            "schema.json",
            "quality_report.json",
            "data_card.md",
        )
        artifacts = {
            name.rsplit(".", maxsplit=1)[0]: {
                "file": name,
                "sha256": sha256_file(staging / name),
                "bytes": (staging / name).stat().st_size,
            }
            for name in artifact_names
        }
        manifest = {
            "build_fingerprint": fingerprint,
            "builder_version": BUILDER_VERSION,
            "builder_source_sha256": package_source_sha256(),
            "schema_version": SCHEMA_VERSION,
            "normalized_source": {
                "directory_name": config.normalized_build.resolve().name,
                "build_fingerprint": normalized_manifest[
                    "build_fingerprint"
                ],
                "schema_version": normalized_manifest["schema_version"],
                "verified_table_sha256": {
                    name: sha256_file(path)
                    for name, path in sorted(table_paths.items())
                },
            },
            "filters": config.filter_payload(),
            "runtime_versions": identity["runtime_versions"],
            "row_counts": {
                "training": len(training),
                "excluded": len(exclusions),
                "hero_vocabulary": len(vocabulary),
            },
            "training_columns": list(TRAINING_COLUMNS),
            "quality_report": quality,
            "artifacts": artifacts,
            "source_attribution": {
                "source": "Liquipedia",
                "license": "CC-BY-SA 3.0",
                "terms": "https://liquipedia.net/api-terms-of-use",
            },
        }
        (staging / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        staging.rename(target)

    return TrainingBuildResult(
        build_fingerprint=fingerprint,
        output_directory=target,
        training_path=target / "draft_training_games.parquet",
        exclusions_path=target / "excluded_games.parquet",
        vocabulary_path=target / "hero_vocabulary.parquet",
        schema_path=target / "schema.json",
        manifest_path=target / "manifest.json",
        quality_report_path=target / "quality_report.json",
        data_card_path=target / "data_card.md",
        training_rows=len(training),
        excluded_rows=len(exclusions),
    )
