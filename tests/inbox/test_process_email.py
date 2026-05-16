"""
Tests for ``process_email`` — the .eml → N WardrobeItems bridge.

The fork from ``process_one``:
    - One .eml can produce 1..N wardrobe rows (multi-item order confirmation).
    - The image (if any) is *inside* the email, not a file on disk — we
      have to materialize it under ``images/raw/`` before the pipeline runs.
    - When the email has no image, we still persist a text-only row and
      ask the operator (via Discord) to attach a photo later.
    - On UnknownRetailerError or ParseFailedError, quarantine the whole
      .eml (the same way ``process_one`` quarantines a broken JPG).
"""

from __future__ import annotations

import base64
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import pytest

from clawbot.discord.bot import BotContext
from clawbot.inbox.watcher import (
    InboxFile,
    ProcessOutcome,
    process_email,
)


# ─────────────────────────────────────────────────────────────────────────────
# .eml builders — same helper as test_email_parser, copied so the two test
# modules can evolve independently without coupling.
# ─────────────────────────────────────────────────────────────────────────────


_TINY_JPG = base64.b64decode(
    b"/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAAEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEB"
    b"AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEB/9sAQwEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEB"
    b"AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEB/8AAEQgAAQABAwEiAAIRAQMRAf/EAB8A"
    b"AAEFAQEBAQEBAAAAAAAAAAABAgMEBQYHCAkKC//EALUQAAIBAwMCBAMFBQQEAAABfQECAwAEEQUSITFB"
    b"BhNRYQcicRQygZGhCCNCscEVUtHwJDNicoIJChYXGBkaJSYnKCkqNDU2Nzg5OkNERUZHSElKU1RVVldY"
    b"WVpjZGVmZ2hpanN0dXZ3eHl6g4SFhoeIiYqSk5SVlpeYmZqio6Slpqeoqaqys7S1tre4ubrCw8TFxsfI"
    b"ycrS09TV1tfY2drh4uPk5ebn6Onq8fLz9PX29/j5+v/aAAwDAQACEQMRAD8A/v4oA//Z"
)


def _write_eml(path: Path, *, from_addr: str, subject: str, html: str,
               images: list[tuple[str, bytes]] | None = None) -> Path:
    msg = MIMEMultipart("related")
    msg["From"] = from_addr
    msg["To"] = "operator@example.com"
    msg["Subject"] = subject
    msg.attach(MIMEText(html, "html"))
    for cid, data in images or []:
        img = MIMEImage(data, _subtype="jpeg")
        img.add_header("Content-ID", f"<{cid}>")
        img.add_header("Content-Disposition", "inline", filename=f"{cid}.jpg")
        msg.attach(img)
    path.write_bytes(msg.as_bytes())
    return path


@pytest.fixture
def quince_eml(cfg) -> Path:
    inbox = cfg.paths.inbox_dir / "email"
    inbox.mkdir(parents=True, exist_ok=True)
    return _write_eml(
        inbox / "order.eml",
        from_addr="orders@quince.com",
        subject="Your Quince order is confirmed",
        html=(
            '<html><body><div class="item">'
            '<img src="cid:i1" />'
            '<p class="product-name">Cashmere Crewneck</p>'
            '<p class="price">$59.90</p>'
            "</div></body></html>"
        ),
        images=[("i1", _TINY_JPG)],
    )


@pytest.fixture
def multi_eml(cfg) -> Path:
    inbox = cfg.paths.inbox_dir / "email"
    inbox.mkdir(parents=True, exist_ok=True)
    return _write_eml(
        inbox / "multi.eml",
        from_addr="orders@quince.com",
        subject="Order confirmed",
        html=(
            '<html><body>'
            '<div class="item">'
            '<img src="cid:a" /><p class="product-name">Sweater</p>'
            '<p class="price">$59.90</p></div>'
            '<div class="item">'
            '<img src="cid:b" /><p class="product-name">Pant</p>'
            '<p class="price">$49.00</p></div>'
            "</body></html>"
        ),
        images=[("a", _TINY_JPG), ("b", _TINY_JPG)],
    )


@pytest.fixture
def no_image_eml(cfg) -> Path:
    inbox = cfg.paths.inbox_dir / "email"
    inbox.mkdir(parents=True, exist_ok=True)
    return _write_eml(
        inbox / "salealert.eml",
        from_addr="hello@quince.com",
        subject="Price drop on your wishlist",
        html=(
            '<html><body><div class="item">'
            '<p class="product-name">Linen Wrap Coat</p>'
            '<p class="price">$229.00</p>'
            "</div></body></html>"
        ),
    )


