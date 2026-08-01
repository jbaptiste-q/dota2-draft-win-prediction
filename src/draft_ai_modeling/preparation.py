"""Offline orchestration for the Milestone 4A modeling-infrastructure gate.

This module verifies the frozen supervised corpus, creates the temporal split,
fits feature vocabularies on training rows only, audits all feature variants,
and records unfitted baseline declarations.  It never calls Liquipedia and it
never fits an estimator.
"""

from __future__ import annotations

import hashlib
import json
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import scipy
import sklearn

from .baselines import (
    BaselineId,
    baseline_contract_payload,
    baseline_fingerprint,
    create_unfitted_estimator,
)
from .contracts import (
    CORPUS_CONTRACT_VERSION,
    CURRENT_TEMPORAL_SPLIT,
    SPLIT_ROLE_TRAIN,
)
from .features import DraftFeatureTransformer, FeatureVariant
from .loader import (
    LoadedWorkingCorpus,
    load_working_corpus,
    sha256_file,
)
from .splits import (
    SplitManifestResult,
    build_split_manifest,
    render_split_report_markdown,
)


PREPARATION_SCHEMA_VERSION = "draft-ai-modeling-preparation-v1"
PREPARATION_VERSION = "1.0.0"


class ModelingPreparationError(ValueError):
    """Raised when generated M4A evidence is inconsistent or incomplete."""


@dataclass(frozen=True, slots=True)
class ModelingPreparationResult:
    """Content-addressed artifacts produced by one offline M4A preparation."""

    build_fingerprint: str
    output_directory: Path
    manifest_path: Path
    split_manifest_path: Path
    split_report_path: Path
    feature_contracts_path: Path
    baseline_contracts_path: Path
    report_path: Path


