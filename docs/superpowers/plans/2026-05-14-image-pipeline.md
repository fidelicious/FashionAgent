# Image Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the offline image-ingestion pipeline (build Step 5) so a raw image path + source flag → `DraftItem` dataclass containing cutout path, color palette, Fashion-CLIP embedding, zero-shot classification, optional OCR, and per-attribute confidence. No DB writes, no Discord I/O.

**Architecture:** Linear functional pipeline. Each stage is a pure-function module under `src/clawbot/vision/`. A `models.py` holds lazy singletons for Fashion-CLIP and rembg; the orchestrator releases them after each ingest when `image_pipeline.lazy_load_models` is true. Heavy imports (torch, rembg, pytesseract) live inside function bodies so the unit-test tier can run on a Mac without `[vision]` extras installed.

**Tech Stack:** Python 3.12, pydantic v2 (already wired), rembg + open-clip-torch + pytesseract + colorthief + Pillow + numpy, pytest with `integration` marker (already declared in `pyproject.toml`).

**Spec:** [`docs/superpowers/specs/2026-05-14-image-pipeline-design.md`](../specs/2026-05-14-image-pipeline-design.md)

---

## Task 0: Branch + lightweight dev deps

We need numpy / Pillow / colorthief available in the default `pytest` run so unit tests on the Mac can construct synthetic images and fake embeddings. The heavy `[vision]` extras (torch, rembg, open-clip-torch, pytesseract) stay opt-in for the NUC.

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Create the Step-5 feature branch off `feat/foundation`**

```bash
git checkout feat/foundation
git checkout -b feat/image-pipeline
```

Expected: `Switched to a new branch 'feat/image-pipeline'`

- [ ] **Step 2: Add numpy / Pillow / colorthief to the `[dev]` extra**

Open `pyproject.toml`. Find the `dev = [` block (around line 63). Replace it with:

```toml
# Dev tooling — pytest, linters, formatters.
dev = [
    "pytest>=8.1,<9",
    "pytest-asyncio>=0.23",
    "pytest-cov>=5.0",
    "hypothesis>=6.100",          # Property tests for the outfit scorer (step 10)
    "ruff>=0.4",
    "mypy>=1.10",
    "pre-commit>=3.7",
    # Unit-test deps for the vision package. The heavy stages (rembg, torch,
    # pytesseract) live in the [vision] extra and are mocked in unit tests,
    # but synthetic-image fixtures and fake-embedding arrays still need these.
    "numpy>=1.26",
    "Pillow>=10.3",
    "colorthief>=0.2.1",
]
```

- [ ] **Step 3: Install the updated dev extras into your venv**

Run: `pip install -e ".[dev]"`
Expected: numpy / Pillow / colorthief installed without error. `pytest --collect-only` still finds the existing tests.

- [ ] **Step 4: Verify the existing test suite still passes**

Run: `pytest -q`
Expected: All existing tests pass (zero new tests yet).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml
git commit -m "build: add numpy/Pillow/colorthief to [dev] for vision unit tests"
```

---

## Task 1: `DraftItem` dataclass

The pure-data return type of the pipeline. Three frozen dataclasses with slots.

**Files:**
- Create: `src/clawbot/vision/__init__.py` (empty package marker for now)
- Create: `src/clawbot/vision/draft.py`
- Create: `tests/vision/__init__.py`
- Create: `tests/vision/test_draft.py`

- [ ] **Step 1: Create empty package markers**

Run:
```bash
mkdir -p src/clawbot/vision tests/vision
touch src/clawbot/vision/__init__.py tests/vision/__init__.py
```

- [ ] **Step 2: Write the failing tests in `tests/vision/test_draft.py`**

```python
"""
Tests for clawbot.vision.draft dataclasses.

The DraftItem and its sub-records are the pipeline's pure return type.
Tests cover:
    - Field presence and types.
    - Dataclass invariants: frozen (immutable after construction), slots.
    - Confidence dict contains the documented keys.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import numpy as np
import pytest

from clawbot.vision.draft import (
    ClassificationResult,
    DraftItem,
    OcrResult,
)


def _make_draft(**overrides: object) -> DraftItem:
    """Build a DraftItem with sensible defaults; overrides as kwargs."""
    base = {
        "image_raw_path": Path("/tmp/raw.jpg"),
        "image_cutout_path": Path("/tmp/cutout.png"),
        "color_primary": "#112233",
        "color_secondary": "#445566",
        "classification": ClassificationResult(
            category="tops",
            subcategory="cardigan",
            formality="smart-casual",
            seasons=["fall", "winter"],
        ),
        "ocr": None,
        "embedding": np.zeros((512,), dtype=np.float32),
        "confidence": {
            "category": 0.9,
            "subcategory": 0.7,
            "formality": 0.8,
            "season": 0.6,
            "color": 0.95,
        },
    }
    base.update(overrides)
    return DraftItem(**base)  # type: ignore[arg-type]


def test_draft_item_is_frozen() -> None:
    draft = _make_draft()
    with pytest.raises(FrozenInstanceError):
        draft.color_primary = "#000000"  # type: ignore[misc]


def test_draft_item_uses_slots() -> None:
    draft = _make_draft()
    # Slots prevent ad-hoc attribute creation.
    with pytest.raises(AttributeError):
        draft.surprise = "value"  # type: ignore[attr-defined]


def test_classification_result_is_frozen() -> None:
    cls = ClassificationResult(
        category="tops",
        subcategory=None,
        formality="casual",
        seasons=["spring"],
    )
    with pytest.raises(FrozenInstanceError):
        cls.category = "bottoms"  # type: ignore[misc]


def test_ocr_result_is_frozen() -> None:
    ocr = OcrResult(brand="Aritzia", price_usd=89.0, raw_text="ARITZIA $89")
    with pytest.raises(FrozenInstanceError):
        ocr.brand = "Madewell"  # type: ignore[misc]


def test_embedding_shape_and_dtype() -> None:
    draft = _make_draft()
    assert draft.embedding.shape == (512,)
    assert draft.embedding.dtype == np.float32


def test_confidence_has_all_documented_keys() -> None:
    draft = _make_draft()
    assert set(draft.confidence.keys()) == {
        "category",
        "subcategory",
        "formality",
        "season",
        "color",
    }


def test_subcategory_can_be_none() -> None:
    draft = _make_draft(
        classification=ClassificationResult(
            category="tops",
            subcategory=None,
            formality="casual",
            seasons=["spring"],
        ),
    )
    assert draft.classification.subcategory is None


def test_ocr_can_be_none() -> None:
    draft = _make_draft(ocr=None)
    assert draft.ocr is None


def test_color_secondary_can_be_none() -> None:
    draft = _make_draft(color_secondary=None)
    assert draft.color_secondary is None
```

- [ ] **Step 3: Run the failing test**

Run: `pytest tests/vision/test_draft.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'clawbot.vision.draft'`.

- [ ] **Step 4: Implement `src/clawbot/vision/draft.py`**

```python
"""
Pure-data return types for the image pipeline.

DraftItem is what ingest_image() returns. It mirrors the subset of
wardrobe_items columns we can infer from pixels, plus per-attribute
confidence so callers (Discord approval flow) can decorate uncertain
fields. Persistence and final-thumbnail generation happen elsewhere.

