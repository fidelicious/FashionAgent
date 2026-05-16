"""
Hourly disk-usage check.

Deferred from /health (which is operator-on-demand) so the operator
doesn't have to remember to poke it. Runs on
``schedule.disk_check`` (default ``0 * * * *``) and posts to the
channel only when usage breaches ``health.disk_warn_pct`` —
quiet otherwise so the channel doesn't fill with green pings.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from clawbot.config import ClawbotConfig
from clawbot.discord.bot import BotContext
from clawbot.inbox.notify import Notifier

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Types
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DiskUsage:
    """Mirror of ``shutil.disk_usage`` output, easy to construct in tests."""

    total: int
    used: int
    free: int

    @property
    def pct(self) -> float:
        return 100.0 * self.used / self.total if self.total else 0.0


class DiskStatus(str, Enum):
    OK = "ok"
    WARN = "warn"
    CRITICAL = "critical"


# Threshold check uses >= so 85% with warn=85 fires WARN — operators expect
# "alert at or above" semantics, not strictly greater than.
def check_disk(usage: DiskUsage, *, config: ClawbotConfig) -> DiskStatus:
    pct = usage.pct
    if pct >= config.health.disk_critical_pct:
        return DiskStatus.CRITICAL
    if pct >= config.health.disk_warn_pct:
        return DiskStatus.WARN
    return DiskStatus.OK


# ─────────────────────────────────────────────────────────────────────────────
# Probe injection
# ─────────────────────────────────────────────────────────────────────────────


UsageProbe = Callable[[Path], DiskUsage]


def default_usage_probe(path: Path) -> DiskUsage:
    u = shutil.disk_usage(path)
    return DiskUsage(total=u.total, used=u.used, free=u.free)


# ─────────────────────────────────────────────────────────────────────────────
# Job entry point
# ─────────────────────────────────────────────────────────────────────────────


async def handle_disk_check(
    ctx: BotContext,
    *,
    notifier: Notifier,
    usage_probe: Optional[UsageProbe] = None,
) -> DiskStatus:
    """Run one disk check. Posts to the channel only when over warn threshold.

    Returns the resolved DiskStatus so the scheduler can audit-log it (and so
    tests don't have to parse the message).
    """
    probe = usage_probe or default_usage_probe
    usage = probe(ctx.config.paths.home)
    status = check_disk(usage, config=ctx.config)

    if status is DiskStatus.OK:
        return status

    pct = int(round(usage.pct))
    if status is DiskStatus.CRITICAL:
        msg = (
            f":rotating_light: **CRITICAL** disk usage at {pct}% "
            f"(critical threshold "
            f"{ctx.config.health.disk_critical_pct}%). "
            f"Free: {usage.free // (1024 ** 3)} GB. "
            f"Stop ingestion and prune `images/raw/`."
        )
    else:
        msg = (
            f":warning: Disk usage at {pct}% — over the "
            f"{ctx.config.health.disk_warn_pct}% warn threshold. "
            f"Free: {usage.free // (1024 ** 3)} GB."
        )

    await notifier.post(msg)
    ctx.repo.audit.write(
        kind="disk_alert",
        actor="scheduler",
        message=f"{status.value} {pct}% used; "
                f"{usage.free} bytes free of {usage.total}",
    )
    logger.warning("disk_alert: %s %s%%", status.value, pct)
    return status
