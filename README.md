# Clawbot

Local-only personal fashion assistant. Runs on a home NUC. Talks to you on Discord.
Open source end-to-end, no paid services.

> **Smart stylist, not autonomous shopping bot.**

## What it does (V1)

- Tracks your wardrobe with rich per-item metadata (cardigan vs sweater, fabric, fit, formality, cost-per-wear).
- Stores a personal profile (skin undertone, body shape, sizing, lifestyle, sensitivities).
- Ingests new items three ways: Discord upload, screenshots dropped into a folder, forwarded retailer emails.
- Suggests outfits on demand and pushes a daily 7am pick to Discord.
- All data stays on your local network. No cloud, no telemetry.

## What's deferred to V2

Retailer scraping, web UI, learning from feedback, weather/calendar hooks, wardrobe gap analysis.

## Where to start

- **Operators (you):** read [GUIDE.md](GUIDE.md) — step-by-step setup written for someone who has never used Docker.
- **Developers:** read [docs/architecture.md](docs/architecture.md) (coming soon) and the [final plan](.claude/plans/task-help-me-finalize-abundant-sundae.md).
- **Original blueprint:** see [fashionClaw.md](fashionClaw.md) for the design rationale.

## Hardware target

- Intel NUC, x86_64, 8 GB RAM, Debian 13.
- The same Docker stack will run on any modest Linux box; performance is sized to the worst case.

## License

Personal project. Not licensed for redistribution.
