"""
Background removal via rembg.

The orchestrator hands us a raw image path and the config; we open the
image, run it through a cached rembg session, and write the transparent
PNG cutout to ``<images_dir>/cutouts/<stem>.png``.

Heavy import note: ``rembg`` pulls in onnxruntime + numpy. We import it
inside ``_rembg_remove`` so unit tests on a Mac without the [vision]
extras can still collect this module.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

from clawbot.config import ClawbotConfig
from clawbot.vision import models

# Register HEIC/HEIF support when pillow-heif is installed (part of the
# [vision] extra). Without this, iPhone .heic photos raise
# PIL.UnidentifiedImageError at the first Image.open() call.
try:
    import pillow_heif  # type: ignore[import-untyped]
    pillow_heif.register_heif_opener()
except ImportError:
    pass


def remove_background(raw_path: Path, config: ClawbotConfig) -> Path:
    """Remove the background from ``raw_path`` and return the cutout path.

    The cutout is written as PNG (so it can carry transparency) under
    ``<images_dir>/cutouts/<stem>.png``. The parent dir is created if
    it doesn't exist.
    """
    session = models.get_rembg_session(config.image_pipeline.rembg_model)
    cutout_dir = config.paths.images_dir / "cutouts"
    cutout_dir.mkdir(parents=True, exist_ok=True)
    cutout_path = cutout_dir / f"{raw_path.stem}.png"

    with Image.open(raw_path) as img:
        cutout = _rembg_remove(img, session=session)
    cutout.save(cutout_path, "PNG")
    return cutout_path


def _rembg_remove(image: Image.Image, session: Any) -> Image.Image:
    """Thin wrapper around ``rembg.remove`` — exists so tests can monkeypatch.

    The lazy import keeps onnxruntime / rembg out of import time on hosts
    without the [vision] extras installed.
    """
    from rembg import remove

    # rembg is untyped; the override in pyproject silences the import but
    # mypy still sees the return as Any. Cast back to the declared type.
    return remove(image, session=session)  # type: ignore[no-any-return]
