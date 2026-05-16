"""
Color-palette extraction for cutout images.

Wraps colorthief.ColorThief. Runs on the rembg cutout so the palette is
not polluted by the original photo's background. Returns the top color
as ``color_primary``; the second is ``color_secondary`` unless it's
within a perceptual distance of the primary, in which case we treat the
item as single-color.
"""

from __future__ import annotations

import io
import math
from pathlib import Path

# colorthief is in the [dev] extras, so safe to import at module level
# alongside Pillow. Heavy ML deps live inside function bodies elsewhere.
from colorthief import ColorThief
from PIL import Image

# Two colors within this Euclidean distance in RGB space are treated as
# the same color. Tuned empirically: ~30 catches near-identical shades
# while letting genuine two-tone garments register a secondary.
_SECONDARY_DISTANCE_THRESHOLD = 30.0

# Maximum perceptual distance (sqrt(3) * 255 ≈ 441) used to normalize the
# heuristic confidence score into [0, 1].
_MAX_RGB_DISTANCE = math.sqrt(3) * 255.0


def _make_thief(cutout_path: Path) -> ColorThief:
    """Return a ColorThief backed by a grey-composited rendering of cutout_path.

    colorthief has two silent filters that can produce zero valid pixels:
    1. Alpha filter: drops pixels with alpha < 125 — harmless for real photos
       but kills fully-transparent rembg cutouts of synthetic test images.
    2. ``ignore_white`` filter (default True): drops pixels where R, G, B > 250
       — kills cutouts where rembg left only near-white pixels opaque.

    Compositing the RGBA image onto a neutral mid-grey (128, 128, 128)
    background sidesteps both filters: garment pixels blend with grey
    (still identifiable as the garment's hue), and a fully-transparent
    cutout degrades gracefully to grey rather than crashing.
    """
    with Image.open(cutout_path) as img:
        if img.mode == "RGBA":
            bg = Image.new("RGB", img.size, (128, 128, 128))
            # paste uses the alpha channel as the compositing mask.
            bg.paste(img.convert("RGB"), mask=img.split()[3])
            composite = bg
        elif img.mode != "RGB":
            composite = img.convert("RGB")
        else:
            composite = img.copy()

        buf = io.BytesIO()
        composite.save(buf, format="PNG")
        buf.seek(0)
    return ColorThief(buf)


def extract_palette(cutout_path: Path) -> tuple[str, str | None, float]:
    """Extract primary + optional secondary color from a cutout image.

    Parameters
    ----------
    cutout_path
        PNG path produced by ``cutout.remove_background``. Transparency
        is ignored by colorthief; only opaque pixels contribute.

    Returns
    -------
    (primary_hex, secondary_hex_or_None, confidence)
        Confidence is a heuristic in [0, 1]: how distinct the primary is
        from the average of the palette tail. 1.0 = strong single hue.
    """
    thief = _make_thief(cutout_path)
    palette = thief.get_palette(color_count=3, quality=10)
    primary_rgb = palette[0]

    secondary_rgb: tuple[int, int, int] | None = None
    if len(palette) > 1:
        candidate = palette[1]
        if _rgb_distance(primary_rgb, candidate) > _SECONDARY_DISTANCE_THRESHOLD:
            secondary_rgb = candidate

    # Confidence: distance from primary to the mean of the tail, normalized.
    tail = palette[1:] if len(palette) > 1 else [primary_rgb]
    mean_tail = (
        sum(c[0] for c in tail) / len(tail),
        sum(c[1] for c in tail) / len(tail),
        sum(c[2] for c in tail) / len(tail),
    )
    distance = _rgb_distance(primary_rgb, mean_tail)
    confidence = 1.0 - min(1.0, distance / _MAX_RGB_DISTANCE)

    return _hex(primary_rgb), _hex(secondary_rgb) if secondary_rgb else None, confidence


def _rgb_distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def _hex(rgb: tuple[int, int, int]) -> str:
    return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"