def canonical_json(value: object) -> str:
    """Return the canonical JSON encoding used by M4A fingerprints."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def package_source_sha256() -> str:
    """Hash the complete active modeling-infrastructure package."""
    root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for path in sorted(root.glob("*.py")):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_parquet(frame: pd.DataFrame, path: Path) -> None:
    escaped = path.resolve().as_posix().replace("'", "''")
    with duckdb.connect() as connection:
        connection.register("split_frame", frame)
        connection.execute(
            "COPY (SELECT * FROM split_frame) "
            f"TO '{escaped}' "
            "(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000)"
        )


def _join_split_roles(
    corpus: LoadedWorkingCorpus,
    split: SplitManifestResult,
) -> pd.DataFrame:
    roles = split.manifest[["sample_id", "split_role"]]
    joined = corpus.frame.merge(
        roles,
        on="sample_id",
        how="left",
        validate="one_to_one",
    )
    if joined["split_role"].isna().any():
        raise ModelingPreparationError(
            "The split manifest does not cover every corpus row."
        )
    return joined


def _matrix_audit(
    transformer: DraftFeatureTransformer,
    frame: pd.DataFrame,
) -> dict[str, object]:
    matrix = transformer.transform(frame)
    names = transformer.get_feature_names_out().tolist()
    unknown_positions = [
        position
        for position, name in enumerate(names)
        if name.endswith("::__UNKNOWN__")
    ]
    unknown_total = (
        int(matrix[:, unknown_positions].sum())
        if unknown_positions
        else 0
    )
    return {
        "rows": int(matrix.shape[0]),
        "columns": int(matrix.shape[1]),
        "nonzero_values": int(matrix.nnz),
        "unknown_feature_columns": len(unknown_positions),
        "unknown_hero_activations": unknown_total,
        "dtype": str(matrix.dtype),
    }


def build_feature_audits(
    corpus: LoadedWorkingCorpus,
    split: SplitManifestResult,
) -> list[dict[str, object]]:
    """Fit each feature vocabulary on train only and audit every split role."""
    joined = _join_split_roles(corpus, split)
    train = joined[joined["split_role"] == SPLIT_ROLE_TRAIN]
    if len(train) != 18_623:
        raise ModelingPreparationError(
            "The feature vocabulary must fit exactly the approved train rows."
        )

    records: list[dict[str, object]] = []
    for variant in FeatureVariant:
        transformer = DraftFeatureTransformer(variant).fit(train)
        matrices = {
            interval.role: _matrix_audit(
                transformer,
                joined[joined["split_role"] == interval.role],
            )
            for interval in CURRENT_TEMPORAL_SPLIT.intervals
        }
        records.append(
            {
                "variant": variant.value,
                "feature_fingerprint": transformer.fingerprint,
                "hero_vocabulary_size": len(
                    transformer.hero_vocabulary_
                ),
                "fitted_on_split_role": SPLIT_ROLE_TRAIN,
                "fitted_rows": len(train),
                "contract": transformer.feature_contract(),
                "matrix_audit_by_role": matrices,
            }
        )
    return records


def build_baseline_declarations() -> list[dict[str, object]]:
    """Record deterministic estimator blueprints without fitting them."""
    declarations: list[dict[str, object]] = []
    for baseline_id in BaselineId:
        estimator = create_unfitted_estimator(baseline_id)
        fitted_attributes = sorted(
            name
            for name in vars(estimator)
            if name.endswith("_") and not name.startswith("__")
        )
        if fitted_attributes:
            raise ModelingPreparationError(
                f"{baseline_id.value} factory returned a fitted estimator."
            )
        declarations.append(
            {
                "baseline_id": baseline_id.value,
                "baseline_fingerprint": baseline_fingerprint(baseline_id),
                "contract": baseline_contract_payload(baseline_id),
                "estimator_class": (
                    f"{type(estimator).__module__}."
                    f"{type(estimator).__qualname__}"
                ),
                "fitted": False,
            }
        )
    return declarations


def _source_payload(
    corpus: LoadedWorkingCorpus,
    config_sha256: str,
) -> dict[str, object]:
    return {
        "corpus_contract_version": CORPUS_CONTRACT_VERSION,
        "corpus_id": corpus.config.corpus_id,
        "config_path": corpus.config.config_path.relative_to(
            corpus.config.repository_root
        ).as_posix(),
        "config_sha256": config_sha256,
        "verified_component_ids": list(corpus.verified_component_ids),
        "components": [
            {
                "component_id": component.component_id,
                "build_fingerprint": component.build_fingerprint,
                "manifest_sha256": component.manifest_sha256,
                "training_sha256": component.training_sha256,
                "training_rows": component.training_rows,
                "start_utc": component.scope.start_utc.isoformat(),
                "end_utc": component.scope.end_utc.isoformat(),
            }
            for component in corpus.config.components
        ],
        "rows": len(corpus.frame),
        "source_matches": int(
            corpus.frame["source_match_id"].nunique()
        ),
    }


def _core_payload(
    corpus: LoadedWorkingCorpus,
    split: SplitManifestResult,
    feature_audits: list[dict[str, object]],
    baseline_declarations: list[dict[str, object]],
) -> dict[str, object]:
    config_sha256 = sha256_file(corpus.config.config_path)
    return {
        "preparation_schema_version": PREPARATION_SCHEMA_VERSION,
        "preparation_version": PREPARATION_VERSION,
        "modeling_source_sha256": package_source_sha256(),
        "source": _source_payload(corpus, config_sha256),
        "split": {
            "split_contract_version": (
                CURRENT_TEMPORAL_SPLIT.contract_version
            ),
            "split_manifest_fingerprint": split.fingerprint,
            "rows": split.report["rows"],
            "source_matches": split.report["source_matches"],
            "by_role": split.report["by_role"],
        },
        "features": [
            {
                "variant": record["variant"],
                "feature_fingerprint": record["feature_fingerprint"],
                "hero_vocabulary_size": record[
                    "hero_vocabulary_size"
                ],
                "fitted_on_split_role": record[
                    "fitted_on_split_role"
                ],
                "fitted_rows": record["fitted_rows"],
                "matrix_audit_by_role": record[
                    "matrix_audit_by_role"
                ],
            }
            for record in feature_audits
        ],
        "baselines": [
            {
                "baseline_id": record["baseline_id"],
                "baseline_fingerprint": record[
                    "baseline_fingerprint"
                ],
                "estimator_class": record["estimator_class"],
                "fitted": record["fitted"],
            }
            for record in baseline_declarations
        ],
        "safety": {
            "api_dependency": False,
            "raw_json_dependency": False,
            "acquisition_dependency": False,
            "feature_vocabularies_fit_on_train_only": True,
            "locked_test_used_for_estimator_selection": False,
            "estimator_fit_performed": False,
            "hyperparameter_search_performed": False,
        },
    }


def _artifact_entry(path: Path) -> dict[str, object]:
    return {
        "file": path.name,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _result_from_existing(target: Path) -> ModelingPreparationResult:
    manifest_path = target / "infrastructure_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ModelingPreparationError(
            f"Existing M4A build is incomplete: {target}"
        ) from error
    if manifest.get("build_fingerprint") != target.name.removeprefix(
        "build_"
    ):
        raise ModelingPreparationError(
            "Existing M4A directory does not match its manifest."
        )
    for entry in manifest.get("artifacts", {}).values():
        path = target / str(entry["file"])
        if not path.is_file() or sha256_file(path) != entry["sha256"]:
            raise ModelingPreparationError(
                f"Existing M4A artifact is incomplete: {path}"
            )
    return ModelingPreparationResult(
        build_fingerprint=manifest["build_fingerprint"],
        output_directory=target,
        manifest_path=manifest_path,
        split_manifest_path=target / "split_manifest.parquet",
        split_report_path=target / "split_report.json",
        feature_contracts_path=target / "feature_contracts.json",
        baseline_contracts_path=target / "baseline_contracts.json",
        report_path=target / "preparation_report.md",
    )


def _render_report(
    build_fingerprint: str,
    core: dict[str, object],
) -> str:
    split = core["split"]
    features = core["features"]
    baselines = core["baselines"]
    lines = [
        "# Milestone 4A Modeling Infrastructure",
        "",
        f"- Build fingerprint: `{build_fingerprint}`",
        f"- Working corpus: `{core['source']['corpus_id']}`",
        f"- Supervised rows: `{core['source']['rows']}`",
        f"- Source matches: `{core['source']['source_matches']}`",
        (
            "- Split fingerprint: "
            f"`{split['split_manifest_fingerprint']}`"
        ),
        "- Estimator fit performed: `no`",
        "- Hyperparameter search performed: `no`",
        "- Authenticated API requests: `0`",
        "",
        "## Feature contracts",
        "",
        "| Variant | Vocabulary | Feature fingerprint |",
        "| --- | ---: | --- |",
    ]
    for record in features:
        lines.append(
            f"| `{record['variant']}` | "
            f"{record['hero_vocabulary_size']} | "
            f"`{record['feature_fingerprint']}` |"
        )
    lines.extend(
        [
            "",
            "## Unfitted baselines",
            "",
            "| ID | Estimator | Fitted |",
            "| --- | --- | --- |",
        ]
    )
    for record in baselines:
        lines.append(
            f"| `{record['baseline_id']}` | "
            f"`{record['estimator_class']}` | no |"
        )
    return "\n".join(lines) + "\n"


def prepare_modeling_infrastructure(
    corpus_config_path: Path,
    *,
    output_root: Path = Path("models/m4a"),
) -> ModelingPreparationResult:
    """Build the complete offline M4A infrastructure evidence."""
    corpus = load_working_corpus(corpus_config_path)
    split = build_split_manifest(corpus.frame)
    feature_audits = build_feature_audits(corpus, split)
    baseline_declarations = build_baseline_declarations()
    core = _core_payload(
        corpus,
        split,
        feature_audits,
        baseline_declarations,
    )
    fingerprint = hashlib.sha256(
        canonical_json(core).encode("utf-8")
    ).hexdigest()
    root = output_root.resolve()
    target = root / f"build_{fingerprint}"
    if target.exists():
        return _result_from_existing(target)

    target.mkdir(parents=True)
    split_manifest_path = target / "split_manifest.parquet"
    split_report_path = target / "split_report.json"
    split_report_markdown_path = target / "split_report.md"
    feature_contracts_path = target / "feature_contracts.json"
    baseline_contracts_path = target / "baseline_contracts.json"
    report_path = target / "preparation_report.md"
    manifest_path = target / "infrastructure_manifest.json"

    _write_parquet(split.manifest, split_manifest_path)
    _write_json(split_report_path, split.report)
    split_report_markdown_path.write_text(
        render_split_report_markdown(split.report),
        encoding="utf-8",
    )
    _write_json(feature_contracts_path, feature_audits)
    _write_json(baseline_contracts_path, baseline_declarations)
    report_path.write_text(
        _render_report(fingerprint, core),
        encoding="utf-8",
    )

    artifact_paths = (
        split_manifest_path,
        split_report_path,
        split_report_markdown_path,
        feature_contracts_path,
        baseline_contracts_path,
        report_path,
    )
    manifest = {
        **core,
        "build_fingerprint": fingerprint,
        "runtime_versions": {
            "python": platform.python_version(),
            "duckdb": duckdb.__version__,
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "scipy": scipy.__version__,
            "scikit_learn": sklearn.__version__,
        },
        "artifacts": {
            path.name.replace(".", "_"): _artifact_entry(path)
            for path in artifact_paths
        },
    }
    _write_json(manifest_path, manifest)
    return ModelingPreparationResult(
        build_fingerprint=fingerprint,
        output_directory=target,
        manifest_path=manifest_path,
        split_manifest_path=split_manifest_path,
        split_report_path=split_report_path,
        feature_contracts_path=feature_contracts_path,
        baseline_contracts_path=baseline_contracts_path,
        report_path=report_path,
    )
