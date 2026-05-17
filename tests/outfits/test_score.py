"""
Deterministic unit tests for each sub-scorer and the weighted combinator.

The five deterministic sub-scorers (style_match, season, occasion_match,
budget_alignment, duplicate_penalty) each return a 0.0–1.0 float. The
combinator multiplies by the locked weights from the plan:

    style_match (35) + compatibility (25) + season (15)
      + occasion_match (15) + budget_alignment (10)
      − duplicate_penalty (25)

These tests pin the *shape* of each sub-scorer at known inputs. Property
tests in test_score_properties.py pin the algebraic invariants.
"""

from __future__ import annotations

import pytest

from clawbot.outfits.score import (
    WEIGHTS,
    budget_alignment,
    duplicate_penalty,
    occasion_match,
    score_outfit,
    season_score,
    style_match,
)
from tests.outfits.conftest import make_item

# ─────────────────────────────────────────────────────────────────────────────
# style_match
# ─────────────────────────────────────────────────────────────────────────────


class TestStyleMatch:
    """style_match rewards favourite colours, penalises disliked colours."""

    def test_all_favourite_colours_returns_one(self, default_context, make_outfit):
        outfit = make_outfit(
            top=make_item(item_id="t", color_primary="navy"),
            bottom=make_item(item_id="b", category="bottoms", color_primary="olive"),
            footwear=make_item(item_id="f", category="footwear", color_primary="navy"),
        )
        assert style_match(outfit, default_context) == pytest.approx(1.0)

    def test_all_disliked_colours_returns_zero(self, default_context, make_outfit):
        outfit = make_outfit(
            top=make_item(item_id="t", color_primary="neon-pink"),
            bottom=make_item(item_id="b", category="bottoms", color_primary="neon-pink"),
            footwear=make_item(item_id="f", category="footwear", color_primary="neon-pink"),
        )
        assert style_match(outfit, default_context) == pytest.approx(0.0)

    def test_neutral_colour_returns_half(self, default_context, make_outfit):
        outfit = make_outfit(
            top=make_item(item_id="t", color_primary="grey"),
            bottom=make_item(item_id="b", category="bottoms", color_primary="grey"),
        )
        assert style_match(outfit, default_context) == pytest.approx(0.5)

    def test_missing_color_treated_as_neutral(self, default_context, make_outfit):
        outfit = make_outfit(
            top=make_item(item_id="t", color_primary=None),
        )
        assert style_match(outfit, default_context) == pytest.approx(0.5)


# ─────────────────────────────────────────────────────────────────────────────
# season_score
# ─────────────────────────────────────────────────────────────────────────────


class TestSeasonScore:
    def test_all_items_match_season(self, default_context, make_outfit):
        outfit = make_outfit(
            top=make_item(item_id="t", seasons=("fall", "winter")),
            bottom=make_item(item_id="b", category="bottoms", seasons=("fall",)),
        )
        assert season_score(outfit, default_context) == pytest.approx(1.0)

    def test_no_items_match_returns_zero(self, default_context, make_outfit):
        outfit = make_outfit(
            top=make_item(item_id="t", seasons=("summer",)),
        )
        assert season_score(outfit, default_context) == pytest.approx(0.0)

    def test_half_items_match_returns_half(self, default_context, make_outfit):
        outfit = make_outfit(
            top=make_item(item_id="t", seasons=("fall",)),
            bottom=make_item(item_id="b", category="bottoms", seasons=("summer",)),
        )
        assert season_score(outfit, default_context) == pytest.approx(0.5)


# ─────────────────────────────────────────────────────────────────────────────
# occasion_match
# ─────────────────────────────────────────────────────────────────────────────


class TestOccasionMatch:
    """Occasion to formality mapping is implicit:

        casual         ↔ very-casual / casual
        smart-casual   ↔ casual / smart-casual
        business       ↔ smart-casual / business
        formal         ↔ business / formal

    Score is 1.0 when every item's formality is at the right tier, scales
    down by the formality distance otherwise.
    """

    def test_exact_match(self, default_context, make_outfit):
        outfit = make_outfit(
            top=make_item(item_id="t", formality="casual"),
            bottom=make_item(item_id="b", category="bottoms", formality="casual"),
        )
        # default_context.occasion == "casual"
        assert occasion_match(outfit, default_context) == pytest.approx(1.0)

    def test_one_step_off_partial_score(self, default_context, make_outfit):
        outfit = make_outfit(
            top=make_item(item_id="t", formality="business"),
        )
        # casual vs business = distance 2 out of max 4 → score ≤ 0.5
        score = occasion_match(outfit, default_context)
        assert 0.0 < score < 1.0

    def test_unknown_formality_neutral(self, default_context, make_outfit):
        outfit = make_outfit(top=make_item(item_id="t", formality=None))
        assert occasion_match(outfit, default_context) == pytest.approx(0.5)


