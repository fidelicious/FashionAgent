"""
Outfit collage builder (build Step 12).

Given an Outfit and a `role → image_path` mapping, compose one square PNG
that visualises the chosen outfit for a Discord embed. Items without an
image are rendered as a labelled placeholder tile rather than crashing.

Strict separation:
  - this file: Pillow plumbing, file I/O, placeholders.
  - `_layout_for_outfit()` below: layout policy (USER CONTRIBUTION).

The layout function is intentionally tiny (5–10 lines) so it's easy to
swap between 2×2 grid, vertical strip, role-anchored mannequin diagram,
etc., without touching the compositor.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

from clawbot.outfits.types import Outfit

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CollageConfig:
    """
    Visual tuning for the collage. All units are pixels.

    Defaults target Discord embed proportions (1:1 looks best in the inline
    preview; 1024 is a reasonable balance between sharpness and file size
    on the NUC's slow upload).
    """

    canvas_px: int = 1024
    background_rgb: tuple[int, int, int] = (245, 245, 245)
    gutter_px: int = 8
    placeholder_rgb: tuple[int, int, int] = (210, 210, 210)
    placeholder_text_rgb: tuple[int, int, int] = (90, 90, 90)


# ─────────────────────────────────────────────────────────────────────────────
# Layout — USER CONTRIBUTION SURFACE
# ─────────────────────────────────────────────────────────────────────────────
#
# The layout function decides which role occupies which tile of a 2×2 grid.
# Returning fewer than 4 entries simply leaves the unused slots as background.
#
# Slot indices in the 2×2 grid:
#     0 (top-left)     1 (top-right)
#     2 (bottom-left)  3 (bottom-right)
#
# Trade-offs to consider when tweaking:
#   - Visual hierarchy: many people read the embed top-left first; put the
#     hero piece there (currently `top` or `dress`).
#   - Body order: top→bottom→shoes mirrors how a person looks at someone
#     they meet, which feels natural.
#   - Outerwear: in cool seasons it carries more visual weight than the
#     top underneath — promote it to slot 0 if you live somewhere cold.
#
# Replace the body with your own mapping if you'd rather use a vertical
# strip, a mannequin-style layout, etc. Keep the return type stable
# (`dict[str, int]`) so the compositor doesn't need changes.

_DEFAULT_LAYOUT_PIECED: dict[str, int] = {
    "top": 0,  # hero, top-left
    "bottom": 1,  # top-right
    "footwear": 2,  # bottom-left
    "outer": 3,  # bottom-right (only present in cool-season outfits)
}

_DEFAULT_LAYOUT_DRESS: dict[str, int] = {
    "dress": 0,  # hero, top-left
    "footwear": 1,  # top-right
    # slots 2 and 3 left blank — looks cleaner than padding with accessories.
}


def _layout_for_outfit(outfit: Outfit) -> dict[str, int]:
    """Pick a slot mapping based on whether the outfit has a dress."""
    if "dress" in outfit.items_by_role:
        return _DEFAULT_LAYOUT_DRESS
    return _DEFAULT_LAYOUT_PIECED


# ─────────────────────────────────────────────────────────────────────────────
# Compositor (plumbing — no design decisions live here)
# ─────────────────────────────────────────────────────────────────────────────


def _slot_box(slot: int, canvas_px: int, gutter: int) -> tuple[int, int, int, int]:
    """Return the (left, top, right, bottom) box for a 2×2 grid slot."""
    half = canvas_px // 2
    col = slot % 2
    row = slot // 2
    x0 = col * half + gutter
    y0 = row * half + gutter
    x1 = (col + 1) * half - gutter
    y1 = (row + 1) * half - gutter
    return (x0, y0, x1, y1)


def _fit_into_box(im: Image.Image, box_w: int, box_h: int) -> Image.Image:
    """Resize an image to fit inside (box_w, box_h) preserving aspect ratio."""
    work = im.copy()
    work.thumbnail((box_w, box_h), Image.Resampling.LANCZOS)
    return work


def _draw_placeholder(
    canvas: Image.Image,
    box: tuple[int, int, int, int],
    label: str,
    config: CollageConfig,
) -> None:
    """Fill an empty slot with a grey rectangle + role label."""
    x0, y0, x1, y1 = box
    draw = ImageDraw.Draw(canvas)
    draw.rectangle(box, fill=config.placeholder_rgb)
    # Default PIL font; we don't ship one to keep image size down.
    text = f"({label})"
    # textbbox gives a tighter measurement than textsize on modern Pillow.
    bbox = draw.textbbox((0, 0), text)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    cx = (x0 + x1) // 2 - text_w // 2
    cy = (y0 + y1) // 2 - text_h // 2
    draw.text((cx, cy), text, fill=config.placeholder_text_rgb)


def _paste_centered(canvas: Image.Image, tile: Image.Image, box: tuple[int, int, int, int]) -> None:
    """Paste `tile` into `box` on `canvas`, centred."""
    x0, y0, x1, y1 = box
    box_w, box_h = x1 - x0, y1 - y0
    fitted = _fit_into_box(tile, box_w, box_h)
    fx = x0 + (box_w - fitted.width) // 2
    fy = y0 + (box_h - fitted.height) // 2
    # Use the alpha channel as a mask when the source has one (rembg cutouts).
    if fitted.mode in ("RGBA", "LA"):
        canvas.paste(fitted, (fx, fy), mask=fitted)
    else:
        canvas.paste(fitted, (fx, fy))


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────


def build_collage(
    outfit: Outfit,
    output_path: Path,
    *,
    image_paths: Mapping[str, Path | str | None] | None = None,
    config: CollageConfig | None = None,
) -> Path:
    """
    Compose `outfit` into a square PNG at `output_path`.

    Parameters:
        outfit:       the Outfit to render. items_by_role keys drive which
                      slots get filled.
        output_path:  where to write the PNG. Parent dir must exist.
        image_paths:  optional `role → filesystem path` mapping. When None,
                      we look up `item.image_final_path` from the outfit's
                      WardrobeItems. Missing or unreadable paths render as
                      labelled placeholders.
        config:       visual tuning (canvas size, gutter, background).

    Returns:
        `output_path` (echoed for ergonomics in callers like Step 13).
    """
    cfg = config or CollageConfig()
    canvas = Image.new("RGB", (cfg.canvas_px, cfg.canvas_px), color=cfg.background_rgb)

    layout = _layout_for_outfit(outfit)

    # Resolve the role→path lookup. Caller-provided mapping wins; otherwise
    # fall back to the items' own image_final_path attribute (set by Step 5).
    paths: dict[str, Path | None] = {}
    for role, item in outfit.items_by_role.items():
        if image_paths is not None and role in image_paths:
            raw = image_paths[role]
            paths[role] = Path(raw) if raw is not None else None
        else:
            # WardrobeItem in types.py doesn't carry image_final_path today —
            # add it when wiring this into Step 13. For now: placeholder.
            paths[role] = None

    for role, slot in layout.items():
        if role not in outfit.items_by_role:
            continue  # this outfit doesn't use this role; leave the slot blank.
        box = _slot_box(slot, cfg.canvas_px, cfg.gutter_px)
        src = paths.get(role)
        if src is None or not Path(src).exists():
            _draw_placeholder(canvas, box, role, cfg)
            continue
        try:
            with Image.open(src) as tile:
                tile.load()  # force read before the file handle closes
                _paste_centered(canvas, tile, box)
        except (OSError, ValueError):
            # Corrupt or unsupported file — degrade gracefully, never crash.
            _draw_placeholder(canvas, box, role, cfg)

    canvas.save(output_path, "PNG")
    return output_path
