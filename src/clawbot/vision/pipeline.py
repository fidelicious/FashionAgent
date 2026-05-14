"""
Image-ingestion orchestrator.

Pure top-down function: input image path + source flag → DraftItem.
Each stage's failure propagates; ``release()`` always fires when
``lazy_load_models`` is true, even on stage error.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, get_args

from clawbot.config import ClawbotConfig
from clawbot.vision import classify, color, cutout, embed, models, ocr
from clawbot.vision.draft import DraftItem

Source = Literal["upload", "screenshot", "email"]
_VALID_SOURCES = frozenset(get_args(Source))


def ingest_image(
    raw_path: Path,
    *,
    source: Source,
    config: ClawbotConfig,
) -> DraftItem:
    """Run the full image pipeline on ``raw_path`` and return a ``DraftItem``.

    No DB writes, no Discord I/O. ``release()`` is called in a ``finally``
    block when ``image_pipeline.lazy_load_models`` is true so that a
    failed ingest still drops the ~600 MB of CLIP weights.
    """
    if source not in _VALID_SOURCES:
        raise ValueError(
            f"source must be one of {sorted(_VALID_SOURCES)}, got {source!r}"
        )

    try:
        cutout_path = cutout.remove_background(raw_path, config)
        primary, secondary, color_conf = color.extract_palette(cutout_path)
        embedding = embed.compute(cutout_path)
        cls_result, cls_conf = classify.zero_shot(
            cutout_path,
            embedding=embedding,
            threshold=config.image_pipeline.fashion_clip_confidence_threshold,
        )
        should_ocr = (
            source == "screenshot"
            and config.image_pipeline.ocr_enabled_for_screenshots
        )
        ocr_result = ocr.read(raw_path) if should_ocr else None

        return DraftItem(
            image_raw_path=raw_path,
            image_cutout_path=cutout_path,
            color_primary=primary,
            color_secondary=secondary,
            classification=cls_result,
            ocr=ocr_result,
            embedding=embedding,
            confidence={"color": color_conf, **cls_conf},
        )
    finally:
        if config.image_pipeline.lazy_load_models:
            models.release()
