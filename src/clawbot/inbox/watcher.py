"""
Inbox watcher — filesystem ingest path.

Three layers, each independently testable:

    discover(inbox_dir) -> [InboxFile]
        Pure read: scan the filesystem, filter by extension + mtime stability,
        skip the sibling .processed/.failed dirs and email/ tree.

    process_one(ctx, file, *, ingest, notify) -> ProcessResult
        Apply the image pipeline to a single file, persist the resulting
        WardrobeItem, then move the source into .processed/ or .failed/.

    sweep(ctx, *, ingest, notify) -> SweepReport
        The job-loop iteration: discover + process_one per file. Returns a
        report so the scheduler can audit-log a single summary row instead
        of one per file.
"""

from __future__ import annotations

import logging
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Awaitable, Callable, Literal, Optional, Protocol

from clawbot.discord.bot import BotContext
from clawbot.discord.cogs.items import build_item_from_draft
from clawbot.vision.draft import DraftItem

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Tuning constants
# ─────────────────────────────────────────────────────────────────────────────


# Stability window — a file whose mtime is younger than this is assumed to
# still be transferring (rsync in flight, AirDrop in progress, etc). Five
# seconds is generous on a LAN and forgiving on flaky Wi-Fi.
_STABILITY_WINDOW_S = 5.0

# Image extensions discover() will pick up. HEIC excluded because rembg's
# onnx backend doesn't decode it; convert to JPG on the iPhone side first.
_IMAGE_EXTS = frozenset({".jpg", ".jpeg", ".png", ".webp"})

# Sibling sub-dirs under the inbox root that hold post-processing state.
# Hidden so they don't pollute `ls` on the live drop folder.
_PROCESSED_SUBDIR = ".processed"
_FAILED_SUBDIR = ".failed"
_SKIP_TOP_DIRS = frozenset({_PROCESSED_SUBDIR, _FAILED_SUBDIR})

# Step 8 scope: screenshots only. Step 9 handles email/.
_SCAN_SUBDIRS = ("screenshots",)


# ─────────────────────────────────────────────────────────────────────────────
# Types
# ─────────────────────────────────────────────────────────────────────────────


Source = Literal["upload", "screenshot", "email"]


@dataclass(frozen=True)
class InboxFile:
    """A discovered file plus the ``source`` the pipeline should run with."""

    path: Path
    source: Source


class ProcessOutcome(str, Enum):
    OK = "ok"
    FAILED = "failed"


@dataclass(frozen=True)
class ProcessResult:
    """Per-file outcome. Failures carry the exception's str for the audit log."""

    file: InboxFile
    outcome: ProcessOutcome
    item_id: Optional[str] = None
    error: Optional[str] = None


