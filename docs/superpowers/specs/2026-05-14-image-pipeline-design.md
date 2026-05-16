# Image Pipeline — Design Spec (Build Step 5)

**Status:** Approved by user 2026-05-14. Ready for implementation plan.

**Parent plan:** `~/.claude/plans/task-help-me-finalize-abundant-sundae.md` (Step 5).

**Scope:** Implement the offline image-ingestion pipeline as a pure transformation:
input raw image → `DraftItem` dataclass. No database writes, no Discord I/O, no
file moves beyond writing the cutout. Persistence happens in later steps
(Step 7 from Discord approval; Step 8 from the inbox watcher).

---

## 1. Goals

1. Accept an image file path + a `source` discriminator and return a `DraftItem`
   carrying everything the pipeline can infer from pixels: cutout path, color
   palette, Fashion-CLIP embedding, zero-shot attribute classification,
   optional OCR (screenshots only), and per-attribute confidence.
2. Stay under the NUC's 8 GB RAM budget by lazy-loading the Fashion-CLIP and
   rembg models and releasing them between jobs when
   `image_pipeline.lazy_load_models: true`.
3. Be testable on a developer Mac without the `[vision]` extras installed — the
   default `pytest` run loads no torch, no rembg, no Fashion-CLIP weights.
   Real-model validation runs via `pytest -m integration` on the NUC.

## 2. Non-goals

- DB writes, Discord posts, or inbox sweeping — those are Steps 7 / 8.
- Final 512-px thumbnail generation — happens at approval time so we don't
  burn storage on rejected drafts.
- Semantic accuracy validation on synthetic test images — integration tests
  assert structural correctness (shape, dtype, range, key existence) only.
  Real-photo QA is a manual pass tied to Step 6/7.

## 3. Public API

```python
from clawbot.vision import ingest_image, DraftItem

draft: DraftItem = ingest_image(
    raw_path=Path("/data/images/raw/abc.jpg"),
    source="screenshot",   # Literal["screenshot", "upload", "email"]
    config=load_config(),
)
```

Everything else under `clawbot.vision` is private (the stage modules,
`models.py`, `taxonomy.py`).

### `source` semantics

| value | OCR runs? | Use case |
|-------|-----------|----------|
| `"upload"` | no | Photo uploaded via Discord `/add_item` |
| `"email"` | no | Image attachment from a parsed retailer email (the email parser already gives us brand/price) |
| `"screenshot"` | yes | File dropped into `inbox/screenshots/` — likely contains retailer UI text we can OCR |

OCR is opt-in by `source` because Tesseract on this CPU costs ~1.5 s per call
and produces noise on phone photos.

## 4. Module layout

```
src/clawbot/vision/
├── __init__.py          # re-exports: ingest_image, DraftItem
├── pipeline.py          # orchestrator (40-ish lines)
├── draft.py             # DraftItem, ClassificationResult, OcrResult dataclasses
├── models.py            # lazy singletons + release()
├── taxonomy.py          # CATEGORY_PROMPTS, FORMALITY_PROMPTS, SEASON_PROMPTS
├── cutout.py            # remove_background(raw_path, config) -> cutout_path
├── color.py             # extract_palette(cutout_path) -> (primary_hex, secondary_hex|None)
├── embed.py             # compute(cutout_path) -> np.ndarray[(512,), float32]
├── classify.py          # zero_shot(cutout_path, taxonomy) -> ClassificationResult
└── ocr.py               # read(raw_path) -> OcrResult
```

Mirrored under `tests/vision/`.

## 5. `DraftItem` dataclass

All dataclasses are `frozen=True, slots=True`.

```python
@dataclass(frozen=True, slots=True)
class ClassificationResult:
    category: str                  # "tops" | "bottoms" | "dresses" | "outerwear"
                                   # | "footwear" | "accessories" | "underlayers"
                                   # | "activewear"
    subcategory: str | None        # e.g. "cardigan"; None when below threshold
    formality: str                 # "very-casual" | "casual" | "smart-casual"
                                   # | "business" | "formal"
    seasons: list[str]             # subset of ["spring","summer","fall","winter"]

@dataclass(frozen=True, slots=True)
class OcrResult:
    brand: str | None
    price_usd: float | None
    raw_text: str                  # full OCR dump for later regex tuning

@dataclass(frozen=True, slots=True)
class DraftItem:
    image_raw_path: Path
    image_cutout_path: Path
    color_primary: str             # "#RRGGBB"
    color_secondary: str | None    # None when palette has only one dominant color
    classification: ClassificationResult
    ocr: OcrResult | None          # None when source != "screenshot"
    embedding: np.ndarray          # shape (512,), dtype float32
    confidence: dict[str, float]   # keys: "category","subcategory","formality",
                                   #       "season","color"
```

### Rationale

