import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

# Ensure backend/ is on path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Set test env before importing app
os.environ.setdefault("ENVIRONMENT", "test")

from app.database import Base
from fastapi import Depends

# Step 3f — import the full model registry so Base.metadata knows about every
# table (AffiliateClick in particular is only imported from app.models, not
# from any router/service). Without this, running the m12 tests in isolation
# skipped the affiliate_clicks table in create_all.
import app.models  # noqa: F401

from app.dependencies import get_current_user, get_db, get_rate_limiter, get_redis
from app.main import app

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://app:test@localhost:5433/barkain_test",
)


# MARK: - One-time schema setup (runs once per pytest session via autouse)

_schema_ready = False


async def _ensure_schema(engine):
    """Create TimescaleDB extension and bootstrap the schema.

    Drift detection: ``Base.metadata.create_all`` is a no-op for tables
    that already exist, so a stale test DB silently keeps a schema from
    a prior step (missing new columns or constraints). To catch this,
    we probe for a marker from the most recent migration before
    creating tables — if missing, we drop the public schema and
    recreate everything.

    The marker is the cheapest available signal that proves the schema
    matches HEAD. Update the query whenever a new migration adds a
    column/constraint to existing tables.
    """
    global _schema_ready
    if _schema_ready:
        return

    # Drift marker: portal_configs table from migration 0012.
    # Update this query when adding new migrations that introduce
    # constraints, columns, or indexes to existing tables.
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        marker = await conn.execute(
            text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_name = 'portal_configs'"
            )
        )
        schema_current = marker.scalar() is not None

        if not schema_current:
            await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
            await conn.execute(
                text("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE")
            )
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        await conn.run_sync(Base.metadata.create_all)

    _schema_ready = True


# MARK: - Test Database Engine

@pytest_asyncio.fixture
async def test_engine():
    engine = create_async_engine(TEST_DATABASE_URL)
    await _ensure_schema(engine)
    yield engine
    await engine.dispose()


# MARK: - Database Session (per test, with rollback)

@pytest_asyncio.fixture
async def db_session(test_engine):
    conn = await test_engine.connect()
    txn = await conn.begin()
    session = AsyncSession(bind=conn, expire_on_commit=False)

    # Clean up any data from previous tests (since rollback doesn't work across engines)
    yield session

    await session.close()
    await txn.rollback()
    await conn.close()


# MARK: - Fake Redis

@pytest_asyncio.fixture
async def fake_redis():
    import fakeredis.aioredis

    r = fakeredis.aioredis.FakeRedis()
    yield r
    await r.flushall()
    await r.aclose()


# MARK: - Serper synthesis bypass (vendor-migrate-1)

@pytest.fixture(autouse=True)
def _serper_synthesis_disabled(monkeypatch):
    """Force ``resolve_via_serper`` → None for every test by default.

    The Serper-then-grounded wire-up in m1_product/service.py:_get_gemini_data
    fires resolve_via_serper before falling back to grounded Gemini. Tests
    that mock the grounded path (``gemini_generate_json``) without also
    handling Serper would otherwise hit the real Serper API (developers
    keep SERPER_API_KEY in .env for the bench scripts) and either return
    surprising real results or fail intermittently.

    This fixture short-circuits the Serper path universally; tests that
    specifically want to assert Serper-path behavior can patch
    ``modules.m1_product.service.resolve_via_serper`` themselves to
    override this default.
    """
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        "modules.m1_product.service.resolve_via_serper",
        AsyncMock(return_value=None),
    )
    yield


# MARK: - Serper Shopping bypass (Step 3n / M14 misc-retailer)

@pytest.fixture(autouse=True)
def _serper_shopping_disabled(monkeypatch):
    """Force ``_serper_shopping_fetch`` → None for every test by default.

    Mirrors `_serper_synthesis_disabled` for the misc-retailer slot. The
    SerperShoppingAdapter calls `ai.web_search._serper_shopping_fetch`
    directly; we patch at the adapter import site so tests that exercise
    the adapter directly can override this.

    Tests that want real Serper Shopping coverage should monkeypatch
    `modules.m14_misc_retailer.adapters.serper_shopping._serper_shopping_fetch`
    themselves; this autouse fixture short-circuits the path so missing
    SERPER_API_KEY in CI doesn't spam warning logs and a hot .env doesn't
    leak real network calls into the test suite.
    """
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        "modules.m14_misc_retailer.adapters.serper_shopping._serper_shopping_fetch",
        AsyncMock(return_value=None),
    )
    yield


# MARK: - Demo mode toggle (Step 3f Pre-Fix #4)

@pytest.fixture
def without_demo_mode(monkeypatch):
    """Force DEMO_MODE=False for tests that verify real auth rejection.

    `.env` leaves DEMO_MODE=1 for local runs. Tests asserting "unauthed
    request returns 401" must flip it off, otherwise `get_current_user`
    short-circuits to `demo_user` and the 401 never fires.

    Patches the module-level `settings` instance directly because
    `get_current_user` reads `settings.DEMO_MODE` at call time.
    """
    from app.config import settings

    monkeypatch.setattr(settings, "DEMO_MODE", False)
    yield


# MARK: - Mock Auth

MOCK_USER_ID = "user_test_123"


@pytest_asyncio.fixture
async def client(db_session, fake_redis):
    """Authenticated test client with all dependencies overridden."""

    async def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_redis] = lambda: fake_redis
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": MOCK_USER_ID,
        "email": "test@example.com",
        "session_id": "sess_test",
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def unauthed_client(db_session, fake_redis):
    """Test client without auth override — for testing 401 responses."""

    async def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_redis] = lambda: fake_redis

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# MARK: - Test-only auth endpoint


@app.get("/api/v1/test-auth")
async def _test_auth_endpoint(user: dict = Depends(get_current_user)):
    return {"user_id": user["user_id"]}


# MARK: - Test-only rate-limited endpoint


@app.get("/api/v1/test-rate-limit")
async def _test_rate_limit_endpoint(
    user: dict = Depends(get_current_user),
    _rate: None = Depends(get_rate_limiter("general")),
):
    return {"ok": True}
