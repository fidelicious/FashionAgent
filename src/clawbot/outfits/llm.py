"""
Ollama wrapper for outfit selection (build Step 11).

The deterministic scorer (`score.py`) ranks all candidates; this module asks
Gemma 3 1B to pick a favourite among the top-K and write a one-sentence
reason. The wrapper is hardened against the model's two most common
failures on a 1B parameter LLM: invalid JSON and out-of-range picks.

Strict separation:
  - this file: HTTP plumbing, prompt building, retry orchestration.
  - llm_schema.py: schema definition + fallback policy (user contribution).

The wrapper assumes the caller has already gated on
`config.health.llm_required_for_outfits`. If that flag is False, Step 13
should not call this function at all.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import httpx
import structlog
from pydantic import ValidationError

from clawbot.outfits.llm_schema import (
    LLMChoice,
    OutfitChoice,
    build_fallback_choice,
)
from clawbot.outfits.types import ScoredOutfit, ScoringContext

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class OllamaConfig:
    """
    Per-call LLM settings. Mirrors `ModelsConfig` in `config.py` but is
    decoupled — the daily-push job (Step 13) will translate
    `ClawbotConfig.models` → `OllamaConfig` at call time, so this module
    doesn't need to import the heavy pydantic-settings layer.
    """

    base_url: str
    model: str
    timeout_seconds: int = 60
    max_retries: int = 2


# ─────────────────────────────────────────────────────────────────────────────
# Prompt construction
# ─────────────────────────────────────────────────────────────────────────────


def _describe_outfit(scored: ScoredOutfit) -> str:
    """A single-line description for one candidate. Keeps the prompt compact
    so Gemma 3 1B's 8k context isn't wasted on token-heavy items."""
    parts = []
    for role, item in scored.outfit.items_by_role.items():
        descriptor = item.subcategory or item.category
        colour = item.color_primary or "unspecified colour"
        parts.append(f"{role}: {colour} {descriptor}")
    return f"{', '.join(parts)}  (score {scored.total:.1f})"


def _build_prompt(candidates: list[ScoredOutfit], ctx: ScoringContext) -> str:
    """Render the structured prompt. JSON-only, no markdown — Gemma is more
    likely to comply with a terse template than a long instruction set."""
    lines = [
        f"You are choosing one outfit for {ctx.occasion} wear in {ctx.season}.",
        "",
        f"Here are {len(candidates)} candidate outfits, indexed 0..{len(candidates) - 1}:",
    ]
    for i, c in enumerate(candidates):
        lines.append(f"  [{i}] {_describe_outfit(c)}")
    max_pick = len(candidates) - 1
    lines.extend(
        [
            "",
            "Return STRICT JSON ONLY with this exact shape:",
            f'  {{"pick": <integer 0..{max_pick}>, "reason": "<one short sentence>"}}',
            "No prose. No code fences. No commentary.",
        ]
    )
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Single-call layer
# ─────────────────────────────────────────────────────────────────────────────


# Errors we treat as retry-worthy. Anything else propagates immediately.
_RETRYABLE_EXCEPTIONS: tuple[type[Exception], ...] = (
    json.JSONDecodeError,
    ValidationError,
    httpx.HTTPStatusError,
    httpx.TimeoutException,
    httpx.HTTPError,  # parent — catches transport-level errors
    ValueError,  # pick > max_pick check below
)


async def _call_ollama(prompt: str, config: OllamaConfig, client: httpx.AsyncClient) -> str:
    """One Ollama call. Returns the model's text response or raises."""
    resp = await client.post(
        f"{config.base_url}/api/generate",
        json={"model": config.model, "prompt": prompt, "stream": False},
        timeout=config.timeout_seconds,
    )
    resp.raise_for_status()
    return resp.json().get("response", "")


def _parse_choice(text: str, max_pick: int) -> LLMChoice:
    """JSON → LLMChoice → bounds check. Raises a retry-worthy exception
    on any failure."""
    parsed = json.loads(text)
    choice = LLMChoice.model_validate(parsed)
    if choice.pick > max_pick:
        raise ValueError(f"pick {choice.pick} exceeds available max {max_pick}")
    return choice


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────


async def pick_best_outfit(
    candidates: list[ScoredOutfit],
    ctx: ScoringContext,
    config: OllamaConfig,
    *,
    client: httpx.AsyncClient | None = None,
) -> OutfitChoice:
    """
    Pick the best candidate via Gemma + reason text.

    Behaviour matrix:
      - 0 candidates       → ValueError (caller bug)
      - 1 candidate        → return it directly, no LLM call
      - 2+ candidates      → call Ollama, retry up to `config.max_retries`,
                             else `build_fallback_choice` decides.

    Parameters:
        candidates: typically top-3 from the scorer, but any 1..N is accepted.
        ctx:        the scoring context used to build the prompt (occasion,
                    season). Not used for any logic beyond prompt text.
        config:     Ollama URL / model / timeout / retry budget.
        client:     optional pre-built httpx.AsyncClient — pass one in from
                    tests with MockTransport, leave None in production to
                    let this function own the client lifecycle.
    """
    if not candidates:
        raise ValueError("pick_best_outfit requires at least one candidate")

    if len(candidates) == 1:
        return OutfitChoice(
            pick=0,
            reason="Only one candidate available.",
            model=config.model,
            attempts_used=0,
            fallback_used=False,
        )

    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient()

    max_pick = len(candidates) - 1
    prompt = _build_prompt(candidates, ctx)
    last_error: Exception | None = None
    # Total attempts = first call + retries, so the loop runs max_retries+1 times.
    total_attempts = config.max_retries + 1

    try:
        for attempt in range(1, total_attempts + 1):
            try:
                raw = await _call_ollama(prompt, config, client)
                choice = _parse_choice(raw, max_pick=max_pick)
                return OutfitChoice(
                    pick=choice.pick,
                    reason=choice.reason.strip(),
                    model=config.model,
                    attempts_used=attempt,
                    fallback_used=False,
                )
            except _RETRYABLE_EXCEPTIONS as exc:
                last_error = exc
                logger.warning(
                    "llm_call_failed",
                    attempt=attempt,
                    total_attempts=total_attempts,
                    error_type=type(exc).__name__,
                    error=str(exc)[:200],
                )

        logger.error(
            "llm_retries_exhausted",
            attempts=total_attempts,
            last_error=str(last_error)[:200] if last_error else None,
        )
        return build_fallback_choice(
            candidates=candidates,
            model=config.model,
            attempts_used=total_attempts,
            error=last_error,
        )
    finally:
        if owns_client:
            await client.aclose()
