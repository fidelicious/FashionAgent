"""
Dataclasses used by the outfit scorer.

These deliberately mirror only the subset of wardrobe_items columns the
scorer actually reads. The DB repo will translate sqlite rows → these
dataclasses; the scorer never sees a Connection. That separation lets
Hypothesis generate millions of inputs cheaply.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import date

# Role slots used in Outfit.items_by_role. Kept as a constant tuple so callers
# can iterate in deterministic order (matters for breakdown and collage layout).
ROLES: tuple[str, ...] = ("top", "bottom", "outer", "footwear", "dress", "accessory")


@dataclass(frozen=True)
class WardrobeItem:
    """
    Subset of `wardrobe_items` columns relevant to outfit scoring.

    Fields not present here (size, fabric, condition, image paths) are
    intentionally excluded because the scorer doesn't read them. Keeping the
    surface area small makes property tests fast.
    """

    id: str
    category: str
    subcategory: str | None
    color_primary: str | None
    formality: str | None
    seasons: tuple[str, ...]
    purchase_price_usd: float | None
    pairs_well_with: tuple[str, ...]
    avoid_pairing_with: tuple[str, ...]
    wear_count: int
    last_worn_date: date | None
    embedding: tuple[float, ...] | None  # 512-dim Fashion-CLIP vector, optional


@dataclass(frozen=True)
class Outfit:
    """
    A combination of items keyed by role.

    The candidate generator emits these; the scorer consumes them. An Outfit
    must have at least one item — sub-scorers that divide by item count
    handle the empty case defensively but the generator never emits empties.
    """

    items_by_role: Mapping[str, WardrobeItem]

    @property
    def items(self) -> tuple[WardrobeItem, ...]:
        """Items in deterministic role order, for stable iteration."""
        return tuple(self.items_by_role[role] for role in ROLES if role in self.items_by_role)


@dataclass(frozen=True)
class ScoringContext:
    """
    Per-request inputs the scorer needs but that aren't on items.

    `recently_worn_ids` powers the duplicate penalty — the daily-push job
    populates it from `wardrobe_items.last_worn_date` within the last N days
    (N tunable in clawbot.yaml, not here).
    """

    occasion: str
    season: str
    favorite_colors: frozenset[str] = frozenset()
    disliked_colors: frozenset[str] = frozenset()
    monthly_budget_usd: float | None = None
    recently_worn_ids: frozenset[str] = frozenset()

    def with_recently_worn(self, ids: frozenset[str] | set[str] | list[str]) -> ScoringContext:
        """Convenience for tests: return a copy with a different recently-worn set."""
        return replace(self, recently_worn_ids=frozenset(ids))


@dataclass(frozen=True)
class ScoredOutfit:
    """
    Result of score_outfit(): the original candidate plus its weighted total
    and the per-sub-scorer breakdown (already weighted, in points, not 0..1).
    """

    outfit: Outfit
    total: float
    breakdown: Mapping[str, float] = field(default_factory=dict)
