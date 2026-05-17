# Inbox stuck

## Symptom

- You dropped a JPG/PNG/WEBP into `inbox/screenshots/` or a `.eml` into `inbox/email/` and nothing happened within ~90 seconds.
- File is still sitting in the inbox subdirectory, not moved to `_processed/` or `_failed/`.
- No Discord message appeared.

## Diagnose

```bash
# 1. Is the sweeper actually running? It logs each tick at DEBUG.
docker compose -f ~/FashionAgent/docker/docker-compose.yml logs -f clawbot \
  | grep -i 'inbox_sweep\|sweep:\|process_one'

# 2. Is the scheduler alive at all?
docker exec clawbot python -c "
import sqlite3, sys
c = sqlite3.connect('/data/db/clawbot.db')
rows = c.execute(
    \"SELECT ts, kind, message FROM audit_log ORDER BY ts DESC LIMIT 10\"
).fetchall()
for r in rows: print(r)
"

# 3. Permissions on the inbox dir? The container user must be able to
#    read AND move files into _processed/ or _failed/.
ls -la ~/FashionAgent/inbox/
ls -la ~/FashionAgent/inbox/screenshots/
```

## Fix

**If the sweeper hasn't logged anything**, the container or scheduler is
down. Restart and watch the boot log for the "Scheduler started" line:
```bash
docker compose -f ~/FashionAgent/docker/docker-compose.yml restart clawbot
docker compose -f ~/FashionAgent/docker/docker-compose.yml logs -f clawbot \
  | grep -E 'Synced|Scheduler started'
```

**If permissions look wrong**, the container's user can't move files:
```bash
sudo chown -R $(id -u):$(id -g) ~/FashionAgent/inbox
```

**If a single file is wedged** (probably corrupt), move it aside manually
and let the rest of the inbox proceed:
```bash
mv ~/FashionAgent/inbox/screenshots/bad-file.jpg \
   ~/FashionAgent/inbox/_failed/$(date +%s)-bad-file.jpg
```

**If the file is fine but the bot can't post to Discord** (this leaves
files moved to `_processed/` but you never see them), see
[discord-token-expired.md](discord-token-expired.md).

## Prevent

- Use `chmod 644` on uploaded files and `chmod 755` on `inbox/`.
- For email forwarding, use `getmail` or your mail client's "save attachment to folder" — never let a third-party tool write directly to a system path without validating the filename.
- The sweep interval is `schedule.inbox_sweep_seconds` (default 60) — set lower (e.g. 15) if you want faster feedback while debugging.
