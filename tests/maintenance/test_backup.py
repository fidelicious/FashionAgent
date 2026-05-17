"""
Tests for the nightly backup module.

Every test runs against a tmp_path so the real ``backups/`` directory on the
NUC is never touched. The tarball spec is straightforward — what's worth
nailing down is:

  - include paths are tarred, exclude globs are honoured,
  - the tarball is gzipped and named with an ISO date stem,
  - retention drops files older than ``retain_days`` and keeps newer ones,
  - missing include paths don't crash the job (degrade-and-log).
"""

from __future__ import annotations

import tarfile
from datetime import date, timedelta
from pathlib import Path

import pytest

from clawbot.maintenance.backup import (
    BackupResult,
    create_backup,
    prune_old_backups,
)

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def populated_data(tmp_path: Path) -> Path:
    """A tiny ~/FashionAgent-shaped tree to back up."""
    root = tmp_path / "data"
    (root / "db").mkdir(parents=True)
    (root / "db" / "clawbot.db").write_bytes(b"PRETEND SQLITE")
    (root / "images" / "final").mkdir(parents=True)
    (root / "images" / "final" / "abc.png").write_bytes(b"PRETEND PNG")
    (root / "images" / "raw").mkdir(parents=True)
    (root / "images" / "raw" / "abc.jpg").write_bytes(b"PRETEND JPG")
    return root


@pytest.fixture
def backups_dir(tmp_path: Path) -> Path:
    d = tmp_path / "backups"
    d.mkdir()
    return d


# ─────────────────────────────────────────────────────────────────────────────
# create_backup
# ─────────────────────────────────────────────────────────────────────────────


class TestCreateBackup:
    def test_writes_dated_tarball(self, populated_data, backups_dir):
        result = create_backup(
            include=[populated_data / "db", populated_data / "images"],
            output_dir=backups_dir,
            today=date(2026, 5, 17),
        )
        assert isinstance(result, BackupResult)
        assert result.path.exists()
        assert result.path.name == "clawbot-2026-05-17.tar.gz"
        assert result.path.parent == backups_dir
        assert result.bytes > 0

    def test_includes_files_under_each_include_path(self, populated_data, backups_dir):
        result = create_backup(
            include=[populated_data / "db", populated_data / "images"],
            output_dir=backups_dir,
            today=date(2026, 5, 17),
        )
        with tarfile.open(result.path, "r:gz") as tar:
            members = {m.name for m in tar.getmembers()}
        # The tarball stores entries relative to each include's parent so the
        # restore is just `tar -xzf clawbot-DATE.tar.gz -C /restore/here/`.
        assert any("clawbot.db" in m for m in members)
        assert any("final/abc.png" in m for m in members)

    def test_exclude_globs_filter_out_matching_files(self, populated_data, backups_dir):
        result = create_backup(
            include=[populated_data / "db", populated_data / "images"],
            output_dir=backups_dir,
            today=date(2026, 5, 17),
            exclude_globs=["**/raw/**"],
        )
        with tarfile.open(result.path, "r:gz") as tar:
            names = [m.name for m in tar.getmembers()]
        assert not any("raw" in n for n in names)
        # Sanity: the final/ path still made it.
        assert any("final/abc.png" in n for n in names)

    def test_collision_appends_suffix(self, populated_data, backups_dir):
        first = create_backup(
            include=[populated_data / "db"],
            output_dir=backups_dir,
            today=date(2026, 5, 17),
        )
        second = create_backup(
            include=[populated_data / "db"],
            output_dir=backups_dir,
            today=date(2026, 5, 17),
        )
        assert first.path != second.path
        assert first.path.exists() and second.path.exists()

    def test_missing_include_path_is_logged_and_skipped(self, populated_data, backups_dir, caplog):
        bogus = populated_data / "does-not-exist"
        result = create_backup(
            include=[populated_data / "db", bogus],
            output_dir=backups_dir,
            today=date(2026, 5, 17),
        )
        assert result.path.exists()
        assert any(
            "missing" in r.message.lower() or "skip" in r.message.lower() for r in caplog.records
        )


# ─────────────────────────────────────────────────────────────────────────────
# prune_old_backups
# ─────────────────────────────────────────────────────────────────────────────


class TestPruneOldBackups:
    @staticmethod
    def _make_backup(dir_: Path, day: date) -> Path:
        path = dir_ / f"clawbot-{day.isoformat()}.tar.gz"
        path.write_bytes(b"x")
        return path

    def test_drops_files_older_than_retain_days(self, backups_dir):
        today = date(2026, 5, 17)
        old = self._make_backup(backups_dir, today - timedelta(days=30))
        recent = self._make_backup(backups_dir, today - timedelta(days=3))
        dropped = prune_old_backups(backups_dir, retain_days=14, today=today)
        assert old in dropped
        assert recent not in dropped
        assert not old.exists()
        assert recent.exists()

    def test_keeps_exactly_retain_days_old_file(self, backups_dir):
        today = date(2026, 5, 17)
        on_boundary = self._make_backup(backups_dir, today - timedelta(days=14))
        dropped = prune_old_backups(backups_dir, retain_days=14, today=today)
        assert on_boundary not in dropped
        assert on_boundary.exists()

    def test_ignores_files_that_dont_match_naming_scheme(self, backups_dir):
        # An operator's manual rsync of a different-named file should not be
        # touched — only files we created (clawbot-YYYY-MM-DD.tar.gz...) are
        # candidates for pruning.
        rogue = backups_dir / "operator-manual-snapshot.tar.gz"
        rogue.write_bytes(b"x")
        prune_old_backups(backups_dir, retain_days=14, today=date(2026, 5, 17))
        assert rogue.exists()

    def test_handles_empty_dir(self, backups_dir):
        dropped = prune_old_backups(backups_dir, retain_days=14, today=date(2026, 5, 17))
        assert dropped == []
