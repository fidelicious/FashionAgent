"""
Tests for clawbot.vision.ocr.

Tesseract is monkeypatched. Tests cover brand-list matching, price regex
on common formats, and the raw_text round-trip.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from clawbot.vision import ocr
from clawbot.vision.draft import OcrResult


def _stub_tesseract(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    monkeypatch.setattr(ocr, "_tesseract_image_to_string", lambda image: text)


def test_returns_ocr_result(
    synthetic_screenshot: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_tesseract(monkeypatch, "ARITZIA\nBabaton Cardigan  $89.00")
    result = ocr.read(synthetic_screenshot)
    assert isinstance(result, OcrResult)


def test_finds_known_brand(
    synthetic_screenshot: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_tesseract(monkeypatch, "Welcome to Aritzia. Buy this cardigan now.")
    result = ocr.read(synthetic_screenshot)
    assert result.brand == "Aritzia"


def test_brand_match_is_case_insensitive(
    synthetic_screenshot: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_tesseract(monkeypatch, "madewell.com / Spring 2026")
    result = ocr.read(synthetic_screenshot)
    assert result.brand == "Madewell"


def test_unknown_brand_returns_none(
    synthetic_screenshot: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_tesseract(monkeypatch, "Random text with no retailer name.")
    result = ocr.read(synthetic_screenshot)
    assert result.brand is None


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Price: $89.00", 89.00),
        ("$1,200", 1200.0),
        ("Sale price $45", 45.0),
        ("$  79.99 only", 79.99),
        ("FREE shipping", None),
    ],
)
def test_price_regex(
    synthetic_screenshot: Path,
    monkeypatch: pytest.MonkeyPatch,
    raw: str,
    expected: float | None,
) -> None:
    _stub_tesseract(monkeypatch, raw)
    result = ocr.read(synthetic_screenshot)
    assert result.price_usd == expected


def test_raw_text_is_passed_through(
    synthetic_screenshot: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = "Some scanned text\nspanning two lines."
    _stub_tesseract(monkeypatch, raw)
    result = ocr.read(synthetic_screenshot)
    assert result.raw_text == raw
