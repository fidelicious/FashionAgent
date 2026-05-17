# Daily outfit failed to post

## Symptom

No Discord message at 7am. One or more of:
- `audit_log` has no `daily_outfit_shipped` row for today.
- The container is up but logs show no `daily_outfit` activity around 07:00.
- The message arrived but had no collage attached, or said "your wardrobe is empty" when you know it isn't.

## Diagnose

```bash
# 1. Was the job scheduled at all?
docker exec clawbot python -c "
from clawbot.scheduler import build_scheduler
# (Requires the bot context — see src/clawbot/main.py for the lifespan wiring.)
"
# Cheaper: check the audit log for any daily_outfit traces (success or failure):
sqlite3 ~/FashionAgent/db/clawbot.db \
  "SELECT ts, kind, message FROM audit_log
    WHERE kind LIKE '%outfit%' OR kind LIKE '%daily%'
    ORDER BY ts DESC LIMIT 20;"

# 2. Did the cron trigger fire?
docker compose -f ~/FashionAgent/docker/docker-compose.yml logs clawbot \
  | grep -i 'daily_outfit\|run_daily_outfit'

# 3. Is the wardrobe actually populated?
sqlite3 ~/FashionAgent/db/clawbot.db \
  "SELECT COUNT(*) FROM wardrobe_items WHERE deleted_at IS NULL;"

# 4. Did the LLM call work? (See also docs/runbooks/llm-unavailable.md.)
curl -sS http://localhost:11434/api/generate \
  -d '{"model":"gemma3:1b","prompt":"test","stream":false}' --max-time 30
```

## Fix

**If the cron didn't fire**, check `schedule.daily_outfit` in
`config/clawbot.yaml` — it must be a valid 5-field crontab string.
Default is `"0 7 * * *"`.

**If the wardrobe is empty**, that's expected behaviour — the job posted a
"your wardrobe is empty" text message instead of an outfit. Add items.

**If candidates couldn't be generated** (text message says "no items match
this season + occasion"), either:
- Some items are missing the `seasons` tag (check `/edit_item`).
- All your items are for a different season — change the season manually:
  ```bash
  # Force a fall-tagged run right now:
  docker exec clawbot python -c "
  import asyncio
  from clawbot.outfits.daily import run_daily_outfit
  # (Wire in repo + notifier; see scheduler.py for the production wiring.)
  "
  ```

**If the collage failed**, the message will have shipped without an image
and a `(collage unavailable)` suffix. Check `images/outfits/` is writable
and `images/final/` has thumbnails for the chosen items.

**If you want to manually re-run today's push** (e.g., to debug):
```bash
docker exec -it clawbot python -c "
import asyncio
from clawbot.scheduler import run_job_now
# (Requires access to the bot's running scheduler — easier to wait for
# the next cron tick or restart the container at 06:55 and watch 07:00.)
"
```

## Prevent

- The job is idempotent — re-running it just inserts a second `outfits` row. No risk in manually triggering for debugging.
- The orchestrator never raises: every failure mode degrades to a text-only message + audit log row + warning log. If you got nothing at all, the failure is *before* the orchestrator (container down, cron didn't fire, token expired).
- Monitor `audit_log` for `daily_outfit_shipped` rows. A daily check catches silent regressions.
