"""
Bot construction and the global whitelist check.

The bot is intentionally thin: ``build_bot()`` wires a ``commands.Bot``
with the right intents, attaches the operator-only check, and returns
both the bot and a ``BotContext`` that cogs will read from.

Why ``BotContext`` is a plain dataclass and not stuffed onto ``bot``:
    Cogs need easy access to the repo + config + secrets in tests where
    no ``commands.Bot`` exists at all. The dataclass is the seam.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

from clawbot.config import ClawbotConfig
from clawbot.db.repo import Repo
from clawbot.discord_secrets import DiscordSecrets

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Duck-typed protocols
#
# The tests use a FakeInteraction with the same surface. Defining a Protocol
# here keeps the real discord.Interaction and the test fake interchangeable
# under mypy without importing discord.py in the type stubs.
# ─────────────────────────────────────────────────────────────────────────────


class _HasSendMessage(Protocol):
    async def send_message(
        self,
        content: str | None = ...,
        *,
        ephemeral: bool = ...,
        embed: Any = ...,
    ) -> None: ...

    async def defer(
        self, *, ephemeral: bool = ..., thinking: bool = ...
    ) -> None: ...


class _HasFollowupSend(Protocol):
    async def send(
        self,
        content: str | None = ...,
        *,
        ephemeral: bool = ...,
        embed: Any = ...,
    ) -> None: ...


class _HasUser(Protocol):
    id: int


class InteractionLike(Protocol):
    """Minimal Interaction surface used by our handlers.

    ``followup`` is required because slow commands (e.g. /add_item) must
    defer first and then reply via ``followup.send`` — after ``defer()``,
    ``response.send_message()`` raises ``InteractionResponded``.
    """

    user: _HasUser
    response: _HasSendMessage
    followup: _HasFollowupSend


# ─────────────────────────────────────────────────────────────────────────────
# BotContext — the dependency bundle every handler receives
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class BotContext:
    """Application-side dependencies. Built once at bot startup, passed to cogs.

    ``repo`` carries DB access; ``config`` the YAML settings; ``secrets`` the
    .env-loaded token + IDs. Handlers should never reach for the global
    ``os.environ`` or open new DB connections — everything they need is here.
    """

    repo: Repo
    config: ClawbotConfig
    secrets: DiscordSecrets


# ─────────────────────────────────────────────────────────────────────────────
# Whitelist primitives
# ─────────────────────────────────────────────────────────────────────────────


def is_whitelisted(ctx: BotContext, user_id: int) -> bool:
    """Return True iff ``user_id`` matches the configured operator.

    Pure predicate so it's easy to test and to reuse in cog-level checks.
    """
    return user_id == ctx.secrets.user_id


async def reject_unauthorized(
    ctx: BotContext,
    interaction: InteractionLike,
    *,
    command_name: str,
) -> None:
    """Standard denial path: audit-log + ephemeral reply.

    ``command_name`` is recorded in the audit log only — the reply must
    NOT echo it back, which would let a stranger probe the command surface
    one slash at a time.
    """
    ctx.repo.audit.write(
        kind="discord_unauthorized",
        actor=str(interaction.user.id),
        message=f"attempted /{command_name}",
    )
    logger.warning(
        "discord_unauthorized user_id=%s command=%s",
        interaction.user.id,
        command_name,
    )
    await interaction.response.send_message(
        ctx.config.discord.unauthorized_reply,
        ephemeral=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# build_bot — lazy import of discord.py
#
# discord.py is an optional dependency. We import it inside the function so
# tests that never call build_bot() don't need it installed.
# ─────────────────────────────────────────────────────────────────────────────


def build_bot(ctx: BotContext) -> Any:
    """Construct a ``discord.ext.commands.Bot`` ready to be ``.run()``.

    The bot has a single global check installed (via a CommandTree subclass)
    that rejects anyone other than the operator. Cogs are loaded by callers
    (see ``main.py``) so this function stays test-friendly.
    """
    import discord
    from discord import app_commands
    from discord.ext import commands

    class _WhitelistedTree(app_commands.CommandTree):
        """CommandTree that gates every slash command on the operator id."""

        async def interaction_check(self, interaction: Any) -> bool:
            if is_whitelisted(ctx, interaction.user.id):
                return True
            name = getattr(
                getattr(interaction, "command", None), "name", "?"
            )
            await reject_unauthorized(ctx, interaction, command_name=name)
            return False

    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True

    bot = commands.Bot(
        command_prefix="!",  # slash-only in V1; prefix is moot
        intents=intents,
        tree_cls=_WhitelistedTree,
    )

    # Stash the context so cogs can reach it via ``bot.clawbot_ctx``.
    bot.clawbot_ctx = ctx  # type: ignore[attr-defined]
    return bot
