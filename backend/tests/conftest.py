import os
import sys
from pathlib import Path

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

from app.dependencies import get_current_user, get_db, get_rate_limiter, get_redis
from app.main import app

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://app:test@localhost:5433/barkain_test",
)


# MARK: - One-time schema setup (runs once per pytest session via autouse)

_schema_ready = False


async def _ensure_schema(engine):
    """Create TimescaleDB extension and all tables if not already present."""
    global _schema_ready
    if _schema_ready:
        return
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE"))
    async with engine.begin() as conn:
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
