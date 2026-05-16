"""
Clawbot entry point.

Two modes:
    1. ``discord.enabled = true`` in config → wire the DB, build the bot,
       load every cog as a discord.py extension, sync the command tree
       against the operator's guild, and call ``bot.start(token)``.
    2. ``discord.enabled = false`` → fall back to the foundation-pass
       behavior of staying alive (so docker-compose's healthcheck sees a
       running container) until SIGTERM. Useful during NUC bring-up and
       in tests.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import time
from pathlib import Path

from clawbot.config import ClawbotConfig, load_config
from clawbot.db import Repo, connect, run_migrations
from clawbot.discord.bot import BotContext, build_bot
from clawbot.discord_secrets import DiscordSecrets, load_discord_secrets

# clawbot.inbox.* and clawbot.scheduler pull in APScheduler. Foundation-pass
# operators (discord.enabled=false) shouldn't need that extras group, so the
# imports happen inside ``_run_bot`` below — see _setup_hook().

logger = logging.getLogger(__name__)

# Cog modules loaded as discord.py extensions on startup. Order doesn't
# matter functionally; we list them grouped by build-step for readability.
_COG_MODULES: tuple[str, ...] = (
    "clawbot.discord.cogs.health",
    "clawbot.discord.cogs.profile",
    "clawbot.discord.cogs.wardrobe",
    "clawbot.discord.cogs.items",
)

_MIGRATIONS_DIR = Path(__file__).resolve().parent / "db" / "migrations"


def _configure_logging(cfg: ClawbotConfig) -> None:
    logging.basicConfig(
        level=cfg.logging.level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _idle_until_signal() -> None:
    """Foundation-pass behavior — block until SIGTERM/SIGINT."""
    stop = False

    def _handle_signal(sig, frame):  # noqa: ANN001
        nonlocal stop
        logger.info("Received signal %s, shutting down.", sig)
        stop = True

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    while not stop:
        time.sleep(1)


async def _run_bot(ctx: BotContext, secrets: DiscordSecrets) -> None:
    """Async bootstrap: load cogs, start the scheduler, run forever.

    The scheduler is built *after* the bot exists so its jobs can post to
    the operator's channel via ``ChannelNotifier``. We stash the scheduler
    on the bot so close-time cleanup is one call.
    """
    import discord

    from clawbot.inbox.notify import ChannelNotifier, NullNotifier, Notifier
    from clawbot.scheduler import build_scheduler

    bot = build_bot(ctx)

    async def _setup_hook() -> None:
        for module in _COG_MODULES:
            await bot.load_extension(module)
        if ctx.config.discord.sync_commands_on_startup:
            guild = discord.Object(id=secrets.guild_id)
            bot.tree.copy_global_to(guild=guild)
            await bot.tree.sync(guild=guild)
            logger.info("Synced slash commands to guild %s", secrets.guild_id)

        notifier: Notifier = (
            ChannelNotifier(bot=bot, channel_id=secrets.channel_id)
            if secrets.channel_id is not None
            else NullNotifier()
        )
        scheduler = build_scheduler(ctx, notifier=notifier)
        scheduler.start()
        bot._clawbot_scheduler = scheduler  # type: ignore[attr-defined]
        logger.info(
            "Scheduler started: inbox_sweep every %ds, disk_check at %r",
            ctx.config.schedule.inbox_sweep_seconds,
            ctx.config.schedule.disk_check,
        )

    async def _on_close() -> None:
        sched = getattr(bot, "_clawbot_scheduler", None)
        if sched is not None and sched.running:
            sched.shutdown(wait=False)
            logger.info("Scheduler stopped.")

    bot.setup_hook = _setup_hook  # type: ignore[assignment]
    bot.close = _wrap_close(bot.close, _on_close)  # type: ignore[assignment]
    await bot.start(secrets.token)


def _wrap_close(original_close, hook):
    """Chain an async cleanup hook in front of ``Bot.close``."""

    async def _close() -> None:
        try:
            await hook()
        finally:
            await original_close()

    return _close


def main() -> None:
    """Process entry point — invoked by ``python -m clawbot.main``."""
    cfg = load_config()
    _configure_logging(cfg)

    if not cfg.discord.enabled:
        logger.info("Discord disabled in config — idling until signal.")
        _idle_until_signal()
        return

    secrets = load_discord_secrets()

    conn = connect(cfg.paths.db_path)
    run_migrations(conn, _MIGRATIONS_DIR)
    ctx = BotContext(repo=Repo(conn=conn), config=cfg, secrets=secrets)

    logger.info("Starting Discord bot.")
    asyncio.run(_run_bot(ctx, secrets))


if __name__ == "__main__":
    main()
