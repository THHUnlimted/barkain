"""Seed the card_reward_programs table with 30 Tier 1 US credit cards.

Step 2e: populates the zero-LLM card reward catalog from docs/CARD_REWARDS.md.
Run after alembic upgrade and after seed_retailers.py.

Idempotent via ON CONFLICT upserts on (card_issuer, card_product). The unique
index backing that ON CONFLICT is created by Alembic migration 0004 (Step 2f);
the seed script no longer lazy-creates it.

Usage:
    alembic upgrade head  # ensures migration 0004 is applied
    python3 scripts/seed_card_catalog.py
"""

import asyncio
import json
import os
import sys
from pathlib import Path

# Add backend/ to path so lint tests can import the constants from this module.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


# MARK: - Vocabularies (also exported from backend/modules/m5_identity/card_schemas.py)

CARD_ISSUERS: tuple[str, ...] = (
    "chase",
    "amex",
    "capital_one",
    "citi",
    "discover",
    "bank_of_america",
    "wells_fargo",
    "us_bank",
)

REWARD_CURRENCIES: tuple[str, ...] = (
    "ultimate_rewards",
    "membership_rewards",
    "venture_miles",
    "thank_you_points",
    "cashback",
    "points",
)


# MARK: - Card Catalog (30 Tier 1 cards from docs/CARD_REWARDS.md)
# Category bonus shape: list of dicts, each with:
#   category    (str)         — tag matched at query time
#   rate        (float)       — earn multiplier at that category
#   cap         (int, opt)    — quarterly spend cap in dollars
#   allowed     (list, opt)   — for category="user_selected", the picker list

