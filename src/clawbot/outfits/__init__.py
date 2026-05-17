"""
Outfit scoring and candidate generation (build step 10).

The scoring layer is intentionally pure — the public API takes dataclasses and
returns dataclasses, with no DB or Discord knowledge. That keeps the formula
testable with Hypothesis and keeps the daily-push job (step 13) free to
compose this module however it wants.
"""

from clawbot.outfits.adapter import (
    build_scoring_context,
    derive_season,
    from_db_item,
)
from clawbot.outfits.candidates import generate_candidates
from clawbot.outfits.collage import CollageConfig, build_collage
from clawbot.outfits.compatibility import compute_compatibility
from clawbot.outfits.daily import DailyResult, format_daily_message, run_daily_outfit
from clawbot.outfits.llm import OllamaConfig, pick_best_outfit
from clawbot.outfits.llm_schema import LLMChoice, OutfitChoice, build_fallback_choice
from clawbot.outfits.persist import OutfitRecord, OutfitsRepo
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
    "CollageConfig",
    "DailyResult",
    "LLMChoice",
    "Outfit",
    "OllamaConfig",
    "OutfitChoice",
    "OutfitRecord",
    "OutfitsRepo",
    "ScoreBreakdown",
    "ScoredOutfit",
    "ScoringContext",
    "WardrobeItem",
    "build_collage",
    "build_fallback_choice",
    "build_scoring_context",
    "compute_compatibility",
    "derive_season",
    "format_daily_message",
    "from_db_item",
    "generate_candidates",
    "pick_best_outfit",
    "run_daily_outfit",
    "score_outfit",
]
