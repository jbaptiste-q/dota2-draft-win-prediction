"""Trusted, hash-verified local bundle support for the frozen Draft AI model."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

from .calibration import apply_calibrator
from .features import DraftFeatureTransformer
from .loader import sha256_file


BUNDLE_SCHEMA_VERSION = "draft-ai-model-bundle-v1"


class ModelBundleError(ValueError):
    """Raised before an untrusted or inconsistent model artifact can be used."""


@dataclass(frozen=True, slots=True)
class LoadedModelBundle:
    """Verified separately serialized components and their public contract."""

    manifest: dict[str, Any]
    transformer: DraftFeatureTransformer
    estimator: LogisticRegression
    calibrator: LogisticRegression | IsotonicRegression | None

    def predict(self, frame: pd.DataFrame) -> dict[str, np.ndarray]:
        """Return both the explainable base and served calibrated probability."""

        matrix = self.transformer.transform(frame)
        classes = list(self.estimator.classes_)
        if 1 not in classes:
            raise ModelBundleError("The base estimator lacks the positive class.")
        raw = np.asarray(
            self.estimator.predict_proba(matrix)[:, classes.index(1)],
            dtype=np.float64,
        )
        calibrated = apply_calibrator(
            str(self.manifest["calibration"]["selected_method"]),
            self.calibrator,
            raw,
        )
        return {
            "raw_radiant_win_probability": raw,
            "calibrated_radiant_win_probability": calibrated,
        }


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _component(path: Path, *, component_id: str, kind: str) -> dict[str, Any]:
    return {
        "component_id": component_id,
        "kind": kind,
        "file": path.name,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _validate_component_types(
    *,
    method: str,
    transformer: object,
    estimator: object,
    calibrator: object,
) -> None:
    if not isinstance(transformer, DraftFeatureTransformer):
        raise ModelBundleError("Feature-transformer type is invalid.")
    if not isinstance(estimator, LogisticRegression):
        raise ModelBundleError("Base-estimator type is invalid.")
    expected_calibrator = {
        "raw": type(None),
        "sigmoid": LogisticRegression,
        "isotonic": IsotonicRegression,
    }.get(method)
    if expected_calibrator is None:
        raise ModelBundleError(f"Unknown calibration method: {method!r}.")
    if not isinstance(calibrator, expected_calibrator):
        raise ModelBundleError(
            f"The {method} calibrator component type is invalid."
        )


def write_model_bundle(
    directory: Path,
    *,
    transformer: DraftFeatureTransformer,
    estimator: LogisticRegression,
    calibrator: LogisticRegression | IsotonicRegression | None,
    selected_method: str,
    metadata: dict[str, Any],
) -> Path:
    """Serialize separately identified trusted components and a JSON contract."""

    _validate_component_types(
        method=selected_method,
        transformer=transformer,
        estimator=estimator,
        calibrator=calibrator,
    )
    output = directory.resolve()
    output.mkdir(parents=True, exist_ok=True)
    paths = {
        "feature_transformer": output / "feature_transformer.joblib",
        "base_estimator": output / "base_estimator.joblib",
    }
    if selected_method != "raw":
        paths["selected_calibrator"] = output / "selected_calibrator.joblib"
    if any(path.exists() for path in paths.values()):
        raise ModelBundleError("A bundle component path already exists.")

    joblib.dump(transformer, paths["feature_transformer"], compress=3)
    joblib.dump(estimator, paths["base_estimator"], compress=3)
    if selected_method != "raw":
        joblib.dump(calibrator, paths["selected_calibrator"], compress=3)

    components = {
        "feature_transformer": _component(
            paths["feature_transformer"],
            component_id="b1-pick-presence-transformer",
            kind=type(transformer).__name__,
        ),
        "base_estimator": _component(
            paths["base_estimator"],
            component_id="b1-full-uniform-c0p01-logistic",
            kind=type(estimator).__name__,
        ),
        "selected_calibrator": (
            {
                "component_id": "raw-identity",
                "kind": "identity",
                "file": None,
                "bytes": 0,
                "sha256": None,
            }
            if selected_method == "raw"
            else _component(
                paths["selected_calibrator"],
                component_id=f"{selected_method}-calibrator",
                kind=type(calibrator).__name__,
            )
        ),
    }
    core = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "trust_policy": {
            "trusted_local_artifacts_only": True,
            "verify_manifest_hash_before_parse": True,
            "verify_component_hash_before_deserialization": True,
            "never_load_user_supplied_paths": True,
        },
        "components": components,
        "calibration": {
            "selected_method": selected_method,
            "base_probability": "raw_radiant_win_probability",
            "served_probability": "calibrated_radiant_win_probability",
        },
        "feature_contract": {
            "variant": transformer.variant_.value,
            "fingerprint": transformer.fingerprint,
            "source_columns": list(transformer.source_columns_),
            "feature_count": len(transformer.get_feature_names_out()),
        },
        "explanation_contract": {
            "faithful_surface": "base_estimator_log_odds",
            "calibrator_role": "maps_base_probability_to_served_probability",
            "calibrated_probability_is_not_additively_explained": True,
        },
        "metadata": metadata,
    }
    manifest = {
        **core,
        "bundle_fingerprint": _sha256_json(core),
    }
    path = output / "model_bundle.json"
    path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    return path


def _trusted_path(path: Path, root: Path, *, label: str) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as error:
        raise ModelBundleError(f"{label} is outside the trusted root.") from error
    return resolved


def _component_path(
    directory: Path,
    payload: dict[str, Any],
    *,
    trusted_root: Path,
) -> Path:
    value = payload.get("file")
    relative = Path(str(value))
    if (
        value is None
        or relative.is_absolute()
        or len(relative.parts) != 1
        or relative.name != str(value)
    ):
        raise ModelBundleError("Bundle component path is not a safe file name.")
    path = _trusted_path(
        directory / relative,
        trusted_root,
        label="Bundle component",
    )
    expected = payload.get("sha256")
    if not path.is_file() or sha256_file(path) != expected:
        raise ModelBundleError(
            f"Bundle component hash failed: {payload.get('component_id')}."
        )
    return path


def load_model_bundle(
    manifest_path: Path,
    *,
    expected_manifest_sha256: str,
    trusted_root: Path,
) -> LoadedModelBundle:
    """Verify every digest before deserializing a trusted local bundle."""

    path = _trusted_path(
        manifest_path,
        trusted_root,
        label="Bundle manifest",
    )
    if not path.is_file() or sha256_file(path) != expected_manifest_sha256:
        raise ModelBundleError("Bundle manifest hash failed before parsing.")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ModelBundleError("Bundle manifest is not valid JSON.") from error
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != BUNDLE_SCHEMA_VERSION
    ):
        raise ModelBundleError("Bundle manifest schema is invalid.")
    core = {
        key: value
        for key, value in manifest.items()
        if key != "bundle_fingerprint"
    }
    if _sha256_json(core) != manifest.get("bundle_fingerprint"):
        raise ModelBundleError("Bundle semantic fingerprint changed.")

    method = str(manifest.get("calibration", {}).get("selected_method"))
    components = manifest.get("components", {})
    if set(components) != {
        "feature_transformer",
        "base_estimator",
        "selected_calibrator",
    }:
        raise ModelBundleError("Bundle component inventory changed.")
    transformer_path = _component_path(
        path.parent,
        components["feature_transformer"],
        trusted_root=trusted_root,
    )
    estimator_path = _component_path(
        path.parent,
        components["base_estimator"],
        trusted_root=trusted_root,
    )
    calibrator_payload = components["selected_calibrator"]
    calibrator_path = (
        None
        if method == "raw"
        else _component_path(
            path.parent,
            calibrator_payload,
            trusted_root=trusted_root,
        )
    )
    if method == "raw" and calibrator_payload != {
        "component_id": "raw-identity",
        "kind": "identity",
        "file": None,
        "bytes": 0,
        "sha256": None,
    }:
        raise ModelBundleError("Raw identity calibrator contract changed.")

    transformer = joblib.load(transformer_path)
    estimator = joblib.load(estimator_path)
    calibrator = (
        None if calibrator_path is None else joblib.load(calibrator_path)
    )
    _validate_component_types(
        method=method,
        transformer=transformer,
        estimator=estimator,
        calibrator=calibrator,
    )
    feature_contract = manifest["feature_contract"]
    if (
        transformer.fingerprint != feature_contract.get("fingerprint")
        or list(transformer.source_columns_)
        != feature_contract.get("source_columns")
        or len(transformer.get_feature_names_out())
        != feature_contract.get("feature_count")
    ):
        raise ModelBundleError("Loaded feature-transformer contract changed.")
    return LoadedModelBundle(
        manifest=manifest,
        transformer=transformer,
        estimator=estimator,
        calibrator=calibrator,
    )


__all__ = [
    "BUNDLE_SCHEMA_VERSION",
    "LoadedModelBundle",
    "ModelBundleError",
    "load_model_bundle",
    "write_model_bundle",
]