@dataclass
class SweepReport:
    """Aggregate over one sweep cycle."""

    ok: int = 0
    failed: int = 0
    results: list[ProcessResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.ok + self.failed


# ─────────────────────────────────────────────────────────────────────────────
# Injectable side-effect protocols
# ─────────────────────────────────────────────────────────────────────────────


class IngestFn(Protocol):
    """Match ``clawbot.vision.ingest_image`` (positional path, kw-only rest)."""

    def __call__(
        self, raw_path: Path, *, source: str, config: object
    ) -> DraftItem: ...


class Notifier(Protocol):
    """Discord-side notifier. ``post`` is async even though the default
    implementation may not need to await — tests can supply sync stubs."""

    async def post(self, content: str) -> None: ...


# ─────────────────────────────────────────────────────────────────────────────
# discover
# ─────────────────────────────────────────────────────────────────────────────


def discover(inbox_dir: Path) -> list[InboxFile]:
    """Scan ``inbox_dir`` and return new ready-to-process files.

    Only ``screenshots/`` is scanned in Step 8 — ``email/`` is Step 9's
    responsibility. The result is sorted by ``(mtime, name)`` so processing
    order is deterministic and roughly FIFO.
    """
    if not inbox_dir.exists():
        return []

    candidates: list[InboxFile] = []
    now = time.time()
    for subdir_name in _SCAN_SUBDIRS:
        subdir = inbox_dir / subdir_name
        if not subdir.is_dir():
            continue
        for child in subdir.iterdir():
            if not child.is_file():
                continue
            if child.suffix.lower() not in _IMAGE_EXTS:
                continue
            try:
                mtime = child.stat().st_mtime
            except OSError:
                continue
            if now - mtime < _STABILITY_WINDOW_S:
                continue
            candidates.append(
                InboxFile(path=child, source=_subdir_to_source(subdir_name))
            )

    # Also ensure we didn't accidentally enumerate the .processed / .failed
    # trees via a different code path. They live under inbox_dir, not under
    # screenshots/, so the loop above never visits them — this is a guard
    # against future refactors.
    candidates = [
        f
        for f in candidates
        if not any(part in _SKIP_TOP_DIRS for part in f.path.parts)
    ]

    candidates.sort(key=lambda f: (f.path.stat().st_mtime, f.path.name))
    return candidates


def _subdir_to_source(subdir_name: str) -> Source:
    if subdir_name == "screenshots":
        return "screenshot"
    if subdir_name == "email":
        return "email"
    return "upload"


# ─────────────────────────────────────────────────────────────────────────────
# process_one
# ─────────────────────────────────────────────────────────────────────────────


async def process_one(
    ctx: BotContext,
    file: InboxFile,
    *,
    ingest: IngestFn,
    notify: Optional[Notifier] = None,
) -> ProcessResult:
    """Run the image pipeline on ``file``, persist, and move the source.

    On success: insert wardrobe row + embedding, move source to
    ``inbox/.processed/<source>/YYYY-MM-DD/<name>``, audit-log
    ``inbox_ingested``, and notify the channel if a Notifier was supplied.

    On failure: move source to ``inbox/.failed/<source>/<name>.<ts>``,
    audit-log ``inbox_failed``, and notify the channel.
    """
    inbox_dir = ctx.config.paths.inbox_dir

    try:
        draft = ingest(file.path, source=file.source, config=ctx.config)
        item = build_item_from_draft(draft)
        item_id = ctx.repo.items.add(item)
        ctx.repo.items.set_embedding(item_id, draft.embedding.tolist())
    except Exception as e:
        logger.exception(
            "inbox ingest failed for %s", file.path
        )
        _move_to_failed(inbox_dir, file)
        ctx.repo.audit.write(
            kind="inbox_failed",
            actor="inbox_watcher",
            message=f"{file.path.name}: {type(e).__name__}: {e}",
        )
        if notify is not None:
            await notify.post(
                f":warning: Failed to ingest `{file.path.name}`: "
                f"`{type(e).__name__}: {e}`"
            )
        return ProcessResult(
            file=file, outcome=ProcessOutcome.FAILED, error=str(e)
        )

    _move_to_processed(inbox_dir, file)
    ctx.repo.audit.write(
        kind="inbox_ingested",
        actor="inbox_watcher",
        message=f"{file.path.name} -> {item_id}",
    )
    if notify is not None:
        short = item_id[:8]
        await notify.post(
            f":new: Added `[{short}]` from inbox `{file.path.name}` — "
            f"category `{item.category}/{item.subcategory or '?'}`. "
            f"Use `/edit_item {short}` to correct anything."
        )
    return ProcessResult(
        file=file, outcome=ProcessOutcome.OK, item_id=item_id
    )


def _move_to_processed(inbox_dir: Path, file: InboxFile) -> Path:
    """Move ``file`` into ``inbox/.processed/<source>/YYYY-MM-DD/``."""
    date_dir = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    target_dir = inbox_dir / _PROCESSED_SUBDIR / _source_subdir(file) / date_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / file.path.name
    target = _unique_path(target)
    shutil.move(str(file.path), str(target))
    return target


def _move_to_failed(inbox_dir: Path, file: InboxFile) -> Path:
    """Move ``file`` into ``inbox/.failed/<source>/`` with a UTC timestamp suffix."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target_dir = inbox_dir / _FAILED_SUBDIR / _source_subdir(file)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{file.path.name}.{ts}"
    shutil.move(str(file.path), str(target))
    return target


def _source_subdir(file: InboxFile) -> str:
    return "screenshots" if file.source == "screenshot" else file.source


def _unique_path(target: Path) -> Path:
    """If ``target`` already exists, append `(2)`, `(3)`, ... before the suffix."""
    if not target.exists():
        return target
    stem, suffix = target.stem, target.suffix
    n = 2
    while True:
        candidate = target.with_name(f"{stem}({n}){suffix}")
        if not candidate.exists():
            return candidate
        n += 1


# ─────────────────────────────────────────────────────────────────────────────
# sweep
# ─────────────────────────────────────────────────────────────────────────────


SweepHook = Callable[[SweepReport], Awaitable[None]]


async def sweep(
    ctx: BotContext,
    *,
    ingest: Optional[IngestFn] = None,
    notify: Optional[Notifier] = None,
    on_complete: Optional[SweepHook] = None,
) -> SweepReport:
    """One sweep cycle. Returns the aggregate report.

    The scheduler calls this on every ``schedule.inbox_sweep_seconds``. The
    pipeline is loaded lazily so an empty sweep stays cheap; non-empty
    sweeps run serially (no parallelism on this NUC's RAM budget).
    """
    if ingest is None:
        from clawbot.vision import ingest_image

        ingest = ingest_image

    report = SweepReport()
    for file in discover(ctx.config.paths.inbox_dir):
        result = await process_one(ctx, file, ingest=ingest, notify=notify)
        report.results.append(result)
        if result.outcome is ProcessOutcome.OK:
            report.ok += 1
        else:
            report.failed += 1

    if on_complete is not None and report.total > 0:
        await on_complete(report)

    return report
