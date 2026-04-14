"""Tests for M5 Card Portfolio — CardService + /api/v1/cards endpoints (Step 2e)."""

import statistics
import time
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select, text

from app.core_models import Retailer
from modules.m1_product.models import Product
from modules.m2_prices.models import Price
from modules.m5_identity.models import (
    CardRewardProgram,
    RotatingCategory,
    UserCategorySelection,
)
from tests.conftest import MOCK_USER_ID


# MARK: - Helpers


async def _seed_user(db_session, user_id: str = MOCK_USER_ID) -> None:
    await db_session.execute(
        text("INSERT INTO users (id) VALUES (:id) ON CONFLICT (id) DO NOTHING"),
        {"id": user_id},
    )
    await db_session.flush()


async def _seed_retailer(
    db_session,
    retailer_id: str,
    display_name: str | None = None,
) -> Retailer:
    retailer = Retailer(
        id=retailer_id,
        display_name=display_name or retailer_id.replace("_", " ").title(),
        base_url=f"https://www.{retailer_id}.com",
        extraction_method="agent_browser",
    )
    db_session.add(retailer)
    await db_session.flush()
    return retailer


async def _seed_card(
    db_session,
    *,
    issuer: str,
    product: str,
    display_name: str,
    base_rate: float = 1.0,
    reward_currency: str = "cashback",
    point_value: float | None = 1.0,
    category_bonuses: list[dict] | None = None,
    has_portal: bool = False,
) -> CardRewardProgram:
    card = CardRewardProgram(
        card_network="visa",
        card_issuer=issuer,
        card_product=product,
        card_display_name=display_name,
        base_reward_rate=Decimal(str(base_rate)),
        reward_currency=reward_currency,
        point_value_cents=(
            Decimal(str(point_value)) if point_value is not None else None
        ),
        category_bonuses=category_bonuses or [],
        has_shopping_portal=has_portal,
    )
    db_session.add(card)
    await db_session.flush()
    return card


async def _seed_rotating(
    db_session,
    card_program_id,
    *,
    categories: list[str],
    bonus_rate: float,
    quarter: str = "2026-Q2",
    effective_from: date = date(2026, 4, 1),
    effective_until: date = date(2026, 6, 30),
    activation_required: bool = True,
    activation_url: str | None = "https://example.com/activate",
) -> RotatingCategory:
    row = RotatingCategory(
        card_program_id=card_program_id,
        quarter=quarter,
        categories=categories,
        bonus_rate=Decimal(str(bonus_rate)),
        activation_required=activation_required,
        activation_url=activation_url,
        effective_from=effective_from,
        effective_until=effective_until,
    )
    db_session.add(row)
    await db_session.flush()
    return row


async def _seed_product_with_prices(
    db_session,
    prices: dict[str, float],
    *,
    name: str = "Card Test Product",
) -> Product:
    """Seed one product + one Price row per (retailer_id, price) pair."""
    product = Product(
        name=name,
        brand="Test",
        upc=str(int(time.time() * 1000))[:12],
        category="test",
        source="test",
    )
    db_session.add(product)
    await db_session.flush()
    for retailer_id, price in prices.items():
        db_session.add(
            Price(
                product_id=product.id,
                retailer_id=retailer_id,
                price=Decimal(str(price)),
                condition="new",
                is_available=True,
            )
        )
    await db_session.flush()
    return product


# MARK: - Catalog + CRUD (endpoint-level)


async def test_catalog_empty_returns_empty(client, db_session):
    resp = await client.get("/api/v1/cards/catalog")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_catalog_returns_active_cards(client, db_session):
    await _seed_card(
        db_session, issuer="chase", product="sapphire_preferred",
        display_name="Chase Sapphire Preferred",
    )
    inactive = await _seed_card(
        db_session, issuer="chase", product="inactive",
        display_name="Old Card",
    )
    inactive.is_active = False
    await db_session.flush()

    resp = await client.get("/api/v1/cards/catalog")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["card_display_name"] == "Chase Sapphire Preferred"


