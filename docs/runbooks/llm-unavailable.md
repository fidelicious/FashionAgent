# LLM unavailable

## Symptom

One or more of:
- Daily Discord outfit message is prefixed `[LLM fallback]`.
- `pytest tests/outfits/test_llm.py` passes locally but the daily push always uses fallback.
- `audit_log.kind = 'daily_outfit_shipped'` rows include `fallback=True`.
- Manual `curl` to Ollama hangs or returns 5xx.

## Diagnose

```bash
# 1. Is the Ollama container running?
docker compose -f ~/FashionAgent/docker/docker-compose.yml ps

# 2. Is the model loaded?
docker exec clawbot-ollama ollama list

# 3. Does a direct generate call work?
curl -sS http://localhost:11434/api/generate \
  -d '{"model":"gemma3:1b","prompt":"hi","stream":false}' \
  --max-time 30 | head -c 500

# 4. Are there OOM kills in dmesg?
dmesg | tail -50 | grep -i 'killed\|oom'
```

## Fix

**If the container is down:**
```bash
docker compose -f ~/FashionAgent/docker/docker-compose.yml up -d ollama
```

**If the model isn't loaded:**
```bash
docker exec -it clawbot-ollama ollama pull gemma3:1b
```

**If you're being OOM-killed**, the LLM is too big for the current RAM
budget. Swap to a smaller model:

```bash
docker exec -it clawbot-ollama ollama pull qwen2.5:0.5b
$EDITOR ~/FashionAgent/config/clawbot.yaml   # models.llm: "qwen2.5:0.5b"
docker compose -f ~/FashionAgent/docker/docker-compose.yml restart clawbot
```

**If curl works but clawbot's HTTP client doesn't**, check
`models.ollama_base_url` — inside the clawbot container, it must be
`http://ollama:11434` (Docker DNS), **not** `http://localhost:11434`.

## Prevent

- The wrapper already retries `llm_max_retries` times before falling back. Bump the value if your LLM is reliable but slow.
- The fallback policy lives in [src/clawbot/outfits/llm_schema.py](../../src/clawbot/outfits/llm_schema.py). It picks the top-scored candidate so the outfit still ships — failure is operator-visible, not operator-blocking.
- Watch `audit_log` for sustained `fallback=True` runs: that's a signal to investigate before users notice.