CARDS: list[dict] = [
    # ── Chase ──
    {
        "card_network": "visa",
        "card_issuer": "chase",
        "card_product": "sapphire_preferred",
        "card_display_name": "Chase Sapphire Preferred",
        "base_reward_rate": 1.0,
        "reward_currency": "ultimate_rewards",
        "point_value_cents": 1.25,
        "category_bonuses": [
            {"category": "dining", "rate": 3.0},
            {"category": "online_grocery", "rate": 3.0},
            {"category": "travel", "rate": 2.0},
            {"category": "streaming", "rate": 3.0},
        ],
        "has_shopping_portal": True,
        "portal_url": "https://ultimaterewardsmall.chase.com",
        "annual_fee": 95,
    },
    {
        "card_network": "visa",
        "card_issuer": "chase",
        "card_product": "sapphire_reserve",
        "card_display_name": "Chase Sapphire Reserve",
        "base_reward_rate": 1.0,
        "reward_currency": "ultimate_rewards",
        "point_value_cents": 2.0,
        "category_bonuses": [
            {"category": "dining", "rate": 3.0},
            {"category": "travel", "rate": 3.0},
        ],
        "has_shopping_portal": True,
        "portal_url": "https://ultimaterewardsmall.chase.com",
        "annual_fee": 550,
    },
    {
        "card_network": "mastercard",
        "card_issuer": "chase",
        "card_product": "freedom_flex",
        "card_display_name": "Chase Freedom Flex",
        "base_reward_rate": 1.0,
        "reward_currency": "ultimate_rewards",
        "point_value_cents": 1.25,
        "category_bonuses": [
            {"category": "dining", "rate": 3.0},
            {"category": "drugstores", "rate": 3.0},
        ],
        "has_shopping_portal": True,
        "portal_url": "https://ultimaterewardsmall.chase.com",
        "annual_fee": 0,
    },
    {
        "card_network": "visa",
        "card_issuer": "chase",
        "card_product": "freedom_unlimited",
        "card_display_name": "Chase Freedom Unlimited",
        "base_reward_rate": 1.5,
        "reward_currency": "ultimate_rewards",
        "point_value_cents": 1.25,
        "category_bonuses": [
            {"category": "dining", "rate": 3.0},
            {"category": "drugstores", "rate": 3.0},
        ],
        "has_shopping_portal": True,
        "portal_url": "https://ultimaterewardsmall.chase.com",
        "annual_fee": 0,
    },
    {
        "card_network": "visa",
        "card_issuer": "chase",
        "card_product": "ink_business_preferred",
        "card_display_name": "Chase Ink Business Preferred",
        "base_reward_rate": 1.0,
        "reward_currency": "ultimate_rewards",
        "point_value_cents": 1.25,
        "category_bonuses": [
            {"category": "travel", "rate": 3.0},
            {"category": "internet_cable_phone", "rate": 3.0},
            {"category": "shipping", "rate": 3.0},
            {"category": "advertising", "rate": 3.0},
        ],
        "has_shopping_portal": True,
        "portal_url": "https://ultimaterewardsmall.chase.com",
        "annual_fee": 95,
    },
    {
        "card_network": "visa",
        "card_issuer": "chase",
        "card_product": "ink_business_cash",
        "card_display_name": "Chase Ink Business Cash",
        "base_reward_rate": 1.0,
        "reward_currency": "ultimate_rewards",
        "point_value_cents": 1.25,
        "category_bonuses": [
            {"category": "office_supplies", "rate": 5.0},
            {"category": "internet_cable_phone", "rate": 5.0},
            {"category": "gas", "rate": 2.0},
            {"category": "restaurants", "rate": 2.0},
        ],
        "has_shopping_portal": True,
        "portal_url": "https://ultimaterewardsmall.chase.com",
        "annual_fee": 0,
    },
    {
        "card_network": "visa",
        "card_issuer": "chase",
        "card_product": "ink_business_unlimited",
        "card_display_name": "Chase Ink Business Unlimited",
        "base_reward_rate": 1.5,
        "reward_currency": "ultimate_rewards",
        "point_value_cents": 1.25,
        "category_bonuses": [],
        "has_shopping_portal": True,
        "portal_url": "https://ultimaterewardsmall.chase.com",
        "annual_fee": 0,
    },
    # ── American Express ──
    {
        "card_network": "amex",
        "card_issuer": "amex",
        "card_product": "gold_card",
        "card_display_name": "Amex Gold",
        "base_reward_rate": 1.0,
        "reward_currency": "membership_rewards",
        "point_value_cents": 1.0,
        "category_bonuses": [
            {"category": "restaurants", "rate": 4.0},
            {"category": "supermarkets", "rate": 4.0},
            {"category": "airlines", "rate": 3.0},
        ],
        "has_shopping_portal": False,
        "portal_url": None,
        "annual_fee": 250,
    },
    {
        "card_network": "amex",
        "card_issuer": "amex",
        "card_product": "platinum",
        "card_display_name": "Amex Platinum",
        "base_reward_rate": 1.0,
        "reward_currency": "membership_rewards",
        "point_value_cents": 1.0,
        "category_bonuses": [
            {"category": "flights", "rate": 5.0},
            {"category": "hotels", "rate": 5.0},
        ],
        "has_shopping_portal": False,
        "portal_url": None,
        "annual_fee": 695,
    },
    {
        "card_network": "amex",
        "card_issuer": "amex",
        "card_product": "blue_cash_preferred",
        "card_display_name": "Amex Blue Cash Preferred",
        "base_reward_rate": 1.0,
        "reward_currency": "cashback",
        "point_value_cents": 1.0,
        "category_bonuses": [
            {"category": "supermarkets", "rate": 6.0, "cap": 6000},
            {"category": "streaming", "rate": 6.0},
            {"category": "gas", "rate": 3.0},
            {"category": "transit", "rate": 3.0},
        ],
        "has_shopping_portal": False,
        "portal_url": None,
        "annual_fee": 95,
    },
    {
        "card_network": "amex",
        "card_issuer": "amex",
        "card_product": "blue_cash_everyday",
        "card_display_name": "Amex Blue Cash Everyday",
        "base_reward_rate": 1.0,
        "reward_currency": "cashback",
        "point_value_cents": 1.0,
        "category_bonuses": [
            {"category": "supermarkets", "rate": 3.0, "cap": 6000},
            {"category": "gas", "rate": 3.0},
            {"category": "online_shopping", "rate": 3.0},
        ],
        "has_shopping_portal": False,
        "portal_url": None,
        "annual_fee": 0,
    },
    {
        "card_network": "amex",
        "card_issuer": "amex",
        "card_product": "green",
        "card_display_name": "Amex Green",
        "base_reward_rate": 1.0,
        "reward_currency": "membership_rewards",
        "point_value_cents": 1.0,
        "category_bonuses": [
            {"category": "restaurants", "rate": 3.0},
            {"category": "travel", "rate": 3.0},
            {"category": "transit", "rate": 3.0},
        ],
        "has_shopping_portal": False,
        "portal_url": None,
        "annual_fee": 150,
    },
    # ── Capital One ──
    {
        "card_network": "visa",
        "card_issuer": "capital_one",
        "card_product": "venture_x",
        "card_display_name": "Capital One Venture X",
        "base_reward_rate": 2.0,
        "reward_currency": "venture_miles",
        "point_value_cents": 1.0,
        "category_bonuses": [
            {"category": "travel", "rate": 5.0},
            {"category": "hotels", "rate": 10.0},
        ],
        "has_shopping_portal": True,
        "portal_url": "https://capitaloneshopping.com",
        "annual_fee": 395,
    },
    {
        "card_network": "visa",
        "card_issuer": "capital_one",
        "card_product": "venture",
        "card_display_name": "Capital One Venture",
        "base_reward_rate": 2.0,
        "reward_currency": "venture_miles",
        "point_value_cents": 1.0,
        "category_bonuses": [
            {"category": "hotels", "rate": 5.0},
        ],
        "has_shopping_portal": True,
        "portal_url": "https://capitaloneshopping.com",
        "annual_fee": 95,
    },
    {
        "card_network": "mastercard",
        "card_issuer": "capital_one",
        "card_product": "savor_one",
        "card_display_name": "Capital One SavorOne",
        "base_reward_rate": 1.0,
        "reward_currency": "cashback",
        "point_value_cents": 1.0,
        "category_bonuses": [
            {"category": "dining", "rate": 3.0},
            {"category": "entertainment", "rate": 3.0},
            {"category": "streaming", "rate": 3.0},
            {"category": "supermarkets", "rate": 3.0},
        ],
        "has_shopping_portal": True,
        "portal_url": "https://capitaloneshopping.com",
        "annual_fee": 0,
    },
    {
        "card_network": "mastercard",
        "card_issuer": "capital_one",
        "card_product": "quicksilver",
        "card_display_name": "Capital One Quicksilver",
        "base_reward_rate": 1.5,
        "reward_currency": "cashback",
        "point_value_cents": 1.0,
        "category_bonuses": [],
        "has_shopping_portal": True,
        "portal_url": "https://capitaloneshopping.com",
        "annual_fee": 0,
    },
    # ── Citi ──
    {
        "card_network": "mastercard",
        "card_issuer": "citi",
        "card_product": "double_cash",
        "card_display_name": "Citi Double Cash",
        "base_reward_rate": 2.0,
        "reward_currency": "cashback",
        "point_value_cents": 1.0,
        "category_bonuses": [],
        "has_shopping_portal": False,
        "portal_url": None,
        "annual_fee": 0,
    },
    {
        "card_network": "mastercard",
        "card_issuer": "citi",
        "card_product": "custom_cash",
        "card_display_name": "Citi Custom Cash",
        "base_reward_rate": 1.0,
        "reward_currency": "cashback",
        "point_value_cents": 1.0,
        "category_bonuses": [
            {"category": "top_spend", "rate": 5.0, "cap": 500},
        ],
        "has_shopping_portal": False,
        "portal_url": None,
        "annual_fee": 0,
    },
    {
        "card_network": "mastercard",
        "card_issuer": "citi",
        "card_product": "premier",
        "card_display_name": "Citi Premier",
        "base_reward_rate": 1.0,
        "reward_currency": "thank_you_points",
        "point_value_cents": 1.0,
        "category_bonuses": [
            {"category": "travel", "rate": 3.0},
            {"category": "dining", "rate": 3.0},
            {"category": "supermarkets", "rate": 3.0},
            {"category": "gas", "rate": 3.0},
        ],
        "has_shopping_portal": False,
        "portal_url": None,
        "annual_fee": 95,
    },
    {
        "card_network": "mastercard",
        "card_issuer": "citi",
        "card_product": "strata_premier",
        "card_display_name": "Citi Strata Premier",
        "base_reward_rate": 1.0,
        "reward_currency": "thank_you_points",
        "point_value_cents": 1.0,
        "category_bonuses": [
            {"category": "travel", "rate": 10.0},
            {"category": "hotels", "rate": 10.0},
            {"category": "gas", "rate": 3.0},
            {"category": "supermarkets", "rate": 3.0},
            {"category": "dining", "rate": 3.0},
        ],
        "has_shopping_portal": False,
        "portal_url": None,
        "annual_fee": 95,
    },
    # ── Discover ──
    {
        "card_network": "discover",
        "card_issuer": "discover",
        "card_product": "it_cash_back",
        "card_display_name": "Discover it Cash Back",
        "base_reward_rate": 1.0,
        "reward_currency": "cashback",
        "point_value_cents": 1.0,
        "category_bonuses": [],
        "has_shopping_portal": True,
        "portal_url": "https://shopdiscover.com",
        "annual_fee": 0,
    },
    {
        "card_network": "discover",
        "card_issuer": "discover",
        "card_product": "it_miles",
        "card_display_name": "Discover it Miles",
        "base_reward_rate": 1.5,
        "reward_currency": "cashback",
        "point_value_cents": 1.0,
        "category_bonuses": [],
        "has_shopping_portal": False,
        "portal_url": None,
        "annual_fee": 0,
    },
    # ── Bank of America ──
    {
        "card_network": "visa",
        "card_issuer": "bank_of_america",
        "card_product": "customized_cash",
        "card_display_name": "BofA Customized Cash Rewards",
        "base_reward_rate": 1.0,
        "reward_currency": "cashback",
        "point_value_cents": 1.0,
        "category_bonuses": [
            {
                "category": "user_selected",
                "rate": 3.0,
                "cap": 2500,
                "allowed": [
                    "gas",
                    "online_shopping",
                    "dining",
                    "travel",
                    "drugstores",
                    "home_improvement",
                ],
            },
            {"category": "grocery_stores", "rate": 2.0, "cap": 2500},
        ],
        "has_shopping_portal": False,
        "portal_url": None,
        "annual_fee": 0,
    },
    {
        "card_network": "visa",
        "card_issuer": "bank_of_america",
        "card_product": "premium_rewards",
        "card_display_name": "BofA Premium Rewards",
        "base_reward_rate": 1.5,
        "reward_currency": "cashback",
        "point_value_cents": 1.0,
        "category_bonuses": [
            {"category": "travel", "rate": 2.0},
            {"category": "dining", "rate": 2.0},
        ],
        "has_shopping_portal": False,
        "portal_url": None,
        "annual_fee": 95,
    },
    {
        "card_network": "visa",
        "card_issuer": "bank_of_america",
        "card_product": "unlimited_cash_rewards",
        "card_display_name": "BofA Unlimited Cash Rewards",
        "base_reward_rate": 1.5,
        "reward_currency": "cashback",
        "point_value_cents": 1.0,
        "category_bonuses": [],
        "has_shopping_portal": False,
        "portal_url": None,
        "annual_fee": 0,
    },
    # ── Wells Fargo ──
    {
        "card_network": "visa",
        "card_issuer": "wells_fargo",
        "card_product": "autograph",
        "card_display_name": "Wells Fargo Autograph",
        "base_reward_rate": 1.0,
        "reward_currency": "points",
        "point_value_cents": 1.0,
        "category_bonuses": [
            {"category": "restaurants", "rate": 3.0},
            {"category": "travel", "rate": 3.0},
            {"category": "gas", "rate": 3.0},
            {"category": "transit", "rate": 3.0},
            {"category": "streaming", "rate": 3.0},
            {"category": "phone", "rate": 3.0},
        ],
        "has_shopping_portal": False,
        "portal_url": None,
        "annual_fee": 0,
    },
    {
        "card_network": "visa",
        "card_issuer": "wells_fargo",
        "card_product": "active_cash",
        "card_display_name": "Wells Fargo Active Cash",
        "base_reward_rate": 2.0,
        "reward_currency": "cashback",
        "point_value_cents": 1.0,
        "category_bonuses": [],
        "has_shopping_portal": False,
        "portal_url": None,
        "annual_fee": 0,
    },
    # ── US Bank ──
    {
        "card_network": "visa",
        "card_issuer": "us_bank",
        "card_product": "altitude_go",
        "card_display_name": "US Bank Altitude Go",
        "base_reward_rate": 1.0,
        "reward_currency": "cashback",
        "point_value_cents": 1.0,
        "category_bonuses": [
            {"category": "dining", "rate": 4.0},
            {"category": "streaming", "rate": 2.0},
            {"category": "supermarkets", "rate": 2.0},
            {"category": "gas", "rate": 2.0},
        ],
        "has_shopping_portal": False,
        "portal_url": None,
        "annual_fee": 0,
    },
    {
        "card_network": "visa",
        "card_issuer": "us_bank",
        "card_product": "cash_plus",
        "card_display_name": "US Bank Cash+",
        "base_reward_rate": 1.0,
        "reward_currency": "cashback",
        "point_value_cents": 1.0,
        "category_bonuses": [
            {
                "category": "user_selected",
                "rate": 5.0,
                "cap": 2000,
                "allowed": [
                    "fast_food",
                    "cell_phone",
                    "electronics_stores",
                    "home_utilities",
                    "gym",
                    "furniture_stores",
                    "department_stores",
                    "movie_theaters",
                    "tv_internet_streaming",
                    "select_clothing",
                    "restaurants",
                    "sporting_goods",
                ],
            },
        ],
        "has_shopping_portal": False,
        "portal_url": None,
        "annual_fee": 0,
    },
    {
        "card_network": "visa",
        "card_issuer": "us_bank",
        "card_product": "shopper_cash_rewards",
        "card_display_name": "US Bank Shopper Cash Rewards",
        "base_reward_rate": 1.5,
        "reward_currency": "cashback",
        "point_value_cents": 1.0,
        "category_bonuses": [
            {
                "category": "user_selected",
                "rate": 6.0,
                "cap": 1500,
                "allowed": [
                    "amazon",
                    "apple",
                    "best_buy",
                    "home_depot",
                    "lowes",
                    "target",
                    "walmart",
                ],
            },
        ],
        "has_shopping_portal": False,
        "portal_url": None,
        "annual_fee": 95,
    },
]


