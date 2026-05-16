"""
Lazy-singleton cache for heavy ML models.

Two policies meet here:
    1. Models are loaded on first use (cold-start cost is paid once).
    2. ``release()`` drops references and forces GC, called by the
       orchestrator after each ingest when image_pipeline.lazy_load_models
       is true.

This module is the *only* place that imports torch / open_clip / rembg.
Stage modules call ``get_clip()`` / ``get_rembg_session()`` and treat the
return values opaquely. That keeps all heavy imports gated behind a
single seam that unit tests monkeypatch.

Thread-safety: the pipeline runs inside a single image worker, so we do
not lock. If multi-worker becomes a thing, wrap the cache reads with a
threading.Lock here.
"""

from __future__ import annotations

import gc
from typing import Any

# Cache state. ``Any`` keeps unit tests free of torch / rembg imports.
_clip: tuple[Any, Any] | None = None
_rembg: Any | None = None
_text_embeddings: dict[str, Any] | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Public getters
# ─────────────────────────────────────────────────────────────────────────────


def get_clip() -> tuple[Any, Any]:
    """Return ``(model, processor)`` for Fashion-CLIP, loading on first call."""
    global _clip
    if _clip is None:
        _clip = _load_fashion_clip()
    return _clip


def get_rembg_session(model_name: str) -> Any:
    """Return a cached rembg Session for ``model_name``, loading on first call.

    The cache is keyed by *the first* model name passed in; switching
    models requires a ``release()`` first. We don't expect mid-process
    switching in V1 (the model is set in config).
    """
    global _rembg
    if _rembg is None:
        _rembg = _new_rembg_session(model_name)
    return _rembg


def get_text_embeddings() -> dict[str, Any]:
    """Return cached text-prompt embeddings keyed by prompt label.

    The dict's keys span every CATEGORY_PROMPTS / FORMALITY_PROMPTS /
    SEASON_PROMPTS / SUBCATEGORY_PROMPTS entry, prefixed with their
    attribute (e.g., ``"category:tops"``). Values are float32 ndarrays
    of shape (512,).
    """
    global _text_embeddings
    if _text_embeddings is None:
        _text_embeddings = _compute_text_embeddings()
    return _text_embeddings


def release() -> None:
    """Drop all cached models and force GC. Idempotent."""
    global _clip, _rembg, _text_embeddings
    _clip = None
    _rembg = None
    _text_embeddings = None
    gc.collect()


# ─────────────────────────────────────────────────────────────────────────────
# Internals — overridden by Task 11 with real torch + open_clip + rembg calls
# ─────────────────────────────────────────────────────────────────────────────


def _load_fashion_clip() -> tuple[Any, Any]:
    """Load Fashion-CLIP weights into RAM (~600 MB).

    patrickjohncyh/fashion-clip is stored in the HuggingFace Transformers
    format (config.json + model.safetensors), not the open_clip format.
    We load it via the ``transformers`` library accordingly. The model is
    moved to CPU — the NUC has no GPU.
    """
    from transformers import CLIPModel, CLIPProcessor

    model = CLIPModel.from_pretrained("patrickjohncyh/fashion-clip")
    model.eval()
    model.to("cpu")
    processor = CLIPProcessor.from_pretrained("patrickjohncyh/fashion-clip")
    return model, processor


def _new_rembg_session(model_name: str) -> Any:
    """Construct a rembg Session for the named model (e.g. ``u2netp``)."""
    import rembg

    return rembg.new_session(model_name)


def _compute_text_embeddings() -> dict[str, Any]:
    """Encode every taxonomy prompt and return a key→ndarray dict.

    Keys are namespaced: ``category:<name>``, ``subcategory:<cat>:<name>``,
    ``formality:<name>``, ``season:<name>``. Values are unit-normalized
    float32 ndarrays of shape (512,).

    Called once per pipeline run (or once per session when
    ``lazy_load_models`` is false). The cost is small relative to the
    image forward pass.
    """
    import numpy as np
    import torch

    from clawbot.vision.taxonomy import (
        CATEGORY_PROMPTS,
        FORMALITY_PROMPTS,
        SEASON_PROMPTS,
        SUBCATEGORY_PROMPTS,
    )

    model, processor = get_clip()

    # Build a flat (key, prompt) list so we tokenise/encode in one batch.
    items: list[tuple[str, str]] = []
    items.extend((f"category:{k}", v) for k, v in CATEGORY_PROMPTS.items())
    for cat, subs in SUBCATEGORY_PROMPTS.items():
        items.extend((f"subcategory:{cat}:{name}", p) for name, p in subs.items())
    items.extend((f"formality:{k}", v) for k, v in FORMALITY_PROMPTS.items())
    items.extend((f"season:{k}", v) for k, v in SEASON_PROMPTS.items())

    keys = [k for k, _ in items]
    prompts = [p for _, p in items]

    with torch.no_grad():
        # processor handles tokenisation, padding, and truncation.
        text_inputs = processor(
            text=prompts,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=77,
        )
        text_inputs = {k: v.to("cpu") for k, v in text_inputs.items()}
        # get_text_features() returns a ModelOutput wrapper (not a plain
        # tensor) in some transformers versions.  Go through text_model +
        # text_projection directly — same pattern as the image path.
        if hasattr(model, "text_model") and hasattr(model, "text_projection"):
            text_out = model.text_model(
                input_ids=text_inputs.get("input_ids"),
                attention_mask=text_inputs.get("attention_mask"),
            )
            # text_out[1] is pooler_output (CLS representation).
            pooled = text_out[1]
            raw = model.text_projection(pooled)
        else:
            raw = model.get_text_features(**text_inputs)
            if not isinstance(raw, torch.Tensor):
                raw = raw[1] if hasattr(raw, "__getitem__") else raw.pooler_output
        embs = raw.detach().cpu().numpy().astype(np.float32)
    # L2-normalize each row.
    norms = np.linalg.norm(embs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    embs = embs / norms

    return {k: embs[i] for i, k in enumerate(keys)}



