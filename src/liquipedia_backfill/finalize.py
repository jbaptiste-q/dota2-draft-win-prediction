"""Offline handoff from completed acquisition to normalized Parquet outputs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from src.liquipedia_pipeline.pipeline import PipelineResult, run_pipeline

from .assembly import AssemblyResult, assemble_snapshot, write_parquet
from .config import BackfillConfig, canonical_json
from .reports import generate_coverage_reports
from .state import StateStore


@dataclass(frozen=True, slots=True)
class FinalizationResult:
    """Acquisition, normalized, and quality-report artifact identities."""

    acquisition_fingerprint: str
    run_directory: Path
    manifest_path: Path
    assembly: AssemblyResult
    normalized: PipelineResult
    reports_directory: Path


def write_run_indices(
    state: StateStore,
    config: BackfillConfig,
) -> tuple[Path, Path]:
    """Export page and request ledgers into immutable review artifacts."""
    run_directory = config.run_directory
    run_directory.mkdir(parents=True, exist_ok=True)
    pages = state.accepted_pages(config.run_id)
    requests = state.request_attempts(config.run_id)
    page_index_path = run_directory / "page_index.parquet"
    page_frame = pd.DataFrame(pages)
    if not page_frame.empty:
        page_frame = page_frame.sort_values(
            "sequence",
            kind="mergesort",
        ).reset_index(drop=True)
    write_parquet(page_frame, page_index_path)

    request_ledger_path = run_directory / "request_ledger.jsonl"
    request_ledger_path.write_text(
        "".join(
            json.dumps(item, sort_keys=True) + "\n"
            for item in requests
        ),
        encoding="utf-8",
    )
    return page_index_path, request_ledger_path


def finalize_completed_run(config: BackfillConfig) -> FinalizationResult:
    """Assemble, normalize, and report a fully acquired historical partition."""
    with StateStore(config.state_path) as state:
        run = state.run(config.run_id)
        if run["status"] != "complete":
            raise ValueError(
                f"Run {config.run_id} is not complete: {run['status']}."
            )
        pages = state.accepted_pages(config.run_id)
        page_index_path, request_ledger_path = write_run_indices(state, config)
        checkpoint_path = state.write_checkpoint(config)

    assembly = assemble_snapshot(
        pages,
        config_hash=config.config_hash,
        output_root=config.run_directory / "assembly",
        request_count=int(run["request_count"]),
        cache_hit_count=int(run["cache_hit_count"]),
    )
    normalized = run_pipeline(
        [assembly.snapshot_path],
        output_root=config.normalized_output_root,
    )
    reports_directory = config.run_directory / "reports"
    coverage_summary = generate_coverage_reports(
        normalized.export.output_directory,
        output_directory=reports_directory,
    )
    acquisition_identity = {
        "config_hash": config.config_hash,
        "raw_response_sha256": sorted(
            str(page["response_sha256"])
            for page in pages
        ),
        "assembly_fingerprint": assembly.build_fingerprint,
        "normalized_build_fingerprint": normalized.export.build_fingerprint,
    }
    acquisition_fingerprint = hashlib.sha256(
        canonical_json(acquisition_identity).encode("utf-8")
    ).hexdigest()
    manifest = {
        "acquisition_fingerprint": acquisition_fingerprint,
        "run_id": config.run_id,
        "config_hash": config.config_hash,
        "scope": config.scope_payload(),
        "request_count": int(run["request_count"]),
        "cache_hit_count": int(run["cache_hit_count"]),
        "raw_response_sha256": acquisition_identity["raw_response_sha256"],
        "assembly": {
            "fingerprint": assembly.build_fingerprint,
            "manifest": str(assembly.manifest_path.resolve()),
            "snapshot_sha256": hashlib.sha256(
                assembly.snapshot_path.read_bytes()
            ).hexdigest(),
        },
        "normalized": {
            "build_fingerprint": normalized.export.build_fingerprint,
            "manifest": str(normalized.export.manifest_path.resolve()),
            "schema_version": "liquipedia-dota-draft-v1",
        },
        "coverage_summary": coverage_summary,
        "artifacts": {
            "checkpoint": str(checkpoint_path.resolve()),
            "page_index": str(page_index_path.resolve()),
            "request_ledger": str(request_ledger_path.resolve()),
            "reports_directory": str(reports_directory.resolve()),
        },
        "source_attribution": {
            "source": "Liquipedia",
            "license": "CC-BY-SA 3.0",
            "terms": "https://liquipedia.net/api-terms-of-use",
        },
    }
    manifest_path = config.run_directory / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return FinalizationResult(
        acquisition_fingerprint=acquisition_fingerprint,
        run_directory=config.run_directory,
        manifest_path=manifest_path,
        assembly=assembly,
        normalized=normalized,
        reports_directory=reports_directory,
    )