@pytest.fixture
def unknown_eml(cfg) -> Path:
    inbox = cfg.paths.inbox_dir / "email"
    inbox.mkdir(parents=True, exist_ok=True)
    return _write_eml(
        inbox / "weird.eml",
        from_addr="orders@some-boutique.example",
        subject="Order",
        html="<html><body>nope</body></html>",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Single-item happy path with an image
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_process_email_single_item_with_image(
    ctx: BotContext, quince_eml: Path, fake_draft_factory, notifier
) -> None:
    results = await process_email(
        ctx,
        InboxFile(path=quince_eml, source="email"),
        ingest=lambda p, **kw: fake_draft_factory(p),
        notify=notifier,
    )
    assert len(results) == 1
    assert results[0].outcome is ProcessOutcome.OK
    # Wardrobe row exists with brand + price from the email.
    items = ctx.repo.items.list_by_category()
    assert len(items) == 1
    assert items[0].brand == "Quince"
    assert items[0].name == "Cashmere Crewneck"
    assert items[0].purchase_price_usd == pytest.approx(59.90)
    # The .eml was moved out of inbox/email/.
    assert not quince_eml.exists()
    processed = list(
        (ctx.config.paths.inbox_dir / ".processed" / "email").rglob("*.eml")
    )
    assert len(processed) == 1


@pytest.mark.asyncio
async def test_process_email_notifies_with_retailer_context(
    ctx: BotContext, quince_eml: Path, fake_draft_factory, notifier
) -> None:
    await process_email(
        ctx,
        InboxFile(path=quince_eml, source="email"),
        ingest=lambda p, **kw: fake_draft_factory(p),
        notify=notifier,
    )
    assert len(notifier.posts) == 1
    msg = notifier.posts[0]
    assert "Quince" in msg
    assert "$59.90" in msg or "59.90" in msg


# ─────────────────────────────────────────────────────────────────────────────
# Multi-item: one .eml → N independent rows
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_process_email_multi_item_splits(
    ctx: BotContext, multi_eml: Path, fake_draft_factory, notifier
) -> None:
    results = await process_email(
        ctx,
        InboxFile(path=multi_eml, source="email"),
        ingest=lambda p, **kw: fake_draft_factory(p),
        notify=notifier,
    )
    assert len(results) == 2
    assert all(r.outcome is ProcessOutcome.OK for r in results)
    assert ctx.repo.items.count() == 2
    # One Discord message per item.
    assert len(notifier.posts) == 2


# ─────────────────────────────────────────────────────────────────────────────
# No-image path: persist text-only row + prompt for photo
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_process_email_no_image_persists_text_only(
    ctx: BotContext, no_image_eml: Path, notifier
) -> None:
    results = await process_email(
        ctx,
        InboxFile(path=no_image_eml, source="email"),
        ingest=lambda p, **kw: pytest.fail("ingest must not be called when no image"),
        notify=notifier,
    )
    assert len(results) == 1
    assert results[0].outcome is ProcessOutcome.OK
    items = ctx.repo.items.list_by_category()
    assert len(items) == 1
    assert items[0].brand == "Quince"
    assert items[0].name == "Linen Wrap Coat"
    assert items[0].image_raw_path is None
    # Notifier should explicitly prompt for a photo.
    assert "photo" in notifier.posts[0].lower()


# ─────────────────────────────────────────────────────────────────────────────
# Failure: unknown retailer → quarantine
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_process_email_unknown_retailer_quarantines(
    ctx: BotContext, unknown_eml: Path, notifier
) -> None:
    results = await process_email(
        ctx,
        InboxFile(path=unknown_eml, source="email"),
        ingest=lambda p, **kw: pytest.fail("ingest must not be called"),
        notify=notifier,
    )
    assert len(results) == 1
    assert results[0].outcome is ProcessOutcome.FAILED
    assert "UnknownRetailerError" in (results[0].error or "")
    # Source quarantined.
    assert not unknown_eml.exists()
    failed = list(
        (ctx.config.paths.inbox_dir / ".failed" / "email").iterdir()
    )
    assert len(failed) == 1
    assert ctx.repo.items.count() == 0
    # Audit + Discord both report the failure.
    kinds = [r["kind"] for r in ctx.repo.audit.recent(limit=5)]
    assert "inbox_failed" in kinds
    assert ":warning:" in notifier.posts[0]
