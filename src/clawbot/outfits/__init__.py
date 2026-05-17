"""
Outfit scoring and candidate generation (build step 10).

The scoring layer is intentionally pure — the public API takes dataclasses and
returns dataclasses, with no DB or Discord knowledge. That keeps the formula
testable with Hypothesis and keeps the daily-push job (step 13) free to
compose this module however it wants.
"""

from clawbot.outfits.candidates import generate_candidates
from clawbot.outfits.compatibility import compute_compatibility
from clawbot.outfits.llm import OllamaConfig, pick_best_outfit
from clawbot.outfits.llm_schema import LLMChoice, OutfitChoice, build_fallback_choice
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
    "LLMChoice",
    "Outfit",
    "OllamaConfig",
    "OutfitChoice",
    "ScoreBreakdown",
    "ScoredOutfit",
    "ScoringContext",
    "WardrobeItem",
    "build_fallback_choice",
    "compute_compatibility",
    "generate_candidates",
    "pick_best_outfit",
    "score_outfit",
]
