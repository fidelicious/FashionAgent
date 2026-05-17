"""
Tests for the daily-outfit orchestrator.

These exercise `run_daily_outfit` end-to-end against a real SQLite (so the
FK joins are real) but with a fake notifier and a fake LLM picker so no
network or Discord traffic happens.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from clawbot.db import Repo, connect, run_migrations
from clawbot.db.repo import WardrobeItem as DbWardrobeItem
from clawbot.outfits.daily import DailyResult, run_daily_outfit
from clawbot.outfits.llm_schema import OutfitChoice
from clawbot.outfits.types import ScoredOutfit

MIGRATIONS_DIR = (
    Path(__file__).resolve().parent.parent.parent / "src" / "clawbot" / "db" / "migrations"
)


# ─────────────────────────────────────────────────────────────────────────────
# Fakes
# ─────────────────────────────────────────────────────────────────────────────


class FakeNotifier:
    """Records every (content, image_path) pair so tests can assert on output."""

    def __init__(self) -> None:
        self.text_calls: list[str] = []
        self.image_calls: list[tuple[str, str]] = []

    async def post(self, content: str) -> None:
        self.text_calls.append(content)

    async def post_image(self, content: str, image_path: Path | str) -> None:
        self.image_calls.append((content, str(image_path)))


async def _fake_pick_first(
    candidates: list[ScoredOutfit], *args: Any, **kwargs: Any
) -> OutfitChoice:
    """Always picks candidate 0 with a canned reason. No HTTP traffic."""
    return OutfitChoice(
        pick=0,
        reason="canned reason for tests",
        model="fake-model",
        attempts_used=1,
        fallback_used=False,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    conn = connect(tmp_path / "test.db")
    run_migrations(conn, MIGRATIONS_DIR)
    return Repo(conn)


@pytest.fixture
def populated_wardrobe(repo: Repo) -> dict[str, str]:
    return {
        "top": repo.items.add(
            DbWardrobeItem(
                category="tops",
                subcategory="t-shirt",
                seasons=["fall"],
                formality="casual",
                color_primary="navy",
            )
        ),
        "bottom": repo.items.add(
            DbWardrobeItem(
                category="bottoms",
                subcategory="jeans",
                seasons=["fall"],
                formality="casual",
                color_primary="blue",
            )
        ),
        "footwear": repo.items.add(
            DbWardrobeItem(
                category="footwear",
                subcategory="sneakers",
                seasons=["fall"],
                formality="casual",
                color_primary="white",
            )
        ),
    }


@pytest.fixture
def collage_dir(tmp_path: Path) -> Path:
    d = tmp_path / "outfits"
    d.mkdir()
    return d


# ─────────────────────────────────────────────────────────────────────────────
# Behaviour
# ─────────────────────────────────────────────────────────────────────────────


class TestRunDailyOutfit:
    @pytest.mark.asyncio
    async def test_happy_path_writes_outfit_collage_and_posts(
        self, repo, populated_wardrobe, collage_dir
    ):
        notifier = FakeNotifier()
        result = await run_daily_outfit(
            repo=repo,
            notifier=notifier,
            collage_dir=collage_dir,
            occasion="casual",
            today=date(2026, 10, 15),  # → fall
            pick_fn=_fake_pick_first,
        )
        assert isinstance(result, DailyResult)
        assert result.outfit_id is not None
        assert result.collage_path is not None
        assert Path(result.collage_path).exists()
        # Persisted to DB.
        rec = repo.conn.execute(
            "SELECT * FROM outfits WHERE id = ?", (result.outfit_id,)
        ).fetchone()
        assert rec is not None
        # Posted to Discord with the collage attached.
        assert len(notifier.image_calls) == 1
        content, image = notifier.image_calls[0]
        assert result.collage_path in image
        assert "casual" in content.lower() or "fall" in content.lower()

    @pytest.mark.asyncio
    async def test_empty_wardrobe_posts_warning_and_returns_none_outfit(self, repo, collage_dir):
        notifier = FakeNotifier()
        result = await run_daily_outfit(
            repo=repo,
            notifier=notifier,
            collage_dir=collage_dir,
            occasion="casual",
            today=date(2026, 10, 15),
            pick_fn=_fake_pick_first,
        )
        assert result.outfit_id is None
        assert result.collage_path is None
        # Warned the operator rather than silently failing.
        assert len(notifier.text_calls) == 1
        assert "wardrobe" in notifier.text_calls[0].lower()
        assert notifier.image_calls == []

    @pytest.mark.asyncio
    async def test_recently_worn_items_are_penalised(self, repo, populated_wardrobe, collage_dir):
        # Run once → fills outfits + outfit_items → marks the three items
        # as recently worn for run #2.
        notifier1 = FakeNotifier()
        first = await run_daily_outfit(
            repo=repo,
            notifier=notifier1,
            collage_dir=collage_dir,
            occasion="casual",
            today=date(2026, 10, 15),
            pick_fn=_fake_pick_first,
        )
        assert first.outfit_id is not None

        # Run #2 with the same wardrobe — duplicate_penalty triggers; the
        # orchestrator must still ship an outfit even when penalty bites,
        # because the test wardrobe is the only option available.
        notifier2 = FakeNotifier()
        second = await run_daily_outfit(
            repo=repo,
            notifier=notifier2,
            collage_dir=collage_dir,
            occasion="casual",
            today=date(2026, 10, 16),
            pick_fn=_fake_pick_first,
        )
        assert second.outfit_id is not None
        assert second.score < first.score  # penalty applied

    @pytest.mark.asyncio
    async def test_uses_derived_season_when_none_provided(
        self, repo, populated_wardrobe, collage_dir
    ):
        # No `season=` kwarg → derive from `today`. October → fall, which
        # matches our items' season list, so a candidate exists.
        notifier = FakeNotifier()
        result = await run_daily_outfit(
            repo=repo,
            notifier=notifier,
            collage_dir=collage_dir,
            occasion="casual",
            today=date(2026, 10, 15),
            pick_fn=_fake_pick_first,
        )
        assert result.outfit_id is not None
        assert result.season == "fall"
