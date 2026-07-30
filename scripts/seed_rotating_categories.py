"""Seed the rotating_categories table with issuer-defined quarterly bonuses.

Step 2e: populates rotating 5%/5x categories for cards whose issuers publish
fixed quarterly lists (Chase Freedom Flex, Discover it Cash Back). Cards with
user-picked categories (US Bank Cash+, BofA Customized Cash) are NOT seeded
here — their rates live in card_reward_programs.category_bonuses under
`user_selected` and are activated per-user via the user_category_selections
table.

Runs AFTER seed_card_catalog.py — it looks up card_reward_programs by
(card_issuer, card_product) to resolve the FK.

⚠️  THIS DATA EXPIRES. `CardService._recommendations` filters on
`effective_from <= date.today() <= effective_until`, so a quarter that rolls
over without a reseed means every rotating bonus silently returns the card's
base rate — no error, no log line, just a worse card winning. That is exactly
what happened between 2026-07-01 and 2026-07-30. Run
`python3 scripts/check_catalog_freshness.py` to detect it; that script exits
non-zero once the newest seeded quarter is inside its final 14 days.

Usage:
    python3 scripts/seed_rotating_categories.py
"""

import asyncio
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


# MARK: - Rotating Categories
#
# Source: docs/CARD_REWARDS.md § "Rotating Categories"
# Only cards with issuer-defined rotating lists are seeded. Cash+ / Customized
# Cash / Custom Cash remain user-picked and are resolved through
# user_category_selections at query time.
#
# Category slugs are matched against `_RETAILER_CATEGORY_TAGS` in
# modules/m5_identity/card_service.py. A slug with no counterpart there is
# inert-but-honest: it records what the issuer actually published, and simply
# never wins a recommendation. Several Q3 2026 categories (gas, transit,
# flights) are inert for exactly this reason — Barkain does not shop those
# verticals. Do NOT "fix" that by omitting them; the row's presence is what
# keeps the freshness checker green and proves the quarter was reviewed.
#
# Older quarters are retained rather than deleted. They are correctly filtered
# out at query time, and keeping them makes a fresh-DB reseed reproduce
# history. ON CONFLICT keys on (card_program_id, quarter), so quarters coexist.

ROTATING_CATEGORIES: list[dict] = [
    # ── 2026-Q2 (historical — expired 2026-06-30) ──────────────────────
    {
        "card_issuer": "chase",
        "card_product": "freedom_flex",
        "quarter": "2026-Q2",
        "categories": ["amazon", "chase_travel", "feeding_america"],
        "bonus_rate": 5.0,
        "activation_required": True,
        "activation_url": "https://www.chase.com/personal/credit-cards/freedom-flex",
        "cap_amount": 1500,
        "effective_from": date(2026, 4, 1),
        "effective_until": date(2026, 6, 30),
    },
    {
        "card_issuer": "discover",
        "card_product": "it_cash_back",
        "quarter": "2026-Q2",
        "categories": ["restaurants", "home_depot", "lowes", "home_improvement"],
        "bonus_rate": 5.0,
        "activation_required": True,
        "activation_url": "https://www.discover.com/credit-cards/cash-back/cashback-bonus.html",
        "cap_amount": 1500,
        "effective_from": date(2026, 4, 1),
        "effective_until": date(2026, 6, 30),
    },
    # ── 2026-Q3 (current) ──────────────────────────────────────────────
    # Chase: gas stations + EV charging, public transit, select live
    # entertainment, United Way donations. Registration open through
    # 2026-09-14. Source: media.chase.com/news/chase-freedom-2026-q3-categories
    #
    # NOTE: none of these slugs map to a Barkain retailer tag, so Freedom Flex
    # correctly falls to its base rate at every retailer we compare this
    # quarter. That is the right answer, not a gap.
    {
        "card_issuer": "chase",
        "card_product": "freedom_flex",
        "quarter": "2026-Q3",
        "categories": [
            "gas_stations",
            "ev_charging",
            "public_transit",
            "live_entertainment",
            "united_way",
        ],
        "bonus_rate": 5.0,
        "activation_required": True,
        "activation_url": "https://www.chase.com/personal/credit-cards/freedom-flex",
        "cap_amount": 1500,
        "effective_from": date(2026, 7, 1),
        "effective_until": date(2026, 9, 30),
    },
    # Discover: gas stations + EV charging, public transportation, flights,
    # drugstores. Activation window 2026-06-01 → 2026-09-30. Flights appear
    # for the first time. Same inert-slug note as Chase above.
    {
        "card_issuer": "discover",
        "card_product": "it_cash_back",
        "quarter": "2026-Q3",
        "categories": [
            "gas_stations",
            "ev_charging",
            "public_transit",
            "flights",
            "drugstores",
        ],
        "bonus_rate": 5.0,
        "activation_required": True,
        "activation_url": "https://www.discover.com/credit-cards/cash-back/cashback-bonus.html",
        "cap_amount": 1500,
        "effective_from": date(2026, 7, 1),
        "effective_until": date(2026, 9, 30),
    },
    # ── 2026-Q4 (PENDING CONFIRMATION — DO NOT UNCOMMENT UNVERIFIED) ────
    # Q4 is the quarter this bug actually costs money. Secondary sources
    # report Discover's Q4 2026 categories as **Amazon and Target** — both
    # first-class Barkain retailers — so from 2026-10-01 an unseeded Q4 means
    # every Discover holder shopping Amazon or Target is told to use a worse
    # card. Discover publishes officially ~September; Chase announces Q4
    # separately, also ~September.
    #
    # ACTION: in early September 2026, confirm both lists against the issuers'
    # own pages (not aggregators), fill in Chase, and uncomment.
    # {
    #     "card_issuer": "discover",
    #     "card_product": "it_cash_back",
    #     "quarter": "2026-Q4",
    #     "categories": ["amazon", "target", "online_shopping"],
    #     "bonus_rate": 5.0,
    #     "activation_required": True,
    #     "activation_url": "https://www.discover.com/credit-cards/cash-back/cashback-bonus.html",
    #     "cap_amount": 1500,
    #     "effective_from": date(2026, 10, 1),
    #     "effective_until": date(2026, 12, 31),
    # },
]


