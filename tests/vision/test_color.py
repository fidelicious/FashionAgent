"""
Tests for clawbot.vision.color.

extract_palette wraps colorthief. Tests run on synthetic solid-color
images so the expected output is predictable.
"""

from __future__ import annotations

from pathlib import Path

from clawbot.vision.color import extract_palette


def _approx_color(actual: str, expected: tuple[int, int, int], tol: int = 30) -> None:
    """Assert two #RRGGBB strings are within ``tol`` per channel.

    Colorthief k-means is non-deterministic on tiny inputs, so we allow
    a generous tolerance.
    """
    assert actual.startswith("#") and len(actual) == 7
    r, g, b = int(actual[1:3], 16), int(actual[3:5], 16), int(actual[5:7], 16)
    er, eg, eb = expected
    assert abs(r - er) <= tol, f"R: got {r}, expected ~{er}"
    assert abs(g - eg) <= tol, f"G: got {g}, expected ~{eg}"
    assert abs(b - eb) <= tol, f"B: got {b}, expected ~{eb}"


def test_returns_tuple_of_primary_secondary_confidence(synthetic_top: Path) -> None:
    result = extract_palette(synthetic_top)
    assert isinstance(result, tuple)
    assert len(result) == 3
    primary, secondary, confidence = result
    assert primary.startswith("#")
    assert secondary is None or secondary.startswith("#")
    assert 0.0 <= confidence <= 1.0


def test_primary_color_matches_synthetic(synthetic_top: Path) -> None:
    primary, _, _ = extract_palette(synthetic_top)
    # synthetic_top is solid (20, 30, 80) — navy.
    _approx_color(primary, (20, 30, 80))


def test_solid_image_has_no_secondary(synthetic_footwear: Path) -> None:
    """A pure-black image yields one dominant color; secondary should be None."""
    _, secondary, _ = extract_palette(synthetic_footwear)
    assert secondary is None


def test_hex_format_is_uppercase_six_digits(synthetic_dress: Path) -> None:
    primary, _, _ = extract_palette(synthetic_dress)
    assert primary[0] == "#"
    assert len(primary) == 7
    # All hex digits, uppercase canonical form.
    assert primary[1:].isalnum()
    assert primary == primary.upper()
