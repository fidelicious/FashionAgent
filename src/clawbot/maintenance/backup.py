"""
Nightly backup + retention pruning.

Two pure-IO helpers:

  - create_backup(): tar.gz the configured include paths into backups_dir
    under a date-stamped filename. Missing include paths are logged and
    skipped (so a wardrobe with no images yet doesn't crash the job).
  - prune_old_backups(): drop tarballs whose date stamp is older than
    retain_days. Only files matching our own naming scheme are
    candidates — operator-placed files are never touched.

Restore is intentionally not a function in this module — it's a
documented shell recipe in GUIDE.md Section 13. Restoring from a tarball
involves stopping the container and rsyncing files into the data volume,
which is operator territory.
"""

from __future__ import annotations

import fnmatch
import logging
import re
import tarfile
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


# Matches the exact names produced by `_build_filename` below.
# Allows an optional `-N` collision suffix.
_BACKUP_NAME_RE = re.compile(r"^clawbot-(\d{4})-(\d{2})-(\d{2})(?:-\d+)?\.tar\.gz$")


@dataclass(frozen=True)
class BackupResult:
    """Outcome of one create_backup() invocation."""

    path: Path
    bytes: int


# ─────────────────────────────────────────────────────────────────────────────
# create_backup
# ─────────────────────────────────────────────────────────────────────────────


def _build_filename(today: date, output_dir: Path) -> Path:
    """Return a unique output path. Appends `-N` if the date stamp collides."""
    base = f"clawbot-{today.isoformat()}.tar.gz"
    candidate = output_dir / base
    if not candidate.exists():
        return candidate
    n = 2
    while True:
        candidate = output_dir / f"clawbot-{today.isoformat()}-{n}.tar.gz"
        if not candidate.exists():
            return candidate
        n += 1


def _excluded(rel_path: str, exclude_globs: list[str]) -> bool:
    """True if any glob in `exclude_globs` matches the relative path."""
    return any(fnmatch.fnmatch(rel_path, pat) for pat in exclude_globs)


def create_backup(
    *,
    include: list[Path],
    output_dir: Path,
    today: date | None = None,
    exclude_globs: list[str] | None = None,
) -> BackupResult:
    """
    Tar+gzip every file under each path in `include` into `output_dir`.

    Members are stored relative to each include's parent — so an include of
    `/data/db` becomes `db/clawbot.db` inside the archive. Restoring is then
    `tar -xzf <file>.tar.gz -C /data/` which lays the tree back down at
    `/data/db/...`.

    Missing include paths are *logged and skipped*, not raised — the
    nightly job must always produce some artifact even if part of the
    tree is missing on a fresh install.
    """
    if today is None:
        today = date.today()
    if exclude_globs is None:
        exclude_globs = []

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = _build_filename(today, output_dir)

    with tarfile.open(out_path, "w:gz") as tar:
        for include_path in include:
            if not include_path.exists():
                logger.warning("backup: skipping missing include path %s", include_path)
                continue
            # arcname starts with the include's basename so the structure
            # round-trips cleanly on restore.
            arc_root = include_path.name
            # Only archive files — tar extract recreates parent dirs on the
            # fly, and including dir entries muddies the exclude_globs check
            # (an empty `images/raw/` dir would survive `**/raw/**`).
            for child in _walk(include_path):
                if not child.is_file():
                    continue
                rel = str(child.relative_to(include_path))
                arcname = f"{arc_root}/{rel}"
                if _excluded(arcname, exclude_globs):
                    continue
                tar.add(child, arcname=arcname, recursive=False)

    size = out_path.stat().st_size
    logger.info("backup: wrote %s (%d bytes)", out_path, size)
    return BackupResult(path=out_path, bytes=size)


def _walk(root: Path):
    """Yield root + every descendant (files + dirs), depth-first."""
    yield root
    if root.is_dir():
        for child in sorted(root.iterdir()):
            yield from _walk(child)


# ─────────────────────────────────────────────────────────────────────────────
# prune_old_backups
# ─────────────────────────────────────────────────────────────────────────────


def prune_old_backups(
    backups_dir: Path,
    *,
    retain_days: int,
    today: date | None = None,
) -> list[Path]:
    """
    Delete tarballs older than `retain_days`. Returns the list of dropped paths.

    Time-based retention by file *date stamp in the filename*, not by mtime,
    so an rsync that loses mtime metadata doesn't accidentally drop a recent
    backup. Only files matching our naming scheme are candidates; manual
    operator artefacts in the same directory are preserved.
    """
    if today is None:
        today = date.today()
    if not backups_dir.exists():
        return []

    cutoff = today - timedelta(days=retain_days)
    dropped: list[Path] = []
    for entry in backups_dir.iterdir():
        if not entry.is_file():
            continue
        m = _BACKUP_NAME_RE.match(entry.name)
        if m is None:
            continue
        try:
            stamp = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue
        if stamp < cutoff:
            entry.unlink()
            dropped.append(entry)
            logger.info("backup: pruned %s (stamp %s < cutoff %s)", entry.name, stamp, cutoff)
    return dropped
