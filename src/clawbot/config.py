"""
Config loader.

Single entrypoint: ``load_config()``. Reads ``$CLAWBOT_CONFIG`` (default
``/app/config/clawbot.yaml``) and validates the YAML against typed pydantic
models. Environment variables prefixed with ``CLAWBOT_`` override matching
keys; secrets always come from ``secrets/.env`` via process env, never the
YAML.

The function is pure — it raises ``ConfigError`` on any problem rather than
exiting. Tests assert on the error messages.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

# ─────────────────────────────────────────────────────────────────────────────
# Errors
# ─────────────────────────────────────────────────────────────────────────────


class ConfigError(Exception):
    """Raised when config is missing, unreadable, or invalid.

    Always carries a human-readable message that points at the offending
    key path; we never let pydantic's raw error reach the operator.
    """


# ─────────────────────────────────────────────────────────────────────────────
# Section models — one per top-level YAML key
# ─────────────────────────────────────────────────────────────────────────────


class ModelsConfig(BaseModel):
    """LLM / embedding / vision model selection and Ollama endpoint."""

    llm: str = "gemma3:1b"
    embedding: str = "nomic-embed-text"
    vision_clip: str = "patrickjohncyh/fashion-clip"
    ollama_base_url: str = "http://ollama:11434"
    llm_timeout_seconds: int = Field(60, gt=0, le=600)
    llm_max_retries: int = Field(2, ge=0, le=10)


class PathsConfig(BaseModel):
    """Filesystem paths inside the container."""

    home: Path = Path("/data")
    db_path: Path = Path("/data/db/clawbot.db")
    images_dir: Path = Path("/data/images")
    inbox_dir: Path = Path("/data/inbox")
    logs_dir: Path = Path("/data/logs")
    backups_dir: Path = Path("/data/backups")
    models_cache_dir: Path = Path("/data/models")


class ImagePipelineConfig(BaseModel):
    """Vision pipeline knobs.

    ``lazy_load_models`` is the single biggest RAM lever on the 8 GB NUC —
    leave it true unless image throughput becomes a bottleneck.
    """

    thumbnail_max_px: int = Field(512, gt=0, le=4096)
    rembg_model: str = "u2netp"
    lazy_load_models: bool = True
    fashion_clip_confidence_threshold: float = Field(0.55, ge=0.0, le=1.0)
    ocr_enabled_for_screenshots: bool = True


class ScoringConfig(BaseModel):
    """Outfit scoring weights. Positives sum to 100 by convention but not enforced."""

    style_match: int = 35
    compatibility: int = 25
    season: int = 15
    occasion_match: int = 15
    budget_alignment: int = 10
    duplicate_penalty: int = 25
    candidate_cap: int = Field(50, gt=0, le=1000)


class ScheduleConfig(BaseModel):
    """APScheduler cron expressions / intervals.

    Cron strings are validated lazily by APScheduler at load time. We only
    do a sanity-check on field count here; full parsing happens in scheduler.py.
    """

    daily_outfit: str = "0 7 * * *"
    nightly_backup: str = "30 2 * * *"
    inbox_sweep_seconds: int = Field(60, gt=0, le=3600)
    disk_check: str = "0 * * * *"
    db_vacuum: str = "0 3 * * 0"

    @field_validator("daily_outfit", "nightly_backup", "disk_check", "db_vacuum")
    @classmethod
    def _check_cron_field_count(cls, v: str) -> str:
        # Sanity check only — we want a clear error here rather than deep
        # inside APScheduler's parser.
        if len(v.split()) != 5:
            raise ValueError(f"cron expression must have 5 fields, got: {v!r}")
        return v


class BackupConfig(BaseModel):
    """Backup tarball retention and inclusion rules."""

    retain_days: int = Field(14, ge=1, le=365)
    include: list[str] = Field(default_factory=lambda: ["/data/db", "/data/images"])
    exclude_globs: list[str] = Field(default_factory=list)


class HealthConfig(BaseModel):
    """Health and safety thresholds."""

    disk_warn_pct: int = Field(85, ge=1, le=100)
    disk_critical_pct: int = Field(95, ge=1, le=100)
    llm_required_for_outfits: bool = True

    @field_validator("disk_critical_pct")
    @classmethod
    def _critical_above_warn(cls, v: int, info: Any) -> int:
        warn = info.data.get("disk_warn_pct", 85)
        if v <= warn:
            raise ValueError(f"disk_critical_pct ({v}) must be greater than disk_warn_pct ({warn})")
        return v


class LoggingConfig(BaseModel):
    """structlog output format."""

    level: str = "INFO"
    format: str = "json"
    rotation_mb: int = Field(50, gt=0, le=10_000)
    retention_files: int = Field(7, ge=1, le=365)

    @field_validator("level")
    @classmethod
    def _level_known(cls, v: str) -> str:
        v_up = v.upper()
        if v_up not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"unknown log level: {v!r}")
        return v_up

    @field_validator("format")
    @classmethod
    def _format_known(cls, v: str) -> str:
        if v not in {"json", "console"}:
            raise ValueError(f"format must be 'json' or 'console', got: {v!r}")
        return v


class FeaturesConfig(BaseModel):
    """V2/V3 feature flags. All default false in V1."""

    scraping: bool = False
    open_webui: bool = False
    feedback_learning: bool = False
    weather: bool = False
    calendar: bool = False


class DiscordConfig(BaseModel):
    """Non-secret Discord knobs.

    The bot token, user ID, guild ID, and channel ID are loaded separately
    from ``secrets/.env`` by ``clawbot.discord_secrets`` — they are never
    written to the YAML so the config file stays safe to commit.

    ``enabled`` defaults to False so that tests and the foundation-pass
    container don't try to dial Discord without a real token.
    """

    enabled: bool = False
    sync_commands_on_startup: bool = True
    unauthorized_reply: str = (
        "Sorry, this bot is private. The operator has been notified."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Top-level config
# ─────────────────────────────────────────────────────────────────────────────


class ClawbotConfig(BaseModel):
    """Full clawbot configuration. One instance per process."""

    models: ModelsConfig = Field(default_factory=ModelsConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    image_pipeline: ImagePipelineConfig = Field(default_factory=ImagePipelineConfig)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    backup: BackupConfig = Field(default_factory=BackupConfig)
    health: HealthConfig = Field(default_factory=HealthConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    features: FeaturesConfig = Field(default_factory=FeaturesConfig)
    discord: DiscordConfig = Field(default_factory=DiscordConfig)

    model_config = {
        # Reject unknown YAML keys — surfaces typos immediately rather than
        # letting them silently fall through to defaults.
        "extra": "forbid",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────


# Env var prefix: CLAWBOT_<SECTION>__<KEY>=value uses double-underscore as
# the section/key separator. Example: CLAWBOT_LOGGING__LEVEL=DEBUG
_ENV_PREFIX = "CLAWBOT_"
_ENV_SEPARATOR = "__"


def load_config(
    path: str | os.PathLike[str] | None = None,
    *,
    env: dict[str, str] | None = None,
) -> ClawbotConfig:
    """Load and validate clawbot config.

    Parameters
    ----------
    path
        Path to the YAML file. If omitted, falls back to ``$CLAWBOT_CONFIG``,
        then to ``/app/config/clawbot.yaml``.
    env
        Optional override of the process env (used in tests). Defaults to ``os.environ``.

    Returns
    -------
    ClawbotConfig
        Fully validated configuration.

    Raises
    ------
    ConfigError
        If the file is missing, unparseable, or fails validation.
    """
    env = dict(os.environ if env is None else env)

    cfg_path = _resolve_path(path, env)
    raw = _read_yaml(cfg_path)
    raw = _apply_env_overrides(raw, env)

    try:
        return ClawbotConfig.model_validate(raw)
    except ValidationError as e:
        # Convert pydantic's verbose error into a single readable line per
        # bad field. Operators don't want to read traceback context.
        lines = [f"Config validation failed for {cfg_path}:"]
        for err in e.errors():
            loc = ".".join(str(p) for p in err["loc"])
            lines.append(f"  - {loc}: {err['msg']} (got {err.get('input')!r})")
        raise ConfigError("\n".join(lines)) from e


# ─────────────────────────────────────────────────────────────────────────────
# Internals
# ─────────────────────────────────────────────────────────────────────────────


def _resolve_path(
    explicit: str | os.PathLike[str] | None, env: dict[str, str]
) -> Path:
    """Resolve config path with precedence: explicit > env var > default."""
    if explicit is not None:
        return Path(explicit)
    if "CLAWBOT_CONFIG" in env:
        return Path(env["CLAWBOT_CONFIG"])
    return Path("/app/config/clawbot.yaml")


def _read_yaml(path: Path) -> dict[str, Any]:
    """Load YAML, raise ConfigError with a clear message on failure."""
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigError(f"Could not parse YAML at {path}: {e}") from e

    if data is None:
        # Empty file is valid but yields {} so all defaults apply.
        return {}
    if not isinstance(data, dict):
        raise ConfigError(
            f"Config root in {path} must be a mapping, got {type(data).__name__}"
        )
    return data


def _apply_env_overrides(raw: dict[str, Any], env: dict[str, str]) -> dict[str, Any]:
    """Apply ``CLAWBOT_<SECTION>__<KEY>=value`` overrides onto the raw dict.

    Unknown keys are left to pydantic to reject (we don't pre-filter).
    String values stay strings; pydantic coerces to the declared type.
    """
    overridden = dict(raw)  # shallow copy so the caller's dict is untouched
    for key, value in env.items():
        if not key.startswith(_ENV_PREFIX) or _ENV_SEPARATOR not in key:
            continue
        # CLAWBOT_LOGGING__LEVEL → ('logging', 'level')
        path_str = key[len(_ENV_PREFIX):]
        section, _, leaf = path_str.partition(_ENV_SEPARATOR)
        section_lc = section.lower()
        leaf_lc = leaf.lower()
        if not section_lc or not leaf_lc:
            continue
        bucket = overridden.get(section_lc)
        if not isinstance(bucket, dict):
            bucket = {}
        bucket[leaf_lc] = value
        overridden[section_lc] = bucket
    return overridden
