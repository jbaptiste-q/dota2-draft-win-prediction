"""Deterministic deduplication and assembly of accepted raw API pages."""

from __future__ import annotations

import hashlib
import json
import platform
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import duckdb
import pandas as pd

from .cache import sha256_bytes
from .config import canonical_json
from .contract import ACQUISITION_VERSION


class AssemblyError(ValueError):
    """Raised when accepted page artifacts cannot form a valid snapshot."""


def decode_json_containers(value: Any) -> Any:
    """Recursively decode JSON-encoded containers without changing scalars."""
    if isinstance(value, str):
        stripped = value.strip()
        if (
            len(stripped) >= 2
            and stripped[0] in "[{"
            and stripped[-1] in "]}"
        ):
            try:
                return decode_json_containers(json.loads(stripped))
            except json.JSONDecodeError:
                return value
        return value
    if isinstance(value, list):
        return [decode_json_containers(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): decode_json_containers(item)
            for key, item in value.items()
        }
    return value


def semantic_sha256(value: Any) -> str:
    """Hash the canonical recursively decoded representation of a value."""
    decoded = decode_json_containers(value)
    return hashlib.sha256(
        canonical_json(decoded).encode("utf-8")
    ).hexdigest()


def source_sha256() -> str:
    """Hash the assembly implementation for snapshot identity."""
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    """Write a deterministic Zstandard-compressed Parquet table."""
    escaped = path.resolve().as_posix().replace("'", "''")
    with duckdb.connect() as connection:
        connection.register("source_frame", frame)
        connection.execute(
            "COPY (SELECT * FROM source_frame) "
            f"TO '{escaped}' "
            "(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000)"
        )


@dataclass(frozen=True, slots=True)
class Occurrence:
    """One record occurrence and its raw-response provenance."""

    match_id: str
    semantic_sha256: str
    source_response_sha256: str
    source_response_path: str
    record_index: int
    record: dict[str, Any]


@dataclass(frozen=True, slots=True)
class AssemblyResult:
    """Paths and counts for one deterministic accepted-record snapshot."""

    build_fingerprint: str
    output_directory: Path
    snapshot_path: Path
    manifest_path: Path
    record_index_path: Path
    game_index_path: Path
    quarantine_path: Path
    accepted_matches: int
    accepted_games: int
    duplicate_matches: int
    duplicate_games: int
    quarantined_matches: int


def page_records(
    response_path: Path,
    *,
    expected_sha256: str,
) -> tuple[list[dict[str, Any]], str]:
    """Load and verify one previously accepted API response."""
    body = response_path.read_bytes()
    actual_sha256 = sha256_bytes(body)
    if actual_sha256 != expected_sha256:
        raise AssemblyError(f"Page checksum mismatch: {response_path}")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AssemblyError(f"Invalid cached JSON: {response_path}") from error
    if not isinstance(payload, dict):
        raise AssemblyError(f"Response root is not an object: {response_path}")
    if payload.get("error"):
        raise AssemblyError(
            f"Accepted response contains API errors: {response_path}"
        )
    records = payload.get("result")
    if not isinstance(records, list):
        raise AssemblyError(
            f"Accepted response result is not an array: {response_path}"
        )
    dictionaries = [item for item in records if isinstance(item, dict)]
    if len(dictionaries) != len(records):
        raise AssemblyError(
            f"Accepted response contains non-object records: {response_path}"
        )
    return dictionaries, actual_sha256


