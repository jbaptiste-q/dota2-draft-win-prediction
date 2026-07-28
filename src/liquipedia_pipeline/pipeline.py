"""Orchestration for the offline Liquipedia data pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .dataset import DatasetTables, build_dataset_tables
from .export import ExportResult, export_dataset
from .models import NormalizedMatch, ParsedMatch, RawApiDocument
from .normalization import normalize_matches
from .parsing import parse_documents
from .raw import load_raw_documents


@dataclass(frozen=True)
class PipelineResult:
    """In-memory stages and exported artifacts from one pipeline run."""

    documents: tuple[RawApiDocument, ...]
    parsed_matches: tuple[ParsedMatch, ...]
    normalized_matches: tuple[NormalizedMatch, ...]
    tables: DatasetTables
    export: ExportResult


def run_pipeline(
    raw_paths: Iterable[Path],
    *,
    output_root: Path,
    include_csv: bool = False,
) -> PipelineResult:
    """Run raw loading, parsing, normalization, datasets, and export."""
    documents = load_raw_documents(raw_paths)
    parsed_matches = parse_documents(documents)
    normalized_matches = normalize_matches(parsed_matches)
    tables = build_dataset_tables(normalized_matches)
    exported = export_dataset(
        tables,
        documents=documents,
        output_root=output_root,
        include_csv=include_csv,
    )
    return PipelineResult(
        documents=documents,
        parsed_matches=parsed_matches,
        normalized_matches=normalized_matches,
        tables=tables,
        export=exported,
    )
