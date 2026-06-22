# FashionAgent

Local-only personal fashion assistant. Runs on a home NUC. Talks to you on Discord.
Open source end-to-end, no paid services.

> **Smart stylist, not autonomous shopping bot.**

## What it does (V1, shipping today)

- **Wardrobe tracking** — rich per-item metadata (cardigan vs. sweater, fabric, fit, formality, cost-per-wear), with soft-delete and edit history.
- **Style profile** — skin undertone, body shape, sizing, fit preferences, sensitivities, monthly budget. One row, your truth.
- **Three ingestion surfaces** — Discord `/add_item`, screenshot drop folder, forwarded retailer emails (Quince, UNIQLO, H&M).
- **Image pipeline** — rembg cutout → Fashion-CLIP embedding → zero-shot attribute classification → Tesseract OCR for brand/price.
- **Daily 7am outfit push** — deterministic scorer (style + compatibility + season + occasion + budget − duplicate penalty) ranks plausible outfits, Gemma 3 1B picks one with a one-sentence reason, Pillow renders a 2×2 collage, Discord receives the image.
- **Backups** — nightly tar.gz with retention pruning, weekly SQLite VACUUM. All scheduled in-process.
- **Hardened against the obvious failures** — LLM unreachable, Discord token expired, malformed email, missing images, FK violations: everything degrades to a logged warning, never a crash.

All data stays on your local network. No cloud, no telemetry, no third-party API calls.

## What's deferred to V2

Retailer scraping (Playwright), web UI (Open WebUI), feedback learning loop, weather/calendar hooks, wardrobe gap analysis, style clustering.

## Where to start

- **Operators (running it):** read **[GUIDE.md](GUIDE.md)** — step-by-step setup written for someone who has never used Docker. Start with the "Features and commands reference" section if you just want to know what the bot can do.
- **Developers (extending it):** the [build plan](.claude/plans/task-help-me-finalize-abundant-sundae.md) describes the 15-step incremental build that produced this codebase. Per-feature design docs are inline in each module's docstring (`src/clawbot/outfits/*.py` is the densest layer).
- **Failure modes:** see [docs/runbooks/](docs/runbooks/) for what to do when something specific breaks.
- **Original blueprint:** [fashionClaw.md](fashionClaw.md) holds the design rationale.

## Hardware target

- Intel NUC (or any x86_64 PC), 8 GB RAM, Debian 13.
- Memory budget: ~6 GB used / 8 GB total at steady state (Ollama + Gemma 3 1B Q4 + nomic-embed + Python). Image jobs peak ~1.5 GB during ingestion.
- The Docker stack runs on any modest Linux box; performance is sized to this worst case.

## Quick architecture

```
                    ┌──────────────────────────────────┐
You (Discord)  ──►  │              clawbot              │
                    │  Discord bot │ FastAPI healthz    │
                    │  APScheduler │ Image worker       │
                    │              │ Daily-outfit job   │
inbox/screenshots/  │       ▲                           │
inbox/email/    ──► │       │ HTTP                      │
                    │   ┌───┴────────┐                  │
                    │   │   Ollama   │ Gemma 3 1B       │
                    │   │            │ nomic-embed-text │
                    │   └────────────┘                  │
                    │                                   │
                    │   SQLite + sqlite-vec             │
                    │   ~/FashionAgent/db/clawbot.db    │
                    └──────────────────────────────────┘
```

LAN-only. No public exposure.

## How to Rebuild every time there is code change

### 1. Get the merged code
git checkout master
git pull

### 2. Rebuild + restart the clawbot container (code is baked into the image)
docker compose -f docker/docker-compose.yml build clawbot
docker compose -f docker/docker-compose.yml up -d clawbot

### 3. Confirm it came up cleanly
docker compose -f docker/docker-compose.yml logs -f clawbot | grep -E "Synced|Scheduler"


## License

Personal project. Not licensed for redistribution.

## TODO
- Add all data to NUC

- Change daily outfit msg to 8pm



## Known bugs