# MARK: - Seeding

async def seed_rotating(session: AsyncSession) -> int:
    count = 0
    for row in ROTATING_CATEGORIES:
        result = await session.execute(
            text(
                """
                SELECT id FROM card_reward_programs
                WHERE card_issuer = :issuer AND card_product = :product
                """
            ),
            {"issuer": row["card_issuer"], "product": row["card_product"]},
        )
        card_row = result.first()
        if card_row is None:
            raise RuntimeError(
                f"Card not found in catalog: {row['card_issuer']}/{row['card_product']}. "
                f"Run scripts/seed_card_catalog.py first."
            )
        card_program_id = card_row[0]

        await session.execute(
            text(
                """
                INSERT INTO rotating_categories (
                    card_program_id, quarter, categories, bonus_rate,
                    activation_required, activation_url, cap_amount,
                    effective_from, effective_until, last_verified
                )
                VALUES (
                    :card_program_id, :quarter, :categories, :bonus_rate,
                    :activation_required, :activation_url, :cap_amount,
                    :effective_from, :effective_until, NOW()
                )
                ON CONFLICT (card_program_id, quarter) DO UPDATE SET
                    categories = EXCLUDED.categories,
                    bonus_rate = EXCLUDED.bonus_rate,
                    activation_required = EXCLUDED.activation_required,
                    activation_url = EXCLUDED.activation_url,
                    cap_amount = EXCLUDED.cap_amount,
                    effective_from = EXCLUDED.effective_from,
                    effective_until = EXCLUDED.effective_until,
                    last_verified = NOW()
                """
            ),
            {
                "card_program_id": card_program_id,
                "quarter": row["quarter"],
                "categories": row["categories"],
                "bonus_rate": row["bonus_rate"],
                "activation_required": row["activation_required"],
                "activation_url": row["activation_url"],
                "cap_amount": row["cap_amount"],
                "effective_from": row["effective_from"],
                "effective_until": row["effective_until"],
            },
        )
        count += 1
    return count


async def main() -> None:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")

    from _db_url import get_dev_db_url

    engine = create_async_engine(get_dev_db_url())
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    async with async_session() as session:
        count = await seed_rotating(session)
        await session.commit()
        quarters = sorted({row["quarter"] for row in ROTATING_CATEGORIES})
        print(f"Seeded {count} rotating category rows across {', '.join(quarters)}.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
