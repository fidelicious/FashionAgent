"""
Repository facade.

The ``Repo`` class wraps a single connection and exposes one attribute per
domain (``profile``, ``items``, ``outfits``, ``jobs``, ``audit``). Domain
modules implement their own queries against the shared connection.

Foundation pass implements ``profile`` and ``items`` (Step 4 needs them).
Other domains land in their respective build steps.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from clawbot.db.connection import transaction


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _utc_now_iso() -> str:
    """Return the current UTC time in our canonical ISO-8601 format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _json_or_none(value: Any) -> Optional[str]:
    """Serialize a Python value to JSON text. None/empty stays None."""
    if value is None:
        return None
    if isinstance(value, (list, tuple)) and len(value) == 0:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _from_json(text: Optional[str]) -> Any:
    """Inverse of ``_json_or_none``."""
    if text is None or text == "":
        return None
    return json.loads(text)


# ─────────────────────────────────────────────────────────────────────────────
# Wardrobe item dataclass
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class WardrobeItem:
    """In-memory shape of a wardrobe item.

    Mirrors the ``wardrobe_items`` table 1:1, with JSON columns deserialized
    to native Python lists/dicts. ``id`` is a uuid4 string; pass ``None`` on
    creation and the repo fills it in.
    """

    category: str
    id: Optional[str] = None
    subcategory: Optional[str] = None
    brand: Optional[str] = None
    name: Optional[str] = None
    color_primary: Optional[str] = None
    color_secondary: Optional[str] = None
    pattern: Optional[str] = None
    fabric: Optional[list[str]] = None
    fit: Optional[str] = None
    silhouette: Optional[str] = None
    formality: Optional[str] = None
    seasons: Optional[list[str]] = None
    size_on_tag: Optional[str] = None
    size_true: Optional[str] = None
    purchase_date: Optional[str] = None
    purchase_price_usd: Optional[float] = None
    purchased_from: Optional[str] = None
    condition: Optional[str] = None
    needs_tailoring: bool = False
    tailoring_notes: Optional[str] = None
    care: Optional[str] = None
    pairs_well_with: Optional[list[str]] = None
    avoid_pairing_with: Optional[list[str]] = None
    wear_count: int = 0
    last_worn_date: Optional[str] = None
    image_raw_path: Optional[str] = None
    image_cutout_path: Optional[str] = None
    image_final_path: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    deleted_at: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# Profile repository
# ─────────────────────────────────────────────────────────────────────────────


# These keys are the only ones the profile setter accepts. Anything else
# raises KeyError — protects against typos in /profile set <field> <value>.
PROFILE_FIELDS: frozenset[str] = frozenset({
    # Identity / physical
    "name", "age_range", "gender_expression",
    "height_cm", "weight_kg_optional",
    "body_shape", "skin_tone", "skin_undertone",
    "hair_color", "hair_length", "hair_style_notes",
    "eye_color", "glasses",
    "piercings_json", "tattoos_json",
    # Sizing
    "top_size", "bottom_size", "dress_size", "shoe_size_us",
    "inseam_cm", "rise_pref", "bra_size", "fit_pref_json",
    # Style
    "favorite_colors_json", "disliked_colors_json",
    "favorite_brands_json", "disliked_brands_json",
    "jewelry_metal", "comfort_vs_style",
    # Sensitivities
    "fabric_avoid_json", "dye_allergies_json",
    # Lifestyle
    "city", "climate_notes", "workplace_dress_code",
    "commute_mode", "activity_schedule_json",
    "travel_frequency", "religious_cultural_notes",
    # Budget
    "monthly_clothing_budget_usd", "cost_per_wear_target",
})

# JSON-typed fields. When the caller passes a list/dict, we serialize.
PROFILE_JSON_FIELDS: frozenset[str] = frozenset({
    f for f in PROFILE_FIELDS if f.endswith("_json")
})


