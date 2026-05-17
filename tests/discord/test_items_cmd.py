"""
Tests for /add_item, /edit_item, /forget_item.

The image pipeline is heavy (rembg + Fashion-CLIP load ~600 MB of weights),
so we inject a fake ingest function instead of calling the real one. The
fake returns a hand-rolled DraftItem so we can verify the mapping from
``DraftItem`` → ``WardrobeItem`` precisely.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from clawbot.db.repo import WardrobeItem
from clawbot.discord.bot import BotContext
from clawbot.discord.cogs.items import (
    build_item_from_draft,
    handle_add_item,
    handle_edit_item,
    handle_forget_item,
    resolve_short_id,
)
from clawbot.vision.draft import ClassificationResult, DraftItem, OcrResult

from .conftest import FakeInteraction


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


def _fake_draft(tmp_path: Path) -> DraftItem:
    """Hand-rolled DraftItem mirroring what ingest_image would return."""
    raw = tmp_path / "raw.jpg"
    cut = tmp_path / "cut.png"
    raw.write_bytes(b"fake")
    cut.write_bytes(b"fake")
    return DraftItem(
        image_raw_path=raw,
        image_cutout_path=cut,
        color_primary="#1a2b3c",
        color_secondary="#cdef01",
        classification=ClassificationResult(
            category="tops",
            subcategory="cardigan",
            formality="casual",
            seasons=("fall", "winter"),
        ),
        ocr=None,
        embedding=np.zeros(512, dtype=np.float32),
        confidence={
            "color": 0.9,
            "category": 0.88,
            "subcategory": 0.62,
            "formality": 0.71,
            "season": 0.77,
        },
    )


@pytest.fixture
def fake_ingest(tmp_path: Path):
    """An injectable replacement for vision.ingest_image."""
    draft = _fake_draft(tmp_path)

    def _ingest(raw_path: Path, *, source: str, config) -> DraftItem:  # noqa: ANN001
        # Honor the actual raw_path so the persisted item points at the real file.
        return DraftItem(
            image_raw_path=raw_path,
            image_cutout_path=draft.image_cutout_path,
            color_primary=draft.color_primary,
            color_secondary=draft.color_secondary,
            classification=draft.classification,
            ocr=draft.ocr,
            embedding=draft.embedding,
            confidence=draft.confidence,
        )

    return _ingest


# ─────────────────────────────────────────────────────────────────────────────
# build_item_from_draft: pure mapping
# ─────────────────────────────────────────────────────────────────────────────


def test_build_item_from_draft_copies_classification(tmp_path: Path) -> None:
    draft = _fake_draft(tmp_path)
    item = build_item_from_draft(draft)

    assert item.category == "tops"
    assert item.subcategory == "cardigan"
    assert item.formality == "casual"
    assert item.seasons == ["fall", "winter"]
    assert item.color_primary == "#1a2b3c"
    assert item.color_secondary == "#cdef01"
    assert item.image_raw_path == str(draft.image_raw_path)
    assert item.image_cutout_path == str(draft.image_cutout_path)


def test_build_item_from_draft_applies_operator_hints(tmp_path: Path) -> None:
    """Operator-supplied brand/name override (or fill in) the draft."""
    draft = _fake_draft(tmp_path)
    item = build_item_from_draft(draft, brand="COS", name="Navy wool cardigan")

    assert item.brand == "COS"
    assert item.name == "Navy wool cardigan"


def test_build_item_from_draft_with_ocr_brand(tmp_path: Path) -> None:
    """If OCR found a brand and the operator didn't override, OCR wins."""
    draft = _fake_draft(tmp_path)
    draft_with_ocr = DraftItem(
        image_raw_path=draft.image_raw_path,
        image_cutout_path=draft.image_cutout_path,
        color_primary=draft.color_primary,
        color_secondary=draft.color_secondary,
        classification=draft.classification,
        ocr=OcrResult(brand="Aritzia", price_usd=128.0, raw_text="..."),
        embedding=draft.embedding,
        confidence=draft.confidence,
    )

    item = build_item_from_draft(draft_with_ocr)
    assert item.brand == "Aritzia"
    assert item.purchase_price_usd == 128.0


# ─────────────────────────────────────────────────────────────────────────────
# handle_add_item: end-to-end with injected ingest
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_add_item_persists_row_and_replies(
    ctx: BotContext,
    operator_interaction: FakeInteraction,
    tmp_path: Path,
    fake_ingest,
) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()

    await handle_add_item(
        ctx,
        operator_interaction,
        image_bytes=b"fake-jpeg-bytes",
        file_suffix=".jpg",
        name=None,
        brand=None,
        raw_dir=raw_dir,
        ingest=fake_ingest,
    )

    items = ctx.repo.items.list_by_category()
    assert len(items) == 1
    assert items[0].category == "tops"
    assert items[0].subcategory == "cardigan"

    body = operator_interaction.followup.sent[0]["content"]
    assert "cardigan" in body
    assert "/edit_item" in body  # tells the operator how to correct


@pytest.mark.asyncio
async def test_add_item_writes_embedding(
    ctx: BotContext,
    operator_interaction: FakeInteraction,
    tmp_path: Path,
    fake_ingest,
) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()

    await handle_add_item(
        ctx,
        operator_interaction,
        image_bytes=b"x",
        file_suffix=".jpg",
        name=None,
        brand=None,
        raw_dir=raw_dir,
        ingest=fake_ingest,
    )

    # find_similar would fail if the embedding wasn't written.
    items = ctx.repo.items.list_by_category()
    similar = ctx.repo.items.find_similar([0.0] * 512, k=1)
    assert items[0].id in {hit[0] for hit in similar}


