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
from typing import Any, Optional, Protocol

logger = logging.getLogger(__name__)


class Notifier(Protocol):
    """Minimal surface: post a string. Errors must not propagate."""

    async def post(self, content: str) -> None: ...


class NullNotifier:
    """No-op notifier. Used when no DISCORD_CHANNEL_ID is configured."""

    async def post(self, content: str) -> None:  # noqa: D401
        return None


class ChannelNotifier:
    """Sends ``content`` to a single Discord channel via a discord.py Bot.

    All failure modes (missing channel id, channel not found, send raised)
    are logged at WARNING and *swallowed* — the inbox sweep must not crash
    because Discord is unreachable.
    """

    def __init__(self, *, bot: Any, channel_id: Optional[int]) -> None:
        self._bot = bot
        self._channel_id = channel_id

    async def post(self, content: str) -> None:
        if self._channel_id is None:
            return
        channel = self._bot.get_channel(self._channel_id)
        if channel is None:
            logger.warning(
                "notifier: channel %s not in cache (deleted? bot lacks "
                "permission?). Dropping message: %s",
                self._channel_id,
                content[:80],
            )
            return
        try:
            await channel.send(content)
        except Exception as e:
            logger.warning(
                "notifier: send to channel %s failed (%s: %s). "
                "Dropping message.",
                self._channel_id,
                type(e).__name__,
                e,
            )
