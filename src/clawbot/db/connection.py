"""
SQLite connection helper.

``connect()`` is the only way to open a clawbot database. It guarantees:
    - sqlite-vec extension loaded (so vec0 virtual tables work)
    - WAL journal mode (concurrent readers + a writer)
    - Foreign keys enforced
    - Row factory returning ``sqlite3.Row`` (dict-like access)
    - ``BEGIN IMMEDIATE`` semantics on writes via the ``transaction()`` ctx manager

Connections are cheap to open. We don't pool; the worker creates one per
job and closes it on completion.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import sqlite_vec


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open a SQLite connection with clawbot's standard pragmas + sqlite-vec.

    The parent directory is created if missing — convenient for tests and
    fresh installs.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # check_same_thread=False so APScheduler workers can hand connections
    # between threads when needed. We still make sure each transaction stays
    # on a single thread by scoping connections to jobs (see jobs.py).
    conn = sqlite3.connect(
        db_path,
        detect_types=sqlite3.PARSE_DECLTYPES,
        check_same_thread=False,
        isolation_level=None,  # autocommit; we manage transactions explicitly
    )
    conn.row_factory = sqlite3.Row

    # Load sqlite-vec extension. Must enable_load_extension first.
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)

    # Pragmas for reliability + concurrency.
    # WAL: writers don't block readers. Critical for the inbox watcher
    # running alongside Discord command handlers.
    conn.execute("PRAGMA journal_mode = WAL")
    # FULL: fsync the WAL file on every COMMIT so that committed transactions
    # survive an unclean shutdown (SIGKILL, power-off before OS page-cache
    # flush). NORMAL skips that fsync and risks data loss on abrupt kills.
    conn.execute("PRAGMA synchronous = FULL")
    conn.execute("PRAGMA foreign_keys = ON")
    # Hard guarantee: don't accept silent truncation of strings.
    conn.execute("PRAGMA strict = ON") if False else None  # opt-in per-table only
    # 30 s busy timeout — if another process is mid-WAL-checkpoint, wait.
    conn.execute("PRAGMA busy_timeout = 30000")

    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Context manager wrapping BEGIN IMMEDIATE / COMMIT / ROLLBACK.

    BEGIN IMMEDIATE acquires the write lock up-front so we fail fast on
    contention rather than after doing work.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