- **No `image_final_path`:** thumbnail is generated at approval, not here.
- **`np.ndarray` embedding (not `list[float]`):** Fashion-CLIP returns numpy
  natively; sqlite-vec consumes numpy bytes directly. Lossy round-trips
  through `list[float]` are wasteful.
- **`dict[str, float]` confidence (flat):** the Discord layer iterates it for
  emoji rendering; no consumer needs nested access yet. Upgrade to a structured
  type only if a second consumer appears.
- **`subcategory: str | None`:** category is forced (top-level taxonomy is
  small, so even the worst guess has signal); subcategory is dropped when its
  confidence is below `fashion_clip_confidence_threshold` (default 0.55 per
  config).

## 6. Orchestration

```python
# pipeline.py
def ingest_image(raw_path: Path, source: Source, config: ClawbotConfig) -> DraftItem:
    try:
        cutout_path = cutout.remove_background(raw_path, config)
        primary, secondary, color_conf = color.extract_palette(cutout_path)
        embedding = embed.compute(cutout_path)
        cls_result, cls_conf = classify.zero_shot(
            cutout_path,
            embedding=embedding,        # reuse to skip a second forward pass
            threshold=config.image_pipeline.fashion_clip_confidence_threshold,
        )
        # cls_conf has keys: "category","subcategory","formality","season"
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

Stages run sequentially. The orchestrator does no error handling beyond the
`try/finally` for `release()`: each stage raises on failure, the caller (jobs
worker or test) decides retry policy.

## 7. Model lifecycle (`models.py`)

```python
_clip: tuple[CLIPModel, CLIPProcessor] | None = None
_rembg: rembg.sessions.BaseSession | None = None

def get_clip() -> tuple[CLIPModel, CLIPProcessor]:
    global _clip
    if _clip is None:
        _clip = _load_fashion_clip()    # ~600 MB
    return _clip

def get_rembg_session(model_name: str) -> rembg.sessions.BaseSession:
    global _rembg
    if _rembg is None:
        _rembg = rembg.new_session(model_name)
    return _rembg

def release() -> None:
    """Drop model refs and force GC. Idempotent."""
    global _clip, _rembg
    _clip = None
    _rembg = None
    gc.collect()
```

- **No thread safety.** The pipeline runs inside the single image worker
  (Step 8). When multi-worker becomes a need, wrap `get_*` with a
  `threading.Lock`.
- **CLIP is loaded once per ingest at most**, shared between `embed.compute`
  and `classify.zero_shot`. Unloading between them would double load time.
- **rembg session is cached for the same reason**, but it's much smaller
  (~5 MB for `u2netp`).
- **Tesseract is not cached.** `pytesseract` shells out to a subprocess; there
  is nothing to hold open. OCR runs at most once per ingest.

### Test seam

`models.get_clip` and `models.get_rembg_session` are the *only* code that
imports torch / rembg. Unit tests monkeypatch them with stubs; nothing else in
the package needs torch installed.

## 8. Zero-shot taxonomy (`taxonomy.py`)

Prompts are derived from the plan's locked taxonomy. Constants only — no
function logic. Example shape (full list in implementation):

```python
CATEGORY_PROMPTS: dict[str, str] = {
    "tops":        "a photo of a shirt, top, or sweater",
    "bottoms":     "a photo of pants, jeans, or a skirt",
    "dresses":     "a photo of a dress or jumpsuit",
    "outerwear":   "a photo of a jacket, coat, or blazer",
    "footwear":    "a photo of shoes or boots",
    "accessories": "a photo of a bag, belt, hat, or jewelry",
    "underlayers": "a photo of underwear, tights, or a base layer",
    "activewear":  "a photo of activewear or athletic clothing",
}

FORMALITY_PROMPTS: dict[str, str] = {
    "very-casual":  "very casual loungewear or pajamas",
    "casual":       "casual everyday clothing",
    "smart-casual": "smart casual office-friendly clothing",
    "business":     "business or professional attire",
    "formal":       "formal evening wear or suit",
}

SEASON_PROMPTS: dict[str, str] = {
    "spring": "lightweight clothing for spring weather",
    "summer": "lightweight clothing for hot summer weather",
    "fall":   "layered clothing for cool fall weather",
    "winter": "heavy clothing for cold winter weather",
}

