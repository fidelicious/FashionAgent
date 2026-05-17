"""
Tests for the db→scoring dataclass adapter.

Two adapters live in clawbot.outfits.adapter:
  - from_db_item(): db.repo.WardrobeItem → outfits.types.WardrobeItem
  - build_scoring_context(): user_profile dict (+ optional overrides)
                              → outfits.types.ScoringContext

These are pure data transforms — no DB, no IO. Tests exercise field-by-field
mapping and the "missing field defaults to safe value" behaviour the scorer
relies on.
"""

from __future__ import annotations

from datetime import date

from clawbot.db.repo import WardrobeItem as DbWardrobeItem
from clawbot.outfits.adapter import (
    build_scoring_context,
    derive_season,
    from_db_item,
)
from clawbot.outfits.types import ScoringContext, WardrobeItem

# ─────────────────────────────────────────────────────────────────────────────
# from_db_item
# ─────────────────────────────────────────────────────────────────────────────


class TestFromDbItem:
    def test_maps_basic_fields(self):
        db_item = DbWardrobeItem(
            id="abc",
            category="tops",
            subcategory="cardigan",
            color_primary="navy",
            formality="smart-casual",
            seasons=["fall", "winter"],
            purchase_price_usd=89.0,
            pairs_well_with=["b1"],
            avoid_pairing_with=["b2"],
            wear_count=3,
            last_worn_date="2026-03-15",
        )
        scoring = from_db_item(db_item)
        assert isinstance(scoring, WardrobeItem)
        assert scoring.id == "abc"
        assert scoring.category == "tops"
        assert scoring.subcategory == "cardigan"
        assert scoring.color_primary == "navy"
        assert scoring.formality == "smart-casual"
        assert scoring.seasons == ("fall", "winter")
        assert scoring.purchase_price_usd == 89.0
        assert scoring.pairs_well_with == ("b1",)
        assert scoring.avoid_pairing_with == ("b2",)
        assert scoring.wear_count == 3
        assert scoring.last_worn_date == date(2026, 3, 15)

    def test_missing_seasons_defaults_to_empty_tuple(self):
        db_item = DbWardrobeItem(id="x", category="tops", seasons=None)
        scoring = from_db_item(db_item)
        assert scoring.seasons == ()
        assert scoring.pairs_well_with == ()
        assert scoring.avoid_pairing_with == ()

    def test_missing_id_raises(self):
        # An item without an id can't be scored — the repo always assigns one
        # at insert time, so this only happens on a programming error.
        db_item = DbWardrobeItem(id=None, category="tops")
        try:
            from_db_item(db_item)
        except ValueError:
            return
        raise AssertionError("expected ValueError for id=None")

    def test_unparseable_last_worn_date_becomes_none(self):
        db_item = DbWardrobeItem(id="x", category="tops", last_worn_date="not-a-date")
        scoring = from_db_item(db_item)
        assert scoring.last_worn_date is None

    def test_embedding_is_none_until_image_pipeline_runs(self):
        # The DB stores embeddings in a separate vec0 table; from_db_item
        # doesn't reach across to fetch them. Daily-push pre-fetches and
        # patches the WardrobeItem in batch if it cares about compatibility.
        db_item = DbWardrobeItem(id="x", category="tops")
        scoring = from_db_item(db_item)
        assert scoring.embedding is None


# ─────────────────────────────────────────────────────────────────────────────
# build_scoring_context
# ─────────────────────────────────────────────────────────────────────────────


class TestBuildScoringContext:
    def test_pulls_colours_and_budget_from_profile(self):
        profile = {
            "favorite_colors_json": '["navy", "olive"]',
            "disliked_colors_json": '["neon-pink"]',
            "monthly_clothing_budget_usd": 250,
        }
        ctx = build_scoring_context(profile, occasion="casual", season="fall")
        assert isinstance(ctx, ScoringContext)
        assert ctx.favorite_colors == frozenset({"navy", "olive"})
        assert ctx.disliked_colors == frozenset({"neon-pink"})
        assert ctx.monthly_budget_usd == 250.0
        assert ctx.occasion == "casual"
        assert ctx.season == "fall"

    def test_empty_profile_yields_neutral_context(self):
        ctx = build_scoring_context({}, occasion="casual", season="fall")
        assert ctx.favorite_colors == frozenset()
        assert ctx.disliked_colors == frozenset()
        assert ctx.monthly_budget_usd is None

    def test_recently_worn_passed_through(self):
        ctx = build_scoring_context(
            {}, occasion="casual", season="fall", recently_worn_ids={"a", "b"}
        )
        assert ctx.recently_worn_ids == frozenset({"a", "b"})


# ─────────────────────────────────────────────────────────────────────────────
# derive_season
# ─────────────────────────────────────────────────────────────────────────────


class TestDeriveSeason:
    """Northern-hemisphere meteorological seasons."""

    def test_winter(self):
        assert derive_season(date(2026, 1, 15)) == "winter"
        assert derive_season(date(2026, 12, 20)) == "winter"

    def test_spring(self):
        assert derive_season(date(2026, 3, 15)) == "spring"

    def test_summer(self):
        assert derive_season(date(2026, 7, 4)) == "summer"

    def test_fall(self):
        assert derive_season(date(2026, 10, 31)) == "fall"
