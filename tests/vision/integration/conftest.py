"""
Integration-tier conftest.

Tests in this directory load the real Fashion-CLIP weights (~600 MB)
and rembg's u2netp. They auto-skip on hosts without the [vision]
extras installed.

Run on the NUC:
    pytest -m integration tests/vision/integration -v
"""

from __future__ import annotations

# Detect [vision] extras; skip the whole subtree if missing.
try:
    from transformers import CLIPModel  # noqa: F401
    import pytesseract  # noqa: F401
    import rembg  # noqa: F401
    import torch  # noqa: F401
    _vision_available = True
except ImportError:
    _vision_available = False

collect_ignore_glob: list[str] = [] if _vision_available else ["test_*.py"]
