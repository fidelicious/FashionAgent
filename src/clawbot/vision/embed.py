"""
Fashion-CLIP image embeddings.

``compute(cutout_path)`` opens the cutout, runs it through the cached
Fashion-CLIP model, and returns a unit-normalized 512-dim float32 vector.
Normalization makes downstream cosine similarity a plain dot product.

The model interface is duck-typed: ``model.encode_image(pixel_values)``
returns a 2-D array of shape ``(1, 512)``. The processor is called with
keyword ``return_tensors="pt"`` to mirror the HuggingFace open_clip API.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from clawbot.vision import models

_EMBEDDING_DIM = 512


def compute(cutout_path: Path) -> np.ndarray:
    """Return a unit-normalized 512-dim float32 image embedding."""
    model, processor = models.get_clip()
    with Image.open(cutout_path) as img:
        # The processor returns a dict with at least "pixel_values".
        inputs = processor(images=img, return_tensors="pt")
        raw = model.encode_image(inputs["pixel_values"])

    # Convert whatever we got (torch tensor or ndarray) to a flat ndarray.
    vec = np.asarray(raw, dtype=np.float32).reshape(-1)
    if vec.shape != (_EMBEDDING_DIM,):
        raise ValueError(
            f"Expected {_EMBEDDING_DIM}-d embedding, got shape {vec.shape}"
        )
    norm = float(np.linalg.norm(vec))
    if norm > 0:
        vec = vec / norm
    return vec.astype(np.float32, copy=False)
