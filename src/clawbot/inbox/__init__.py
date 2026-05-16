"""
Clawbot's inbox watcher — auto-ingestion from the filesystem.

Build Step 8 ships ``screenshots/`` ingestion only; ``email/`` is Step 9.
The operator drops images into ``inbox/screenshots/`` (via AirDrop +
rsync, scp, or whatever), and the scheduler's ``inbox_sweep`` job picks
them up every ``schedule.inbox_sweep_seconds``.

Layout
------
watcher.py : discover(), process_one(), sweep()
notify.py  : Discord channel notifier protocol + default implementation
"""

from clawbot.inbox.watcher import (
    InboxFile,
    ProcessOutcome,
    ProcessResult,
    SweepReport,
    discover,
    process_one,
    sweep,
)

__all__ = [
    "InboxFile",
    "ProcessOutcome",
    "ProcessResult",
    "SweepReport",
    "discover",
    "process_one",
    "sweep",
]