SUBCATEGORY_PROMPTS: dict[str, dict[str, str]] = {
    "tops": {"t-shirt": "...", "cardigan": "...", ...},
    "bottoms": {"jeans": "...", "trousers": "...", ...},
    # one nested dict per top-level category
}
```

### Classification logic

`classify.zero_shot(cutout_path, embedding, threshold)`:

1. Compute text-embedding for each prompt in `CATEGORY_PROMPTS` (cached at
   first call inside `models.py`; text embeddings don't change between
   ingests).
2. Cosine-similarity `embedding` against each text vector; apply softmax →
   per-class probability.
3. `category = argmax`; `confidence["category"] = max prob`.
4. Look up the per-category subcategory prompts and repeat → `subcategory` /
   `confidence["subcategory"]`. If below `threshold`, set `subcategory=None`.
5. Repeat for `FORMALITY_PROMPTS` → single label.
6. For `SEASON_PROMPTS`, threshold each independently (multi-label).
   `seasons` is the list of labels passing threshold; `confidence["season"]`
   is the mean probability of the chosen labels.

Text-embedding cache lives on `models.py`:
```python
_text_embeddings: dict[str, np.ndarray] | None = None
def get_text_embeddings() -> dict[str, np.ndarray]:
    ...
```
Cleared by `release()` along with the CLIP weights.

## 9. Color extraction (`color.py`)

Use `colorthief.ColorThief(cutout_path).get_palette(color_count=3)` on the
**cutout** (background already removed → palette isn't polluted by white/grey
backdrop). Convert top-2 RGB tuples to hex.

- `color_primary` = the first palette entry, formatted `"#RRGGBB"`.
- `color_secondary` = the second entry, or `None` when colorthief's `get_color`
  and `get_palette[1]` are within a perceptual-distance threshold (we treat
  the item as effectively single-color).
- `confidence["color"]` = `1.0 - normalized_distance` between primary and the
  background-cleared average (heuristic; gives Discord something to display).

## 10. Cutout (`cutout.py`)

```python
def remove_background(raw_path: Path, config: ClawbotConfig) -> Path:
    session = models.get_rembg_session(config.image_pipeline.rembg_model)
    with Image.open(raw_path) as img:
        cutout = rembg.remove(img, session=session)
    cutout_path = Path(config.paths.images_dir) / "cutouts" / f"{raw_path.stem}.png"
    cutout_path.parent.mkdir(parents=True, exist_ok=True)
    cutout.save(cutout_path, "PNG")
    return cutout_path
```

Output is always PNG (transparency). Cutout path naming uses the raw file's
stem to make manual association trivial; UUIDs are assigned later when the
draft is persisted.

## 11. OCR (`ocr.py`)

```python
def read(raw_path: Path) -> OcrResult:
    raw_text = pytesseract.image_to_string(Image.open(raw_path))
    return OcrResult(
        brand=_guess_brand(raw_text),
        price_usd=_guess_price(raw_text),
        raw_text=raw_text,
    )
```

Brand and price extraction are regex-based heuristics — V1 keeps it simple:

- **Brand:** match the raw text against a hard-coded list of known retailers
  (`COS`, `Everlane`, `Quince`, `Sezane`, `Madewell`, `Theory`, `Aritzia`,
  `Banana Republic`, `Uniqlo`, `J.Crew`, `Nordstrom`). Case-insensitive
  substring; first match wins; `None` if no match.
- **Price:** regex `\$\s*(\d{1,4})(?:\.(\d{2}))?` over the text; first match
  wins; `None` if no match.

The retailer list and price regex live as module-level constants for easy
tuning. We deliberately don't go LLM-based here — Tesseract output on
screenshot UI is structured enough for regex and the failure mode (returning
`None`) is acceptable.

## 12. Configuration touch-points

All knobs already exist in `config/clawbot.example.yaml` under `image_pipeline`:

| key | used by |
|-----|---------|
| `thumbnail_max_px` | **NOT** used in Step 5 — reserved for thumbnail generation at approval time (Step 7) |
| `rembg_model` | `cutout.remove_background` |
| `lazy_load_models` | `pipeline.ingest_image` (controls `release()` call) |
| `fashion_clip_confidence_threshold` | `classify.zero_shot` |
| `ocr_enabled_for_screenshots` | acts as a kill-switch — when `false`, `ingest_image` always passes `ocr=None` regardless of `source` |

No new config keys needed.

## 13. Dependencies

Already declared as the `[vision]` optional in `pyproject.toml`:

```
rembg>=2.0.57
Pillow>=10.3
colorthief>=0.2.1
open-clip-torch>=2.24
torch>=2.2,<3
torchvision>=0.17
pytesseract>=0.3.10
```

System packages required on the NUC (the Dockerfile already installs them):
`tesseract-ocr`, `libgl1` (Pillow/OpenCV), `libglib2.0-0`.

No additions to `pyproject.toml` required.

## 14. Test strategy

Two tiers, both run under `pytest`:

### 14.1 Unit tier (default `pytest` run)

Lives in `tests/vision/`. No torch, no rembg, no Fashion-CLIP load.

- **`test_pipeline.py`** — orchestrator wiring. Monkeypatches every stage
  function with a stub returning known values, asserts the resulting
  `DraftItem` is constructed correctly, asserts `models.release()` is called
  iff `lazy_load_models` is true, asserts OCR is skipped when
  `source != "screenshot"`.
- **`test_color.py`** — runs real `colorthief` on a synthetic 256×256 PIL
  image of known color. Fast (<100 ms).
- **`test_cutout.py`** — monkeypatches `rembg.remove`; verifies output path
  convention, file is written, PNG extension forced.
- **`test_embed.py`** — monkeypatches `models.get_clip`; verifies output is
  `np.ndarray` with shape `(512,)` and dtype `float32`.
- **`test_classify.py`** — monkeypatches model and text embeddings; verifies
  argmax/softmax math and threshold logic with hand-crafted probability
  vectors.
- **`test_ocr.py`** — monkeypatches `pytesseract.image_to_string`; verifies
  brand and price regex against representative strings (Aritzia, no brand,
  `$89.00`, `$1,200`, no price).
- **`test_draft.py`** — dataclass invariants (frozen, required confidence
  keys present).
- **`test_models.py`** — singleton behavior, `release()` is idempotent and
  drops both refs.

Synthetic fixtures in `tests/vision/conftest.py` generate tiny solid-color
PNGs at test time. No binary files committed.

### 14.2 Integration tier (`pytest -m integration`)

Lives in `tests/vision/integration/` (sibling of the unit tests). One
end-to-end test per `source` value. Loads real Fashion-CLIP, real rembg.
Auto-skipped on hosts without the `[vision]` extras via a top-level
`try: import torch except ImportError: pytestmark = skip` in
`tests/vision/integration/conftest.py`. Integration tests use the same
synthetic-image fixtures as the unit tier — they're enough to drive the
plumbing end-to-end without needing committed binary fixtures.

Assertions are structural only:

```python
@pytest.mark.integration
def test_real_ingest_upload(synthetic_top, real_config):
    draft = ingest_image(synthetic_top, source="upload", config=real_config)
    assert draft.embedding.shape == (512,)
    assert draft.embedding.dtype == np.float32
    assert draft.classification.category in {
        "tops","bottoms","dresses","outerwear",
        "footwear","accessories","underlayers","activewear"
    }
    assert 0.0 <= draft.confidence["category"] <= 1.0
    assert draft.ocr is None       # source=="upload"
    assert draft.image_cutout_path.exists()
