"""
Fashion-CLIP image embeddings.

``compute(cutout_path)`` opens the cutout, runs it through the cached
Fashion-CLIP model, and returns a unit-normalized 512-dim float32 vector.
Normalization makes downstream cosine similarity a plain dot product.

The model interface is duck-typed: ``model.get_image_features(pixel_values=pixel_values)``
returns a 2-D array of shape ``(1, 512)``. The processor is called with
keyword ``return_tensors="pt"`` matching the HuggingFace Transformers API.
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
        # torch.no_grad disables autograd bookkeeping. model.eval() is not
        # enough — without this, every encode_image call retains a graph
        # roughly doubling RAM during a forward pass. Critical on the NUC
        # where the 8 GB budget has no headroom for gradient tensors.
        raw = _encode_no_grad(model, inputs["pixel_values"])

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


def _encode_no_grad(model: object, pixel_values: object) -> object:
    """Run the model's encode under torch.no_grad when torch is around.

    Lazy import so this module collects on hosts without [vision] extras.
    Tests monkeypatch ``get_clip`` to return a fake model with a plain
    ``get_image_features`` — the fake returns ndarray directly.

    ``CLIPModel.get_image_features`` should return a tensor, but some model
    configurations and transformers versions return a ``BaseModelOutputWithPooling``
    instead.  When that happens we apply ``model.visual_projection`` manually
    to the pooler_output to get the same 512-d projected features.
    """
    try:
        import torch
    except ImportError:
        # No torch installed (unit-test tier on Mac); fake model returns ndarray.
        return model.get_image_features(pixel_values=pixel_values)  # type: ignore[attr-defined]

    with torch.no_grad():
        result = model.get_image_features(pixel_values=pixel_values)  # type: ignore[attr-defined]
        if isinstance(result, torch.Tensor):
            return result
        # BaseModelOutputWithPooling or similar ModelOutput: project manually.
        pooler = getattr(result, "pooler_output", None)
        if pooler is None:
            # Fall back to indexing (index 1 = pooler_output in standard outputs).
            pooler = result[1]  # type: ignore[index]
        return model.visual_projection(pooler)  # type: ignore[attr-defined]