All dataclasses are frozen + slots:
    - frozen: lets us hash and rely on value identity in tests; prevents
      stages from mutating each other's outputs.
    - slots: cheaper attribute access and catches typos at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True, slots=True)
class ClassificationResult:
    """Zero-shot attribute outputs from Fashion-CLIP.

    ``subcategory`` is None when the per-class confidence falls below
    ``image_pipeline.fashion_clip_confidence_threshold`` — we'd rather
    return no guess than a wrong one. ``seasons`` is multi-label.
    """

    category: str
    subcategory: str | None
    formality: str
    seasons: list[str]


@dataclass(frozen=True, slots=True)
class OcrResult:
    """Tesseract output, regex-extracted into structured fields.

    ``raw_text`` is kept so we can tune the brand / price regexes later
    without re-OCRing.
    """

    brand: str | None
    price_usd: float | None
    raw_text: str


@dataclass(frozen=True, slots=True)
class DraftItem:
    """The pipeline's complete output for one input image.

    Fields the user must provide (size, fit, notes, purchase metadata)
    are deliberately absent — they're filled in at approval time, not
    here. The final 512-px thumbnail is also deferred until approval.
    """

    image_raw_path: Path
    image_cutout_path: Path
    color_primary: str  # "#RRGGBB"
    color_secondary: str | None
    classification: ClassificationResult
    ocr: OcrResult | None  # None when source != "screenshot"
    embedding: np.ndarray  # shape (512,), dtype float32
    confidence: dict[str, float]
    # confidence keys: "category", "subcategory", "formality", "season", "color"
```

- [ ] **Step 5: Run tests, expect pass**

Run: `pytest tests/vision/test_draft.py -v`
Expected: all 9 tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/clawbot/vision/__init__.py src/clawbot/vision/draft.py \
        tests/vision/__init__.py tests/vision/test_draft.py
git commit -m "feat(vision): DraftItem dataclasses for image pipeline output"
```

---

## Task 2: Zero-shot taxonomy

Constants only — the text prompts Fashion-CLIP compares image embeddings against. Sourced from the locked taxonomy in the V1 plan.

**Files:**
- Create: `src/clawbot/vision/taxonomy.py`
- Create: `tests/vision/test_taxonomy.py`

- [ ] **Step 1: Write the failing tests in `tests/vision/test_taxonomy.py`**

```python
"""
Tests for clawbot.vision.taxonomy.

Constants only — these checks ensure the taxonomy matches the project plan
(every category in the schema has a prompt; every category has a
non-empty subcategory dict; formality and season prompts cover the
documented enums).
"""

from __future__ import annotations

from clawbot.vision.taxonomy import (
    CATEGORY_PROMPTS,
    FORMALITY_PROMPTS,
    SEASON_PROMPTS,
    SUBCATEGORY_PROMPTS,
)

# Locked from fashionClaw.md + the build plan. Update both if you change this.
EXPECTED_CATEGORIES = {
    "tops",
    "bottoms",
    "dresses",
    "outerwear",
    "footwear",
    "accessories",
    "underlayers",
    "activewear",
}

EXPECTED_FORMALITY = {
    "very-casual",
    "casual",
    "smart-casual",
    "business",
    "formal",
}

EXPECTED_SEASONS = {"spring", "summer", "fall", "winter"}


def test_category_prompts_cover_all_categories() -> None:
    assert set(CATEGORY_PROMPTS.keys()) == EXPECTED_CATEGORIES


def test_formality_prompts_cover_all_levels() -> None:
    assert set(FORMALITY_PROMPTS.keys()) == EXPECTED_FORMALITY


def test_season_prompts_cover_all_seasons() -> None:
    assert set(SEASON_PROMPTS.keys()) == EXPECTED_SEASONS


def test_all_prompts_are_nonempty_strings() -> None:
    for d in (CATEGORY_PROMPTS, FORMALITY_PROMPTS, SEASON_PROMPTS):
        for k, v in d.items():
            assert isinstance(v, str), f"{k!r} prompt is not a string"
            assert v.strip(), f"{k!r} prompt is empty"


def test_subcategory_dict_has_one_entry_per_category() -> None:
    assert set(SUBCATEGORY_PROMPTS.keys()) == EXPECTED_CATEGORIES


def test_each_subcategory_dict_is_nonempty() -> None:
    for category, subs in SUBCATEGORY_PROMPTS.items():
        assert subs, f"category {category!r} has no subcategory prompts"
        for sub_name, prompt in subs.items():
            assert isinstance(prompt, str) and prompt.strip(), (
                f"{category}.{sub_name} prompt is empty"
            )


def test_known_subcategories_present() -> None:
    # Sanity-check a handful of subcategories named in the V1 plan.
    assert "cardigan" in SUBCATEGORY_PROMPTS["tops"]
    assert "jeans" in SUBCATEGORY_PROMPTS["bottoms"]
    assert "ankle-boot" in SUBCATEGORY_PROMPTS["footwear"]
    assert "blazer" in SUBCATEGORY_PROMPTS["outerwear"]
```

- [ ] **Step 2: Run the failing test**

Run: `pytest tests/vision/test_taxonomy.py -v`
Expected: `ModuleNotFoundError: No module named 'clawbot.vision.taxonomy'`.

- [ ] **Step 3: Implement `src/clawbot/vision/taxonomy.py`**

