"""
Tests for clawbot.vision.cutout.

The rembg session is opaque (monkeypatched via models). cutout.remove_background
opens the raw image with PIL, calls rembg.remove(image, session=...),
and saves the result. Tests assert on path conventions and side effects;
the actual model is exercised by the integration tier.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from clawbot.config import ClawbotConfig, ImagePipelineConfig, PathsConfig
from clawbot.vision import cutout, models


@pytest.fixture(autouse=True)
def _reset_models():
    models.release()
    yield
    models.release()


@pytest.fixture
def cfg(tmp_path: Path) -> ClawbotConfig:
    paths = PathsConfig(images_dir=tmp_path / "images")
    pipeline = ImagePipelineConfig(rembg_model="u2netp")
    return ClawbotConfig(paths=paths, image_pipeline=pipeline)


def test_cutout_path_is_under_images_dir_cutouts(
    cfg: ClawbotConfig, synthetic_top: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sentinel_session = object()
    monkeypatch.setattr(models, "_new_rembg_session", lambda name: sentinel_session)

    def fake_remove(image: object, session: object) -> Image.Image:
        # Real rembg returns an RGBA image; we hand back a tiny stand-in.
        assert session is sentinel_session
        return Image.new("RGBA", (32, 32), (255, 0, 0, 128))

    monkeypatch.setattr(cutout, "_rembg_remove", fake_remove)
    out = cutout.remove_background(synthetic_top, cfg)

    assert out == cfg.paths.images_dir / "cutouts" / "top.png"
    assert out.exists()


def test_cutout_directory_is_created(
    cfg: ClawbotConfig, synthetic_top: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(models, "_new_rembg_session", lambda name: object())
    monkeypatch.setattr(
        cutout,
        "_rembg_remove",
        lambda image, session: Image.new("RGBA", (32, 32), (0, 0, 0, 0)),
    )

    assert not (cfg.paths.images_dir / "cutouts").exists()
    cutout.remove_background(synthetic_top, cfg)
    assert (cfg.paths.images_dir / "cutouts").is_dir()


def test_output_is_png_with_transparency(
    cfg: ClawbotConfig, synthetic_top: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(models, "_new_rembg_session", lambda name: object())
    monkeypatch.setattr(
        cutout,
        "_rembg_remove",
        lambda image, session: Image.new("RGBA", (32, 32), (0, 255, 0, 200)),
    )
    out = cutout.remove_background(synthetic_top, cfg)

    with Image.open(out) as img:
        assert img.format == "PNG"
        assert img.mode == "RGBA"


def test_uses_configured_rembg_model(
    cfg: ClawbotConfig, synthetic_top: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, str] = {}

    def fake_new_session(model_name: str) -> object:
        seen["model"] = model_name
        return object()

    monkeypatch.setattr(models, "_new_rembg_session", fake_new_session)
    monkeypatch.setattr(
        cutout,
        "_rembg_remove",
        lambda image, session: Image.new("RGBA", (32, 32), (0, 0, 0, 0)),
    )

    cutout.remove_background(synthetic_top, cfg)
    assert seen["model"] == "u2netp"
