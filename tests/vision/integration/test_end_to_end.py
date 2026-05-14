"""
End-to-end integration tests for the image pipeline.

Synthetic images give no real signal about classification quality —
these tests assert STRUCTURAL correctness only: shapes, dtypes, value
ranges, presence/absence of OCR. Semantic accuracy is a manual QA pass
on real photos during Step 6/7 build.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from clawbot.config import ClawbotConfig, ImagePipelineConfig, PathsConfig
from clawbot.vision import DraftItem, ingest_image

# Belt-and-suspenders skip guard. The directory-level conftest.py already
# sets collect_ignore_glob when [vision] extras are missing, but that
# mechanism is fragile if the conftest itself ever gains a non-gated
# import. This pytestmark keeps the suite robust to that failure.
try:
    import torch  # noqa: F401
    _vision_available = True
except ImportError:
    _vision_available = False

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _vision_available,
        reason="[vision] extras not installed",
    ),
]

CATEGORIES = {
    "tops", "bottoms", "dresses", "outerwear",
    "footwear", "accessories", "underlayers", "activewear",
}
FORMALITY = {
    "very-casual", "casual", "smart-casual", "business", "formal",
}


@pytest.fixture
def cfg(tmp_path: Path) -> ClawbotConfig:
    return ClawbotConfig(
        paths=PathsConfig(images_dir=tmp_path / "images"),
        image_pipeline=ImagePipelineConfig(
            lazy_load_models=True,
            ocr_enabled_for_screenshots=True,
            fashion_clip_confidence_threshold=0.10,  # generous on synthetic
            rembg_model="u2netp",
        ),
    )


def _assert_structural_valid(draft: DraftItem) -> None:
    assert draft.image_cutout_path.exists()
    assert draft.image_cutout_path.suffix == ".png"
    assert draft.color_primary.startswith("#") and len(draft.color_primary) == 7
    assert draft.embedding.shape == (512,)
    assert draft.embedding.dtype == np.float32
    assert pytest.approx(np.linalg.norm(draft.embedding), rel=1e-4) == 1.0
    assert draft.classification.category in CATEGORIES
    assert draft.classification.formality in FORMALITY
    assert set(draft.confidence.keys()) == {
        "category", "subcategory", "formality", "season", "color",
    }
    for k, v in draft.confidence.items():
        assert 0.0 <= v <= 1.0, f"{k}: {v}"


def test_ingest_upload_structurally_valid(
    cfg: ClawbotConfig, synthetic_top: Path
) -> None:
    draft = ingest_image(synthetic_top, source="upload", config=cfg)
    _assert_structural_valid(draft)
    assert draft.ocr is None


def test_ingest_email_structurally_valid(
    cfg: ClawbotConfig, synthetic_top: Path
) -> None:
    draft = ingest_image(synthetic_top, source="email", config=cfg)
    _assert_structural_valid(draft)
    assert draft.ocr is None


def test_ingest_screenshot_runs_ocr(
    cfg: ClawbotConfig, synthetic_screenshot: Path
) -> None:
    draft = ingest_image(synthetic_screenshot, source="screenshot", config=cfg)
    _assert_structural_valid(draft)
    assert draft.ocr is not None
    # raw_text content depends on tesseract version; just check it's not empty.
    assert isinstance(draft.ocr.raw_text, str)
