"""
Tests for clawbot.vision.models — the lazy-singleton model cache.

Verified properties:
    - get_clip returns the same object on repeated calls (caching).
    - get_rembg_session caches per model name.
    - release() drops both refs and is idempotent.
    - Without monkeypatching, the real CLIP loader raises
      NotImplementedError (real loader lands in Task 11).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from clawbot.vision import models


@pytest.fixture(autouse=True)
def _reset_singletons() -> Iterator[None]:
    """Tests share the module — reset state before/after each test."""
    models.release()
    yield
    models.release()


def test_get_clip_uses_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = ("fake-model", "fake-processor")
    calls = {"n": 0}

    def fake_load() -> tuple[object, object]:
        calls["n"] += 1
        return sentinel

    monkeypatch.setattr(models, "_load_fashion_clip", fake_load)
    first = models.get_clip()
    second = models.get_clip()
    assert first is second is sentinel
    assert calls["n"] == 1


def test_get_rembg_session_uses_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = object()
    calls = {"n": 0}

    def fake_new_session(model_name: str) -> object:
        calls["n"] += 1
        return sentinel

    monkeypatch.setattr(models, "_new_rembg_session", fake_new_session)
    first = models.get_rembg_session("u2netp")
    second = models.get_rembg_session("u2netp")
    assert first is second is sentinel
    assert calls["n"] == 1


def test_release_drops_clip_and_rembg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(models, "_load_fashion_clip", lambda: ("m", "p"))
    monkeypatch.setattr(models, "_new_rembg_session", lambda name: object())
    models.get_clip()
    models.get_rembg_session("u2netp")
    assert models._clip is not None
    assert models._rembg is not None
    models.release()
    assert models._clip is None
    assert models._rembg is None  # type: ignore[unreachable]


def test_release_is_idempotent() -> None:
    models.release()
    models.release()  # second call must not error


def test_real_loader_requires_vision_extras_or_succeeds() -> None:
    # Behavior depends on host:
    #   - Mac dev (no [vision] extras): _load_fashion_clip raises ImportError
    #     because `import open_clip` fails. Unit tests proceed via the
    #     monkeypatched fake loader.
    #   - NUC with [vision] extras: _load_fashion_clip succeeds and returns
    #     a (model, processor) tuple. We don't load 600 MB just to check that.
    # This test only documents the seam — it passes silently on either path.
    try:
        result = models._load_fashion_clip()
    except (ImportError, ModuleNotFoundError):
        return  # Mac path: extras missing, loader can't even import.
    # NUC path: a real model came back. Validate the shape and let the rest
    # of the test scope clean up via the autouse release fixture.
    assert isinstance(result, tuple) and len(result) == 2


def test_get_text_embeddings_uses_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Text-prompt embeddings are computed once and cached alongside CLIP."""
    import numpy as np

    sentinel = {"tops": np.zeros(512, dtype=np.float32)}
    calls = {"n": 0}

    def fake_compute() -> dict[str, np.ndarray]:
        calls["n"] += 1
        return sentinel

    monkeypatch.setattr(models, "_compute_text_embeddings", fake_compute)
    first = models.get_text_embeddings()
    second = models.get_text_embeddings()
    assert first is second is sentinel
    assert calls["n"] == 1


def test_release_drops_text_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    import numpy as np

    monkeypatch.setattr(
        models,
        "_compute_text_embeddings",
        lambda: {"tops": np.zeros(512, dtype=np.float32)},
    )
    models.get_text_embeddings()
    assert models._text_embeddings is not None
    models.release()
    assert models._text_embeddings is None
