"""
Database layer.

Public surface
--------------
- ``connect(db_path)``: open a SQLite connection with sqlite-vec loaded,
  WAL on, foreign keys on. Always use this rather than ``sqlite3.connect``.
- ``run_migrations(conn, migrations_dir)``: apply pending migrations in
  numeric order; idempotent.
- ``Repo``: thin facade over connection-bound repositories
  (``profile``, ``items``, ``outfits``, ``jobs``, ``audit``).

Design notes
------------
- All multi-valued columns (``favorite_colors_json``, ``fabric_json``,
  ``pairs_well_with_json`` …) are TEXT containing JSON. Filter with
  SQLite's ``json_extract(col, '$.path')``.
- Wardrobe items are soft-deleted via ``deleted_at``. The default item
  queries filter ``deleted_at IS NULL``; pass ``include_deleted=True``
  for admin/recovery flows.
- Vector embeddings live in a ``vec0`` virtual table joined to
  ``wardrobe_items`` via ``item_id``. Cosine similarity search is one
  ``SELECT … MATCH …`` away.
"""

from clawbot.db.connection import connect
from clawbot.db.migrate import run_migrations
from clawbot.db.repo import Repo

__all__ = ["connect", "run_migrations", "Repo"]
