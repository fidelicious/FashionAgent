"""
Outfit compatibility sub-score — the "do these items go together?" signal.

The plan locks the *role* of this score (25 weight points in the combinator)
and the *ingredients* — Fashion-CLIP cosine similarity between item
embeddings, plus the `pairs_well_with` / `avoid_pairing_with` curated lists.
It does **not** lock the exact arithmetic. That's a design call for you.

What plugs into this module from elsewhere:
  - `WardrobeItem.embedding`: a 512-dim Fashion-CLIP vector (or None for items
    added before the image pipeline ran). Unit-norm in practice but not
    guaranteed in tests — normalise if you need to.
  - `WardrobeItem.pairs_well_with`: tuple of other item ids the user said
    "always works with". A confirmed style affinity.
  - `WardrobeItem.avoid_pairing_with`: tuple of other item ids the user said
    "clashes". A confirmed style anti-affinity.

What it feeds into:
  - `score.score_outfit()` multiplies the returned value by 25 and adds it to
    the total. Range MUST be [0.0, 1.0] — anything else breaks the property
    tests that pin the total to [-25, 100].

╔════════════════════════════════════════════════════════════════════════════╗
║  TODO — USER CONTRIBUTION                                                  ║
║                                                                            ║
║  Implement compute_compatibility() below. You're designing the formula     ║
║  that decides whether an outfit "hangs together". Trade-offs to weigh:    ║
║                                                                            ║
║  1. AGGREGATION over pairs                                                 ║
║     With 3 items there are 3 pairs; with 4 there are 6. Options:           ║
║       - Mean cosine similarity   → fair, but one bad pair gets diluted.    ║
║       - Min cosine similarity    → strict, "no outfit is stronger than    ║
║                                     its weakest link".                     ║
║       - Weighted (top-bottom pair matters more than top-shoe)              ║
║                                                                            ║
║  2. NORMALISATION                                                          ║
║     Cosine sim is in [-1, 1]; we need [0, 1]. Options:                     ║
║       - (cos + 1) / 2           → linear, includes a free floor at 0.5     ║
║                                    for orthogonal pieces.                  ║
║       - max(cos, 0)             → strict, dissimilar = 0.                  ║
║                                                                            ║
║  3. CURATED OVERRIDES                                                      ║
║     `pairs_well_with` should *raise* the score; `avoid_pairing_with`       ║
║     should *lower* it. Magnitudes are your call:                           ║
║       - Additive bonus / penalty (e.g. +0.10 / −0.20)?                     ║
║       - Multiplicative (e.g. ×1.2 / ×0.5)?                                 ║
║       - Hard veto on avoid (force return 0.0)?                             ║
║       - Cap the boosted score at 1.0 — the unit-interval invariant is     ║
║         enforced by tests and by the property suite.                       ║
║                                                                            ║
║  4. MISSING EMBEDDINGS                                                     ║
║     Items with `embedding is None` exist (pre-pipeline imports). Choose:   ║
║       - Skip them in the cosine averaging?                                 ║
║       - Treat them as neutral (cos = 0)?                                   ║
║                                                                            ║
║  Once you implement the body, flip STRICT_XFAIL = True in                  ║
║  tests/outfits/test_compatibility.py so the suite enforces it.             ║
╚════════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

from collections.abc import Sequence

from clawbot.outfits.types import WardrobeItem


def _cosine(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    """Plain cosine similarity in [-1, 1]; here so you don't have to import numpy
    in the formula body. Returns 0.0 for zero-norm vectors (defensive)."""
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def compute_compatibility(items: Sequence[WardrobeItem]) -> float:
    """
    Return a 0.0–1.0 compatibility score for these items.

    Inputs:
        items: 0..N WardrobeItem instances. Order is not meaningful.

    Output:
        A float in [0.0, 1.0]. 0.5 is "neutral / no signal".

    Algorithm
    ---------
    1. **Cosine base**: compute cosine similarity for every pair of items that
       both have embeddings.  Map each raw cosine ∈ [-1, 1] to [0, 1] via
       ``(cos + 1) / 2`` so that:
         - identical vectors  → 1.0  (very compatible)
         - orthogonal vectors → 0.5  (neutral, no signal)
         - opposite vectors   → 0.0  (incompatible)
       Average across all valid pairs.  Fall back to 0.5 when no pair has
       embeddings (no visual signal available).

    2. **Curated overrides**: additive adjustments on top of the base:
         - +0.10 per item whose ``pairs_well_with`` overlaps the outfit ids
         - −0.20 per item whose ``avoid_pairing_with`` overlaps the outfit ids
       Using a larger penalty than bonus deliberately makes explicit clashes
       hurt more than explicit affinities help — erring on the side of not
       suggesting outfits the user has labelled as clashing.

    3. **Clamp** to [0.0, 1.0] to satisfy the unit-interval invariant.

    Invariants (enforced by tests):
        - return value ∈ [0.0, 1.0]
        - identical embeddings → ≥ 0.5
        - opposite embeddings  → strictly less than identical
        - pairs_well_with boost → strictly higher than baseline
        - avoid_pairing_with    → strictly lower than baseline
    """
    from itertools import combinations

    if len(items) < 2:
        return 0.5

    # ── Step 1: embedding-based cosine base ─────────────────────────────────
    # Only include pairs where both items have a non-empty embedding.  Items
    # added before the image pipeline ran will have embedding=None and are
    # simply ignored in the average rather than dragging it toward 0.
    pairs = list(combinations(items, 2))
    sims = [
        _cosine(a.embedding, b.embedding)
        for a, b in pairs
        if a.embedding and b.embedding
    ]
    # Map mean cosine from [-1, 1] into [0, 1].
    base: float = (sum(sims) / len(sims) + 1.0) / 2.0 if sims else 0.5

    # ── Step 2: curated override adjustments ────────────────────────────────
    ids = {it.id for it in items}
    # Count items that have at least one confirmed pairing partner in the outfit.
    boost = sum(
        1 for it in items if set(it.pairs_well_with) & (ids - {it.id})
    )
    # Count items that have at least one confirmed clash partner in the outfit.
    penalty = sum(
        1 for it in items if set(it.avoid_pairing_with) & (ids - {it.id})
    )

    # ── Step 3: combine and clamp ────────────────────────────────────────────
    return max(0.0, min(1.0, base + 0.10 * boost - 0.20 * penalty))