# ─────────────────────────────────────────────────────────────────────────────
# budget_alignment
# ─────────────────────────────────────────────────────────────────────────────


class TestBudgetAlignment:
    """1.0 when outfit total ≤ budget; decays toward 0 as total grows."""

    def test_under_budget_returns_one(self, default_context, make_outfit):
        outfit = make_outfit(
            top=make_item(item_id="t", purchase_price_usd=20.0),
            bottom=make_item(item_id="b", category="bottoms", purchase_price_usd=30.0),
        )
        # default budget = 300
        assert budget_alignment(outfit, default_context) == pytest.approx(1.0)

    def test_at_budget_returns_one(self, default_context, make_outfit):
        outfit = make_outfit(
            top=make_item(item_id="t", purchase_price_usd=300.0),
        )
        assert budget_alignment(outfit, default_context) == pytest.approx(1.0)

    def test_double_budget_returns_half(self, default_context, make_outfit):
        outfit = make_outfit(
            top=make_item(item_id="t", purchase_price_usd=600.0),
        )
        assert budget_alignment(outfit, default_context) == pytest.approx(0.5)

    def test_missing_prices_treated_as_zero(self, default_context, make_outfit):
        outfit = make_outfit(top=make_item(item_id="t", purchase_price_usd=None))
        assert budget_alignment(outfit, default_context) == pytest.approx(1.0)


# ─────────────────────────────────────────────────────────────────────────────
# duplicate_penalty
# ─────────────────────────────────────────────────────────────────────────────


class TestDuplicatePenalty:
    """Fraction of items in the recently-worn set."""

    def test_none_recent_returns_zero(self, default_context, make_outfit):
        outfit = make_outfit(top=make_item(item_id="t"))
        assert duplicate_penalty(outfit, default_context) == pytest.approx(0.0)

    def test_all_recent_returns_one(self, make_outfit, default_context):
        ctx = default_context.with_recently_worn({"t", "b"})
        outfit = make_outfit(
            top=make_item(item_id="t"),
            bottom=make_item(item_id="b", category="bottoms"),
        )
        assert duplicate_penalty(outfit, ctx) == pytest.approx(1.0)

    def test_half_recent_returns_half(self, default_context, make_outfit):
        ctx = default_context.with_recently_worn({"t"})
        outfit = make_outfit(
            top=make_item(item_id="t"),
            bottom=make_item(item_id="b", category="bottoms"),
        )
        assert duplicate_penalty(outfit, ctx) == pytest.approx(0.5)


# ─────────────────────────────────────────────────────────────────────────────
# score_outfit (combinator)
# ─────────────────────────────────────────────────────────────────────────────


class TestScoreOutfit:
    def test_weights_sum_to_documented_total(self):
        # Positive weights sum to 100; duplicate_penalty is subtracted.
        positive = (
            WEIGHTS["style_match"]
            + WEIGHTS["compatibility"]
            + WEIGHTS["season"]
            + WEIGHTS["occasion_match"]
            + WEIGHTS["budget_alignment"]
        )
        assert positive == 100
        assert WEIGHTS["duplicate_penalty"] == 25

    def test_breakdown_keys_present(self, default_context, make_outfit):
        outfit = make_outfit(
            top=make_item(item_id="t"), bottom=make_item(item_id="b", category="bottoms")
        )
        result = score_outfit(outfit, default_context)
        assert set(result.breakdown.keys()) == {
            "style_match",
            "compatibility",
            "season",
            "occasion_match",
            "budget_alignment",
            "duplicate_penalty",
        }

    def test_total_equals_weighted_sum(self, default_context, make_outfit):
        outfit = make_outfit(
            top=make_item(item_id="t"), bottom=make_item(item_id="b", category="bottoms")
        )
        result = score_outfit(outfit, default_context)
        expected = (
            result.breakdown["style_match"]
            + result.breakdown["compatibility"]
            + result.breakdown["season"]
            + result.breakdown["occasion_match"]
            + result.breakdown["budget_alignment"]
            - result.breakdown["duplicate_penalty"]
        )
        assert result.total == pytest.approx(expected)

    def test_perfect_outfit_scores_at_most_100(self, default_context, make_outfit):
        outfit = make_outfit(
            top=make_item(
                item_id="t",
                color_primary="navy",
                formality="casual",
                seasons=("fall",),
                purchase_price_usd=0.0,
            ),
        )
        result = score_outfit(outfit, default_context)
        assert result.total <= 100.0
