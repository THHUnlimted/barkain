"""Seed the discount_programs table + 8 brand-direct retailer entries.

Step 2d: populates the zero-LLM identity discount catalog from
docs/IDENTITY_DISCOUNTS.md. Run after alembic upgrade and after
seed_retailers.py (which creates the 11 Phase 1 retailers).

Idempotent via ON CONFLICT upserts. Safe to re-run whenever the catalog
shifts (e.g., after refreshing from the weekly verification-platform
scrape).

Usage:
    python3 scripts/seed_discount_catalog.py
"""

import asyncio
import os
import sys
from pathlib import Path

# Add backend/ to path so we can import schemas.ELIGIBILITY_TYPES.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


# MARK: - Brand-direct retailers
# These are redirect-only retailers — Barkain does not scrape them. Users tap
# an identity discount card and are sent to the brand's verification page.

BRAND_RETAILERS: list[dict] = [
    {
        "id": "samsung_direct",
        "display_name": "Samsung.com",
        "base_url": "https://www.samsung.com/us/shop",
        "extraction_method": "none",
        "supports_coupons": False,
        "supports_identity": True,
        "supports_portals": False,
    },
    {
        "id": "apple_direct",
        "display_name": "Apple.com",
        "base_url": "https://www.apple.com/shop",
        "extraction_method": "none",
        "supports_coupons": False,
        "supports_identity": True,
        "supports_portals": False,
    },
    {
        "id": "hp_direct",
        "display_name": "HP.com",
        "base_url": "https://www.hp.com/us-en/shop",
        "extraction_method": "none",
        "supports_coupons": False,
        "supports_identity": True,
        "supports_portals": False,
    },
    {
        "id": "dell_direct",
        "display_name": "Dell.com",
        "base_url": "https://www.dell.com",
        "extraction_method": "none",
        "supports_coupons": False,
        "supports_identity": True,
        "supports_portals": False,
    },
    {
        "id": "lenovo_direct",
        "display_name": "Lenovo.com",
        "base_url": "https://www.lenovo.com",
        "extraction_method": "none",
        "supports_coupons": False,
        "supports_identity": True,
        "supports_portals": False,
    },
    {
        "id": "microsoft_direct",
        "display_name": "Microsoft.com",
        "base_url": "https://www.microsoft.com/en-us/store",
        "extraction_method": "none",
        "supports_coupons": False,
        "supports_identity": True,
        "supports_portals": False,
    },
    {
        "id": "sony_direct",
        "display_name": "Sony.com",
        "base_url": "https://www.sony.com/en",
        "extraction_method": "none",
        "supports_coupons": False,
        "supports_identity": True,
        "supports_portals": False,
    },
    {
        "id": "lg_direct",
        "display_name": "LG.com",
        "base_url": "https://www.lg.com/us",
        "extraction_method": "none",
        "supports_coupons": False,
        "supports_identity": True,
        "supports_portals": False,
    },
]


# MARK: - Discount programs
# Each row is one (retailer_id, program_name, eligibility_type) combination.
# Programs that cover multiple eligibility types are expanded to N rows below.
# The service deduplicates by (retailer_id, program_name) when surfacing
# results, so users see ONE card per program regardless of row count.

