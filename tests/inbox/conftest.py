"""Shared fixtures for the inbox tests."""

from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np
import pytest

from clawbot.config import ClawbotConfig
from clawbot.db import Repo, connect, run_migrations
from clawbot.discord.bot import BotContext
from clawbot.discord_secrets import DiscordSecrets
from clawbot.vision.draft import ClassificationResult, DraftItem

_MIGRATIONS_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "src" / "clawbot" / "db" / "migrations"
)


@pytest.fixture
def cfg(tmp_path: Path) -> ClawbotConfig:
    """Real config tweaked so all paths point at tmp_path."""
    cfg = ClawbotConfig()
    cfg.paths.inbox_dir = tmp_path / "inbox"
    cfg.paths.images_dir = tmp_path / "images"
    cfg.paths.db_path = tmp_path / "db" / "clawbot.db"
    cfg.paths.home = tmp_path
    return cfg


@pytest.fixture
def repo(cfg: ClawbotConfig) -> Repo:
    cfg.paths.db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(cfg.paths.db_path)
    run_migrations(conn, _MIGRATIONS_DIR)
    return Repo(conn=conn)


@pytest.fixture
def secrets() -> DiscordSecrets:
    return DiscordSecrets(
        token="t", user_id=1, guild_id=2, channel_id=3
    )


@pytest.fixture
def ctx(repo: Repo, cfg: ClawbotConfig, secrets: DiscordSecrets) -> BotContext:
    return BotContext(repo=repo, config=cfg, secrets=secrets)


@pytest.fixture
def stable_screenshot(cfg: ClawbotConfig):
    """Factory: drop a stable (past-mtime) screenshot into inbox/screenshots/."""

    def _make(name: str = "test.jpg", mtime_ago_s: float = 30.0) -> Path:
        target = cfg.paths.inbox_dir / "screenshots" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"\xff\xd8\xff" + b"\x00" * 1024)  # tiny fake JPG header
        past = time.time() - mtime_ago_s
        os.utime(target, (past, past))
        return target

    return _make


@pytest.fixture
def fake_draft_factory(tmp_path: Path):
    """Factory: build a DraftItem that honors a specified raw_path."""

    def _make(raw_path: Path) -> DraftItem:
        cut = tmp_path / f"cut-{raw_path.stem}.png"
        cut.write_bytes(b"x")
        return DraftItem(
            image_raw_path=raw_path,
            image_cutout_path=cut,
            color_primary="#1a2b3c",
            color_secondary=None,
            classification=ClassificationResult(
                category="tops",
                subcategory="cardigan",
                formality="casual",
                seasons=("fall",),
            ),
            ocr=None,
            embedding=np.zeros(512, dtype=np.float32),
            confidence={"color": 0.9, "category": 0.85},
        )

    return _make


class RecordingNotifier:
    """Captures every ``post()`` call so tests can assert on Discord output."""

    def __init__(self) -> None:
        self.posts: list[str] = []

    async def post(self, content: str) -> None:
        self.posts.append(content)


@pytest.fixture
def notifier() -> RecordingNotifier:
    return RecordingNotifier()
