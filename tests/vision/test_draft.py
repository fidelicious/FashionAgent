"""
Tests for clawbot.vision.draft dataclasses.

The DraftItem and its sub-records are the pipeline's pure return type.
Tests cover:
    - Field presence and types.
    - Dataclass invariants: frozen (immutable after construction), slots.
    - Confidence dict contains the documented keys.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import numpy as np
import pytest

from clawbot.vision.draft import (
    ClassificationResult,
    DraftItem,
    OcrResult,
)


def _make_draft(**overrides: object) -> DraftItem:
    """Build a DraftItem with sensible defaults; overrides as kwargs."""
    base = {
        "image_raw_path": Path("/tmp/raw.jpg"),
        "image_cutout_path": Path("/tmp/cutout.png"),
        "color_primary": "#112233",
        "color_secondary": "#445566",
        "classification": ClassificationResult(
            category="tops",
            subcategory="cardigan",
            formality="smart-casual",
            seasons=("fall", "winter"),
        ),
        "ocr": None,
        "embedding": np.zeros((512,), dtype=np.float32),
        "confidence": {
            "category": 0.9,
            "subcategory": 0.7,
            "formality": 0.8,
            "season": 0.6,
            "color": 0.95,
        },
    }
    base.update(overrides)
    return DraftItem(**base)  # type: ignore[arg-type]


def test_draft_item_is_frozen() -> None:
    draft = _make_draft()
    with pytest.raises(FrozenInstanceError):
        draft.color_primary = "#000000"  # type: ignore[misc]


def test_draft_item_uses_slots() -> None:
    # We can't trigger AttributeError via assignment because frozen=True
    # makes ANY __setattr__ raise FrozenInstanceError first. Instead, verify
    # slots are active by introspection: __slots__ is populated and the
    # instance has no __dict__ to absorb stray attributes.
    draft = _make_draft()
    assert hasattr(DraftItem, "__slots__")
    assert "image_raw_path" in DraftItem.__slots__
    assert not hasattr(draft, "__dict__")


def test_classification_result_is_frozen() -> None:
    cls = ClassificationResult(
        category="tops",
        subcategory=None,
        formality="casual",
        seasons=("spring",),
    )
    with pytest.raises(FrozenInstanceError):
        cls.category = "bottoms"  # type: ignore[misc]


def test_classification_result_seasons_is_immutable() -> None:
    cls = ClassificationResult(
        category="tops",
        subcategory=None,
        formality="casual",
        seasons=("spring", "fall"),
    )
    # tuple has no append/extend — type checker would catch this too.
    with pytest.raises(AttributeError):
        cls.seasons.append("winter")  # type: ignore[attr-defined]


def test_ocr_result_is_frozen() -> None:
    ocr = OcrResult(brand="Aritzia", price_usd=89.0, raw_text="ARITZIA $89")
    with pytest.raises(FrozenInstanceError):
        ocr.brand = "Madewell"  # type: ignore[misc]


def test_embedding_shape_and_dtype() -> None:
    draft = _make_draft()
    assert draft.embedding.shape == (512,)
    assert draft.embedding.dtype == np.float32


def test_confidence_has_all_documented_keys() -> None:
    draft = _make_draft()
    assert set(draft.confidence.keys()) == {
        "category",
        "subcategory",
        "formality",
        "season",
        "color",
    }


def test_subcategory_can_be_none() -> None:
    draft = _make_draft(
        classification=ClassificationResult(
            category="tops",
            subcategory=None,
            formality="casual",
            seasons=("spring",),
        ),
    )
    assert draft.classification.subcategory is None


def test_ocr_can_be_none() -> None:
    draft = _make_draft(ocr=None)
    assert draft.ocr is None


def test_color_secondary_can_be_none() -> None:
    draft = _make_draft(color_secondary=None)
    assert draft.color_secondary is None
