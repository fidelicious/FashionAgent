"""
Persistence layer for outfit recommendations.

The `outfits` table records every outfit shipped to Discord (manual or
scheduled). `outfit_items` keeps the role→item mapping so future "what
did I wear last week?" queries don't need to re-derive it.

Kept narrowly scoped to writes the daily-push job needs today. Read
helpers we use for the duplicate-penalty signal (`recently_worn_ids`)
live here too because they're outfit-shaped queries.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from clawbot.db.connection import transaction
from clawbot.outfits.llm_schema import OutfitChoice
from clawbot.outfits.types import ScoredOutfit


@dataclass(frozen=True)
class OutfitRecord:
    """Read-side projection of an outfit + its item assignments."""

    outfit_id: str
    generated_at: str
    occasion: str | None
    score: float
    llm_explanation: str | None
    collage_path: str | None
    item_ids_by_role: dict[str, str] = field(default_factory=dict)


class OutfitsRepo:
    """CRUD for the outfits + outfit_items tables.

    Saves are wrapped in a single `BEGIN IMMEDIATE` transaction so an FK
    failure on `outfit_items` rolls the parent `outfits` row back rather
    than leaving an orphan.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save(
        self,
        *,
        scored: ScoredOutfit,
        choice: OutfitChoice,
        collage_path: Path | str,
        occasion: str,
        weather_summary: str | None = None,
    ) -> str:
        """Insert one outfit + its outfit_items rows. Returns the new id.

        The transaction ensures partial writes (e.g. an item id that no
        longer exists in wardrobe_items) don't leave an orphan outfits row.
        """
        outfit_id = uuid.uuid4().hex
        with transaction(self._conn):
            self._conn.execute(
                """
                INSERT INTO outfits (id, occasion, weather_summary, score,
                                     llm_explanation, collage_path)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    outfit_id,
                    occasion,
                    weather_summary,
                    scored.total,
                    choice.reason,
                    str(collage_path),
                ),
            )
            for role, item in scored.outfit.items_by_role.items():
                self._conn.execute(
                    "INSERT INTO outfit_items (outfit_id, item_id, role) VALUES (?, ?, ?)",
                    (outfit_id, item.id, role),
                )
        return outfit_id

    def get(self, outfit_id: str) -> OutfitRecord | None:
        """Return an OutfitRecord (with item assignments) or None."""
        outfit_row = self._conn.execute(
            "SELECT * FROM outfits WHERE id = ?", (outfit_id,)
        ).fetchone()
        if outfit_row is None:
            return None
        item_rows = self._conn.execute(
            "SELECT role, item_id FROM outfit_items WHERE outfit_id = ?",
            (outfit_id,),
        ).fetchall()
        return OutfitRecord(
            outfit_id=outfit_row["id"],
            generated_at=outfit_row["generated_at"],
            occasion=outfit_row["occasion"],
            score=float(outfit_row["score"] or 0.0),
            llm_explanation=outfit_row["llm_explanation"],
            collage_path=outfit_row["collage_path"],
            item_ids_by_role={r["role"]: r["item_id"] for r in item_rows},
        )

    def recent(self, *, limit: int = 10) -> list[OutfitRecord]:
        """Return the N newest outfits, including item assignments.

        Tiebreak on rowid because `generated_at` is second-precision and
        rapid saves (manual triggers, tests) can land in the same second.
        """
        rows = self._conn.execute(
            "SELECT id FROM outfits ORDER BY generated_at DESC, rowid DESC LIMIT ?",
            (limit,),
        ).fetchall()
        results: list[OutfitRecord] = []
        for r in rows:
            rec = self.get(r["id"])
            if rec is not None:
                results.append(rec)
        return results

    def recently_worn_ids(self, *, limit: int = 14) -> set[str]:
        """Item ids that appear in any of the last `limit` outfits.

        Fed into the duplicate_penalty sub-scorer so today's outfit doesn't
        repeat last Tuesday's. `limit` is the window in *outfits*, not days
        — typical daily push → roughly two weeks of variety.
        """
        rows = self._conn.execute(
            """
            SELECT DISTINCT oi.item_id
              FROM outfit_items oi
              JOIN outfits o ON o.id = oi.outfit_id
             ORDER BY o.generated_at DESC, o.rowid DESC
             LIMIT ?
            """,
            (limit * 6,),  # rough upper bound: 6 items per outfit
        ).fetchall()
        return {r["item_id"] for r in rows}
