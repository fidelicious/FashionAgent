"""
/add_item, /edit_item, /forget_item cogs.

V1 design notes (decided in build-Step-7 planning):
    - /add_item persists immediately using the pipeline's draft attributes.
      No two-step confirm; the operator runs /edit_item if anything is off.
      That keeps state out of memory and avoids a schema change for "draft"
      rows.
    - Image bytes arrive via discord.Attachment in the slash command. The
      cog saves them to ``images/raw/<uuid>.<suffix>`` before calling the
      injectable pipeline function — letting tests bypass the 600 MB model
      load.
    - resolve_short_id() lets the operator type the first 8 hex chars of
      the uuid that /wardrobe shows, instead of copy-pasting 36-char strings.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Callable, Optional

import discord
from discord import app_commands

from clawbot.db.repo import (
    _ITEM_COL_MAP,
    PROFILE_FIELDS,  # noqa: F401  (kept for grep parity)
    Repo,
    WardrobeItem,
)
from clawbot.discord.bot import BotContext, InteractionLike
from clawbot.discord.images import build_item_files
from clawbot.vision.draft import DraftItem

# ─────────────────────────────────────────────────────────────────────────────
# DraftItem → WardrobeItem mapping
# ─────────────────────────────────────────────────────────────────────────────


def build_item_from_draft(
    draft: DraftItem,
    *,
    brand: Optional[str] = None,
    name: Optional[str] = None,
) -> WardrobeItem:
    """Build a ``WardrobeItem`` from a freshly-ingested ``DraftItem``.

    Operator hints win over draft predictions when both are present, except
    for brand: if the operator passed nothing AND OCR detected a brand, we
    keep the OCR brand. Same logic for price.
    """
    cls = draft.classification

    final_brand = brand
    final_price: Optional[float] = None
    if draft.ocr is not None:
        if final_brand is None and draft.ocr.brand:
            final_brand = draft.ocr.brand
        if draft.ocr.price_usd is not None:
            final_price = draft.ocr.price_usd

    return WardrobeItem(
        category=cls.category,
        subcategory=cls.subcategory,
        brand=final_brand,
        name=name,
        color_primary=draft.color_primary,
        color_secondary=draft.color_secondary,
        formality=cls.formality,
        seasons=list(cls.seasons) if cls.seasons else None,
        purchase_price_usd=final_price,
        image_raw_path=str(draft.image_raw_path),
        image_cutout_path=str(draft.image_cutout_path),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Short-id resolution
# ─────────────────────────────────────────────────────────────────────────────


def resolve_short_id(repo: Repo, prefix: str) -> Optional[str]:
    """Look up a wardrobe item by full uuid or by the first 8 chars.

    Returns the full id when there's exactly one match; otherwise None.
    Multiple matches collapse to None — the caller surfaces the ambiguity to
    the operator (rare with uuid4 at our scale).
    """
    prefix = prefix.strip()
    if not prefix:
        return None
    rows = repo.conn.execute(
        "SELECT id FROM wardrobe_items "
        "WHERE (id = ? OR substr(id, 1, ?) = ?) AND deleted_at IS NULL "
        "LIMIT 2",
        (prefix, len(prefix), prefix),
    ).fetchall()
    if len(rows) != 1:
        return None
    return str(rows[0]["id"])


# ─────────────────────────────────────────────────────────────────────────────
# /add_item
# ─────────────────────────────────────────────────────────────────────────────


IngestFn = Callable[..., DraftItem]


async def handle_add_item(
    ctx: BotContext,
    interaction: InteractionLike,
    *,
    image_bytes: bytes,
    file_suffix: str,
    name: Optional[str],
    brand: Optional[str],
    raw_dir: Optional[Path] = None,
    ingest: Optional[IngestFn] = None,
) -> None:
    """Save the image, run the pipeline, persist the row, and reply.

    Steps:
        1. Persist bytes to ``raw_dir/<uuid>.<suffix>``.
        2. Run ``ingest(raw_path, source='upload', config=ctx.config)``.
        3. Build a WardrobeItem from the draft + operator hints.
        4. Insert; write the 512-d embedding into wardrobe_items_vec.
        5. Audit-log; reply ephemerally via ``followup.send``.

    The reply goes through ``followup.send`` (not ``response.send_message``)
    because the slash-command wrapper defers the interaction first — the
    pipeline can take 10–30s and Discord expires unacknowledged interactions
    after 3s. After ``defer()``, the initial response is already consumed.
    """
    raw_dir = raw_dir or (ctx.config.paths.images_dir / "raw")
    raw_dir.mkdir(parents=True, exist_ok=True)

    raw_path = raw_dir / f"{uuid.uuid4().hex}{file_suffix or '.jpg'}"
    raw_path.write_bytes(image_bytes)

    if ingest is None:
        # Imported lazily so unit tests that pass ``ingest=`` don't pay the
        # ~600 MB Fashion-CLIP cost just to import the items module.
        from clawbot.vision import ingest_image

        ingest = ingest_image

    try:
        draft = ingest(raw_path, source="upload", config=ctx.config)
    except Exception as exc:
        # Surface the failure to the operator instead of leaving the deferred
        # interaction hanging until Discord times it out. Common causes:
        # unsupported image format (e.g. HEIC without pillow-heif installed),
        # rembg/ONNX runtime error, or a corrupt file.
        await interaction.followup.send(
            f"⚠️ Could not process image: {exc}\n"
            "Supported formats: JPEG, PNG, WEBP, HEIC (requires [vision] extra).",
            ephemeral=True,
        )
        return

    item = build_item_from_draft(draft, brand=brand, name=name)
    item_id = ctx.repo.items.add(item)

    # Persist the 512-d embedding alongside the item so /outfit (Step 10+) can
    # do KNN. ``embedding`` is a numpy array; the repo wants a plain list.
    ctx.repo.items.set_embedding(item_id, draft.embedding.tolist())

    ctx.repo.audit.write(
        kind="item_added",
        actor=str(interaction.user.id),
        message=f"{item_id} {item.category}/{item.subcategory}",
    )

    short = item_id[:8]
    summary = _format_add_reply(item, short_id=short)
    await interaction.followup.send(summary, ephemeral=True)


def _format_add_reply(item: WardrobeItem, *, short_id: str) -> str:
    """Friendly reply with the new id + draft attributes + edit hint."""
    name = item.name or "(unnamed)"
    brand = f" — {item.brand}" if item.brand else ""
    parts: list[str] = [
        f"✓ Added `[{short_id}]` **{name}**{brand}",
        f"  category: `{item.category}/{item.subcategory or '?'}`",
    ]
    if item.formality:
        parts.append(f"  formality: `{item.formality}`")
    if item.seasons:
        parts.append(f"  seasons: `{', '.join(item.seasons)}`")
    if item.color_primary:
        parts.append(f"  color: `{item.color_primary}`")
    if item.purchase_price_usd:
        parts.append(f"  price: `${item.purchase_price_usd:.2f}` (from OCR)")
    parts.append("")
    parts.append(
        f"Use `/edit_item {short_id} <field> <value>` to correct anything."
    )
    return "\n".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# /edit_item
# ─────────────────────────────────────────────────────────────────────────────


# Numeric columns where Discord's string input needs coercion. Type coercion
# at this layer keeps the repo strictly typed.
_NUMERIC_FIELDS: dict[str, type] = {
    "purchase_price_usd": float,
    "wear_count": int,
}

_BOOL_FIELDS = frozenset({"needs_tailoring"})

# JSON-list fields that come in as comma-separated strings from Discord.
_LIST_FIELDS = frozenset({
    "fabric", "seasons", "pairs_well_with", "avoid_pairing_with",
})


def _coerce_field_value(field: str, raw: str) -> Any:
    """Coerce a Discord-supplied string into the dataclass field's type."""
    if field in _NUMERIC_FIELDS:
        return _NUMERIC_FIELDS[field](raw)
    if field in _BOOL_FIELDS:
        return raw.strip().lower() in {"true", "yes", "1", "y"}
    if field in _LIST_FIELDS:
        return [s.strip() for s in raw.split(",") if s.strip()]
    return raw


