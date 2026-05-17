"""
Tests for the Ollama LLM wrapper.

We never hit the real Ollama server. Every test installs an httpx MockTransport
that returns canned bodies, so the test suite stays hermetic and fast even
when the NUC is offline.

Coverage targets:
  - happy path: model returns clean JSON, wrapper returns parsed choice.
  - retry: first response is invalid JSON, second is valid → success.
  - retry exhaustion: every response invalid → fallback choice.
  - schema violation: pick out of range (5) → invalid → retry → fallback.
  - HTTP timeout / 5xx: treated as retry-worthy.
  - reason field stripped of whitespace and length-capped.
"""

from __future__ import annotations

import json

import httpx
import pytest

from clawbot.outfits.candidates import generate_candidates
from clawbot.outfits.llm import OllamaConfig, OutfitChoice, pick_best_outfit
from clawbot.outfits.score import score_outfit
from tests.outfits.conftest import make_item

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _ollama_body(text: str) -> bytes:
    """Mimic Ollama's /api/generate response envelope."""
    return json.dumps({"model": "gemma3:1b", "response": text, "done": True}).encode()


def _client_returning(*responses: httpx.Response) -> httpx.AsyncClient:
    """An httpx.AsyncClient that returns each response in order, then loops the
    last one (so 'retries forever' tests still terminate)."""
    iterator = iter(responses)
    last: httpx.Response | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal last
        try:
            last = next(iterator)
        except StopIteration:
            assert last is not None
        return last

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.fixture
def small_candidates(default_context):
    """Three plausible candidates the scorer would emit (3 tops × 1 × 1 = 3)."""
    wardrobe = [
        make_item(item_id="t1", category="tops", seasons=("fall",), formality="casual"),
        make_item(item_id="t2", category="tops", seasons=("fall",), formality="casual"),
        make_item(item_id="t3", category="tops", seasons=("fall",), formality="casual"),
        make_item(item_id="b1", category="bottoms", seasons=("fall",), formality="casual"),
        make_item(item_id="s1", category="footwear", seasons=("fall",), formality="casual"),
    ]
    cands = generate_candidates(wardrobe, default_context, max_candidates=3)
    return [score_outfit(c, default_context) for c in cands]


@pytest.fixture
def fast_config() -> OllamaConfig:
    """Tight retries so failure-path tests don't crawl."""
    return OllamaConfig(
        base_url="http://ollama-test:11434",
        model="gemma3:1b",
        timeout_seconds=1,
        max_retries=2,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Happy path
# ─────────────────────────────────────────────────────────────────────────────


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_clean_json_returns_parsed_choice(
        self, small_candidates, default_context, fast_config
    ):
        body = _ollama_body('{"pick": 1, "reason": "the cardigan adds warmth"}')
        client = _client_returning(httpx.Response(200, content=body))
        result = await pick_best_outfit(
            small_candidates, default_context, fast_config, client=client
        )
        assert isinstance(result, OutfitChoice)
        assert result.pick == 1
        assert "cardigan" in result.reason
        assert result.fallback_used is False
        assert result.attempts_used == 1

    @pytest.mark.asyncio
    async def test_reason_is_trimmed(self, small_candidates, default_context, fast_config):
        body = _ollama_body('{"pick": 0, "reason": "   nice   "}')
        client = _client_returning(httpx.Response(200, content=body))
        result = await pick_best_outfit(
            small_candidates, default_context, fast_config, client=client
        )
        assert result.reason == "nice"


# ─────────────────────────────────────────────────────────────────────────────
# Retry behaviour
# ─────────────────────────────────────────────────────────────────────────────


class TestRetries:
    @pytest.mark.asyncio
    async def test_garbage_then_valid_succeeds(
        self, small_candidates, default_context, fast_config
    ):
        bad = _ollama_body("garbage not-json")
        good = _ollama_body('{"pick": 2, "reason": "best fit"}')
        client = _client_returning(
            httpx.Response(200, content=bad),
            httpx.Response(200, content=good),
        )
        result = await pick_best_outfit(
            small_candidates, default_context, fast_config, client=client
        )
        assert result.pick == 2
        assert result.attempts_used == 2
        assert result.fallback_used is False

    @pytest.mark.asyncio
    async def test_schema_violation_then_valid(
        self, small_candidates, default_context, fast_config
    ):
        # pick=5 is out of [0, 2] — schema rejects, wrapper retries.
        bad = _ollama_body('{"pick": 5, "reason": "x"}')
        good = _ollama_body('{"pick": 0, "reason": "ok"}')
        client = _client_returning(
            httpx.Response(200, content=bad),
            httpx.Response(200, content=good),
        )
        result = await pick_best_outfit(
            small_candidates, default_context, fast_config, client=client
        )
        assert result.pick == 0
        assert result.attempts_used == 2

    @pytest.mark.asyncio
    async def test_http_5xx_triggers_retry(self, small_candidates, default_context, fast_config):
        good = _ollama_body('{"pick": 0, "reason": "ok"}')
        client = _client_returning(
            httpx.Response(503, content=b""),
            httpx.Response(200, content=good),
        )
        result = await pick_best_outfit(
            small_candidates, default_context, fast_config, client=client
        )
        assert result.pick == 0
        assert result.attempts_used == 2

    @pytest.mark.asyncio
    async def test_all_retries_exhausted_returns_fallback(
        self, small_candidates, default_context, fast_config
    ):
        bad = _ollama_body("still garbage")
        client = _client_returning(httpx.Response(200, content=bad))
        result = await pick_best_outfit(
            small_candidates, default_context, fast_config, client=client
        )
        assert result.fallback_used is True
        # Fallback picks the highest-scored candidate (index of max in input).
        scores = [c.total for c in small_candidates]
        assert result.pick == scores.index(max(scores))
        assert result.attempts_used == fast_config.max_retries + 1


# ─────────────────────────────────────────────────────────────────────────────
# Edge cases
# ─────────────────────────────────────────────────────────────────────────────


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_candidates_raises(self, default_context, fast_config):
        with pytest.raises(ValueError):
            await pick_best_outfit([], default_context, fast_config)

    @pytest.mark.asyncio
    async def test_single_candidate_skips_llm(self, default_context, fast_config):
        # With only one option, there's nothing for the LLM to pick — return
        # it directly with a canned reason, no HTTP call.
        wardrobe = [
            make_item(item_id="t", category="tops", seasons=("fall",)),
            make_item(item_id="b", category="bottoms", seasons=("fall",)),
            make_item(item_id="s", category="footwear", seasons=("fall",)),
        ]
        cands = generate_candidates(wardrobe, default_context)
        scored = [score_outfit(c, default_context) for c in cands]
        assert len(scored) == 1

        # No client passed — if the wrapper tried to call Ollama, it'd fail.
        result = await pick_best_outfit(scored, default_context, fast_config)
        assert result.pick == 0
        assert result.attempts_used == 0
