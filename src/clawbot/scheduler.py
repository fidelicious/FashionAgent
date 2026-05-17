"""
APScheduler bootstrap.

One ``AsyncIOScheduler`` lives inside the bot's event loop. After Step 14
it registers five jobs:

    inbox_sweep     : interval, ``schedule.inbox_sweep_seconds`` (default 60s)
    disk_check      : cron,     ``schedule.disk_check``          (default "0 * * * *")
    daily_outfit    : cron,     ``schedule.daily_outfit``        (default "0 7 * * *")
    nightly_backup  : cron,     ``schedule.nightly_backup``      (default "30 2 * * *")
    db_vacuum       : cron,     ``schedule.db_vacuum``           (default "0 3 * * 0")

Each must keep the "injectable side-effects + skinny wrapper" shape so unit
tests stay synchronous and offline.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from clawbot.discord.bot import BotContext
from clawbot.inbox.disk_check import handle_disk_check
from clawbot.inbox.notify import Notifier
from clawbot.inbox.watcher import IngestFn, SweepReport, sweep
from clawbot.maintenance import (
    BackupResult,
    VacuumResult,
    create_backup,
    prune_old_backups,
    run_db_vacuum,
)
from clawbot.outfits.daily import DailyResult, run_daily_outfit
from clawbot.outfits.llm import OllamaConfig

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────


def build_scheduler(
    ctx: BotContext,
    *,
    notifier: Notifier,
    ingest: IngestFn | None = None,
) -> AsyncIOScheduler:
    """Build a configured ``AsyncIOScheduler`` but **do not start it**.

    Caller is responsible for ``scheduler.start()`` and
    ``scheduler.shutdown(wait=False)`` — splitting construction from start
    keeps tests free of clock side effects.
    """
    sched = AsyncIOScheduler()

    async def _inbox_sweep() -> SweepReport:
        return await sweep(ctx, ingest=ingest, notify=notifier)

    sched.add_job(
        _inbox_sweep,
        IntervalTrigger(seconds=ctx.config.schedule.inbox_sweep_seconds),
        id="inbox_sweep",
        replace_existing=True,
        max_instances=1,  # never overlap sweeps on this NUC's RAM budget
        coalesce=True,  # if multiple ticks queued, collapse to one
    )

    async def _disk_check() -> Any:
        return await handle_disk_check(ctx, notifier=notifier)

    sched.add_job(
        _disk_check,
        CronTrigger.from_crontab(ctx.config.schedule.disk_check),
        id="disk_check",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    async def _daily_outfit() -> DailyResult:
        collage_dir = Path(ctx.config.paths.images_dir) / "outfits"
        collage_dir.mkdir(parents=True, exist_ok=True)
        ollama = OllamaConfig(
            base_url=ctx.config.models.ollama_base_url,
            model=ctx.config.models.llm,
            timeout_seconds=ctx.config.models.llm_timeout_seconds,
            max_retries=ctx.config.models.llm_max_retries,
        )
        return await run_daily_outfit(
            repo=ctx.repo,
            notifier=notifier,
            collage_dir=collage_dir,
            ollama_config=ollama,
        )

    sched.add_job(
        _daily_outfit,
        CronTrigger.from_crontab(ctx.config.schedule.daily_outfit),
        id="daily_outfit",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    async def _nightly_backup() -> BackupResult:
        # `include` paths in clawbot.yaml are container-absolute. Pass them
        # straight through; the backup helper handles missing paths gracefully.
        include_paths = [Path(p) for p in ctx.config.backup.include]
        backups_dir = Path(ctx.config.paths.backups_dir)
        result = create_backup(
            include=include_paths,
            output_dir=backups_dir,
            exclude_globs=list(ctx.config.backup.exclude_globs),
        )
        # Retention runs in the same tick so the disk stays bounded.
        dropped = prune_old_backups(backups_dir, retain_days=ctx.config.backup.retain_days)
        if dropped:
            logger.info("nightly_backup: pruned %d old tarball(s)", len(dropped))
        ctx.repo.audit.write(
            "nightly_backup",
            f"path={result.path.name} bytes={result.bytes} pruned={len(dropped)}",
            actor="job:nightly_backup",
        )
        return result

    sched.add_job(
        _nightly_backup,
        CronTrigger.from_crontab(ctx.config.schedule.nightly_backup),
        id="nightly_backup",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    async def _db_vacuum() -> VacuumResult:
        result = run_db_vacuum(ctx.repo.conn)
        ctx.repo.audit.write(
            "db_vacuum",
            f"before={result.bytes_before} after={result.bytes_after} "
            f"reclaimed={result.bytes_reclaimed}",
            actor="job:db_vacuum",
        )
        return result

    sched.add_job(
        _db_vacuum,
        CronTrigger.from_crontab(ctx.config.schedule.db_vacuum),
        id="db_vacuum",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    return sched


async def run_job_now(sched: AsyncIOScheduler, job_id: str) -> Any:
    """Manually invoke a registered job once, bypassing the trigger.

    Useful for /admin commands ("force a sweep now") and for tests that want
    to assert on side effects without waiting for the scheduler to tick.
    """
    job = sched.get_job(job_id)
    if job is None:
        raise KeyError(f"no scheduler job named {job_id!r}")
    return await job.func()