```python
"""
Text prompts for Fashion-CLIP zero-shot classification.

Constants only. Phrases are short, descriptive, and avoid overlapping
vocabulary across categories so the model has a clean distance signal.

Update the canonical taxonomy in ``fashionClaw.md`` if you add a category
here, and bump the corresponding tests in tests/vision/test_taxonomy.py.
"""

from __future__ import annotations

CATEGORY_PROMPTS: dict[str, str] = {
    "tops":        "a photo of a shirt, top, or sweater",
    "bottoms":     "a photo of pants, jeans, or a skirt",
    "dresses":     "a photo of a dress or jumpsuit",
    "outerwear":   "a photo of a jacket, coat, or blazer",
    "footwear":    "a photo of shoes or boots",
    "accessories": "a photo of a bag, belt, hat, or jewelry",
    "underlayers": "a photo of underwear, tights, or a base layer",
    "activewear":  "a photo of athletic or workout clothing",
}

FORMALITY_PROMPTS: dict[str, str] = {
    "very-casual":  "very casual loungewear or pajamas",
    "casual":       "casual everyday clothing",
    "smart-casual": "smart casual office-friendly clothing",
    "business":     "business or professional attire",
    "formal":       "formal evening wear or a suit",
}

SEASON_PROMPTS: dict[str, str] = {
    "spring": "lightweight clothing for spring weather",
    "summer": "lightweight clothing for hot summer weather",
    "fall":   "layered clothing for cool fall weather",
    "winter": "heavy clothing for cold winter weather",
}

# Per-category subcategory prompts. Picked up by classify.zero_shot only
# after the top-level category is decided, so the search space stays small.
SUBCATEGORY_PROMPTS: dict[str, dict[str, str]] = {
    "tops": {
        "t-shirt":    "a plain t-shirt",
        "tank":       "a tank top or sleeveless shirt",
        "blouse":     "a blouse",
        "button-down": "a button-down shirt",
        "sweater":    "a sweater or pullover",
        "cardigan":   "a cardigan",
        "turtleneck": "a turtleneck",
        "polo":       "a polo shirt",
        "henley":     "a henley shirt",
        "sweatshirt": "a sweatshirt",
        "hoodie":     "a hoodie",
        "crop-top":   "a crop top",
        "bodysuit":   "a bodysuit",
    },
    "bottoms": {
        "jeans":      "blue jeans",
        "trousers":   "dress trousers",
        "chinos":     "chinos or khaki pants",
        "leggings":   "leggings",
        "shorts":     "shorts",
        "mini-skirt": "a mini skirt",
        "midi-skirt": "a midi skirt",
        "maxi-skirt": "a maxi skirt",
        "culottes":   "culottes",
    },
    "dresses": {
        "mini-dress":  "a mini dress",
        "midi-dress":  "a midi dress",
        "maxi-dress":  "a maxi dress",
        "jumpsuit":    "a jumpsuit",
        "romper":      "a romper",
    },
    "outerwear": {
        "cardigan":       "a heavy cardigan worn as outerwear",
        "blazer":         "a blazer",
        "denim-jacket":   "a denim jacket",
        "leather-jacket": "a leather jacket",
        "coat":           "a long coat",
        "parka":          "a parka",
        "vest":           "a vest",
        "trench":         "a trench coat",
        "puffer":         "a puffer jacket",
    },
    "footwear": {
        "sneakers":    "sneakers",
        "loafers":     "loafers",
        "ankle-boot":  "ankle boots",
        "knee-boot":   "knee-high boots",
        "heels":       "high heels",
        "flats":       "ballet flats",
        "sandals":     "sandals",
        "mules":       "mules",
        "slides":      "slides",
    },
    "accessories": {
        "belt":       "a belt",
        "handbag":    "a handbag",
        "tote":       "a tote bag",
        "crossbody":  "a crossbody bag",
        "scarf":      "a scarf",
        "hat":        "a hat",
        "jewelry":    "jewelry",
        "sunglasses": "sunglasses",
        "watch":      "a wristwatch",
    },
    "underlayers": {
        "bra":        "a bra",
        "slip":       "a slip",
        "base-layer": "a base layer or thermal",
        "tights":     "tights",
        "socks":      "socks",
    },
    "activewear": {
        "sports-bra": "a sports bra",
        "leggings":   "athletic leggings",
        "shorts":     "athletic shorts",
        "top":        "an athletic top",
    },
}
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest tests/vision/test_taxonomy.py -v`
Expected: all 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/clawbot/vision/taxonomy.py tests/vision/test_taxonomy.py
git commit -m "feat(vision): zero-shot text-prompt taxonomy"
```

---

## Task 3: Synthetic-image fixtures + `color` module

Build a shared `tests/vision/conftest.py` with synthetic PIL fixtures, then implement `color.py` (uses real colorthief).

**Files:**
- Create: `tests/vision/conftest.py`
- Create: `src/clawbot/vision/color.py`
- Create: `tests/vision/test_color.py`

- [ ] **Step 1: Write shared synthetic-image fixtures**

Create `tests/vision/conftest.py`:

```python
"""
Shared fixtures for vision-package unit tests.

All fixtures are tiny synthetic images generated at test time — no binary
files committed to the repo. They exercise plumbing, not model accuracy;
semantic correctness is validated manually on real photos during Step 7.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw


def _save_solid(tmp_path: Path, name: str, color: tuple[int, int, int]) -> Path:
    """Write a 256x256 solid-color PNG to tmp_path and return its path."""
    path = tmp_path / name
    Image.new("RGB", (256, 256), color=color).save(path, "PNG")
    return path


@pytest.fixture
def synthetic_top(tmp_path: Path) -> Path:
    """Navy-blue flat: stands in for an upload photo of a top."""
    return _save_solid(tmp_path, "top.png", (20, 30, 80))


@pytest.fixture
def synthetic_bottoms(tmp_path: Path) -> Path:
    """Khaki-tan flat: stands in for an upload photo of pants."""
    return _save_solid(tmp_path, "bottoms.png", (180, 160, 110))


@pytest.fixture
def synthetic_dress(tmp_path: Path) -> Path:
    """Burgundy flat: stands in for an upload photo of a dress."""
    return _save_solid(tmp_path, "dress.png", (130, 30, 60))


@pytest.fixture
def synthetic_footwear(tmp_path: Path) -> Path:
    """Black flat: stands in for an upload photo of shoes."""
    return _save_solid(tmp_path, "shoes.png", (15, 15, 15))


@pytest.fixture
def synthetic_screenshot(tmp_path: Path) -> Path:
    """White canvas with retailer-like text rendered into it.

    Tesseract is mocked in unit tests so the actual rendering doesn't
    need to be perfectly readable — it just needs to *be* a valid PNG
    with a known stem. The drawn text matches the strings that the OCR
    mock will return.
    """
    path = tmp_path / "screenshot.png"
    img = Image.new("RGB", (512, 256), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    # Default PIL font is fine; we don't OCR this for real in unit tests.
    draw.text((20, 80), "ARITZIA", fill=(0, 0, 0))
    draw.text((20, 130), "Babaton Cardigan  $89.00", fill=(0, 0, 0))
    img.save(path, "PNG")
    return path
```

- [ ] **Step 2: Write the failing tests in `tests/vision/test_color.py`**

```python
"""
Tests for clawbot.vision.color.

extract_palette wraps colorthief. Tests run on synthetic solid-color
images so the expected output is predictable.
"""

from __future__ import annotations

from pathlib import Path

from clawbot.vision.color import extract_palette


def _approx_color(actual: str, expected: tuple[int, int, int], tol: int = 30) -> None:
    """Assert two #RRGGBB strings are within ``tol`` per channel.

    Colorthief k-means is non-deterministic on tiny inputs, so we allow
    a generous tolerance.
    """
    assert actual.startswith("#") and len(actual) == 7
    r, g, b = int(actual[1:3], 16), int(actual[3:5], 16), int(actual[5:7], 16)
    er, eg, eb = expected
    assert abs(r - er) <= tol, f"R: got {r}, expected ~{er}"
    assert abs(g - eg) <= tol, f"G: got {g}, expected ~{eg}"
    assert abs(b - eb) <= tol, f"B: got {b}, expected ~{eb}"


def test_returns_tuple_of_primary_secondary_confidence(synthetic_top: Path) -> None:
    result = extract_palette(synthetic_top)
    assert isinstance(result, tuple)
    assert len(result) == 3
    primary, secondary, confidence = result
    assert primary.startswith("#")
    assert secondary is None or secondary.startswith("#")
    assert 0.0 <= confidence <= 1.0


def test_primary_color_matches_synthetic(synthetic_top: Path) -> None:
    primary, _, _ = extract_palette(synthetic_top)
    # synthetic_top is solid (20, 30, 80) — navy.
    _approx_color(primary, (20, 30, 80))


def test_solid_image_has_no_secondary(synthetic_footwear: Path) -> None:
    """A pure-black image yields one dominant color; secondary should be None."""
    _, secondary, _ = extract_palette(synthetic_footwear)
    assert secondary is None


def test_hex_format_is_uppercase_six_digits(synthetic_dress: Path) -> None:
    primary, _, _ = extract_palette(synthetic_dress)
    assert primary[0] == "#"
    assert len(primary) == 7
    # All hex digits, uppercase canonical form.
    assert primary[1:].isalnum()
    assert primary == primary.upper()
```

- [ ] **Step 3: Run the failing test**

Run: `pytest tests/vision/test_color.py -v`
Expected: `ModuleNotFoundError: No module named 'clawbot.vision.color'`.

- [ ] **Step 4: Implement `src/clawbot/vision/color.py`**

```python
"""
Color-palette extraction for cutout images.

