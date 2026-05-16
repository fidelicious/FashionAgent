"""
Tests for the hourly disk_check job.

This is the job ``/health`` deliberately omitted. It runs on an hourly
cron, checks ``shutil.disk_usage(paths.home)`` against
``health.disk_warn_pct`` and ``health.disk_critical_pct``, and posts to
the operator channel when the threshold is breached.

We don't post when usage stays below the warn threshold — operators don't
want hourly "everything fine" pings.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from clawbot.discord.bot import BotContext
from clawbot.inbox.disk_check import (
    DiskUsage,
    DiskStatus,
    check_disk,
    handle_disk_check,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _usage(total: int, used: int) -> DiskUsage:
    return DiskUsage(total=total, used=used, free=total - used)


# ─────────────────────────────────────────────────────────────────────────────
# Pure threshold logic
# ─────────────────────────────────────────────────────────────────────────────


def test_disk_below_warn_is_ok(ctx: BotContext) -> None:
    # warn=85, critical=95 by default
    status = check_disk(_usage(total=100, used=50), config=ctx.config)
    assert status is DiskStatus.OK


def test_disk_above_warn_is_warn(ctx: BotContext) -> None:
    status = check_disk(_usage(total=100, used=86), config=ctx.config)
    assert status is DiskStatus.WARN


def test_disk_above_critical_is_critical(ctx: BotContext) -> None:
    status = check_disk(_usage(total=100, used=96), config=ctx.config)
    assert status is DiskStatus.CRITICAL


def test_disk_exactly_at_warn_is_warn(ctx: BotContext) -> None:
    """Threshold semantics are inclusive on the low side — 85% triggers warn."""
    ctx.config.health.disk_warn_pct = 85
    ctx.config.health.disk_critical_pct = 95
    status = check_disk(_usage(total=100, used=85), config=ctx.config)
    assert status is DiskStatus.WARN


# ─────────────────────────────────────────────────────────────────────────────
# handle_disk_check — Discord-side wrapper
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_disk_check_silent_when_ok(
    ctx: BotContext, notifier
) -> None:
    await handle_disk_check(
        ctx,
        notifier=notifier,
        usage_probe=lambda path: _usage(100, 50),
    )
    assert notifier.posts == []  # silence on green


@pytest.mark.asyncio
async def test_handle_disk_check_warns_at_threshold(
    ctx: BotContext, notifier
) -> None:
    await handle_disk_check(
        ctx,
        notifier=notifier,
        usage_probe=lambda path: _usage(100, 86),
    )
    assert len(notifier.posts) == 1
    assert ":warning:" in notifier.posts[0]
    assert "86%" in notifier.posts[0]


@pytest.mark.asyncio
async def test_handle_disk_check_critical_uses_red(
    ctx: BotContext, notifier
) -> None:
    await handle_disk_check(
        ctx,
        notifier=notifier,
        usage_probe=lambda path: _usage(100, 97),
    )
    assert len(notifier.posts) == 1
    # Critical messages should be visibly more urgent than WARN ones.
    msg = notifier.posts[0]
    assert ":rotating_light:" in msg or "CRITICAL" in msg


@pytest.mark.asyncio
async def test_handle_disk_check_audit_logs_alert(
    ctx: BotContext, notifier
) -> None:
    """Disk alerts get an audit row so the operator can grep history later."""
    await handle_disk_check(
        ctx,
        notifier=notifier,
        usage_probe=lambda path: _usage(100, 96),
    )
    kinds = [r["kind"] for r in ctx.repo.audit.recent(limit=5)]
    assert "disk_alert" in kinds
