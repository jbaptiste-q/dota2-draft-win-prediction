"""Deterministic Parquet/CSV export with reproducibility metadata."""

from __future__ import annotations

import hashlib
import json
import platform
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import duckdb
import pandas as pd

from .dataset import SCHEMA_VERSION, DatasetTables
from .models import RawApiDocument


PIPELINE_VERSION = "2.0.0"


@dataclass(frozen=True, slots=True)
class ExportResult:
    """Paths and identity of one reproducible exported dataset."""

    build_fingerprint: str
    output_directory: Path
    manifest_path: Path
    parquet_paths: tuple[Path, ...]
    csv_paths: tuple[Path, ...]


def sha256_file(path: Path) -> str:
    """Calculate a file checksum without loading it all into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pipeline_source_sha256() -> str:
    """Hash pipeline source so code changes produce a new build identity."""
    package_root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for path in sorted(package_root.glob("*.py")):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def runtime_versions() -> dict[str, str]:
    """Return output-affecting runtime versions for build provenance."""
    return {
        "python": platform.python_version(),
        "pandas": pd.__version__,
        "duckdb": duckdb.__version__,
    }


def build_fingerprint(
    documents: Iterable[RawApiDocument],
    *,
    include_csv: bool = False,
) -> str:
    """Create a deterministic identity from inputs, code, and export format."""
    identity = {
        "pipeline_version": PIPELINE_VERSION,
        "schema_version": SCHEMA_VERSION,
        "pipeline_source_sha256": pipeline_source_sha256(),
        "runtime_versions": runtime_versions(),
        "source_sha256": sorted(document.sha256 for document in documents),
        "export_formats": (
            ["csv", "parquet"] if include_csv else ["parquet"]
        ),
    }
    encoded = json.dumps(
        identity,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    """Write one frame with DuckDB's native deterministic Parquet writer."""
    escaped_path = path.as_posix().replace("'", "''")
    connection = duckdb.connect()
    try:
        connection.register("source_frame", frame)
        connection.execute(
            "COPY (SELECT * FROM source_frame) "
            f"TO '{escaped_path}' "
            "(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000)"
        )
    finally:
        connection.close()


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    """Write a stable UTF-8 CSV representation."""
    frame.to_csv(
        path,
        index=False,
        encoding="utf-8",
        lineterminator="\n",
        date_format="%Y-%m-%dT%H:%M:%S.%fZ",
    )


def existing_result(target: Path, fingerprint: str) -> ExportResult | None:
    """Return an existing matching build without rewriting its files."""
    manifest_path = target / "manifest.json"
    if not manifest_path.is_file():
        return None
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if payload.get("build_fingerprint") != fingerprint:
        raise ValueError(f"Existing dataset has a mismatched manifest: {target}")
    parquet_paths = tuple(
        target / table["parquet_file"]
        for table in payload["tables"]
    )
    csv_paths = tuple(
        target / table["csv_file"]
        for table in payload["tables"]
        if table.get("csv_file")
    )
    if not all(path.is_file() for path in (*parquet_paths, *csv_paths)):
        raise ValueError(f"Existing dataset is incomplete: {target}")
    return ExportResult(
        build_fingerprint=fingerprint,
        output_directory=target,
        manifest_path=manifest_path,
        parquet_paths=parquet_paths,
        csv_paths=csv_paths,
    )


def export_dataset(
    tables: DatasetTables,
    *,
    documents: tuple[RawApiDocument, ...],
    output_root: Path,
    include_csv: bool = False,
) -> ExportResult:
    """Atomically export all tables and a deterministic manifest."""
    fingerprint = build_fingerprint(
        documents,
        include_csv=include_csv,
    )
    target = output_root.resolve() / f"build_{fingerprint[:16]}"
    target.parent.mkdir(parents=True, exist_ok=True)
    cached = existing_result(target, fingerprint)
    if cached is not None:
        return cached

    with tempfile.TemporaryDirectory(
        prefix=".liquipedia-build-",
        dir=target.parent,
    ) as temporary:
        staging = Path(temporary)
        table_manifest = []
        parquet_paths: list[Path] = []
        csv_paths: list[Path] = []

        for table_name, frame in tables.ordered():
            parquet_name = f"{table_name}.parquet"
            parquet_path = staging / parquet_name
            write_parquet(frame, parquet_path)
            parquet_paths.append(parquet_path)

            csv_name = None
            csv_sha256 = None
            if include_csv:
                csv_name = f"{table_name}.csv"
                csv_path = staging / csv_name
                write_csv(frame, csv_path)
                csv_paths.append(csv_path)
                csv_sha256 = sha256_file(csv_path)

            table_manifest.append(
                {
                    "name": table_name,
                    "rows": len(frame),
                    "columns": frame.columns.tolist(),
                    "dtypes": {
                        column: str(dtype)
                        for column, dtype in frame.dtypes.items()
                    },
                    "parquet_file": parquet_name,
                    "parquet_sha256": sha256_file(parquet_path),
                    "csv_file": csv_name,
                    "csv_sha256": csv_sha256,
                }
            )

        manifest = {
            "build_fingerprint": fingerprint,
            "pipeline_version": PIPELINE_VERSION,
            "pipeline_source_sha256": pipeline_source_sha256(),
            "runtime_versions": runtime_versions(),
            "schema_version": SCHEMA_VERSION,
            "export_formats": (
                ["csv", "parquet"] if include_csv else ["parquet"]
            ),
            "source_documents": [
                {
                    "filename": document.path.name,
                    "sha256": document.sha256,
                    "bytes": len(document.content),
                }
                for document in documents
            ],
            "tables": table_manifest,
        }
        manifest_path = staging / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                manifest,
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

        staging.rename(target)

    return ExportResult(
        build_fingerprint=fingerprint,
        output_directory=target,
        manifest_path=target / "manifest.json",
        parquet_paths=tuple(target / path.name for path in parquet_paths),
        csv_paths=tuple(target / path.name for path in csv_paths),
    )
