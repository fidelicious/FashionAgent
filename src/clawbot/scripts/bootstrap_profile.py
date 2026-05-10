"""
Bootstrap the user profile from ``config/profile.bootstrap.yaml``.

Run inside the container:

    docker exec clawbot python -m clawbot.scripts.bootstrap_profile

Or from a local dev install:

    python -m clawbot.scripts.bootstrap_profile --yaml ./config/profile.bootstrap.yaml \\
                                                --db   ./db/clawbot.db

Behavior is idempotent — re-running just overwrites whatever fields are
present in the YAML. Fields you don't list are left alone.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from clawbot.config import load_config
from clawbot.db import Repo, connect, run_migrations
from clawbot.profile import ProfileError, bootstrap_from_yaml

# Migrations live alongside the package so we can reach them at runtime.
_MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "db" / "migrations"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--yaml",
        default=None,
        help="Path to bootstrap YAML. Defaults to config/profile.bootstrap.yaml under "
        "the configured paths.home.",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="Override DB path. Default comes from clawbot config.",
    )
    args = parser.parse_args(argv)

    cfg = load_config()
    db_path = Path(args.db) if args.db else Path(cfg.paths.db_path)
    yaml_path = (
        Path(args.yaml)
        if args.yaml
        else Path(cfg.paths.home) / "config" / "profile.bootstrap.yaml"
    )

    conn = connect(db_path)
    run_migrations(conn, _MIGRATIONS_DIR)
    repo = Repo(conn)

    try:
        applied = bootstrap_from_yaml(repo, yaml_path)
    except ProfileError as e:
        print(f"Bootstrap failed:\n{e}", file=sys.stderr)
        return 1

    print(f"Profile bootstrap applied {len(applied)} field(s) from {yaml_path}.")
    for k in sorted(applied):
        print(f"  • {k}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
