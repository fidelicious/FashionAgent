"""
Tests for compute_compatibility — the cosine-similarity-based pairing score.

⚠ The body of compute_compatibility is a user contribution (see
src/clawbot/outfits/compatibility.py). Until the formula is filled in, every
test in this module is marked xfail(strict=False) so the suite stays green.
Once you implement the function, flip `STRICT_XFAIL = True` to enforce it.

What each test pins:
  - return value is in [0.0, 1.0]
  - identical embeddings → score ≥ 0.5 (visually consistent → at least neutral)
  - opposite embeddings (cosine = -1) → score lower than identical
  - pairs_well_with boost makes the score strictly higher
  - avoid_pairing_with penalty makes the score strictly lower
"""

from __future__ import annotations

import numpy as np
import pytest

from clawbot.outfits.compatibility import compute_compatibility
from tests.outfits.conftest import make_item

STRICT_XFAIL = False  # Flip to True after compute_compatibility is implemented.


def _override_embedding(item, vec):
    """Return a copy of `item` with a different embedding."""
    return item.__class__(**{**item.__dict__, "embedding": tuple(float(x) for x in vec)})


class TestCompatibility:
    """Always-on invariants — must hold for any implementation, including the
    neutral placeholder."""

    def test_returns_unit_interval(self):
        top = make_item(item_id="t", embedding_seed=1)
        bot = make_item(item_id="b", category="bottoms", embedding_seed=2)
        score = compute_compatibility([top, bot])
        assert 0.0 <= score <= 1.0

    def test_identical_embeddings_at_least_neutral(self):
        v = np.ones(512, dtype=np.float32)
        v /= np.linalg.norm(v)
        top = _override_embedding(make_item(item_id="t"), v)
        bot = _override_embedding(make_item(item_id="b", category="bottoms"), v)
        assert compute_compatibility([top, bot]) >= 0.5


@pytest.mark.xfail(strict=STRICT_XFAIL, reason="compatibility body is a user contribution")
class TestCompatibilityFormula:
    """Invariants that require a real formula — fail today, will pass once you
    implement compute_compatibility(). Flip STRICT_XFAIL = True after to enforce."""

    def test_opposite_embeddings_lower_than_identical(self):
        v = np.ones(512, dtype=np.float32)
        v /= np.linalg.norm(v)
        top = _override_embedding(make_item(item_id="t"), v)
        bot_same = _override_embedding(make_item(item_id="b", category="bottoms"), v)
        bot_opp = _override_embedding(make_item(item_id="b", category="bottoms"), -v)
        same_score = compute_compatibility([top, bot_same])
        opp_score = compute_compatibility([top, bot_opp])
        assert opp_score < same_score

    def test_pairs_well_with_boosts_score(self):
        plain_top = make_item(item_id="t", embedding_seed=1)
        plain_bot = make_item(item_id="b", category="bottoms", embedding_seed=2)
        boosted_top = make_item(item_id="t", embedding_seed=1, pairs_well_with=("b",))
        baseline = compute_compatibility([plain_top, plain_bot])
        boosted = compute_compatibility([boosted_top, plain_bot])
        assert boosted > baseline

    def test_avoid_pairing_with_penalises_score(self):
        plain_top = make_item(item_id="t", embedding_seed=1)
        plain_bot = make_item(item_id="b", category="bottoms", embedding_seed=2)
        avoidant_top = make_item(item_id="t", embedding_seed=1, avoid_pairing_with=("b",))
        baseline = compute_compatibility([plain_top, plain_bot])
        penalised = compute_compatibility([avoidant_top, plain_bot])
        assert penalised < baseline
