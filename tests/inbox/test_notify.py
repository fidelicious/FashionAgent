"""
Tests for the Discord channel notifier.

The notifier is the only place ``DISCORD_CHANNEL_ID`` is used. If the
channel ID isn't set or the channel can't be resolved (operator deleted
it, bot lost permissions), the notifier must degrade gracefully — log
and drop the message rather than crash the sweep job.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import pytest

from clawbot.discord.bot import BotContext
from clawbot.inbox.notify import ChannelNotifier, NullNotifier


# ─────────────────────────────────────────────────────────────────────────────
# Fake bot — discord.Client.get_channel returns a Messageable or None.
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class FakeChannel:
    sent: list[str] = field(default_factory=list)

    async def send(self, content: str) -> None:
        self.sent.append(content)


@dataclass
class FakeBot:
    channels: dict[int, FakeChannel] = field(default_factory=dict)
    raise_on_send: bool = False

    def get_channel(self, channel_id: int) -> Optional[FakeChannel]:
        if self.raise_on_send and channel_id in self.channels:
            class _Boom:
                async def send(self, content: str) -> None:
                    raise RuntimeError("Forbidden")

            return _Boom()  # type: ignore[return-value]
        return self.channels.get(channel_id)


# ─────────────────────────────────────────────────────────────────────────────
# ChannelNotifier
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_channel_notifier_sends_to_configured_channel(
    ctx: BotContext,
) -> None:
    bot = FakeBot(channels={3: FakeChannel()})  # secrets.channel_id == 3
    notifier = ChannelNotifier(bot=bot, channel_id=ctx.secrets.channel_id)

    await notifier.post("hello")
    assert bot.channels[3].sent == ["hello"]


@pytest.mark.asyncio
async def test_channel_notifier_drops_when_channel_id_missing() -> None:
    """If channel_id is None, post() is a no-op (don't crash the sweep)."""
    bot = FakeBot()
    notifier = ChannelNotifier(bot=bot, channel_id=None)

    await notifier.post("hello")  # must not raise


@pytest.mark.asyncio
async def test_channel_notifier_logs_when_channel_unresolved(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """If get_channel() returns None, log a warning instead of raising."""
    bot = FakeBot()  # no channel registered
    notifier = ChannelNotifier(bot=bot, channel_id=999)

    with caplog.at_level(logging.WARNING):
        await notifier.post("hello")
    assert any("999" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_channel_notifier_logs_when_send_raises(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A 403/HTTP exception from .send() must not propagate up to the sweep."""
    bot = FakeBot(channels={3: FakeChannel()}, raise_on_send=True)
    notifier = ChannelNotifier(bot=bot, channel_id=3)

    with caplog.at_level(logging.WARNING):
        await notifier.post("hello")
    assert any("Forbidden" in r.message for r in caplog.records)


# ─────────────────────────────────────────────────────────────────────────────
# NullNotifier — for tests and when bot is offline
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_null_notifier_is_safe_noop() -> None:
    n = NullNotifier()
    await n.post("anything")  # no exception, nothing observable
