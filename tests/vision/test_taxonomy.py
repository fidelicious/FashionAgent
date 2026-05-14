"""
Tests for clawbot.vision.taxonomy.

Constants only — these checks ensure the taxonomy matches the project plan
(every category in the schema has a prompt; every category has a
non-empty subcategory dict; formality and season prompts cover the
documented enums).
"""

from __future__ import annotations

from clawbot.vision.taxonomy import (
    CATEGORY_PROMPTS,
    FORMALITY_PROMPTS,
    SEASON_PROMPTS,
    SUBCATEGORY_PROMPTS,
)

# Locked from fashionClaw.md + the build plan. Update both if you change this.
EXPECTED_CATEGORIES = {
    "tops",
    "bottoms",
    "dresses",
    "outerwear",
    "footwear",
    "accessories",
    "underlayers",
    "activewear",
}

EXPECTED_FORMALITY = {
    "very-casual",
    "casual",
    "smart-casual",
    "business",
    "formal",
}

EXPECTED_SEASONS = {"spring", "summer", "fall", "winter"}


def test_category_prompts_cover_all_categories() -> None:
    assert set(CATEGORY_PROMPTS.keys()) == EXPECTED_CATEGORIES


def test_formality_prompts_cover_all_levels() -> None:
    assert set(FORMALITY_PROMPTS.keys()) == EXPECTED_FORMALITY


def test_season_prompts_cover_all_seasons() -> None:
    assert set(SEASON_PROMPTS.keys()) == EXPECTED_SEASONS


def test_all_prompts_are_nonempty_strings() -> None:
    for d in (CATEGORY_PROMPTS, FORMALITY_PROMPTS, SEASON_PROMPTS):
        for k, v in d.items():
            assert isinstance(v, str), f"{k!r} prompt is not a string"
            assert v.strip(), f"{k!r} prompt is empty"


def test_subcategory_dict_has_one_entry_per_category() -> None:
    assert set(SUBCATEGORY_PROMPTS.keys()) == EXPECTED_CATEGORIES


def test_each_subcategory_dict_is_nonempty() -> None:
    for category, subs in SUBCATEGORY_PROMPTS.items():
        assert subs, f"category {category!r} has no subcategory prompts"
        for sub_name, prompt in subs.items():
            assert isinstance(prompt, str) and prompt.strip(), (
                f"{category}.{sub_name} prompt is empty"
            )


def test_known_subcategories_present() -> None:
    # Sanity-check a handful of subcategories named in the V1 plan.
    assert "cardigan" in SUBCATEGORY_PROMPTS["tops"]
    assert "jeans" in SUBCATEGORY_PROMPTS["bottoms"]
    assert "ankle-boot" in SUBCATEGORY_PROMPTS["footwear"]
    assert "blazer" in SUBCATEGORY_PROMPTS["outerwear"]
