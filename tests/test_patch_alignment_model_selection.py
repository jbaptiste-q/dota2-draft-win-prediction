"""Offline tests for Milestone 9 Phase 2 Step 2A: stratified sampling."""

from __future__ import annotations

import pytest

from src.patch_alignment.change_flattening import FlattenedChange
from src.patch_alignment.model_selection import stratified_sample


def build_population() -> list[FlattenedChange]:
    changes = []
    scopes = ("hero", "ability", "talent", "general")
    for patch_index in range(5):
        for scope_index, scope in enumerate(scopes):
            for item_index in range(6):
                changes.append(
                    FlattenedChange(
                        change_uid=f"p{patch_index}-{scope}-{item_index}",
                        patch=f"9.{patch_index}",
                        hero_id=item_index,
                        hero_key=f"hero_{item_index}",
                        json_path=f"heroes[{item_index}]",
                        scope=scope,
                        raw_text=f"fixture text {patch_index}-{scope}-{item_index}",
                    )
                )
    return changes


def test_stratified_sample_returns_requested_size_and_excludes_general_scope() -> None:
    population = build_population()
    sample = stratified_sample(population, sample_size=20, seed=1)
    assert len(sample) == 20
    assert {c.scope for c in sample} <= {"hero", "ability", "talent"}


def test_stratified_sample_is_deterministic_for_a_fixed_seed() -> None:
    population = build_population()
    first = stratified_sample(population, sample_size=20, seed=42)
    second = stratified_sample(population, sample_size=20, seed=42)
    assert [c.change_uid for c in first] == [c.change_uid for c in second]


def test_stratified_sample_differs_across_seeds() -> None:
    population = build_population()
    sample_a = stratified_sample(population, sample_size=20, seed=1)
    sample_b = stratified_sample(population, sample_size=20, seed=2)
    assert [c.change_uid for c in sample_a] != [c.change_uid for c in sample_b]


def test_stratified_sample_rejects_oversized_request() -> None:
    population = build_population()
    with pytest.raises(ValueError):
        stratified_sample(population, sample_size=10_000, seed=1)


def test_stratified_sample_rejects_empty_population() -> None:
    with pytest.raises(ValueError):
        stratified_sample([], sample_size=5, seed=1)
