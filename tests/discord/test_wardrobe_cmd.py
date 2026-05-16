"""
Tests for /wardrobe.

Read-only listing with optional category filter. Pagination is simple in V1:
show the first N items and append an overflow hint — no buttons/views yet.
"""

from __future__ import annotations

import pytest

from clawbot.db.repo import WardrobeItem
from clawbot.discord.bot import BotContext
from clawbot.discord.cogs.wardrobe import (
    LIST_PAGE_SIZE,
    handle_wardrobe,
    render_wardrobe,
)

from .conftest import FakeInteraction


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


def _add_item(repo, **overrides):
    item = WardrobeItem(
        id=None,
        category=overrides.pop("category", "tops"),
        subcategory=overrides.pop("subcategory", "cardigan"),
        brand=overrides.pop("brand", "COS"),
        name=overrides.pop("name", "Navy wool cardigan"),
        color_primary=overrides.pop("color_primary", "navy"),
    )
    for k, v in overrides.items():
        setattr(item, k, v)
    return repo.items.add(item)


# ─────────────────────────────────────────────────────────────────────────────
# render_wardrobe
# ─────────────────────────────────────────────────────────────────────────────


def test_render_wardrobe_empty() -> None:
    assert "no items" in render_wardrobe([], total=0, category=None).lower()


def test_render_wardrobe_lists_brand_and_subcategory(ctx: BotContext) -> None:
    _add_item(ctx.repo, brand="Quince", subcategory="turtleneck", name="Cashmere mock-neck")
    items = ctx.repo.items.list_by_category()
    body = render_wardrobe(items, total=1, category=None)

    assert "Quince" in body
    assert "turtleneck" in body
    assert "Cashmere mock-neck" in body


def test_render_wardrobe_overflow_hint(ctx: BotContext) -> None:
    """When more items exist than the page shows, mention the remainder."""
    for i in range(LIST_PAGE_SIZE + 3):
        _add_item(ctx.repo, name=f"Item {i}")
    items = ctx.repo.items.list_by_category(limit=LIST_PAGE_SIZE)
    body = render_wardrobe(
        items, total=LIST_PAGE_SIZE + 3, category=None
    )
    assert f"{LIST_PAGE_SIZE} of {LIST_PAGE_SIZE + 3}" in body or "more" in body


# ─────────────────────────────────────────────────────────────────────────────
# handle_wardrobe
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_wardrobe_no_filter(
    ctx: BotContext, operator_interaction: FakeInteraction
) -> None:
    _add_item(ctx.repo, name="Linen tee", category="tops", subcategory="t-shirt")
    _add_item(ctx.repo, name="Black jeans", category="bottoms", subcategory="jeans")

    await handle_wardrobe(ctx, operator_interaction, category=None)
    body = operator_interaction.response.sent[0]["content"]
    assert "Linen tee" in body
    assert "Black jeans" in body


@pytest.mark.asyncio
async def test_handle_wardrobe_category_filter(
    ctx: BotContext, operator_interaction: FakeInteraction
) -> None:
    _add_item(ctx.repo, name="Linen tee", category="tops")
    _add_item(ctx.repo, name="Black jeans", category="bottoms")

    await handle_wardrobe(ctx, operator_interaction, category="tops")
    body = operator_interaction.response.sent[0]["content"]
    assert "Linen tee" in body
    assert "Black jeans" not in body


@pytest.mark.asyncio
async def test_handle_wardrobe_invalid_category(
    ctx: BotContext, operator_interaction: FakeInteraction
) -> None:
    await handle_wardrobe(ctx, operator_interaction, category="not_a_thing")
    body = operator_interaction.response.sent[0]["content"]
    assert "not_a_thing" in body
    # Must surface the legal options so the operator can recover.
    assert "tops" in body


@pytest.mark.asyncio
async def test_handle_wardrobe_is_ephemeral(
    ctx: BotContext, operator_interaction: FakeInteraction
) -> None:
    await handle_wardrobe(ctx, operator_interaction, category=None)
    assert operator_interaction.response.sent[0]["ephemeral"] is True
