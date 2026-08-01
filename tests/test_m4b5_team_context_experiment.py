"""Safety-focused tests for the bounded M4B.5 runner."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from src.draft_ai_modeling import team_context_experiment as experiment


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "configs/modeling/m4b5_team_context.json"


def _metrics() -> dict[str, dict[str, float]]:
    return {
        name: {"log_loss": 0.6, "brier_score": 0.2}
        for name in ("joint", "team_only", "frozen_b1", "canonical_b0")
    }


def test_failed_development_gate_never_opens_q4(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    config = SimpleNamespace(
        payload=payload,
        fingerprint="f" * 64,
        config_path=CONFIG_PATH,
        source_paths={"corpus_config": Path("/not-opened/corpus.json")},
        repository_root=ROOT,
        development_end_utc=pd.Timestamp("2025-10-01", tz="UTC").to_pydatetime(),
        q4_end_utc=pd.Timestamp("2026-01-01", tz="UTC").to_pydatetime(),
    )
    prefix = SimpleNamespace(
        frame=pd.DataFrame(index=range(20_087)),
        verified_component_ids=("through-2025-Q3",),
    )
    opened: list[object] = []

    def load_prefix(*args: object, **kwargs: object) -> object:
        opened.append(kwargs["end_utc"])
        return prefix

    development_predictions = pd.DataFrame(
        {
            "sample_id": ["sample"],
            "joint_probability": [0.5],
        }
    )
    development_evaluation = {
        "qualified": False,
        "passed": False,
        "metrics": {"recent_pooled": _metrics()},
    }

    monkeypatch.setattr(
        experiment,
        "load_team_context_experiment_config",
        lambda *args, **kwargs: config,
    )
    monkeypatch.setattr(experiment, "_source_sha256", lambda: "s" * 64)
    monkeypatch.setattr(experiment, "_runtime_versions", lambda: {})
    monkeypatch.setattr(experiment, "load_working_corpus_prefix", load_prefix)
    monkeypatch.setattr(
        experiment,
        "_load_development_references",
        lambda config: pd.DataFrame(),
    )
    monkeypatch.setattr(
        experiment,
        "_development_predictions",
        lambda *args: (development_predictions, []),
    )
    monkeypatch.setattr(
        experiment,
        "evaluate_team_context_development",
        lambda *args, **kwargs: development_evaluation,
    )
    monkeypatch.setattr(
        experiment,
        "_verify_q4_prediction_pin",
        lambda *args: pytest.fail("Q4 evidence must remain unopened."),
    )

    result = experiment.run_team_context_experiment(
        CONFIG_PATH,
        output_root=tmp_path / "models",
        repository_root=ROOT,
    )

    assert result.development_qualified is False
    assert result.q4_opened is False
    assert result.q4_readiness_passed is None
    assert opened == [config.development_end_utc]


class _Audit:
    def to_payload(self) -> dict[str, object]:
        return {"passed": True}


def test_q4_team_transform_receives_no_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    config = SimpleNamespace(
        payload=payload,
        source_paths={"m4b3_readiness": Path("/not-opened/readiness.json")},
    )
    timestamps = pd.to_datetime(
        ["2025-09-01T00:00:00Z", "2025-10-02T00:00:00Z"],
        utc=True,
    )
    base = pd.DataFrame(
        {
            "sample_id": ["base"],
            "source_match_id": ["base-series"],
            "radiant_win": [True],
            "match_start_utc": [timestamps[0]],
        }
    )
    q4 = pd.DataFrame(
        {
            "sample_id": ["q4"],
            "source_match_id": ["q4-series"],
            "radiant_win": [False],
            "match_start_utc": [timestamps[1]],
            "patch": ["7.39"],
        }
    )
    history_result = SimpleNamespace(
        features=pd.DataFrame({"sample_id": ["base"], "elo_logit": [0.0]}),
        state=object(),
        audit=_Audit(),
    )
    frozen_result = SimpleNamespace(
        features=pd.DataFrame({"sample_id": ["q4"], "elo_logit": [0.25]}),
        audit=_Audit(),
    )

    monkeypatch.setattr(
        experiment,
        "build_training_team_strength",
        lambda *args, **kwargs: history_result,
    )

    def frozen_transform(
        frame: pd.DataFrame,
        *args: object,
        **kwargs: object,
    ) -> object:
        assert "radiant_win" not in frame.columns
        return frozen_result

    monkeypatch.setattr(
        experiment,
        "transform_frozen_team_strength",
        frozen_transform,
    )
    monkeypatch.setattr(
        experiment,
        "_fit_two_models",
        lambda *args, **kwargs: (
            np.asarray([0.6]),
            np.asarray([0.55]),
            {"fit_rows": 1},
        ),
    )
    monkeypatch.setattr(
        experiment,
        "_load_q4_reference",
        lambda *args: pd.DataFrame(
            {
                "sample_id": ["q4"],
                "source_match_id": ["q4-series"],
                "radiant_win": [0],
                "frozen_b1_probability": [0.51],
            }
        ),
    )
    monkeypatch.setattr(
        experiment,
        "_read_json",
        lambda *args, **kwargs: {"base_prior": 1.0},
    )

    predictions, audit = experiment._q4_predictions(base, q4, config)

    assert predictions["joint_probability"].tolist() == [0.6]
    assert predictions["elo_logit"].tolist() == [0.25]
    assert audit["evaluation_target_passed_to_team_transform"] is False
