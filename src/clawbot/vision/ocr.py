"""
Tesseract OCR with regex brand + price extraction.

We deliberately keep this regex-based, not LLM-based, because:
    1. Tesseract output on retailer screenshots is short and structured.
    2. Regex failures (returning None) are an acceptable mode — the
       Discord layer just shows ❓ and lets the user fill it in.
    3. Loading the LLM from inside an image worker would burn RAM budget.

The retailer list is the V1 target set; add new retailers here as we
encounter their email/screenshot formats.
"""

from __future__ import annotations

import re
from pathlib import Path

from PIL import Image

from clawbot.vision.draft import OcrResult

# Canonical brand names. Case-insensitive substring match; first hit wins.
_KNOWN_BRANDS: tuple[str, ...] = (
    "Aritzia",
    "Banana Republic",
    "COS",
    "Everlane",
    "J.Crew",
    "Madewell",
    "Nordstrom",
    "Quince",
    "Sezane",
    "Theory",
    "Uniqlo",
)

# Matches $X, $X.XX, $X,XXX, $XX.XX, optional whitespace after $.
_PRICE_RE = re.compile(r"\$\s*([0-9]{1,3}(?:,[0-9]{3})*|[0-9]+)(?:\.([0-9]{2}))?")


def read(raw_path: Path) -> OcrResult:
    """Run Tesseract and pull out brand + price."""
    with Image.open(raw_path) as img:
        text = _tesseract_image_to_string(img)
    return OcrResult(
        brand=_guess_brand(text),
        price_usd=_guess_price(text),
        raw_text=text,
    )


def _guess_brand(text: str) -> str | None:
    lower = text.lower()
    for brand in _KNOWN_BRANDS:
        if brand.lower() in lower:
            return brand
    return None


def _guess_price(text: str) -> float | None:
    match = _PRICE_RE.search(text)
    if not match:
        return None
    whole = match.group(1).replace(",", "")
    cents = match.group(2)
    try:
        return float(f"{whole}.{cents}") if cents else float(whole)
    except ValueError:
        return None


def _tesseract_image_to_string(image: Image.Image) -> str:
    """Wraps pytesseract.image_to_string — exists so tests can monkeypatch.

    Lazy import keeps pytesseract out of import time on hosts that lack it.
    """
    import pytesseract  # noqa: PLC0415 — intentional lazy import

    return pytesseract.image_to_string(image)
