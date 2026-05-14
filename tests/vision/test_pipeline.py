"""
Tests for clawbot.vision.pipeline.

The orchestrator is a thin function: call each stage in order, decide
whether to run OCR, build the DraftItem, and release models. We mock
every stage so the test is fast and deterministic — wiring is the
contract under test.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest

from clawbot.config import (
    ClawbotConfig,
    ImagePipelineConfig,
    PathsConfig,
)
from clawbot.vision import classify, color, cutout, embed, models, ocr, pipeline
from clawbot.vision.draft import ClassificationResult, OcrResult

# Module-level default avoids ruff's B008 warning about constructing dataclasses
# in argument defaults. Safe to share because OcrResult is frozen.
_DEFAULT_OCR = OcrResult("Aritzia", 89.0, "raw")


@pytest.fixture(autouse=True)
def _reset_models() -> Iterator[None]:
    models.release()
    yield
    models.release()


@pytest.fixture
def cfg(tmp_path: Path) -> ClawbotConfig:
    return ClawbotConfig(
        paths=PathsConfig(images_dir=tmp_path / "images"),
        image_pipeline=ImagePipelineConfig(
            lazy_load_models=True,
            ocr_enabled_for_screenshots=True,
            fashion_clip_confidence_threshold=0.55,
        ),
    )


def _wire_stage_mocks(
    monkeypatch: pytest.MonkeyPatch,
    *,
    cutout_path: Path,
    palette: tuple[str, str | None, float] = ("#112233", "#445566", 0.9),
    embedding: np.ndarray | None = None,
    classification: ClassificationResult | None = None,
    cls_conf: dict[str, float] | None = None,
    ocr_result: OcrResult | None = _DEFAULT_OCR,
) -> dict[str, int]:
    """Patch every stage and return a counter dict to assert call counts."""
    """Patch every stage and return a counter dict to assert call counts."""
    calls = {"cutout": 0, "color": 0, "embed": 0, "classify": 0, "ocr": 0, "release": 0}

    if embedding is None:
        embedding = np.zeros(512, dtype=np.float32)
    if classification is None:
        classification = ClassificationResult("tops", "cardigan", "casual", ["fall"])
    if cls_conf is None:
        cls_conf = {"category": 0.9, "subcategory": 0.8, "formality": 0.7, "season": 0.6}

    def fake_cutout(raw_path: Path, config: ClawbotConfig) -> Path:
        calls["cutout"] += 1
        cutout_path.parent.mkdir(parents=True, exist_ok=True)
        cutout_path.write_bytes(b"fake")
        return cutout_path

    def fake_color(p: Path) -> tuple[str, str | None, float]:
        calls["color"] += 1
        return palette

    def fake_embed(p: Path) -> np.ndarray:
        calls["embed"] += 1
        return embedding

    def fake_classify(p: Path, *, embedding: np.ndarray, threshold: float) -> tuple[ClassificationResult, dict[str, float]]:
        calls["classify"] += 1
        return classification, cls_conf

    def fake_ocr(p: Path) -> OcrResult:
        calls["ocr"] += 1
        return ocr_result  # type: ignore[return-value]

    def fake_release() -> None:
        calls["release"] += 1

    monkeypatch.setattr(cutout, "remove_background", fake_cutout)
    monkeypatch.setattr(color, "extract_palette", fake_color)
    monkeypatch.setattr(embed, "compute", fake_embed)
    monkeypatch.setattr(classify, "zero_shot", fake_classify)
    monkeypatch.setattr(ocr, "read", fake_ocr)
    monkeypatch.setattr(models, "release", fake_release)
    return calls


def test_runs_every_stage_for_screenshot(
    cfg: ClawbotConfig,
    synthetic_screenshot: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cutout_path = tmp_path / "images" / "cutouts" / "screenshot.png"
    calls = _wire_stage_mocks(monkeypatch, cutout_path=cutout_path)
    draft = pipeline.ingest_image(synthetic_screenshot, source="screenshot", config=cfg)

    assert calls == {
        "cutout": 1, "color": 1, "embed": 1,
        "classify": 1, "ocr": 1, "release": 1,
    }
    assert draft.image_raw_path == synthetic_screenshot
    assert draft.image_cutout_path == cutout_path
    assert draft.color_primary == "#112233"
    assert draft.color_secondary == "#445566"
    assert draft.ocr is not None and draft.ocr.brand == "Aritzia"
    assert draft.confidence["category"] == 0.9
    assert draft.confidence["color"] == 0.9


def test_ocr_skipped_for_upload(
    cfg: ClawbotConfig,
    synthetic_top: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cutout_path = tmp_path / "images" / "cutouts" / "top.png"
    calls = _wire_stage_mocks(monkeypatch, cutout_path=cutout_path)
    draft = pipeline.ingest_image(synthetic_top, source="upload", config=cfg)

    assert calls["ocr"] == 0
    assert draft.ocr is None


def test_ocr_skipped_for_email(
    cfg: ClawbotConfig,
    synthetic_top: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cutout_path = tmp_path / "images" / "cutouts" / "top.png"
    calls = _wire_stage_mocks(monkeypatch, cutout_path=cutout_path)
    draft = pipeline.ingest_image(synthetic_top, source="email", config=cfg)

    assert calls["ocr"] == 0
    assert draft.ocr is None


def test_ocr_killswitch_disables_even_for_screenshot(
    cfg: ClawbotConfig,
    synthetic_screenshot: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg_off = cfg.model_copy(
        update={
            "image_pipeline": cfg.image_pipeline.model_copy(
                update={"ocr_enabled_for_screenshots": False}
            )
        }
    )
    cutout_path = tmp_path / "images" / "cutouts" / "screenshot.png"
    calls = _wire_stage_mocks(monkeypatch, cutout_path=cutout_path)
    draft = pipeline.ingest_image(
        synthetic_screenshot, source="screenshot", config=cfg_off
    )

    assert calls["ocr"] == 0
    assert draft.ocr is None


def test_release_called_when_lazy_load_true(
    cfg: ClawbotConfig,
    synthetic_top: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cutout_path = tmp_path / "images" / "cutouts" / "top.png"
    calls = _wire_stage_mocks(monkeypatch, cutout_path=cutout_path)
    pipeline.ingest_image(synthetic_top, source="upload", config=cfg)
    assert calls["release"] == 1


def test_release_skipped_when_lazy_load_false(
    cfg: ClawbotConfig,
    synthetic_top: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg_eager = cfg.model_copy(
        update={
            "image_pipeline": cfg.image_pipeline.model_copy(
                update={"lazy_load_models": False}
            )
        }
    )
    cutout_path = tmp_path / "images" / "cutouts" / "top.png"
    calls = _wire_stage_mocks(monkeypatch, cutout_path=cutout_path)
    pipeline.ingest_image(synthetic_top, source="upload", config=cfg_eager)
    assert calls["release"] == 0


def test_release_called_even_on_stage_failure(
    cfg: ClawbotConfig,
    synthetic_top: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If a stage raises, release() must still fire (try/finally)."""
    calls = {"release": 0}

    def boom(raw_path: Path, config: ClawbotConfig) -> Path:
        raise RuntimeError("rembg blew up")

    monkeypatch.setattr(cutout, "remove_background", boom)
    monkeypatch.setattr(models, "release", lambda: calls.__setitem__("release", calls["release"] + 1))

    with pytest.raises(RuntimeError, match="rembg blew up"):
        pipeline.ingest_image(synthetic_top, source="upload", config=cfg)
    assert calls["release"] == 1


def test_invalid_source_raises(
    cfg: ClawbotConfig, synthetic_top: Path
) -> None:
    with pytest.raises(ValueError, match="source"):
        pipeline.ingest_image(
            synthetic_top,
            source="bogus",  # type: ignore[arg-type]
            config=cfg,
        )
