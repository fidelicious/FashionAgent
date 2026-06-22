"""
/health cog.

Operator-only smoke test. Reports on:
    - DB connection reachable (SELECT 1)
    - All on-disk migrations have been applied (no schema drift)
    - Ollama is reachable on its base URL

The check core (``check_health``) is pure and synchronous — Discord-free.
The cog wires it into a slash command and renders the report ephemerally.

The Ollama probe is injected (default: stdlib urllib) so tests stay offline.
"""

from __future__ import annotations

import logging
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

import discord
from discord import app_commands

from clawbot.discord.bot import BotContext, InteractionLike

logger = logging.getLogger(__name__)

# Default probe timeout. 2s is enough to distinguish "down" from "slow" on a LAN
# and short enough not to make /health feel sluggish to the operator.
_OLLAMA_TIMEOUT_S = 2.0


# ─────────────────────────────────────────────────────────────────────────────
# Report types
# ─────────────────────────────────────────────────────────────────────────────


class HealthStatus(str, Enum):
    """Worst-of aggregation across individual checks.

    RED      = a foundation check failed (DB). Bot can't serve requests.
    DEGRADED = a non-critical check failed (Ollama, migrations). Reads work
               but outfits / new features may not.
    OK       = everything green.
    """

    OK = "ok"
    DEGRADED = "degraded"
    RED = "red"


# Which check, if it fails, escalates to which status. Anything not listed
# here is treated as DEGRADED on failure.
_CRITICAL_CHECKS = frozenset({"db"})


@dataclass
class HealthReport:
    """A single /health call's result. ``status`` is derived from ``checks``."""

    checks: dict[str, bool] = field(default_factory=dict)
    details: dict[str, str] = field(default_factory=dict)

    @property
    def status(self) -> HealthStatus:
        failed = [name for name, ok in self.checks.items() if not ok]
        if not failed:
            return HealthStatus.OK
        if any(name in _CRITICAL_CHECKS for name in failed):
            return HealthStatus.RED
        return HealthStatus.DEGRADED


# ─────────────────────────────────────────────────────────────────────────────
# Probes
# ─────────────────────────────────────────────────────────────────────────────


OllamaProbe = Callable[[str, float], bool]


def default_ollama_probe(base_url: str, timeout: float) -> bool:
    """HTTP GET ``{base_url}/api/tags`` and return True on a 2xx response.

    Uses stdlib urllib so /health has no transitive dependency on httpx — the
    real LLM client (Step 11) brings httpx in for streaming + retries, but we
    don't need any of that here.
    """
    url = base_url.rstrip("/") + "/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, socket.timeout, ConnectionError, OSError):
        return False


def _check_db(ctx: BotContext) -> bool:
    """SELECT 1 against the open connection."""
    try:
        cur = ctx.repo.conn.execute("SELECT 1")
        cur.fetchone()
        return True
    except Exception:  # pragma: no cover — exercised via closed-conn test
        return False


def _check_migrations(ctx: BotContext, migrations_dir: Optional[Path]) -> bool:
    """Compare on-disk migration files to applied rows in schema_migrations.

    Any pending migration → False. We're conservative on errors (False) so a
    misconfigured path surfaces as a visible warning rather than a green tick.
    """
    try:
        applied = {
            int(r["version"])
            for r in ctx.repo.conn.execute(
                "SELECT version FROM schema_migrations"
            )
        }
    except Exception:
        return False

    if migrations_dir is None:
        # Resolve from package layout; works in both dev and container.
        migrations_dir = (
            Path(__file__).resolve().parent.parent.parent / "db" / "migrations"
        )
    if not migrations_dir.exists():
        return False

    on_disk: set[int] = set()
    for p in migrations_dir.glob("*.sql"):
        head = p.name.split("_", 1)[0]
        try:
            on_disk.add(int(head))
        except ValueError:
            continue

    return on_disk.issubset(applied)


# ─────────────────────────────────────────────────────────────────────────────
# Core check + Discord handler
# ─────────────────────────────────────────────────────────────────────────────


def check_health(
    ctx: BotContext,
    *,
    ollama_probe: Optional[OllamaProbe] = None,
    migrations_dir: Optional[Path] = None,
) -> HealthReport:
    """Run every /health probe and return a ``HealthReport``.

    Synchronous and side-effect-free; safe to call from tests without an
    event loop.
    """
    probe = ollama_probe or default_ollama_probe

    report = HealthReport()
    report.checks["db"] = _check_db(ctx)
    report.checks["migrations"] = _check_migrations(ctx, migrations_dir)

    try:
        report.checks["ollama"] = probe(
            ctx.config.models.ollama_base_url, _OLLAMA_TIMEOUT_S
        )
    except Exception as e:
        report.checks["ollama"] = False
        report.details["ollama"] = f"probe raised: {type(e).__name__}"

    return report


