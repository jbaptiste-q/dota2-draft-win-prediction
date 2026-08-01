#!/usr/bin/env python3
"""Export the pinned trusted joblib bundle as a safe public JSON snapshot."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote

import duckdb
import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.draft_ai_assistant.snapshot import (
    SNAPSHOT_SCHEMA_VERSION,
    InferenceSnapshot,
    semantic_fingerprint,
    sha256_file,
)
from src.draft_ai_modeling.model_bundle import load_model_bundle


DEFAULT_CONFIG = (
    PROJECT_ROOT / "configs" / "product" / "draft_assistant_v0.json"
)


class SnapshotExportError(ValueError):
    """Raised if frozen lineage cannot produce the exact public snapshot."""


def _load_json(path: Path, *, expected_sha256: str | None = None) -> dict:
    if expected_sha256 is not None and sha256_file(path) != expected_sha256:
        raise SnapshotExportError(f"Source hash verification failed: {path}.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SnapshotExportError(f"Invalid JSON source: {path}.") from error
    if not isinstance(payload, dict):
        raise SnapshotExportError(f"JSON source must be an object: {path}.")
    return payload


def _resolve(relative_path: str) -> Path:
    path = (PROJECT_ROOT / relative_path).resolve()
    try:
        path.relative_to(PROJECT_ROOT)
    except ValueError as error:
        raise SnapshotExportError(
            f"Configured source escapes the repository: {relative_path}."
        ) from error
    return path


def _coefficient_maps(bundle: object) -> tuple[dict[str, float], dict[str, float]]:
    estimator = bundle.estimator
    transformer = bundle.transformer
    if list(estimator.classes_) != [0, 1]:
        raise SnapshotExportError("Base estimator class order is not [0, 1].")
    coefficients = np.asarray(estimator.coef_, dtype=np.float64)
    if coefficients.shape != (1, len(transformer.get_feature_names_out())):
        raise SnapshotExportError("Estimator and transformer dimensions differ.")

    radiant: dict[str, float] = {}
    dire: dict[str, float] = {}
    for name, coefficient in zip(
        transformer.get_feature_names_out(),
        coefficients[0],
        strict=True,
    ):
        value = str(name)
        if value.endswith("::__UNKNOWN__"):
            continue
        parts = value.split("::")
        if len(parts) != 4 or parts[0] != "presence" or parts[2] != "hero":
            raise SnapshotExportError(f"Unexpected B1 feature name: {value}.")
        hero_key = unquote(parts[3])
        target = (
            radiant
            if parts[1] == "radiant_pick"
            else dire
            if parts[1] == "dire_pick"
            else None
        )
        if target is None or hero_key in target:
            raise SnapshotExportError(f"Unexpected B1 feature role: {value}.")
        target[hero_key] = float(coefficient)
    return radiant, dire


def _sigmoid(value: float) -> float:
    if value >= 0:
        inverse = math.exp(-value)
        return 1.0 / (1.0 + inverse)
    exponential = math.exp(value)
    return exponential / (1.0 + exponential)


def _verify_export_parity(
    *,
    bundle: object,
    hero_keys: list[str],
    radiant: dict[str, float],
    dire: dict[str, float],
) -> tuple[int, float]:
    if len(hero_keys) < 30:
        raise SnapshotExportError("Hero catalog is too small for parity checks.")
    drafts = (
        (hero_keys[:5], hero_keys[5:10]),
        (hero_keys[-10:-5], hero_keys[-5:]),
        (hero_keys[::12][:5], hero_keys[6::12][:5]),
    )
    rows = []
    exported = []
    for radiant_picks, dire_picks in drafts:
        if len(set((*radiant_picks, *dire_picks))) != 10:
            raise SnapshotExportError("Parity draft heroes must be unique.")
        row = {
            **{
                f"radiant_pick_slot_{index}": hero_key
                for index, hero_key in enumerate(radiant_picks, start=1)
            },
            **{
                f"dire_pick_slot_{index}": hero_key
                for index, hero_key in enumerate(dire_picks, start=1)
            },
        }
        rows.append(row)
        log_odds = math.fsum(
            (
                float(bundle.estimator.intercept_[0]),
                *(radiant[hero_key] for hero_key in radiant_picks),
                *(dire[hero_key] for hero_key in dire_picks),
            )
        )
        exported.append(_sigmoid(log_odds))
    source = bundle.predict(pd.DataFrame(rows))[
        "raw_radiant_win_probability"
    ]
    maximum_error = float(
        np.max(np.abs(np.asarray(exported, dtype=np.float64) - source))
    )
    if maximum_error > 1e-15:
        raise SnapshotExportError(
            "JSON snapshot does not reproduce source bundle probabilities."
        )
    return len(drafts), maximum_error


def build_snapshot(config_path: Path = DEFAULT_CONFIG) -> dict[str, object]:
    """Build a deterministic JSON-safe snapshot from exact pinned sources."""

    config = _load_json(config_path.resolve())
    if config.get("schema_version") != "draft-assistant-snapshot-export-v1":
        raise SnapshotExportError("Snapshot export config schema changed.")
    source = config.get("source")
    contract = config.get("product_contract")
    if not isinstance(source, dict) or not isinstance(contract, dict):
        raise SnapshotExportError("Snapshot export config is incomplete.")
    if contract != {
        "representation": "unordered_side_relative_completed_picks",
        "picks_per_side": 5,
        "unique_heroes_required": True,
        "out_of_vocabulary_policy": "reject",
        "probability_method": "raw_logistic",
        "explanation_surface": "base_estimator_log_odds",
        "first_pick_supported": False,
        "global_draft_order_supported": False,
        "bans_used": False,
        "recommendations_available": False,
    }:
        raise SnapshotExportError("Product inference contract changed.")

    bundle_manifest_path = _resolve(source["bundle_manifest_path"])
    bundle = load_model_bundle(
        bundle_manifest_path,
        expected_manifest_sha256=source["bundle_manifest_sha256"],
        trusted_root=_resolve(source["trusted_bundle_root"]),
    )
    manifest = bundle.manifest
    if manifest["feature_contract"]["variant"] != "b1-pick-presence":
        raise SnapshotExportError("Only the frozen B1 variant can be exported.")
    if manifest["calibration"]["selected_method"] != "raw":
        raise SnapshotExportError("Only the frozen raw policy can be exported.")
    metadata = manifest["metadata"]
    if (
        metadata["readiness_gate_passed"] is not False
        or metadata["locked_test_predictions"] != 0
    ):
        raise SnapshotExportError("Frozen readiness boundary changed.")

    experiment_manifest = _load_json(
        _resolve(source["experiment_manifest_path"]),
        expected_sha256=source["experiment_manifest_sha256"],
    )
    if (
        experiment_manifest.get("build_fingerprint")
        != metadata["experiment_build_fingerprint"]
        or experiment_manifest.get("artifacts", {})
        .get("bundle_manifest", {})
        .get("sha256")
        != source["bundle_manifest_sha256"]
        or experiment_manifest.get("artifacts", {})
        .get("readiness", {})
        .get("sha256")
        != source["readiness_sha256"]
    ):
        raise SnapshotExportError(
            "Experiment manifest does not pin the selected bundle evidence."
        )
    expected_zero_counters = {
        "authenticated_api_requests": 0,
        "locked_test_prediction_rows": 0,
        "locked_test_target_rows_used_for_modeling": 0,
        "locked_test_transform_rows": 0,
    }
    result = experiment_manifest.get("result", {})
    if any(result.get(key) != value for key, value in expected_zero_counters.items()):
        raise SnapshotExportError(
            "Experiment manifest locked-test or API counters changed."
        )
    role_audit = experiment_manifest.get("role_audit", {})
    if (
        role_audit.get("locked_test_prediction_rows") != 0
        or role_audit.get("locked_test_transform_rows") != 0
        or role_audit.get("locked_test_targets_masked_before_role_selection")
        is not True
    ):
        raise SnapshotExportError(
            "Experiment manifest locked-test role audit changed."
        )
    safety = experiment_manifest.get("safety", {})
    if any(
        safety.get(key) is not False
        for key in (
            "locked_test_predictions",
            "locked_test_target_use",
            "locked_test_transform",
        )
    ):
        raise SnapshotExportError(
            "Experiment manifest locked-test safety contract changed."
        )

    readiness = _load_json(
        _resolve(source["readiness_path"]),
        expected_sha256=source["readiness_sha256"],
    )
    if readiness.get("passed") is not False:
        raise SnapshotExportError("The source readiness gate must remain failed.")

    catalog_path = _resolve(source["hero_catalog_path"])
    if sha256_file(catalog_path) != source["hero_catalog_sha256"]:
        raise SnapshotExportError("Hero catalog hash verification failed.")
    catalog_frame = duckdb.connect().execute(
        """
        SELECT CAST(hero_key AS VARCHAR), CAST(source_name AS VARCHAR)
        FROM read_parquet(?)
        ORDER BY hero_key
        """,
        [str(catalog_path)],
    ).fetchall()
    heroes = [
        {"hero_key": str(hero_key), "display_name": str(display_name)}
        for hero_key, display_name in catalog_frame
    ]
    if len(heroes) != len({item["hero_key"] for item in heroes}):
        raise SnapshotExportError("Hero catalog keys are not unique.")

    radiant, dire = _coefficient_maps(bundle)
    hero_keys = {item["hero_key"] for item in heroes}
    if set(radiant) != hero_keys or set(dire) != hero_keys:
        raise SnapshotExportError(
            "Hero catalog and frozen transformer vocabulary differ."
        )
    parity_examples, parity_error = _verify_export_parity(
        bundle=bundle,
        hero_keys=sorted(hero_keys),
        radiant=radiant,
        dire=dire,
    )
    comparison = readiness["comparison"]["metrics"]
    core: dict[str, object] = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "artifact_id": config["artifact_id"],
        "status": config["status"],
        "source": {
            "candidate_id": metadata["candidate_id"],
            "candidate_fingerprint": metadata["candidate_fingerprint"],
            "experiment_build_fingerprint": (
                metadata["experiment_build_fingerprint"]
            ),
            "source_experiment_manifest_sha256": (
                source["experiment_manifest_sha256"]
            ),
            "source_bundle_fingerprint": manifest["bundle_fingerprint"],
            "source_bundle_manifest_sha256": (
                source["bundle_manifest_sha256"]
            ),
            "source_feature_fingerprint": (
                manifest["feature_contract"]["fingerprint"]
            ),
            "source_split_fingerprint": (
                metadata["source_split_fingerprint"]
            ),
            "hero_catalog_sha256": source["hero_catalog_sha256"],
            "fit_cutoff_utc_exclusive": (
                metadata["base_fit_end_utc_exclusive"]
            ),
            "fit_rows": metadata["base_fit_rows"],
        },
        "evidence": {
            "readiness_gate_passed": False,
            "locked_test_evaluated": False,
            "readiness_reference": readiness["reference"],
            "q4_rows": readiness["comparison"]["audit"]["rows"],
            "candidate_log_loss": (
                comparison["log_loss"]["candidate_point_estimate"]
            ),
            "reference_log_loss": (
                comparison["log_loss"]["reference_point_estimate"]
            ),
            "candidate_brier_score": (
                comparison["brier_score"]["candidate_point_estimate"]
            ),
            "reference_brier_score": (
                comparison["brier_score"]["reference_point_estimate"]
            ),
            "export_parity_examples": parity_examples,
            "export_parity_max_abs_probability_error": parity_error,
        },
        "heroes": heroes,
        "model": {
            "probability_method": "raw_logistic",
            "intercept_log_odds": float(bundle.estimator.intercept_[0]),
            "radiant_hero_log_odds": dict(sorted(radiant.items())),
            "dire_hero_log_odds": dict(sorted(dire.items())),
        },
        "limitations": config["limitations"],
    }
    return {
        **core,
        "artifact_fingerprint": semantic_fingerprint(core),
    }


def _validated_render(payload: dict[str, object]) -> str:
    try:
        InferenceSnapshot.model_validate(payload)
    except ValueError as error:
        raise SnapshotExportError(
            f"Generated snapshot failed its runtime contract: {error}"
        ) from error
    return (
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
        + "\n"
    )


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
            temporary_path = Path(stream.name)
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export the pinned B1 development candidate to safe JSON."
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write the configured public snapshot; otherwise only verify.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = _load_json(args.config.resolve())
    payload = build_snapshot(args.config)
    output = _resolve(config["output_path"])
    rendered = _validated_render(payload)
    if args.write:
        _atomic_write(output, rendered)
    elif not output.is_file() or output.read_text(encoding="utf-8") != rendered:
        raise SnapshotExportError(
            "Tracked inference snapshot is absent or not reproducible; "
            "rerun with --write from the pinned local artifacts."
        )
    print(
        json.dumps(
            {
                "artifact_fingerprint": payload["artifact_fingerprint"],
                "heroes": len(payload["heroes"]),
                "output_path": str(output.relative_to(PROJECT_ROOT)),
                "output_sha256": (
                    sha256_file(output) if output.is_file() else None
                ),
                "readiness_gate_passed": False,
                "locked_test_evaluated": False,
                "authenticated_api_requests": 0,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
