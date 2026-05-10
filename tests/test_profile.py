"""
Tests for clawbot.profile.

Covers:
    - get_profile after bootstrap.
    - set_field happy paths and validation rejections per field type:
      enum, numeric range, JSON list, freeform.
    - set_many is atomic on validation error.
    - bootstrap_from_yaml flattens groups, surfaces all errors at once.
    - Audit log records every update.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from clawbot.db import Repo, connect, run_migrations
from clawbot.profile import (
    ALLOWED_VALUES,
    ProfileError,
    bootstrap_from_yaml,
    get_profile,
    set_field,
    set_many,
)

MIGRATIONS_DIR = (
    Path(__file__).resolve().parent.parent / "src" / "clawbot" / "db" / "migrations"
)


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    conn = connect(tmp_path / "p.db")
    run_migrations(conn, MIGRATIONS_DIR)
    return Repo(conn)


# ─────────────────────────────────────────────────────────────────────────────
# Single-field set
# ─────────────────────────────────────────────────────────────────────────────


def test_set_enum_field_normalizes_case(repo: Repo) -> None:
    set_field(repo, "skin_undertone", "WARM")
    assert get_profile(repo)["skin_undertone"] == "warm"


def test_set_enum_field_rejects_unknown(repo: Repo) -> None:
    with pytest.raises(ProfileError, match="skin_undertone"):
        set_field(repo, "skin_undertone", "lukewarm")


def test_set_numeric_field_in_range(repo: Repo) -> None:
    set_field(repo, "comfort_vs_style", 7)
    assert get_profile(repo)["comfort_vs_style"] == 7


def test_set_numeric_field_out_of_range(repo: Repo) -> None:
    with pytest.raises(ProfileError, match="outside"):
        set_field(repo, "comfort_vs_style", 11)


def test_set_numeric_field_string_coerces(repo: Repo) -> None:
    """Discord commands arrive as strings; we coerce."""
    set_field(repo, "height_cm", "165")
    assert get_profile(repo)["height_cm"] == 165


def test_set_numeric_field_bad_string(repo: Repo) -> None:
    with pytest.raises(ProfileError, match="numeric"):
        set_field(repo, "height_cm", "tall")


def test_set_json_list_field_from_list(repo: Repo) -> None:
    set_field(repo, "favorite_colors_json", ["navy", "camel", "olive"])
    assert get_profile(repo)["favorite_colors_json"] == ["navy", "camel", "olive"]


def test_set_json_list_field_from_csv_string(repo: Repo) -> None:
    """Comma-separated strings are a Discord ergonomic shortcut."""
    set_field(repo, "favorite_colors_json", "navy, camel, olive")
    assert get_profile(repo)["favorite_colors_json"] == ["navy", "camel", "olive"]


def test_set_freeform_text_strips(repo: Repo) -> None:
    set_field(repo, "city", "  Oakland, CA  ")
    assert get_profile(repo)["city"] == "Oakland, CA"


def test_set_freeform_text_empty_becomes_none(repo: Repo) -> None:
    set_field(repo, "city", "Oakland, CA")
    set_field(repo, "city", "")
    assert get_profile(repo)["city"] is None


def test_set_unknown_field_rejected(repo: Repo) -> None:
    with pytest.raises(ProfileError, match="Unknown profile field"):
        set_field(repo, "favorite_pet", "cat")


# ─────────────────────────────────────────────────────────────────────────────
# Bulk set
# ─────────────────────────────────────────────────────────────────────────────


def test_set_many_applies_all(repo: Repo) -> None:
    set_many(repo, {
        "skin_undertone": "cool",
        "comfort_vs_style": 4,
        "favorite_colors_json": ["forest", "rust"],
    })
    p = get_profile(repo)
    assert p["skin_undertone"] == "cool"
    assert p["comfort_vs_style"] == 4
    assert p["favorite_colors_json"] == ["forest", "rust"]


def test_set_many_atomic_on_error(repo: Repo) -> None:
    """If any field fails validation, none are written."""
    with pytest.raises(ProfileError) as exc_info:
        set_many(repo, {
            "skin_undertone": "warm",       # OK
            "body_shape": "blob",           # bad enum
            "comfort_vs_style": 99,         # out of range
        })
    msg = str(exc_info.value)
    assert "body_shape" in msg
    assert "comfort_vs_style" in msg
    # Verify nothing was persisted.
    p = get_profile(repo)
    assert p["skin_undertone"] is None


# ─────────────────────────────────────────────────────────────────────────────
# Bootstrap from YAML
# ─────────────────────────────────────────────────────────────────────────────


def test_bootstrap_from_example_yaml(repo: Repo, tmp_path: Path) -> None:
    """The shipped example YAML must be valid and apply cleanly."""
    example = (
        Path(__file__).resolve().parent.parent
        / "config"
        / "profile.bootstrap.example.yaml"
    )
    bootstrap_from_yaml(repo, example)
    p = get_profile(repo)
    # Spot-check fields from each group.
    assert p["body_shape"] == "hourglass"
    assert p["skin_undertone"] == "warm"
    assert p["top_size"] == "M"
    assert "navy" in p["favorite_colors_json"]
    assert p["jewelry_metal"] == "gold"
    assert p["commute_mode"] == "transit"
    assert p["monthly_clothing_budget_usd"] == 250


def test_bootstrap_flattens_groups(repo: Repo, tmp_path: Path) -> None:
    yml = tmp_path / "p.yaml"
    yml.write_text(
        "physical:\n"
        "  skin_undertone: warm\n"
        "style:\n"
        "  jewelry_metal: silver\n"
    )
    bootstrap_from_yaml(repo, yml)
    p = get_profile(repo)
    assert p["skin_undertone"] == "warm"
    assert p["jewelry_metal"] == "silver"


def test_bootstrap_top_level_field_kept(repo: Repo, tmp_path: Path) -> None:
    """If a top-level YAML key matches a profile field, it isn't treated as a group."""
    yml = tmp_path / "p.yaml"
    yml.write_text("skin_undertone: cool\n")
    bootstrap_from_yaml(repo, yml)
    assert get_profile(repo)["skin_undertone"] == "cool"


