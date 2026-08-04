"""Offline tests for the pure-logic parts of hero_mapping.py.

fetch_opendota_heroes() itself is network-touching and untested here;
these tests exercise build_hero_id_mapping and
apply_corpus_confirmed_additions against synthetic OpenDotaHero objects.
"""

from __future__ import annotations

import pytest

from src.patch_alignment.hero_mapping import (
    HeroMappingError,
    OpenDotaHero,
    apply_corpus_confirmed_additions,
    build_hero_id_mapping,
)


def test_build_hero_id_mapping_reports_unmatched_on_both_sides() -> None:
    opendota_heroes = [
        OpenDotaHero(hero_id=1, localized_name="Alpha", normalized_key="alpha"),
        OpenDotaHero(hero_id=2, localized_name="Beta", normalized_key="beta"),
        OpenDotaHero(hero_id=3, localized_name="Gamma", normalized_key="gamma"),
    ]
    vocabulary = ("alpha", "beta", "delta")

    result = build_hero_id_mapping(opendota_heroes, vocabulary)

    assert {item["hero_key"] for item in result.mapped} == {"alpha", "beta"}
    assert result.unmatched_vocabulary == ("delta",)
    assert [entry["hero_id"] for entry in result.unmatched_opendota] == [3]


def test_build_hero_id_mapping_rejects_ambiguous_normalized_keys() -> None:
    opendota_heroes = [
        OpenDotaHero(hero_id=1, localized_name="Alpha", normalized_key="alpha"),
        OpenDotaHero(hero_id=2, localized_name="Alpha Prime", normalized_key="alpha"),
    ]
    with pytest.raises(HeroMappingError):
        build_hero_id_mapping(opendota_heroes, ("alpha",))


def test_apply_corpus_confirmed_additions_adds_a_validated_entry() -> None:
    opendota_heroes = [
        OpenDotaHero(hero_id=1, localized_name="Alpha", normalized_key="alpha"),
        OpenDotaHero(hero_id=145, localized_name="Kez", normalized_key="kez"),
    ]
    result = build_hero_id_mapping(opendota_heroes, ("alpha",))
    assert {entry["hero_id"] for entry in result.unmatched_opendota} == {145}

    updated, applied_count = apply_corpus_confirmed_additions(
        result,
        opendota_heroes,
        additions=(
            {"hero_key": "kez", "hero_id": 145, "opendota_localized_name": "Kez"},
        ),
    )

    assert applied_count == 1
    assert {item["hero_key"] for item in updated.mapped} == {"alpha", "kez"}
    assert updated.unmatched_opendota == ()


def test_apply_corpus_confirmed_additions_skips_already_mapped_hero_key() -> None:
    opendota_heroes = [OpenDotaHero(hero_id=1, localized_name="Alpha", normalized_key="alpha")]
    result = build_hero_id_mapping(opendota_heroes, ("alpha",))

    updated, applied_count = apply_corpus_confirmed_additions(
        result,
        opendota_heroes,
        additions=(
            {"hero_key": "alpha", "hero_id": 1, "opendota_localized_name": "Alpha"},
        ),
    )

    assert applied_count == 0
    assert len(updated.mapped) == 1


def test_apply_corpus_confirmed_additions_rejects_missing_hero_id() -> None:
    opendota_heroes = [OpenDotaHero(hero_id=1, localized_name="Alpha", normalized_key="alpha")]
    result = build_hero_id_mapping(opendota_heroes, ("alpha",))

    with pytest.raises(HeroMappingError):
        apply_corpus_confirmed_additions(
            result,
            opendota_heroes,
            additions=(
                {"hero_key": "kez", "hero_id": 145, "opendota_localized_name": "Kez"},
            ),
        )


def test_apply_corpus_confirmed_additions_rejects_name_drift() -> None:
    opendota_heroes = [
        OpenDotaHero(hero_id=1, localized_name="Alpha", normalized_key="alpha"),
        OpenDotaHero(hero_id=145, localized_name="Renamed Hero", normalized_key="renamed-hero"),
    ]
    result = build_hero_id_mapping(opendota_heroes, ("alpha",))

    with pytest.raises(HeroMappingError):
        apply_corpus_confirmed_additions(
            result,
            opendota_heroes,
            additions=(
                {"hero_key": "kez", "hero_id": 145, "opendota_localized_name": "Kez"},
            ),
        )
