"""
Tests for clawbot.config.

Covers:
    - Loading the shipped example config (smoke test).
    - Default values applied to an empty file.
    - Missing file raises ConfigError with a readable message.
    - Bad YAML / non-mapping root raises ConfigError.
    - Validation errors are surfaced cleanly (not as raw pydantic stack).
    - Environment variable overrides take effect.
    - The disk_critical_pct > disk_warn_pct cross-field rule.
    - Cron field-count validation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from clawbot.config import ClawbotConfig, ConfigError, load_config


# ─────────────────────────────────────────────────────────────────────────────
# Happy path
# ─────────────────────────────────────────────────────────────────────────────


def test_example_yaml_loads(example_config_yaml: str, tmp_path: Path) -> None:
    """The shipped example config must always parse and validate."""
    cfg_file = tmp_path / "clawbot.yaml"
    cfg_file.write_text(example_config_yaml)
    cfg = load_config(cfg_file)

    assert isinstance(cfg, ClawbotConfig)
    assert cfg.models.llm == "gemma3:1b"
    assert cfg.image_pipeline.lazy_load_models is True
    assert cfg.features.scraping is False  # V2 deferred


def test_empty_yaml_yields_all_defaults(tmp_path: Path) -> None:
    """An empty YAML file is a valid configuration; defaults fill the gap."""
    cfg_file = tmp_path / "empty.yaml"
    cfg_file.write_text("")
    cfg = load_config(cfg_file)

    assert cfg.models.llm == "gemma3:1b"
    assert cfg.scoring.candidate_cap == 50
    assert cfg.health.disk_warn_pct == 85


# ─────────────────────────────────────────────────────────────────────────────
# Failure modes — surfaced as ConfigError, never raw pydantic
# ─────────────────────────────────────────────────────────────────────────────


def test_missing_file_raises_config_error(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.yaml"
    with pytest.raises(ConfigError, match="not found"):
        load_config(missing)


def test_invalid_yaml_raises_config_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("this: is: not: yaml: -\n  -\n -")
    with pytest.raises(ConfigError, match="parse YAML"):
        load_config(bad)


def test_non_mapping_root_raises_config_error(tmp_path: Path) -> None:
    bad = tmp_path / "list.yaml"
    bad.write_text("- just\n- a\n- list\n")
    with pytest.raises(ConfigError, match="must be a mapping"):
        load_config(bad)


def test_unknown_section_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "extra.yaml"
    bad.write_text("not_a_real_section: 42\n")
    with pytest.raises(ConfigError) as exc_info:
        load_config(bad)
    # extra=forbid means pydantic flags it; we re-format into a readable line.
    assert "not_a_real_section" in str(exc_info.value)


def test_bad_log_level_message_is_readable(tmp_path: Path) -> None:
    bad = tmp_path / "level.yaml"
    bad.write_text("logging:\n  level: WHATEVER\n")
    with pytest.raises(ConfigError) as exc_info:
        load_config(bad)
    msg = str(exc_info.value)
    assert "logging.level" in msg
    assert "WHATEVER" in msg


def test_critical_must_exceed_warn(tmp_path: Path) -> None:
    bad = tmp_path / "thresholds.yaml"
    bad.write_text("health:\n  disk_warn_pct: 90\n  disk_critical_pct: 80\n")
    with pytest.raises(ConfigError, match="disk_critical_pct"):
        load_config(bad)


def test_bad_cron_field_count(tmp_path: Path) -> None:
    bad = tmp_path / "cron.yaml"
    # Only 4 fields, valid 5-field cron is required
    bad.write_text("schedule:\n  daily_outfit: '0 7 * *'\n")
    with pytest.raises(ConfigError, match="5 fields"):
        load_config(bad)


# ─────────────────────────────────────────────────────────────────────────────
# Path resolution and env overrides
# ─────────────────────────────────────────────────────────────────────────────


def test_env_var_resolves_path(tmp_path: Path) -> None:
    """If no path is passed, $CLAWBOT_CONFIG is honored."""
    cfg_file = tmp_path / "via_env.yaml"
    cfg_file.write_text("models:\n  llm: 'qwen2.5:3b'\n")

    cfg = load_config(env={"CLAWBOT_CONFIG": str(cfg_file)})
    assert cfg.models.llm == "qwen2.5:3b"


def test_env_override_takes_precedence(tmp_path: Path) -> None:
    """CLAWBOT_<SECTION>__<KEY>=value overrides the YAML."""
    cfg_file = tmp_path / "override.yaml"
    cfg_file.write_text("logging:\n  level: INFO\n")

    cfg = load_config(
        cfg_file,
        env={"CLAWBOT_LOGGING__LEVEL": "DEBUG"},
    )
    assert cfg.logging.level == "DEBUG"


def test_env_override_creates_new_section(tmp_path: Path) -> None:
    """Env override works even when the section is absent from the YAML."""
    cfg_file = tmp_path / "no_logging.yaml"
    cfg_file.write_text("models:\n  llm: 'gemma3:1b'\n")

    cfg = load_config(
        cfg_file,
        env={"CLAWBOT_LOGGING__LEVEL": "WARNING"},
    )
    assert cfg.logging.level == "WARNING"
    assert cfg.models.llm == "gemma3:1b"  # unchanged


def test_unrelated_env_vars_ignored(tmp_path: Path) -> None:
    """Env vars that don't match the prefix or shape are left alone."""
    cfg_file = tmp_path / "ignore.yaml"
    cfg_file.write_text("")
    cfg = load_config(
        cfg_file,
        env={
            "PATH": "/usr/bin",
            "CLAWBOT_CONFIG": str(cfg_file),  # path resolution, not an override
            "CLAWBOT_NO_SEPARATOR": "x",  # missing __
        },
    )
    # Should not raise, defaults preserved
    assert cfg.logging.level == "INFO"