def test_bootstrap_missing_file(repo: Repo, tmp_path: Path) -> None:
    with pytest.raises(ProfileError, match="not found"):
        bootstrap_from_yaml(repo, tmp_path / "nope.yaml")


def test_bootstrap_non_mapping(repo: Repo, tmp_path: Path) -> None:
    yml = tmp_path / "p.yaml"
    yml.write_text("- a\n- b\n")
    with pytest.raises(ProfileError, match="must be a mapping"):
        bootstrap_from_yaml(repo, yml)


def test_bootstrap_reports_all_errors(repo: Repo, tmp_path: Path) -> None:
    yml = tmp_path / "p.yaml"
    yml.write_text(
        "skin_undertone: lukewarm\n"     # bad
        "body_shape: pyramid\n"          # bad
        "comfort_vs_style: 11\n"         # out of range
        "city: Oakland, CA\n"            # ok
    )
    with pytest.raises(ProfileError) as exc_info:
        bootstrap_from_yaml(repo, yml)
    msg = str(exc_info.value)
    assert "skin_undertone" in msg
    assert "body_shape" in msg
    assert "comfort_vs_style" in msg


# ─────────────────────────────────────────────────────────────────────────────
# Audit log
# ─────────────────────────────────────────────────────────────────────────────


def test_set_field_writes_audit_entry(repo: Repo) -> None:
    set_field(repo, "skin_undertone", "warm")
    log = repo.audit.recent()
    assert any(
        e["kind"] == "profile_updated" and "skin_undertone" in e["message"]
        for e in log
    )


def test_set_many_writes_one_audit_entry(repo: Repo) -> None:
    set_many(repo, {"skin_undertone": "warm", "body_shape": "rectangle"})
    log = repo.audit.recent()
    profile_updates = [e for e in log if e["kind"] == "profile_updated"]
    assert len(profile_updates) == 1
    msg = profile_updates[0]["message"]
    assert "skin_undertone" in msg
    assert "body_shape" in msg


# ─────────────────────────────────────────────────────────────────────────────
# Sanity checks on the controlled vocabularies
# ─────────────────────────────────────────────────────────────────────────────


def test_allowed_values_are_lowercase() -> None:
    """Discord users type with mixed case; we always store lowercase."""
    for field, options in ALLOWED_VALUES.items():
        for o in options:
            assert o == o.lower(), f"{field}: {o!r} should be lowercase"
