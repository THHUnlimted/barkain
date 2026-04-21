"""Seed the rotating_categories table with Q2 2026 issuer-defined bonuses.

Step 2e: populates rotating 5%/5x categories for cards whose issuers publish
fixed quarterly lists (Chase Freedom Flex, Discover it Cash Back). Cards with
user-picked categories (US Bank Cash+, BofA Customized Cash) are NOT seeded
here — their rates live in card_reward_programs.category_bonuses under
`user_selected` and are activated per-user via the user_category_selections
table.

Runs AFTER seed_card_catalog.py — it looks up card_reward_programs by
(card_issuer, card_product) to resolve the FK.

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


# MARK: - Q2 2026 Rotating Categories
#
# Source: docs/CARD_REWARDS.md § "Q2 2026 Rotating Categories"
# Only cards with issuer-defined rotating lists are seeded. Cash+ / Customized
# Cash / Custom Cash remain user-picked and are resolved through
# user_category_selections at query time.

ROTATING_CATEGORIES: list[dict] = [
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
        print(f"Seeded {count} rotating category rows for Q2 2026.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