Wraps colorthief.ColorThief. Runs on the rembg cutout so the palette is
not polluted by the original photo's background. Returns the top color
as ``color_primary``; the second is ``color_secondary`` unless it's
within a perceptual distance of the primary, in which case we treat the
item as single-color.
"""

from __future__ import annotations

import math
from pathlib import Path

# colorthief is in the [dev] extras, so safe to import at module level
# alongside Pillow. Heavy ML deps live inside function bodies elsewhere.
from colorthief import ColorThief

# Two colors within this Euclidean distance in RGB space are treated as
# the same color. Tuned empirically: ~30 catches near-identical shades
# while letting genuine two-tone garments register a secondary.
_SECONDARY_DISTANCE_THRESHOLD = 30.0

# Maximum perceptual distance (sqrt(3) * 255 ≈ 441) used to normalize the
# heuristic confidence score into [0, 1].
_MAX_RGB_DISTANCE = math.sqrt(3) * 255.0


def extract_palette(cutout_path: Path) -> tuple[str, str | None, float]:
    """Extract primary + optional secondary color from a cutout image.

    Parameters
    ----------
    cutout_path
        PNG path produced by ``cutout.remove_background``. Transparency
        is ignored by colorthief; only opaque pixels contribute.

    Returns
    -------
    (primary_hex, secondary_hex_or_None, confidence)
        Confidence is a heuristic in [0, 1]: how distinct the primary is
        from the average of the palette tail. 1.0 = strong single hue.
    """
    thief = ColorThief(str(cutout_path))
    palette = thief.get_palette(color_count=3, quality=10)
    primary_rgb = palette[0]

    secondary_rgb: tuple[int, int, int] | None = None
    if len(palette) > 1:
        candidate = palette[1]
        if _rgb_distance(primary_rgb, candidate) > _SECONDARY_DISTANCE_THRESHOLD:
            secondary_rgb = candidate

    # Confidence: distance from primary to the mean of the tail, normalized.
    tail = palette[1:] if len(palette) > 1 else [primary_rgb]
    mean_tail = (
        sum(c[0] for c in tail) / len(tail),
        sum(c[1] for c in tail) / len(tail),
        sum(c[2] for c in tail) / len(tail),
    )
    distance = _rgb_distance(primary_rgb, mean_tail)
    confidence = 1.0 - min(1.0, distance / _MAX_RGB_DISTANCE)

    return _hex(primary_rgb), _hex(secondary_rgb) if secondary_rgb else None, confidence


def _rgb_distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def _hex(rgb: tuple[int, int, int]) -> str:
    return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"
```

- [ ] **Step 5: Run tests, expect pass**

Run: `pytest tests/vision/test_color.py -v`
Expected: all 4 tests pass.

- [ ] **Step 6: Commit**

```bash
git add tests/vision/conftest.py src/clawbot/vision/color.py tests/vision/test_color.py
git commit -m "feat(vision): color-palette extraction via colorthief"
```

---

## Task 4: `models.py` lazy singletons

The model cache. `_load_fashion_clip()` raises `NotImplementedError` for now — the real loader lands in Task 11, after all unit-tested stages are in place. Unit tests of stages that use models monkeypatch the getters directly.

**Files:**
- Create: `src/clawbot/vision/models.py`
- Create: `tests/vision/test_models.py`

- [ ] **Step 1: Write the failing tests in `tests/vision/test_models.py`**

```python
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

import pytest

from clawbot.vision import models


@pytest.fixture(autouse=True)
def _reset_singletons():
    """Tests share the module — reset state before/after each test."""
    models.release()
    yield
    models.release()


def test_get_clip_uses_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = ("fake-model", "fake-processor")
    calls = {"n": 0}

    def fake_load() -> tuple[object, object]:
        calls["n"] += 1
        return sentinel  # type: ignore[return-value]

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
    assert models._rembg is None


def test_release_is_idempotent() -> None:
    models.release()
    models.release()  # second call must not error


def test_real_loader_not_implemented_yet() -> None:
    # Until Task 11 lands, calling the real loader must signal clearly.
    with pytest.raises(NotImplementedError):
        models._load_fashion_clip()


def test_get_text_embeddings_uses_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Text-prompt embeddings are computed once and cached alongside CLIP."""
    import numpy as np

    sentinel = {"tops": np.zeros(512, dtype=np.float32)}
    calls = {"n": 0}

    def fake_compute() -> dict[str, "np.ndarray"]:
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
```

- [ ] **Step 2: Run the failing test**

Run: `pytest tests/vision/test_models.py -v`
Expected: `ImportError: cannot import name 'models'` or similar.

- [ ] **Step 3: Implement `src/clawbot/vision/models.py`**

```python
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
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest tests/vision/test_models.py -v`
Expected: all 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/clawbot/vision/models.py tests/vision/test_models.py
git commit -m "feat(vision): lazy-singleton model cache (loaders deferred)"
```

---

## Task 5: `cutout.py` — background removal

Calls `models.get_rembg_session()` to get a cached session, then runs `session.remove()` on the input image. Output is a transparent PNG at `<images_dir>/cutouts/<stem>.png`.

**Files:**
- Create: `src/clawbot/vision/cutout.py`
- Create: `tests/vision/test_cutout.py`

- [ ] **Step 1: Write the failing tests in `tests/vision/test_cutout.py`**

```python
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
```

- [ ] **Step 2: Run the failing test**

Run: `pytest tests/vision/test_cutout.py -v`
Expected: `ModuleNotFoundError: No module named 'clawbot.vision.cutout'`.

- [ ] **Step 3: Implement `src/clawbot/vision/cutout.py`**

