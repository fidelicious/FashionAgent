"""
Zero-shot attribute classification against Fashion-CLIP text prompts.

The image is already encoded as a 512-d unit vector by ``embed.compute``.
For each attribute group (category / formality / season / per-category
subcategory) we cosine-sim the image vector against every prompt in
that group, softmax → argmax (or per-label threshold for season).

Text embeddings are precomputed once and cached by ``models.get_text_embeddings``
under keys of the form ``"category:tops"``, ``"subcategory:tops:cardigan"``,
``"formality:business"``, ``"season:winter"``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from clawbot.vision import models
from clawbot.vision.draft import ClassificationResult


def zero_shot(
    cutout_path: Path,
    *,
    embedding: np.ndarray,
    threshold: float,
) -> tuple[ClassificationResult, dict[str, float]]:
    """Run zero-shot classification given a precomputed image embedding.

    Parameters
    ----------
    cutout_path
        Kept on the signature so future implementations could re-open the
        image (e.g., for multi-crop ensembling); not used by V1.
    embedding
        Unit-normalized 512-d float32 vector from ``embed.compute``.
    threshold
        Per-attribute confidence threshold. Subcategory below threshold
        becomes ``None``. Seasons are multi-label: every label passing
        threshold is included.

    Returns
    -------
    (ClassificationResult, confidence_dict)
        ``confidence_dict`` has keys ``"category"``, ``"subcategory"``,
        ``"formality"``, ``"season"`` — values in ``[0.0, 1.0]``.
    """
    text_embs = models.get_text_embeddings()

    # Category: argmax across category:* prompts.
    cat_scores = _group_probs(embedding, text_embs, prefix="category:")
    category, cat_conf = _argmax(cat_scores)

    # Subcategory: argmax across subcategory:<category>:* prompts.
    sub_prefix = f"subcategory:{category}:"
    sub_scores = _group_probs(embedding, text_embs, prefix=sub_prefix)
    if sub_scores:
        subcategory, sub_conf = _argmax(sub_scores)
        if sub_conf < threshold:
            subcategory = None  # type: ignore[assignment]
    else:
        subcategory, sub_conf = None, 0.0

    # Formality: argmax across formality:* prompts.
    formality_scores = _group_probs(embedding, text_embs, prefix="formality:")
    formality, formality_conf = _argmax(formality_scores)

    # Season: multi-label — every prompt above threshold passes.
    season_scores = _group_probs(embedding, text_embs, prefix="season:")
    seasons = [name for name, p in season_scores.items() if p >= threshold]
    season_conf = (
        float(np.mean([season_scores[s] for s in seasons])) if seasons else 0.0
    )

    return (
        ClassificationResult(
            category=category,
            subcategory=subcategory,
            formality=formality,
            seasons=sorted(seasons),
        ),
        {
            "category": cat_conf,
            "subcategory": sub_conf,
            "formality": formality_conf,
            "season": season_conf,
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# Math helpers
# ─────────────────────────────────────────────────────────────────────────────


def _group_probs(
    image_emb: np.ndarray,
    text_embs: dict[str, np.ndarray],
    *,
    prefix: str,
) -> dict[str, float]:
    """Softmax over cosine-similarities for every text emb starting with ``prefix``."""
    keys = [k for k in text_embs if k.startswith(prefix)]
    if not keys:
        return {}
    sims = np.array([float(np.dot(image_emb, text_embs[k])) for k in keys], dtype=np.float64)
    # Stable softmax.
    sims = sims - sims.max()
    exp = np.exp(sims)
    probs = exp / exp.sum()
    return {k[len(prefix):]: float(p) for k, p in zip(keys, probs, strict=True)}


def _argmax(scores: dict[str, float]) -> tuple[str, float]:
    best_key, best_prob = max(scores.items(), key=lambda kv: kv[1])
    return best_key, best_prob
