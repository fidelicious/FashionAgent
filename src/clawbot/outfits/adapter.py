"""
Translation layer between the DB row dataclass and the scoring dataclass.

The DB layer (`clawbot.db.repo.WardrobeItem`) and the scoring layer
(`clawbot.outfits.types.WardrobeItem`) carry different concerns:

  - DB row: full schema mirror, mutable, lists/None for JSON columns,
    string dates.
  - Scoring: scorer-relevant subset, frozen, tuples for hashability,
    real date objects.

Keeping them separate means the scorer stays Hypothesis-fast and pure,
while the DB layer can grow new columns without touching property tests.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import date
from typing import Any

from clawbot.db.repo import WardrobeItem as DbWardrobeItem
from clawbot.outfits.types import ScoringContext, WardrobeItem


def _to_tuple(value: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    """Normalise a JSON-list field into a tuple (never None)."""
    if value is None:
        return ()
    return tuple(value)


def _parse_iso_date(value: str | None) -> date | None:
    """Parse an ISO date string, tolerantly. None on any failure."""
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def from_db_item(item: DbWardrobeItem) -> WardrobeItem:
    """
    Convert a DB-side WardrobeItem into the scoring-side WardrobeItem.

    The DB row carries `image_final_path` etc.; we drop those here because
    the scorer doesn't read them. The daily-push orchestrator keeps a
    parallel `{item_id: image_path}` map for the collage step.

    Raises ValueError when ``item.id`` is None — that's a programmer error
    (the repo always assigns an id at insert time).
    """
    if item.id is None:
        raise ValueError("from_db_item: item.id must be set before scoring")
    return WardrobeItem(
        id=item.id,
        category=item.category,
        subcategory=item.subcategory,
        color_primary=item.color_primary,
        formality=item.formality,
        seasons=_to_tuple(item.seasons),
        purchase_price_usd=item.purchase_price_usd,
        pairs_well_with=_to_tuple(item.pairs_well_with),
        avoid_pairing_with=_to_tuple(item.avoid_pairing_with),
        wear_count=item.wear_count,
        last_worn_date=_parse_iso_date(item.last_worn_date),
        embedding=None,  # populated separately by daily-push if needed
    )


def _parse_json_list(value: Any) -> list[str]:
    """Profile JSON columns come back as strings; deserialise + normalise."""
    if value is None:
        return []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return [str(x) for x in parsed] if isinstance(parsed, list) else []
    if isinstance(value, list):
        return [str(x) for x in value]
    return []


def build_scoring_context(
    profile: dict[str, Any],
    *,
    occasion: str,
    season: str,
    recently_worn_ids: Iterable[str] | None = None,
) -> ScoringContext:
    """
    Construct a ScoringContext from the singleton user_profile dict the
    repo returns plus per-request bits (occasion + season + recently worn).

    Missing or unparseable profile fields degrade to neutral defaults —
    the daily push must still ship even when the profile is empty.
    """
    favourites = _parse_json_list(profile.get("favorite_colors_json"))
    dislikes = _parse_json_list(profile.get("disliked_colors_json"))
    budget = profile.get("monthly_clothing_budget_usd")
    budget_f = float(budget) if budget is not None else None
    return ScoringContext(
        occasion=occasion,
        season=season,
        favorite_colors=frozenset(favourites),
        disliked_colors=frozenset(dislikes),
        monthly_budget_usd=budget_f,
        recently_worn_ids=frozenset(recently_worn_ids or ()),
    )


# Meteorological seasons, Northern hemisphere. Used by the daily job when
# nothing else (config, command argument) overrides.
_SEASONS_BY_MONTH: dict[int, str] = {
    12: "winter",
    1: "winter",
    2: "winter",
    3: "spring",
    4: "spring",
    5: "spring",
    6: "summer",
    7: "summer",
    8: "summer",
    9: "fall",
    10: "fall",
    11: "fall",
}


def derive_season(today: date) -> str:
    """Map a date to its meteorological season label (NH)."""
    return _SEASONS_BY_MONTH[today.month]