# Program template: (retailer_id, program_name, program_type, eligibility_types,
#                    discount_type, discount_value, discount_max_value,
#                    verification_method, verification_url, url, notes)
_PROGRAM_TEMPLATES: list[dict] = [
    # Apple
    {
        "retailer_id": "apple_direct",
        "program_name": "Military & Veterans Discount",
        "program_type": "identity",
        "eligibility_types": ["military", "veteran", "first_responder"],
        "discount_type": "percentage",
        "discount_value": 10,
        "discount_max_value": None,
        "verification_method": "id_me",
        "verification_url": "https://www.apple.com/shop/browse/home/veterans_military",
        "url": "https://www.apple.com/shop/browse/home/veterans_military",
        "discount_details": "10% off select products. Household family eligible. Cannot combine with education pricing.",
    },
    {
        "retailer_id": "apple_direct",
        "program_name": "Education Pricing",
        "program_type": "identity",
        "eligibility_types": ["student", "teacher"],
        "discount_type": "percentage",
        "discount_value": 5,
        "discount_max_value": 10,
        "verification_method": "unidays",
        "verification_url": "https://www.apple.com/us-hed/shop",
        "url": "https://www.apple.com/us-hed/shop",
        "discount_details": "Education Store pricing (5-10% depending on product). Back-to-school promo adds gift card.",
    },
    # Samsung
    {
        "retailer_id": "samsung_direct",
        "program_name": "Samsung Offer Program",
        "program_type": "identity",
        "eligibility_types": [
            "military",
            "veteran",
            "first_responder",
            "student",
            "teacher",
            "nurse",
            "healthcare_worker",
            "government",
        ],
        "discount_type": "percentage",
        "discount_value": 30,
        "discount_max_value": None,
        "verification_method": "id_me",
        "verification_url": "https://www.samsung.com/us/shop/offer-program/military",
        "url": "https://www.samsung.com/us/shop/offer-program/military",
        "discount_details": "Up to 30% off. 2 products per category per calendar year.",
    },
    # HP
    {
        "retailer_id": "hp_direct",
        "program_name": "Frontline Heroes Program",
        "program_type": "identity",
        "eligibility_types": [
            "military",
            "veteran",
            "first_responder",
            "nurse",
            "healthcare_worker",
        ],
        "discount_type": "percentage",
        "discount_value": 40,
        "discount_max_value": 55,
        "verification_method": "id_me",
        "verification_url": "https://www.hp.com/us-en/shop/cv/hp-frontline-heroes",
        "url": "https://www.hp.com/us-en/shop/cv/hp-frontline-heroes",
        "discount_details": "Up to 40% military/first responders, up to 55% healthcare workers. Free shipping.",
    },
    {
        "retailer_id": "hp_direct",
        "program_name": "Education Store",
        "program_type": "identity",
        "eligibility_types": ["student", "teacher"],
        "discount_type": "percentage",
        "discount_value": 40,
        "discount_max_value": None,
        "verification_method": "id_me",
        "verification_url": "https://www.hp.com/us-en/shop/cv/hp-education",
        "url": "https://www.hp.com/us-en/shop/cv/hp-education",
        "discount_details": "Education pricing (product-specific, up to ~40%).",
    },
    # Dell
    {
        "retailer_id": "dell_direct",
        "program_name": "Military Store",
        "program_type": "identity",
        "eligibility_types": ["military", "veteran"],
        "discount_type": "percentage",
        "discount_value": 5,
        "discount_max_value": None,
        "verification_method": "wesalute",
        "verification_url": "https://www.dell.com/military",
        "url": "https://www.dell.com/military",
        "discount_details": "Extra 5% off. Requires WeSalute+ membership.",
    },
    {
        "retailer_id": "dell_direct",
        "program_name": "Member Purchase Program",
        "program_type": "identity",
        "eligibility_types": ["government"],
        "discount_type": "percentage",
        "discount_value": 30,
        "discount_max_value": None,
        "verification_method": "id_me",
        "verification_url": "https://www.dell.com/mpp",
        "url": "https://www.dell.com/mpp",
        "discount_details": "Up to 30% on select products. Employer email required.",
    },
    {
        "retailer_id": "dell_direct",
        "program_name": "University Store",
        "program_type": "identity",
        "eligibility_types": ["student"],
        "discount_type": "percentage",
        "discount_value": 10,
        "discount_max_value": None,
        "verification_method": "id_me",
        "verification_url": "https://www.dell.com/en-us/lp/student",
        "url": "https://www.dell.com/en-us/lp/student",
        "discount_details": "Dell University pricing. Varies by product.",
    },
    # Lenovo
    {
        "retailer_id": "lenovo_direct",
        "program_name": "Military Discount",
        "program_type": "identity",
        "eligibility_types": ["military", "veteran", "first_responder"],
        "discount_type": "percentage",
        "discount_value": 5,
        "discount_max_value": None,
        "verification_method": "id_me",
        "verification_url": "https://www.lenovo.com/us/en/d/deals/military/",
        "url": "https://www.lenovo.com/us/en/d/deals/discount-programs/",
        "discount_details": "Extra 5% off sitewide. First responders additionally eligible.",
    },
    {
        "retailer_id": "lenovo_direct",
        "program_name": "Education Store",
        "program_type": "identity",
        "eligibility_types": ["student", "teacher"],
        "discount_type": "percentage",
        "discount_value": 5,
        "discount_max_value": None,
        "verification_method": "id_me",
        "verification_url": "https://www.lenovo.com/us/en/d/deals/student/",
        "url": "https://www.lenovo.com/us/en/d/deals/student/",
        "discount_details": "Education pricing. Varies by product.",
    },
    # Microsoft
    {
        "retailer_id": "microsoft_direct",
        "program_name": "Military Store",
        "program_type": "identity",
        "eligibility_types": ["military", "veteran"],
        "discount_type": "percentage",
        "discount_value": 10,
        "discount_max_value": None,
        "verification_method": "id_me",
        "verification_url": "https://www.microsoft.com/en-us/store/b/military",
        "url": "https://www.microsoft.com/en-us/store/b/military",
        "discount_details": "10% off select products. Cannot combine with education or seasonal discounts.",
    },
    {
        "retailer_id": "microsoft_direct",
        "program_name": "Education Store",
        "program_type": "identity",
        "eligibility_types": ["student", "teacher"],
        "discount_type": "percentage",
        "discount_value": 10,
        "discount_max_value": None,
        "verification_method": "sheer_id",
        "verification_url": "https://www.microsoft.com/en-us/store/b/education",
        "url": "https://www.microsoft.com/en-us/store/b/education",
        "discount_details": "10% off select products (K-12 + Higher Ed). Cannot combine with military discount.",
    },
    # Sony
    {
        "retailer_id": "sony_direct",
        "program_name": "Identity Discount Program",
        "program_type": "identity",
        "eligibility_types": [
            "military",
            "student",
            "teacher",
            "first_responder",
            "nurse",
            "healthcare_worker",
        ],
        "discount_type": "percentage",
        "discount_value": 10,
        "discount_max_value": None,
        "verification_method": "id_me",
        "verification_url": "https://electronics.sony.com",
        "url": "https://electronics.sony.com",
        "discount_details": "10% off electronics (TVs, headphones, cameras, consoles). Applied at checkout after ID.me verification.",
    },
    # LG
    {
        "retailer_id": "lg_direct",
        "program_name": "Appreciation Program",
        "program_type": "identity",
        "eligibility_types": [
            "military",
            "veteran",
            "first_responder",
            "student",
            "teacher",
            "nurse",
            "healthcare_worker",
            "government",
        ],
        "discount_type": "percentage",
        "discount_value": 10,
        "discount_max_value": 46,
        "verification_method": "id_me",
        "verification_url": "https://www.lg.com/us/appreciation-program",
        "url": "https://www.lg.com/us/appreciation-program",
        "discount_details": "Minimum 10% additional savings on appliances; up to 40-46% on select items.",
    },
    # Home Depot
    {
        "retailer_id": "home_depot",
        "program_name": "Military Discount",
        "program_type": "identity",
        "eligibility_types": ["military", "veteran"],
        "discount_type": "percentage",
        "discount_value": 10,
        "discount_max_value": 400,
        "verification_method": "sheer_id",
        "verification_url": "https://www.homedepot.com/c/military_discount_registration",
        "url": "https://www.homedepot.com/c/military",
        "discount_details": "$400 annual cap. Must register digitally. Spouses included. Expanded May 2025 to include tax-free shopping on 2M+ products.",
    },
    # Lowe's
    {
        "retailer_id": "lowes",
        "program_name": "Honor Our Military",
        "program_type": "identity",
        "eligibility_types": ["military", "veteran"],
        "discount_type": "percentage",
        "discount_value": 10,
        "discount_max_value": 400,
        "verification_method": "id_me",
        "verification_url": "https://www.lowes.com/mylowes/mymilitarydiscount",
        "url": "https://www.lowes.com/l/about/honor-our-military",
        "discount_details": "$400 annual cap. Most full-price products. Cannot combine with sale pricing or Lowe's credit 5% discount. In-store only since 2024.",
    },
    # Amazon
    {
        "retailer_id": "amazon",
        "program_name": "Prime Student",
        "program_type": "membership",
        "eligibility_types": ["student"],
        "discount_type": "percentage",
        "discount_value": 50,
        "discount_max_value": None,
        "verification_method": "unidays",
        "verification_url": "https://www.amazon.com/primestudent",
        "url": "https://www.amazon.com/primestudent",
        "discount_details": "50% off Prime ($7.49/mo after 6-mo free trial). Requires .edu email. Includes GrubHub+, other perks.",
    },
]


