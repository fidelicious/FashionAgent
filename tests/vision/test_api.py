"""
Tests for the public surface of clawbot.vision.

Only ``ingest_image`` and the three dataclasses should be importable
from the package root. Everything else is private (the stage modules
remain reachable as ``clawbot.vision.<stage>`` for callers that need
them, but are not re-exported through __init__).
"""

from __future__ import annotations


def test_public_api_exports() -> None:
    import clawbot.vision as v

    # Required public names.
    assert hasattr(v, "ingest_image")
    assert hasattr(v, "DraftItem")
    assert hasattr(v, "ClassificationResult")
    assert hasattr(v, "OcrResult")


def test_dunder_all_is_explicit() -> None:
    import clawbot.vision as v

    assert v.__all__ == [
        "ClassificationResult",
        "DraftItem",
        "OcrResult",
        "ingest_image",
    ]