async def handle_edit_item(
    ctx: BotContext,
    interaction: InteractionLike,
    *,
    item_id: str,
    field: str,
    value: str,
) -> None:
    """Update a single field on an existing item. Short ids accepted."""
    if field not in _ITEM_COL_MAP:
        await interaction.response.send_message(
            f"❌ Unknown item field `{field}`. "
            f"Valid: {', '.join(sorted(_ITEM_COL_MAP))}.",
            ephemeral=True,
        )
        return

    resolved = resolve_short_id(ctx.repo, item_id)
    if resolved is None:
        await interaction.response.send_message(
            f"❌ No item matches `{item_id}`. Use `/wardrobe` to list ids.",
            ephemeral=True,
        )
        return

    try:
        coerced = _coerce_field_value(field, value)
    except ValueError as e:
        await interaction.response.send_message(
            f"❌ `{value}` is not a valid value for `{field}`: {e}",
            ephemeral=True,
        )
        return

    ctx.repo.items.update(resolved, **{field: coerced})
    ctx.repo.audit.write(
        kind="item_edited",
        actor=str(interaction.user.id),
        message=f"{resolved} {field}",
    )

    # Attach the item's photo (if any) so the operator sees what they edited.
    item = ctx.repo.items.get(resolved)
    files = build_item_files([item], cap=1) if item is not None else []
    await interaction.response.send_message(
        f"✓ `[{resolved[:8]}]` `{field}` → `{coerced}`",
        ephemeral=True,
        files=files,
    )


