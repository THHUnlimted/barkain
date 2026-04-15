"""Tests for workers.portal_rates.

Parser tests load HTML fixtures captured from live portal probes on
2026-04-14. Upsert tests hit a real test DB so they exercise the
``is_elevated`` GENERATED ALWAYS column end-to-end.
"""

from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select, text

from app.core_models import Retailer
from modules.m5_identity.models import PortalBonus
from workers.portal_rates import (
    PortalRate,
    normalize_retailer,
    parse_befrugal,
    parse_rakuten,
    parse_topcashback,
    upsert_portal_bonus,
)

FIXDIR = Path(__file__).resolve().parents[1] / "fixtures" / "portal_rates"


def _load(name: str) -> str:
    return (FIXDIR / name).read_text()


async def _seed_retailer(db, retailer_id: str) -> None:
    if (
        await db.execute(
            text("SELECT 1 FROM retailers WHERE id = :id"), {"id": retailer_id}
        )
    ).scalar_one_or_none() is None:
        db.add(
            Retailer(
                id=retailer_id,
                display_name=retailer_id.replace("_", " ").title(),
                base_url=f"https://www.{retailer_id}.com",
                extraction_method="agent_browser",
            )
        )
        await db.flush()


# MARK: - Parser tests


def test_parse_rakuten_extracts_phase1_retailers():
    rates = parse_rakuten(_load("rakuten.html"))
    assert len(rates) >= 3
    ids = {r.retailer_id for r in rates}
    # At least some overlap with Phase 1.
    assert ids & {"amazon", "best_buy", "walmart", "target", "lowes", "home_depot"}
    # Rakuten exposes the "was X%" marker — at least one tile should carry it.
    assert any(r.previous_rate_percent is not None for r in rates)
    # Rates are Decimal and positive.
    for r in rates:
        assert isinstance(r.rate_percent, Decimal)
        assert r.rate_percent > 0


def test_parse_topcashback_extracts_phase1_retailers():
    rates = parse_topcashback(_load("topcashback.html"))
    assert len(rates) >= 3
    ids = {r.retailer_id for r in rates}
    assert ids & {"amazon", "best_buy", "walmart", "target", "lowes", "home_depot", "ebay_new"}


def test_parse_befrugal_extracts_at_least_two_phase1_retailers():
    # BeFrugal's store index only surfaces a handful of Phase-1 retailers
    # with explicit cashback rates — Amazon, Walmart, and several others
    # either route to reward programs or don't publish a bold rate.
    # Two known hits (best_buy + home_depot) is enough to prove the
    # parser works.
    rates = parse_befrugal(_load("befrugal.html"))
    assert len(rates) >= 2
    ids = {r.retailer_id for r in rates}
    assert "best_buy" in ids or "home_depot" in ids
    for r in rates:
        assert isinstance(r.rate_percent, Decimal)
        assert r.rate_percent > 0


def test_normalize_retailer_handles_aliases_and_apostrophes():
    assert normalize_retailer("Best Buy") == "best_buy"
    assert normalize_retailer("bestbuy") == "best_buy"
    assert normalize_retailer("Lowe's") == "lowes"
    # Curly apostrophe (U+2019) — survives the normalization pass.
    assert normalize_retailer("Lowe\u2019s") == "lowes"
    assert normalize_retailer("The Home Depot") == "home_depot"
    assert normalize_retailer("Unknown Store") is None
    assert normalize_retailer("") is None


# MARK: - Upsert tests


@pytest.mark.asyncio
async def test_upsert_portal_bonus_seeds_baseline_on_first_write(db_session):
    await _seed_retailer(db_session, "best_buy")

    await upsert_portal_bonus(
        db_session,
        "rakuten",
        PortalRate(
            retailer_name="Best Buy",
            retailer_id="best_buy",
            rate_percent=Decimal("8"),
        ),
    )
    await db_session.flush()

    row = (
        await db_session.execute(
            select(PortalBonus).where(
                PortalBonus.portal_source == "rakuten",
                PortalBonus.retailer_id == "best_buy",
            )
        )
    ).scalar_one()

    assert row.bonus_value == Decimal("8")
    assert row.normal_value == Decimal("8")
    # is_elevated reads back False when current == baseline.
    assert row.is_elevated is False


@pytest.mark.asyncio
async def test_upsert_portal_bonus_detects_spike_via_generated_column(
    db_session,
):
    await _seed_retailer(db_session, "best_buy")

    # First observation: rate 5, baseline 5.
    await upsert_portal_bonus(
        db_session,
        "rakuten",
        PortalRate(
            retailer_name="Best Buy",
            retailer_id="best_buy",
            rate_percent=Decimal("5"),
        ),
    )
    await db_session.flush()

    # Second observation: rate 10 (spike). normal_value should stay at 5
    # because the upsert deliberately preserves the baseline when the
    # scrape doesn't report its own "was" marker. is_elevated then flips
    # True because 10 > 5 * 1.5 = 7.5.
    await upsert_portal_bonus(
        db_session,
        "rakuten",
        PortalRate(
            retailer_name="Best Buy",
            retailer_id="best_buy",
            rate_percent=Decimal("10"),
        ),
    )
    await db_session.flush()

    row = (
        await db_session.execute(
            select(PortalBonus).where(
                PortalBonus.portal_source == "rakuten",
                PortalBonus.retailer_id == "best_buy",
            )
        )
    ).scalar_one()

    assert row.bonus_value == Decimal("10")
    assert row.normal_value == Decimal("5")
    assert row.is_elevated is True
