"""
Tests for the item-image attachment helpers.

``select_item_image`` is pure (path fallback + on-disk existence check) and is
the bulk of the logic; ``build_item_files`` is the thin discord.File-building
layer. We test selection exhaustively and the file builder for its cap, skip,
and filename-labelling behaviour.
"""

from __future__ import annotations

from pathlib import Path

from clawbot.db.repo import WardrobeItem
from clawbot.discord.images import (
    MAX_ATTACHMENTS,
    build_item_files,
    select_item_image,
)


def _img(tmp_path: Path, name: str) -> Path:
    """Create a tiny real file on disk and return its path."""
    p = tmp_path / name
    p.write_bytes(b"\x89PNG\r\n\x1a\n")  # not a real PNG, but a real file
    return p


# ─────────────────────────────────────────────────────────────────────────────
# select_item_image — fallback order is raw → cutout → final
# ─────────────────────────────────────────────────────────────────────────────


def test_select_prefers_raw_when_present(tmp_path: Path) -> None:
    raw = _img(tmp_path, "raw.jpg")
    cut = _img(tmp_path, "cut.png")
    item = WardrobeItem(
        category="tops", image_raw_path=str(raw), image_cutout_path=str(cut)
    )
    assert select_item_image(item) == raw


def test_select_falls_back_to_cutout_when_raw_missing_on_disk(tmp_path: Path) -> None:
    cut = _img(tmp_path, "cut.png")
    # raw path is set but the file does not exist on disk
    item = WardrobeItem(
        category="tops",
        image_raw_path=str(tmp_path / "gone.jpg"),
        image_cutout_path=str(cut),
    )
    assert select_item_image(item) == cut


def test_select_falls_back_to_final(tmp_path: Path) -> None:
    final = _img(tmp_path, "final.png")
    item = WardrobeItem(
        category="tops",
        image_raw_path=None,
        image_cutout_path=None,
        image_final_path=str(final),
    )
    assert select_item_image(item) == final


def test_select_returns_none_when_no_paths_set() -> None:
    assert select_item_image(WardrobeItem(category="tops")) is None


def test_select_returns_none_when_paths_set_but_files_absent(tmp_path: Path) -> None:
    item = WardrobeItem(
        category="tops",
        image_raw_path=str(tmp_path / "a.jpg"),
        image_cutout_path=str(tmp_path / "b.png"),
        image_final_path=str(tmp_path / "c.png"),
    )
    assert select_item_image(item) is None


def test_select_skips_heic_raw_and_returns_png_cutout(tmp_path: Path) -> None:
    """HEIC files are not renderable by Discord — the cutout PNG must be
    returned even when the raw HEIC file exists on disk."""
    heic_raw = _img(tmp_path, "raw.heic")
    png_cut = _img(tmp_path, "cut.png")
    item = WardrobeItem(
        category="tops",
        image_raw_path=str(heic_raw),
        image_cutout_path=str(png_cut),
    )
    assert select_item_image(item) == png_cut


def test_select_skips_heif_raw_and_returns_png_cutout(tmp_path: Path) -> None:
    """Same guard for the .heif extension variant."""
    heif_raw = _img(tmp_path, "raw.heif")
    png_cut = _img(tmp_path, "cut.png")
    item = WardrobeItem(
        category="tops",
        image_raw_path=str(heif_raw),
        image_cutout_path=str(png_cut),
    )
    assert select_item_image(item) == png_cut


# ─────────────────────────────────────────────────────────────────────────────
# build_item_files — cap, skip-missing, identifying filename
# ─────────────────────────────────────────────────────────────────────────────


def test_build_caps_at_max_attachments(tmp_path: Path) -> None:
    items = []
    for i in range(MAX_ATTACHMENTS + 5):
        p = _img(tmp_path, f"{i}.jpg")
        items.append(
            WardrobeItem(category="tops", id=f"{i:08d}", image_raw_path=str(p))
        )
    files = build_item_files(items)
    assert len(files) == MAX_ATTACHMENTS


def test_build_honours_explicit_cap(tmp_path: Path) -> None:
    items = [
        WardrobeItem(
            category="tops", id=f"{i:08d}", image_raw_path=str(_img(tmp_path, f"{i}.jpg"))
        )
        for i in range(5)
    ]
    assert len(build_item_files(items, cap=2)) == 2


def test_build_skips_items_without_an_image(tmp_path: Path) -> None:
    with_img = WardrobeItem(
        category="tops", id="aaaaaaaa", image_raw_path=str(_img(tmp_path, "x.jpg"))
    )
    without = WardrobeItem(category="tops", id="bbbbbbbb")  # no image at all
    files = build_item_files([with_img, without])
    assert len(files) == 1


def test_build_filename_encodes_short_id_and_name(tmp_path: Path) -> None:
    item = WardrobeItem(
        category="tops",
        id="a3f2c841ffff",
        name="Navy wool cardigan",
        image_raw_path=str(_img(tmp_path, "x.jpg")),
    )
    [f] = build_item_files([item])
    assert f.filename.startswith("a3f2c841")
    assert "Navy" in f.filename or "navy" in f.filename.lower()
    assert f.filename.endswith(".jpg")
