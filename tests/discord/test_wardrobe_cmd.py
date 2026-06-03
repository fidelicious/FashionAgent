"""
Tests for /wardrobe.

Read-only listing with optional category filter. Pagination is simple in V1:
show the first N items and append an overflow hint — no buttons/views yet.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from clawbot.db.repo import WardrobeItem
from clawbot.discord.bot import BotContext
from clawbot.discord.cogs.wardrobe import (
    LIST_PAGE_SIZE,
    handle_wardrobe,
    render_wardrobe,
)
from clawbot.discord.images import MAX_ATTACHMENTS

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


def _add_item_with_image(repo, tmp_path: Path, idx: int, **overrides):
    """Add an item whose raw image actually exists on disk."""
    img = tmp_path / f"item-{idx}.jpg"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    overrides.setdefault("name", f"Item {idx}")
    return _add_item(repo, image_raw_path=str(img), **overrides)


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


# /wardrobe defers (it may upload up to 10 images, which can exceed Discord's
# 3s ack window), so the handler replies via followup.send, not response.
@pytest.mark.asyncio
async def test_handle_wardrobe_no_filter(
    ctx: BotContext, operator_interaction: FakeInteraction
) -> None:
    _add_item(ctx.repo, name="Linen tee", category="tops", subcategory="t-shirt")
    _add_item(ctx.repo, name="Black jeans", category="bottoms", subcategory="jeans")

    await handle_wardrobe(ctx, operator_interaction, category=None)
    body = operator_interaction.followup.sent[0]["content"]
    assert "Linen tee" in body
    assert "Black jeans" in body


@pytest.mark.asyncio
async def test_handle_wardrobe_category_filter(
    ctx: BotContext, operator_interaction: FakeInteraction
) -> None:
    _add_item(ctx.repo, name="Linen tee", category="tops")
    _add_item(ctx.repo, name="Black jeans", category="bottoms")

    await handle_wardrobe(ctx, operator_interaction, category="tops")
    body = operator_interaction.followup.sent[0]["content"]
    assert "Linen tee" in body
    assert "Black jeans" not in body


@pytest.mark.asyncio
async def test_handle_wardrobe_invalid_category(
    ctx: BotContext, operator_interaction: FakeInteraction
) -> None:
    await handle_wardrobe(ctx, operator_interaction, category="not_a_thing")
    body = operator_interaction.followup.sent[0]["content"]
    assert "not_a_thing" in body
    # Must surface the legal options so the operator can recover.
    assert "tops" in body


@pytest.mark.asyncio
async def test_handle_wardrobe_is_ephemeral(
    ctx: BotContext, operator_interaction: FakeInteraction
) -> None:
    await handle_wardrobe(ctx, operator_interaction, category=None)
    assert operator_interaction.followup.sent[0]["ephemeral"] is True


# ─────────────────────────────────────────────────────────────────────────────
# Image attachments
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_wardrobe_attaches_item_photos(
    ctx: BotContext, operator_interaction: FakeInteraction, tmp_path: Path
) -> None:
    _add_item_with_image(ctx.repo, tmp_path, 1, name="Linen tee")
    _add_item_with_image(ctx.repo, tmp_path, 2, name="Black jeans")

    await handle_wardrobe(ctx, operator_interaction, category=None)
    files = operator_interaction.followup.sent[0]["files"]
    assert len(files) == 2


@pytest.mark.asyncio
async def test_handle_wardrobe_caps_photos_and_notes_overflow(
    ctx: BotContext, operator_interaction: FakeInteraction, tmp_path: Path
) -> None:
    for i in range(MAX_ATTACHMENTS + 2):
        _add_item_with_image(ctx.repo, tmp_path, i)

    await handle_wardrobe(ctx, operator_interaction, category=None)
    sent = operator_interaction.followup.sent[0]
    assert len(sent["files"]) == MAX_ATTACHMENTS
    assert str(MAX_ATTACHMENTS) in sent["content"]


@pytest.mark.asyncio
async def test_handle_wardrobe_no_images_sends_no_files(
    ctx: BotContext, operator_interaction: FakeInteraction
) -> None:
    # Items without on-disk images → text-only, no attachments.
    _add_item(ctx.repo, name="Imageless")
    await handle_wardrobe(ctx, operator_interaction, category=None)
    assert not operator_interaction.followup.sent[0]["files"]
