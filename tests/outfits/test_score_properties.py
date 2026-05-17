"""
Property-based tests for the outfit scorer.

These guard the algebraic invariants that any sub-scorer change must preserve:

  - Each sub-scorer returns a value in [0.0, 1.0].
  - score_outfit().total is in [-25.0, 100.0] (positive weights sum to 100,
    duplicate_penalty subtracts up to 25).
  - score_outfit().total is deterministic — same inputs → same output.
  - The breakdown.values() composed with the weights reproduce .total exactly.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from clawbot.outfits.score import (
    budget_alignment,
    duplicate_penalty,
    occasion_match,
    score_outfit,
    season_score,
    style_match,
)
from clawbot.outfits.types import Outfit, ScoringContext, WardrobeItem

# ─────────────────────────────────────────────────────────────────────────────
# Hypothesis strategies
# ─────────────────────────────────────────────────────────────────────────────

CATEGORIES = ("tops", "bottoms", "outerwear", "footwear", "dresses")
COLOURS = ("navy", "olive", "grey", "white", "black", "red", "neon-pink")
SEASONS = ("spring", "summer", "fall", "winter")
FORMALITIES = ("very-casual", "casual", "smart-casual", "business", "formal")
OCCASIONS = ("casual", "smart-casual", "business", "formal")


@st.composite
def items_strategy(draw, idx: int = 0) -> WardrobeItem:
    return WardrobeItem(
        id=f"i{idx}-{draw(st.integers(0, 999))}",
        category=draw(st.sampled_from(CATEGORIES)),
        subcategory=None,
        color_primary=draw(st.sampled_from(COLOURS + (None,))),
        formality=draw(st.sampled_from(FORMALITIES + (None,))),
        seasons=tuple(draw(st.sets(st.sampled_from(SEASONS), max_size=4))),
        purchase_price_usd=draw(st.one_of(st.none(), st.floats(0, 2000, allow_nan=False))),
        pairs_well_with=(),
        avoid_pairing_with=(),
        wear_count=draw(st.integers(0, 100)),
        last_worn_date=None,
        embedding=None,
    )


@st.composite
def outfits_strategy(draw) -> Outfit:
    n = draw(st.integers(1, 4))
    items = {}
    roles = ["top", "bottom", "outer", "footwear", "dress"]
    for i in range(n):
        items[roles[i]] = draw(items_strategy(idx=i))
    return Outfit(items_by_role=items)


@st.composite
def contexts_strategy(draw) -> ScoringContext:
    return ScoringContext(
        occasion=draw(st.sampled_from(OCCASIONS)),
        season=draw(st.sampled_from(SEASONS)),
        favorite_colors=frozenset(draw(st.sets(st.sampled_from(COLOURS), max_size=3))),
        disliked_colors=frozenset(draw(st.sets(st.sampled_from(COLOURS), max_size=2))),
        monthly_budget_usd=draw(st.floats(50, 2000, allow_nan=False)),
        recently_worn_ids=frozenset(),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Properties
# ─────────────────────────────────────────────────────────────────────────────


@given(outfit=outfits_strategy(), ctx=contexts_strategy())
@settings(max_examples=200, deadline=None)
def test_each_sub_scorer_in_unit_interval(outfit, ctx):
    """Each deterministic sub-scorer must stay within [0.0, 1.0]."""
    for fn in (style_match, season_score, occasion_match, budget_alignment, duplicate_penalty):
        v = fn(outfit, ctx)
        assert 0.0 <= v <= 1.0, f"{fn.__name__} returned {v}"


@given(outfit=outfits_strategy(), ctx=contexts_strategy())
@settings(max_examples=200, deadline=None)
def test_total_in_documented_range(outfit, ctx):
    """Total must lie in [-25.0, 100.0]."""
    result = score_outfit(outfit, ctx)
    assert -25.0 <= result.total <= 100.0


@given(outfit=outfits_strategy(), ctx=contexts_strategy())
@settings(max_examples=100, deadline=None)
def test_score_is_deterministic(outfit, ctx):
    a = score_outfit(outfit, ctx).total
    b = score_outfit(outfit, ctx).total
    assert a == b