def render_health(report: HealthReport) -> str:
    """Format a HealthReport as a compact monospaced message.

    Layout chosen for ephemeral replies (no embed, looks fine on mobile):

        Status: OK
        ✓ db
        ✓ migrations
        ✓ ollama
    """
    lines: list[str] = [f"**Status:** `{report.status.value.upper()}`"]
    for name, ok in report.checks.items():
        mark = "✓" if ok else "✗"
        suffix = f" — {report.details[name]}" if name in report.details else ""
        lines.append(f"{mark} {name}{suffix}")
    return "\n".join(lines)


async def handle_health(
    ctx: BotContext,
    interaction: InteractionLike,
    *,
    ollama_probe: Optional[OllamaProbe] = None,
) -> None:
    """Discord-side wrapper: run probes, send the report ephemerally."""
    report = check_health(ctx, ollama_probe=ollama_probe)
    await interaction.response.send_message(
        render_health(report), ephemeral=True
    )


# ─────────────────────────────────────────────────────────────────────────────
# Cog wiring — only imported when discord.py is available.
# ─────────────────────────────────────────────────────────────────────────────


async def handle_run_outfit(
    ctx: BotContext,
    interaction: InteractionLike,
    *,
    bot: Any,
    occasion: str = "casual",
    _run_fn: Any = None,
    _notifier: Any = None,
    _collage_dir: Optional[Path] = None,
) -> None:
    """Trigger the daily outfit pipeline immediately and reply with a summary.

    Posts the collage to the configured Discord channel (same path as the
    07:00 cron) and sends the operator an ephemeral confirmation with the
    score and fallback flag.

    ``_run_fn`` and ``_notifier`` are test-injection points; production code
    leaves them None and the real implementations are used.
    """
    from clawbot.inbox.notify import ChannelNotifier, NullNotifier
    from clawbot.outfits.daily import run_daily_outfit
    from clawbot.outfits.llm import OllamaConfig

    if _notifier is None:
        _notifier = (
            ChannelNotifier(bot=bot, channel_id=ctx.secrets.channel_id)
            if ctx.secrets.channel_id
            else NullNotifier()
        )
    if _run_fn is None:
        _run_fn = run_daily_outfit

    collage_dir = _collage_dir or Path(ctx.config.paths.images_dir) / "outfits"
    collage_dir.mkdir(parents=True, exist_ok=True)
    ollama = OllamaConfig(
        base_url=ctx.config.models.ollama_base_url,
        model=ctx.config.models.llm,
        timeout_seconds=ctx.config.models.llm_timeout_seconds,
        max_retries=ctx.config.models.llm_max_retries,
    )

    try:
        result = await _run_fn(
            repo=ctx.repo,
            notifier=_notifier,
            collage_dir=collage_dir,
            occasion=occasion,
            ollama_config=ollama,
        )
    except Exception as exc:
        logger.exception("run_outfit triggered manually but failed: %s", exc)
        await interaction.followup.send(
            f"\u26a0\ufe0f Daily outfit run failed: {exc}", ephemeral=True
        )
        return

    if result.outfit_id is None:
        await interaction.followup.send(
            "\u26a0\ufe0f No outfit generated — check wardrobe or season/occasion.",
            ephemeral=True,
        )
    else:
        fallback = " (LLM fallback used)" if result.fallback_used else ""
        await interaction.followup.send(
            f"\u2705 Outfit posted to channel.\n"
            f"  score: `{result.score:.2f}` · season: `{result.season}`"
            f" · occasion: `{result.occasion}`{fallback}",
            ephemeral=True,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Cog wiring — only imported when discord.py is available.
# ─────────────────────────────────────────────────────────────────────────────


async def setup(bot: Any) -> None:
    """discord.py extension entrypoint. Adds the /health and /run_outfit commands."""
    ctx: BotContext = bot.clawbot_ctx

    @bot.tree.command(name="health", description="Show bot health status.")
    async def _health(interaction: discord.Interaction) -> None:  # type: ignore[misc]
        await handle_health(ctx, interaction)

    @bot.tree.command(
        name="run_outfit",
        description="Trigger today's outfit push immediately (operator only).",
    )
    @app_commands.describe(
        occasion="Occasion to dress for (default: casual)",
    )
    @app_commands.choices(occasion=[
        app_commands.Choice(name="casual", value="casual"),
        app_commands.Choice(name="smart-casual", value="smart-casual"),
        app_commands.Choice(name="business", value="business"),
        app_commands.Choice(name="formal", value="formal"),
    ])
    async def _run_outfit(
        interaction: discord.Interaction,
        occasion: str = "casual",
    ) -> None:  # type: ignore[misc]
        # Defer because the LLM + Pillow pipeline takes 10-60s.
        await interaction.response.defer(ephemeral=True, thinking=True)
        await handle_run_outfit(ctx, interaction, bot=bot, occasion=occasion)
