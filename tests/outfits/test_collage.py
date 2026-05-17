"""
Tests for the outfit collage builder.

These verify *plumbing*, not aesthetics:
  - the output file exists and is a valid PNG of the expected dimensions;
  - each role's tile carries the source image's dominant colour (so we know
    the layout function placed items in the right slots);
  - missing image_final_path falls back to a placeholder tile (no crash).

We deliberately avoid byte-exact snapshots — those break on Pillow / font
version drifts and don't tell us anything about correctness.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from clawbot.outfits.collage import CollageConfig, build_collage
from tests.outfits.conftest import make_item

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _save_solid(tmp_path: Path, name: str, color: tuple[int, int, int]) -> Path:
    """Write a 512×512 solid-colour PNG and return its path.

    512 matches the default tile size on a 1024-canvas so the pasted image
    fills the tile end-to-end — important for the per-tile colour assertions
    below, which would otherwise average heavy background bleed.
    """
    path = tmp_path / name
    Image.new("RGB", (512, 512), color=color).save(path, "PNG")
    return path


def _avg_color(im: Image.Image, box: tuple[int, int, int, int]) -> tuple[int, int, int]:
    """Average RGB of the given rectangle. Used to assert a tile got the
    right source image."""
    crop = im.crop(box).resize((1, 1), Image.Resampling.BILINEAR)
    r, g, b = crop.getpixel((0, 0))[:3]
    return (r, g, b)


def _close(a: tuple[int, int, int], b: tuple[int, int, int], tolerance: int = 25) -> bool:
    """Channel-wise absolute distance under tolerance."""
    return all(abs(x - y) <= tolerance for x, y in zip(a, b, strict=True))


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def navy_top_path(tmp_path: Path) -> Path:
    return _save_solid(tmp_path, "top.png", (20, 30, 80))


@pytest.fixture
def khaki_bottoms_path(tmp_path: Path) -> Path:
    return _save_solid(tmp_path, "bottoms.png", (180, 160, 110))


@pytest.fixture
def black_shoes_path(tmp_path: Path) -> Path:
    return _save_solid(tmp_path, "shoes.png", (15, 15, 15))


@pytest.fixture
def burgundy_outer_path(tmp_path: Path) -> Path:
    return _save_solid(tmp_path, "outer.png", (130, 30, 60))


@pytest.fixture
def three_item_outfit(navy_top_path, khaki_bottoms_path, black_shoes_path, make_outfit):
    return make_outfit(
        top=make_item(item_id="t", category="tops"),
        bottom=make_item(item_id="b", category="bottoms"),
        footwear=make_item(item_id="f", category="footwear"),
    ), {
        "top": navy_top_path,
        "bottom": khaki_bottoms_path,
        "footwear": black_shoes_path,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Behaviour
# ─────────────────────────────────────────────────────────────────────────────


class TestBuildCollage:
    def test_writes_file_with_expected_dimensions(self, three_item_outfit, tmp_path):
        outfit, image_paths = three_item_outfit
        out = tmp_path / "collage.png"

        path = build_collage(outfit, out, image_paths=image_paths)

        assert path == out
        assert path.exists()
        with Image.open(path) as im:
            assert im.size == (CollageConfig().canvas_px, CollageConfig().canvas_px)
            assert im.format == "PNG"

    def test_each_tile_carries_its_source_colour(self, three_item_outfit, tmp_path):
        outfit, image_paths = three_item_outfit
        out = tmp_path / "collage.png"
        build_collage(outfit, out, image_paths=image_paths)

        with Image.open(out) as im:
            w, h = im.size
            half_w, half_h = w // 2, h // 2

            # 2×2 grid: top-left → top, top-right → bottom, bottom-left → footwear.
            # The tile-to-role mapping is the layout function's contract; we
            # check by sampling the interior of each cell (inset to avoid the
            # padding gap).
            inset = 30
            tl_avg = _avg_color(im, (inset, inset, half_w - inset, half_h - inset))
            tr_avg = _avg_color(im, (half_w + inset, inset, w - inset, half_h - inset))
            bl_avg = _avg_color(im, (inset, half_h + inset, half_w - inset, h - inset))

            assert _close(tl_avg, (20, 30, 80)), f"top tile colour drifted: {tl_avg}"
            assert _close(tr_avg, (180, 160, 110)), f"bottom tile colour drifted: {tr_avg}"
            assert _close(bl_avg, (15, 15, 15)), f"footwear tile colour drifted: {bl_avg}"

    def test_outer_layer_uses_fourth_slot(
        self,
        navy_top_path,
        khaki_bottoms_path,
        black_shoes_path,
        burgundy_outer_path,
        make_outfit,
        tmp_path,
    ):
        outfit = make_outfit(
            top=make_item(item_id="t", category="tops"),
            bottom=make_item(item_id="b", category="bottoms"),
            footwear=make_item(item_id="f", category="footwear"),
            outer=make_item(item_id="o", category="outerwear"),
        )
        image_paths = {
            "top": navy_top_path,
            "bottom": khaki_bottoms_path,
            "footwear": black_shoes_path,
            "outer": burgundy_outer_path,
        }
        out = tmp_path / "collage.png"
        build_collage(outfit, out, image_paths=image_paths)

        with Image.open(out) as im:
            w, h = im.size
            half_w, half_h = w // 2, h // 2
            inset = 30
            br_avg = _avg_color(im, (half_w + inset, half_h + inset, w - inset, h - inset))
            assert _close(br_avg, (130, 30, 60)), f"outer tile colour drifted: {br_avg}"

    def test_missing_image_path_renders_placeholder(
        self, navy_top_path, khaki_bottoms_path, make_outfit, tmp_path
    ):
        # The footwear item is in the outfit but has no image yet (e.g. it was
        # added before the image pipeline ran).
        outfit = make_outfit(
            top=make_item(item_id="t", category="tops"),
            bottom=make_item(item_id="b", category="bottoms"),
            footwear=make_item(item_id="f", category="footwear"),
        )
        image_paths = {
            "top": navy_top_path,
            "bottom": khaki_bottoms_path,
            # footwear missing on purpose
        }
        out = tmp_path / "collage.png"
        # Should not raise.
        path = build_collage(outfit, out, image_paths=image_paths)
        assert path.exists()

    def test_custom_canvas_size_respected(self, three_item_outfit, tmp_path):
        outfit, image_paths = three_item_outfit
        out = tmp_path / "collage.png"
        build_collage(outfit, out, image_paths=image_paths, config=CollageConfig(canvas_px=512))
        with Image.open(out) as im:
            assert im.size == (512, 512)

    def test_dress_outfit_uses_dress_slot(
        self, burgundy_outer_path, black_shoes_path, make_outfit, tmp_path
    ):
        # Dresses live in their own slot; the layout function decides where.
        outfit = make_outfit(
            dress=make_item(item_id="d", category="dresses"),
            footwear=make_item(item_id="f", category="footwear"),
        )
        image_paths = {"dress": burgundy_outer_path, "footwear": black_shoes_path}
        out = tmp_path / "collage.png"
        # Must succeed — dresses are valid outfits.
        path = build_collage(outfit, out, image_paths=image_paths)
        assert path.exists()
