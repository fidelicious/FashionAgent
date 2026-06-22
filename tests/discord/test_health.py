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
    handle_run_outfit,
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


# ─────────────────────────────────────────────────────────────────────────────
# handle_run_outfit
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_outfit_success_sends_ephemeral_confirmation(
    ctx: BotContext, operator_interaction: FakeInteraction, tmp_path: Path
) -> None:
    """A successful run posts to the channel via the notifier and sends the
    operator an ephemeral score summary."""
    from clawbot.outfits.daily import DailyResult

    posted: list[str] = []

    class _FakeNotifier:
        async def post(self, content: str) -> None:
            posted.append(content)

        async def post_image(self, content: str, image_path) -> None:
            posted.append(content)

    fake_result = DailyResult(
        outfit_id="abc-123",
        collage_path=None,
        score=0.82,
        occasion="casual",
        season="summer",
        fallback_used=False,
    )

    async def _fake_run(**kwargs):  # noqa: ANN001
        return fake_result

    # Defer first, as the real slash command would.
    await operator_interaction.response.defer(ephemeral=True, thinking=True)
    await handle_run_outfit(
        ctx,
        operator_interaction,
        bot=None,  # not needed — we inject run_fn below
        occasion="casual",
        _run_fn=_fake_run,
        _notifier=_FakeNotifier(),
        _collage_dir=tmp_path,
    )

    body = operator_interaction.followup.sent[0]["content"]
    assert "✅" in body
    assert "0.82" in body


@pytest.mark.asyncio
async def test_run_outfit_empty_wardrobe_warns_operator(
    ctx: BotContext, operator_interaction: FakeInteraction, tmp_path: Path
) -> None:
    from clawbot.outfits.daily import DailyResult

    async def _fake_run(**kwargs):  # noqa: ANN001
        return DailyResult(
            outfit_id=None, collage_path=None, score=0.0,
            occasion="casual", season="summer", fallback_used=False,
        )

    await operator_interaction.response.defer(ephemeral=True, thinking=True)
    await handle_run_outfit(
        ctx,
        operator_interaction,
        bot=None,
        occasion="casual",
        _run_fn=_fake_run,
        _notifier=None,
        _collage_dir=tmp_path,
    )

    body = operator_interaction.followup.sent[0]["content"]
    assert "⚠️" in body


@pytest.mark.asyncio
async def test_run_outfit_pipeline_failure_replies_with_error(
    ctx: BotContext, operator_interaction: FakeInteraction, tmp_path: Path
) -> None:
    async def _failing_run(**kwargs):  # noqa: ANN001
        raise RuntimeError("ollama timeout")

    await operator_interaction.response.defer(ephemeral=True, thinking=True)
    await handle_run_outfit(
        ctx,
        operator_interaction,
        bot=None,
        occasion="casual",
        _run_fn=_failing_run,
        _notifier=None,
        _collage_dir=tmp_path,
    )

    body = operator_interaction.followup.sent[0]["content"]
    assert "⚠️" in body
    assert "ollama timeout" in body
