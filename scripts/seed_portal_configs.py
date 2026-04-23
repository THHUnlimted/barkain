"""Seed `portal_configs` with display + promo metadata for shopping portals.

Five rows total: rakuten / topcashback / befrugal active, chase_shop /
capital_one_shopping inactive (deferred — auth-gated, out of scope for 3g).

Promo amounts and copy reflect the live values circa 2026-04-22:
    * Rakuten: $50 welcome bonus on $30 spend within 90 days, ends
      2026-06-30 (after which it reverts to $30 — refresh manually or
      via a future admin script when the promo cycle changes).
    * TopCashback: no signup promo configured until FlexOffers approval.
    * BeFrugal: personal referral grants no welcome bonus, only ongoing
      cashback access.

Idempotent: ON CONFLICT (portal_source) DO UPDATE keeps the table in sync
with this file. Safe to re-run after editing promo amounts.

Usage:
    python3 scripts/seed_portal_configs.py
"""

import asyncio
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


SEED_ROWS: list[dict] = [
    {
        "portal_source": "rakuten",
        "display_name": "Rakuten",
        "homepage_url": "https://www.rakuten.com/",
        "signup_promo_amount": 50.00,
        "signup_promo_copy": "Get $50 when you spend $30 within 90 days",
        "signup_promo_ends_at": datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC),
        "is_active": True,
    },
    {
        "portal_source": "topcashback",
        "display_name": "TopCashback",
        "homepage_url": "https://www.topcashback.com/",
        "signup_promo_amount": None,
        "signup_promo_copy": None,
        "signup_promo_ends_at": None,
        "is_active": True,
    },
    {
        "portal_source": "befrugal",
        "display_name": "BeFrugal",
        "homepage_url": "https://www.befrugal.com/",
        "signup_promo_amount": None,
        "signup_promo_copy": None,
        "signup_promo_ends_at": None,
        "is_active": True,
    },
    # Deferred — auth-gated portals not in scope for 3g. Stored inactive
    # so the resolver doesn't render them, but the rows exist for an
    # operator to flip on once the credential plumbing lands.
    {
        "portal_source": "chase_shop",
        "display_name": "Shop through Chase",
        "homepage_url": "https://ultimaterewardspoints.chase.com/",
        "signup_promo_amount": None,
        "signup_promo_copy": None,
        "signup_promo_ends_at": None,
        "is_active": False,
    },
    {
        "portal_source": "capital_one_shopping",
        "display_name": "Capital One Shopping",
        "homepage_url": "https://capitaloneshopping.com/",
        "signup_promo_amount": None,
        "signup_promo_copy": None,
        "signup_promo_ends_at": None,
        "is_active": False,
    },
]


async def seed(session: AsyncSession) -> dict[str, int]:
    counts = {"inserted": 0, "updated": 0}

    for row in SEED_ROWS:
        existing = await session.execute(
            text("SELECT id FROM portal_configs WHERE portal_source = :ps"),
            {"ps": row["portal_source"]},
        )
        action = "updated" if existing.first() is not None else "inserted"

        await session.execute(
            text(
                """
                INSERT INTO portal_configs (
                    portal_source, display_name, homepage_url,
                    signup_promo_amount, signup_promo_copy,
                    signup_promo_ends_at, is_active, updated_at
                ) VALUES (
                    :portal_source, :display_name, :homepage_url,
                    :signup_promo_amount, :signup_promo_copy,
                    :signup_promo_ends_at, :is_active, NOW()
                )
                ON CONFLICT (portal_source) DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    homepage_url = EXCLUDED.homepage_url,
                    signup_promo_amount = EXCLUDED.signup_promo_amount,
                    signup_promo_copy = EXCLUDED.signup_promo_copy,
                    signup_promo_ends_at = EXCLUDED.signup_promo_ends_at,
                    is_active = EXCLUDED.is_active,
                    updated_at = NOW()
                """
            ),
            row,
        )
        counts[action] += 1

    return counts


async def _main() -> None:
    from app.config import settings

    engine = create_async_engine(settings.DATABASE_URL)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async with SessionLocal() as session:
        counts = await seed(session)
        await session.commit()

    await engine.dispose()
    print(
        f"portal_configs seed: inserted={counts['inserted']} "
        f"updated={counts['updated']}"
    )


if __name__ == "__main__":
    asyncio.run(_main())
