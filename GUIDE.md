# Clawbot Operator Guide

Step-by-step setup for running Clawbot on your Debian NUC. Written so that
nothing is assumed — every command is explained, every "did it work?" check
is included, every common failure has a Troubleshooting note.

> **You'll need:** physical access (or SSH access) to the NUC, the NUC's IP
> address on your home network, a Discord account, and ~30 minutes for the
> first run-through. The first model download is ~2 GB, so a decent home
> internet connection helps but isn't required.

---

## Status of this guide

This is a **living document** that grows as the V1 build progresses. The
implementation has 15 build steps; the GUIDE has 15 operator sections that
roughly mirror them but are not identical. As of the current branch
`feat/backup-vacuum` (build Steps 1–14 complete):

- ✅ Sections **1–11** are complete and exercisable today.
- ✅ Section **7.5** (validate the image pipeline on the NUC) — all 3
  integration tests pass on NUC hardware.
- ✅ Section **8** (bootstrap your profile) — Step 4 wired the profile
  module and YAML loader; Step 6 added `/profile set` in Discord.
- ✅ Section **9** (add your first wardrobe item) — Step 7 shipped
  `/add_item`, `/edit_item`, `/forget_item` and the operator-only
  whitelist.
- ✅ Section **10** (auto-ingest from your phone) — Step 8 shipped the
  inbox watcher: drop a JPG/PNG/WEBP into
  `inbox/screenshots/`, the scheduler picks it up within 60 s, posts
  to the operator channel, and quarantines on failure. Hourly
  `disk_check` job also lives here.
- ✅ Section **11** (email forwarding) — Step 9 shipped the email
  parser for **Quince**, **UNIQLO**, **H&M**: drop a `.eml` into
  `inbox/email/` and the watcher splits it into 1..N wardrobe rows,
  with or without inline product images.
- 🛠️ Build Step **10** (outfit scorer) — pure-Python deterministic
  scorer with 5 sub-formulas (style_match, season, occasion_match,
  budget_alignment, duplicate_penalty) plus a `compute_compatibility()`
  function blending Fashion-CLIP pair cosine similarity with the
  curated `pairs_well_with` / `avoid_pairing_with` lists. No operator
  surface yet — feeds into Step 13 (daily push). Hypothesis property
  tests pin the total to the documented `[-25, 100]` range.
- 🛠️ Build Step **11** (LLM wrapper) — async Ollama client at
  `clawbot.outfits.pick_best_outfit()`. Sends the top-K scored
  candidates to `gemma3:1b`, parses a strict `{pick, reason}` JSON
  reply via Pydantic, retries on bad JSON / 5xx / timeout up to
  `llm_max_retries`, and falls back to the top-scored candidate when
  retries exhaust. No operator surface yet — feeds into Step 13.
- 🛠️ Build Step **12** (outfit collage) — Pillow-based 2×2 grid at
  `clawbot.outfits.build_collage()`. Default layout puts the hero
  (top or dress) in the top-left; renders labelled placeholders for
  items that don't yet have a thumbnail. Writes a 1024×1024 PNG.
  Feeds into Step 13.
- 🛠️ Build Step **13** (daily push) — `clawbot.outfits.run_daily_outfit()`
  + APScheduler cron `0 7 * * *`. Queries the wardrobe, scores
  candidates, asks `gemma3:1b` to pick a favourite, renders the
  collage, persists to `outfits` / `outfit_items`, and posts the
  image to Discord. Manual trigger via `run_job_now(sched, "daily_outfit")`.
- 🛠️ Build Step **14** (maintenance) — nightly tar.gz backup at 02:30
  with 14-day retention pruning, and weekly SQLite `VACUUM` at 03:00
  every Sunday. Both jobs write to `audit_log` so the operator can
  confirm they ran via `SELECT * FROM audit_log WHERE kind LIKE '%backup%'`.
- ⏳ Section **15** (docs wrap) is the final step:
  - 13. Backups and restores → **build Step 14**
  - 14. Maintenance → **build Step 14**
- 🧰 Section **15** (Troubleshooting) grows in place.

Each section ends with a **"How to verify"** subsection — never skip it. If
verification fails, jump to the **Troubleshooting** subsection at the end of
that same section before moving on.

---

## Where you are now

If you've followed this GUIDE on your NUC (`fidelicious@10.0.0.85`,
`~/FashionAgent`), you've already completed sections 1–7.5. To pull the
post-Step-9 build:

```bash
cd ~/FashionAgent
git pull
docker compose -f docker/docker-compose.yml build clawbot
docker compose -f docker/docker-compose.yml up -d clawbot
docker compose -f docker/docker-compose.yml logs -f clawbot | grep -E "Synced|Scheduler"
```

You should see one `Synced slash commands ...` line and one
`Scheduler started: inbox_sweep every 60s ...` line on startup.

From there:

1. Run **Section 8** if you haven't yet — bootstrap your style profile
   from `config/profile.bootstrap.yaml`.
2. Run **Section 9** to add your first item by hand with `/add_item`.
3. Run **Section 10** to wire the phone-to-NUC rsync and let the
   inbox watcher ingest screenshots in the background.
4. Run **Section 11** to forward retailer order/sale emails to the
   NUC so brand + price land in your wardrobe automatically.

After that, the next operator-facing milestone is the daily 07:00
outfit push — that needs build Steps 10 + 11 + 12 (scorer, LLM
wrapper, collage) before Section 12 can light up.

If you're new to this NUC and haven't done any setup yet, start at Section 1.

---

## Table of contents

