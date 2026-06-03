"""
Item-image attachment helpers for Discord command responses.

Two layers, deliberately split so the rules are testable without discord.py:

    select_item_image(item) -> Path | None
        Pure: pick which stored image to show and confirm it exists on disk.
        Preference order is raw → cutout → final — the operator's original
        photo is the most recognisable; the processed cutout/final are
        fallbacks for older rows that only have those.

    build_item_files(items, *, cap) -> list[discord.File]
        Thin: map items through ``select_item_image`` and build attachments,
        capped at Discord's per-message limit. discord.py is imported lazily
        so ``select_item_image`` stays importable in environments without it.

Missing files never raise — they're skipped — so a wardrobe row pointing at a
deleted image degrades to text-only rather than crashing the command.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Optional

from clawbot.db.repo import WardrobeItem

logger = logging.getLogger(__name__)

# Discord accepts at most 10 attachments on a single message.
MAX_ATTACHMENTS = 10


def select_item_image(item: WardrobeItem) -> Optional[Path]:
    """Return the best on-disk image for ``item``, or None if it has none.

    Tries the raw upload first, then the cutout, then the final render, and
    returns the first path whose file actually exists on disk. A path that is
    set in the DB but missing from the filesystem is skipped (not an error).
    """
    for candidate in (
        item.image_raw_path,
        item.image_cutout_path,
        item.image_final_path,
    ):
        if not candidate:
            continue
        path = Path(candidate)
        if path.is_file():
            return path
    return None


def _short_id(item_id: Optional[str]) -> str:
    """First 8 chars of the uuid — matches the id shown by /wardrobe."""
    return (item_id or "????????")[:8]


def _attachment_filename(item: WardrobeItem, path: Path) -> str:
    """Build a gallery-friendly filename: ``<shortid>_<slug><suffix>``.

    Raw photos carry no in-image label, so the filename is the only thing
    tying a photo back to its item in Discord's attachment gallery. We slug
    the item name to keep it filesystem- and Discord-safe.
    """
    name = (item.name or "item").strip()
    slug = "".join(c if (c.isalnum() or c in " -_") else "_" for c in name)
    slug = "-".join(slug.split())[:40] or "item"
    return f"{_short_id(item.id)}_{slug}{path.suffix.lower()}"


def build_item_files(
    items: Iterable[WardrobeItem], *, cap: int = MAX_ATTACHMENTS
) -> list[Any]:
    """Build up to ``cap`` ``discord.File`` attachments for ``items``.

    Items without a usable on-disk image are skipped. A file that can't be
    opened is logged and skipped rather than aborting the whole batch.
    """
    import discord  # lazy: keep select_item_image usable without discord.py

    files: list[Any] = []
    for item in items:
        if len(files) >= cap:
            break
        path = select_item_image(item)
        if path is None:
            continue
        try:
            files.append(
                discord.File(str(path), filename=_attachment_filename(item, path))
            )
        except OSError as e:
            logger.warning(
                "could not attach image for item %s: %s", _short_id(item.id), e
            )
    return files
