"""
Maintenance jobs: nightly backup and weekly SQLite VACUUM.

Both run from the in-process APScheduler. Each is a thin, side-effect-only
function so tests can exercise them in isolation against a tmp directory or
an in-memory SQLite, without spinning up the scheduler or Discord.
"""

from clawbot.maintenance.backup import BackupResult, create_backup, prune_old_backups
from clawbot.maintenance.vacuum import VacuumResult, run_db_vacuum

__all__ = [
    "BackupResult",
    "VacuumResult",
    "create_backup",
    "prune_old_backups",
    "run_db_vacuum",
]
