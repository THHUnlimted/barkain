import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.database import Base
from app.models import *  # noqa: F401, F403 — register all models
from scripts.seed_retailers import seed_retailers

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://app:test@localhost:5433/barkain_test",
)


@pytest.fixture
async def seed_session():
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE"))
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    conn = await engine.connect()
    txn = await conn.begin()
    session = AsyncSession(bind=conn, expire_on_commit=False)

    # Clean retailers table for test isolation
    await session.execute(text("DELETE FROM retailer_health"))
    await session.execute(text("DELETE FROM retailers"))
    await session.flush()

    yield session

    await session.close()
    await txn.rollback()
    await conn.close()
    await engine.dispose()


async def test_seed_creates_11_retailers(seed_session):
    await seed_retailers(seed_session)
    await seed_session.flush()

    result = await seed_session.execute(text("SELECT COUNT(*) FROM retailers"))
    count = result.scalar()
    assert count == 11


async def test_seed_is_idempotent(seed_session):
    await seed_retailers(seed_session)
    await seed_session.flush()
    await seed_retailers(seed_session)
    await seed_session.flush()

    result = await seed_session.execute(text("SELECT COUNT(*) FROM retailers"))
    count = result.scalar()
    assert count == 11
