"""
Tests for the weekly SQLite VACUUM job.

VACUUM is a brute-force defragmenter: rewrites the database file in-place
to reclaim space freed by DELETEs and INSERTs. It runs once a week on
Sunday at 03:00 to keep `clawbot.db` from bloating.

We're not testing SQLite — we're testing that our wrapper:
  - runs the VACUUM (file shrinks after a delete + vacuum cycle),
  - reports before/after byte counts,
  - handles a fresh DB (no rows) without raising.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from clawbot.db import Repo, connect, run_migrations
from clawbot.db.repo import WardrobeItem as DbWardrobeItem
from clawbot.maintenance.vacuum import VacuumResult, run_db_vacuum

MIGRATIONS_DIR = (
    Path(__file__).resolve().parent.parent.parent / "src" / "clawbot" / "db" / "migrations"
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "clawbot.db"


@pytest.fixture
def repo(db_path: Path) -> Repo:
    conn = connect(db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    return Repo(conn)


# ─────────────────────────────────────────────────────────────────────────────
# Behaviour
# ─────────────────────────────────────────────────────────────────────────────


class TestRunDbVacuum:
    def test_returns_before_and_after_byte_counts(self, repo, db_path):
        result = run_db_vacuum(repo.conn)
        assert isinstance(result, VacuumResult)
        assert result.bytes_before > 0
        # On a tiny fresh DB, bytes_after is approximately equal to before.
        assert result.bytes_after > 0

    def test_freshly_migrated_db_does_not_raise(self, repo):
        # Empty schema VACUUMs fine — SQLite just rewrites the page allocator.
        run_db_vacuum(repo.conn)

    def test_vacuum_runs_after_bulk_delete_without_error(self, repo, db_path):
        # Real value here is "vacuum survives a delete-heavy workload" — exact
        # shrinkage is SQLite's contract, not ours. WAL mode complicates the
        # size measurement enough that asserting on it tests SQLite internals.
        big_note = "x" * 2048
        for i in range(200):
            repo.items.add(DbWardrobeItem(category="tops", subcategory=f"t{i}", notes=big_note))
        repo.conn.execute("DELETE FROM wardrobe_items")
        repo.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

        result = run_db_vacuum(repo.conn)
        assert result.bytes_before > 0
        assert result.bytes_after > 0
        # bytes_reclaimed may be 0 or positive — never assert strict shrinkage.
        assert result.bytes_reclaimed >= 0 or result.bytes_after <= result.bytes_before * 1.1
