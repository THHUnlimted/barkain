import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.database import Base
from app.models import *  # noqa: F401, F403 — register all models

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://app:test@localhost:5433/barkain_test",
)

EXPECTED_TABLES = [
    "affiliate_clicks",
    "card_reward_programs",
    "coupon_cache",
    "discount_programs",
    "listings",
    "portal_bonuses",
    "prediction_cache",
    "price_history",
    "prices",
    "products",
    "receipt_items",
    "receipts",
    "retailer_health",
    "retailers",
    "rotating_categories",
    "user_cards",
    "user_category_selections",
    "user_discount_profiles",
    "users",
    "watchdog_events",
    "watched_items",
]


@pytest.fixture
async def migration_engine():
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE"))
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Convert price_history to hypertable (mirrors Alembic migration)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("SELECT create_hypertable('price_history', 'time', if_not_exists => true)")
            )
    except Exception:
        pass  # Already a hypertable
    yield engine
    await engine.dispose()


async def test_all_21_tables_exist(migration_engine):
    async with migration_engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' "
                "ORDER BY tablename"
            )
        )
        tables = [row[0] for row in result.fetchall()]

    for table in EXPECTED_TABLES:
        assert table in tables, f"Missing table: {table}"
    assert len([t for t in tables if t in EXPECTED_TABLES]) == 21


async def test_price_history_is_hypertable(migration_engine):
    async with migration_engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT hypertable_name FROM timescaledb_information.hypertables "
                "WHERE hypertable_name = 'price_history'"
            )
        )
        rows = result.fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "price_history"