class ProfileRepo:
    """CRUD for the singleton user profile."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get(self) -> dict[str, Any]:
        """Return the profile row with JSON columns deserialized."""
        row = self._conn.execute(
            "SELECT * FROM user_profile WHERE id = 1"
        ).fetchone()
        if row is None:  # pragma: no cover — migration always seeds row 1
            return {}
        out = dict(row)
        for f in PROFILE_JSON_FIELDS:
            if f in out:
                out[f] = _from_json(out[f])
        return out

    def set(self, field: str, value: Any) -> None:
        """Update a single field on the profile.

        Raises KeyError if ``field`` isn't a known profile column.
        JSON fields accept native Python lists/dicts.
        """
        if field not in PROFILE_FIELDS:
            raise KeyError(f"Unknown profile field: {field!r}")

        if field in PROFILE_JSON_FIELDS and not isinstance(value, (str, type(None))):
            value = _json_or_none(value)

        sql = f"UPDATE user_profile SET {field} = ?, updated_at = ? WHERE id = 1"
        with transaction(self._conn):
            self._conn.execute(sql, (value, _utc_now_iso()))

    def set_many(self, fields: dict[str, Any]) -> None:
        """Update many fields atomically. Same validation as ``set()``."""
        unknown = set(fields) - PROFILE_FIELDS
        if unknown:
            raise KeyError(f"Unknown profile fields: {sorted(unknown)}")

        cols = []
        values: list[Any] = []
        for k, v in fields.items():
            if k in PROFILE_JSON_FIELDS and not isinstance(v, (str, type(None))):
                v = _json_or_none(v)
            cols.append(f"{k} = ?")
            values.append(v)
        cols.append("updated_at = ?")
        values.append(_utc_now_iso())

        sql = f"UPDATE user_profile SET {', '.join(cols)} WHERE id = 1"
        with transaction(self._conn):
            self._conn.execute(sql, values)


# ─────────────────────────────────────────────────────────────────────────────
# Wardrobe items repository
# ─────────────────────────────────────────────────────────────────────────────


# Mapping from WardrobeItem dataclass field → DB column. Differs only where
# we drop the _json/_bool suffix in the dataclass for ergonomics.
_ITEM_COL_MAP: dict[str, str] = {
    "id": "id",
    "category": "category",
    "subcategory": "subcategory",
    "brand": "brand",
    "name": "name",
    "color_primary": "color_primary",
    "color_secondary": "color_secondary",
    "pattern": "pattern",
    "fabric": "fabric_json",
    "fit": "fit",
    "silhouette": "silhouette",
    "formality": "formality",
    "seasons": "seasons_json",
    "size_on_tag": "size_on_tag",
    "size_true": "size_true",
    "purchase_date": "purchase_date",
    "purchase_price_usd": "purchase_price_usd",
    "purchased_from": "purchased_from",
    "condition": "condition",
    "needs_tailoring": "needs_tailoring_bool",
    "tailoring_notes": "tailoring_notes",
    "care": "care",
    "pairs_well_with": "pairs_well_with_json",
    "avoid_pairing_with": "avoid_pairing_with_json",
    "wear_count": "wear_count",
    "last_worn_date": "last_worn_date",
    "image_raw_path": "image_raw_path",
    "image_cutout_path": "image_cutout_path",
    "image_final_path": "image_final_path",
    "notes": "notes",
    "created_at": "created_at",
    "updated_at": "updated_at",
    "deleted_at": "deleted_at",
}

# Reverse map for hydration.
_ITEM_COL_REVERSE: dict[str, str] = {v: k for k, v in _ITEM_COL_MAP.items()}

# Which DB columns hold JSON.
_ITEM_JSON_COLUMNS: frozenset[str] = frozenset({
    "fabric_json", "seasons_json",
    "pairs_well_with_json", "avoid_pairing_with_json",
})


def _item_to_row(item: WardrobeItem) -> dict[str, Any]:
    """Turn a WardrobeItem into a {column: value} dict ready for INSERT."""
    row: dict[str, Any] = {}
    data = asdict(item)
    for field_name, value in data.items():
        col = _ITEM_COL_MAP[field_name]
        if col in _ITEM_JSON_COLUMNS:
            value = _json_or_none(value)
        elif col == "needs_tailoring_bool":
            value = 1 if value else 0
        row[col] = value
    return row


def _row_to_item(row: sqlite3.Row | dict[str, Any]) -> WardrobeItem:
    """Inverse of ``_item_to_row``."""
    d = dict(row)
    kwargs: dict[str, Any] = {}
    for col, value in d.items():
        field_name = _ITEM_COL_REVERSE.get(col)
        if field_name is None:
            continue  # column we don't model (e.g., embeddings live elsewhere)
        if col in _ITEM_JSON_COLUMNS:
            value = _from_json(value)
        elif col == "needs_tailoring_bool":
            value = bool(value)
        kwargs[field_name] = value
    return WardrobeItem(**kwargs)


class ItemsRepo:
    """CRUD + soft-delete for wardrobe items.

    Vector embeddings are written to ``wardrobe_items_vec`` via ``set_embedding``;
    they're kept separate so callers can defer the embed step.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ── create ──────────────────────────────────────────────────────────────
    def add(self, item: WardrobeItem) -> str:
        """Insert ``item``, generating a uuid if not set. Returns the id."""
        if not item.category:
            raise ValueError("category is required")
        if item.id is None:
            item.id = str(uuid.uuid4())
        now = _utc_now_iso()
        item.created_at = item.created_at or now
        item.updated_at = item.updated_at or now

        row = _item_to_row(item)
        cols = list(row.keys())
        placeholders = ",".join("?" for _ in cols)
        sql = (
            f"INSERT INTO wardrobe_items({','.join(cols)}) "
            f"VALUES ({placeholders})"
        )
        with transaction(self._conn):
            self._conn.execute(sql, [row[c] for c in cols])
        return item.id

    # ── read ────────────────────────────────────────────────────────────────
    def get(self, item_id: str, *, include_deleted: bool = False) -> Optional[WardrobeItem]:
        """Fetch a single item by id. Returns None if absent or soft-deleted."""
        sql = "SELECT * FROM wardrobe_items WHERE id = ?"
        if not include_deleted:
            sql += " AND deleted_at IS NULL"
        row = self._conn.execute(sql, (item_id,)).fetchone()
        return _row_to_item(row) if row else None

    def list_by_category(
        self,
        category: Optional[str] = None,
        *,
        include_deleted: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[WardrobeItem]:
        """List items, optionally filtered by category. Default page is 100.

        Soft-deleted rows are excluded unless ``include_deleted=True``.
        """
        clauses: list[str] = []
        params: list[Any] = []
        if category is not None:
            clauses.append("category = ?")
            params.append(category)
        if not include_deleted:
            clauses.append("deleted_at IS NULL")
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = (
            f"SELECT * FROM wardrobe_items{where} "
            f"ORDER BY created_at DESC LIMIT ? OFFSET ?"
        )
        params += [limit, offset]
        rows = self._conn.execute(sql, params).fetchall()
        return [_row_to_item(r) for r in rows]

    def count(self, *, include_deleted: bool = False) -> int:
        """Total count of items (active by default)."""
        sql = "SELECT COUNT(*) AS n FROM wardrobe_items"
        if not include_deleted:
            sql += " WHERE deleted_at IS NULL"
        return int(self._conn.execute(sql).fetchone()["n"])

    # ── update ──────────────────────────────────────────────────────────────
    def update(self, item_id: str, **fields: Any) -> None:
        """Partial update by dataclass field name.

        ``fields`` keys must be names on ``WardrobeItem``; columns are
        looked up via ``_ITEM_COL_MAP``. Raises KeyError on unknown keys.
        Soft-deleted rows can still be updated (e.g., to undo deletion via
        ``deleted_at=None``).
        """
        if not fields:
            return
        unknown = set(fields) - set(_ITEM_COL_MAP)
        if unknown:
            raise KeyError(f"Unknown wardrobe item fields: {sorted(unknown)}")

        sets: list[str] = []
        values: list[Any] = []
        for k, v in fields.items():
            col = _ITEM_COL_MAP[k]
            if col in _ITEM_JSON_COLUMNS and not isinstance(v, (str, type(None))):
                v = _json_or_none(v)
            elif col == "needs_tailoring_bool":
                v = 1 if v else 0
            sets.append(f"{col} = ?")
            values.append(v)
        sets.append("updated_at = ?")
        values.append(_utc_now_iso())
        values.append(item_id)

        sql = f"UPDATE wardrobe_items SET {', '.join(sets)} WHERE id = ?"
        with transaction(self._conn):
            self._conn.execute(sql, values)

    # ── delete ──────────────────────────────────────────────────────────────
    def soft_delete(self, item_id: str) -> None:
        """Mark an item as deleted. Idempotent."""
        with transaction(self._conn):
            self._conn.execute(
                "UPDATE wardrobe_items SET deleted_at = ?, updated_at = ? "
                "WHERE id = ? AND deleted_at IS NULL",
                (_utc_now_iso(), _utc_now_iso(), item_id),
            )

    def restore(self, item_id: str) -> None:
        """Undo a soft delete. Idempotent."""
        with transaction(self._conn):
            self._conn.execute(
                "UPDATE wardrobe_items SET deleted_at = NULL, updated_at = ? WHERE id = ?",
                (_utc_now_iso(), item_id),
            )

    # ── embeddings ──────────────────────────────────────────────────────────
    def set_embedding(self, item_id: str, vector: list[float]) -> None:
        """Insert or replace a Fashion-CLIP embedding for ``item_id``.

        ``vector`` must be 512 floats. We delete any existing row first
        because vec0 doesn't support upsert directly.
        """
        if len(vector) != 512:
            raise ValueError(f"embedding must be 512-dim, got {len(vector)}")
        # sqlite-vec accepts a JSON array string for INSERT.
        vec_text = json.dumps(vector)
        with transaction(self._conn):
            self._conn.execute(
                "DELETE FROM wardrobe_items_vec WHERE item_id = ?",
                (item_id,),
            )
            self._conn.execute(
                "INSERT INTO wardrobe_items_vec(item_id, embedding) VALUES (?, ?)",
                (item_id, vec_text),
            )

    def find_similar(
        self,
        vector: list[float],
        *,
        k: int = 10,
        exclude_ids: list[str] | None = None,
    ) -> list[tuple[str, float]]:
        """K-nearest-neighbors search by cosine distance.

        Returns ``[(item_id, distance), ...]`` sorted by distance ascending.
        Distances <= ~0.2 are typically "very similar". Soft-deleted items
        are filtered out via a join.
        """
        if len(vector) != 512:
            raise ValueError(f"embedding must be 512-dim, got {len(vector)}")
        exclude_ids = exclude_ids or []
        # sqlite-vec MATCH operator with LIMIT k.
        # Inner SELECT returns (item_id, distance); we LEFT JOIN to filter
        # deleted rows and exclude_ids.
        ph = ",".join("?" for _ in exclude_ids) if exclude_ids else "''"
        sql = f"""
            SELECT v.item_id, v.distance
              FROM wardrobe_items_vec v
              JOIN wardrobe_items i ON i.id = v.item_id
             WHERE v.embedding MATCH ?
               AND k = ?
               AND i.deleted_at IS NULL
               AND v.item_id NOT IN ({ph})
          ORDER BY v.distance
        """
        params: list[Any] = [json.dumps(vector), k, *exclude_ids]
        rows = self._conn.execute(sql, params).fetchall()
        return [(r["item_id"], float(r["distance"])) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# Audit log repo (used by upcoming steps; minimal surface for now)
# ─────────────────────────────────────────────────────────────────────────────


class AuditRepo:
    """Append-only audit log."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def write(self, kind: str, message: str, *, actor: Optional[str] = None) -> None:
        with transaction(self._conn):
            self._conn.execute(
                "INSERT INTO audit_log(kind, actor, message) VALUES (?, ?, ?)",
                (kind, actor, message),
            )

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT id, ts, kind, actor, message FROM audit_log "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# Top-level facade
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class Repo:
    """Bundle of per-domain repositories sharing one connection.

    Construct once per worker / request; all methods on the children
    are safe to call as long as the connection is alive.
    """

    conn: sqlite3.Connection
    profile: ProfileRepo = field(init=False)
    items: ItemsRepo = field(init=False)
    audit: AuditRepo = field(init=False)

    def __post_init__(self) -> None:
        self.profile = ProfileRepo(self.conn)
        self.items = ItemsRepo(self.conn)
        self.audit = AuditRepo(self.conn)
