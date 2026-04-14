"""Seed the retailers table with the 11 Phase 1 retailers."""

import asyncio
import os
import sys
from pathlib import Path

# Add backend/ to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

RETAILERS = [
    {
        "id": "amazon",
        "display_name": "Amazon",
        "base_url": "https://www.amazon.com",
        "extraction_method": "agent_browser",
        "supports_coupons": True,
        "supports_identity": True,
        "supports_portals": True,
    },
    {
        "id": "best_buy",
        "display_name": "Best Buy",
        "base_url": "https://www.bestbuy.com",
        "extraction_method": "agent_browser",
        "supports_coupons": True,
        "supports_identity": False,
        "supports_portals": True,
    },
    {
        "id": "walmart",
        "display_name": "Walmart",
        "base_url": "https://www.walmart.com",
        "extraction_method": "agent_browser",
        "supports_coupons": True,
        "supports_identity": False,
        "supports_portals": True,
    },
    {
        "id": "target",
        "display_name": "Target",
        "base_url": "https://www.target.com",
        "extraction_method": "agent_browser",
        "supports_coupons": True,
        "supports_identity": False,
        "supports_portals": True,
    },
    {
        "id": "home_depot",
        "display_name": "Home Depot",
        "base_url": "https://www.homedepot.com",
        "extraction_method": "agent_browser",
        "supports_coupons": True,
        "supports_identity": True,
        "supports_portals": True,
    },
    {
        "id": "lowes",
        "display_name": "Lowe's",
        "base_url": "https://www.lowes.com",
        "extraction_method": "agent_browser",
        "supports_coupons": True,
        "supports_identity": True,
        "supports_portals": True,
    },
    {
        "id": "ebay_new",
        "display_name": "eBay (New)",
        "base_url": "https://www.ebay.com",
        "extraction_method": "agent_browser",
        "supports_coupons": True,
        "supports_identity": False,
        "supports_portals": True,
    },
    {
        "id": "ebay_used",
        "display_name": "eBay (Used/Refurb)",
        "base_url": "https://www.ebay.com",
        "extraction_method": "agent_browser",
        "supports_coupons": False,
        "supports_identity": False,
        "supports_portals": True,
    },
    {
        "id": "sams_club",
        "display_name": "Sam's Club",
        "base_url": "https://www.samsclub.com",
        "extraction_method": "agent_browser",
        "supports_coupons": True,
        "supports_identity": False,
        "supports_portals": True,
    },
    {
        "id": "backmarket",
        "display_name": "Back Market",
        "base_url": "https://www.backmarket.com",
        "extraction_method": "agent_browser",
        "supports_coupons": True,
        "supports_identity": False,
        "supports_portals": True,
    },
    {
        "id": "fb_marketplace",
        "display_name": "Facebook Marketplace",
        "base_url": "https://www.facebook.com/marketplace",
        "extraction_method": "agent_browser",
        "supports_coupons": False,
        "supports_identity": False,
        "supports_portals": False,
    },
]


async def seed_retailers(session: AsyncSession) -> int:
    """Insert or update all Phase 1 retailers. Returns count of upserted rows."""
    count = 0
    for r in RETAILERS:
        await session.execute(
            text(
                """
                INSERT INTO retailers (id, display_name, base_url, extraction_method,
                    supports_coupons, supports_identity, supports_portals)
                VALUES (:id, :display_name, :base_url, :extraction_method,
                    :supports_coupons, :supports_identity, :supports_portals)
                ON CONFLICT (id) DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    base_url = EXCLUDED.base_url,
                    extraction_method = EXCLUDED.extraction_method,
                    supports_coupons = EXCLUDED.supports_coupons,
                    supports_identity = EXCLUDED.supports_identity,
                    supports_portals = EXCLUDED.supports_portals,
                    updated_at = NOW()
                """
            ),
            r,
        )
        count += 1
    return count


async def main() -> None:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")

    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://app:localdev@localhost:5432/barkain",
    )
    engine = create_async_engine(database_url)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    async with async_session() as session:
        count = await seed_retailers(session)
        await session.commit()
        print(f"Seeded {count} retailers.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
