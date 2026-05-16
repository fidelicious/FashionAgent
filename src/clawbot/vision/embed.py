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
    """Run the vision encoder under torch.no_grad when torch is around.

    Lazy import so this module collects on hosts without [vision] extras.
    Tests monkeypatch ``get_clip`` to return a fake model that only
    implements ``get_image_features`` — the real path goes through
    ``vision_model + visual_projection`` to avoid the ambiguity of
    ``get_image_features`` returning a ModelOutput object instead of a
    plain tensor in some transformers versions.
    """
    try:
        import torch
    except ImportError:
        # No torch installed (unit-test tier on Mac); fake model returns ndarray.
        return model.get_image_features(pixel_values=pixel_values)  # type: ignore[attr-defined]

    with torch.no_grad():
        # Prefer the explicit two-step path when the model exposes the
        # underlying vision encoder and projection layer directly.
        # This avoids get_image_features() returning a ModelOutput wrapper
        # (instead of a plain tensor) in certain transformers versions.
        if hasattr(model, "vision_model") and hasattr(model, "visual_projection"):
            vision_out = model.vision_model(pixel_values=pixel_values)  # type: ignore[attr-defined]
            # vision_out[1] is pooler_output — the CLS-token representation
            # (e.g. 768-d for ViT-B/32) before the projection head.
            pooled = vision_out[1]
            return model.visual_projection(pooled)  # type: ignore[attr-defined]

        # Fallback for test fakes that only implement get_image_features.
        result = model.get_image_features(pixel_values=pixel_values)  # type: ignore[attr-defined]
        if isinstance(result, torch.Tensor):
            return result
        # ModelOutput: return the first 2-D float tensor found in the tuple.
        to_check = result.to_tuple() if hasattr(result, "to_tuple") else (result[0], result[1])
        for val in to_check:
            if isinstance(val, torch.Tensor) and val.dim() == 2 and val.is_floating_point():
                return val
        raise RuntimeError(f"Cannot extract image features from {type(result)}")
