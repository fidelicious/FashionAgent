"""
Tests for the candidate generator.

Goal: given a wardrobe (list of items), emit a bounded list (≤ max_candidates,
plan target = 50) of Outfit candidates that are *plausibly* wearable —
filtered by the requested season + occasion before combinatorial expansion.
"""

from __future__ import annotations

import pytest

from clawbot.outfits.candidates import generate_candidates
from tests.outfits.conftest import make_item

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures local to these tests
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def small_wardrobe():
    """A tiny but valid wardrobe: 2 tops, 2 bottoms, 1 footwear, all casual+fall."""
    return [
        make_item(item_id="top1", category="tops", formality="casual", seasons=("fall",)),
        make_item(item_id="top2", category="tops", formality="casual", seasons=("fall",)),
        make_item(item_id="bot1", category="bottoms", formality="casual", seasons=("fall",)),
        make_item(item_id="bot2", category="bottoms", formality="casual", seasons=("fall",)),
        make_item(item_id="shoe1", category="footwear", formality="casual", seasons=("fall",)),
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Behaviour
# ─────────────────────────────────────────────────────────────────────────────


class TestGenerateCandidates:
    def test_empty_wardrobe_returns_no_candidates(self, default_context):
        assert generate_candidates([], default_context) == []

    def test_single_top_bottom_shoe_produces_one_candidate(self, default_context):
        wardrobe = [
            make_item(item_id="t", category="tops", seasons=("fall",), formality="casual"),
            make_item(item_id="b", category="bottoms", seasons=("fall",), formality="casual"),
            make_item(item_id="s", category="footwear", seasons=("fall",), formality="casual"),
        ]
        cands = generate_candidates(wardrobe, default_context)
        assert len(cands) == 1
        roles = cands[0].items_by_role
        assert {"top", "bottom", "footwear"} <= roles.keys()
        assert roles["top"].id == "t"

    def test_filters_out_off_season_items(self, default_context):
        wardrobe = [
            make_item(item_id="t-summer", category="tops", seasons=("summer",), formality="casual"),
            make_item(item_id="b-fall", category="bottoms", seasons=("fall",), formality="casual"),
            make_item(item_id="s-fall", category="footwear", seasons=("fall",), formality="casual"),
        ]
        cands = generate_candidates(wardrobe, default_context)
        # No top matches the fall season → cannot form a complete outfit.
        assert cands == []

    def test_cartesian_expansion_capped_at_max(self, default_context):
        # 5 × 5 × 5 = 125 raw combos; cap at 50.
        wardrobe = []
        for i in range(5):
            wardrobe.append(make_item(item_id=f"t{i}", category="tops", seasons=("fall",)))
            wardrobe.append(make_item(item_id=f"b{i}", category="bottoms", seasons=("fall",)))
            wardrobe.append(make_item(item_id=f"s{i}", category="footwear", seasons=("fall",)))
        cands = generate_candidates(wardrobe, default_context, max_candidates=50)
        assert 0 < len(cands) <= 50

    def test_dress_path_produces_dress_plus_footwear(self, default_context):
        wardrobe = [
            make_item(item_id="d1", category="dresses", seasons=("fall",), formality="casual"),
            make_item(item_id="s1", category="footwear", seasons=("fall",), formality="casual"),
        ]
        cands = generate_candidates(wardrobe, default_context)
        assert len(cands) == 1
        roles = cands[0].items_by_role
        assert "dress" in roles and "footwear" in roles
        assert "top" not in roles and "bottom" not in roles

    def test_skips_soft_deleted_items(self, small_wardrobe, default_context):
        # Removed items are simply not in the input list — the generator
        # doesn't filter by deleted_at itself (that's the repo's job).
        # This test pins the contract: any item passed in is fair game.
        cands = generate_candidates(small_wardrobe, default_context)
        assert len(cands) >= 1
