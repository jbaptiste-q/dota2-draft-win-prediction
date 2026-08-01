"""Offline integrity tests for the tracked Draft Assistant JSON snapshot."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.draft_ai_assistant.snapshot import (
    DEFAULT_SNAPSHOT_SHA256,
    SNAPSHOT_SCHEMA_VERSION,
    InferenceSnapshotError,
    default_snapshot_path,
    load_inference_snapshot,
    semantic_fingerprint,
    sha256_file,
)
from scripts.export_draft_assistant_snapshot import (
    SnapshotExportError,
    _atomic_write,
    _validated_render,
)


EXPECTED_SNAPSHOT_SHA256 = (
    "bfb7fc8d907e77057cafaef8109a4aec8085915c9215f0dc43cc15ff61dc1a61"
)
EXPECTED_ARTIFACT_FINGERPRINT = (
    "69730a62f42cda234337e8cbf152fb50fcb7ae02faf38367955c267fbe714442"
)


def _payload() -> dict[str, object]:
    return json.loads(default_snapshot_path().read_text(encoding="utf-8"))


def _write_payload(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    return path


def test_tracked_snapshot_has_the_exact_public_hash_and_semantic_identity() -> None:
    path = default_snapshot_path()
    payload = _payload()

    assert path.name == "development_candidate_v0.json"
    assert DEFAULT_SNAPSHOT_SHA256 == EXPECTED_SNAPSHOT_SHA256
    assert sha256_file(path) == EXPECTED_SNAPSHOT_SHA256
    assert payload["schema_version"] == SNAPSHOT_SCHEMA_VERSION
    assert payload["artifact_fingerprint"] == EXPECTED_ARTIFACT_FINGERPRINT
    assert semantic_fingerprint(payload) == EXPECTED_ARTIFACT_FINGERPRINT


def test_snapshot_contract_pins_candidate_evidence_and_safe_json_model() -> None:
    snapshot = load_inference_snapshot(
        default_snapshot_path(),
        expected_sha256=EXPECTED_SNAPSHOT_SHA256,
    )

    assert snapshot.schema_version == SNAPSHOT_SCHEMA_VERSION
    assert snapshot.status == "development_candidate"
    assert snapshot.artifact_fingerprint == EXPECTED_ARTIFACT_FINGERPRINT
    assert snapshot.source.candidate_id == "b1_full_uniform_c0p01"
    assert snapshot.source.candidate_fingerprint == (
        "cc74f23fbd16e6ff6f5a3e2598cd9d326b78abee860bfceeb569154c0c77837e"
    )
    assert snapshot.source.experiment_build_fingerprint == (
        "3f768bb13f0b447bcf6704086f00c28f4652a21e467089d3549060ad3ab64a5c"
    )
    assert snapshot.source.source_experiment_manifest_sha256 == (
        "5a968b5d0d1b9e09e3ba31d16c09454078f4b2ec0d7ba99fa4d9a8018de9cd15"
    )
    assert snapshot.source.source_bundle_fingerprint == (
        "d89104b0688a68b0c708b2719d616786d752d0880f8e9662384f9769c38aadb6"
    )
    assert snapshot.source.source_bundle_manifest_sha256 == (
        "043646136f4034b62cf08679ce15c406e6c4c132a7d6c64afc248599785991f4"
    )
    assert snapshot.source.source_feature_fingerprint == (
        "f651eb86302489110e9af72ea03ef3ffdc790f13b73531a893d3a7bdd4d5401a"
    )
    assert snapshot.source.fit_cutoff_utc_exclusive == (
        "2025-10-01T00:00:00Z"
    )
    assert snapshot.source.fit_rows == 20_087
    assert snapshot.evidence.readiness_gate_passed is False
    assert snapshot.evidence.locked_test_evaluated is False
    assert snapshot.evidence.candidate_log_loss > (
        snapshot.evidence.reference_log_loss
    )
    assert snapshot.evidence.candidate_brier_score > (
        snapshot.evidence.reference_brier_score
    )
    assert snapshot.evidence.export_parity_examples == 3
    assert (
        snapshot.evidence.export_parity_max_abs_probability_error
        <= 1e-15
    )
    assert snapshot.model.probability_method == "raw_logistic"
    assert len(snapshot.heroes) == 125
    hero_keys = tuple(hero.hero_key for hero in snapshot.heroes)
    assert hero_keys == tuple(sorted(hero_keys))
    assert set(snapshot.model.radiant_hero_log_odds) == set(hero_keys)
    assert set(snapshot.model.dire_hero_log_odds) == set(hero_keys)
    assert all(path.suffix != ".joblib" for path in [default_snapshot_path()])


def test_snapshot_file_tampering_fails_before_json_parsing(
    tmp_path: Path,
) -> None:
    tampered = tmp_path / "snapshot.json"
    tampered.write_bytes(default_snapshot_path().read_bytes() + b" ")

    with pytest.raises(
        InferenceSnapshotError,
        match="file hash verification failed",
    ):
        load_inference_snapshot(
            tampered,
            expected_sha256=EXPECTED_SNAPSHOT_SHA256,
        )


def test_semantic_tampering_fails_even_with_the_new_file_hash(
    tmp_path: Path,
) -> None:
    payload = _payload()
    payload["model"]["intercept_log_odds"] = 99.0
    tampered = _write_payload(tmp_path / "snapshot.json", payload)

    with pytest.raises(
        InferenceSnapshotError,
        match="semantic fingerprint verification failed",
    ):
        load_inference_snapshot(
            tampered,
            expected_sha256=sha256_file(tampered),
        )


def test_snapshot_contract_rejects_unknown_fields_after_rehash(
    tmp_path: Path,
) -> None:
    payload = _payload()
    payload["unreviewed_contract_field"] = True
    payload["artifact_fingerprint"] = semantic_fingerprint(payload)
    changed = _write_payload(tmp_path / "snapshot.json", payload)

    with pytest.raises(
        InferenceSnapshotError,
        match="contract validation failed",
    ):
        load_inference_snapshot(
            changed,
            expected_sha256=sha256_file(changed),
        )


def test_snapshot_contract_rejects_coefficient_catalog_drift_after_rehash(
    tmp_path: Path,
) -> None:
    payload = _payload()
    payload["model"]["radiant_hero_log_odds"].pop("abaddon")
    payload["artifact_fingerprint"] = semantic_fingerprint(payload)
    changed = _write_payload(tmp_path / "snapshot.json", payload)

    with pytest.raises(
        InferenceSnapshotError,
        match="Radiant coefficients do not match",
    ):
        load_inference_snapshot(
            changed,
            expected_sha256=sha256_file(changed),
        )


def test_export_validates_runtime_contract_before_atomic_write(
    tmp_path: Path,
) -> None:
    payload = _payload()
    rendered = _validated_render(payload)
    output = tmp_path / "snapshot.json"

    _atomic_write(output, rendered)

    assert output.read_text(encoding="utf-8") == rendered
    assert not tuple(tmp_path.glob(".*.tmp"))

    payload["model"]["dire_hero_log_odds"].pop("abaddon")
    payload["artifact_fingerprint"] = semantic_fingerprint(payload)
    with pytest.raises(
        SnapshotExportError,
        match="failed its runtime contract",
    ):
        _validated_render(payload)
