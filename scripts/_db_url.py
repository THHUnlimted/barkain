"""Shared DB URL helper for seed scripts (Step 3f Pre-Fix #3).

Centralizes the DATABASE_URL fallback so a single place owns the
docker-compose default (`app:localdev`). Prior to this, seed scripts
drifted between `app:app` and `app:localdev` causing password-mismatch
failures on fresh clones.

Usage:
    from scripts._db_url import get_dev_db_url
    database_url = get_dev_db_url()
    engine = create_async_engine(database_url)
"""

import os

DEFAULT_DEV_DB_URL = "postgresql+asyncpg://app:localdev@localhost:5432/barkain"


def get_dev_db_url() -> str:
    """Return the dev database URL for seed scripts.

    Honors `DATABASE_URL` from the environment when set (CI, EC2 redeploy,
    integration tests). Otherwise returns the docker-compose default.
    """
    return os.getenv("DATABASE_URL", DEFAULT_DEV_DB_URL)