def _expand_programs() -> list[dict]:
    """Split each multi-eligibility program into one row per eligibility_type."""
    rows: list[dict] = []
    for template in _PROGRAM_TEMPLATES:
        eligibility_types = template["eligibility_types"]
        for etype in eligibility_types:
            row = {
                "retailer_id": template["retailer_id"],
                "program_name": template["program_name"],
                "program_type": template["program_type"],
                "eligibility_type": etype,
                "discount_type": template["discount_type"],
                "discount_value": template["discount_value"],
                "discount_max_value": template["discount_max_value"],
                "verification_method": template["verification_method"],
                "verification_url": template["verification_url"],
                "url": template["url"],
                "discount_details": template["discount_details"],
                "is_active": True,
            }
            rows.append(row)
    return rows


DISCOUNT_PROGRAMS: list[dict] = _expand_programs()


# MARK: - Seed functions


async def seed_brand_retailers(session: AsyncSession) -> int:
    """UPSERT the 8 brand-direct retailer entries. Returns row count."""
    count = 0
    for r in BRAND_RETAILERS:
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


async def seed_discount_programs(session: AsyncSession) -> int:
    """UPSERT discount programs. Dedup key: (retailer_id, program_name, eligibility_type)."""
    count = 0
    for p in DISCOUNT_PROGRAMS:
        await session.execute(
            text(
                """
                INSERT INTO discount_programs (
                    retailer_id, program_name, program_type, eligibility_type,
                    discount_type, discount_value, discount_max_value,
                    discount_details, verification_method, verification_url,
                    url, is_active
                )
                VALUES (
                    :retailer_id, :program_name, :program_type, :eligibility_type,
                    :discount_type, :discount_value, :discount_max_value,
                    :discount_details, :verification_method, :verification_url,
                    :url, :is_active
                )
                ON CONFLICT (retailer_id, program_name, eligibility_type) DO UPDATE SET
                    program_type = EXCLUDED.program_type,
                    discount_type = EXCLUDED.discount_type,
                    discount_value = EXCLUDED.discount_value,
                    discount_max_value = EXCLUDED.discount_max_value,
                    discount_details = EXCLUDED.discount_details,
                    verification_method = EXCLUDED.verification_method,
                    verification_url = EXCLUDED.verification_url,
                    url = EXCLUDED.url,
                    is_active = EXCLUDED.is_active,
                    updated_at = NOW()
                """
            ),
            p,
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
        retailers = await seed_brand_retailers(session)
        programs = await seed_discount_programs(session)
        await session.commit()
        print(
            f"Seeded {retailers} brand-direct retailers and {programs} discount programs."
        )

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
