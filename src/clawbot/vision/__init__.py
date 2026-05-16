"""
clawbot.vision — offline image-ingestion pipeline.

Public API:
    ingest_image(raw_path, *, source, config) -> DraftItem

DraftItem and its sub-records (ClassificationResult, OcrResult) are
re-exported so callers don't need to know which stage produced them.
"""

from clawbot.vision.draft import ClassificationResult, DraftItem, OcrResult
from clawbot.vision.pipeline import ingest_image

__all__ = [
    "ClassificationResult",
    "DraftItem",
    "OcrResult",
    "ingest_image",
]
