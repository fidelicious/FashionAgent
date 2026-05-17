"""
Daily 7am outfit orchestrator (build Step 13).

Wires every prior outfit-related step into one async coroutine:
    DB query → adapter → candidates → score → LLM pick → collage → persist → Discord.

The coroutine is intentionally dependency-injected so unit tests can supply
a fake notifier, a fake LLM `pick_fn`, and an in-memory DB. The
APScheduler binding (`scheduler.py`) wraps it with the production
dependencies.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from clawbot.db.repo import Repo
from clawbot.outfits.adapter import (
    build_scoring_context,
    derive_season,
    from_db_item,
)
from clawbot.outfits.candidates import generate_candidates
from clawbot.outfits.collage import build_collage
from clawbot.outfits.llm import OllamaConfig, pick_best_outfit
from clawbot.outfits.llm_schema import OutfitChoice
from clawbot.outfits.persist import OutfitsRepo
from clawbot.outfits.score import score_outfit
from clawbot.outfits.types import ScoredOutfit, ScoringContext

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Result dataclass
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DailyResult:
    """What the orchestrator returns. `outfit_id` is None when no outfit could
    be assembled (empty wardrobe, no season-matching items, etc.)."""

    outfit_id: str | None
    collage_path: str | None
    score: float
    occasion: str
    season: str
    fallback_used: bool


# ─────────────────────────────────────────────────────────────────────────────
# Dependency-injected types
# ─────────────────────────────────────────────────────────────────────────────


# Signature: (candidates, ctx, config, *, client=None) → OutfitChoice.
# Matches `clawbot.outfits.llm.pick_best_outfit`. We pass it in as a parameter
# so tests don't need to spin up an httpx mock — they hand in a 3-line fake.
PickFn = Callable[..., Awaitable[OutfitChoice]]


# Same protocol as clawbot.inbox.notify.Notifier (text + image). Duplicated
# here as a `Protocol` would force a cross-package import for type-only use.
class _NotifierLike:
    async def post(self, content: str) -> None: ...
    async def post_image(self, content: str, image_path: Path | str) -> None: ...


# ─────────────────────────────────────────────────────────────────────────────
# Message formatting — USER CONTRIBUTION SURFACE
# ─────────────────────────────────────────────────────────────────────────────
#
# This is what the operator sees in Discord every morning. Tune it for tone,
# information density, and how "honest" you want to be about fallback uses.
# 5-10 lines max, format-string style. Stays text-only — the image is sent
# as an attachment on the same message.
#
# Trade-offs to consider:
#   - Score number: useful for tuning weights, noisy for daily use.
#   - Fallback signalling: a clear "[LLM unavailable]" tag tells you when
#     to investigate; hiding it keeps the message clean.
#   - Emoji density: zero (operator vibe) ↔ many (assistant vibe).
#
# Replace the body of `format_daily_message` to taste.


def format_daily_message(
    *,
    scored: ScoredOutfit,
    choice: OutfitChoice,
    ctx: ScoringContext,
) -> str:
    """Build the Discord-bound text that accompanies the collage."""
    header = f"Today's {ctx.occasion} outfit for {ctx.season}:"
    body = choice.reason
    if choice.fallback_used:
        # Operator-visible signal that the LLM gave up — easy to swap to a
        # cosmetic message later if you'd rather hide failures.
        body = f"[LLM fallback] {body}"
    score_line = f"(score {scored.total:.0f} / 100)"
    return f"{header} {body} {score_line}"


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────────────────────────────────────


async def run_daily_outfit(
    *,
    repo: Repo,
    notifier: _NotifierLike,
    collage_dir: Path,
    occasion: str = "casual",
    season: str | None = None,
    today: date | None = None,
    pick_fn: PickFn = pick_best_outfit,
    ollama_config: OllamaConfig | None = None,
    top_k: int = 3,
) -> DailyResult:
    """
    Generate, score, pick, render, persist, and post one outfit.

    Designed to be called both by APScheduler (07:00 cron) and by manual
    operator triggers ("/admin run daily_outfit now").

    Failure modes:
      - empty wardrobe → posts a text warning, returns DailyResult with
        outfit_id=None. No exception.
      - LLM unreachable / bad JSON → `pick_best_outfit` handles its own
        retries + fallback; we render whatever it returns.
      - collage write fails / Discord send fails → logged, never raised.
    """
    today = today or date.today()
    resolved_season = season or derive_season(today)

    # 1. Query the wardrobe (active items only).
    active_items_db = repo.items.list_by_category(limit=10_000)
    if not active_items_db:
        await notifier.post(
            f"Daily outfit ({resolved_season}, {occasion}): your wardrobe is "
            "empty — add some items with /add_item to get tomorrow's outfit."
        )
        return DailyResult(
            outfit_id=None,
            collage_path=None,
            score=0.0,
            occasion=occasion,
            season=resolved_season,
            fallback_used=False,
        )

    # 2. Adapt to scoring dataclasses + fetch the duplicate-penalty signal.
    items = [from_db_item(it) for it in active_items_db]
    outfits_repo = OutfitsRepo(repo.conn)
    recently_worn = outfits_repo.recently_worn_ids()
    profile = repo.profile.get()
    ctx = build_scoring_context(
        profile,
        occasion=occasion,
        season=resolved_season,
        recently_worn_ids=recently_worn,
    )

    # 3. Candidates → score → top-K.
    cands = generate_candidates(items, ctx)
    if not cands:
        await notifier.post(
            f"Daily outfit ({resolved_season}, {occasion}): no items match "
            "this season + occasion. Add items or change occasion."
        )
        return DailyResult(
            outfit_id=None,
            collage_path=None,
            score=0.0,
            occasion=occasion,
            season=resolved_season,
            fallback_used=False,
        )
    scored = [score_outfit(c, ctx) for c in cands]
    scored.sort(key=lambda s: s.total, reverse=True)
    top = scored[:top_k]

    # 4. Ask the LLM to pick from the top-K.
    cfg = ollama_config or OllamaConfig(base_url="http://ollama:11434", model="gemma3:1b")
    choice = await pick_fn(top, ctx, cfg)
    winner = top[choice.pick]

    # 5. Render the collage. Build the role→image_path map from the DB
    # `image_final_path` column (which our scoring dataclass dropped).
    db_by_id = {it.id: it for it in active_items_db}
    image_paths: dict[str, Path | None] = {
        role: Path(db_by_id[item.id].image_final_path)
        if db_by_id.get(item.id) and db_by_id[item.id].image_final_path
        else None
        for role, item in winner.outfit.items_by_role.items()
    }
    collage_path = collage_dir / f"{uuid.uuid4().hex}.png"
    try:
        build_collage(winner.outfit, collage_path, image_paths=image_paths)
    except Exception as e:
        logger.warning("daily_outfit collage failed: %s: %s", type(e).__name__, e)
        # Still persist the choice + post a text message so the operator
        # at least knows the LLM ran.
        await notifier.post(
            format_daily_message(scored=winner, choice=choice, ctx=ctx) + "  (collage unavailable)"
        )
        return DailyResult(
            outfit_id=None,
            collage_path=None,
            score=winner.total,
            occasion=occasion,
            season=resolved_season,
            fallback_used=choice.fallback_used,
        )

    # 6. Persist.
    outfit_id = outfits_repo.save(
        scored=winner,
        choice=choice,
        collage_path=collage_path,
        occasion=occasion,
    )
    repo.audit.write(
        "daily_outfit_shipped",
        f"id={outfit_id} score={winner.total:.1f} fallback={choice.fallback_used}",
        actor="job:daily_outfit",
    )

    # 7. Post to Discord with the collage attached.
    message = format_daily_message(scored=winner, choice=choice, ctx=ctx)
    try:
        await notifier.post_image(message, collage_path)
    except Exception as e:
        logger.warning("daily_outfit notify failed: %s: %s", type(e).__name__, e)

    return DailyResult(
        outfit_id=outfit_id,
        collage_path=str(collage_path),
        score=winner.total,
        occasion=occasion,
        season=resolved_season,
        fallback_used=choice.fallback_used,
    )