# ─────────────────────────────────────────────────────────────────────────────
# /forget_item
# ─────────────────────────────────────────────────────────────────────────────


async def handle_forget_item(
    ctx: BotContext,
    interaction: InteractionLike,
    *,
    item_id: str,
) -> None:
    """Soft-delete an item. Recoverable via the repo if regretted."""
    resolved = resolve_short_id(ctx.repo, item_id)
    if resolved is None:
        await interaction.response.send_message(
            f"❌ No item matches `{item_id}`.",
            ephemeral=True,
        )
        return

    # Resolve the photo *before* soft-deleting — afterwards the active-only
    # ``get`` returns None — so the confirmation can show what was hidden.
    item = ctx.repo.items.get(resolved)
    files = build_item_files([item], cap=1) if item is not None else []

    ctx.repo.items.soft_delete(resolved)
    ctx.repo.audit.write(
        kind="item_forgotten",
        actor=str(interaction.user.id),
        message=resolved,
    )

    await interaction.response.send_message(
        f"✓ Forgot `[{resolved[:8]}]`. It's hidden from recommendations but "
        f"still in the DB.",
        ephemeral=True,
        files=files,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Cog wiring
# ─────────────────────────────────────────────────────────────────────────────


async def setup(bot: Any) -> None:
    """discord.py extension entrypoint."""
    ctx: BotContext = bot.clawbot_ctx

    @bot.tree.command(
        name="add_item",
        description="Upload a photo to add a wardrobe item.",
    )
    @app_commands.describe(
        file="Photo of the item",
        name="Display name (optional)",
        brand="Brand (optional)",
    )
    async def _add_item(
        interaction: discord.Interaction,
        file: discord.Attachment,
        name: Optional[str] = None,
        brand: Optional[str] = None,
    ) -> None:  # type: ignore[misc]
        # Defer because the image pipeline can take 10–30s on this NUC.
        await interaction.response.defer(ephemeral=True, thinking=True)
        image_bytes = await file.read()
        suffix = "." + (file.filename.rsplit(".", 1)[-1].lower()
                        if "." in file.filename else "jpg")
        await handle_add_item(
            ctx,
            interaction,
            image_bytes=image_bytes,
            file_suffix=suffix,
            name=name,
            brand=brand,
        )

    @bot.tree.command(
        name="edit_item",
        description="Edit a field on an item.",
    )
    @app_commands.describe(
        item_id="Short id from /wardrobe (first 8 chars)",
        field="Field name",
        value="New value",
    )
    async def _edit_item(
        interaction: discord.Interaction,
        item_id: str,
        field: str,
        value: str,
    ) -> None:  # type: ignore[misc]
        await handle_edit_item(
            ctx, interaction, item_id=item_id, field=field, value=value
        )

    @bot.tree.command(
        name="forget_item",
        description="Hide an item from recommendations (soft-delete).",
    )
    @app_commands.describe(item_id="Short id from /wardrobe (first 8 chars)")
    async def _forget_item(
        interaction: discord.Interaction,
        item_id: str,
    ) -> None:  # type: ignore[misc]
        await handle_forget_item(ctx, interaction, item_id=item_id)
