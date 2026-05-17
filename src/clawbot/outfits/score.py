"""
Deterministic outfit scorer (build step 10).

Formula locked in the plan:

    total = style_match * 35
          + compatibility * 25      ← computed by compatibility.py
          + season * 15
          + occasion_match * 15
          + budget_alignment * 10
          - duplicate_penalty * 25

Each sub-scorer returns a 0.0–1.0 float; the combinator applies the weights
and assembles a ScoredOutfit. The breakdown returned to callers is in
*weighted points* (e.g. style_match: 28.0, not 0.8) so logs / Discord
embeds can show "where the points came from" without recomputing weights.
"""

from __future__ import annotations

from collections.abc import Mapping

from clawbot.outfits.compatibility import compute_compatibility
from clawbot.outfits.types import Outfit, ScoredOutfit, ScoringContext

# ─────────────────────────────────────────────────────────────────────────────
# Locked weights — change here, not at call sites.
# ─────────────────────────────────────────────────────────────────────────────
WEIGHTS: Mapping[str, int] = {
    "style_match": 35,
    "compatibility": 25,
    "season": 15,
    "occasion_match": 15,
    "budget_alignment": 10,
    "duplicate_penalty": 25,  # subtracted, not added
}


# ─────────────────────────────────────────────────────────────────────────────
# Formality ladder used by occasion_match.
# Distance on this ladder maps to a partial score: distance 0 → 1.0, max → 0.0.
# Unknown / None formalities are treated as neutral (0.5).
# ─────────────────────────────────────────────────────────────────────────────
_FORMALITY_LADDER = ("very-casual", "casual", "smart-casual", "business", "formal")
_FORMALITY_INDEX = {f: i for i, f in enumerate(_FORMALITY_LADDER)}
_MAX_FORMALITY_DISTANCE = len(_FORMALITY_LADDER) - 1

# Map an occasion to its preferred formality tier on the same ladder. Occasions
# not in the map fall back to the occasion string itself if it's a formality,
# else "casual".
_OCCASION_TO_FORMALITY: Mapping[str, str] = {
    "casual": "casual",
    "smart-casual": "smart-casual",
    "business": "business",
    "formal": "formal",
    "workout": "very-casual",
    "errands": "casual",
    "date": "smart-casual",
    "wedding": "formal",
}


# ─────────────────────────────────────────────────────────────────────────────
# Sub-scorers
# ─────────────────────────────────────────────────────────────────────────────


def style_match(outfit: Outfit, ctx: ScoringContext) -> float:
    """
    Fraction of items whose `color_primary` is a favourite, minus the fraction
    that's disliked, mapped to [0, 1] via (1 + fav_share - dis_share) / 2.

    Items with no colour info contribute 0.5 (neutral) so missing data doesn't
    bias the score toward either extreme.
    """
    items = outfit.items
    if not items:
        return 0.5

    per_item: list[float] = []
    for item in items:
        c = item.color_primary
        if c is None:
            per_item.append(0.5)
        elif c in ctx.favorite_colors:
            per_item.append(1.0)
        elif c in ctx.disliked_colors:
            per_item.append(0.0)
        else:
            per_item.append(0.5)
    return sum(per_item) / len(per_item)


def season_score(outfit: Outfit, ctx: ScoringContext) -> float:
    """Fraction of items whose `seasons` includes the requested season."""
    items = outfit.items
    if not items:
        return 0.0
    hits = sum(1 for it in items if ctx.season in it.seasons)
    return hits / len(items)


def occasion_match(outfit: Outfit, ctx: ScoringContext) -> float:
    """
    Average closeness of each item's formality to the occasion's target tier.

    Score per item = 1 - (distance / max_distance). Items with unknown
    formality contribute 0.5.
    """
    items = outfit.items
    if not items:
        return 0.5

    target_label = _OCCASION_TO_FORMALITY.get(ctx.occasion, ctx.occasion)
    target_idx = _FORMALITY_INDEX.get(target_label)
    if target_idx is None:
        # Unrecognised occasion → neutral.
        return 0.5

    per_item: list[float] = []
    for item in items:
        idx = _FORMALITY_INDEX.get(item.formality) if item.formality else None
        if idx is None:
            per_item.append(0.5)
            continue
        distance = abs(idx - target_idx)
        per_item.append(1.0 - distance / _MAX_FORMALITY_DISTANCE)
    return sum(per_item) / len(per_item)


def budget_alignment(outfit: Outfit, ctx: ScoringContext) -> float:
    """
    1.0 when the outfit's total purchase price is at or below the monthly
    clothing budget; decays as `budget / total` once total exceeds budget.
    Items with `purchase_price_usd=None` (e.g. gifts) contribute 0 to the
    total — they don't penalise the outfit.
    """
    if ctx.monthly_budget_usd is None or ctx.monthly_budget_usd <= 0:
        return 1.0
    total_price = sum((it.purchase_price_usd or 0.0) for it in outfit.items)
    if total_price <= ctx.monthly_budget_usd:
        return 1.0
    return max(0.0, ctx.monthly_budget_usd / total_price)


def duplicate_penalty(outfit: Outfit, ctx: ScoringContext) -> float:
    """Fraction of items in the recently-worn set (0.0 = none, 1.0 = all)."""
    items = outfit.items
    if not items or not ctx.recently_worn_ids:
        return 0.0
    hits = sum(1 for it in items if it.id in ctx.recently_worn_ids)
    return hits / len(items)


# ─────────────────────────────────────────────────────────────────────────────
# Public combinator
# ─────────────────────────────────────────────────────────────────────────────


# Backwards-compat alias for tests / callers that imported ScoreBreakdown as a
# type. ScoredOutfit.breakdown is `Mapping[str, float]`, so we just re-export
# the alias here for ergonomics.
ScoreBreakdown = Mapping[str, float]


def score_outfit(outfit: Outfit, ctx: ScoringContext) -> ScoredOutfit:
    """
    Score one outfit. Returns a ScoredOutfit whose `total` lies in
    [-25.0, 100.0] and whose `breakdown` maps each sub-scorer to its
    *weighted* point contribution (already multiplied by WEIGHTS).
    """
    sub_unit = {
        "style_match": style_match(outfit, ctx),
        "compatibility": compute_compatibility(list(outfit.items)),
        "season": season_score(outfit, ctx),
        "occasion_match": occasion_match(outfit, ctx),
        "budget_alignment": budget_alignment(outfit, ctx),
        "duplicate_penalty": duplicate_penalty(outfit, ctx),
    }
    weighted = {k: v * WEIGHTS[k] for k, v in sub_unit.items()}
    total = (
        weighted["style_match"]
        + weighted["compatibility"]
        + weighted["season"]
        + weighted["occasion_match"]
        + weighted["budget_alignment"]
        - weighted["duplicate_penalty"]
    )
    return ScoredOutfit(outfit=outfit, total=total, breakdown=weighted)