# MARK: - Seeding
#
# Note: the ON CONFLICT (card_issuer, card_product) clause below relies on the
# `idx_card_reward_programs_product` unique index created by Alembic migration
# 0004 (Step 2f). Run `alembic upgrade head` before seeding on a fresh DB.


async def seed_cards(session: AsyncSession) -> int:
    count = 0
    for card in CARDS:
        params = {**card, "category_bonuses": json.dumps(card["category_bonuses"])}
        await session.execute(
            text(
                """
                INSERT INTO card_reward_programs (
                    card_network, card_issuer, card_product, card_display_name,
                    base_reward_rate, reward_currency, point_value_cents,
                    category_bonuses, has_shopping_portal, portal_url, annual_fee,
                    is_active
                )
                VALUES (
                    :card_network, :card_issuer, :card_product, :card_display_name,
                    :base_reward_rate, :reward_currency, :point_value_cents,
                    CAST(:category_bonuses AS JSONB), :has_shopping_portal,
                    :portal_url, :annual_fee, TRUE
                )
                ON CONFLICT (card_issuer, card_product) DO UPDATE SET
                    card_network = EXCLUDED.card_network,
                    card_display_name = EXCLUDED.card_display_name,
                    base_reward_rate = EXCLUDED.base_reward_rate,
                    reward_currency = EXCLUDED.reward_currency,
                    point_value_cents = EXCLUDED.point_value_cents,
                    category_bonuses = EXCLUDED.category_bonuses,
                    has_shopping_portal = EXCLUDED.has_shopping_portal,
                    portal_url = EXCLUDED.portal_url,
                    annual_fee = EXCLUDED.annual_fee,
                    is_active = TRUE,
                    updated_at = NOW()
                """
            ),
            params,
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
        seeded = await seed_cards(session)
        await session.commit()
        print(f"Seeded {seeded} card reward programs.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
