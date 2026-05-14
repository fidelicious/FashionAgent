"""
Shared fixtures for vision-package unit tests.

All fixtures are tiny synthetic images generated at test time — no binary
files committed to the repo. They exercise plumbing, not model accuracy;
semantic correctness is validated manually on real photos during Step 7.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw


def _save_solid(tmp_path: Path, name: str, color: tuple[int, int, int]) -> Path:
    """Write a 256x256 solid-color PNG to tmp_path and return its path."""
    path = tmp_path / name
    Image.new("RGB", (256, 256), color=color).save(path, "PNG")
    return path


@pytest.fixture
def synthetic_top(tmp_path: Path) -> Path:
    """Navy-blue flat: stands in for an upload photo of a top."""
    return _save_solid(tmp_path, "top.png", (20, 30, 80))


@pytest.fixture
def synthetic_bottoms(tmp_path: Path) -> Path:
    """Khaki-tan flat: stands in for an upload photo of pants."""
    return _save_solid(tmp_path, "bottoms.png", (180, 160, 110))


@pytest.fixture
def synthetic_dress(tmp_path: Path) -> Path:
    """Burgundy flat: stands in for an upload photo of a dress."""
    return _save_solid(tmp_path, "dress.png", (130, 30, 60))


@pytest.fixture
def synthetic_footwear(tmp_path: Path) -> Path:
    """Black flat: stands in for an upload photo of shoes."""
    return _save_solid(tmp_path, "shoes.png", (15, 15, 15))


@pytest.fixture
def synthetic_screenshot(tmp_path: Path) -> Path:
    """White canvas with retailer-like text rendered into it.

    Tesseract is mocked in unit tests so the actual rendering doesn't
    need to be perfectly readable — it just needs to *be* a valid PNG
    with a known stem. The drawn text matches the strings that the OCR
    mock will return.
    """
    path = tmp_path / "screenshot.png"
    img = Image.new("RGB", (512, 256), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    # Default PIL font is fine; we don't OCR this for real in unit tests.
    draw.text((20, 80), "ARITZIA", fill=(0, 0, 0))
    draw.text((20, 130), "Babaton Cardigan  $89.00", fill=(0, 0, 0))
    img.save(path, "PNG")
    return path
