"""
/profile cog.

Two commands:
    /profile             — show the operator's profile, grouped.
    /profile set FIELD VALUE — validate via clawbot.profile then write.

The actual validation lives in ``clawbot.profile``; this layer is purely
about Discord-side rendering and error surfacing.
"""

from __future__ import annotations

from typing import Any

import discord
from discord import app_commands

from clawbot import profile as profile_mod
from clawbot.discord.bot import BotContext, InteractionLike

# ─────────────────────────────────────────────────────────────────────────────
# Visual grouping — mirrors config/profile.bootstrap.example.yaml.
# Keep order stable: humans scan top-to-bottom and editing the group list
# silently rearranges everyone's /profile display.
# ─────────────────────────────────────────────────────────────────────────────


PROFILE_GROUPS: dict[str, list[str]] = {
    "Physical": [
        "name", "age_range", "gender_expression",
        "height_cm", "weight_kg_optional",
        "body_shape", "skin_tone", "skin_undertone",
        "hair_color", "hair_length", "hair_style_notes",
        "eye_color", "glasses",
        "piercings_json", "tattoos_json",
    ],
    "Sizing": [
        "top_size", "bottom_size", "dress_size", "shoe_size_us",
        "inseam_cm", "rise_pref", "bra_size", "fit_pref_json",
    ],
    "Style": [
        "favorite_colors_json", "disliked_colors_json",
        "favorite_brands_json", "disliked_brands_json",
        "jewelry_metal", "comfort_vs_style",
    ],
    "Sensitivities": [
        "fabric_avoid_json", "dye_allergies_json",
    ],
    "Lifestyle": [
        "city", "climate_notes", "workplace_dress_code",
        "commute_mode", "activity_schedule_json",
        "travel_frequency", "religious_cultural_notes",
    ],
    "Budget": [
        "monthly_clothing_budget_usd", "cost_per_wear_target",
    ],
}


# ─────────────────────────────────────────────────────────────────────────────
# Rendering
# ─────────────────────────────────────────────────────────────────────────────


_UNSET = "_(unset)_"


def _format_value(value: Any) -> str:
    """Render a single profile value compactly.

    Lists collapse to ``a, b, c``; dicts to ``key=value`` pairs. None / empty
    become the italic ``(unset)`` marker so an empty profile still looks tidy.
    """
    if value is None:
        return _UNSET
    if isinstance(value, list):
        if not value:
            return _UNSET
        return ", ".join(str(v) for v in value)
    if isinstance(value, dict):
        if not value:
            return _UNSET
        return ", ".join(f"{k}={v}" for k, v in value.items())
    text = str(value).strip()
    return text if text else _UNSET


def render_profile(profile: dict[str, Any]) -> str:
    """Render a profile dict as a grouped Discord-flavored message.

    The output is one **bolded group header** per section, followed by
    ``field: value`` lines. Fields missing from the profile dict (i.e.,
    truly absent in the DB, not just None) are shown as ``(unset)`` so the
    operator can see at a glance what they still need to fill in.
    """
    lines: list[str] = []
    for group_name, field_names in PROFILE_GROUPS.items():
        lines.append(f"**{group_name}**")
        for fname in field_names:
            val = profile.get(fname)
            lines.append(f"  `{fname}`: {_format_value(val)}")
        lines.append("")  # blank line between groups
    return "\n".join(lines).rstrip()


# ─────────────────────────────────────────────────────────────────────────────
# Handlers
# ─────────────────────────────────────────────────────────────────────────────


async def handle_profile_show(
    ctx: BotContext, interaction: InteractionLike
) -> None:
    """Send the operator's current profile, grouped, ephemerally."""
    body = render_profile(profile_mod.get_profile(ctx.repo))
    await interaction.response.send_message(body, ephemeral=True)


async def handle_profile_set(
    ctx: BotContext,
    interaction: InteractionLike,
    *,
    field: str,
    value: Any,
) -> None:
    """Validate via ``profile.set_field`` and reply with the outcome.

    On success: ``Set <field> to <value>``.
    On ProfileError: surface the validator's human message verbatim — it
    already mentions field name and allowed alternatives.
    """
    try:
        stored = profile_mod.set_field(ctx.repo, field, value)
    except profile_mod.ProfileError as e:
        await interaction.response.send_message(
            f"❌ {e}", ephemeral=True
        )
        return

    await interaction.response.send_message(
        f"✓ Set `{field}` to `{stored}`.", ephemeral=True
    )


# ─────────────────────────────────────────────────────────────────────────────
# Cog wiring
# ─────────────────────────────────────────────────────────────────────────────


async def setup(bot: Any) -> None:
    """discord.py extension entrypoint. Registers /profile and /profile set."""
    ctx: BotContext = bot.clawbot_ctx

    profile_group = app_commands.Group(
        name="profile", description="View or update your operator profile."
    )

    @profile_group.command(name="show", description="Show your profile.")
    async def _show(interaction: discord.Interaction) -> None:  # type: ignore[misc]
        await handle_profile_show(ctx, interaction)

    @profile_group.command(name="set", description="Set a profile field.")
    @app_commands.describe(field="Field name", value="New value")
    async def _set(
        interaction: discord.Interaction,
        field: str,
        value: str,
    ) -> None:  # type: ignore[misc]
        await handle_profile_set(ctx, interaction, field=field, value=value)

    bot.tree.add_command(profile_group)
