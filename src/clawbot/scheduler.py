"""
APScheduler bootstrap.

One ``AsyncIOScheduler`` lives inside the bot's event loop. Build-Step-8
registers two jobs:

    inbox_sweep : interval, ``schedule.inbox_sweep_seconds`` (default 60s)
    disk_check  : cron,    ``schedule.disk_check``           (default "0 * * * *")

Subsequent steps will add ``daily_outfit`` (Step 13), ``nightly_backup``
(Step 14), and ``db_vacuum`` (also Step 14) here. Each must keep the
"injectable side-effects + skinny wrapper" shape so unit tests stay
synchronous and offline.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from clawbot.discord.bot import BotContext
from clawbot.inbox.disk_check import handle_disk_check
from clawbot.inbox.notify import Notifier
from clawbot.inbox.watcher import IngestFn, SweepReport, sweep

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────


def build_scheduler(
    ctx: BotContext,
    *,
    notifier: Notifier,
    ingest: Optional[IngestFn] = None,
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
        coalesce=True,    # if multiple ticks queued, collapse to one
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
