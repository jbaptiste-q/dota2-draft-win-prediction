"""Leakage-safe modeling infrastructure for the Dota 2 Draft AI."""

from .baseline_experiment import run_baseline_experiment
from .baselines import BaselineId, create_unfitted_estimator
from .calibration_experiment import run_calibration_experiment
from .features import DraftFeatureTransformer, FeatureVariant
from .interaction_experiment import run_interaction_experiment
from .interaction_features import PickInteractionTransformer
from .loader import load_working_corpus
from .preparation import prepare_modeling_infrastructure
from .splits import build_split_manifest

__all__ = [
    "BaselineId",
    "DraftFeatureTransformer",
    "FeatureVariant",
    "PickInteractionTransformer",
    "build_split_manifest",
    "create_unfitted_estimator",
    "load_working_corpus",
    "prepare_modeling_infrastructure",
    "run_baseline_experiment",
    "run_calibration_experiment",
    "run_interaction_experiment",
]