```python
"""
Background removal via rembg.

The orchestrator hands us a raw image path and the config; we open the
image, run it through a cached rembg session, and write the transparent
PNG cutout to ``<images_dir>/cutouts/<stem>.png``.

Heavy import note: ``rembg`` pulls in onnxruntime + numpy. We import it
inside ``_rembg_remove`` so unit tests on a Mac without the [vision]
extras can still collect this module.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

from clawbot.config import ClawbotConfig
from clawbot.vision import models


def remove_background(raw_path: Path, config: ClawbotConfig) -> Path:
    """Remove the background from ``raw_path`` and return the cutout path.

    The cutout is written as PNG (so it can carry transparency) under
    ``<images_dir>/cutouts/<stem>.png``. The parent dir is created if
    it doesn't exist.
    """
    session = models.get_rembg_session(config.image_pipeline.rembg_model)
    cutout_dir = config.paths.images_dir / "cutouts"
    cutout_dir.mkdir(parents=True, exist_ok=True)
    cutout_path = cutout_dir / f"{raw_path.stem}.png"

    with Image.open(raw_path) as img:
        cutout = _rembg_remove(img, session=session)
    cutout.save(cutout_path, "PNG")
    return cutout_path


def _rembg_remove(image: Image.Image, session: Any) -> Image.Image:
    """Thin wrapper around ``rembg.remove`` — exists so tests can monkeypatch.

    The lazy import keeps onnxruntime / rembg out of import time on hosts
    without the [vision] extras installed.
    """
    from rembg import remove  # noqa: PLC0415 — intentional lazy import

    return remove(image, session=session)
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest tests/vision/test_cutout.py -v`
Expected: all 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/clawbot/vision/cutout.py tests/vision/test_cutout.py
git commit -m "feat(vision): rembg cutout stage with model-cache integration"
```

---

## Task 6: `embed.py` — Fashion-CLIP image embedding

**Files:**
- Create: `src/clawbot/vision/embed.py`
- Create: `tests/vision/test_embed.py`

- [ ] **Step 1: Write the failing tests in `tests/vision/test_embed.py`**

```python
"""
Tests for clawbot.vision.embed.

compute() calls get_clip() and runs a forward pass to return a 512-dim
float32 image embedding. The CLIP model is monkeypatched; the test
asserts on output shape, dtype, and that the model is invoked with the
opened cutout image.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

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
```

- [ ] **Step 2: Run the failing test**

Run: `pytest tests/vision/test_embed.py -v`
Expected: `ModuleNotFoundError: No module named 'clawbot.vision.embed'`.

- [ ] **Step 3: Implement `src/clawbot/vision/embed.py`**

```python
"""
Fashion-CLIP image embeddings.

``compute(cutout_path)`` opens the cutout, runs it through the cached
Fashion-CLIP model, and returns a unit-normalized 512-dim float32 vector.
Normalization makes downstream cosine similarity a plain dot product.

The model interface is duck-typed: ``model.encode_image(pixel_values)``
returns a 2-D array of shape ``(1, 512)``. The processor is called with
keyword ``return_tensors="pt"`` to mirror the HuggingFace open_clip API.
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
        raw = model.encode_image(inputs["pixel_values"])

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
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest tests/vision/test_embed.py -v`
Expected: all 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/clawbot/vision/embed.py tests/vision/test_embed.py
git commit -m "feat(vision): Fashion-CLIP image embedding with L2 normalization"
```

---

## Task 7: `classify.py` — zero-shot attribute classification

Uses the precomputed text embeddings from `models.get_text_embeddings()`. Categorical attributes (`category`, `subcategory`, `formality`) use softmax over their prompt group → argmax. Seasons is multi-label: threshold each independently.

**Files:**
- Create: `src/clawbot/vision/classify.py`
- Create: `tests/vision/test_classify.py`

- [ ] **Step 1: Write the failing tests in `tests/vision/test_classify.py`**

```python
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
```

- [ ] **Step 2: Run the failing test**

Run: `pytest tests/vision/test_classify.py -v`
Expected: `ModuleNotFoundError: No module named 'clawbot.vision.classify'`.

- [ ] **Step 3: Implement `src/clawbot/vision/classify.py`**

```python
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
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest tests/vision/test_classify.py -v`
Expected: all 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/clawbot/vision/classify.py tests/vision/test_classify.py
git commit -m "feat(vision): zero-shot attribute classification with thresholding"
```

---

## Task 8: `ocr.py` — Tesseract + regex extraction

**Files:**
- Create: `src/clawbot/vision/ocr.py`
- Create: `tests/vision/test_ocr.py`

- [ ] **Step 1: Write the failing tests in `tests/vision/test_ocr.py`**

```python
"""
Tests for clawbot.vision.ocr.

Tesseract is monkeypatched. Tests cover brand-list matching, price regex
on common formats, and the raw_text round-trip.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from clawbot.vision import ocr
from clawbot.vision.draft import OcrResult


def _stub_tesseract(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    monkeypatch.setattr(ocr, "_tesseract_image_to_string", lambda image: text)


def test_returns_ocr_result(
    synthetic_screenshot: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_tesseract(monkeypatch, "ARITZIA\nBabaton Cardigan  $89.00")
    result = ocr.read(synthetic_screenshot)
    assert isinstance(result, OcrResult)


def test_finds_known_brand(
    synthetic_screenshot: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_tesseract(monkeypatch, "Welcome to Aritzia. Buy this cardigan now.")
    result = ocr.read(synthetic_screenshot)
    assert result.brand == "Aritzia"


def test_brand_match_is_case_insensitive(
    synthetic_screenshot: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_tesseract(monkeypatch, "madewell.com / Spring 2026")
    result = ocr.read(synthetic_screenshot)
    assert result.brand == "Madewell"


def test_unknown_brand_returns_none(
    synthetic_screenshot: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_tesseract(monkeypatch, "Random text with no retailer name.")
    result = ocr.read(synthetic_screenshot)
    assert result.brand is None


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Price: $89.00", 89.00),
        ("$1,200", 1200.0),
        ("Sale price $45", 45.0),
        ("$  79.99 only", 79.99),
        ("FREE shipping", None),
    ],
)
def test_price_regex(
    synthetic_screenshot: Path,
    monkeypatch: pytest.MonkeyPatch,
    raw: str,
    expected: float | None,
) -> None:
    _stub_tesseract(monkeypatch, raw)
    result = ocr.read(synthetic_screenshot)
    assert result.price_usd == expected


def test_raw_text_is_passed_through(
    synthetic_screenshot: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = "Some scanned text\nspanning two lines."
    _stub_tesseract(monkeypatch, raw)
    result = ocr.read(synthetic_screenshot)
    assert result.raw_text == raw
```

- [ ] **Step 2: Run the failing test**

Run: `pytest tests/vision/test_ocr.py -v`
Expected: `ModuleNotFoundError: No module named 'clawbot.vision.ocr'`.

- [ ] **Step 3: Implement `src/clawbot/vision/ocr.py`**

```python
"""
Tesseract OCR with regex brand + price extraction.

We deliberately keep this regex-based, not LLM-based, because:
    1. Tesseract output on retailer screenshots is short and structured.
    2. Regex failures (returning None) are an acceptable mode — the
       Discord layer just shows ❓ and lets the user fill it in.
    3. Loading the LLM from inside an image worker would burn RAM budget.

