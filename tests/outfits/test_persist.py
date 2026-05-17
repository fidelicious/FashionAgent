"""
Tests for OutfitsRepo — round-trip persistence of scored outfits.

Uses the same `repo` fixture pattern as tests/test_db.py (real SQLite file
under tmp_path, migrations applied). The repo is small but covers the
foreign-key cascade between outfits and outfit_items.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from clawbot.db import Repo, connect, run_migrations
from clawbot.db.repo import WardrobeItem as DbWardrobeItem

MIGRATIONS_DIR = (
    Path(__file__).resolve().parent.parent.parent / "src" / "clawbot" / "db" / "migrations"
)
from clawbot.outfits.candidates import generate_candidates
from clawbot.outfits.llm_schema import OutfitChoice
from clawbot.outfits.persist import OutfitsRepo
from clawbot.outfits.score import score_outfit
from tests.outfits.conftest import make_item

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    conn = connect(tmp_path / "test.db")
    run_migrations(conn, MIGRATIONS_DIR)
    return Repo(conn)


@pytest.fixture
def outfits_repo(repo: Repo) -> OutfitsRepo:
    return OutfitsRepo(repo.conn)


@pytest.fixture
def seeded_wardrobe(repo: Repo) -> dict[str, str]:
    """Insert 3 items so outfit_items can FK to real rows. Returns role→id."""
    top_id = repo.items.add(DbWardrobeItem(category="tops", subcategory="t-shirt"))
    bot_id = repo.items.add(DbWardrobeItem(category="bottoms", subcategory="jeans"))
    shoe_id = repo.items.add(DbWardrobeItem(category="footwear", subcategory="sneakers"))
    return {"top": top_id, "bottom": bot_id, "footwear": shoe_id}


@pytest.fixture
def sample_scored(default_context, seeded_wardrobe):
    """One scored Outfit whose item ids match the seeded wardrobe."""
    wardrobe = [
        make_item(item_id=seeded_wardrobe["top"], category="tops", seasons=("fall",)),
        make_item(item_id=seeded_wardrobe["bottom"], category="bottoms", seasons=("fall",)),
        make_item(item_id=seeded_wardrobe["footwear"], category="footwear", seasons=("fall",)),
    ]
    cands = generate_candidates(wardrobe, default_context)
    assert len(cands) == 1
    return score_outfit(cands[0], default_context)


# ─────────────────────────────────────────────────────────────────────────────
# Behaviour
# ─────────────────────────────────────────────────────────────────────────────


class TestOutfitsRepo:
    def test_save_writes_outfit_and_items(self, outfits_repo, sample_scored, tmp_path):
        choice = OutfitChoice(
            pick=0,
            reason="balanced fall look",
            model="gemma3:1b",
            attempts_used=1,
            fallback_used=False,
        )
        collage = tmp_path / "collage.png"
        collage.touch()

        outfit_id = outfits_repo.save(
            scored=sample_scored,
            choice=choice,
            collage_path=collage,
            occasion="casual",
        )
        assert isinstance(outfit_id, str) and len(outfit_id) >= 8

        record = outfits_repo.get(outfit_id)
        assert record is not None
        assert record.outfit_id == outfit_id
        assert record.score == pytest.approx(sample_scored.total)
        assert record.llm_explanation == "balanced fall look"
        assert record.collage_path == str(collage)
        assert record.occasion == "casual"
        # The outfit_items row count matches the items in the scored outfit.
        assert len(record.item_ids_by_role) == len(sample_scored.outfit.items_by_role)

    def test_recent_returns_newest_first(self, outfits_repo, sample_scored, tmp_path):
        choice = OutfitChoice(pick=0, reason="r", model="m", attempts_used=1, fallback_used=False)
        collage = tmp_path / "c.png"
        collage.touch()
        ids = []
        for _ in range(3):
            ids.append(
                outfits_repo.save(
                    scored=sample_scored,
                    choice=choice,
                    collage_path=collage,
                    occasion="casual",
                )
            )
        listed = outfits_repo.recent(limit=2)
        assert len(listed) == 2
        assert [r.outfit_id for r in listed] == ids[-1:-3:-1]

    def test_recently_worn_ids_returns_items_from_past_outfits(
        self, outfits_repo, sample_scored, tmp_path
    ):
        choice = OutfitChoice(pick=0, reason="r", model="m", attempts_used=1, fallback_used=False)
        collage = tmp_path / "c.png"
        collage.touch()
        outfits_repo.save(
            scored=sample_scored, choice=choice, collage_path=collage, occasion="casual"
        )
        worn = outfits_repo.recently_worn_ids(limit=10)
        # All 3 items of the saved outfit show up.
        expected_ids = {it.id for it in sample_scored.outfit.items}
        assert worn == expected_ids

    def test_save_is_transactional(self, outfits_repo, sample_scored, tmp_path):
        # Pass an item id that doesn't exist in wardrobe_items — the FK on
        # outfit_items must reject it, and we must end up with no orphan
        # row in the outfits table.
        from clawbot.outfits.types import Outfit, ScoredOutfit

        bogus_item = make_item(item_id="does-not-exist-in-db", category="tops")
        bogus_outfit = Outfit(items_by_role={"top": bogus_item})
        bogus_scored = ScoredOutfit(outfit=bogus_outfit, total=42.0, breakdown={})

        choice = OutfitChoice(pick=0, reason="r", model="m", attempts_used=1, fallback_used=False)
        collage = tmp_path / "c.png"
        collage.touch()
        with pytest.raises(Exception):
            outfits_repo.save(
                scored=bogus_scored, choice=choice, collage_path=collage, occasion="casual"
            )

        # No orphan outfit row.
        count = outfits_repo._conn.execute("SELECT COUNT(*) AS n FROM outfits").fetchone()["n"]
        assert count == 0
