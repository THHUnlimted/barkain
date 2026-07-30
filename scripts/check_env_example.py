"""Assert that every setting in backend/app/config.py appears in .env.example.

Why this exists
---------------
`.env.example` drifted to 37-of-63 settings documented. The expensive omission
was `DECODO_SCRAPER_API_AUTH`: an environment built from the example file lost
Amazon pricing entirely, with no error and no log line, because the amazon leg
silently falls back to a container path that is broken from cloud IPs.

The failure mode is always the same — a setting is added to `config.py` with a
default that works on the author's machine, and nobody notices the example file
never learned about it. This script closes that loop mechanically.

A setting counts as documented whether it is live (`KEY=value`) or commented
(`# KEY=value`). Commented entries are the preferred form for anything with a
usable default: they are discoverable but inert, so they cannot drift out of
sync with `config.py` the way a duplicated live default can (SP-5 post-mortem).

Parsing is done with `ast`, not by importing `app.config` — this must run in a
bare checkout with no dependencies installed and no `.env` present.

Usage:
    python3 scripts/check_env_example.py          # exits 1 on drift
"""

import ast
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "backend" / "app" / "config.py"
ENV_EXAMPLE_PATH = REPO_ROOT / ".env.example"

# Read by boto3 straight from the environment rather than through Settings, so
# they legitimately appear in .env.example without a config.py counterpart.
ENV_ONLY_KEYS = {"AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"}

# `# KEY=` or `KEY=`, allowing the commented form any leading whitespace.
_ENV_KEY_RE = re.compile(r"^\s*#?\s*([A-Z][A-Z0-9_]*)\s*=")


def settings_fields(config_source: str) -> list[str]:
    """Return every annotated field name on the Settings class, in file order."""
    tree = ast.parse(config_source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Settings":
            return [
                stmt.target.id
                for stmt in node.body
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
            ]
    raise RuntimeError(f"No `class Settings` found in {CONFIG_PATH}")


def documented_keys(env_source: str) -> set[str]:
    """Return every key mentioned in .env.example, live or commented."""
    keys = set()
    for line in env_source.splitlines():
        match = _ENV_KEY_RE.match(line)
        if match:
            keys.add(match.group(1))
    return keys


def main() -> int:
    declared = settings_fields(CONFIG_PATH.read_text())
    documented = documented_keys(ENV_EXAMPLE_PATH.read_text())

    missing = [name for name in declared if name not in documented]
    orphaned = sorted(documented - set(declared) - ENV_ONLY_KEYS)

    if missing:
        print(
            f"✗ {len(missing)} setting(s) in backend/app/config.py are absent "
            f"from .env.example:\n"
        )
        for name in missing:
            print(f"    {name}")
        print(
            "\nAdd each one — commented out with its default if it has a usable "
            "one, live if it is a secret you must supply."
        )

    if orphaned:
        print(
            f"\n⚠ {len(orphaned)} key(s) in .env.example have no counterpart in "
            f"config.py (renamed? removed? add to ENV_ONLY_KEYS if read "
            f"directly from the environment):\n"
        )
        for name in orphaned:
            print(f"    {name}")

    if missing:
        return 1

    print(f"✓ all {len(declared)} settings documented in .env.example")
    return 0 if not orphaned else 0


if __name__ == "__main__":
    sys.exit(main())
