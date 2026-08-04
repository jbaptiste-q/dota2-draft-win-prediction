"""Offline tests for Milestone 9 Phase 2 Step 2A: stratified sampling."""

from __future__ import annotations

import pytest

from src.patch_alignment.change_flattening import FlattenedChange
from src.patch_alignment.model_selection import draw_screening_pool, interleave, stratified_sample


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


def test_draw_screening_pool_excludes_given_uids() -> None:
    population = build_population()
    exclude = {c.change_uid for c in population[:10]}
    pool = draw_screening_pool(population, exclude_uids=exclude, pool_size=15, seed=1)
    assert not (exclude & {c.change_uid for c in pool})
    assert {c.scope for c in pool} <= {"hero", "ability", "talent"}


def test_draw_screening_pool_is_deterministic() -> None:
    population = build_population()
    exclude = {c.change_uid for c in population[:5]}
    first = draw_screening_pool(population, exclude_uids=exclude, pool_size=10, seed=7)
    second = draw_screening_pool(population, exclude_uids=exclude, pool_size=10, seed=7)
    assert [c.change_uid for c in first] == [c.change_uid for c in second]


def test_draw_screening_pool_caps_at_available_population() -> None:
    population = build_population()
    exclude = {c.change_uid for c in population}  # exclude everything
    pool = draw_screening_pool(population, exclude_uids=exclude, pool_size=50, seed=1)
    assert pool == []


def test_interleave_is_deterministic_and_preserves_membership() -> None:
    population = build_population()
    sample = stratified_sample(population, sample_size=10, seed=1)
    first = interleave(sample)
    second = interleave(sample)
    assert [c.change_uid for c in first] == [c.change_uid for c in second]
    assert {c.change_uid for c in first} == {c.change_uid for c in sample}


def test_interleave_actually_reorders() -> None:
    population = build_population()
    sample = stratified_sample(population, sample_size=15, seed=1)
    original_order = [c.change_uid for c in sample]
    shuffled_order = [c.change_uid for c in interleave(sample)]
    assert shuffled_order != original_order