The retailer list is the V1 target set; add new retailers here as we
encounter their email/screenshot formats.
"""

from __future__ import annotations

import re
from pathlib import Path

from PIL import Image

from clawbot.vision.draft import OcrResult

# Canonical brand names. Case-insensitive substring match; first hit wins.
_KNOWN_BRANDS: tuple[str, ...] = (
    "Aritzia",
    "Banana Republic",
    "COS",
    "Everlane",
    "J.Crew",
    "Madewell",
    "Nordstrom",
    "Quince",
    "Sezane",
    "Theory",
    "Uniqlo",
)

# Matches $X, $X.XX, $X,XXX, $XX.XX, optional whitespace after $.
_PRICE_RE = re.compile(r"\$\s*([0-9]{1,3}(?:,[0-9]{3})*|[0-9]+)(?:\.([0-9]{2}))?")


def read(raw_path: Path) -> OcrResult:
    """Run Tesseract and pull out brand + price."""
    with Image.open(raw_path) as img:
        text = _tesseract_image_to_string(img)
    return OcrResult(
        brand=_guess_brand(text),
        price_usd=_guess_price(text),
        raw_text=text,
    )


def _guess_brand(text: str) -> str | None:
    lower = text.lower()
    for brand in _KNOWN_BRANDS:
        if brand.lower() in lower:
            return brand
    return None


def _guess_price(text: str) -> float | None:
    match = _PRICE_RE.search(text)
    if not match:
        return None
    whole = match.group(1).replace(",", "")
    cents = match.group(2)
    try:
        return float(f"{whole}.{cents}") if cents else float(whole)
    except ValueError:
        return None


def _tesseract_image_to_string(image: Image.Image) -> str:
    """Wraps pytesseract.image_to_string — exists so tests can monkeypatch.

    Lazy import keeps pytesseract out of import time on hosts that lack it.
    """
    import pytesseract  # noqa: PLC0415 — intentional lazy import

    return pytesseract.image_to_string(image)
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest tests/vision/test_ocr.py -v`
Expected: all 9 tests pass (parametrize expands 5).

- [ ] **Step 5: Commit**

```bash
git add src/clawbot/vision/ocr.py tests/vision/test_ocr.py
git commit -m "feat(vision): Tesseract OCR with brand-list + price regex"
```

---

## Task 9: `pipeline.py` orchestrator

The top-down function that wires the stages together. Unit test monkeypatches every stage and asserts on wiring + `release()` policy.

**Files:**
- Create: `src/clawbot/vision/pipeline.py`
- Create: `tests/vision/test_pipeline.py`

- [ ] **Step 1: Write the failing tests in `tests/vision/test_pipeline.py`**

```python
"""
Tests for clawbot.vision.pipeline.

The orchestrator is a thin function: call each stage in order, decide
whether to run OCR, build the DraftItem, and release models. We mock
every stage so the test is fast and deterministic — wiring is the
contract under test.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from clawbot.config import (
    ClawbotConfig,
    ImagePipelineConfig,
    PathsConfig,
)
from clawbot.vision import pipeline, models
from clawbot.vision.draft import ClassificationResult, OcrResult


@pytest.fixture(autouse=True)
def _reset_models():
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
    ocr_result: OcrResult | None = OcrResult("Aritzia", 89.0, "raw"),
) -> dict[str, int]:
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

    def fake_classify(p: Path, *, embedding: np.ndarray, threshold: float):
        calls["classify"] += 1
        return classification, cls_conf

    def fake_ocr(p: Path) -> OcrResult:
        calls["ocr"] += 1
        return ocr_result  # type: ignore[return-value]

    def fake_release() -> None:
        calls["release"] += 1

    monkeypatch.setattr(pipeline.cutout, "remove_background", fake_cutout)
    monkeypatch.setattr(pipeline.color, "extract_palette", fake_color)
    monkeypatch.setattr(pipeline.embed, "compute", fake_embed)
    monkeypatch.setattr(pipeline.classify, "zero_shot", fake_classify)
    monkeypatch.setattr(pipeline.ocr, "read", fake_ocr)
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

    monkeypatch.setattr(pipeline.cutout, "remove_background", boom)
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
```

- [ ] **Step 2: Run the failing test**

Run: `pytest tests/vision/test_pipeline.py -v`
Expected: `ModuleNotFoundError: No module named 'clawbot.vision.pipeline'`.

- [ ] **Step 3: Implement `src/clawbot/vision/pipeline.py`**

```python
"""
Image-ingestion orchestrator.

Pure top-down function: input image path + source flag → DraftItem.
Each stage's failure propagates; ``release()`` always fires when
``lazy_load_models`` is true, even on stage error.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, get_args

from clawbot.config import ClawbotConfig
from clawbot.vision import classify, color, cutout, embed, models, ocr
from clawbot.vision.draft import DraftItem

Source = Literal["upload", "screenshot", "email"]
_VALID_SOURCES = frozenset(get_args(Source))


def ingest_image(
    raw_path: Path,
    *,
    source: Source,
    config: ClawbotConfig,
) -> DraftItem:
    """Run the full image pipeline on ``raw_path`` and return a ``DraftItem``.

    No DB writes, no Discord I/O. ``release()`` is called in a ``finally``
    block when ``image_pipeline.lazy_load_models`` is true so that a
    failed ingest still drops the ~600 MB of CLIP weights.
    """
    if source not in _VALID_SOURCES:
        raise ValueError(
            f"source must be one of {sorted(_VALID_SOURCES)}, got {source!r}"
        )

    try:
        cutout_path = cutout.remove_background(raw_path, config)
        primary, secondary, color_conf = color.extract_palette(cutout_path)
        embedding = embed.compute(cutout_path)
        cls_result, cls_conf = classify.zero_shot(
            cutout_path,
            embedding=embedding,
            threshold=config.image_pipeline.fashion_clip_confidence_threshold,
        )
        should_ocr = (
            source == "screenshot"
            and config.image_pipeline.ocr_enabled_for_screenshots
        )
        ocr_result = ocr.read(raw_path) if should_ocr else None

        return DraftItem(
            image_raw_path=raw_path,
            image_cutout_path=cutout_path,
            color_primary=primary,
            color_secondary=secondary,
            classification=cls_result,
            ocr=ocr_result,
            embedding=embedding,
            confidence={"color": color_conf, **cls_conf},
        )
    finally:
        if config.image_pipeline.lazy_load_models:
            models.release()
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest tests/vision/test_pipeline.py -v`
Expected: all 8 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/clawbot/vision/pipeline.py tests/vision/test_pipeline.py
git commit -m "feat(vision): pipeline orchestrator with try/finally release"
```

---

## Task 10: Public package API

Expose `ingest_image` + the dataclasses through `clawbot.vision.__init__`. Verify the whole vision suite still passes.

**Files:**
- Modify: `src/clawbot/vision/__init__.py`
- Create: `tests/vision/test_api.py`

- [ ] **Step 1: Write the failing test in `tests/vision/test_api.py`**

```python
"""
Tests for the public surface of clawbot.vision.

Only ``ingest_image`` and the three dataclasses should be importable
from the package root. Everything else is private (the stage modules
remain reachable as ``clawbot.vision.<stage>`` for callers that need
them, but are not re-exported through __init__).
"""

from __future__ import annotations


def test_public_api_exports() -> None:
    import clawbot.vision as v

    # Required public names.
    assert hasattr(v, "ingest_image")
    assert hasattr(v, "DraftItem")
    assert hasattr(v, "ClassificationResult")
    assert hasattr(v, "OcrResult")


def test_dunder_all_is_explicit() -> None:
    import clawbot.vision as v

    assert v.__all__ == [
        "ClassificationResult",
        "DraftItem",
        "OcrResult",
        "ingest_image",
    ]
```

- [ ] **Step 2: Run the failing test**

Run: `pytest tests/vision/test_api.py -v`
Expected: `AttributeError: module 'clawbot.vision' has no attribute 'ingest_image'`.

- [ ] **Step 3: Fill in `src/clawbot/vision/__init__.py`**

Replace the empty file with:

```python
"""
clawbot.vision — offline image-ingestion pipeline.

