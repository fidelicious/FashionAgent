"""
Tests for the Discord config + secrets pair.

Why split:
    - YAML holds non-sensitive operational knobs (DiscordConfig).
    - The actual token + identifier IDs come from secrets/.env (DiscordSecrets),
      which the operator chmods 600 and never commits.

Both must be available to the bot, but the loader treats them differently so
the YAML can be checked into git without dragging secrets along.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from clawbot.config import ClawbotConfig, ConfigError, load_config
from clawbot.discord_secrets import (
    DiscordSecrets,
    DiscordSecretsError,
    load_discord_secrets,
)


# ─────────────────────────────────────────────────────────────────────────────
# DiscordConfig (YAML side)
# ─────────────────────────────────────────────────────────────────────────────


def test_discord_config_defaults(tmp_path: Path) -> None:
    """Empty YAML yields safe defaults: bot disabled, commands sync on startup."""
    cfg_file = tmp_path / "empty.yaml"
    cfg_file.write_text("")
    cfg = load_config(cfg_file)

    assert isinstance(cfg, ClawbotConfig)
    assert cfg.discord.enabled is False
    assert cfg.discord.sync_commands_on_startup is True
    assert cfg.discord.unauthorized_reply.startswith("Sorry")


def test_discord_config_explicit(tmp_path: Path) -> None:
    cfg_file = tmp_path / "discord.yaml"
    cfg_file.write_text(
        "discord:\n"
        "  enabled: true\n"
        "  sync_commands_on_startup: false\n"
        "  unauthorized_reply: 'Not for you.'\n"
    )
    cfg = load_config(cfg_file)
    assert cfg.discord.enabled is True
    assert cfg.discord.sync_commands_on_startup is False
    assert cfg.discord.unauthorized_reply == "Not for you."


def test_discord_config_env_override(tmp_path: Path) -> None:
    """Env override path works on the new section."""
    cfg_file = tmp_path / "x.yaml"
    cfg_file.write_text("discord:\n  enabled: false\n")
    cfg = load_config(cfg_file, env={"CLAWBOT_DISCORD__ENABLED": "true"})
    assert cfg.discord.enabled is True


# ─────────────────────────────────────────────────────────────────────────────
# DiscordSecrets (env side)
# ─────────────────────────────────────────────────────────────────────────────


def _good_env() -> dict[str, str]:
    return {
        "DISCORD_TOKEN": "test.token.xxxx",
        "DISCORD_USER_ID": "111111111111111111",
        "DISCORD_GUILD_ID": "222222222222222222",
        "DISCORD_CHANNEL_ID": "333333333333333333",
    }


def test_discord_secrets_happy_path() -> None:
    s = load_discord_secrets(env=_good_env())
    assert isinstance(s, DiscordSecrets)
    assert s.token == "test.token.xxxx"
    assert s.user_id == 111111111111111111
    assert s.guild_id == 222222222222222222
    assert s.channel_id == 333333333333333333


def test_discord_secrets_missing_token_raises() -> None:
    env = _good_env()
    del env["DISCORD_TOKEN"]
    with pytest.raises(DiscordSecretsError, match="DISCORD_TOKEN"):
        load_discord_secrets(env=env)


def test_discord_secrets_placeholder_token_rejected() -> None:
    env = _good_env()
    env["DISCORD_TOKEN"] = "replace-me"
    with pytest.raises(DiscordSecretsError, match="replace-me"):
        load_discord_secrets(env=env)


def test_discord_secrets_non_numeric_user_id_rejected() -> None:
    env = _good_env()
    env["DISCORD_USER_ID"] = "not-a-snowflake"
    with pytest.raises(DiscordSecretsError, match="DISCORD_USER_ID"):
        load_discord_secrets(env=env)


def test_discord_secrets_channel_id_optional() -> None:
    """DISCORD_CHANNEL_ID is only needed for the V1 daily push; absent → None."""
    env = _good_env()
    del env["DISCORD_CHANNEL_ID"]
    s = load_discord_secrets(env=env)
    assert s.channel_id is None


def test_discord_secrets_repr_does_not_leak_token() -> None:
    """A casual log/repr of the secrets object must not contain the raw token."""
    s = load_discord_secrets(env=_good_env())
    assert "test.token.xxxx" not in repr(s)
