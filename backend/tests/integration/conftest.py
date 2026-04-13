"""Integration test conftest — auto-loads .env when BARKAIN_RUN_INTEGRATION_TESTS=1.

Fixes 2b-val-L4: `test_real_api_contracts.py` reads FIRECRAWL_API_KEY, GEMINI_API_KEY,
and UPCITEMDB_API_KEY at module load, so pytest previously needed
`set -a && source ../.env && set +a` before every run. Now the env is loaded
automatically when integration tests are enabled.
"""

import os
from pathlib import Path


def pytest_configure(config):
    """Auto-load .env into os.environ when running integration tests."""
    if os.environ.get("BARKAIN_RUN_INTEGRATION_TESTS") != "1":
        return

    # backend/tests/integration/conftest.py → backend/tests/integration/ →
    # backend/tests/ → backend/ → repo root
    env_path = Path(__file__).resolve().parents[3] / ".env"
    if not env_path.exists():
        return

    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)