Public API:
    ingest_image(raw_path, *, source, config) -> DraftItem

DraftItem and its sub-records (ClassificationResult, OcrResult) are
re-exported so callers don't need to know which stage produced them.
"""

from clawbot.vision.draft import ClassificationResult, DraftItem, OcrResult
from clawbot.vision.pipeline import ingest_image

__all__ = [
    "ClassificationResult",
    "DraftItem",
    "OcrResult",
    "ingest_image",
]
```

- [ ] **Step 4: Run the whole vision suite**

Run: `pytest tests/vision -v`
Expected: every test passes. The full suite should be well under 5 seconds (no torch / rembg loads).

- [ ] **Step 5: Run the full project suite to catch regressions**

Run: `pytest -q`
Expected: all existing tests still pass.

- [ ] **Step 6: Type-check the new package**

Run: `mypy src/clawbot/vision`
Expected: no errors. If `numpy` stubs complain, add `numpy>=1.26` already covers it.

- [ ] **Step 7: Lint**

Run: `ruff check src/clawbot/vision tests/vision`
Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add src/clawbot/vision/__init__.py tests/vision/test_api.py
git commit -m "feat(vision): public package API (ingest_image + dataclasses)"
```

---

## Task 11: Real model loaders

Replace the three `NotImplementedError` stubs in `models.py` with real loaders. This is the first task that requires `[vision]` extras to *run* — but it does **not** require new tests in the unit tier (still all monkeypatched). Validation happens via the integration tier (Task 12).

**Files:**
- Modify: `src/clawbot/vision/models.py`

- [ ] **Step 1: Confirm `[vision]` extras are available locally (or skip to Task 12 if you're on the dev Mac without them)**

Run: `python -c "import torch, rembg, open_clip"`
Expected: no error. If you get `ModuleNotFoundError`, install: `pip install -e ".[vision]"`. The installs are ~2 GB and slow.

- [ ] **Step 2: Replace `_load_fashion_clip` in `src/clawbot/vision/models.py`**

Find the function:
```python
def _load_fashion_clip() -> tuple[Any, Any]:
    """Load Fashion-CLIP weights. Replaced with the real impl in Task 11."""
    raise NotImplementedError(...)
```

Replace with:
```python
def _load_fashion_clip() -> tuple[Any, Any]:
    """Load Fashion-CLIP weights into RAM (~600 MB).

    Uses open_clip_torch, which is the standard way to load the
    patrickjohncyh/fashion-clip checkpoint. The model is moved to CPU
    explicitly — the NUC has no GPU.
    """
    import open_clip
    import torch

    model, _, preprocess = open_clip.create_model_and_transforms(
        "hf-hub:patrickjohncyh/fashion-clip"
    )
    model.eval()
    model.to("cpu")
    tokenizer = open_clip.get_tokenizer("hf-hub:patrickjohncyh/fashion-clip")
    # We bundle the tokenizer with the preprocessor as the "processor" tuple
    # because both downstream stages (embed, classify) need access:
    # embed uses `preprocess`; classify uses `tokenizer` indirectly through
    # _compute_text_embeddings below.
    return model, _ClipProcessor(preprocess=preprocess, tokenizer=tokenizer)
```

Add a small dataclass at the bottom of the file (before the `_new_rembg_session` stub):

```python
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class _ClipProcessor:
    """Bundle the preprocess transform with the tokenizer.

    open_clip returns them separately; embed.compute and the text-embedding
    builder both reach in here.
    """
    preprocess: Any
    tokenizer: Any

    def __call__(self, *, images: Any, return_tensors: str = "pt") -> dict[str, Any]:
        """Mirror the HuggingFace processor signature embed.compute relies on."""
        import torch

        if return_tensors != "pt":
            raise ValueError("only return_tensors='pt' is supported")
        return {"pixel_values": self.preprocess(images).unsqueeze(0)}
```

- [ ] **Step 3: Replace `_new_rembg_session`**

Find:
```python
def _new_rembg_session(model_name: str) -> Any:
    raise NotImplementedError(...)
```

Replace with:
```python
def _new_rembg_session(model_name: str) -> Any:
    """Construct a rembg Session for the named model (e.g. ``u2netp``)."""
    import rembg

    return rembg.new_session(model_name)
```

- [ ] **Step 4: Replace `_compute_text_embeddings`**

Find:
```python
def _compute_text_embeddings() -> dict[str, Any]:
    raise NotImplementedError(...)
```

Replace with:
```python
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
    tokenizer = processor.tokenizer  # type: ignore[union-attr]

    # Build a flat (key, prompt) list so we tokenize/encode in one batch.
    items: list[tuple[str, str]] = []
    items.extend((f"category:{k}", v) for k, v in CATEGORY_PROMPTS.items())
    for cat, subs in SUBCATEGORY_PROMPTS.items():
        items.extend((f"subcategory:{cat}:{name}", p) for name, p in subs.items())
    items.extend((f"formality:{k}", v) for k, v in FORMALITY_PROMPTS.items())
    items.extend((f"season:{k}", v) for k, v in SEASON_PROMPTS.items())

    keys = [k for k, _ in items]
    prompts = [p for _, p in items]

    with torch.no_grad():
        tokens = tokenizer(prompts)
        embs = model.encode_text(tokens).detach().cpu().numpy().astype(np.float32)

    # L2-normalize each row.
    norms = np.linalg.norm(embs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    embs = embs / norms

    return {k: embs[i] for i, k in enumerate(keys)}
```

- [ ] **Step 5: Re-run the unit suite — everything still mocked, still passes**

Run: `pytest tests/vision -q`
Expected: every test passes. The real loaders are not exercised by the unit tier.

- [ ] **Step 6: Type-check**

Run: `mypy src/clawbot/vision`
Expected: no errors (the lazy imports may trip strict mode — if mypy complains about untyped `import torch`, add `# type: ignore[import-not-found]` on the line).

- [ ] **Step 7: Commit**

```bash
git add src/clawbot/vision/models.py
git commit -m "feat(vision): real Fashion-CLIP / rembg loaders + text-embedding cache"
```

---

## Task 12: Integration tests

End-to-end tests with real models. Auto-skip without `[vision]` extras. Run only via `pytest -m integration`.

**Files:**
- Create: `tests/vision/integration/__init__.py`
- Create: `tests/vision/integration/conftest.py`
- Create: `tests/vision/integration/test_end_to_end.py`

- [ ] **Step 1: Create package marker**

Run:
```bash
mkdir -p tests/vision/integration
touch tests/vision/integration/__init__.py
```

- [ ] **Step 2: Write the skip guard in `tests/vision/integration/conftest.py`**

```python
"""
Integration-tier conftest.

Tests in this directory load the real Fashion-CLIP weights (~600 MB)
and rembg's u2netp. They auto-skip on hosts without the [vision]
extras installed.