- [Features and commands reference](#features-and-commands-reference) — start here if you just want to know what the bot can do
1. [Prerequisites and hardware check](#1-prerequisites-and-hardware-check)
2. [Install Docker and Docker Compose on Debian 13](#2-install-docker-and-docker-compose-on-debian-13)
3. [Clone the repo and create the directory tree](#3-clone-the-repo-and-create-the-directory-tree)
4. [Set up Discord (developer portal + bot invite)](#4-set-up-discord-developer-portal--bot-invite)
5. [Fill in `secrets/.env`](#5-fill-in-secretsenv)
6. [Start Ollama and pull the models](#6-start-ollama-and-pull-the-models)
7. [Start the clawbot container](#7-start-the-clawbot-container)
7.5. [Validate the image pipeline on the NUC](#75-validate-the-image-pipeline-on-the-nuc)
8. [Bootstrap your profile](#8-bootstrap-your-profile)
9. [Add your first wardrobe item](#9-add-your-first-wardrobe-item)
10. [Set up auto-ingest from your phone](#10-set-up-auto-ingest-from-your-phone)
11. [Set up email forwarding for retailer mails](#11-set-up-email-forwarding-for-retailer-mails)
12. [Verify the daily 7am outfit push](#12-verify-the-daily-7am-outfit-push)
13. [Backups and restores](#13-backups-and-restores)
14. [Maintenance](#14-maintenance)
15. [Troubleshooting](#15-troubleshooting-cookbook)

---

## Features and commands reference

Everything FashionAgent does in V1, grouped by how you interact with it.
Each entry has a one-line summary plus a pointer into the GUIDE for the
full setup or verification recipe.

### Slash commands (Discord)

All commands are gated to your `DISCORD_USER_ID` — nobody else in the
server can invoke them.

| Command | What it does | Notes |
|---|---|---|
| `/health` | Show bot health: DB connectivity, Ollama reachability, last successful job timestamps. | First thing to run when something feels off. See [Section 7](#7-start-the-clawbot-container). |
| `/profile show` | Print your full style profile (skin undertone, body shape, sizing, preferences, sensitivities…). | One row only — there's just one operator. |
| `/profile set <field> <value>` | Update a single profile field. Field names match the DB columns; `comfort_vs_style 7` etc. | Bulk-edit by editing `config/profile.bootstrap.yaml` and running the bootstrap script. See [Section 8](#8-bootstrap-your-profile). |
| `/wardrobe [category]` | Paginated list of active items. Filter by category (`tops`, `bottoms`, `dresses`, `outerwear`, `footwear`, `accessories`). | Soft-deleted items are hidden — use `include_deleted=true` in `sqlite3` if you need to recover one. |
| `/add_item <photo>` | Drop a photo in Discord; the bot runs it through rembg → Fashion-CLIP → colorthief, suggests category/colour/etc., asks you to confirm. | See [Section 9](#9-add-your-first-wardrobe-item) for the modal workflow. |
| `/edit_item <short_id> <field> <value>` | Edit any single field on an existing item. Use the first 8 chars of the uuid that `/wardrobe` shows. | All `wardrobe_items` columns are addressable. |
| `/forget_item <short_id>` | Soft-delete (sets `deleted_at`). The item still exists in the DB but won't appear in `/wardrobe` or outfits. | Restore by setting `deleted_at = NULL` in SQL. |

> **Planned but not yet shipped in V1:** `/outfit [occasion]` and
> `/backup_now`. The daily push (07:00 cron) and nightly backup (02:30
> cron) cover the same ground automatically — manual command versions
> are a V1.1 polish item.

### Automatic background jobs (in-process scheduler)

All of these run inside the clawbot container's APScheduler. No host-side
cron entries needed.

| Job | Schedule | What it does | Verify it ran |
|---|---|---|---|
| `inbox_sweep` | every 60s | Picks up new files in `inbox/screenshots/` and `inbox/email/`, runs the image pipeline or email parser, posts a draft to Discord. | `ls ~/FashionAgent/inbox/_processed/` |
| `disk_check` | hourly | Warns on Discord when disk usage crosses `health.disk_warn_pct` (default 85%). | Watch the operator channel after dropping a big file. |
| `daily_outfit` | `0 7 * * *` | Generates today's outfit, asks the LLM to pick from the top 3, renders a collage, posts it to Discord. | `SELECT * FROM outfits ORDER BY generated_at DESC LIMIT 1;` See [Section 12](#12-verify-the-daily-7am-outfit-push). |
| `nightly_backup` | `30 2 * * *` | tar+gzip `db/` + `images/` to `backups/clawbot-YYYY-MM-DD.tar.gz`, prune older than `backup.retain_days`. | `ls -lht ~/FashionAgent/backups/` See [Section 13](#13-backups-and-restores). |
| `db_vacuum` | `0 3 * * 0` | Sunday 03:00 SQLite VACUUM to reclaim space freed by deletes. | `SELECT * FROM audit_log WHERE kind='db_vacuum' ORDER BY ts DESC LIMIT 1;` |

### Ingestion surfaces

Three ways to add items to your wardrobe, in increasing order of automation:

| Surface | How to use | Where it lands |
|---|---|---|
| **Discord upload** | `/add_item` with a photo attachment. | Image pipeline → Discord confirmation modal → `wardrobe_items` row. |
| **Inbox screenshots** | `rsync`, `scp`, or AirDrop a JPG/PNG/WEBP into `~/FashionAgent/inbox/screenshots/` on the NUC. | Within 60s the watcher picks it up, runs OCR for brand/price, posts a draft to Discord, moves the file to `_processed/`. See [Section 10](#10-set-up-auto-ingest-from-your-phone). |
| **Forwarded email** | Forward a retailer order confirmation (Quince, UNIQLO, H&M) to your mail-handling script that drops the `.eml` into `~/FashionAgent/inbox/email/`. | Email parser splits into 1..N wardrobe rows (one per line item), posts each to Discord with brand + price + item name pre-filled. See [Section 11](#11-set-up-email-forwarding-for-retailer-mails). |

### Outfit recommendation engine

How the daily push and any future `/outfit` command work, from the inside:

1. **Candidate generation** — bucket every active item by role, filter by season, enumerate plausible combinations (top × bottom × footwear × optional outer, or dress × footwear), cap at 50.
2. **Deterministic scoring** — each candidate gets a score in `[-25, 100]`:
   - `style_match` (35) — colours match your favourites, avoid your dislikes
   - `compatibility` (25) — Fashion-CLIP cosine similarity + curated `pairs_well_with`/`avoid_pairing_with` overrides
   - `season` (15) — items tagged with the current season
   - `occasion_match` (15) — formality distance from the requested occasion
   - `budget_alignment` (10) — outfit total vs your `monthly_clothing_budget_usd`
   - `duplicate_penalty` (−25) — items you wore in the last ~14 outfits
3. **LLM tiebreaker** — top 3 candidates → `gemma3:1b` returns `{pick, reason}`. Retries on bad JSON; falls back to top-by-score if the LLM is unreachable.
4. **Collage** — 2×2 grid PNG via Pillow, hero piece in top-left.
5. **Persist + post** — write to `outfits` + `outfit_items`, send the collage + reason to Discord.

All five scoring weights live in `config/clawbot.yaml` under `scoring:` —
tune to taste without code changes.

### Data and configuration on disk

| Path (on the NUC) | What lives there |
|---|---|
| `~/FashionAgent/db/clawbot.db` | SQLite + sqlite-vec. Single source of truth. |
| `~/FashionAgent/config/clawbot.yaml` | All tunable knobs — model choice, schedule, scoring weights, retention. |
| `~/FashionAgent/secrets/.env` | `DISCORD_TOKEN`, `DISCORD_USER_ID`, `DISCORD_GUILD_ID`, `DISCORD_CHANNEL_ID`. **chmod 600.** |
| `~/FashionAgent/images/raw/` | Original uploads. |
| `~/FashionAgent/images/cutouts/` | Background-removed PNGs from rembg. |
| `~/FashionAgent/images/final/` | 512px thumbnails used in collages and `/wardrobe`. |
| `~/FashionAgent/images/outfits/` | Generated collage PNGs, one per `outfits` row. |
| `~/FashionAgent/inbox/{screenshots,email}/` | Drop new files here; watcher picks them up within 60s. |
| `~/FashionAgent/backups/` | Nightly tarballs. |
| `~/FashionAgent/logs/` | Structlog JSON, rotated daily. |

### Manual triggers (operator escape hatches)

Until `/outfit` and `/backup_now` ship as slash commands, you can force a
job from the host:

```bash
# Run today's outfit job immediately:
docker exec -it clawbot python -c "
import asyncio
from clawbot.scheduler import run_job_now
# (Inject scheduler from your bot's lifespan — see src/clawbot/main.py.)
"

# Snapshot the data trees right now (stops the container briefly):
docker compose -f docker/docker-compose.yml stop clawbot
tar -czf ~/FashionAgent/backups/manual-$(date +%F).tar.gz \
  -C ~/FashionAgent db images
docker compose -f docker/docker-compose.yml start clawbot
```

---

## 9. Add your first wardrobe item

### Add an item

1. In Discord, type `/add_item` and press space.
2. Attach a photo. On mobile Discord this opens the camera/gallery
   picker; on desktop, drag-and-drop or paste a clipboard image.
3. Optionally set `name` and `brand` parameters. If you skip them, the
   bot uses what Fashion-CLIP and OCR could infer.
4. Press enter.

The bot replies with the new item's short id (first 8 chars of the
uuid) and the draft attributes it inferred — category, subcategory,
formality, seasons, primary color, and any price OCR could read from a
retailer screenshot. Example:

```
✓ Added [a1b2c3d4] (unnamed) — COS
  category: tops/cardigan
  formality: casual
  seasons: fall, winter
  color: #1a2b3c

Use /edit_item a1b2c3d4 <field> <value> to correct anything.
```

### Correct or rename the item

Anything wrong? `/edit_item a1b2c3d4 name "Navy wool cardigan"`.
Field names match the columns on the `wardrobe_items` table — common
ones: `name`, `brand`, `subcategory`, `formality`, `seasons`,
`size_on_tag`, `size_true`, `condition`, `purchase_price_usd`,
`needs_tailoring`, `tailoring_notes`, `care`, `notes`.

List fields (`seasons`, `fabric`, `pairs_well_with`,
`avoid_pairing_with`) accept comma-separated input:
`/edit_item a1b2c3d4 seasons "fall, winter"`.

### Hide an item from recommendations

`/forget_item a1b2c3d4` soft-deletes the item — it disappears from
`/wardrobe` and won't appear in `/outfit` suggestions, but stays in the
DB so you can audit history or recover it later from sqlite directly.

### How to verify

```bash
sqlite3 ~/FashionAgent/db/clawbot.db \
    "SELECT substr(id,1,8) AS id, category, subcategory, name, brand \
     FROM wardrobe_items WHERE deleted_at IS NULL ORDER BY created_at DESC LIMIT 5;"
```

You should see the item you just added, plus any others.

### Troubleshooting

- **"Clawbot is thinking…" never resolves** — the image pipeline crashed
  inside the worker. Check
  `docker compose logs clawbot | tail -50`. The most common cause is
  out-of-memory while loading Fashion-CLIP: confirm
  `image_pipeline.lazy_load_models: true` in `config/clawbot.yaml`, then
  restart the container.
- **`/add_item` errors with "must be an image"** — Discord rejected the
  attachment before it reached the bot. Re-upload as JPG or PNG; HEIC
  from iOS sometimes needs conversion.
- **The reply says category: tops/?** — Fashion-CLIP's subcategory
  confidence fell below the threshold
  (`fashion_clip_confidence_threshold` in config). The item is still
  saved with the right top-level category; fix the subcategory with
  `/edit_item`.

---

## 10. Set up auto-ingest from your phone

> ✅ **Works today** (build Step 8 shipped the inbox watcher).
> Screenshots only; email forwarding lands in Step 9.

### How the watcher works

A scheduled job inside the clawbot process scans
`~/FashionAgent/inbox/screenshots/` every
`schedule.inbox_sweep_seconds` (default **60 s**). For each new image
file it runs the same pipeline `/add_item` uses (rembg → Fashion-CLIP
→ color → optional OCR → wardrobe row + embedding), then moves the
source into a hidden sibling directory so the next sweep doesn't
reprocess it:

```
inbox/
├── screenshots/                       ← drop files here
├── .processed/screenshots/2026-05-16/ ← successful ingests, by UTC date
└── .failed/screenshots/               ← anything that raised, with a UTC suffix
```

On success the bot posts to your `DISCORD_CHANNEL_ID` channel with the
new item's short id and inferred category — same shape as `/add_item`.
On failure it quarantines the file and posts a `:warning:` with the
exception type.

### Recommended desktop → NUC transport (rsync over SSH)

On a Mac, save your share-sheet target to
`~/Pictures/Screenshots-to-Clawbot/`. Then run this once-per-minute
cron line on the Mac:

```bash
# crontab -e
* * * * * rsync -avz --remove-source-files \
    ~/Pictures/Screenshots-to-Clawbot/ \
    fidelicious@10.0.0.85:~/FashionAgent/inbox/screenshots/ \
    >/tmp/clawbot-rsync.log 2>&1
```

`--remove-source-files` keeps the Mac folder clean after upload. The
watcher's 5-second mtime stability check ignores files mid-transfer,
so partial rsync uploads can't be ingested prematurely.

### From iPhone

Use AirDrop into the Mac folder above, or **Shortcuts** with a
"Save to Folder" action targeting the same path. Anything that lands
there gets rsync'd in within 60 s and ingested within 120 s.

### How to verify

1. Drop one JPG into `~/FashionAgent/inbox/screenshots/` directly on
   the NUC (skip the rsync for the smoke test):

   ```bash
   cp ~/some-cardigan.jpg ~/FashionAgent/inbox/screenshots/
   ```

2. Within 60 s, Discord should post a `:new:` message in your bot
   channel with the new item's short id.

3. Confirm the file moved:

   ```bash
   ls ~/FashionAgent/inbox/screenshots/        # empty (or only stuck files)
   ls ~/FashionAgent/inbox/.processed/screenshots/  # has today's date dir
   ```

4. Confirm the row:

   ```bash
   sqlite3 ~/FashionAgent/db/clawbot.db \
       "SELECT substr(id,1,8) id, category, subcategory, image_raw_path \
        FROM wardrobe_items WHERE deleted_at IS NULL ORDER BY created_at DESC LIMIT 1;"
   ```

5. To force a sweep without waiting, add an admin `/sweep` command in a
   later step or just `docker compose restart clawbot` and check that
   `inbox_sweep` runs on startup.

### Disk-usage warnings

The same scheduler that runs `inbox_sweep` also runs `disk_check` on
the `schedule.disk_check` cron (default hourly). When usage on
`paths.home` exceeds `health.disk_warn_pct` (default 85%) or
`health.disk_critical_pct` (95%), the bot posts a one-time alert into
the operator channel — the inbox watcher is the most disk-heavy thing
in V1, so it owns this guardrail. Alerts are also written to
`audit_log` with kind `disk_alert`.

### Troubleshooting

- **Files pile up in `inbox/screenshots/` and nothing happens** — the
  scheduler didn't start. `docker compose logs clawbot | grep
  "Scheduler started"` should show one line at boot. If absent,
  `discord.enabled` is false or the bot is in foundation-idle mode.
- **File gets moved to `.failed/` immediately** — open the file, check
  it's a real image (`file <path>`). If it is, look in
  `audit_log` for the matching `inbox_failed` row to see the
  exception class.
- **Bot replies "channel not in cache"** — `DISCORD_CHANNEL_ID` in
  `secrets/.env` points at a channel the bot can't see (wrong server,
  no "View Channel" permission). Reinvite or fix the perms.
- **Sweep runs but the wardrobe row never appears** — the image
  pipeline raised mid-flight; the file is in `.failed/`. Most common
  on this NUC: OOM during Fashion-CLIP load. Confirm
  `image_pipeline.lazy_load_models: true`.

---

## 11. Set up email forwarding for retailer mails

> ✅ **Works today** (build Step 9 shipped the email parser).
> V1 retailers: **Quince**, **UNIQLO**, **H&M**. Adding more is a
> ~30-line PR (see "Add a new retailer" below).

### How it works

Drop a `.eml` file into `~/FashionAgent/inbox/email/`. The same
scheduler that runs `inbox_sweep` (Section 10) picks it up within
60 s and:

1. Parses the email's `From:` header to find the retailer.
2. Walks the HTML body for one or more product rows (name + price).
3. Extracts the inline product image, if any, and runs it through
   the same vision pipeline `/add_item` uses — but overrides
   brand/name/price with the regex-extracted values (retailer email
   data is more reliable than OCR on a screenshot).
4. If the email has **no image** (sale alert, wishlist drop), a
   text-only wardrobe row is inserted with the brand + price, and
   you get a `:bust_in_silhouette:` Discord message asking you to
   attach a photo later via `/edit_item` or by dropping one into
   `inbox/screenshots/`.
5. The `.eml` itself moves into `inbox/.processed/email/<date>/`.
   Unknown senders or parse failures land in `inbox/.failed/email/`
   with a `:warning:` notification.

One multi-item order email becomes N separate wardrobe rows — you
get one Discord message per item.

### Fastest setup: Gmail → forward to NUC inbox

This route needs zero extra software on the NUC. Filters at Gmail
mark the right emails, an Apple Mail rule on your Mac saves them as
`.eml`, and rsync delivers them.

1. **In Gmail**, set up forwarding *or* a label + filter:
   - Create label `retailer-orders`.
   - Filter rule: `from:(@quince.com OR @uniqlo.com OR @hm.com)`
     → "Apply label retailer-orders" + "Forward to <your Mac
     Apple-Mail address>".
2. **On your Mac, in Apple Mail**:
   - Rule: "If from any of [...the same domains...] save attachment
     to `~/Mail-Drops/clawbot-emails/`, then **Save raw message**
     to the same folder."
3. **Reuse the rsync cron from Section 10** but add a second line:
   ```bash
   * * * * * rsync -avz --remove-source-files \
       ~/Mail-Drops/clawbot-emails/ \
       fidelicious@10.0.0.85:~/FashionAgent/inbox/email/ \
       >>/tmp/clawbot-rsync.log 2>&1
   ```

### Verify

1. Forward a real Quince/UNIQLO/H&M confirmation to yourself.
2. Save it via Apple Mail / Outlook / Thunderbird → "Save as → .eml".
3. SCP it to the NUC:
   ```bash
   scp ~/Downloads/order-12345.eml \
       fidelicious@10.0.0.85:~/FashionAgent/inbox/email/
   ```
4. Within 60 s, Discord should post a `:new:` (or `:bust_in_silhouette:`
   if there was no image) per item in the email.
5. Inspect the row:
   ```bash
   sqlite3 ~/FashionAgent/db/clawbot.db \
       "SELECT substr(id,1,8) id, brand, name, purchase_price_usd \
        FROM wardrobe_items ORDER BY created_at DESC LIMIT 5;"
   ```

### Add a new retailer

Open
[src/clawbot/inbox/email_parser.py](src/clawbot/inbox/email_parser.py)
and:

1. Write a `parse_<retailer>(msg, source_path) -> list[EmailItem]`
   function. The shared helpers `_html_body`, `_inline_images`,
   `_resolve_cid_image`, and `_parse_price` cover most cases.
2. Register the domain in `RETAILER_PARSERS` and `_DOMAIN_TO_NAME`.
3. Add a synthetic-fixture test in
   [tests/inbox/test_email_parser.py](tests/inbox/test_email_parser.py)
   that mirrors the new retailer's HTML structure.

### Troubleshooting

- **`.eml` keeps landing in `.failed/email/`** — check the audit log
  for `inbox_failed` rows: a `UnknownRetailerError` means the
  `From:` domain isn't registered; a `ParseFailedError` means the
  retailer's template drifted and the regex needs tuning. Forward
  one example to yourself, open the .eml in a text editor, and
  adjust the row/name/price regex in `email_parser.py`.
- **Wardrobe row has `category=unknown`** — that's the default for
  text-only rows. Run `/edit_item <shortid> category=tops`
  (or whatever the real category is) once you've attached a photo.
- **Multi-item order produced fewer rows than expected** — the
  retailer's HTML uses a different row delimiter than the synthetic
  fixture. Same fix as above.

---

## 12. Verify the daily 7am outfit push

> ✅ **Works today** (build Step 13). The scheduler fires `daily_outfit`
> on the cron in `clawbot.yaml` (default `0 7 * * *`).

### What the job does

1. Lists every active wardrobe item.
2. Generates plausible outfit candidates (filtered by current season),
   scores each, keeps the top 3.
3. Asks `gemma3:1b` over Ollama to pick one with a one-sentence reason.
   Retries on bad JSON; falls back to the highest-scored if the LLM is
   unreachable.
4. Renders a 1024×1024 collage to `~/FashionAgent/images/outfits/`.
5. Writes one row to `outfits` and one row per item to `outfit_items`.
6. Posts the collage + the LLM reason to the operator Discord channel.

### How to verify after the next 7am tick

```bash
# Today's outfit row, if any:
sqlite3 ~/FashionAgent/db/clawbot.db "SELECT id, score, llm_explanation FROM outfits ORDER BY generated_at DESC LIMIT 1;"

# And the collage that was sent:
ls -lht ~/FashionAgent/images/outfits/ | head -5
```

You should also see one Discord message in the operator channel with the
collage attached. If the LLM was unreachable, the message will be prefixed
`[LLM fallback]` — that's an operator-visible signal, not a failure.

### Trigger it manually for testing

Open a Python shell in the running container and call:

```bash
docker exec -it clawbot python -c "
import asyncio
from clawbot.outfits.daily import run_daily_outfit
# (Wire up repo + notifier from your bot context.)
"
```

The cleaner path lands in **Step 14** (CLI entry point). For now, restart
the container at 06:55 and watch the 07:00 tick fire.

### Troubleshooting

- **No Discord message at 7am** — check `docker compose logs -f clawbot |
  grep daily_outfit`. The job logs each stage; a silent run means the cron
  trigger isn't firing (usually a typo in `clawbot.yaml`'s `daily_outfit:
  "0 7 * * *"`).
- **Message arrived without an image** — collage write failed. Check disk
  space (`df -h ~/FashionAgent`) and the warning log line.
- **Operator wardrobe is empty** — the job posts a clear "wardrobe is
  empty" message instead of crashing. Run `/add_item` a few times and
  wait for the next tick.
- **Outfit keeps recommending the same items** — `duplicate_penalty` is
  capped at the last ~14 outfits. Wear count and other variety levers
  land in V2.

---

## 13. Backups and restores

> ✅ **Works today** (build Step 14). Two automated jobs run inside the
> clawbot container — no host-side cron needed.

### What runs and when

| Job | Cron | Action |
|---|---|---|
| `nightly_backup` | `30 2 * * *` | tar+gzip the paths in `backup.include` (default `/data/db` + `/data/images`) into `/data/backups/clawbot-YYYY-MM-DD.tar.gz`, then prune anything older than `backup.retain_days` (default 14). |
| `db_vacuum`      | `0 3 * * 0`  | Run SQLite `VACUUM` to defragment `clawbot.db`. Reclaims space freed by `/forget_item` and outfit churn. |

Each job writes one row to `audit_log` so the operator can confirm it ran.

### How to verify the next morning

```bash
# Was the tarball created?
ls -lht ~/FashionAgent/backups/ | head -5

# Did the audit log capture it?
sqlite3 ~/FashionAgent/db/clawbot.db \
  "SELECT ts, kind, message FROM audit_log
    WHERE kind IN ('nightly_backup', 'db_vacuum')
    ORDER BY ts DESC LIMIT 5;"
```

You should see a `nightly_backup` row each day and a `db_vacuum` row every
Sunday morning.

### Restore from a backup

Stop the container first so SQLite isn't being written to mid-restore:

```bash
docker compose -f docker/docker-compose.yml stop clawbot

# Extract into a sibling directory and inspect it before swapping in.
mkdir -p ~/FashionAgent/restore-test
tar -xzf ~/FashionAgent/backups/clawbot-2026-05-17.tar.gz \
  -C ~/FashionAgent/restore-test/

# Sanity check: the restored DB should open.
sqlite3 ~/FashionAgent/restore-test/db/clawbot.db \
  "SELECT COUNT(*) FROM wardrobe_items;"
```

When you're satisfied:

```bash
# Move the live data aside (don't delete until you've confirmed the restore).
mv ~/FashionAgent/db    ~/FashionAgent/db.broken
mv ~/FashionAgent/images ~/FashionAgent/images.broken

# Swap in the restored copy.
mv ~/FashionAgent/restore-test/db     ~/FashionAgent/db
mv ~/FashionAgent/restore-test/images ~/FashionAgent/images

# Start back up.
docker compose -f docker/docker-compose.yml start clawbot
```

If the bot comes up clean (`/health` returns green), remove the
`*.broken` directories at your leisure.

### Manually trigger a backup now

Useful before risky migrations:

```bash
docker exec clawbot python -c "
import asyncio
from clawbot.scheduler import run_job_now
# (Wire up scheduler from your running bot context — see app.py.)
"
```

Cleaner CLI lands in Step 15. For now, the cleanest "right now" snapshot is
to stop the container and tar the host paths directly:

```bash
docker compose -f docker/docker-compose.yml stop clawbot
tar -czf ~/FashionAgent/backups/manual-$(date +%F).tar.gz \
  -C ~/FashionAgent db images
docker compose -f docker/docker-compose.yml start clawbot
```

### Troubleshooting

- **No new tarball appearing** — check `docker compose logs -f clawbot |
  grep backup`. A silent run usually means the cron didn't fire (typo in
  `schedule.nightly_backup`). The audit log will show the last successful run.
- **Tarball grew unexpectedly** — `images/raw/` is the usual culprit once
  the wardrobe stabilises. Add `"**/raw/**"` to `backup.exclude_globs` in
  `clawbot.yaml` and restart the container.
- **`PRAGMA database_list` returns no file path in the vacuum log** —
  you're running against `:memory:`. VACUUM still runs; the size readout
  is just 0/0.

---

## 14. Maintenance

> ✅ **Works today** (build Step 14 shipped the cron jobs; the recipes
> below cover everything you'll touch by hand).

### Update the LLM

Pulling a newer or larger Gemma keeps the daily outfit reasons fresh.

```bash
# Pull a new model:
docker exec -it clawbot-ollama ollama pull gemma3:1b

# Or experiment with a bigger one (RAM permitting — 3B is borderline on 8 GB):
docker exec -it clawbot-ollama ollama pull qwen2.5:3b

# Switch which model the daily push uses:
$EDITOR ~/FashionAgent/config/clawbot.yaml
# … change models.llm: "qwen2.5:3b" …
docker compose -f docker/docker-compose.yml restart clawbot

# Verify the change took:
docker exec clawbot grep '^  llm:' /data/config/clawbot.yaml
```

If the new model is too slow, switch back the same way — your wardrobe and
outfit history are untouched.

### Update Python dependencies

```bash
cd ~/FashionAgent
$EDITOR pyproject.toml   # bump versions in [project.dependencies]
docker compose -f docker/docker-compose.yml build --no-cache clawbot
docker compose -f docker/docker-compose.yml up -d clawbot
docker compose -f docker/docker-compose.yml logs -f clawbot | head -50
```

Run the test suite locally before rebuilding to catch breakage early:

```bash
source .venv/bin/activate
pip install -e ".[dev,vision,discord,scheduler,email,llm,api]"
pytest
```

### Inspect the database

`sqlite3` is the readonly Swiss army knife:

```bash
sqlite3 ~/FashionAgent/db/clawbot.db

# Useful queries once you're in the shell:
.tables
.schema wardrobe_items
SELECT COUNT(*) FROM wardrobe_items WHERE deleted_at IS NULL;
SELECT id, score, llm_explanation, generated_at FROM outfits ORDER BY generated_at DESC LIMIT 10;
SELECT ts, kind, message FROM audit_log ORDER BY ts DESC LIMIT 20;
.quit
```

Use `\` instead of `;` to break long queries across lines.

### Free disk space

```bash
# 1. Container/image cruft:
docker system prune -a

# 2. Old originals — once cutouts are stable you don't strictly need raw/:
du -sh ~/FashionAgent/images/*
# If raw/ dominates, set backup.exclude_globs to skip it in nightly tarballs
# (see Section 13), then archive or delete the directory's contents.

# 3. Old backups (the prune job handles this automatically, but you can
#    nuke older snapshots safely):
ls -lht ~/FashionAgent/backups/ | tail -10
```

The `nightly_backup` job already prunes anything older than
`backup.retain_days`. The button to push is in `clawbot.yaml`, not at the
command line.

### Confirm the scheduled jobs ran

```bash
sqlite3 ~/FashionAgent/db/clawbot.db \
  "SELECT ts, kind FROM audit_log
    WHERE kind IN ('nightly_backup', 'db_vacuum', 'daily_outfit_shipped')
    ORDER BY ts DESC LIMIT 10;"
```

You should see one `nightly_backup` row each day, one `db_vacuum` each
Sunday, and one `daily_outfit_shipped` each morning after the 07:00 tick.

### Rotate Discord credentials

If your token leaks or you want to migrate to a new bot:

```bash
$EDITOR ~/FashionAgent/secrets/.env
# … update DISCORD_TOKEN= … (and DISCORD_GUILD_ID if the new bot is in a different server)
docker compose -f docker/docker-compose.yml restart clawbot
```

The old token can be revoked from the Discord Developer Portal → Bot →
Reset Token.

### Keeping it running

Both containers ship with `restart: unless-stopped`
([docker-compose.yml:18,48](docker/docker-compose.yml#L18)). Here's the
full behaviour matrix:

| Event | Behaviour | Action needed |
|---|---|---|
| Bot crashes (Python exception, OOM, etc.) | Docker restarts the container immediately. | None |
| Ollama crashes | Docker restarts it. | None |
| NUC reboots (planned `sudo reboot`) | Docker daemon starts on boot **if you enabled it** — see below. | One-time setup |
| NUC loses power, comes back | Same as reboot — depends on Docker auto-start. | One-time setup |
| You ran `docker compose down` manually | Containers stay down until you bring them back up. | Manual `up -d` |
| You ran `docker compose stop clawbot` | Same — stays stopped until you `start` it. | Manual `start` |

`unless-stopped` is the right policy: it restarts on crashes but respects
your explicit `stop` (so you don't fight Docker when debugging).

#### One-time setup: Docker on boot

You almost certainly want this. Run once on the NUC:

```bash
sudo systemctl enable docker
sudo systemctl is-enabled docker   # expect: enabled
```

After this, a power cycle → Docker daemon starts → both containers come
back automatically.

Test it without rebooting:

```bash
sudo systemctl restart docker
sleep 10
docker compose -f ~/FashionAgent/docker/docker-compose.yml ps
# both containers should show "Up"
```

#### How to confirm everything's really running

Three checks together give you full confidence:

```bash
# 1. Containers are up:
docker compose -f ~/FashionAgent/docker/docker-compose.yml ps

# 2. Bot logged the real startup banners (not the foundation-pass stub):
docker compose -f ~/FashionAgent/docker/docker-compose.yml logs clawbot --tail 50 \
  | grep -E 'Starting Discord|Synced|Scheduler started'

# 3. Discord shows the bot online with a green dot.
```

If all three pass, you're good.

#### Quick remote health check from your Mac

```bash
ssh fidelicious@10.0.0.85 \
  "docker compose -f ~/FashionAgent/docker/docker-compose.yml ps --format 'table {{.Service}}\t{{.Status}}'"
```

Or just type `/health` in Discord — fastest way to confirm DB + Ollama + bot
are all happy.

#### Big red button: full restart

If something's wrong and you don't want to investigate yet, this resets
everything cleanly **without** losing data:

```bash
cd ~/FashionAgent
docker compose -f docker/docker-compose.yml restart
sleep 10
docker compose -f docker/docker-compose.yml logs clawbot --tail 50
```

Your DB, images, inbox, and backups live on the host filesystem (bind
mounts at lines 59-66 of the compose file) — restarting containers never
touches them.

---

## 15. Troubleshooting cookbook

This section grows over time. Check it before opening a fresh investigation.

For named failure modes with full procedures, see
**[docs/runbooks/](docs/runbooks/)** — one file per failure mode (LLM
unavailable, disk full, database locked, etc.) following a consistent
*Symptom → Diagnose → Fix → Prevent* format.

### "Something's wrong but I don't know what" — diagnostic flowchart

Three categories cover almost everything. Pick the one that matches your
symptom, run the listed checks, then jump to the specific section the
output points you to.

| What you see | Where to start |
|---|---|
| Bot shows offline in Discord (grey dot) | **Step 1** below |
| Daily 7am message didn't arrive | **Step 2** below |
| Both — or "it's broken in some other way" | **Step 3** below |

#### Step 1: is the container running?

```bash
docker compose -f ~/FashionAgent/docker/docker-compose.yml ps
```

- **Status `Up`** → container is fine; problem is Discord-side. See
  [docs/runbooks/discord-token-expired.md](docs/runbooks/discord-token-expired.md).
- **Status `Restarting`** → it's in a crash loop. Go to Step 3.
- **Status `Exited` or missing** → bring it back:
  `docker compose -f ~/FashionAgent/docker/docker-compose.yml up -d`.

#### Step 2: did the cron actually fire?

```bash
sqlite3 ~/FashionAgent/db/clawbot.db \
  "SELECT ts, kind, message FROM audit_log
   WHERE kind LIKE '%outfit%' OR kind LIKE '%backup%' OR kind LIKE '%vacuum%'
   ORDER BY ts DESC LIMIT 10;"
```

If you don't see a row from this morning, follow
[docs/runbooks/daily-outfit-failed.md](docs/runbooks/daily-outfit-failed.md).

#### Step 3: read the logs

```bash
# Last 200 lines, errors and warnings only:
docker compose -f ~/FashionAgent/docker/docker-compose.yml logs clawbot --tail 200 \
  | grep -iE 'error|warn|exception|traceback'

# If that's quiet but the container is restarting, get everything unfiltered:
docker compose -f ~/FashionAgent/docker/docker-compose.yml logs clawbot --tail 200
```

The **first** traceback or `ERROR` line is almost always the real cause —
later lines are usually downstream noise. Match it against the runbooks:

| Log fragment | Runbook |
|---|---|
| `LoginFailure: Improper token` | [discord-token-expired.md](docs/runbooks/discord-token-expired.md) |
| `database is locked` | [database-locked.md](docs/runbooks/database-locked.md) |
| `[Errno 28] No space left on device` | [disk-full.md](docs/runbooks/disk-full.md) |
| `httpx.ConnectError` / `ollama: connection refused` | [llm-unavailable.md](docs/runbooks/llm-unavailable.md) |
| Files piling up in `inbox/` but no sweep activity | [inbox-stuck.md](docs/runbooks/inbox-stuck.md) |
| `Clawbot starting (foundation-pass stub)` | The image is stale. You're on an old branch, or never rebuilt — see "I rebuilt but it's still the old code" below. |

### "I rebuilt but it's still the old code"

The Docker image bakes in `src/` at build time
([clawbot.Dockerfile](docker/clawbot.Dockerfile)). Pulling `main` on the
host doesn't update the running container until you also rebuild.

1. Confirm you're actually on `main`:
   ```bash
   cd ~/FashionAgent
   git status -sb     # expect: ## main...origin/main
   git log --oneline -3
   ```
   If `HEAD ->` points at any `feat/...` branch, switch:
   `git checkout main && git pull --ff-only`.

2. Force a no-cache rebuild — the layer cache may otherwise serve old
   `COPY src/` even after a branch change:
   ```bash
   docker compose -f ~/FashionAgent/docker/docker-compose.yml down
   docker compose -f ~/FashionAgent/docker/docker-compose.yml build --no-cache clawbot
   docker compose -f ~/FashionAgent/docker/docker-compose.yml up -d
   docker compose -f ~/FashionAgent/docker/docker-compose.yml logs -f clawbot --tail 100
   ```

3. Expected boot lines (in order):
   ```
   INFO clawbot.main: Starting Discord bot.
   INFO clawbot.main: Synced slash commands to guild <ID>
   INFO clawbot.main: Scheduler started: inbox_sweep every 60s, disk_check at '0 * * * *'
   ```
   If you instead see `Clawbot starting (foundation-pass stub)`, the
   image is still serving Step 1-4 code — re-check step 1.

### "I added `discord:` to clawbot.yaml but pydantic says `extra_forbidden`"

The `discord` block requires Step 6+ schema. If pydantic rejects it, your
running image predates Step 6 — apply the rebuild recipe above.

### "`pip install` says `externally-managed-environment`"

Debian 13 ships Python with PEP 668 protection — the system interpreter
refuses to install user packages. You are running `pip install` against
system Python instead of the project venv.

1. Make sure you've created the venv: `cd ~/FashionAgent && python3.12 -m venv .venv`.
2. Activate it: `source .venv/bin/activate` (your prompt should now start
   with `(.venv)`).
3. Re-run: `pip install -e ".[dev,vision]"`.

Or invoke the venv's pip directly without activating:
`~/FashionAgent/.venv/bin/pip install -e ".[dev,vision]"`.

Do **not** pass `--break-system-packages` — that pollutes the system
Python and can break Debian's own tools.

### "Ollama is too slow"

The 1B model on a 2012 CPU runs at ~15–25 tok/s. A 100-word reply takes
~5–10 seconds. If it's worse:

1. Confirm nothing else is hammering the CPU: `top` and look for >80%.
2. Confirm the model is loaded: `docker logs clawbot-ollama | tail -50`
   should *not* show "loading model" on every request — keep-alive should
   hold it.
3. Try a smaller model: `docker exec -it clawbot-ollama ollama pull qwen2.5:0.5b`
   then change `models.llm` in `config/clawbot.yaml`.

### "Bot doesn't respond in Discord"

1. Is the container running? `docker compose ps`.
2. Are intents enabled? Re-check 4.3 step 6 (Message Content + Server Members).
3. Is `DISCORD_USER_ID` correct? The bot ignores everyone else.
4. Is the bot online (green dot) in your member list? If grey, the token
   is wrong; rotate it (4.3 step 7).

### "Image pipeline ran out of memory"

The 8 GB budget is tight when Fashion-CLIP + rembg are both resident.

1. Confirm `image_pipeline.lazy_load_models: true` in `clawbot.yaml`
   (default true).
2. Restart the container: `docker compose restart clawbot`. Memory leaks
   in the vision libs do happen.
3. Long-term: move image jobs to your Mac via SSH (planned for V2).

### "Disk is full"

1. `df -h ~` to confirm.
2. `docker system prune -a` (frees old images/containers/builds).
3. `du -sh ~/FashionAgent/*` — if `images/raw/` is the culprit, its files are
   originals you no longer strictly need (cutouts and final thumbnails
   live elsewhere). Plan: a Step-14 retention policy will auto-thin.

### "I want to start over from scratch"

```bash
cd ~/FashionAgent
docker compose -f docker/docker-compose.yml down
rm -rf db/* images/*/* logs/* backups/* models/fashion-clip/*
# DO NOT delete models/ollama unless you want to re-download the LLM
docker compose -f docker/docker-compose.yml up -d
```

`secrets/.env` and `config/clawbot.yaml` are kept so you don't have to
redo Sections 4–6.
