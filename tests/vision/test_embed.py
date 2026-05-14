"""
Tests for clawbot.vision.embed.

compute() calls get_clip() and runs a forward pass to return a 512-dim
float32 image embedding. The CLIP model is monkeypatched; the test
asserts on output shape, dtype, and that the model is invoked with the
opened cutout image.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from clawbot.vision import embed, models


@pytest.fixture(autouse=True)
def _reset_models():
    models.release()
    yield
    models.release()


def _install_fake_clip(monkeypatch: pytest.MonkeyPatch, vec: np.ndarray) -> dict[str, int]:
    """Install a fake (model, processor) that returns ``vec`` from compute."""
    calls = {"encode": 0}

    class FakeProcessor:
        def __call__(self, images: object, return_tensors: str = "pt") -> dict[str, object]:
            return {"pixel_values": object()}

    class FakeModel:
        def encode_image(self, pixel_values: object) -> np.ndarray:
            calls["encode"] += 1
            return vec.reshape(1, -1)

    monkeypatch.setattr(
        models, "_load_fashion_clip", lambda: (FakeModel(), FakeProcessor())
    )
    return calls


def test_returns_float32_512_vector(
    synthetic_top: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vec = np.arange(512, dtype=np.float32)
    _install_fake_clip(monkeypatch, vec)

    out = embed.compute(synthetic_top)
    assert isinstance(out, np.ndarray)
    assert out.shape == (512,)
    assert out.dtype == np.float32


def test_normalizes_to_unit_length(
    synthetic_top: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vec = np.ones(512, dtype=np.float32) * 3.0  # raw length 3*sqrt(512)
    _install_fake_clip(monkeypatch, vec)

    out = embed.compute(synthetic_top)
    assert pytest.approx(np.linalg.norm(out), rel=1e-5) == 1.0


def test_calls_clip_exactly_once(
    synthetic_top: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _install_fake_clip(monkeypatch, np.zeros(512, dtype=np.float32) + 1)
    embed.compute(synthetic_top)
    assert calls["encode"] == 1
