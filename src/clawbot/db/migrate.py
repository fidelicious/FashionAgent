"""
Migration runner.

Files in ``migrations/`` named ``NNNN_name.sql`` are applied in numeric
order. Each one runs in a transaction; partial application is impossible.

Why hand-rolled instead of Alembic:
    - Schema is small and change frequency is low.
    - Alembic depends on SQLAlchemy, which we don't otherwise need.
    - Operators reading the migration files don't need to know an ORM.

Tracking table:
    schema_migrations(version INTEGER PK, applied_at TEXT)
"""

from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from pathlib import Path

from clawbot.db.connection import transaction

# Filenames must look like: 0001_init.sql, 0002_add_x.sql, ...
_MIGRATION_FILENAME = re.compile(r"^(\d{4,})_[\w-]+\.sql$")


class MigrationError(RuntimeError):
    """Raised when migrations are inconsistent with the database state."""


def run_migrations(conn: sqlite3.Connection, migrations_dir: str | Path) -> list[int]:
    """Apply pending migrations from ``migrations_dir``.

    Returns the list of versions that were applied in this call (empty if
    everything was already up to date). Idempotent.

    Raises ``MigrationError`` if a previously-applied version is missing
    from disk (operator likely deleted a migration file by mistake).
    """
    migrations_dir = Path(migrations_dir)
    _ensure_tracking_table(conn)

    on_disk = _discover_migrations(migrations_dir)
    applied = _applied_versions(conn)

    # Sanity check: any version recorded as applied but missing from disk?
    missing = applied - {v for v, _ in on_disk}
    if missing:
        raise MigrationError(
            f"Migrations recorded as applied but not found on disk: {sorted(missing)}. "
            f"Did a file get deleted from {migrations_dir}?"
        )

    pending = [(v, p) for v, p in on_disk if v not in applied]
    pending.sort(key=lambda vp: vp[0])

    applied_now: list[int] = []
    for version, path in pending:
        sql = path.read_text(encoding="utf-8")
        with transaction(conn):
            # executescript lets us run multi-statement SQL files
            conn.executescript(sql)
            conn.execute(
                "INSERT INTO schema_migrations(version, applied_at) "
                "VALUES (?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))",
                (version,),
            )
        applied_now.append(version)

    return applied_now


# ─────────────────────────────────────────────────────────────────────────────
# Internals
# ─────────────────────────────────────────────────────────────────────────────


def _ensure_tracking_table(conn: sqlite3.Connection) -> None:
    """Create schema_migrations if it doesn't exist. Always safe to call."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )


def _discover_migrations(migrations_dir: Path) -> list[tuple[int, Path]]:
    """Return (version, path) for every well-named migration file.

    Files that don't match the convention are ignored silently; this lets
    operators drop README.md or notes into the migrations folder without
    breaking the runner.
    """
    if not migrations_dir.exists():
        return []
    out: list[tuple[int, Path]] = []
    for entry in migrations_dir.iterdir():
        if not entry.is_file():
            continue
        m = _MIGRATION_FILENAME.match(entry.name)
        if not m:
            continue
        out.append((int(m.group(1)), entry))
    return out


def _applied_versions(conn: sqlite3.Connection) -> set[int]:
    """Return the set of versions already applied to this database."""
    with closing(conn.execute("SELECT version FROM schema_migrations")) as cur:
        return {row[0] for row in cur.fetchall()}
