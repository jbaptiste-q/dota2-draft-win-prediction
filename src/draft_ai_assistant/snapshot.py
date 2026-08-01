"""Safe, JSON-only inference snapshot loading with strict provenance checks."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


SNAPSHOT_SCHEMA_VERSION = "draft-ai-inference-snapshot-v1"
DEFAULT_SNAPSHOT_SHA256 = (
    "bfb7fc8d907e77057cafaef8109a4aec8085915c9215f0dc43cc15ff61dc1a61"
)


class InferenceSnapshotError(ValueError):
    """Raised before an inconsistent public inference snapshot can be served."""


class SnapshotContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SnapshotHero(SnapshotContract):
    hero_key: str
    display_name: str


class SnapshotSource(SnapshotContract):
    candidate_id: str
    candidate_fingerprint: str
    experiment_build_fingerprint: str
    source_experiment_manifest_sha256: str
    source_bundle_fingerprint: str
    source_bundle_manifest_sha256: str
    source_feature_fingerprint: str
    source_split_fingerprint: str
    hero_catalog_sha256: str
    fit_cutoff_utc_exclusive: str
    fit_rows: int = Field(gt=0)


class SnapshotEvidence(SnapshotContract):
    readiness_gate_passed: Literal[False]
    locked_test_evaluated: Literal[False]
    readiness_reference: str
    q4_rows: int = Field(gt=0)
    candidate_log_loss: float
    reference_log_loss: float
    candidate_brier_score: float
    reference_brier_score: float
    export_parity_examples: int = Field(gt=0)
    export_parity_max_abs_probability_error: float = Field(ge=0.0)


class SnapshotModel(SnapshotContract):
    probability_method: Literal["raw_logistic"]
    intercept_log_odds: float
    radiant_hero_log_odds: dict[str, float]
    dire_hero_log_odds: dict[str, float]


class InferenceSnapshot(SnapshotContract):
    schema_version: Literal["draft-ai-inference-snapshot-v1"]
    artifact_id: str
    artifact_fingerprint: str
    status: Literal["development_candidate"]
    source: SnapshotSource
    evidence: SnapshotEvidence
    heroes: tuple[SnapshotHero, ...]
    model: SnapshotModel
    limitations: tuple[str, ...]

    @model_validator(mode="after")
    def validate_semantics(self) -> "InferenceSnapshot":
        hero_keys = tuple(hero.hero_key for hero in self.heroes)
        if not hero_keys or len(hero_keys) != len(set(hero_keys)):
            raise ValueError("Snapshot hero keys must be non-empty and unique.")
        if tuple(sorted(hero_keys)) != hero_keys:
            raise ValueError("Snapshot heroes must be sorted by hero key.")
        display_names = [hero.display_name for hero in self.heroes]
        if any(not value for value in display_names):
            raise ValueError("Snapshot display names cannot be empty.")
        expected_keys = set(hero_keys)
        if set(self.model.radiant_hero_log_odds) != expected_keys:
            raise ValueError("Radiant coefficients do not match the hero catalog.")
        if set(self.model.dire_hero_log_odds) != expected_keys:
            raise ValueError("Dire coefficients do not match the hero catalog.")
        numeric_values = (
            self.model.intercept_log_odds,
            *self.model.radiant_hero_log_odds.values(),
            *self.model.dire_hero_log_odds.values(),
        )
        if not all(math.isfinite(value) for value in numeric_values):
            raise ValueError("Snapshot coefficients must all be finite.")
        if not self.limitations or any(not value for value in self.limitations):
            raise ValueError("Snapshot limitations must be explicit.")
        return self


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def semantic_fingerprint(payload: dict[str, object]) -> str:
    core = {
        key: value
        for key, value in payload.items()
        if key != "artifact_fingerprint"
    }
    return hashlib.sha256(_canonical_json(core).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def default_snapshot_path() -> Path:
    return (
        Path(__file__).resolve().parent
        / "resources"
        / "development_candidate_v0.json"
    )


def load_inference_snapshot(
    path: Path,
    *,
    expected_sha256: str,
) -> InferenceSnapshot:
    """Hash, parse, and semantically validate a public JSON snapshot."""

    resolved = path.resolve()
    if not resolved.is_file() or sha256_file(resolved) != expected_sha256:
        raise InferenceSnapshotError(
            "Inference snapshot file hash verification failed."
        )
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InferenceSnapshotError(
            "Inference snapshot is not valid UTF-8 JSON."
        ) from error
    if not isinstance(payload, dict):
        raise InferenceSnapshotError("Inference snapshot root must be an object.")
    if semantic_fingerprint(payload) != payload.get("artifact_fingerprint"):
        raise InferenceSnapshotError(
            "Inference snapshot semantic fingerprint verification failed."
        )
    try:
        return InferenceSnapshot.model_validate(payload)
    except ValueError as error:
        raise InferenceSnapshotError(
            f"Inference snapshot contract validation failed: {error}"
        ) from error


__all__ = [
    "DEFAULT_SNAPSHOT_SHA256",
    "SNAPSHOT_SCHEMA_VERSION",
    "InferenceSnapshot",
    "InferenceSnapshotError",
    "SnapshotEvidence",
    "SnapshotHero",
    "SnapshotModel",
    "SnapshotSource",
    "default_snapshot_path",
    "load_inference_snapshot",
    "semantic_fingerprint",
    "sha256_file",
]
