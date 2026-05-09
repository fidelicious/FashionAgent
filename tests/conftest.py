"""
Shared pytest fixtures.

Kept intentionally small — fixtures should live near the tests that use them
unless they're truly cross-cutting.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# Path to the example YAML, used as a known-good config baseline by config tests.
EXAMPLE_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "clawbot.example.yaml"
)


@pytest.fixture
def example_config_yaml() -> str:
    """Return the contents of config/clawbot.example.yaml as a string.

    Tests that need a custom config should write a tweaked version of this
    to a tmp_path, not edit the example in place.
    """
    return EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8")
