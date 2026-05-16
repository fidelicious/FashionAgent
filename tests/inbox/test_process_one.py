"""
Tests for ``process_one`` — the per-file ingest path.

Covers:
    - Success: row inserted, embedding stored, file moved to .processed/,
      audit row written, notifier posted a 'new draft' message.
    - Failure: source moved to .failed/ with a timestamp suffix, audit row
      written with the exception class, notifier got a 'failed' message,
      no half-written DB rows.
    - Filename collisions in .processed/ get `(2)`, `(3)` suffixes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from clawbot.discord.bot import BotContext
from clawbot.inbox.watcher import (
    InboxFile,
    ProcessOutcome,
    process_one,
)


# ─────────────────────────────────────────────────────────────────────────────
# Success path
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_process_one_success_persists_and_moves(
    ctx: BotContext, stable_screenshot, fake_draft_factory, notifier
) -> None:
    raw = stable_screenshot("cardigan.jpg")
    file = InboxFile(path=raw, source="screenshot")

    result = await process_one(
        ctx,
        file,
        ingest=lambda p, **kw: fake_draft_factory(p),
        notify=notifier,
    )

    assert result.outcome is ProcessOutcome.OK
    assert result.item_id is not None
    # Wardrobe row exists.
    items = ctx.repo.items.list_by_category()
    assert len(items) == 1
    assert items[0].id == result.item_id
    # Source file was moved into .processed/screenshots/<date>/.
    assert not raw.exists()
    processed = list(
        (ctx.config.paths.inbox_dir / ".processed" / "screenshots")
        .rglob("cardigan.jpg")
    )
    assert len(processed) == 1


@pytest.mark.asyncio
async def test_process_one_success_writes_embedding(
    ctx: BotContext, stable_screenshot, fake_draft_factory
) -> None:
    raw = stable_screenshot()
    await process_one(
        ctx,
        InboxFile(path=raw, source="screenshot"),
        ingest=lambda p, **kw: fake_draft_factory(p),
    )
    hits = ctx.repo.items.find_similar([0.0] * 512, k=1)
    assert hits, "embedding should be queryable post-ingest"


@pytest.mark.asyncio
async def test_process_one_success_audit_logged(
    ctx: BotContext, stable_screenshot, fake_draft_factory
) -> None:
    raw = stable_screenshot()
    await process_one(
        ctx,
        InboxFile(path=raw, source="screenshot"),
        ingest=lambda p, **kw: fake_draft_factory(p),
    )
    kinds = [r["kind"] for r in ctx.repo.audit.recent(limit=10)]
    assert "inbox_ingested" in kinds


@pytest.mark.asyncio
async def test_process_one_success_notifies(
    ctx: BotContext, stable_screenshot, fake_draft_factory, notifier
) -> None:
    raw = stable_screenshot("hat.jpg")
    await process_one(
        ctx,
        InboxFile(path=raw, source="screenshot"),
        ingest=lambda p, **kw: fake_draft_factory(p),
        notify=notifier,
    )
    assert len(notifier.posts) == 1
    assert "hat.jpg" in notifier.posts[0]
    assert ":new:" in notifier.posts[0]


# ─────────────────────────────────────────────────────────────────────────────
# Failure path
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_process_one_failure_quarantines_file(
    ctx: BotContext, stable_screenshot, notifier
) -> None:
    raw = stable_screenshot("broken.jpg")

    def boom(p: Path, **_kw):
        raise RuntimeError("CLIP weights missing")

    result = await process_one(
        ctx,
        InboxFile(path=raw, source="screenshot"),
        ingest=boom,
        notify=notifier,
    )

    assert result.outcome is ProcessOutcome.FAILED
    assert "CLIP weights missing" in (result.error or "")
    assert not raw.exists()
    failed = list(
        (ctx.config.paths.inbox_dir / ".failed" / "screenshots").iterdir()
    )
    assert len(failed) == 1
    # Filename gets a UTC timestamp suffix so retries don't collide.
    assert failed[0].name.startswith("broken.jpg.")


@pytest.mark.asyncio
async def test_process_one_failure_audit_logged(
    ctx: BotContext, stable_screenshot
) -> None:
    raw = stable_screenshot("broken.jpg")
    await process_one(
        ctx,
        InboxFile(path=raw, source="screenshot"),
        ingest=lambda p, **kw: (_ for _ in ()).throw(ValueError("bad")),
    )
    rows = [r for r in ctx.repo.audit.recent(limit=10) if r["kind"] == "inbox_failed"]
    assert len(rows) == 1
    assert "ValueError" in rows[0]["message"]


@pytest.mark.asyncio
async def test_process_one_failure_notifies(
    ctx: BotContext, stable_screenshot, notifier
) -> None:
    raw = stable_screenshot("broken.jpg")
    await process_one(
        ctx,
        InboxFile(path=raw, source="screenshot"),
        ingest=lambda p, **kw: (_ for _ in ()).throw(RuntimeError("oops")),
        notify=notifier,
    )
    assert len(notifier.posts) == 1
    assert ":warning:" in notifier.posts[0]
    assert "broken.jpg" in notifier.posts[0]


@pytest.mark.asyncio
async def test_process_one_failure_does_not_leave_db_rows(
    ctx: BotContext, stable_screenshot
) -> None:
    """If ingest raises we must NOT insert a half-built wardrobe row."""
    raw = stable_screenshot()
    await process_one(
        ctx,
        InboxFile(path=raw, source="screenshot"),
        ingest=lambda p, **kw: (_ for _ in ()).throw(RuntimeError("oops")),
    )
    assert ctx.repo.items.count() == 0


# ─────────────────────────────────────────────────────────────────────────────
# Filename collisions in .processed/
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_process_one_handles_duplicate_filename(
    ctx: BotContext, stable_screenshot, fake_draft_factory
) -> None:
    """Two files with the same name on the same day get `(2)` suffix on the second move."""
    raw1 = stable_screenshot("dup.jpg")
    await process_one(
        ctx,
        InboxFile(path=raw1, source="screenshot"),
        ingest=lambda p, **kw: fake_draft_factory(p),
    )
    raw2 = stable_screenshot("dup.jpg")
    await process_one(
        ctx,
        InboxFile(path=raw2, source="screenshot"),
        ingest=lambda p, **kw: fake_draft_factory(p),
    )

    names = sorted(
        p.name
        for p in (ctx.config.paths.inbox_dir / ".processed" / "screenshots").rglob("*.jpg")
    )
    assert names == ["dup(2).jpg", "dup.jpg"]
