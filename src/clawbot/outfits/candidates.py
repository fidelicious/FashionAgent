"""
Candidate outfit generator.

Goal: given a wardrobe and a request (season + occasion), emit a bounded list
of plausible Outfit candidates that the scorer can rank. The plan caps this
at ~50 so the LLM call in step 11 stays fast on Gemma 3 1B.

Strategy:
  1. Bucket items by role.
  2. Filter by season (strict — wrong-season items are never good candidates).
  3. Generate two paths in parallel:
       - Dress-based outfits  → dress × footwear
       - Pieced outfits       → top × bottom × footwear (× optional outer)
  4. Truncate at max_candidates. The current implementation walks the
     itertools.product lazily, which means callers can iterate without
     materialising the full Cartesian product. Diversity sampling is a
     V2 concern (step 13 daily-push job will wrap this).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from itertools import islice, product

from clawbot.outfits.types import Outfit, ScoringContext, WardrobeItem

# Categories that map to which role slot. `tops` includes light cardigans;
# `outerwear` includes heavy cardigans — the taxonomy in the plan deliberately
# overlaps because the user disambiguates at upload time.
_CATEGORY_TO_ROLE: dict[str, str] = {
    "tops": "top",
    "bottoms": "bottom",
    "dresses": "dress",
    "outerwear": "outer",
    "footwear": "footwear",
    # Accessories and underlayers are not part of the outfit grid in V1.
}


def _matches_season(item: WardrobeItem, season: str) -> bool:
    """An item with no `seasons` recorded is treated as all-season."""
    return not item.seasons or season in item.seasons


def _bucket(items: Iterable[WardrobeItem], ctx: ScoringContext) -> dict[str, list[WardrobeItem]]:
    """Group season-matching items by their canonical role."""
    buckets: dict[str, list[WardrobeItem]] = {}
    for item in items:
        role = _CATEGORY_TO_ROLE.get(item.category)
        if role is None:
            continue
        if not _matches_season(item, ctx.season):
            continue
        buckets.setdefault(role, []).append(item)
    return buckets


def _piece_combos(
    buckets: dict[str, list[WardrobeItem]],
) -> Iterator[dict[str, WardrobeItem]]:
    """Yield top × bottom × footwear (× optional outer) dicts."""
    tops = buckets.get("top", [])
    bottoms = buckets.get("bottom", [])
    shoes = buckets.get("footwear", [])
    if not (tops and bottoms and shoes):
        return
    outers = buckets.get("outer") or [None]  # type: ignore[list-item]
    for top, bottom, shoe, outer in product(tops, bottoms, shoes, outers):
        roles: dict[str, WardrobeItem] = {
            "top": top,
            "bottom": bottom,
            "footwear": shoe,
        }
        if outer is not None:
            roles["outer"] = outer
        yield roles


def _dress_combos(
    buckets: dict[str, list[WardrobeItem]],
) -> Iterator[dict[str, WardrobeItem]]:
    """Yield dress × footwear dicts."""
    dresses = buckets.get("dress", [])
    shoes = buckets.get("footwear", [])
    if not (dresses and shoes):
        return
    for dress, shoe in product(dresses, shoes):
        yield {"dress": dress, "footwear": shoe}


def generate_candidates(
    items: Sequence[WardrobeItem],
    ctx: ScoringContext,
    max_candidates: int = 50,
) -> list[Outfit]:
    """
    Return up to `max_candidates` plausible Outfit candidates.

    Caller is expected to have already filtered out soft-deleted items
    (`deleted_at IS NOT NULL`) at the repo layer — this function trusts the
    input list.
    """
    if not items or max_candidates <= 0:
        return []

    buckets = _bucket(items, ctx)
    # Chain the two paths; islice gives us a hard cap without materialising
    # the full Cartesian product.
    combo_stream = (
        roles
        for roles in (
            *list(_dress_combos(buckets)),
            *list(_piece_combos(buckets)),
        )
    )
    return [Outfit(items_by_role=roles) for roles in islice(combo_stream, max_candidates)]
