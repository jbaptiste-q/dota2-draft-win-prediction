"""Tests for trusted, separately hashed Draft AI model bundles."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression

from src.draft_ai_modeling.calibration import fit_calibrator
from src.draft_ai_modeling.features import (
    DraftFeatureTransformer,
    FeatureVariant,
)
from src.draft_ai_modeling.loader import sha256_file
from src.draft_ai_modeling.model_bundle import (
    ModelBundleError,
    load_model_bundle,
    write_model_bundle,
)


def draft_frame(rows: int = 20) -> pd.DataFrame:
    """Return a small complete pick frame with both target classes."""

    records = []
    for index in range(rows):
        target = index % 2
        record: dict[str, object] = {"radiant_win": target}
        radiant_prefix = "strong" if target else "weak"
        dire_prefix = "weak" if target else "strong"
        for slot in range(1, 6):
            record[f"radiant_pick_slot_{slot}"] = (
                f"{radiant_prefix}-hero-{slot}"
            )
            record[f"dire_pick_slot_{slot}"] = (
                f"{dire_prefix}-hero-{slot}"
            )
        records.append(record)
    return pd.DataFrame(records)


def fitted_components() -> tuple[
    pd.DataFrame,
    DraftFeatureTransformer,
    LogisticRegression,
    np.ndarray,
]:
    frame = draft_frame()
    transformer = DraftFeatureTransformer(
        FeatureVariant.B1_PICK_PRESENCE
    ).fit(frame)
    matrix = transformer.transform(frame)
    estimator = LogisticRegression(
        C=0.01,
        solver="liblinear",
        max_iter=2000,
        random_state=42,
    ).fit(matrix, frame["radiant_win"].to_numpy())
    raw = estimator.predict_proba(matrix)[:, 1]
    return frame, transformer, estimator, raw


@pytest.mark.parametrize("method", ["raw", "sigmoid"])
def test_bundle_round_trip_preserves_both_probability_surfaces(
    tmp_path: Path,
    method: str,
) -> None:
    frame, transformer, estimator, raw = fitted_components()
    calibrator = fit_calibrator(
        method,
        raw,
        frame["radiant_win"].to_numpy(),
    )
    manifest = write_model_bundle(
        tmp_path / "bundle",
        transformer=transformer,
        estimator=estimator,
        calibrator=calibrator,
        selected_method=method,
        metadata={"test": True},
    )
    loaded = load_model_bundle(
        manifest,
        expected_manifest_sha256=sha256_file(manifest),
        trusted_root=tmp_path,
    )

    predictions = loaded.predict(frame)

    assert np.allclose(
        predictions["raw_radiant_win_probability"],
        raw,
        atol=1e-12,
        rtol=0,
    )
    assert predictions["calibrated_radiant_win_probability"].shape == (
        len(frame),
    )
    assert loaded.manifest["calibration"]["selected_method"] == method
    assert (
        loaded.manifest["explanation_contract"]["faithful_surface"]
        == "base_estimator_log_odds"
    )


def test_component_corruption_is_rejected_before_deserialization(
    tmp_path: Path,
) -> None:
    _, transformer, estimator, _ = fitted_components()
    manifest = write_model_bundle(
        tmp_path / "bundle",
        transformer=transformer,
        estimator=estimator,
        calibrator=None,
        selected_method="raw",
        metadata={},
    )
    estimator_path = manifest.parent / "base_estimator.joblib"
    estimator_path.write_bytes(estimator_path.read_bytes() + b"corrupt")

    with pytest.raises(ModelBundleError, match="component hash failed"):
        load_model_bundle(
            manifest,
            expected_manifest_sha256=sha256_file(manifest),
            trusted_root=tmp_path,
        )


def test_manifest_requires_an_external_hash_and_trusted_root(
    tmp_path: Path,
) -> None:
    _, transformer, estimator, _ = fitted_components()
    manifest = write_model_bundle(
        tmp_path / "bundle",
        transformer=transformer,
        estimator=estimator,
        calibrator=None,
        selected_method="raw",
        metadata={},
    )

    with pytest.raises(ModelBundleError, match="manifest hash"):
        load_model_bundle(
            manifest,
            expected_manifest_sha256="0" * 64,
            trusted_root=tmp_path,
        )
    with pytest.raises(ModelBundleError, match="outside the trusted root"):
        load_model_bundle(
            manifest,
            expected_manifest_sha256=sha256_file(manifest),
            trusted_root=tmp_path / "different",
        )


def test_bundle_rejects_calibrator_type_mismatch(tmp_path: Path) -> None:
    _, transformer, estimator, _ = fitted_components()

    with pytest.raises(ModelBundleError, match="type is invalid"):
        write_model_bundle(
            tmp_path / "bundle",
            transformer=transformer,
            estimator=estimator,
            calibrator=None,
            selected_method="sigmoid",
            metadata={},
        )
