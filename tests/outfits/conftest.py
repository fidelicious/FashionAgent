"""
Shared fixtures for outfit-scorer tests.

The scorer is intentionally pure (takes dataclasses, returns floats), so these
fixtures build small canned wardrobes with no DB involvement. Embeddings are
synthetic — unit-norm random vectors — because compatibility-score tests need
something cosine-similarity-able without loading Fashion-CLIP.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

import numpy as np
import pytest

from clawbot.outfits.types import Outfit, ScoringContext, WardrobeItem


def _unit(seed: int, dim: int = 512) -> tuple[float, ...]:
    """Reproducible unit-norm 512-d vector. Different seeds → low cosine sim."""
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(dim).astype(np.float32)
    v /= np.linalg.norm(v) or 1.0
    return tuple(float(x) for x in v)


def make_item(
    *,
    item_id: str = "i1",
    category: str = "tops",
    subcategory: str | None = "t-shirt",
    color_primary: str | None = "navy",
    formality: str | None = "casual",
    seasons: Iterable[str] = ("spring", "fall"),
    purchase_price_usd: float | None = 40.0,
    pairs_well_with: Iterable[str] = (),
    avoid_pairing_with: Iterable[str] = (),
    wear_count: int = 0,
    last_worn_date: date | None = None,
    embedding_seed: int = 1,
) -> WardrobeItem:
    """Build a WardrobeItem with sane defaults; override only what each test cares about."""
    return WardrobeItem(
        id=item_id,
        category=category,
        subcategory=subcategory,
        color_primary=color_primary,
        formality=formality,
        seasons=tuple(seasons),
        purchase_price_usd=purchase_price_usd,
        pairs_well_with=tuple(pairs_well_with),
        avoid_pairing_with=tuple(avoid_pairing_with),
        wear_count=wear_count,
        last_worn_date=last_worn_date,
        embedding=_unit(embedding_seed),
    )


@pytest.fixture
def make_outfit():
    """Factory: build an Outfit from role→item kwargs."""

    def _build(**roles: WardrobeItem) -> Outfit:
        return Outfit(items_by_role=dict(roles))

    return _build


@pytest.fixture
def default_context() -> ScoringContext:
    """A ScoringContext with neutral inputs — tests override fields as needed."""
    return ScoringContext(
        occasion="casual",
        season="fall",
        favorite_colors=frozenset({"navy", "olive"}),
        disliked_colors=frozenset({"neon-pink"}),
        monthly_budget_usd=300.0,
        recently_worn_ids=frozenset(),
    )


@pytest.fixture
def item_factory():
    """Expose make_item as a fixture for tests that prefer fixture-style access."""
    return make_item
