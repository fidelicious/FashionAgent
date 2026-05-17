"""
Discord notifier abstraction for inbox sweeps and scheduler jobs.

Why a thin abstraction:
    - ``process_one`` and ``disk_check`` are pure-logic functions in tests;
      they shouldn't import ``discord`` just to send a message.
    - In production we want one place that owns "send to the operator
      channel" semantics — including the failure modes (channel missing,
      bot lost permissions, channel ID never configured).

Two implementations:
    - ``ChannelNotifier``: real, wraps a discord.py Bot + a channel id.
    - ``NullNotifier``: drops every message. Used when ``DISCORD_CHANNEL_ID``
      isn't set in ``.env``, and as a stand-in in tests that don't care
      about output.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class Notifier(Protocol):
    """Minimal surface: post a string, optionally with an image attachment.

    Errors must not propagate — Discord being unreachable can't crash the
    inbox sweep or the daily-outfit job.
    """

    async def post(self, content: str) -> None: ...

    async def post_image(self, content: str, image_path: Path | str) -> None: ...


class NullNotifier:
    """No-op notifier. Used when no DISCORD_CHANNEL_ID is configured."""

    async def post(self, content: str) -> None:
        return None

    async def post_image(self, content: str, image_path: Path | str) -> None:
        return None


class ChannelNotifier:
    """Sends ``content`` to a single Discord channel via a discord.py Bot.

    All failure modes (missing channel id, channel not found, send raised)
    are logged at WARNING and *swallowed* — the inbox sweep and daily
    outfit push must not crash because Discord is unreachable.
    """

    def __init__(self, *, bot: Any, channel_id: int | None) -> None:
        self._bot = bot
        self._channel_id = channel_id

    async def post(self, content: str) -> None:
        channel = self._resolve_channel(content[:80])
        if channel is None:
            return
        try:
            await channel.send(content)
        except Exception as e:
            self._log_send_failure(e, content)

    async def post_image(self, content: str, image_path: Path | str) -> None:
        channel = self._resolve_channel(content[:80])
        if channel is None:
            return
        # Import here so the rest of the module stays importable without
        # discord.py (unit tests for NullNotifier shouldn't pull it in).
        try:
            import discord  # type: ignore[import-not-found]
        except ImportError:
            logger.warning(
                "notifier: discord.py not installed; dropping image message %s",
                str(image_path),
            )
            return
        try:
            await channel.send(content, file=discord.File(str(image_path)))
        except Exception as e:
            self._log_send_failure(e, content)

    # ── internals ──────────────────────────────────────────────────────────
    def _resolve_channel(self, content_preview: str) -> Any:
        if self._channel_id is None:
            return None
        channel = self._bot.get_channel(self._channel_id)
        if channel is None:
            logger.warning(
                "notifier: channel %s not in cache (deleted? bot lacks "
                "permission?). Dropping message: %s",
                self._channel_id,
                content_preview,
            )
        return channel

    def _log_send_failure(self, e: Exception, content: str) -> None:
        logger.warning(
            "notifier: send to channel %s failed (%s: %s). Dropping message: %s",
            self._channel_id,
            type(e).__name__,
            e,
            content[:80],
        )
