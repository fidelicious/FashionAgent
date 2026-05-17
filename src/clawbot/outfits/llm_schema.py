"""
Schema + fallback policy for the Ollama LLM wrapper.

This module is the **user-contribution surface** for build Step 11. The
HTTP plumbing, prompt building, and retry loop live in `llm.py`. What you
design here is:

  1. The strict response schema (`LLMChoice`) — what the wrapper accepts
     as "valid JSON from the model" before it gets returned to callers.
  2. The fallback policy (`build_fallback_choice`) — what the wrapper
     returns when every retry has failed.

Both pieces shape user experience:
  - A tighter schema → fewer "bad outfit" responses leak through, but
    more retries (and slower median latency on the 2012 NUC).
  - A more graceful fallback → outfits always get sent to Discord, but
    you may be hiding real LLM problems from yourself.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field

from clawbot.outfits.types import ScoredOutfit

# ─────────────────────────────────────────────────────────────────────────────
# Public result type — returned to callers regardless of LLM success/failure
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class OutfitChoice:
    """
    The final answer the wrapper hands back to its callers (Step 13 daily-push).

    Always valid — even when every LLM retry failed, the fallback policy
    guarantees a usable `pick` and `reason`. Check `fallback_used` if you
    want to render a different Discord embed colour / alert.
    """

    pick: int
    reason: str
    model: str
    attempts_used: int
    fallback_used: bool


# ─────────────────────────────────────────────────────────────────────────────
# 1. LLMChoice — strict response schema  ← USER CONTRIBUTION
# ─────────────────────────────────────────────────────────────────────────────
#
# This is what Pydantic enforces on the raw JSON Gemma returns. Anything that
# fails to parse OR fails schema validation is treated as a retry-worthy
# error in the loop. Trade-offs to consider:
#
#   - `pick`: int range. The wrapper passes the caller-supplied upper bound
#     in via _validate_pick_in_range() in llm.py — keep `le` here generous
#     so the schema itself doesn't reject before that explicit check runs.
#     (We use le=99 as a safety ceiling — no realistic top-K is that large.)
#
#   - `reason`: min/max length. Too tight and Gemma's verbose outputs get
#     rejected; too loose and you risk a multi-paragraph essay landing in
#     a Discord embed. 500 chars ≈ 100 words, a comfortable embed limit.
#
#   - Strict mode: setting `model_config = {"extra": "forbid"}` makes any
#     unexpected field cause validation to fail. Strict catches the model
#     hallucinating fields like `"confidence"`; lenient ignores them.
#
# Modify the field set / constraints below to match the prompt template you
# write. The test suite covers pick=5 (out of range) and reason="" (empty)
# as schema-violation cases — add tests if you tighten further.


class LLMChoice(BaseModel):
    """Strict schema for the Ollama response body."""

    pick: int = Field(ge=0, le=99, description="Index into the candidates list")
    reason: str = Field(min_length=1, max_length=500)

    model_config = {"extra": "forbid"}  # reject hallucinated fields


# ─────────────────────────────────────────────────────────────────────────────
# 2. build_fallback_choice — what to return when retries exhaust ← USER
# ─────────────────────────────────────────────────────────────────────────────


def build_fallback_choice(
    candidates: list[ScoredOutfit],
    model: str,
    attempts_used: int,
    error: Exception | None,
) -> OutfitChoice:
    """
    Build an OutfitChoice when every LLM attempt has failed.

    USER CONTRIBUTION OPPORTUNITY — the body below is a reasonable default
    (pick the deterministic top-scored candidate, name the failure in the
    reason). Trade-offs to consider:

      - Strategy for `pick`:
          * Top-by-score (current default) — deterministic, "best guess
            without help".
          * Random — diversity over reliability.
          * Raise — push the failure to the caller (Step 13 would then
            decide whether to skip the daily push entirely).

      - `reason` text:
          * Honest, e.g. "LLM unavailable; falling back to top-scored
            outfit." — gives you operator-visible failure feedback.
          * Cosmetic, e.g. "A balanced, season-appropriate choice." —
            hides the failure from your daily Discord message.

      - `fallback_used` is always True here so callers can branch on it.

    The contract enforced by tests:
        - returns a valid OutfitChoice (no exceptions),
        - `pick` is a valid index into `candidates`,
        - `fallback_used is True`,
        - `attempts_used` reflects what the caller passed in.
    """
    # Default policy: pick the highest-scored candidate. Stable order — ties
    # resolved by lowest index (max() returns the first occurrence).
    scores = [c.total for c in candidates]
    best_idx = scores.index(max(scores))

    reason = "LLM unavailable; using the highest-scored outfit instead."
    if error is not None:
        # Keep the error type in the reason so logs can correlate, but don't
        # spam the user with a Python traceback.
        reason = f"{reason} ({type(error).__name__})"

    return OutfitChoice(
        pick=best_idx,
        reason=reason,
        model=model,
        attempts_used=attempts_used,
        fallback_used=True,
    )
