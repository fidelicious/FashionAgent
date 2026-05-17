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

## 1. Prerequisites and hardware check

### What you need

- A NUC (or any x86_64 PC) running Debian 13 (Trixie).
- At least **8 GB RAM**. Less and the LLM will struggle.
- At least **50 GB free disk** in your home directory. Image storage adds up.
- Network access (LAN is enough; no public exposure required).
- A regular user account (we'll call yours `you` in examples). **Don't run
  this as root.**

### Reach the NUC over SSH

If the NUC is plugged in next to you with a keyboard and monitor, skip this
and just open a terminal on it. Otherwise, from your Mac:

```bash
# Replace with your NUC's IP. Find it on your router's "connected devices"
# page if you don't know it.
ssh you@192.168.1.42
```

### Confirm the hardware budget

Run these on the NUC. The first three are read-only — they don't change anything.

```bash
# How much RAM does it actually have?
free -h
# Look for the "Mem:" row, "total" column. Expect ~7.5G or higher.

# What's the CPU?
lscpu | grep -E '^(Model name|CPU\(s\)|Architecture)'
# We expect x86_64. Number of CPUs ideally 4+. The Ivy Bridge i5 is fine.

# How much disk space is free in your home directory?
df -h ~
# Look at "Avail". We need at least ~50G, ideally 100G+.
```

### How to verify

You should see RAM ≥ 7 GB available, an x86_64 CPU, and ≥ 50 GB free disk.
If any of these fail, **stop here** — adding more RAM or freeing disk is
much easier before installing software than after.

### Troubleshooting

- **`free` shows much less RAM than I expected** — a process may be hogging
  it. Run `ps aux --sort=-%mem | head -10` to see the top consumers.
- **`df` shows little free space** — `du -sh ~/* | sort -h` shows what's
  taking the space. Common culprits: old Docker images (`docker system prune`
  helps after Section 2).

---

## 2. Install Docker and Docker Compose on Debian 13

We install **Docker Engine** (the daemon that runs containers) and the
**Compose plugin** (which understands `docker-compose.yml` files).

### Why Docker

Containers package the application + every dependency into a single image.
When you upgrade clawbot, you swap the image — your data on disk doesn't
move, so upgrades are reversible. Without Docker we'd be tracking system
Python versions, OS package updates, and library conflicts by hand.

### Install

These commands come from Docker's official Debian instructions. Read them
before running; pasting unknown commands as root is how computers break.

```bash
# 1. Update package lists.
sudo apt-get update

# 2. Install prerequisites needed to add a new APT repo over HTTPS.
sudo apt-get install -y ca-certificates curl gnupg

# 3. Add Docker's official GPG key.
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/debian/gpg \
    -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

# 4. Add the Docker APT repository for Debian 13 (Trixie).
echo \
  "deb [arch=$(dpkg --print-architecture) \
        signed-by=/etc/apt/keyrings/docker.asc] \
  https://download.docker.com/linux/debian \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# 5. Install Docker Engine + Compose plugin + buildx.
sudo apt-get update
sudo apt-get install -y \
    docker-ce docker-ce-cli containerd.io \
    docker-buildx-plugin docker-compose-plugin
```

### Add yourself to the `docker` group

By default only root can talk to Docker. Adding your user to the `docker`
group lets you run `docker` commands without `sudo`.

```bash
sudo usermod -aG docker $USER
```

**You must log out and back in for this to take effect.** If you're on SSH,
disconnect and reconnect. If you're on the console, log out fully.

### How to verify

```bash
docker run --rm hello-world
```

You should see a "Hello from Docker!" message. If you get a "permission
denied while trying to connect to the Docker daemon socket" error, you
forgot to log out/back in.

```bash
docker compose version
```

Should print something like `Docker Compose version v2.27.x`.

### Troubleshooting

- **`docker: command not found`** — the install failed silently or your
  shell still has the old PATH. Try `which docker` (expect `/usr/bin/docker`).
- **`Cannot connect to the Docker daemon`** — the daemon isn't running.
  `sudo systemctl start docker` then `sudo systemctl enable docker` to
  start it on boot.
- **APT errors about a missing key** — re-run step 3 (the GPG key fetch).

---

## 3. Clone the repo and create the directory tree

### Get the code onto the NUC

If you've been editing the project on your Mac and storing it in iCloud,
**don't copy the iCloud folder directly** — iCloud places-as-needed corrupts
SQLite. Instead, sync the source via git or rsync, and let the runtime data
live on the NUC's local disk.

Pick one of the two options:

#### Option A: clone from a git remote (cleanest)

If you've pushed the repo to GitHub or another remote:

```bash
mkdir -p ~/FashionAgent
cd ~/FashionAgent
git clone <your-remote-url> .
```

#### Option B: rsync from your Mac (works without a remote)

From your **Mac** terminal (replace IP with the NUC's):

```bash
rsync -av --delete \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='.venv' \
    "$HOME/Library/Mobile Documents/com~apple~CloudDocs/Projects/FashionAgent/" \
    "fidelicious@10.0.0.85:/home/fidelicious/FashionAgent/"
```

This copies the source. Re-run it after any edit on the Mac.

### Create the runtime directories

These directories are **not in git** (they're listed in `.gitignore`) so you
need to create them explicitly. They live alongside the source on the NUC.

```bash
cd ~/FashionAgent
mkdir -p db images/{raw,cutouts,final,products,outfits} \
         inbox/{screenshots,email} \
         logs models backups secrets
```

### Set permissions

Secrets are sensitive. Lock them down so only your user can read.

```bash
chmod 700 secrets
```

### How to verify

```bash
ls -la ~/FashionAgent
```

You should see the source files (`pyproject.toml`, `docker/`, `src/`, etc.)
plus the runtime dirs you just made. `secrets/` should show `drwx------`.

### Troubleshooting

- **rsync says "permission denied"** — make sure your user owns
  `/home/fidelicious/FashionAgent` on the NUC: `sudo chown -R fidelicious:fidelicious /home/fidelicious/FashionAgent`.
- **`mkdir` complains the directory already exists** — that's fine, the `-p`
  flag makes it idempotent.

---

## 4. Set up Discord (developer portal + bot invite)

We're going to register a bot application, get its token, and invite it
into your private server.

### 4.1 Create a Discord server (skip if you have one)

If you don't already have a private server you control:

1. Open Discord (desktop or web).
2. Click the **+** button on the left sidebar → **Create my own** →
   **For me and my friends** → name it something like "Clawbot HQ".

You're now the admin of a server only you can see.

### 4.2 Enable Developer Mode (so you can copy IDs)

1. In Discord, click the **gear icon** (User Settings) at the bottom-left.
2. Sidebar → **Advanced** → toggle **Developer Mode** on.
3. Close Settings.

You can now right-click any user, channel, or server icon to find a **Copy
ID** option. We'll use this in 4.4.

### 4.3 Register the bot application

1. Open https://discord.com/developers/applications in your browser. Log in
   with the same Discord account you use day-to-day.
2. Click **New Application** (top right).
3. Name it `Clawbot`. Tick the terms-of-service box. Click **Create**.
4. You'll land on the application's "General Information" page. **Copy the
   Application ID** — you'll need it for the invite link in 4.5. Save it
   somewhere temporary (a scratch text file).
5. Sidebar → **Bot**.
6. Under "Privileged Gateway Intents", **enable both**:
   - **Message Content Intent**
   - **Server Members Intent**
   - (Presence Intent is OK to leave off.)
   Click **Save Changes** at the bottom.
7. Under "Token", click **Reset Token**, confirm, then **Copy** the new
   token. Save it to your scratch file. **Treat this like a password** —
   anyone with it can post as your bot.

### 4.4 Find your IDs

You need three IDs. With Developer Mode on (4.2):

- **Your user ID** — right-click your username (top-right or in any
  message), choose **Copy User ID**. **This is the operator
  whitelist**: any slash command from another user is silently refused
  (with an "this bot is private" ephemeral reply) and logged to
  `audit_log` with kind `discord_unauthorized`.
- **Your server (guild) ID** — right-click the server icon in the left
  sidebar, choose **Copy Server ID**. The bot registers its slash
  commands against this guild on startup so they appear instantly,
  instead of waiting up to an hour for global propagation.
- **The channel ID** for daily outfit pushes — pick any text channel in
  your server (or create one called `#wardrobe`), right-click it, choose
  **Copy Channel ID**.

Save all three to your scratch file.

### 4.5 Generate the bot invite URL

1. Back on https://discord.com/developers/applications, click your Clawbot
   app → sidebar → **OAuth2** → **URL Generator**.
2. Under "Scopes", check **bot** and **applications.commands**.
3. Under "Bot Permissions", check:
   - View Channels
   - Send Messages
   - Embed Links
   - Attach Files
   - Read Message History
   - Use Slash Commands
4. Scroll to the bottom — there's a generated URL. **Copy** it.
5. Paste the URL into a new browser tab. Discord will ask which server to
   add the bot to. Pick your Clawbot server. Click **Authorize**.

The bot will appear in your server's member list, offline.

### How to verify

Open your Discord server. The Clawbot bot is in the member list. It's grey
(offline) — that's correct, we haven't started the container yet.

### Troubleshooting

- **"Reset Token" greyed out** — you skipped clicking **Add Bot** earlier.
  Sidebar → Bot → click "Add Bot" first.
- **Can't see "Copy ID" on right-click** — Developer Mode isn't on. Redo 4.2.
- **Invite link errors with "Missing Permissions"** — you tried to invite
  to a server you don't admin. Use a server you created.

---

## 5. Fill in `secrets/.env`

This file holds the Discord token + IDs from Section 4. It is **never
committed to git**.

```bash
cd ~/FashionAgent
cp secrets/.env.example secrets/.env
chmod 600 secrets/.env
nano secrets/.env       # or vim, or your editor of choice
```

Replace the four `replace-me` values with the real ones from your scratch
file:

```env
DISCORD_TOKEN=<the token from step 4.3>
DISCORD_USER_ID=<your user ID from step 4.4>
DISCORD_GUILD_ID=<your server ID from step 4.4>
DISCORD_CHANNEL_ID=<the channel ID from step 4.4>
```

Save and quit (in nano: Ctrl+O, Enter, Ctrl+X).

### How to verify

```bash
ls -la secrets/.env
```

The mode column should be `-rw-------`. If it shows anything broader (e.g.,
`-rw-r--r--`), re-run `chmod 600 secrets/.env`.

```bash
grep -c '^[A-Z_]\+=replace-me$' secrets/.env
```

Should print `0` — meaning none of the placeholders remain.

### Troubleshooting

- **You committed `.env` by accident** — `git rm --cached secrets/.env`,
  then `git commit -m "fix: remove .env from tracking"`. The token is now
  in git history; **rotate it** in the Discord developer portal (4.3 step
  7, "Reset Token" again) and put the new value in your `.env`.

---

## 6. Start Ollama and pull the models

Ollama is the LLM runtime. We use the official image; nothing custom.

### Boot Ollama

```bash
cd ~/FashionAgent
docker compose -f docker/docker-compose.yml up -d ollama
```

`-d` means "detached" — the container runs in the background.

```bash
docker compose -f docker/docker-compose.yml logs -f ollama
```

This streams Ollama's logs. Wait until you see something like
`Listening on [::]:11434`. Press **Ctrl+C** to stop tailing logs (the
container keeps running).

### Pull the models

We need two models for V1: a small LLM and an embedding model. Pull them
into the running Ollama container:

```bash
docker exec -it clawbot-ollama ollama pull gemma3:1b
```

This downloads ~700 MB. It may take a minute or two on a slow connection.

```bash
docker exec -it clawbot-ollama ollama pull nomic-embed-text
```

This is much smaller (~270 MB).

### How to verify

```bash
docker exec -it clawbot-ollama ollama list
```

You should see both models listed.

```bash
curl -s http://localhost:11434/api/generate \
    -d '{"model":"gemma3:1b","prompt":"say hi","stream":false}' \
    | head -c 200
```

You should see a JSON response containing a short greeting. The first
generation is slow (~30 seconds) because Ollama has to load the model
into RAM. Subsequent calls within 5 minutes are faster; after 5 minutes
of idle, the model unloads (we set `OLLAMA_KEEP_ALIVE=5m` in compose).

### Troubleshooting

- **`docker exec` says "container not found"** — Ollama failed to start.
  `docker compose -f docker/docker-compose.yml ps` shows the state. If it
  says "Exited", `docker compose -f docker/docker-compose.yml logs ollama`
  shows why. Common cause: the `models/ollama` volume isn't writable.
  Fix: `chmod 755 ~/FashionAgent/models/ollama`.
- **`ollama pull` hangs at 0%** — your DNS isn't resolving. Try
  `docker exec -it clawbot-ollama ping -c 1 registry.ollama.ai`.
- **Generation is extremely slow (>2 minutes)** — your CPU is heavily
  loaded by something else, or you ran out of RAM and the model is
  swapping. Check `free -h` and `top`.

---

## 7. Start the clawbot container

> **Status note (post-Step-7):** the Discord bot is live. With
> `discord.enabled: true` in `config/clawbot.yaml` (already set in
> `clawbot.example.yaml`) and `secrets/.env` filled in, `clawbot.main`
> connects to Discord on startup, loads four cogs, and registers six
> slash commands (`/health`, `/profile`, `/wardrobe`, `/add_item`,
> `/edit_item`, `/forget_item`) against your guild. The image pipeline,
> Fashion-CLIP, rembg, and Tesseract are already baked into the runtime
> image (see the `[vision,discord,scheduler,email,llm,api]` extras in
> `docker/clawbot.Dockerfile`), so `/add_item` works end-to-end. Daily
> push, inbox watcher, and outfit recommendations land in build Steps
> 8–13.

### Build the image

The first build pulls Python 3.12 + system libraries + the base Python
dependencies. Without `[vision]` extras the image is ~500 MB and builds
in ~5 minutes. When the Dockerfile gains the `[vision]` extras in build
Step 8 (image worker), expect +2 GB of pip downloads and 10–20 minutes
the first time on this CPU.

```bash
cd ~/FashionAgent
docker compose -f docker/docker-compose.yml build clawbot
```

### Start the container

```bash
docker compose -f docker/docker-compose.yml up -d clawbot
```

### Watch the logs

```bash
docker compose -f docker/docker-compose.yml logs -f clawbot
```

### How to verify

1. Both containers up:

   ```bash
   docker compose -f docker/docker-compose.yml ps
   ```

   You should see both `clawbot-ollama` and `clawbot` with status
   `running`.

2. The bot announces itself in the logs:

   ```bash
   docker compose -f docker/docker-compose.yml logs clawbot | grep -E "Synced|logged in"
   ```

   Expect a line like `Synced slash commands to guild <your guild id>`.

3. In Discord, type `/health` in your private server. You should see an
   ephemeral reply (only visible to you) listing `db ✓`, `migrations ✓`,
   `ollama ✓`. If `ollama` shows `✗`, jump back to Section 6 — the bot
   reached Discord but can't talk to Ollama on the Docker network.

4. Try `/health` from a second Discord account (a friend, an alt). The
   bot should silently refuse with the "private" message you set in
   `config.discord.unauthorized_reply`. The denial is also written to
   `audit_log` with kind `discord_unauthorized` — inspect with:

   ```bash
   sqlite3 ~/FashionAgent/db/clawbot.db \
       "SELECT ts, actor, message FROM audit_log WHERE kind='discord_unauthorized' ORDER BY ts DESC LIMIT 5;"
   ```

The FastAPI `/healthz` HTTP endpoint mentioned in earlier drafts moves
to build Step 13 (operator dashboard).

### Troubleshooting

- **Build fails partway through `pip install`** — usually a network blip.
  Re-run `docker compose build clawbot`. Stuck in the same place repeatedly?
  Try `docker compose build --no-cache clawbot` (slower but clean).
- **Container restarts repeatedly** — `docker compose logs clawbot` shows
  the Python traceback. Most common cause at foundation pass: missing
  `secrets/.env`. Re-do Section 5.

---

## 7.5. Validate the image pipeline on the NUC

After build Step 5, the image pipeline (`clawbot.vision.ingest_image`)
exists as a callable library — raw image path → cutout PNG, color palette,
Fashion-CLIP embedding, zero-shot attributes, optional OCR. Build Step 7
wired it into Discord via `/add_item`, but this section's standalone
integration tests stay useful for confirming the pipeline works on NUC
hardware before involving Discord/Ollama.

This section is what to do **once**, on the NUC, to confirm Step 5 is real.

### Get the Step-5 branch onto the NUC

If you set up the NUC from `main`/`feat/foundation`, you need the
`feat/image-pipeline` branch now. Pick whichever transport you've been using:

```bash
cd ~/FashionAgent
git fetch origin
git checkout feat/image-pipeline
git pull
```

If you haven't pushed `feat/image-pipeline` to a remote, rsync from the Mac:

```bash
# Run on the Mac:
rsync -av --delete \
    --exclude='.git' --exclude='__pycache__' \
    --exclude='.venv' --exclude='.worktrees' \
    "$HOME/Library/Mobile Documents/com~apple~CloudDocs/Projects/FashionAgent/" \
    "fidelicious@10.0.0.85:/home/fidelicious/FashionAgent/"
```

### Why we need a venv on Debian 13

Debian 13 ships Python 3.13 with [PEP 668](https://peps.python.org/pep-0668/)
protection — `pip install` against the system interpreter is blocked with
"externally-managed-environment" by design. We make a project-local
virtualenv to keep the dependency install reproducible and reversible.

(Note: this is *not* the production runtime. Production runs inside Docker.
This venv exists only to let you run the integration tests against real
Fashion-CLIP / rembg / Tesseract weights on the NUC hardware.)

### Make the venv and install dependencies

```bash
cd ~/FashionAgent
sudo apt install -y python3.12-venv tesseract-ocr
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev,vision]"
```

- `tesseract-ocr` is the OS binary that `pytesseract` shells out to. The
  Python wrapper is in `[vision]`; the binary isn't.
- `python3.12-venv` is needed because the project pins Python 3.12 in
  `pyproject.toml`. If `python3.12` isn't installed, `apt install python3.12`
  first.
- `[dev,vision]` pulls pytest + ~2 GB of torch wheels. On the i5-3427U
  this is 10–20 minutes the first time.

### Run the integration tests

The first run downloads model weights (~600 MB Fashion-CLIP + ~5 MB rembg
u2netp) into `~/.cache/huggingface/` and `~/.u2net/`. Plan for ~5 minutes
on first run; subsequent runs are seconds.

```bash
.venv/bin/pytest -m integration tests/vision/integration -v
```

### How to verify

You should see 3 tests pass:

- `test_ingest_upload_structurally_valid`
- `test_ingest_email_structurally_valid`
- `test_ingest_screenshot_runs_ocr`

The assertions are structural (embedding shape, color hex format,
classification category in the expected set, OCR present/absent per source
type). They are *not* semantic — synthetic blue/black/white blobs won't
score well against Fashion-CLIP; the threshold in the integration `cfg`
fixture is intentionally loose. Semantic accuracy gets validated by
running `/add_item` on real photos in Section 9.

Also confirm the cutout files were written:

```bash
ls -la /tmp/pytest-of-fidelicious/pytest-*/test_ingest_*/images/cutouts/
```

You should see PNG cutouts of the synthetic inputs.

### Troubleshooting

- **`pip install` fails with `externally-managed-environment`** — you're
  installing into system Python instead of the venv. Make sure
  `source .venv/bin/activate` ran first (or use `.venv/bin/pip` directly).
- **`python3.12: command not found`** — Debian 13 ships 3.13. Either
  `apt install python3.12` if available, or fall back to `python3.13 -m venv .venv`
  and ignore the version mismatch — the code is 3.12+ and works on 3.13.
- **`ModuleNotFoundError: No module named 'transformers'`** — the venv isn't
  active or `[vision]` extras didn't install. Re-run
  `.venv/bin/pip install -e ".[dev,vision]"` and watch for errors.
- **Tests fail with `pytesseract.TesseractNotFoundError`** — the OS binary
  is missing. `sudo apt install tesseract-ocr`.
- **First run hangs at "Downloading model"** — slow HuggingFace mirror or
  no network. Try `curl -I https://huggingface.co` to confirm DNS/connectivity.
- **NUC ran out of RAM during integration test** — `free -h` to confirm.
  The 1B Gemma model in Ollama + Fashion-CLIP + rembg is tight at 8 GB.
  Stop Ollama temporarily: `docker compose -f docker/docker-compose.yml stop ollama`,
  re-run the test, then start it again.

---

## 8. Bootstrap your profile

> ✅ **Works today** (build Step 4 wired the profile module; build
> Step 6 added the `/profile set` slash command).

You can populate the profile by editing
`config/profile.bootstrap.example.yaml`, copying it to
`config/profile.bootstrap.yaml`, and running:

```bash
docker exec -it clawbot \
    python -m clawbot.scripts.bootstrap_profile \
        --yaml /app/config/profile.bootstrap.yaml \
        --db   /data/db/clawbot.db
```

The script tells you which fields it applied. Idempotent — re-run after
edits without harm.

### How to verify

```bash
docker exec -it clawbot \
    sqlite3 /data/db/clawbot.db "SELECT name, skin_undertone, comfort_vs_style FROM user_profile;"
```

You should see the values from your YAML. Empty fields show as blank.

### Troubleshooting

- **`sqlite3: command not found` inside the container** — the foundation
  image doesn't ship sqlite3. Inspect from the host instead:
  `sqlite3 ~/FashionAgent/db/clawbot.db "SELECT * FROM user_profile;"`.
- **`UNIQUE constraint failed: user_profile.id`** — the script tried to
  insert a second row. The bootstrap is `INSERT OR REPLACE` so this
  shouldn't happen; if it does, check that the migration ran:
  `sqlite3 ~/FashionAgent/db/clawbot.db ".tables"` should show
  `schema_migrations` and `user_profile` among others.

You can also drive this from Discord with `/profile set <field> <value>`
once the bot is running — but the YAML path is faster for the initial
~40-field bootstrap. After that, use `/profile` to view and
`/profile set` for one-off corrections.

---

## 9. Add your first wardrobe item

> ✅ **Works today** (build Step 7).

The flow is one slash command. The bot defers (Discord shows
"Clawbot is thinking…") while it runs rembg + Fashion-CLIP + OCR on the
NUC's CPU — expect 10–30 seconds on the i5-3427U the first time per
session (the models stay warm afterward).

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

---

---

## 15. Troubleshooting cookbook

This section grows over time. Check it before opening a fresh investigation.

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
