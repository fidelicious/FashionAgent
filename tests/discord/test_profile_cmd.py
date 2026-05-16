"""
Tests for /profile and /profile set.

Both call into ``clawbot.profile``, so this layer is mostly about Discord-side
formatting and error-message surfacing.
"""

from __future__ import annotations

import pytest

from clawbot import profile as profile_mod
from clawbot.discord.bot import BotContext
from clawbot.discord.cogs.profile import (
    PROFILE_GROUPS,
    handle_profile_set,
    handle_profile_show,
    render_profile,
)

from .conftest import FakeInteraction


# ─────────────────────────────────────────────────────────────────────────────
# render_profile: pure
# ─────────────────────────────────────────────────────────────────────────────


def test_groups_cover_all_profile_fields() -> None:
    """Every PROFILE_FIELD must live in exactly one group, else /profile hides it."""
    from clawbot.db.repo import PROFILE_FIELDS

    grouped: set[str] = set()
    for fields in PROFILE_GROUPS.values():
        for f in fields:
            assert f not in grouped, f"field {f} listed in multiple groups"
            grouped.add(f)
    missing = PROFILE_FIELDS - grouped
    assert not missing, f"PROFILE_GROUPS missing: {sorted(missing)}"


def test_render_profile_shows_set_fields(ctx: BotContext) -> None:
    profile_mod.set_field(ctx.repo, "skin_undertone", "warm")
    profile_mod.set_field(ctx.repo, "comfort_vs_style", 7)

    body = render_profile(profile_mod.get_profile(ctx.repo))

    assert "skin_undertone" in body
    assert "warm" in body
    assert "comfort_vs_style" in body
    assert "7" in body


def test_render_profile_omits_unset_fields_per_group(ctx: BotContext) -> None:
    """Unset fields render as a faded placeholder, not an empty line."""
    profile_mod.set_field(ctx.repo, "skin_undertone", "warm")
    body = render_profile(profile_mod.get_profile(ctx.repo))
    # We rendered something for skin_undertone but should not have a literal
    # 'None' string anywhere.
    assert "None" not in body


# ─────────────────────────────────────────────────────────────────────────────
# /profile (show)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_profile_show_is_ephemeral(
    ctx: BotContext, operator_interaction: FakeInteraction
) -> None:
    await handle_profile_show(ctx, operator_interaction)
    msg = operator_interaction.response.sent[0]
    assert msg["ephemeral"] is True


@pytest.mark.asyncio
async def test_handle_profile_show_renders_groups(
    ctx: BotContext, operator_interaction: FakeInteraction
) -> None:
    profile_mod.set_field(ctx.repo, "skin_undertone", "warm")
    await handle_profile_show(ctx, operator_interaction)

    body = operator_interaction.response.sent[0]["content"]
    for group_label in PROFILE_GROUPS:
        assert group_label in body


# ─────────────────────────────────────────────────────────────────────────────
# /profile set
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_profile_set_happy_path(
    ctx: BotContext, operator_interaction: FakeInteraction
) -> None:
    await handle_profile_set(
        ctx, operator_interaction, field="skin_undertone", value="warm"
    )

    assert profile_mod.get_profile(ctx.repo)["skin_undertone"] == "warm"
    body = operator_interaction.response.sent[0]["content"]
    assert "skin_undertone" in body
    assert "warm" in body
    assert operator_interaction.response.sent[0]["ephemeral"] is True


@pytest.mark.asyncio
async def test_handle_profile_set_unknown_field_reports_error(
    ctx: BotContext, operator_interaction: FakeInteraction
) -> None:
    await handle_profile_set(
        ctx, operator_interaction, field="not_real", value="x"
    )

    body = operator_interaction.response.sent[0]["content"]
    assert "not_real" in body
    # Error reply must be ephemeral so it doesn't leak the field list publicly.
    assert operator_interaction.response.sent[0]["ephemeral"] is True


@pytest.mark.asyncio
async def test_handle_profile_set_bad_value_reports_error(
    ctx: BotContext, operator_interaction: FakeInteraction
) -> None:
    await handle_profile_set(
        ctx, operator_interaction, field="skin_undertone", value="purple"
    )

    body = operator_interaction.response.sent[0]["content"]
    # The validation message from profile.py mentions the allowed alternatives.
    assert "warm" in body
    # And the DB is unchanged.
    assert profile_mod.get_profile(ctx.repo).get("skin_undertone") is None
