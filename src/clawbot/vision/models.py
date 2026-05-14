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
    """Load Fashion-CLIP weights. Replaced with the real impl in Task 11."""
    raise NotImplementedError(
        "Fashion-CLIP loader not wired yet — pending Task 11. "
        "Monkeypatch this function in unit tests."
    )


def _new_rembg_session(model_name: str) -> Any:
    """Construct a rembg Session. Replaced with the real impl in Task 11."""
    raise NotImplementedError(
        "rembg session loader not wired yet — pending Task 11. "
        "Monkeypatch this function in unit tests."
    )


def _compute_text_embeddings() -> dict[str, Any]:
    """Compute and cache text-prompt embeddings. Replaced in Task 11."""
    raise NotImplementedError(
        "Text-embedding computer not wired yet — pending Task 11. "
        "Monkeypatch this function in unit tests."
    )
