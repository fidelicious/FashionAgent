"""
Discord secrets loader.

Lives outside ``clawbot.discord`` because it has zero dependency on
discord.py — it just parses four env vars. Keeping it separate lets the
config/test layers import it without pulling in the bot framework.

Public API:
    - ``DiscordSecrets``: frozen dataclass holding token + identifier IDs.
    - ``DiscordSecretsError``: raised on missing / malformed env vars.
    - ``load_discord_secrets(env=None)``: parse the process env (or a
      passed-in dict for tests).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


class DiscordSecretsError(Exception):
    """Raised when DISCORD_* env vars are missing or malformed.

    The message names the offending env var so the operator can fix
    ``secrets/.env`` without reading code.
    """


_PLACEHOLDER_VALUES = frozenset({"", "replace-me", "TODO", "changeme"})


@dataclass(frozen=True)
class DiscordSecrets:
    """Loaded Discord credentials and target IDs.

    ``__repr__`` is overridden so the raw token never appears in logs —
    structlog and exception tracebacks routinely call repr() on locals.
    """

    token: str = field(repr=False)
    user_id: int
    guild_id: int
    channel_id: Optional[int] = None

    def __repr__(self) -> str:
        tok = "<set>" if self.token else "<empty>"
        return (
            f"DiscordSecrets(token={tok}, user_id={self.user_id}, "
            f"guild_id={self.guild_id}, channel_id={self.channel_id})"
        )


def _require(env: dict[str, str], name: str) -> str:
    """Fetch ``name`` from env, rejecting absent or placeholder values."""
    raw = env.get(name, "").strip()
    if not raw:
        raise DiscordSecretsError(
            f"{name} is missing from the environment. "
            f"Set it in secrets/.env (see secrets/.env.example)."
        )
    if raw in _PLACEHOLDER_VALUES:
        raise DiscordSecretsError(
            f"{name} is still set to the placeholder value {raw!r}. "
            f"Replace it with the real value from Discord."
        )
    return raw


def _parse_id(name: str, raw: str) -> int:
    """Parse a Discord snowflake ID. Errors mention the env var by name."""
    try:
        return int(raw)
    except ValueError as e:
        raise DiscordSecretsError(
            f"{name} must be a numeric Discord ID, got {raw!r}"
        ) from e


def load_discord_secrets(
    *, env: Optional[dict[str, str]] = None
) -> DiscordSecrets:
    """Build a ``DiscordSecrets`` from environment variables.

    Required: ``DISCORD_TOKEN``, ``DISCORD_USER_ID``, ``DISCORD_GUILD_ID``.
    Optional: ``DISCORD_CHANNEL_ID`` (only used by the daily-push job).
    """
    src = dict(os.environ if env is None else env)

    token = _require(src, "DISCORD_TOKEN")
    user_id = _parse_id("DISCORD_USER_ID", _require(src, "DISCORD_USER_ID"))
    guild_id = _parse_id("DISCORD_GUILD_ID", _require(src, "DISCORD_GUILD_ID"))

    channel_id: Optional[int] = None
    channel_raw = src.get("DISCORD_CHANNEL_ID", "").strip()
    if channel_raw and channel_raw not in _PLACEHOLDER_VALUES:
        channel_id = _parse_id("DISCORD_CHANNEL_ID", channel_raw)

    return DiscordSecrets(
        token=token,
        user_id=user_id,
        guild_id=guild_id,
        channel_id=channel_id,
    )