```

Semantic accuracy ("is this synthetic blue blob actually classified as a
top?") is NOT asserted — synthetic images give no real signal. Real-photo
spot-checking is a manual pass during Step 6/7 build.

## 15. TDD build order

Per global CLAUDE.md (TDD always):

1. `draft.py` — write `test_draft.py`, then dataclasses. (Pure data; trivial.)
2. `taxonomy.py` — write `test_taxonomy.py` (asserts every category in the
   plan has a prompt), then constants.
3. `color.py` — write `test_color.py` against known synthetic colors, then
   implementation.
4. `models.py` — write `test_models.py` (singleton + release), then stubs.
   No real model loading yet — `_load_fashion_clip()` raises `NotImplementedError`.
5. `cutout.py` — write `test_cutout.py` (monkeypatched `rembg.remove`), then
   implementation.
6. `embed.py` — write `test_embed.py` (monkeypatched `get_clip`), then
   implementation.
7. `classify.py` — write `test_classify.py` (monkeypatched model + text
   embeddings), then implementation.
8. `ocr.py` — write `test_ocr.py` (monkeypatched pytesseract), then
   implementation.
9. `pipeline.py` — write `test_pipeline.py` (monkeypatched stages), then
   orchestrator.
10. `models.py` — fill in `_load_fashion_clip` and text-embedding cache. This
    is the only step that requires the `[vision]` extras to *run* (still no
    test changes — covered by integration tests).
11. Integration tests in `tests/vision/integration/`. Run only on the NUC.

## 16. Acceptance criteria

- `pytest` (no extras installed, on the Mac) passes with the new tests, and
  takes no longer than the current suite.
- `pytest -m integration` on the NUC passes, end-to-end, returning structurally
  valid `DraftItem`s for all three `source` values.
- `mypy --strict src/clawbot/vision` is clean.
- `ruff check src/clawbot/vision tests/vision` is clean.
- Memory: a single `ingest_image` call followed by `models.release()` returns
  resident set size to within 50 MB of the pre-call baseline (manually
  validated on the NUC with `tracemalloc` once).
- No DB writes, no Discord calls anywhere in `clawbot/vision/`.

## 17. Open questions deferred to implementation

- Exact text prompts for subcategory zero-shot — we'll iterate after the first
  real-photo manual pass.
- Whether to add a `confidence["overall"]` aggregate — Discord layer
  (Step 7) will tell us if it needs it.
- Memory release granularity — current design releases everything; if a single
  ingest plus release blows past the 50 MB threshold, consider unloading only
  CLIP and keeping rembg.
