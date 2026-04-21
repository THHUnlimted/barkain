"""Seed `portal_bonuses` with realistic demo rates.

# DEMO SEED — replace with live worker scrapes in Phase 3g.
# Safe to delete after 3g lands.

Step 3e assumes at least a few rows in `portal_bonuses` so the stacking
story has a third layer. In dev the table is usually empty, and the live
portal_rates worker (Step 2h) runs on a cron that may not have fired on
the current machine. Without portal data, every recommendation collapses
to identity + card — fine for correctness, flat for the demo.

Idempotent UPSERT on `(portal_source, retailer_id)`. Rows for missing
retailers are silently skipped (e.g., if `samsung_direct` hasn't been
seeded yet, we just don't insert Rakuten × Samsung).

Usage:
    python3 scripts/seed_portal_bonuses_demo.py
"""

import asyncio
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Rates are the "typical advertised" number from each portal circa 2026-04.
# NOT live — do not treat as truth. Replace in 3g.
SEED_ROWS: list[dict] = [
    {"portal_source": "rakuten", "retailer_id": "amazon", "bonus_value": 2.0},
    {"portal_source": "rakuten", "retailer_id": "best_buy", "bonus_value": 1.0},
    {"portal_source": "rakuten", "retailer_id": "walmart", "bonus_value": 2.0},
    {"portal_source": "rakuten", "retailer_id": "target", "bonus_value": 1.0},
    {"portal_source": "rakuten", "retailer_id": "home_depot", "bonus_value": 1.5},
    {"portal_source": "rakuten", "retailer_id": "samsung_direct", "bonus_value": 4.0},
    {"portal_source": "rakuten", "retailer_id": "apple_direct", "bonus_value": 1.0},
    {"portal_source": "topcashback", "retailer_id": "amazon", "bonus_value": 1.5},
    {"portal_source": "topcashback", "retailer_id": "best_buy", "bonus_value": 2.0},
    {"portal_source": "topcashback", "retailer_id": "target", "bonus_value": 2.5},
    {"portal_source": "topcashback", "retailer_id": "home_depot", "bonus_value": 2.5},
    {"portal_source": "befrugal", "retailer_id": "backmarket", "bonus_value": 4.0},
    {"portal_source": "befrugal", "retailer_id": "walmart", "bonus_value": 2.5},
]


async def seed(session: AsyncSession) -> dict[str, int]:
    """Upsert each row. Returns {"inserted", "updated", "skipped"}."""
    counts = {"inserted": 0, "updated": 0, "skipped": 0}
    now = datetime.now(UTC)

    # Pull existing retailer ids so we can skip gracefully when a demo
    # environment hasn't seeded brand-direct rows.
    present = {
        row[0]
        for row in (await session.execute(text("SELECT id FROM retailers"))).all()
    }

    for row in SEED_ROWS:
        if row["retailer_id"] not in present:
            counts["skipped"] += 1
            continue

        existing = await session.execute(
            text(
                "SELECT id FROM portal_bonuses "
                "WHERE portal_source = :ps AND retailer_id = :rid"
            ),
            {"ps": row["portal_source"], "rid": row["retailer_id"]},
        )
        if existing.first() is None:
            action = "inserted"
        else:
            action = "updated"

        await session.execute(
            text(
                """
                INSERT INTO portal_bonuses (
                    portal_source, retailer_id, bonus_type, bonus_value,
                    normal_value, effective_from, verified_by
                )
                VALUES (
                    :ps, :rid, 'percentage', :bv, :bv, :now, 'demo_seed'
                )
                ON CONFLICT (portal_source, retailer_id) DO UPDATE SET
                    bonus_value = EXCLUDED.bonus_value,
                    normal_value = EXCLUDED.normal_value,
                    effective_from = EXCLUDED.effective_from,
                    verified_by = EXCLUDED.verified_by
                """
            ),
            {
                "ps": row["portal_source"],
                "rid": row["retailer_id"],
                "bv": row["bonus_value"],
                "now": now,
            },
        )
        counts[action] += 1

    await session.commit()
    return counts


async def main() -> None:
    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://app:app@localhost:5432/barkain",
    )
    engine = create_async_engine(database_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as session:
        counts = await seed(session)

    await engine.dispose()

    print(
        f"portal_bonuses seed: inserted={counts['inserted']} "
        f"updated={counts['updated']} skipped={counts['skipped']}"
    )


if __name__ == "__main__":
    asyncio.run(main())