def decoded_games(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Return source games as a deterministic decoded list."""
    value = decode_json_containers(record.get("match2games", []))
    if value in (None, ""):
        return []
    if isinstance(value, dict):
        value = [
            value[key]
            for key in sorted(value, key=lambda item: str(item))
        ]
    if not isinstance(value, list) or any(
        not isinstance(item, dict) for item in value
    ):
        raise AssemblyError("match2games must contain an array of objects.")
    return value


def deduplicate_games(
    record: dict[str, Any],
    *,
    match_id: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], int]:
    """Deduplicate exact game IDs and reject conflicting game versions."""
    games = decoded_games(record)
    accepted: list[dict[str, Any]] = []
    by_game_id: dict[str, tuple[str, dict[str, Any]]] = {}
    duplicate_count = 0
    game_index: list[dict[str, Any]] = []

    for index, game in enumerate(games):
        game_hash = semantic_sha256(game)
        raw_game_id = game.get("match2gameid")
        game_id = (
            str(raw_game_id).strip()
            if raw_game_id not in (None, "")
            else None
        )
        if game_id is not None:
            existing = by_game_id.get(game_id)
            if existing is not None:
                if existing[0] != game_hash:
                    raise AssemblyError(
                        f"Conflicting game versions for {match_id}/{game_id}."
                    )
                duplicate_count += 1
                continue
            by_game_id[game_id] = (game_hash, game)
            lineage_key = f"{match_id}:{game_id}"
        else:
            lineage_key = f"{match_id}:index:{index}:sha256:{game_hash}"

        accepted.append(game)
        game_index.append(
            {
                "match2id": match_id,
                "match2gameid": game_id,
                "game_index": index,
                "lineage_key": lineage_key,
                "game_payload_sha256": game_hash,
                "source_game_id_missing": game_id is None,
            }
        )

    normalized_record = dict(decode_json_containers(record))
    normalized_record["match2games"] = accepted
    return normalized_record, game_index, duplicate_count


def assemble_snapshot(
    pages: Iterable[dict[str, Any]],
    *,
    config_hash: str,
    output_root: Path,
    request_count: int,
    cache_hit_count: int,
) -> AssemblyResult:
    """Build a content-addressed, conflict-aware snapshot from cached pages."""
    page_entries = sorted(
        pages,
        key=lambda item: (
            int(item["sequence"]),
            str(item["response_sha256"]),
        ),
    )
    occurrences: dict[str, list[Occurrence]] = {}
    quarantine: list[dict[str, Any]] = []
    raw_page_hashes: list[str] = []

    for page in page_entries:
        path = Path(str(page["response_path"]))
        records, response_sha = page_records(
            path,
            expected_sha256=str(page["response_sha256"]),
        )
        raw_page_hashes.append(response_sha)
        for index, raw_record in enumerate(records):
            decoded = decode_json_containers(raw_record)
            if not isinstance(decoded, dict):
                quarantine.append(
                    {
                        "reason": "record_not_object",
                        "source_response_sha256": response_sha,
                        "record_index": index,
                    }
                )
                continue
            raw_match_id = decoded.get("match2id")
            if raw_match_id in (None, ""):
                quarantine.append(
                    {
                        "reason": "missing_match2id",
                        "source_response_sha256": response_sha,
                        "record_index": index,
                        "record_payload_sha256": semantic_sha256(decoded),
                    }
                )
                continue
            match_id = str(raw_match_id).strip()
            occurrence = Occurrence(
                match_id=match_id,
                semantic_sha256=semantic_sha256(decoded),
                source_response_sha256=response_sha,
                source_response_path=str(path.resolve()),
                record_index=index,
                record=decoded,
            )
            occurrences.setdefault(match_id, []).append(occurrence)

    accepted_records: list[dict[str, Any]] = []
    record_index_rows: list[dict[str, Any]] = []
    game_index_rows: list[dict[str, Any]] = []
    duplicate_matches = 0
    duplicate_games = 0

    for match_id in sorted(occurrences):
        versions = occurrences[match_id]
        hashes = sorted({item.semantic_sha256 for item in versions})
        sources = sorted(
            {
                item.source_response_sha256
                for item in versions
            }
        )
        if len(hashes) != 1:
            quarantine.append(
                {
                    "reason": "conflicting_match_versions",
                    "match2id": match_id,
                    "record_payload_sha256_values": hashes,
                    "source_response_sha256_values": sources,
                }
            )
            record_index_rows.append(
                {
                    "match2id": match_id,
                    "record_payload_sha256": None,
                    "source_response_sha256": None,
                    "occurrence_count": len(versions),
                    "status": "quarantined_conflict",
                }
            )
            continue

        duplicate_matches += len(versions) - 1
        selected = min(
            versions,
            key=lambda item: (
                item.source_response_sha256,
                item.record_index,
            ),
        )
        try:
            record, games, removed_games = deduplicate_games(
                selected.record,
                match_id=match_id,
            )
        except AssemblyError as error:
            quarantine.append(
                {
                    "reason": "conflicting_or_invalid_games",
                    "match2id": match_id,
                    "detail": str(error),
                    "record_payload_sha256": selected.semantic_sha256,
                    "source_response_sha256_values": sources,
                }
            )
            record_index_rows.append(
                {
                    "match2id": match_id,
                    "record_payload_sha256": selected.semantic_sha256,
                    "source_response_sha256": selected.source_response_sha256,
                    "occurrence_count": len(versions),
                    "status": "quarantined_games",
                }
            )
            continue

        duplicate_games += removed_games
        accepted_records.append(record)
        game_index_rows.extend(games)
        record_index_rows.append(
            {
                "match2id": match_id,
                "record_payload_sha256": selected.semantic_sha256,
                "source_response_sha256": selected.source_response_sha256,
                "occurrence_count": len(versions),
                "status": "accepted",
            }
        )

    identity = {
        "acquisition_version": ACQUISITION_VERSION,
        "config_hash": config_hash,
        "raw_response_sha256": sorted(raw_page_hashes),
        "assembly_source_sha256": source_sha256(),
        "accepted_record_sha256": sorted(
            semantic_sha256(record)
            for record in accepted_records
        ),
    }
    fingerprint = hashlib.sha256(
        canonical_json(identity).encode("utf-8")
    ).hexdigest()
    target = output_root.resolve() / f"build_{fingerprint[:16]}"
    existing_manifest = target / "manifest.json"
    if existing_manifest.is_file():
        existing = json.loads(existing_manifest.read_text(encoding="utf-8"))
        if existing.get("build_fingerprint") != fingerprint:
            raise AssemblyError(f"Assembly manifest mismatch: {target}")
        return AssemblyResult(
            build_fingerprint=fingerprint,
            output_directory=target,
            snapshot_path=target / "snapshot.json",
            manifest_path=existing_manifest,
            record_index_path=target / "record_index.parquet",
            game_index_path=target / "game_index.parquet",
            quarantine_path=target / "quarantine.jsonl",
            accepted_matches=int(existing["counts"]["accepted_matches"]),
            accepted_games=int(existing["counts"]["accepted_games"]),
            duplicate_matches=int(existing["counts"]["duplicate_matches"]),
            duplicate_games=int(existing["counts"]["duplicate_games"]),
            quarantined_matches=int(existing["counts"]["quarantined_records"]),
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".assembly-",
        dir=target.parent,
    ) as temporary:
        staging = Path(temporary)
        snapshot_path = staging / "snapshot.json"
        snapshot_path.write_text(
            json.dumps(
                {"result": accepted_records, "error": []},
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        record_index_frame = pd.DataFrame(
            record_index_rows,
            columns=(
                "match2id",
                "record_payload_sha256",
                "source_response_sha256",
                "occurrence_count",
                "status",
            ),
        ).sort_values("match2id", kind="mergesort").reset_index(drop=True)
        game_index_frame = pd.DataFrame(
            game_index_rows,
            columns=(
                "match2id",
                "match2gameid",
                "game_index",
                "lineage_key",
                "game_payload_sha256",
                "source_game_id_missing",
            ),
        )
        if not game_index_frame.empty:
            game_index_frame = game_index_frame.sort_values(
                ["match2id", "game_index"],
                kind="mergesort",
            ).reset_index(drop=True)
        write_parquet(record_index_frame, staging / "record_index.parquet")
        write_parquet(game_index_frame, staging / "game_index.parquet")
        (staging / "quarantine.jsonl").write_text(
            "".join(
                json.dumps(item, sort_keys=True, ensure_ascii=False) + "\n"
                for item in quarantine
            ),
            encoding="utf-8",
        )
        manifest = {
            "build_fingerprint": fingerprint,
            "acquisition_version": ACQUISITION_VERSION,
            "config_hash": config_hash,
            "assembly_source_sha256": source_sha256(),
            "runtime_versions": {
                "python": platform.python_version(),
                "pandas": pd.__version__,
                "duckdb": duckdb.__version__,
            },
            "request_count": request_count,
            "cache_hit_count": cache_hit_count,
            "raw_response_sha256": sorted(raw_page_hashes),
            "snapshot_file": "snapshot.json",
            "snapshot_sha256": sha256_bytes(snapshot_path.read_bytes()),
            "record_index_file": "record_index.parquet",
            "game_index_file": "game_index.parquet",
            "quarantine_file": "quarantine.jsonl",
            "counts": {
                "raw_pages": len(page_entries),
                "record_occurrences": sum(
                    len(items) for items in occurrences.values()
                ),
                "accepted_matches": len(accepted_records),
                "accepted_games": len(game_index_rows),
                "duplicate_matches": duplicate_matches,
                "duplicate_games": duplicate_games,
                "quarantined_records": len(quarantine),
            },
        }
        (staging / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        staging.rename(target)

    return AssemblyResult(
        build_fingerprint=fingerprint,
        output_directory=target,
        snapshot_path=target / "snapshot.json",
        manifest_path=target / "manifest.json",
        record_index_path=target / "record_index.parquet",
        game_index_path=target / "game_index.parquet",
        quarantine_path=target / "quarantine.jsonl",
        accepted_matches=len(accepted_records),
        accepted_games=len(game_index_rows),
        duplicate_matches=duplicate_matches,
        duplicate_games=duplicate_games,
        quarantined_matches=len(quarantine),
    )
