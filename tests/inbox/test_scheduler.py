"""
Tests for the APScheduler bootstrap.

We don't exercise APScheduler's clock — that's its own test suite's job.
What we DO test:
    - The scheduler returned from build_scheduler() has the right jobs
      registered with the right triggers parsed from config.
    - Running each job manually via ``run_job_now`` produces the same side
      effects as if the cron fired.

The scheduler is never ``start()``-ed in these tests, so it doesn't need
a corresponding ``shutdown()`` — AsyncIOScheduler is inert until started.
"""

from __future__ import annotations

import pytest
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from clawbot.discord.bot import BotContext
from clawbot.scheduler import build_scheduler, run_job_now


def _job(sched, job_id: str):
    return sched.get_job(job_id)


# ─────────────────────────────────────────────────────────────────────────────
# Job registration
# ─────────────────────────────────────────────────────────────────────────────


def test_build_scheduler_registers_inbox_sweep(ctx: BotContext, notifier) -> None:
    sched = build_scheduler(ctx, notifier=notifier)
    job = _job(sched, "inbox_sweep")
    assert job is not None
    assert isinstance(job.trigger, IntervalTrigger)
    assert job.trigger.interval.total_seconds() == (ctx.config.schedule.inbox_sweep_seconds)


def test_build_scheduler_registers_disk_check(ctx: BotContext, notifier) -> None:
    sched = build_scheduler(ctx, notifier=notifier)
    job = _job(sched, "disk_check")
    assert job is not None
    assert isinstance(job.trigger, CronTrigger)


def test_build_scheduler_registers_daily_outfit(ctx: BotContext, notifier) -> None:
    """Step 13 wires daily_outfit into the scheduler."""
    sched = build_scheduler(ctx, notifier=notifier)
    job = _job(sched, "daily_outfit")
    assert job is not None
    assert isinstance(job.trigger, CronTrigger)


def test_build_scheduler_registers_nightly_backup_and_db_vacuum(ctx: BotContext, notifier) -> None:
    """Step 14 wires the two maintenance jobs."""
    sched = build_scheduler(ctx, notifier=notifier)
    backup_job = _job(sched, "nightly_backup")
    vacuum_job = _job(sched, "db_vacuum")
    assert backup_job is not None
    assert vacuum_job is not None
    assert isinstance(backup_job.trigger, CronTrigger)
    assert isinstance(vacuum_job.trigger, CronTrigger)


# ─────────────────────────────────────────────────────────────────────────────
# run_job_now — manual trigger used in /health follow-ups and tests
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_job_now_inbox_sweep_processes_file(
    ctx: BotContext, notifier, stable_screenshot, fake_draft_factory
) -> None:
    sched = build_scheduler(ctx, notifier=notifier, ingest=lambda p, **kw: fake_draft_factory(p))
    stable_screenshot("from_inbox.jpg")
    report = await run_job_now(sched, "inbox_sweep")
    assert report.ok == 1
    assert ctx.repo.items.count() == 1


@pytest.mark.asyncio
async def test_run_job_now_unknown_job_raises(ctx: BotContext, notifier) -> None:
    sched = build_scheduler(ctx, notifier=notifier)
    with pytest.raises(KeyError, match="does_not_exist"):
        await run_job_now(sched, "does_not_exist")
