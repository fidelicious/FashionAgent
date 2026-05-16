"""
Tests for /health.

Strategy:
    - ``check_health`` is the pure synchronous core. It accepts an injected
      ``ollama_probe`` callable so we never make real HTTP.
    - ``handle_health`` is the async Discord-side wrapper that picks the
      default probe, formats the report, and sends ephemerally.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from clawbot.db.repo import Repo
from clawbot.discord.bot import BotContext
from clawbot.discord.cogs.health import (
    HealthReport,
    HealthStatus,
    check_health,
    handle_health,
)

from .conftest import FakeInteraction


# ─────────────────────────────────────────────────────────────────────────────
# check_health: pure, sync, deterministic
# ─────────────────────────────────────────────────────────────────────────────


def test_all_good(ctx: BotContext) -> None:
    report = check_health(ctx, ollama_probe=lambda url, timeout: True)
    assert report.status is HealthStatus.OK
    assert report.checks["db"] is True
    assert report.checks["migrations"] is True
    assert report.checks["ollama"] is True


def test_ollama_unreachable_is_degraded(ctx: BotContext) -> None:
    report = check_health(ctx, ollama_probe=lambda url, timeout: False)
    assert report.status is HealthStatus.DEGRADED
    assert report.checks["ollama"] is False
    assert report.checks["db"] is True


def test_ollama_probe_exception_does_not_propagate(ctx: BotContext) -> None:
    def boom(url: str, timeout: float) -> bool:
        raise ConnectionError("nope")

    report = check_health(ctx, ollama_probe=boom)
    assert report.status is HealthStatus.DEGRADED
    assert report.checks["ollama"] is False


def test_db_closed_marks_red(ctx: BotContext, repo: Repo) -> None:
    """If the connection is closed, `SELECT 1` raises — health goes RED."""
    repo.conn.close()
    report = check_health(ctx, ollama_probe=lambda url, timeout: True)
    assert report.status is HealthStatus.RED
    assert report.checks["db"] is False


def test_migrations_behind_marks_degraded(
    ctx: BotContext, tmp_path: Path
) -> None:
    """If a migration file exists on disk but not in schema_migrations, warn."""
    # Pretend there's a future migration by adding a fake row gap.
    # Easiest fake: drop one applied row so the on-disk count > applied count.
    ctx.repo.conn.execute(
        "DELETE FROM schema_migrations WHERE version = "
        "(SELECT MAX(version) FROM schema_migrations)"
    )
    ctx.repo.conn.commit()

    report = check_health(ctx, ollama_probe=lambda url, timeout: True)
    assert report.status is HealthStatus.DEGRADED
    assert report.checks["migrations"] is False


# ─────────────────────────────────────────────────────────────────────────────
# handle_health: ephemeral reply, message contains each check
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_health_replies_ephemerally(
    ctx: BotContext, operator_interaction: FakeInteraction
) -> None:
    await handle_health(
        ctx, operator_interaction, ollama_probe=lambda url, timeout: True
    )

    assert len(operator_interaction.response.sent) == 1
    msg = operator_interaction.response.sent[0]
    assert msg["ephemeral"] is True


@pytest.mark.asyncio
async def test_handle_health_message_names_each_check(
    ctx: BotContext, operator_interaction: FakeInteraction
) -> None:
    await handle_health(
        ctx, operator_interaction, ollama_probe=lambda url, timeout: True
    )
    body = operator_interaction.response.sent[0]["content"]
    assert "db" in body.lower()
    assert "migrations" in body.lower()
    assert "ollama" in body.lower()


# ─────────────────────────────────────────────────────────────────────────────
# HealthReport rendering helper
# ─────────────────────────────────────────────────────────────────────────────


def test_health_report_status_aggregation() -> None:
    """The aggregate status picks the worst-of: RED > DEGRADED > OK."""
    r1 = HealthReport(
        checks={"db": True, "migrations": True, "ollama": True}
    )
    r2 = HealthReport(
        checks={"db": True, "migrations": True, "ollama": False}
    )
    r3 = HealthReport(
        checks={"db": False, "migrations": True, "ollama": True}
    )
    assert r1.status is HealthStatus.OK
    assert r2.status is HealthStatus.DEGRADED
    assert r3.status is HealthStatus.RED
