"""
Tests for the pure inbox-discovery function.

``discover()`` is the read-only sweep step: given an inbox root, return
the list of *new* image files in ``screenshots/`` (and later ``email/``)
plus their inferred source. It must:

    - Skip the hidden sibling dirs ``.processed/`` and ``.failed/``.
    - Skip files whose mtime is too recent (still being written by rsync).
    - Skip files with non-image extensions.
    - Skip the ``email/`` tree entirely in Step 8 (Step 9 handles it).
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from clawbot.inbox.watcher import InboxFile, _STABILITY_WINDOW_S, discover


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _touch(path: Path, *, mtime_ago_s: float = 30.0) -> Path:
    """Create an empty file with mtime in the past so discover() considers it stable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    past = time.time() - mtime_ago_s
    os.utime(path, (past, past))
    return path


# ─────────────────────────────────────────────────────────────────────────────
# Happy path
# ─────────────────────────────────────────────────────────────────────────────


def test_discover_picks_up_jpg_in_screenshots(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    f = _touch(inbox / "screenshots" / "cardigan.jpg")

    found = discover(inbox)
    assert found == [InboxFile(path=f, source="screenshot")]


def test_discover_picks_up_common_image_extensions(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    for name in ("a.jpg", "b.jpeg", "c.png", "d.webp"):
        _touch(inbox / "screenshots" / name)

    found = sorted(f.path.name for f in discover(inbox))
    assert found == ["a.jpg", "b.jpeg", "c.png", "d.webp"]


def test_discover_returns_empty_on_empty_inbox(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    (inbox / "screenshots").mkdir(parents=True)
    assert discover(inbox) == []


def test_discover_handles_missing_inbox(tmp_path: Path) -> None:
    """A missing inbox root is treated as 'no new files', not an error."""
    assert discover(tmp_path / "nope") == []


# ─────────────────────────────────────────────────────────────────────────────
# Filtering
# ─────────────────────────────────────────────────────────────────────────────


def test_discover_skips_processed_dir(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    _touch(inbox / ".processed" / "screenshots" / "old.jpg")
    assert discover(inbox) == []


def test_discover_skips_failed_dir(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    _touch(inbox / ".failed" / "screenshots" / "broken.jpg")
    assert discover(inbox) == []


def test_discover_picks_up_eml_in_email(tmp_path: Path) -> None:
    """Step 9 wired email/*.eml — should now be discovered with source='email'."""
    inbox = tmp_path / "inbox"
    eml = _touch(inbox / "email" / "receipt.eml")
    found = discover(inbox)
    assert found == [InboxFile(path=eml, source="email")]


def test_discover_skips_non_eml_in_email_subdir(tmp_path: Path) -> None:
    """A stray .jpg in email/ is not what we expect there — ignore it so
    the operator doesn't accidentally get it ingested twice with different
    code paths."""
    inbox = tmp_path / "inbox"
    _touch(inbox / "email" / "spam.jpg")
    assert discover(inbox) == []


def test_discover_skips_non_image_extensions(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    _touch(inbox / "screenshots" / "notes.txt")
    _touch(inbox / "screenshots" / "movie.mp4")
    _touch(inbox / "screenshots" / ".DS_Store")
    assert discover(inbox) == []


def test_discover_skips_recent_files_under_stability_window(tmp_path: Path) -> None:
    """A file whose mtime is younger than the stability window is still being
    written (rsync in flight). discover() must wait for the next sweep."""
    inbox = tmp_path / "inbox"
    f = _touch(inbox / "screenshots" / "midwrite.jpg", mtime_ago_s=0.1)
    assert _STABILITY_WINDOW_S > 0.1
    assert discover(inbox) == []
    # Now age it past the window — should appear.
    past = time.time() - (_STABILITY_WINDOW_S + 1)
    os.utime(f, (past, past))
    assert discover(inbox)[0].path == f


def test_discover_is_sorted_for_deterministic_order(tmp_path: Path) -> None:
    """Operators expect FIFO-ish behavior — sort by mtime then name."""
    inbox = tmp_path / "inbox"
    a = _touch(inbox / "screenshots" / "b.jpg")
    b = _touch(inbox / "screenshots" / "a.jpg")
    # Force literally identical mtimes so the alphabetical tiebreak kicks in.
    pinned = time.time() - 30
    os.utime(a, (pinned, pinned))
    os.utime(b, (pinned, pinned))
    found = [f.path.name for f in discover(inbox)]
    assert found == ["a.jpg", "b.jpg"]
