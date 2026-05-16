"""
Discord-test fixtures.

We test command handlers directly with a fake Interaction rather than spinning
up dpytest, so most fixtures here build small in-memory stand-ins for the
Discord SDK + the application's BotContext.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import pytest

from clawbot.config import ClawbotConfig
from clawbot.db import Repo, connect, run_migrations
from clawbot.discord.bot import BotContext
from clawbot.discord_secrets import DiscordSecrets

_MIGRATIONS_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "src" / "clawbot" / "db" / "migrations"
)


# ─────────────────────────────────────────────────────────────────────────────
# Fake discord.py types
#
# discord.Interaction is huge and instantiating one means dragging in the whole
# gateway. For unit tests we only need: user.id, response.send_message(),
# followup.send(). The fakes below mimic the duck-typed surface we use.
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class FakeUser:
    id: int
    name: str = "operator"


@dataclass
class FakeResponse:
    sent: list[dict[str, Any]] = field(default_factory=list)

    async def send_message(
        self,
        content: Optional[str] = None,
        *,
        ephemeral: bool = False,
        embed: Any = None,
    ) -> None:
        self.sent.append(
            {"content": content, "ephemeral": ephemeral, "embed": embed}
        )


@dataclass
class FakeInteraction:
    user: FakeUser
    response: FakeResponse = field(default_factory=FakeResponse)
    guild_id: Optional[int] = None


@pytest.fixture
def fake_secrets() -> DiscordSecrets:
    return DiscordSecrets(
        token="t",
        user_id=999_000_111,
        guild_id=222_333_444,
        channel_id=555_666_777,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    """A real Repo on a tmp SQLite DB with all migrations applied."""
    db_path = tmp_path / "clawbot.db"
    conn = connect(db_path)
    run_migrations(conn, _MIGRATIONS_DIR)
    return Repo(conn=conn)


@pytest.fixture
def cfg() -> ClawbotConfig:
    """Defaults for everything; discord.enabled is irrelevant in handler tests."""
    return ClawbotConfig()


@pytest.fixture
def ctx(repo: Repo, cfg: ClawbotConfig, fake_secrets: DiscordSecrets) -> BotContext:
    return BotContext(repo=repo, config=cfg, secrets=fake_secrets)


@pytest.fixture
def operator_interaction(fake_secrets: DiscordSecrets) -> FakeInteraction:
    """An interaction from the whitelisted operator."""
    return FakeInteraction(user=FakeUser(id=fake_secrets.user_id))


@pytest.fixture
def stranger_interaction() -> FakeInteraction:
    """An interaction from someone who is *not* the operator."""
    return FakeInteraction(user=FakeUser(id=42))
