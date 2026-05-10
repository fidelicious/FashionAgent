"""
User profile module.

Why this layer exists on top of ``db.repo.ProfileRepo``:
    - The DB column type is just TEXT/INTEGER. We need controlled vocabularies
      ("warm" / "cool" / "neutral" for ``skin_undertone``) and friendly error
      messages for typos coming in from Discord commands.
    - Bootstrapping from ``config/profile.bootstrap.yaml`` lets the operator
      fill in a 40-field profile by editing a file rather than running 40
      Discord commands.

Public API:
    - ``ProfileError``: validation failure with a human message.
    - ``set_field(repo, field, value)``: strict-validated update.
    - ``set_many(repo, fields)``: atomic bulk update with the same validation.
    - ``bootstrap_from_yaml(repo, path)``: load a YAML and apply set_many.
    - ``get_profile(repo)``: return the row as a dict, JSON columns parsed.
    - ``ALLOWED_VALUES``: dict of field → allowed enum values, for Discord
      autocomplete and ``/profile help``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import yaml

from clawbot.db.repo import (
    PROFILE_FIELDS,
    PROFILE_JSON_FIELDS,
    Repo,
)


class ProfileError(ValueError):
    """Raised when a profile field name or value is invalid.

    The message is intended to be shown verbatim to the user, so it should
    name the offending field and the allowed alternatives where relevant.
    """


# ─────────────────────────────────────────────────────────────────────────────
# Controlled vocabularies
#
# Keep these short and editable. New options here cost nothing — but a typo
# at write time would be silent without this guard.
# ─────────────────────────────────────────────────────────────────────────────

ALLOWED_VALUES: dict[str, frozenset[str]] = {
    "body_shape": frozenset({
        "rectangle", "hourglass", "pear", "apple", "inverted-triangle", "other",
    }),
    "skin_tone": frozenset({"fair", "light", "medium", "olive", "tan", "deep"}),
    "skin_undertone": frozenset({"warm", "cool", "neutral"}),
    "glasses": frozenset({"none", "always", "occasional"}),
    "jewelry_metal": frozenset({"gold", "silver", "rose", "mixed"}),
    "rise_pref": frozenset({"low", "mid", "high"}),
    "commute_mode": frozenset({"walk", "bike", "car", "transit", "mixed"}),
}

# Numeric fields with acceptable ranges (inclusive).
NUMERIC_RANGES: dict[str, tuple[int, int]] = {
    "height_cm": (50, 250),
    "weight_kg_optional": (20, 300),
    "shoe_size_us": (1, 20),
    "inseam_cm": (40, 130),
    "comfort_vs_style": (1, 10),
    "monthly_clothing_budget_usd": (0, 100_000),
    "cost_per_wear_target": (0, 10_000),
}

# JSON list fields where every element should also pass an enum check.
JSON_LIST_VOCABS: dict[str, frozenset[str]] = {
    # Currently empty — favorite_colors_json is freeform on purpose so the
    # user can use named or hex colors. Add entries here later if we want
    # tighter constraints (e.g., a fabric whitelist).
}


# ─────────────────────────────────────────────────────────────────────────────
# Validation
# ─────────────────────────────────────────────────────────────────────────────


def _validate_field(field: str, value: Any) -> Any:
    """Normalize and validate a single (field, value) pair.

    Returns the value to store — possibly coerced (e.g., ``"7"`` → ``7``).
    Raises ``ProfileError`` on any problem.
    """
    if field not in PROFILE_FIELDS:
        raise ProfileError(
            f"Unknown profile field {field!r}. "
            f"Run /profile to see what's available."
        )

    if value is None:
        return None  # explicit clear

    # Enum fields
    if field in ALLOWED_VALUES:
        if not isinstance(value, str):
            raise ProfileError(f"{field}: expected a string, got {type(value).__name__}")
        v = value.strip().lower()
        allowed = ALLOWED_VALUES[field]
        if v not in allowed:
            raise ProfileError(
                f"{field}: {value!r} is not one of "
                f"{sorted(allowed)}"
            )
        return v

    # Numeric ranges
    if field in NUMERIC_RANGES:
        try:
            num: int | float = int(value) if field != "shoe_size_us" else float(value)
        except (TypeError, ValueError) as e:
            raise ProfileError(f"{field}: must be numeric, got {value!r}") from e
        lo, hi = NUMERIC_RANGES[field]
        if not (lo <= num <= hi):
            raise ProfileError(f"{field}: {num} is outside [{lo}, {hi}]")
        return num

    # JSON list fields with enum element check
    if field in JSON_LIST_VOCABS:
        if isinstance(value, str):
            raise ProfileError(f"{field}: expected a list, got string")
        vocab = JSON_LIST_VOCABS[field]
        for elem in value:
            if elem not in vocab:
                raise ProfileError(f"{field}: {elem!r} not in allowed list {sorted(vocab)}")
        return list(value)

    # JSON list fields that are freeform — accept list/tuple, reject scalars.
    if field in PROFILE_JSON_FIELDS:
        if isinstance(value, (list, tuple)):
            return list(value)
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            # Allow comma-separated shortcut: "navy, camel, burgundy"
            return [s.strip() for s in value.split(",") if s.strip()]
        raise ProfileError(f"{field}: expected a list/dict/comma-string")

    # Freeform text
    if isinstance(value, str):
        v = value.strip()
        return v if v else None
    return value


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────


def get_profile(repo: Repo) -> dict[str, Any]:
    """Return the singleton profile row, JSON columns deserialized."""
    return repo.profile.get()


def set_field(repo: Repo, field: str, value: Any) -> Any:
    """Validate and set a single profile field. Returns the stored value."""
    normalized = _validate_field(field, value)
    repo.profile.set(field, normalized)
    repo.audit.write(
        kind="profile_updated",
        actor="user",
        message=f"set {field}",
    )
    return normalized


def set_many(repo: Repo, fields: dict[str, Any]) -> dict[str, Any]:
    """Validate and atomically apply a bulk update.

    Validation runs *before* the DB transaction; if any field fails, no
    write happens. Returns the dict of stored (normalized) values.
    """
    if not fields:
        return {}
    normalized: dict[str, Any] = {}
    errors: list[str] = []
    for k, v in fields.items():
        try:
            normalized[k] = _validate_field(k, v)
        except ProfileError as e:
            errors.append(str(e))
    if errors:
        # Surface every problem in one go so editing the YAML is iterative.
        raise ProfileError("\n".join(errors))

    repo.profile.set_many(normalized)
    repo.audit.write(
        kind="profile_updated",
        actor="user",
        message=f"set {sorted(normalized.keys())}",
    )
    return normalized


def bootstrap_from_yaml(repo: Repo, path: str | Path) -> dict[str, Any]:
    """Load ``path`` (YAML) and apply every key as a profile update.

    Top-level YAML structure must be a mapping. Nested mappings are flattened
    one level — this lets the bootstrap file group fields visually:

    .. code-block:: yaml

        physical:
          skin_undertone: warm
          body_shape: hourglass
        sizing:
          top_size: M
          shoe_size_us: 8.5

    The grouping keys (``physical``, ``sizing``) are ignored at apply time.
    """
    path = Path(path)
    if not path.exists():
        raise ProfileError(f"Bootstrap file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ProfileError(
            f"Bootstrap YAML root must be a mapping, got {type(data).__name__}"
        )
    flat = _flatten(data)
    return set_many(repo, flat)


def known_fields() -> Iterable[str]:
    """Return all valid profile field names. Useful for /profile autocomplete."""
    return sorted(PROFILE_FIELDS)


# ─────────────────────────────────────────────────────────────────────────────
# Internals
# ─────────────────────────────────────────────────────────────────────────────


def _flatten(data: dict[str, Any]) -> dict[str, Any]:
    """One-level flatten of grouped bootstrap YAML.

    Group keys must be plain mappings; if a top-level key matches a known
    profile field, it's kept as-is.
    """
    out: dict[str, Any] = {}
    for k, v in data.items():
        if k in PROFILE_FIELDS:
            out[k] = v
        elif isinstance(v, dict):
            for inner_k, inner_v in v.items():
                if inner_k in out:
                    raise ProfileError(
                        f"Duplicate field {inner_k!r} in bootstrap YAML "
                        f"(seen under multiple groups)"
                    )
                out[inner_k] = inner_v
        else:
            # Top-level key that isn't a profile field and isn't a group.
            # Surface as a validation error rather than silently dropping.
            out[k] = v  # set_many() will raise with a clear message
    return out
