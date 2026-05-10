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

This is the **foundation pass**. As of the current commit:

- ✅ Sections **1–6** are complete and exercisable today.
- ⚠️ Section **7** (start clawbot) will partially work: the container
  builds, but most application features land in upcoming build steps.
  Use it now to verify the build plumbing; don't expect a working bot.
- ⏳ Sections **8–15** are placeholders that get filled in as their
  features ship (image pipeline, Discord commands, daily push, etc.).

Each section ends with a **"How to verify"** subsection — never skip it. If
verification fails, jump to the **Troubleshooting** subsection at the end of
that same section before moving on.

---

## Table of contents

1. [Prerequisites and hardware check](#1-prerequisites-and-hardware-check)
2. [Install Docker and Docker Compose on Debian 13](#2-install-docker-and-docker-compose-on-debian-13)
3. [Clone the repo and create the directory tree](#3-clone-the-repo-and-create-the-directory-tree)
4. [Set up Discord (developer portal + bot invite)](#4-set-up-discord-developer-portal--bot-invite)
5. [Fill in `secrets/.env`](#5-fill-in-secretsenv)
6. [Start Ollama and pull the models](#6-start-ollama-and-pull-the-models)
7. [Start the clawbot container](#7-start-the-clawbot-container)
8. [Bootstrap your profile](#8-bootstrap-your-profile)
9. [Add your first wardrobe item](#9-add-your-first-wardrobe-item)
10. [Set up auto-ingest from your phone](#10-set-up-auto-ingest-from-your-phone)
11. [Set up email forwarding for retailer mails](#11-set-up-email-forwarding-for-retailer-mails)
12. [Verify the daily 7am outfit push](#12-verify-the-daily-7am-outfit-push)
13. [Backups and restores](#13-backups-and-restores)
14. [Maintenance](#14-maintenance)
15. [Troubleshooting](#15-troubleshooting-cookbook)

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
  message), choose **Copy User ID**.
- **Your server (guild) ID** — right-click the server icon in the left
  sidebar, choose **Copy Server ID**.
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

> **Foundation-pass note:** As of the current commit, `clawbot.main` is a
> placeholder; the full Discord bot, FastAPI server, and image worker
> aren't wired up yet. Running this now verifies the **build** is healthy.
> The bot will *not* respond in Discord yet — that lands in build Step 6.

### Build the image

The first build pulls Python 3.12 + system libraries + ~2 GB of pip
dependencies (rembg, torch, etc.). It takes 10–20 minutes on this CPU.
Subsequent builds are fast thanks to layer caching.

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

### How to verify (foundation pass)

For now, the verification is just "the container is running and not
crash-looping":

```bash
docker compose -f docker/docker-compose.yml ps
```

You should see both `clawbot-ollama` and `clawbot` with status
`running` (or `restarting` briefly, then `running`).

When build Step 6 (Discord bot) lands, this section will gain:

- `/health` in Discord returns green
- `curl http://localhost:8000/healthz` returns `{"status": "ok", ...}`

### Troubleshooting

- **Build fails partway through `pip install`** — usually a network blip.
  Re-run `docker compose build clawbot`. Stuck in the same place repeatedly?
  Try `docker compose build --no-cache clawbot` (slower but clean).
- **Container restarts repeatedly** — `docker compose logs clawbot` shows
  the Python traceback. Most common cause at foundation pass: missing
  `secrets/.env`. Re-do Section 5.

---

## 8. Bootstrap your profile

> ⏳ **Skeleton.** Filled in when build Step 6 (Discord bot) lands. Until then:

You can already populate the profile by editing
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

When the Discord bot is wired up, the same effect will be achievable via
`/profile set <field> <value>` slash commands.

---

## 9. Add your first wardrobe item

> ⏳ **Skeleton.** Filled in with build Step 5 (image pipeline) + Step 7
> (Discord write commands). Until then there's no end-to-end ingest path.

---

## 10. Set up auto-ingest from your phone

> ⏳ **Skeleton.** Filled in with build Step 8 (inbox watcher). Until then:

The plan is two flavors of "drop file → bot processes it":

- **Screenshots from your phone** — AirDrop or share-sheet to a Mac
  folder, rsync that folder to `~/FashionAgent/inbox/screenshots/` on the NUC
  every minute via cron. The watcher picks files up within 60 s.
- **Forwarded retailer emails** — Gmail filter forwards order/sale mails
  to a folder; getmail or imapfilter on the NUC writes the `.eml` files
  into `~/FashionAgent/inbox/email/`. Same watcher, same outcome.

Detailed commands land here when Step 8 ships.

---

## 11. Set up email forwarding for retailer mails

> ⏳ **Skeleton.** Filled in with build Step 9 (email parser).

---

## 12. Verify the daily 7am outfit push

> ⏳ **Skeleton.** Filled in with build Step 13 (daily push job).

---

## 13. Backups and restores

> ⏳ **Skeleton.** Filled in with build Step 14 (backup script). Outline:
>
> - Nightly job at 02:30 tarballs `db/` + `images/` into `backups/`.
> - Retention is 14 days (configurable via `backup.retain_days` in `clawbot.yaml`).
> - Restore is `tar -xzf backups/clawbot-YYYYMMDD.tar.gz -C /tmp/restore-test/`
>   then point a temporary container at the restored path to verify it opens.

---

## 14. Maintenance

> ⏳ **Skeleton.** Filled in alongside Step 14. Outline:
>
> - Update LLM: `docker exec clawbot-ollama ollama pull gemma3:1b`.
> - Update Python deps: edit `pyproject.toml`, then
>   `docker compose build --no-cache clawbot`.
> - Inspect DB: `sqlite3 ~/FashionAgent/db/clawbot.db` then `.tables`, `.schema`,
>   `SELECT * FROM user_profile;` etc.
> - Free disk: `docker system prune -a` (removes unused images), then
>   inspect `~/FashionAgent/images/raw/` for items that already have cutouts.

---

## 15. Troubleshooting cookbook

This section grows over time. Check it before opening a fresh investigation.

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
