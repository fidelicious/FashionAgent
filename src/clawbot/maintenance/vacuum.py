"""
Weekly SQLite VACUUM job.

`VACUUM` rewrites the entire database file in-place to reclaim space freed
by deletes and updates. On a 1B-LLM-host NUC it's cheap (single-digit MB)
and keeps page allocation from drifting.

Notes:
  - VACUUM cannot run inside a transaction. The connection must be in
    autocommit mode (our `connect()` sets `isolation_level=None`, so we're
    safe by default).
  - VACUUM acquires an EXCLUSIVE lock — concurrent reads/writes will block.
    The 03:00 Sunday slot is chosen so the daily-outfit job (07:00) and
    the inbox sweep (60s) won't race against it.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VacuumResult:
    """Outcome of one run_db_vacuum() invocation."""

    bytes_before: int
    bytes_after: int

    @property
    def bytes_reclaimed(self) -> int:
        """Positive when VACUUM shrank the file; 0 or negative otherwise."""
        return self.bytes_before - self.bytes_after


def _db_file_size(conn: sqlite3.Connection) -> int:
    """Return the on-disk size of the database file backing this connection."""
    row = conn.execute("PRAGMA database_list").fetchone()
    # `database_list` rows are (seq, name, file). The 'main' DB is always seq=0.
    file_path = row[2] if not isinstance(row, sqlite3.Row) else row["file"]
    if not file_path:
        return 0
    return Path(file_path).stat().st_size


def run_db_vacuum(conn: sqlite3.Connection) -> VacuumResult:
    """
    Run `VACUUM` against the main database. Returns before/after byte counts
    so the operator can verify that disk usage is trending in the right
    direction over time.
    """
    before = _db_file_size(conn)
    conn.execute("VACUUM")
    after = _db_file_size(conn)
    logger.info("vacuum: %d -> %d bytes (reclaimed %d)", before, after, before - after)
    return VacuumResult(bytes_before=before, bytes_after=after)
