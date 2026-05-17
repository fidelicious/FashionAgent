# Database locked

## Symptom

- `sqlite3.OperationalError: database is locked` in `docker compose logs`.
- A Discord command hangs ~30 seconds and then fails.
- `inbox_sweep` or `daily_outfit` jobs in `audit_log` show error rows.

## Diagnose

SQLite uses a single writer at a time. With WAL mode (which we enable in
[connection.py](../../src/clawbot/db/connection.py)), reads never block,
but two simultaneous writes will queue up to 30 seconds (`busy_timeout`)
before erroring.

```bash
# 1. Is something outside the container holding a write lock?
fuser ~/FashionAgent/db/clawbot.db
lsof ~/FashionAgent/db/clawbot.db
# Common culprits: a `sqlite3` shell with a pending `BEGIN`, a manual
# VACUUM from the host, a backup tool still copying.

# 2. Are there leftover WAL/SHM files that suggest a crash?
ls -la ~/FashionAgent/db/
# Expect: clawbot.db, clawbot.db-wal, clawbot.db-shm
# A leftover -journal file suggests a crash mid-transaction.

# 3. Are two scheduler jobs trying to write at the same time?
sqlite3 ~/FashionAgent/db/clawbot.db \
  "SELECT ts, kind, message FROM audit_log
    WHERE kind IN ('job_failed', 'db_locked')
    ORDER BY ts DESC LIMIT 10;"
```

## Fix

**If a manual `sqlite3` shell is the culprit**, just exit it. WAL mode
automatically reconciles after the writer releases.

**If a `-journal` file exists** (suggests a crash):
```bash
docker compose -f ~/FashionAgent/docker/docker-compose.yml stop clawbot
# The journal will be auto-rolled-back on next open; just confirm:
sqlite3 ~/FashionAgent/db/clawbot.db "PRAGMA integrity_check;"
docker compose -f ~/FashionAgent/docker/docker-compose.yml start clawbot
```

**If two scheduler jobs collide** (rare — APScheduler `max_instances=1`
should prevent this for any single job), check that you haven't manually
started a second clawbot container against the same DB file:
```bash
docker compose -f ~/FashionAgent/docker/docker-compose.yml ps
```

## Prevent

- All write paths go through `transaction()` ([connection.py:64](../../src/clawbot/db/connection.py#L64)) which uses `BEGIN IMMEDIATE` — failures fast rather than partial writes.
- `busy_timeout = 30000` gives long-running jobs (image pipeline, vacuum) headroom to wait for each other.
- Don't run `sqlite3` writes from the host while the container is running. Always stop the container first for ad-hoc maintenance.
