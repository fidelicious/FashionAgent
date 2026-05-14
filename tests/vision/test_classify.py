"""
Tests for clawbot.vision.classify.

zero_shot consumes a precomputed image embedding (so we don't pay a
second CLIP forward pass) and a precomputed text-embedding dict from
models.get_text_embeddings. Tests construct fake text embeddings so the
softmax outcomes are predictable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from clawbot.vision import classify, models


@pytest.fixture(autouse=True)
def _reset_models():
    models.release()
    yield
    models.release()


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n else v


def _install_fake_text_embeddings(
    monkeypatch: pytest.MonkeyPatch,
    embeddings: dict[str, np.ndarray],
) -> None:
    monkeypatch.setattr(models, "_compute_text_embeddings", lambda: embeddings)


def test_argmax_picks_closest_category(
    synthetic_top: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Image embedding aligned with the "tops" axis.
    img_emb = _unit(np.array([1.0] + [0.0] * 511, dtype=np.float32))
    _install_fake_text_embeddings(
        monkeypatch,
        {
            "category:tops":      _unit(np.array([1.0] + [0.0] * 511, dtype=np.float32)),
            "category:bottoms":   _unit(np.array([0.0, 1.0] + [0.0] * 510, dtype=np.float32)),
            "category:dresses":   _unit(np.array([0.0, 0.0, 1.0] + [0.0] * 509, dtype=np.float32)),
            "category:outerwear": _unit(np.array([0.0] * 3 + [1.0] + [0.0] * 508, dtype=np.float32)),
            "category:footwear":  _unit(np.array([0.0] * 4 + [1.0] + [0.0] * 507, dtype=np.float32)),
            "category:accessories": _unit(np.array([0.0] * 5 + [1.0] + [0.0] * 506, dtype=np.float32)),
            "category:underlayers": _unit(np.array([0.0] * 6 + [1.0] + [0.0] * 505, dtype=np.float32)),
            "category:activewear":  _unit(np.array([0.0] * 7 + [1.0] + [0.0] * 504, dtype=np.float32)),
            # Add at least one subcategory under tops so the second pass works.
            "subcategory:tops:cardigan": _unit(np.array([1.0] + [0.0] * 511, dtype=np.float32)),
            # Formality and season prompts (all five / four).
            "formality:very-casual":  _unit(np.array([1.0] + [0.0] * 511, dtype=np.float32)),
            "formality:casual":       _unit(np.array([0.0, 1.0] + [0.0] * 510, dtype=np.float32)),
            "formality:smart-casual": _unit(np.array([0.0, 0.0, 1.0] + [0.0] * 509, dtype=np.float32)),
            "formality:business":     _unit(np.array([0.0] * 3 + [1.0] + [0.0] * 508, dtype=np.float32)),
            "formality:formal":       _unit(np.array([0.0] * 4 + [1.0] + [0.0] * 507, dtype=np.float32)),
            "season:spring": _unit(np.array([1.0] + [0.0] * 511, dtype=np.float32)),
            "season:summer": _unit(np.array([0.0, 1.0] + [0.0] * 510, dtype=np.float32)),
            "season:fall":   _unit(np.array([0.0, 0.0, 1.0] + [0.0] * 509, dtype=np.float32)),
            "season:winter": _unit(np.array([0.0] * 3 + [1.0] + [0.0] * 508, dtype=np.float32)),
        },
    )

    result, conf = classify.zero_shot(synthetic_top, embedding=img_emb, threshold=0.0)
    assert result.category == "tops"
    assert conf["category"] > 0.0
    assert set(conf.keys()) == {"category", "subcategory", "formality", "season"}


def test_subcategory_below_threshold_returns_none(
    synthetic_top: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Image aligned with category "tops"; subcategory has only one prompt
    # so softmax probability is 1.0 — we need a tighter threshold test.
    # Build two subcategory prompts with near-equal similarity so the max
    # softmax prob is ~0.5, below a threshold of 0.9.
    img_emb = _unit(np.array([1.0, 1.0] + [0.0] * 510, dtype=np.float32))
    _install_fake_text_embeddings(
        monkeypatch,
        {
            "category:tops":      _unit(np.array([1.0, 1.0] + [0.0] * 510, dtype=np.float32)),
            "category:bottoms":   _unit(np.array([0.0] * 510 + [1.0, 0.0], dtype=np.float32)),
            "category:dresses":   _unit(np.array([0.0] * 510 + [0.0, 1.0], dtype=np.float32)),
            "category:outerwear": _unit(np.array([0.0] * 511 + [1.0], dtype=np.float32)),
            "category:footwear":  _unit(np.array([1.0] + [0.0] * 511, dtype=np.float32)),
            "category:accessories": _unit(np.array([0.0, 1.0] + [0.0] * 510, dtype=np.float32)),
            "category:underlayers": _unit(np.array([0.0, 0.0, 1.0] + [0.0] * 509, dtype=np.float32)),
            "category:activewear":  _unit(np.array([0.0, 0.0, 0.0, 1.0] + [0.0] * 508, dtype=np.float32)),
            "subcategory:tops:t-shirt": _unit(np.array([1.0, 1.0] + [0.0] * 510, dtype=np.float32)),
            "subcategory:tops:sweater": _unit(np.array([1.0, 1.0] + [0.0] * 510, dtype=np.float32)),
            "formality:very-casual":  _unit(np.array([1.0] + [0.0] * 511, dtype=np.float32)),
            "formality:casual":       _unit(np.array([0.0, 1.0] + [0.0] * 510, dtype=np.float32)),
            "formality:smart-casual": _unit(np.array([0.0, 0.0, 1.0] + [0.0] * 509, dtype=np.float32)),
            "formality:business":     _unit(np.array([0.0] * 3 + [1.0] + [0.0] * 508, dtype=np.float32)),
            "formality:formal":       _unit(np.array([0.0] * 4 + [1.0] + [0.0] * 507, dtype=np.float32)),
            "season:spring": _unit(np.array([1.0] + [0.0] * 511, dtype=np.float32)),
            "season:summer": _unit(np.array([0.0, 1.0] + [0.0] * 510, dtype=np.float32)),
            "season:fall":   _unit(np.array([0.0, 0.0, 1.0] + [0.0] * 509, dtype=np.float32)),
            "season:winter": _unit(np.array([0.0] * 3 + [1.0] + [0.0] * 508, dtype=np.float32)),
        },
    )
    result, _ = classify.zero_shot(synthetic_top, embedding=img_emb, threshold=0.9)
    # Two subcategories with identical similarity → softmax max ≈ 0.5 < 0.9
    assert result.subcategory is None


def test_seasons_is_multi_label(
    synthetic_top: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Image aligned with two season axes; both should pass threshold.
    img_emb = _unit(np.array([0.0, 0.0, 1.0, 1.0] + [0.0] * 508, dtype=np.float32))
    _install_fake_text_embeddings(
        monkeypatch,
        {
            "category:tops":      _unit(np.array([1.0] + [0.0] * 511, dtype=np.float32)),
            "category:bottoms":   _unit(np.array([0.0, 1.0] + [0.0] * 510, dtype=np.float32)),
            "category:dresses":   _unit(np.array([0.0, 0.0, 1.0] + [0.0] * 509, dtype=np.float32)),
            "category:outerwear": _unit(np.array([0.0] * 3 + [1.0] + [0.0] * 508, dtype=np.float32)),
            "category:footwear":  _unit(np.array([0.0] * 4 + [1.0] + [0.0] * 507, dtype=np.float32)),
            "category:accessories": _unit(np.array([0.0] * 5 + [1.0] + [0.0] * 506, dtype=np.float32)),
            "category:underlayers": _unit(np.array([0.0] * 6 + [1.0] + [0.0] * 505, dtype=np.float32)),
            "category:activewear":  _unit(np.array([0.0] * 7 + [1.0] + [0.0] * 504, dtype=np.float32)),
            "subcategory:tops:t-shirt": _unit(np.array([1.0] + [0.0] * 511, dtype=np.float32)),
            "formality:very-casual":  _unit(np.array([1.0] + [0.0] * 511, dtype=np.float32)),
            "formality:casual":       _unit(np.array([0.0, 1.0] + [0.0] * 510, dtype=np.float32)),
            "formality:smart-casual": _unit(np.array([0.0, 0.0, 1.0] + [0.0] * 509, dtype=np.float32)),
            "formality:business":     _unit(np.array([0.0] * 3 + [1.0] + [0.0] * 508, dtype=np.float32)),
            "formality:formal":       _unit(np.array([0.0] * 4 + [1.0] + [0.0] * 507, dtype=np.float32)),
            "season:spring": _unit(np.array([1.0] + [0.0] * 511, dtype=np.float32)),
            "season:summer": _unit(np.array([0.0, 1.0] + [0.0] * 510, dtype=np.float32)),
            "season:fall":   _unit(np.array([0.0, 0.0, 1.0] + [0.0] * 509, dtype=np.float32)),
            "season:winter": _unit(np.array([0.0] * 3 + [1.0] + [0.0] * 508, dtype=np.float32)),
        },
    )
    result, _ = classify.zero_shot(synthetic_top, embedding=img_emb, threshold=0.3)
    assert "fall" in result.seasons and "winter" in result.seasons
    assert "spring" not in result.seasons and "summer" not in result.seasons


def test_returns_classification_result_and_confidence_dict(
    synthetic_top: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from clawbot.vision.draft import ClassificationResult

    img_emb = _unit(np.array([1.0] + [0.0] * 511, dtype=np.float32))
    _install_fake_text_embeddings(
        monkeypatch,
        {
            f"category:{c}": _unit(np.array([1.0] + [0.0] * 511, dtype=np.float32))
            for c in (
                "tops", "bottoms", "dresses", "outerwear",
                "footwear", "accessories", "underlayers", "activewear",
            )
        }
        | {
            "subcategory:tops:cardigan": _unit(np.array([1.0] + [0.0] * 511, dtype=np.float32)),
            "formality:very-casual":  _unit(np.array([1.0] + [0.0] * 511, dtype=np.float32)),
            "formality:casual":       _unit(np.array([0.0, 1.0] + [0.0] * 510, dtype=np.float32)),
            "formality:smart-casual": _unit(np.array([0.0, 0.0, 1.0] + [0.0] * 509, dtype=np.float32)),
            "formality:business":     _unit(np.array([0.0] * 3 + [1.0] + [0.0] * 508, dtype=np.float32)),
            "formality:formal":       _unit(np.array([0.0] * 4 + [1.0] + [0.0] * 507, dtype=np.float32)),
            "season:spring": _unit(np.array([1.0] + [0.0] * 511, dtype=np.float32)),
            "season:summer": _unit(np.array([0.0, 1.0] + [0.0] * 510, dtype=np.float32)),
            "season:fall":   _unit(np.array([0.0, 0.0, 1.0] + [0.0] * 509, dtype=np.float32)),
            "season:winter": _unit(np.array([0.0] * 3 + [1.0] + [0.0] * 508, dtype=np.float32)),
        },
    )
    result, conf = classify.zero_shot(synthetic_top, embedding=img_emb, threshold=0.0)
    assert isinstance(result, ClassificationResult)
    assert 0.0 <= conf["category"] <= 1.0
    assert 0.0 <= conf["formality"] <= 1.0
    assert 0.0 <= conf["season"] <= 1.0
