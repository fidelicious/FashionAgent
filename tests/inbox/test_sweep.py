"""
Tests for ``sweep`` — the per-tick orchestrator.

Sweep should:
    - Return an empty SweepReport quickly when the inbox is empty.
    - Aggregate ok/failed counts across the per-file results.
    - Process files serially (no parallelism; 8 GB NUC budget).
    - Skip the .processed/.failed dirs that itself created.
"""

from __future__ import annotations

import pytest

from clawbot.discord.bot import BotContext
from clawbot.inbox.watcher import ProcessOutcome, SweepReport, sweep


@pytest.mark.asyncio
async def test_sweep_empty_inbox(ctx: BotContext) -> None:
    report = await sweep(ctx, ingest=lambda p, **kw: None)  # type: ignore[arg-type]
    assert report.total == 0
    assert report.ok == 0
    assert report.failed == 0


@pytest.mark.asyncio
async def test_sweep_processes_each_file(
    ctx: BotContext, stable_screenshot, fake_draft_factory
) -> None:
    stable_screenshot("a.jpg")
    stable_screenshot("b.jpg")
    stable_screenshot("c.jpg")

    report = await sweep(
        ctx, ingest=lambda p, **kw: fake_draft_factory(p)
    )

    assert report.total == 3
    assert report.ok == 3
    assert report.failed == 0
    assert ctx.repo.items.count() == 3


@pytest.mark.asyncio
async def test_sweep_mixes_ok_and_failed(
    ctx: BotContext, stable_screenshot, fake_draft_factory
) -> None:
    stable_screenshot("good1.jpg")
    stable_screenshot("bad.jpg")
    stable_screenshot("good2.jpg")

    def ingest(path, **kw):
        if path.name == "bad.jpg":
            raise RuntimeError("nope")
        return fake_draft_factory(path)

    report = await sweep(ctx, ingest=ingest)

    assert report.ok == 2
    assert report.failed == 1
    assert ctx.repo.items.count() == 2


@pytest.mark.asyncio
async def test_sweep_does_not_revisit_processed(
    ctx: BotContext, stable_screenshot, fake_draft_factory
) -> None:
    """After a successful sweep, the next sweep must find nothing — the
    moved files live under .processed/ which discover() skips."""
    stable_screenshot("once.jpg")

    first = await sweep(ctx, ingest=lambda p, **kw: fake_draft_factory(p))
    assert first.total == 1

    second = await sweep(ctx, ingest=lambda p, **kw: fake_draft_factory(p))
    assert second.total == 0


@pytest.mark.asyncio
async def test_sweep_processes_email_alongside_screenshots(
    ctx, stable_screenshot, fake_draft_factory, notifier
) -> None:
    """One sweep should pick up both a screenshot and a Quince .eml and
    route each through its own processor."""
    import base64
    from email.mime.image import MIMEImage
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    stable_screenshot("cardigan.jpg")

    email_dir = ctx.config.paths.inbox_dir / "email"
    email_dir.mkdir(parents=True, exist_ok=True)
    msg = MIMEMultipart("related")
    msg["From"] = "orders@quince.com"
    msg["Subject"] = "Order"
    msg.attach(
        MIMEText(
            '<html><body><div class="item">'
            '<img src="cid:i1" />'
            '<p class="product-name">Sweater</p>'
            '<p class="price">$59.90</p></div></body></html>',
            "html",
        )
    )
    tiny = base64.b64decode(
        b"/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAAEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEB"
        b"AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEB/9sAQwEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEB"
        b"AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEB/8AAEQgAAQABAwEiAAIRAQMRAf/EAB8A"
        b"AAEFAQEBAQEBAAAAAAAAAAABAgMEBQYHCAkKC//EALUQAAIBAwMCBAMFBQQEAAABfQECAwAEEQUSITFB"
        b"BhNRYQcicRQygZGhCCNCscEVUtHwJDNicoIJChYXGBkaJSYnKCkqNDU2Nzg5OkNERUZHSElKU1RVVldY"
        b"WVpjZGVmZ2hpanN0dXZ3eHl6g4SFhoeIiYqSk5SVlpeYmZqio6Slpqeoqaqys7S1tre4ubrCw8TFxsfI"
        b"ycrS09TV1tfY2drh4uPk5ebn6Onq8fLz9PX29/j5+v/aAAwDAQACEQMRAD8A/v4oA//Z"
    )
    img = MIMEImage(tiny, _subtype="jpeg")
    img.add_header("Content-ID", "<i1>")
    msg.attach(img)

    eml = email_dir / "order.eml"
    eml.write_bytes(msg.as_bytes())
    import os, time
    past = time.time() - 30
    os.utime(eml, (past, past))

    report = await sweep(
        ctx,
        ingest=lambda p, **kw: fake_draft_factory(p),
        notify=notifier,
    )
    assert report.ok == 2  # 1 screenshot + 1 item from email
    assert ctx.repo.items.count() == 2


@pytest.mark.asyncio
async def test_sweep_calls_on_complete_when_nonempty(
    ctx: BotContext, stable_screenshot, fake_draft_factory
) -> None:
    """on_complete fires only for sweeps that actually processed something —
    keeps the daily log readable instead of one row per quiet tick."""
    received: list[SweepReport] = []

    async def hook(r: SweepReport) -> None:
        received.append(r)

    # Empty tick — no hook call.
    await sweep(
        ctx,
        ingest=lambda p, **kw: fake_draft_factory(p),
        on_complete=hook,
    )
    assert received == []

    # File present — hook fires.
    stable_screenshot()
    await sweep(
        ctx,
        ingest=lambda p, **kw: fake_draft_factory(p),
        on_complete=hook,
    )
    assert len(received) == 1
    assert received[0].ok == 1