@pytest.mark.asyncio
async def test_add_item_audit_logged(
    ctx: BotContext,
    operator_interaction: FakeInteraction,
    tmp_path: Path,
    fake_ingest,
) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()

    await handle_add_item(
        ctx,
        operator_interaction,
        image_bytes=b"x",
        file_suffix=".jpg",
        name=None,
        brand=None,
        raw_dir=raw_dir,
        ingest=fake_ingest,
    )

    rows = ctx.repo.audit.recent(limit=10)
    kinds = [r["kind"] for r in rows]
    assert "item_added" in kinds


@pytest.mark.asyncio
async def test_add_item_uses_followup_after_defer(
    ctx: BotContext,
    operator_interaction: FakeInteraction,
    tmp_path: Path,
    fake_ingest,
) -> None:
    # Regression for the production crash: _add_item defers (because the
    # pipeline is slow), so handle_add_item MUST reply via followup.send,
    # not response.send_message — the latter raises InteractionResponded.
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()

    await operator_interaction.response.defer(ephemeral=True, thinking=True)

    await handle_add_item(
        ctx,
        operator_interaction,
        image_bytes=b"fake-jpeg-bytes",
        file_suffix=".jpg",
        name=None,
        brand=None,
        raw_dir=raw_dir,
        ingest=fake_ingest,
    )

    assert len(operator_interaction.followup.sent) == 1
    body = operator_interaction.followup.sent[0]["content"]
    assert "cardigan" in body


# ─────────────────────────────────────────────────────────────────────────────
# resolve_short_id
# ─────────────────────────────────────────────────────────────────────────────


def test_resolve_short_id_unique(ctx: BotContext) -> None:
    full = ctx.repo.items.add(WardrobeItem(category="tops", name="X"))
    resolved = resolve_short_id(ctx.repo, full[:8])
    assert resolved == full


def test_resolve_short_id_full_id_passthrough(ctx: BotContext) -> None:
    full = ctx.repo.items.add(WardrobeItem(category="tops", name="X"))
    assert resolve_short_id(ctx.repo, full) == full


def test_resolve_short_id_unknown_returns_none(ctx: BotContext) -> None:
    assert resolve_short_id(ctx.repo, "deadbeef") is None


# ─────────────────────────────────────────────────────────────────────────────
# handle_edit_item
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_edit_item_updates_field(
    ctx: BotContext, operator_interaction: FakeInteraction
) -> None:
    item_id = ctx.repo.items.add(WardrobeItem(category="tops", name="Old name"))

    await handle_edit_item(
        ctx,
        operator_interaction,
        item_id=item_id[:8],
        field="name",
        value="New name",
    )

    assert ctx.repo.items.get(item_id).name == "New name"
    body = operator_interaction.response.sent[0]["content"]
    assert "New name" in body


@pytest.mark.asyncio
async def test_edit_item_unknown_field_errors(
    ctx: BotContext, operator_interaction: FakeInteraction
) -> None:
    item_id = ctx.repo.items.add(WardrobeItem(category="tops"))

    await handle_edit_item(
        ctx,
        operator_interaction,
        item_id=item_id,
        field="not_a_real_field",
        value="x",
    )
    body = operator_interaction.response.sent[0]["content"]
    assert "not_a_real_field" in body


@pytest.mark.asyncio
async def test_edit_item_unknown_id_errors(
    ctx: BotContext, operator_interaction: FakeInteraction
) -> None:
    await handle_edit_item(
        ctx, operator_interaction, item_id="deadbeef", field="name", value="x"
    )
    body = operator_interaction.response.sent[0]["content"]
    assert "deadbeef" in body


@pytest.mark.asyncio
async def test_edit_item_numeric_coercion(
    ctx: BotContext, operator_interaction: FakeInteraction
) -> None:
    """Operators type strings in Discord; numeric columns must accept them."""
    item_id = ctx.repo.items.add(WardrobeItem(category="tops"))

    await handle_edit_item(
        ctx,
        operator_interaction,
        item_id=item_id,
        field="purchase_price_usd",
        value="125.50",
    )
    assert ctx.repo.items.get(item_id).purchase_price_usd == 125.50


# ─────────────────────────────────────────────────────────────────────────────
# handle_forget_item
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_forget_item_soft_deletes(
    ctx: BotContext, operator_interaction: FakeInteraction
) -> None:
    item_id = ctx.repo.items.add(WardrobeItem(category="tops"))

    await handle_forget_item(ctx, operator_interaction, item_id=item_id[:8])

    # active list excludes it
    assert ctx.repo.items.get(item_id) is None
    # but it's still there if we include_deleted
    assert ctx.repo.items.get(item_id, include_deleted=True) is not None


@pytest.mark.asyncio
async def test_forget_item_unknown_id_errors(
    ctx: BotContext, operator_interaction: FakeInteraction
) -> None:
    await handle_forget_item(ctx, operator_interaction, item_id="deadbeef")
    body = operator_interaction.response.sent[0]["content"]
    assert "deadbeef" in body
