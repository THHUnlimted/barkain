"""Tests for ``scripts/check_catalog_freshness.py``.

The load-bearing test here is ``test_seed_module_top_level_imports_are_stdlib``.
The freshness checker's entire premise is that it runs in a bare CI checkout
with no ``pip install`` — that is why it reads the seed file instead of the
database. But it gets ``ROTATING_CATEGORIES`` by *importing* the seed module,
so any third-party import that module grows at top level silently breaks the
alarm. That is not hypothetical: ``scripts/seed_rotating_categories.py`` had
``from sqlalchemy import text`` at module level, and the `catalog-freshness`
job failed with ``ModuleNotFoundError`` on a PR whose catalog data was current.

An alarm that fails for its own reasons is worse than no alarm — it trains
people to ignore red, which is the exact failure this whole check exists to
prevent. So the import surface gets pinned mechanically.

Parsing is done with ``ast`` rather than by importing, so this test asserts
what a dependency-free interpreter would see, not what this environment (which
has SQLAlchemy installed) happens to allow.

The remaining tests cover the checker's three date branches through the
``--today`` override, so the expiry logic is verified without waiting for the
calendar.
"""

from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECK_SCRIPT = REPO_ROOT / "scripts" / "check_catalog_freshness.py"
SEED_SCRIPT = REPO_ROOT / "scripts" / "seed_rotating_categories.py"


def _load_checker():
    spec = importlib.util.spec_from_file_location("check_catalog_freshness", CHECK_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_catalog_freshness"] = module
    spec.loader.exec_module(module)
    return module


def _top_level_import_roots(source: str) -> set[str]:
    """Root module names imported at module scope, excluding TYPE_CHECKING blocks.

    Only module-scope statements count. Imports inside functions are deferred to
    call time and cost a dependency-free importer nothing, which is precisely
    how the seed script keeps its SQLAlchemy usage.
    """
    tree = ast.parse(source)
    roots: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            # Relative imports have no resolvable root package name here.
            if node.level == 0 and node.module:
                roots.add(node.module.split(".")[0])
    return roots


def test_seed_module_top_level_imports_are_stdlib():
    """The seed module must import for its data alone with zero third-party deps.

    `check_catalog_freshness.py` imports it in a CI job that runs no
    `pip install`. A top-level `from sqlalchemy import text` here turns the
    freshness alarm into a ModuleNotFoundError traceback.
    """
    roots = _top_level_import_roots(SEED_SCRIPT.read_text())
    non_stdlib = roots - set(sys.stdlib_module_names)
    assert not non_stdlib, (
        f"scripts/seed_rotating_categories.py imports {sorted(non_stdlib)} at module "
        "level. The catalog-freshness CI job installs no dependencies — move these "
        "inside the function that uses them (see seed_rotating / main)."
    )


def test_checker_module_top_level_imports_are_stdlib():
    """Same contract for the checker itself."""
    roots = _top_level_import_roots(CHECK_SCRIPT.read_text())
    non_stdlib = roots - set(sys.stdlib_module_names)
    assert not non_stdlib, (
        f"scripts/check_catalog_freshness.py imports {sorted(non_stdlib)} at module "
        "level, but runs in a CI job with no dependencies installed."
    )


def test_checker_runs_in_a_subprocess_without_backend_on_the_path():
    """End-to-end proof the script is self-contained.

    A subprocess started from the repo root inherits none of pytest's
    conftest-managed `sys.path` surgery, so this exercises the same import
    resolution the CI job does.
    """
    result = subprocess.run(
        [sys.executable, str(CHECK_SCRIPT), "--today", "2026-08-01"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr
    assert "rotating_categories" in result.stdout


def test_current_quarter_is_reported_fresh():
    """Guards the seeded data itself, not just the plumbing."""
    checker = _load_checker()
    ok, lines = checker.check_rotating_categories(date(2026, 8, 1), checker.WARN_WINDOW_DAYS)

    assert ok, "\n".join(lines)
    assert lines, "checker produced no output rows — seed data may be empty"
    assert all(line.lstrip().startswith("✓") for line in lines), lines


def test_expired_quarter_fails_and_names_the_card():
    """After 2026-09-30 both cards are lapsed; the message must say which."""
    checker = _load_checker()
    ok, lines = checker.check_rotating_categories(date(2026, 10, 15), checker.WARN_WINDOW_DAYS)

    assert ok is False
    assert any("EXPIRED" in line for line in lines), lines
    assert any("discover/it_cash_back" in line for line in lines), lines


def test_warning_window_fails_before_expiry():
    """The point of the alarm is lead time — red must precede the lapse."""
    checker = _load_checker()
    # 2026-09-20 is 10 days out from the 2026-09-30 expiry: inside the 14-day
    # window, so still effective but already failing.
    ok, lines = checker.check_rotating_categories(date(2026, 9, 20), checker.WARN_WINDOW_DAYS)

    assert ok is False
    assert any("expires in 10 day(s)" in line for line in lines), lines
    assert not any("EXPIRED" in line for line in lines), lines


@pytest.mark.parametrize("days_out", [15, 30])
def test_outside_warning_window_passes(days_out: int):
    """Well before expiry the check stays green so it is not chronically red."""
    checker = _load_checker()
    today = date(2026, 9, 30) - timedelta(days=days_out)
    ok, _ = checker.check_rotating_categories(today, checker.WARN_WINDOW_DAYS)

    assert ok is True
