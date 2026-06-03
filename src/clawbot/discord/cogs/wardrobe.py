"""
/wardrobe cog.

Read-only listing. V1 pagination is intentionally crude — show the first
``LIST_PAGE_SIZE`` items and tell the operator if more exist. Buttons/views
can come in V2 once we have a non-trivial wardrobe to test against.
"""

from __future__ import annotations

from typing import Any, Optional

import discord
from discord import app_commands

from clawbot.db.repo import WardrobeItem
from clawbot.discord.bot import BotContext, InteractionLike
from clawbot.discord.images import MAX_ATTACHMENTS, build_item_files
from clawbot.vision.taxonomy import CATEGORY_PROMPTS

# Discord's hard message-content limit is 2000 chars; one item line is ~60–80,
# so 25 fits comfortably with headers + overflow note.
LIST_PAGE_SIZE = 25

VALID_CATEGORIES = frozenset(CATEGORY_PROMPTS)


# ─────────────────────────────────────────────────────────────────────────────
# Rendering
# ─────────────────────────────────────────────────────────────────────────────


def _short_id(item_id: Optional[str]) -> str:
    """First 8 chars of the uuid — enough to disambiguate at human scale."""
    return (item_id or "????????")[:8]


def _format_item(item: WardrobeItem) -> str:
    """One-line summary: `[12345678] Navy cardigan — COS (tops/cardigan)`."""
    name = item.name or "(unnamed)"
    brand_part = f" — {item.brand}" if item.brand else ""
    cat = item.category or "?"
    sub = f"/{item.subcategory}" if item.subcategory else ""
    return f"`[{_short_id(item.id)}]` **{name}**{brand_part} ({cat}{sub})"


def render_wardrobe(
    items: list[WardrobeItem], *, total: int, category: Optional[str]
) -> str:
    """Render an item list as a multi-line ephemeral message.

    ``total`` is the unfiltered/full count for the active filter — it's used
    only for the overflow hint, so the caller can pass ``len(items)`` when
    there's no pagination concern.
    """
    if not items:
        scope = f" in `{category}`" if category else ""
        return f"_(no items{scope} yet — use `/add_item` to add one)_"

    header = (
        f"**Wardrobe — `{category}`**"
        if category
        else "**Wardrobe**"
    )
    lines = [header, ""]
    for item in items:
        lines.append(f"• {_format_item(item)}")

    if total > len(items):
        lines.append("")
        lines.append(
            f"_(showing {len(items)} of {total} — refine with a `category:` filter)_"
        )
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Handler
# ─────────────────────────────────────────────────────────────────────────────


async def handle_wardrobe(
    ctx: BotContext,
    interaction: InteractionLike,
    *,
    category: Optional[str],
) -> None:
    """Reply with a paginated list of wardrobe items, optionally filtered.

    Each listed item's photo is attached (up to Discord's 10-attachment
    limit). The caller must have ``defer()``-ed first — uploading several
    images can exceed Discord's 3s ack window — so every reply goes through
    ``followup.send``.
    """
    if category is not None and category not in VALID_CATEGORIES:
        await interaction.followup.send(
            f"❌ Unknown category `{category}`. "
            f"Valid: {', '.join(sorted(VALID_CATEGORIES))}.",
            ephemeral=True,
        )
        return

    items = ctx.repo.items.list_by_category(
        category=category, limit=LIST_PAGE_SIZE
    )
    total = ctx.repo.items.count() if category is None else len(
        ctx.repo.items.list_by_category(category=category, limit=10_000)
    )

    body = render_wardrobe(items, total=total, category=category)
    files = build_item_files(items, cap=MAX_ATTACHMENTS)
    # Photos are capped well below the text page size, so signal when the
    # list shows more items than we could attach photos for.
    if len(items) > MAX_ATTACHMENTS and files:
        body += f"\n\n_(photos shown for the first {MAX_ATTACHMENTS} items)_"
    await interaction.followup.send(body, ephemeral=True, files=files)


# ─────────────────────────────────────────────────────────────────────────────
# Cog wiring
# ─────────────────────────────────────────────────────────────────────────────


async def setup(bot: Any) -> None:
    """discord.py extension entrypoint. Registers /wardrobe."""
    ctx: BotContext = bot.clawbot_ctx

    @bot.tree.command(
        name="wardrobe",
        description="List your wardrobe, optionally filtered by category.",
    )
    @app_commands.describe(category="Filter by category (e.g. tops, bottoms)")
    async def _wardrobe(
        interaction: discord.Interaction,
        category: Optional[str] = None,
    ) -> None:  # type: ignore[misc]
        # Defer first: building + uploading up to 10 photos can exceed
        # Discord's 3s initial-response deadline.
        await interaction.response.defer(ephemeral=True, thinking=True)
        await handle_wardrobe(ctx, interaction, category=category)
