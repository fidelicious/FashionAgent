"""
Tests for the Discord bot foundation: BotContext + global whitelist check.

The whitelist is the single most security-critical line in the V1 bot.
These tests pin its behavior so regressions can't sneak in:
    - Operator → allowed.
    - Stranger → denied + audit log row + ephemeral reply.
"""

from __future__ import annotations

import pytest

from clawbot.db.repo import Repo
from clawbot.discord.bot import BotContext, is_whitelisted, reject_unauthorized

from .conftest import FakeInteraction


# ─────────────────────────────────────────────────────────────────────────────
# is_whitelisted: the pure predicate at the heart of the global check
# ─────────────────────────────────────────────────────────────────────────────


def test_operator_is_whitelisted(
    ctx: BotContext, operator_interaction: FakeInteraction
) -> None:
    assert is_whitelisted(ctx, operator_interaction.user.id) is True


def test_stranger_is_not_whitelisted(
    ctx: BotContext, stranger_interaction: FakeInteraction
) -> None:
    assert is_whitelisted(ctx, stranger_interaction.user.id) is False


# ─────────────────────────────────────────────────────────────────────────────
# reject_unauthorized: shared denial path
#   1. Writes one row to audit_log with kind='discord_unauthorized'.
#   2. Sends an ephemeral reply using config.discord.unauthorized_reply.
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reject_writes_audit_log(
    ctx: BotContext,
    stranger_interaction: FakeInteraction,
    repo: Repo,
) -> None:
    await reject_unauthorized(ctx, stranger_interaction, command_name="health")

    rows = repo.audit.recent(limit=10)
    relevant = [r for r in rows if r["kind"] == "discord_unauthorized"]
    assert len(relevant) == 1
    assert "health" in relevant[0]["message"]
    assert str(stranger_interaction.user.id) in (relevant[0]["actor"] or "")


@pytest.mark.asyncio
async def test_reject_sends_ephemeral_reply(
    ctx: BotContext, stranger_interaction: FakeInteraction
) -> None:
    await reject_unauthorized(ctx, stranger_interaction, command_name="health")

    assert len(stranger_interaction.response.sent) == 1
    msg = stranger_interaction.response.sent[0]
    assert msg["ephemeral"] is True
    assert msg["content"] == ctx.config.discord.unauthorized_reply


@pytest.mark.asyncio
async def test_reject_does_not_leak_command_internals(
    ctx: BotContext, stranger_interaction: FakeInteraction
) -> None:
    """The denial reply must not echo back the command name (info leak)."""
    await reject_unauthorized(
        ctx, stranger_interaction, command_name="add_item"
    )
    msg = stranger_interaction.response.sent[0]
    assert "add_item" not in (msg["content"] or "")


# ─────────────────────────────────────────────────────────────────────────────
# build_bot smoke — constructs the real discord.py Bot. Skipped if the lib
# isn't installed.
# ─────────────────────────────────────────────────────────────────────────────


def test_build_bot_constructs_with_whitelisted_tree(ctx: BotContext) -> None:
    discord = pytest.importorskip("discord")
    from clawbot.discord.bot import build_bot

    bot = build_bot(ctx)
    assert bot.clawbot_ctx is ctx
    # The tree must be our subclass, not the vanilla CommandTree.
    assert isinstance(bot.tree, discord.app_commands.CommandTree)
    assert type(bot.tree).__name__ == "_WhitelistedTree"


@pytest.mark.asyncio
async def test_all_cogs_load_into_built_bot(ctx: BotContext) -> None:
    """Each cog's setup() runs cleanly and registers at least one command."""
    pytest.importorskip("discord")
    from clawbot.discord.bot import build_bot
    from clawbot.main import _COG_MODULES

    bot = build_bot(ctx)
    for module in _COG_MODULES:
        await bot.load_extension(module)

    # All four cogs registered — at minimum we expect /health, /profile group,
    # /wardrobe, /add_item, /edit_item, /forget_item.
    names = {c.name for c in bot.tree.get_commands()}
    assert {"health", "profile", "wardrobe",
            "add_item", "edit_item", "forget_item"}.issubset(names)