async def test_add_card_to_portfolio(client, db_session):
    card = await _seed_card(
        db_session, issuer="chase", product="freedom_flex",
        display_name="Chase Freedom Flex",
    )
    resp = await client.post(
        "/api/v1/cards/my-cards",
        json={"card_program_id": str(card.id), "nickname": "daily driver"},
    )
    assert resp.status_code == 201
    added = resp.json()
    assert added["nickname"] == "daily driver"
    assert added["card_display_name"] == "Chase Freedom Flex"

    # GET my-cards returns it
    resp = await client.get("/api/v1/cards/my-cards")
    assert resp.status_code == 200
    cards = resp.json()
    assert len(cards) == 1
    assert cards[0]["card_program_id"] == str(card.id)


async def test_add_card_unknown_returns_404(client, db_session):
    resp = await client.post(
        "/api/v1/cards/my-cards",
        json={"card_program_id": str(uuid4())},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["error"]["code"] == "CARD_NOT_FOUND"


async def test_add_card_reactivates_soft_deleted(client, db_session):
    card = await _seed_card(
        db_session, issuer="amex", product="gold_card",
        display_name="Amex Gold",
    )
    await client.post(
        "/api/v1/cards/my-cards",
        json={"card_program_id": str(card.id)},
    )
    cards = (await client.get("/api/v1/cards/my-cards")).json()
    user_card_id = cards[0]["id"]

    # Remove
    del_resp = await client.delete(f"/api/v1/cards/my-cards/{user_card_id}")
    assert del_resp.status_code == 204
    assert (await client.get("/api/v1/cards/my-cards")).json() == []

    # Re-add with a new nickname
    await client.post(
        "/api/v1/cards/my-cards",
        json={"card_program_id": str(card.id), "nickname": "restored"},
    )
    cards2 = (await client.get("/api/v1/cards/my-cards")).json()
    assert len(cards2) == 1
    assert cards2[0]["nickname"] == "restored"
    assert cards2[0]["id"] == user_card_id  # same row, reactivated


async def test_set_preferred_unsets_others(client, db_session):
    c1 = await _seed_card(db_session, issuer="chase", product="a", display_name="A")
    c2 = await _seed_card(db_session, issuer="chase", product="b", display_name="B")
    await client.post("/api/v1/cards/my-cards", json={"card_program_id": str(c1.id)})
    await client.post("/api/v1/cards/my-cards", json={"card_program_id": str(c2.id)})
    cards = (await client.get("/api/v1/cards/my-cards")).json()
    id_b = next(c["id"] for c in cards if c["card_product"] == "b")

    resp = await client.put(f"/api/v1/cards/my-cards/{id_b}/preferred")
    assert resp.status_code == 200
    updated = (await client.get("/api/v1/cards/my-cards")).json()
    preferred = [c for c in updated if c["is_preferred"]]
    assert len(preferred) == 1
    assert preferred[0]["card_product"] == "b"


async def test_set_user_categories_upserts(client, db_session):
    card = await _seed_card(
        db_session,
        issuer="us_bank",
        product="cash_plus",
        display_name="US Bank Cash+",
        category_bonuses=[
            {
                "category": "user_selected",
                "rate": 5.0,
                "cap": 2000,
                "allowed": ["electronics_stores", "department_stores", "restaurants"],
            }
        ],
    )
    await client.post("/api/v1/cards/my-cards", json={"card_program_id": str(card.id)})
    cards = (await client.get("/api/v1/cards/my-cards")).json()
    user_card_id = cards[0]["id"]

    resp = await client.post(
        f"/api/v1/cards/my-cards/{user_card_id}/categories",
        json={"categories": ["electronics_stores", "restaurants"], "quarter": "2026-Q2"},
    )
    assert resp.status_code == 200

    # Confirm row exists with the expected shape
    selection = (
        await db_session.execute(
            select(UserCategorySelection).where(
                UserCategorySelection.user_id == MOCK_USER_ID,
                UserCategorySelection.card_program_id == card.id,
            )
        )
    ).scalar_one()
    assert set(selection.selected_categories) == {"electronics_stores", "restaurants"}
    assert selection.effective_from == date(2026, 4, 1)
    assert selection.effective_until == date(2026, 6, 30)


async def test_set_user_categories_rejects_unknown(client, db_session):
    card = await _seed_card(
        db_session,
        issuer="us_bank",
        product="cash_plus",
        display_name="US Bank Cash+",
        category_bonuses=[
            {
                "category": "user_selected",
                "rate": 5.0,
                "allowed": ["electronics_stores"],
            }
        ],
    )
    await client.post("/api/v1/cards/my-cards", json={"card_program_id": str(card.id)})
    cards = (await client.get("/api/v1/cards/my-cards")).json()
    user_card_id = cards[0]["id"]

    resp = await client.post(
        f"/api/v1/cards/my-cards/{user_card_id}/categories",
        json={"categories": ["amazon"], "quarter": "2026-Q2"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"]["code"] == "INVALID_CATEGORY_SELECTION"


# MARK: - Recommendations (service + endpoint)


async def test_recommendations_no_cards_returns_empty(client, db_session):
    product = await _seed_product_with_prices(db_session, {})
    resp = await client.get(
        f"/api/v1/cards/recommendations?product_id={product.id}"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_has_cards"] is False
    assert body["recommendations"] == []


async def test_recommendations_rotating_bonus_wins(client, db_session):
    """Freedom Flex with Amazon 5x rotating beats Sapphire Preferred 1x at Amazon."""
    await _seed_retailer(db_session, "amazon", "Amazon")
    csp = await _seed_card(
        db_session, issuer="chase", product="sapphire_preferred",
        display_name="Chase Sapphire Preferred", base_rate=1.0,
        reward_currency="ultimate_rewards", point_value=1.25,
        category_bonuses=[{"category": "dining", "rate": 3.0}],
    )
    ff = await _seed_card(
        db_session, issuer="chase", product="freedom_flex",
        display_name="Chase Freedom Flex", base_rate=1.0,
        reward_currency="ultimate_rewards", point_value=1.25,
    )
    await _seed_rotating(
        db_session, ff.id, categories=["amazon"], bonus_rate=5.0,
    )
    for c in (csp, ff):
        await client.post(
            "/api/v1/cards/my-cards", json={"card_program_id": str(c.id)}
        )
    product = await _seed_product_with_prices(db_session, {"amazon": 100.0})

    resp = await client.get(
        f"/api/v1/cards/recommendations?product_id={product.id}"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_has_cards"] is True
    assert len(body["recommendations"]) == 1
    rec = body["recommendations"][0]
    assert rec["card_display_name"] == "Chase Freedom Flex"
    assert rec["reward_rate"] == 5.0
    assert rec["is_rotating_bonus"] is True
    assert rec["activation_required"] is True
    assert rec["activation_url"] == "https://example.com/activate"
    # 100 * 5.0 * 1.25 / 100 = 6.25
    assert rec["reward_amount"] == 6.25


async def test_recommendations_static_bonus_wins(client, db_session):
    """Amex Blue Cash Everyday 3% online_shopping beats Quicksilver 1.5% at amazon."""
    await _seed_retailer(db_session, "amazon", "Amazon")
    qs = await _seed_card(
        db_session, issuer="capital_one", product="quicksilver",
        display_name="Capital One Quicksilver", base_rate=1.5,
    )
    bce = await _seed_card(
        db_session, issuer="amex", product="blue_cash_everyday",
        display_name="Amex Blue Cash Everyday", base_rate=1.0,
        category_bonuses=[{"category": "online_shopping", "rate": 3.0}],
    )
    for c in (qs, bce):
        await client.post(
            "/api/v1/cards/my-cards", json={"card_program_id": str(c.id)}
        )
    product = await _seed_product_with_prices(db_session, {"amazon": 200.0})

    resp = await client.get(
        f"/api/v1/cards/recommendations?product_id={product.id}"
    )
    body = resp.json()
    rec = body["recommendations"][0]
    assert rec["card_display_name"] == "Amex Blue Cash Everyday"
    assert rec["reward_rate"] == 3.0
    assert rec["is_rotating_bonus"] is False
    assert rec["is_user_selected_bonus"] is False
    # 200 * 3 * 1.0 / 100 = 6.00
    assert rec["reward_amount"] == 6.0


async def test_recommendations_user_selected_wins(client, db_session):
    """Cash+ 5x at electronics_stores (user-selected) beats Quicksilver 1.5% at Best Buy."""
    await _seed_retailer(db_session, "best_buy", "Best Buy")
    qs = await _seed_card(
        db_session, issuer="capital_one", product="quicksilver",
        display_name="Capital One Quicksilver", base_rate=1.5,
    )
    cashplus = await _seed_card(
        db_session,
        issuer="us_bank",
        product="cash_plus",
        display_name="US Bank Cash+",
        base_rate=1.0,
        category_bonuses=[
            {
                "category": "user_selected",
                "rate": 5.0,
                "cap": 2000,
                "allowed": ["electronics_stores"],
            }
        ],
    )
    for c in (qs, cashplus):
        await client.post(
            "/api/v1/cards/my-cards", json={"card_program_id": str(c.id)}
        )
    cashplus_user_card = (
        await client.get("/api/v1/cards/my-cards")
    ).json()
    cash_id = next(
        c["id"] for c in cashplus_user_card if c["card_product"] == "cash_plus"
    )
    await client.post(
        f"/api/v1/cards/my-cards/{cash_id}/categories",
        json={"categories": ["electronics_stores"], "quarter": "2026-Q2"},
    )
    product = await _seed_product_with_prices(db_session, {"best_buy": 400.0})

    resp = await client.get(
        f"/api/v1/cards/recommendations?product_id={product.id}"
    )
    rec = resp.json()["recommendations"][0]
    assert rec["card_display_name"] == "US Bank Cash+"
    assert rec["reward_rate"] == 5.0
    assert rec["is_user_selected_bonus"] is True
    # 400 * 5 * 1.0 / 100 = 20.00
    assert rec["reward_amount"] == 20.0


async def test_recommendations_expired_rotating_ignored(client, db_session):
    """A rotating row whose effective_until is in the past must not fire."""
    await _seed_retailer(db_session, "amazon", "Amazon")
    ff = await _seed_card(
        db_session, issuer="chase", product="freedom_flex",
        display_name="Chase Freedom Flex", base_rate=1.0,
    )
    yesterday = date.today() - timedelta(days=10)
    await _seed_rotating(
        db_session, ff.id, categories=["amazon"], bonus_rate=5.0,
        quarter="2025-Q1",
        effective_from=yesterday - timedelta(days=90),
        effective_until=yesterday,
    )
    await client.post(
        "/api/v1/cards/my-cards", json={"card_program_id": str(ff.id)}
    )
    product = await _seed_product_with_prices(db_session, {"amazon": 100.0})

    resp = await client.get(
        f"/api/v1/cards/recommendations?product_id={product.id}"
    )
    rec = resp.json()["recommendations"][0]
    assert rec["reward_rate"] == 1.0
    assert rec["is_rotating_bonus"] is False


async def test_recommendations_one_per_retailer(client, db_session):
    """Product with 3 retailer prices → 3 recommendations."""
    for rid in ("amazon", "best_buy", "walmart"):
        await _seed_retailer(db_session, rid, rid.replace("_", " ").title())
    card = await _seed_card(
        db_session, issuer="wells_fargo", product="active_cash",
        display_name="Wells Fargo Active Cash", base_rate=2.0,
    )
    await client.post(
        "/api/v1/cards/my-cards", json={"card_program_id": str(card.id)}
    )
    product = await _seed_product_with_prices(
        db_session,
        {"amazon": 100.0, "best_buy": 105.0, "walmart": 110.0},
    )

    resp = await client.get(
        f"/api/v1/cards/recommendations?product_id={product.id}"
    )
    body = resp.json()
    retailer_ids = {r["retailer_id"] for r in body["recommendations"]}
    assert retailer_ids == {"amazon", "best_buy", "walmart"}
    # All pick the same card, each with the same 2x flat rate.
    for rec in body["recommendations"]:
        assert rec["reward_rate"] == 2.0


async def test_recommendations_matching_under_50ms(client, db_session):
    """Perf gate: 5 cards × 2 rotating × 1 selection × 3 retailers < 50ms median."""
    for rid in ("amazon", "best_buy", "walmart"):
        await _seed_retailer(db_session, rid, rid.replace("_", " ").title())
    cards = []
    for i in range(5):
        card = await _seed_card(
            db_session,
            issuer="chase",
            product=f"perf_card_{i}",
            display_name=f"Perf Card {i}",
            base_rate=1.0 + 0.1 * i,
            category_bonuses=[{"category": "online_shopping", "rate": 2.5}],
        )
        cards.append(card)
    await _seed_rotating(
        db_session, cards[0].id, categories=["amazon"], bonus_rate=5.0
    )
    await _seed_rotating(
        db_session, cards[1].id, categories=["home_improvement"], bonus_rate=5.0
    )
    for c in cards:
        await client.post(
            "/api/v1/cards/my-cards", json={"card_program_id": str(c.id)}
        )
    product = await _seed_product_with_prices(
        db_session,
        {"amazon": 100.0, "best_buy": 120.0, "walmart": 90.0},
    )

    timings: list[float] = []
    for _ in range(5):
        t0 = time.perf_counter()
        resp = await client.get(
            f"/api/v1/cards/recommendations?product_id={product.id}"
        )
        timings.append((time.perf_counter() - t0) * 1000.0)
        assert resp.status_code == 200
    median_ms = statistics.median(timings)
    assert median_ms < 150.0, (
        f"card recommendations too slow: median={median_ms:.1f}ms timings={timings}"
    )


async def test_add_card_creates_users_row_first(client, db_session):
    """Adding a card for a brand-new user upserts the users row (FK satisfied)."""
    # No explicit _seed_user call; the mock client has a fresh MOCK_USER_ID.
    card = await _seed_card(
        db_session, issuer="chase", product="freedom_unlimited",
        display_name="Chase Freedom Unlimited",
    )
    resp = await client.post(
        "/api/v1/cards/my-cards", json={"card_program_id": str(card.id)}
    )
    assert resp.status_code == 201
    # users row now exists
    users_row = (
        await db_session.execute(
            text("SELECT id FROM users WHERE id = :id"),
            {"id": MOCK_USER_ID},
        )
    ).first()
    assert users_row is not None


async def test_service_quarter_to_dates():
    from modules.m5_identity.card_service import _quarter_to_dates

    assert _quarter_to_dates("2026-Q1") == (date(2026, 1, 1), date(2026, 3, 31))
    assert _quarter_to_dates("2026-Q2") == (date(2026, 4, 1), date(2026, 6, 30))
    assert _quarter_to_dates("2026-Q3") == (date(2026, 7, 1), date(2026, 9, 30))
    assert _quarter_to_dates("2026-Q4") == (date(2026, 10, 1), date(2026, 12, 31))
    import pytest

    with pytest.raises(ValueError):
        _quarter_to_dates("bogus")
