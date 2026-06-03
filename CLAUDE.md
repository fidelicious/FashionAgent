# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Naming note

The repo is **FashionAgent**, but the Python package, Docker containers, config keys, and env-var prefix are all **`clawbot`** (historical name). Both refer to the same project — don't "fix" the mismatch.

## Commands

The dev environment is a venv at `.venv`. Activate it (`source .venv/bin/activate`) or prefix commands with `.venv/bin/`.

```bash
# One-time dev install (all optional extras so every module imports):
pip install -e ".[dev,vision,discord,scheduler,email,llm,api]"

# Tests
pytest                                  # full suite
pytest tests/outfits/test_score.py      # one file
pytest tests/outfits/test_score.py::test_name   # one test
pytest -m "not integration"             # skip tests needing Ollama/external services
pytest -m slow                          # only the >1s tests

# Lint / format / type-check (also wired into pre-commit)
ruff check --fix . && ruff format .
mypy            # strict mode, files = src + tests

# Run the app locally
python -m clawbot.main                  # entry point; needs config + secrets (see below)

# Run the full stack (NUC / prod-like)
docker compose -f docker/docker-compose.yml up -d
```

Heavy runtime deps (`torch`, `rembg`, `transformers`, `pytesseract`) live in the `[vision]` extra and are **mocked in unit tests** — you do not need them installed to run `pytest`. mypy is configured to ignore their missing stubs.

## Configuration & secrets

- **Config**: `load_config()` in [config.py](src/clawbot/config.py) reads YAML from `$CLAWBOT_CONFIG` (default `/app/config/clawbot.yaml`), validates against pydantic models with `extra="forbid"`. Override any key via `CLAWBOT_<SECTION>__<KEY>` env vars (double-underscore separator, e.g. `CLAWBOT_LOGGING__LEVEL=DEBUG`). Use `config/clawbot.example.yaml` as the baseline.
- **Secrets** (Discord token, user/guild/channel IDs) come only from `secrets/.env` via process env, loaded by [discord_secrets.py](src/clawbot/discord_secrets.py) — **never** put them in YAML. The YAML stays safe to commit.

## Architecture

Single Python process (`clawbot.main`) that, when `discord.enabled=true`, runs a Discord bot + an in-process `AsyncIOScheduler` sharing one SQLite connection. When disabled, it idles until SIGTERM (foundation/bring-up mode). Built incrementally over 15 steps — git history and per-module docstrings track this; the build plan lives outside the repo at `~/.claude/plans/`.

Layered packages under `src/clawbot/`:

- **`db/`** — `connect()` opens SQLite with sqlite-vec loaded, WAL mode, `synchronous=FULL`, FK enforcement, and explicit `transaction()` (`BEGIN IMMEDIATE`). `Repo` is a **facade** exposing one attribute per domain (`profile`, `items`, `outfits`, `jobs`, `audit`). Schema is hand-rolled SQL in `db/migrations/NNNN_*.sql`, applied in order by `run_migrations()` (no ORM/Alembic).
- **`discord/`** — `build_bot()` wires a `commands.Bot` with a `CommandTree` subclass that gates **every** slash command on the single operator's user ID (`is_whitelisted`); unauthorized attempts are audit-logged and given a generic reply that never echoes the command name. Cogs (`cogs/health|profile|wardrobe|items`) are loaded as extensions in `main.py`.
- **`vision/`** — pure top-down image pipeline ([pipeline.py](src/clawbot/vision/pipeline.py)): cutout (rembg) → color palette → Fashion-CLIP embedding → zero-shot classify → optional OCR → `DraftItem`. No DB or Discord I/O. Models lazy-load and `release()` in a `finally` to stay within the 8 GB RAM budget.
- **`inbox/`** — filesystem + email ingestion in three independently-testable layers: `discover()` (pure scan) → `process_one()` (pipeline + persist + move to `.processed`/`.failed`) → `sweep()` (the scheduler job loop). Retailer email parsing in `email_parser.py` (Quince/UNIQLO/H&M).
- **`outfits/`** — **the densest layer.** Daily orchestrator ([daily.py](src/clawbot/outfits/daily.py)) chains: DB query → adapter → candidate generation → deterministic `score_outfit` (style + compatibility + season + occasion + budget − duplicate penalty; weights in `ScoringConfig`) → LLM pick (Gemma 3 1B via Ollama, strict JSON + retry) → Pillow collage → persist → Discord push. Has property tests (hypothesis).
- **`maintenance/`** — nightly tar.gz backup with retention pruning, weekly SQLite VACUUM.
- **`scheduler.py`** — `build_scheduler()` registers five jobs (`inbox_sweep`, `disk_check`, `daily_outfit`, `nightly_backup`, `db_vacuum`). Construction is split from `.start()` so tests stay clock-free.

## Conventions specific to this codebase

- **Dependency injection over globals.** Handlers and jobs receive a `BotContext` (repo + config + secrets) or explicit injected callables (`ingest`, `notify`, `pick_fn`). Never reach for `os.environ` or open a new DB connection inside a handler — everything needed is passed in. This is the seam that keeps tests synchronous, offline, and free of discord.py/Ollama.
- **Optional deps are lazy-imported** inside functions (e.g. `discord` inside `build_bot`, vision libs inside pipeline stages) so code paths that don't use them don't require the extra installed.
- **Graceful degradation is a hard requirement** (see README): LLM unreachable, expired token, malformed email, missing image, FK violation — each degrades to a logged warning, never a process crash.
- **Audit everything material.** Scheduler jobs and privileged actions write to `repo.audit`.
- **Tests for command handlers use fake `Interaction` objects** (`tests/discord/conftest.py`), not dpytest — the fakes enforce Discord's one-initial-response rule (defer-then-followup) to catch ordering bugs in CI.