Run on the NUC:
    pytest -m integration tests/vision/integration -v
"""

from __future__ import annotations

import pytest

# Detect [vision] extras; skip the whole subtree if missing.
try:
    import open_clip  # noqa: F401
    import rembg  # noqa: F401
    import torch  # noqa: F401
    import pytesseract  # noqa: F401
    _vision_available = True
except ImportError:
    _vision_available = False

collect_ignore_glob: list[str] = [] if _vision_available else ["test_*.py"]
```

- [ ] **Step 3: Write the integration test**

```python
"""
End-to-end integration tests for the image pipeline.

Synthetic images give no real signal about classification quality —
these tests assert STRUCTURAL correctness only: shapes, dtypes, value
ranges, presence/absence of OCR. Semantic accuracy is a manual QA pass
on real photos during Step 6/7 build.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from clawbot.config import ClawbotConfig, ImagePipelineConfig, PathsConfig
from clawbot.vision import DraftItem, ingest_image

pytestmark = pytest.mark.integration

CATEGORIES = {
    "tops", "bottoms", "dresses", "outerwear",
    "footwear", "accessories", "underlayers", "activewear",
}
FORMALITY = {
    "very-casual", "casual", "smart-casual", "business", "formal",
}


@pytest.fixture
def cfg(tmp_path: Path) -> ClawbotConfig:
    # Note: the `synthetic_top` / `synthetic_screenshot` fixtures are inherited
    # from `tests/vision/conftest.py` — pytest discovers conftests up the tree.
    return ClawbotConfig(
        paths=PathsConfig(images_dir=tmp_path / "images"),
        image_pipeline=ImagePipelineConfig(
            lazy_load_models=True,
            ocr_enabled_for_screenshots=True,
            fashion_clip_confidence_threshold=0.10,  # generous on synthetic
            rembg_model="u2netp",
        ),
    )


def _assert_structural_valid(draft: DraftItem) -> None:
    assert draft.image_cutout_path.exists()
    assert draft.image_cutout_path.suffix == ".png"
    assert draft.color_primary.startswith("#") and len(draft.color_primary) == 7
    assert draft.embedding.shape == (512,)
    assert draft.embedding.dtype == np.float32
    assert pytest.approx(np.linalg.norm(draft.embedding), rel=1e-4) == 1.0
    assert draft.classification.category in CATEGORIES
    assert draft.classification.formality in FORMALITY
    assert set(draft.confidence.keys()) == {
        "category", "subcategory", "formality", "season", "color",
    }
    for k, v in draft.confidence.items():
        assert 0.0 <= v <= 1.0, f"{k}: {v}"


def test_ingest_upload_structurally_valid(
    cfg: ClawbotConfig, synthetic_top: Path
) -> None:
    draft = ingest_image(synthetic_top, source="upload", config=cfg)
    _assert_structural_valid(draft)
    assert draft.ocr is None


def test_ingest_email_structurally_valid(
    cfg: ClawbotConfig, synthetic_top: Path
) -> None:
    draft = ingest_image(synthetic_top, source="email", config=cfg)
    _assert_structural_valid(draft)
    assert draft.ocr is None


def test_ingest_screenshot_runs_ocr(
    cfg: ClawbotConfig, synthetic_screenshot: Path
) -> None:
    draft = ingest_image(synthetic_screenshot, source="screenshot", config=cfg)
    _assert_structural_valid(draft)
    assert draft.ocr is not None
    # raw_text content depends on tesseract version; just check it's not empty.
    assert isinstance(draft.ocr.raw_text, str)
```

- [ ] **Step 4: Run the integration suite on the NUC**

On the NUC (or any host with `[vision]` installed):

Run: `pytest -m integration tests/vision/integration -v`
Expected: 3 tests pass. First run is slow (Fashion-CLIP downloads on first model load, ~600 MB). Subsequent runs cache.

- [ ] **Step 5: Verify unit suite still skips integration on the Mac**

Run on the Mac: `pytest tests/vision -q`
Expected: all unit tests pass; integration tests are silently skipped/ignored (no error about missing `torch`).

- [ ] **Step 6: Commit**

```bash
git add tests/vision/integration/
git commit -m "test(vision): integration tier with real Fashion-CLIP + rembg + Tesseract"
```

---

## Task 13: Final verification

End-to-end sanity check before opening a PR.

- [ ] **Step 1: Run the full project test suite**

On the Mac (no `[vision]` extras):
Run: `pytest -q`
Expected: every test passes; no surprises.

- [ ] **Step 2: Type-check the whole project**

Run: `mypy src tests`
Expected: clean.

- [ ] **Step 3: Lint**

Run: `ruff check src tests`
Expected: clean.

- [ ] **Step 4: Verify the spec's acceptance criteria are met**

Open `docs/superpowers/specs/2026-05-14-image-pipeline-design.md`, scroll to
"Acceptance criteria" (§16). Tick off each:

  - ✅ `pytest` on Mac passes, no new dep weight beyond [dev]
  - ✅ `pytest -m integration` on NUC passes
  - ✅ `mypy --strict src/clawbot/vision` clean
  - ✅ `ruff check src/clawbot/vision tests/vision` clean
  - ☐  RSS-delta check: manual on the NUC. Run:
    ```bash
    python -c "
    import tracemalloc, pathlib
    from clawbot.config import load_config
    from clawbot.vision import ingest_image

    cfg = load_config(pathlib.Path('config/clawbot.yaml'))
    tracemalloc.start()
    snapshot_before = tracemalloc.take_snapshot()
    ingest_image(pathlib.Path('test_image.jpg'), source='upload', config=cfg)
    snapshot_after = tracemalloc.take_snapshot()
    diff = sum(s.size_diff for s in snapshot_after.compare_to(snapshot_before, 'lineno'))
    print(f'RSS delta after release: {diff / 1024 / 1024:.1f} MB')
    "
    ```
    Expected: delta < 50 MB. If above, file as a follow-up; do not block merge.
  - ✅ No DB writes / Discord calls in `clawbot/vision/`. Verify with `grep -r "import clawbot.db" src/clawbot/vision` — expect zero matches.

- [ ] **Step 5: Final commit (if any quality fixes were needed)**

If steps 1–4 surfaced any small fixes, commit them now with a descriptive message. Otherwise skip.

- [ ] **Step 6: Push the branch**

```bash
git push -u origin feat/image-pipeline
```

- [ ] **Step 7: Open a PR via `gh`** (only if the user asks — `feat/foundation` itself hasn't been merged yet, so this PR's base might need to be that branch, not `master`).

---

## Notes for the implementing engineer

- **Run order matters.** Each task's tests will fail if you skip the previous task — the modules import each other. Stick to the numbered sequence.
- **Don't add helpers across modules.** Every module's surface is what's documented in the spec; the only cross-module call is into `models.py`. If you find yourself wanting to add a utility used by two stages, push back and check with the spec author.
- **Don't worry if integration tests pick "wrong" categories** on synthetic solid colors — that's expected. The assertions are structural, not semantic, because synthetic images carry no real signal.
- **Memory:** if the NUC tracemalloc check shows >50 MB residue per ingest, the most likely culprit is the text-embedding cache. Verify `models.release()` clears `_text_embeddings`.
