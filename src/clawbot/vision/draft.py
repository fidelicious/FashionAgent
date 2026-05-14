"""
Pure-data return types for the image pipeline.

DraftItem is what ingest_image() returns. It mirrors the subset of
wardrobe_items columns we can infer from pixels, plus per-attribute
confidence so callers (Discord approval flow) can decorate uncertain
fields. Persistence and final-thumbnail generation happen elsewhere.

All dataclasses are frozen + slots:
    - frozen: lets us hash and rely on value identity in tests; prevents
      stages from mutating each other's outputs.
    - slots: cheaper attribute access and catches typos at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True, slots=True)
class ClassificationResult:
    """Zero-shot attribute outputs from Fashion-CLIP.

    ``subcategory`` is None when the per-class confidence falls below
    ``image_pipeline.fashion_clip_confidence_threshold`` — we'd rather
    return no guess than a wrong one. ``seasons`` is multi-label.
    """

    category: str
    subcategory: str | None
    formality: str
    seasons: list[str]


@dataclass(frozen=True, slots=True)
class OcrResult:
    """Tesseract output, regex-extracted into structured fields.

    ``raw_text`` is kept so we can tune the brand / price regexes later
    without re-OCRing.
    """

    brand: str | None
    price_usd: float | None
    raw_text: str


@dataclass(frozen=True, slots=True)
class DraftItem:
    """The pipeline's complete output for one input image.

    Fields the user must provide (size, fit, notes, purchase metadata)
    are deliberately absent — they're filled in at approval time, not
    here. The final 512-px thumbnail is also deferred until approval.
    """

    image_raw_path: Path
    image_cutout_path: Path
    color_primary: str  # "#RRGGBB"
    color_secondary: str | None
    classification: ClassificationResult
    ocr: OcrResult | None  # None when source != "screenshot"
    embedding: np.ndarray  # shape (512,), dtype float32
    confidence: dict[str, float]
    # confidence keys: "category", "subcategory", "formality", "season", "color"
