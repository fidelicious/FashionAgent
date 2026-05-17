"""
Outfit scoring and candidate generation (build step 10).

The scoring layer is intentionally pure — the public API takes dataclasses and
returns dataclasses, with no DB or Discord knowledge. That keeps the formula
testable with Hypothesis and keeps the daily-push job (step 13) free to
compose this module however it wants.
"""

from clawbot.outfits.candidates import generate_candidates
from clawbot.outfits.compatibility import compute_compatibility
from clawbot.outfits.score import (
    WEIGHTS,
    ScoreBreakdown,
    score_outfit,
)
from clawbot.outfits.types import (
    Outfit,
    ScoredOutfit,
    ScoringContext,
    WardrobeItem,
)

__all__ = [
    "WEIGHTS",
    "Outfit",
    "ScoreBreakdown",
    "ScoredOutfit",
    "ScoringContext",
    "WardrobeItem",
    "compute_compatibility",
    "generate_candidates",
    "score_outfit",
]
