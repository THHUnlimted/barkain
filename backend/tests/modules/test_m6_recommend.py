"""Tests for M6 Recommendation Engine (Step 3e).

Deterministic stacking — no LLM, no mocks required for Anthropic/Gemini.
The test file exercises the real service end-to-end over the Docker PG
fixture plus fakeredis, then drops to pure-function tests on the
stacking helpers for the math edge cases.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.core_models import Retailer, RetailerHealth
from modules.m1_product.models import Product
from modules.m2_prices.models import Price
from modules.m5_identity.card_schemas import CardRecommendation
from modules.m5_identity.models import (
    CardRewardProgram,
    DiscountProgram,
    PortalBonus,
    UserCard,
    UserDiscountProfile,
)
from modules.m5_identity.schemas import EligibleDiscount
from modules.m6_recommend.schemas import StackedPath
from modules.m6_recommend.service import (
    InsufficientPriceDataError,
    RecommendationService,
    _build_brand_direct_callout,
    _build_headline,
    _build_why,
    _rank_key,
    _stack_retailer_path,
)
from tests.conftest import MOCK_USER_ID


# MARK: - Fixture builders


async def _seed_user(db_session, user_id: str = MOCK_USER_ID) -> None:
    await db_session.execute(
        text("INSERT INTO users (id) VALUES (:id) ON CONFLICT (id) DO NOTHING"),
        {"id": user_id},
    )
    await db_session.flush()


async def _seed_retailer(
    db_session,
    retailer_id: str,
    *,
    display_name: str | None = None,
    is_active: bool = True,
) -> Retailer:
    retailer = Retailer(
        id=retailer_id,
        display_name=display_name or retailer_id.replace("_", " ").title(),
        base_url=f"https://www.{retailer_id}.com",
        extraction_method="agent_browser",
        is_active=is_active,
        supports_identity=True,
        supports_portals=True,
    )
    db_session.add(retailer)
    await db_session.flush()
    return retailer


async def _seed_health(
    db_session, retailer_id: str, *, status: str = "ok"
) -> None:
    db_session.add(
        RetailerHealth(retailer_id=retailer_id, status=status, script_version="0.0.0")
    )
    await db_session.flush()


async def _seed_product(
    db_session, *, name: str = "Sony WH-1000XM5", brand: str = "Sony"
) -> Product:
    product = Product(
        upc="194252818381",
        name=name,
        brand=brand,
        category="Electronics > Audio > Headphones",
        source="test",
    )
    db_session.add(product)
    await db_session.flush()
    return product


async def _seed_price(
    db_session,
    product_id,
    retailer_id: str,
    price_value: float,
    *,
    condition: str = "new",
) -> Price:
    row = Price(
        product_id=product_id,
        retailer_id=retailer_id,
        price=Decimal(str(price_value)),
        condition=condition,
        is_available=True,
    )
    db_session.add(row)
    await db_session.flush()
    return row


async def _seed_discount(
    db_session,
    retailer_id: str,
    *,
    program_name: str = "Samsung Offer Program",
    eligibility_type: str = "military",
    discount_value: float = 30.0,
    discount_type: str = "percentage",
) -> DiscountProgram:
    prog = DiscountProgram(
        retailer_id=retailer_id,
        program_name=program_name,
        program_type="identity",
        eligibility_type=eligibility_type,
        discount_type=discount_type,
        discount_value=Decimal(str(discount_value)),
        url=f"https://www.{retailer_id}.com/offer",
        is_active=True,
    )
    db_session.add(prog)
    await db_session.flush()
    return prog


async def _seed_portal(
    db_session, portal_source: str, retailer_id: str, bonus_value: float
) -> PortalBonus:
    row = PortalBonus(
        portal_source=portal_source,
        retailer_id=retailer_id,
        bonus_type="percentage",
        bonus_value=Decimal(str(bonus_value)),
        normal_value=Decimal(str(bonus_value)),
        effective_from=datetime.now(UTC),
    )
    db_session.add(row)
    await db_session.flush()
    return row


async def _seed_card(
    db_session,
    user_id: str,
    *,
    card_name: str = "Chase Freedom Flex",
    base_rate: float = 1.0,
) -> UserCard:
    program = CardRewardProgram(
        card_network="visa",
        card_issuer="chase",
        card_product="freedom_flex",
        card_display_name=card_name,
        base_reward_rate=Decimal(str(base_rate)),
        reward_currency="cashback",
        point_value_cents=Decimal("1.0"),
        category_bonuses=[],
    )
    db_session.add(program)
    await db_session.flush()

    user_card = UserCard(
        user_id=user_id,
        card_program_id=program.id,
        nickname=None,
        is_preferred=True,
        is_active=True,
    )
    db_session.add(user_card)
    await db_session.flush()
    return user_card


async def _seed_profile_military(db_session, user_id: str) -> None:
    profile = UserDiscountProfile(user_id=user_id, is_military=True)
    db_session.add(profile)
    await db_session.flush()


# MARK: - Pure-function stacking tests


def _mk_price_row(
    retailer_id: str,
    price: float,
    *,
    condition: str = "new",
    retailer_name: str | None = None,
) -> dict:
    return {
        "retailer_id": retailer_id,
        "retailer_name": retailer_name or retailer_id.title(),
        "price": price,
        "condition": condition,
        "url": f"https://www.{retailer_id}.com/p",
    }


def _mk_identity(
    retailer_id: str,
    *,
    program_name: str = "Military Discount",
    savings: float = 30.0,
    discount_value: float = 30.0,
) -> EligibleDiscount:
    return EligibleDiscount(
        program_id="00000000-0000-0000-0000-000000000001",
        retailer_id=retailer_id,
        retailer_name=retailer_id.title(),
        program_name=program_name,
        eligibility_type="military",
        discount_type="percentage",
        discount_value=discount_value,
        discount_max_value=None,
        estimated_savings=savings,
    )


def _mk_card(retailer_id: str, *, rate: float = 2.0) -> CardRecommendation:
    return CardRecommendation(
        retailer_id=retailer_id,
        retailer_name=retailer_id.title(),
        user_card_id="00000000-0000-0000-0000-000000000002",
        card_program_id="00000000-0000-0000-0000-000000000003",
        card_display_name="Chase Freedom Flex",
        card_issuer="chase",
        reward_rate=rate,
        reward_amount=0.0,
        reward_currency="cashback",
    )


def _mk_portal(retailer_id: str, *, rate: float = 2.0, source: str = "rakuten"):
    # Minimal stand-in for a PortalBonus row. _stack_retailer_path only reads
    # `retailer_id`, `portal_source`, `bonus_value`.
    class _P:  # noqa: D401 — test-local simple struct
        pass

    p = _P()
    p.retailer_id = retailer_id
    p.portal_source = source
    p.bonus_value = Decimal(str(rate))
    return p


def test_stack_all_three_layers_composes_identity_card_portal():
    """All three layers present — verify each lands in the output."""
    path = _stack_retailer_path(
        price_row=_mk_price_row("samsung_direct", 1000.0),
        identity_matches=[_mk_identity("samsung_direct", savings=300.0)],
        card_match=_mk_card("samsung_direct", rate=2.0),
        portal_matches=[_mk_portal("samsung_direct", rate=4.0)],
    )
    assert path.base_price == 1000.0
    assert path.identity_savings == 300.0
    # Card + portal are computed on post-identity price = 700
    assert path.card_savings == pytest.approx(14.0)
    assert path.portal_savings == pytest.approx(28.0)
    assert path.final_price == 700.0
    # effective_cost = final_price - card - portal
    assert path.effective_cost == pytest.approx(658.0)
    assert path.total_savings == pytest.approx(342.0)


def test_stack_identity_only():
    """Identity savings present, no card, no portal."""
    path = _stack_retailer_path(
        price_row=_mk_price_row("samsung_direct", 1000.0),
        identity_matches=[_mk_identity("samsung_direct", savings=200.0)],
        card_match=None,
        portal_matches=[],
    )
    assert path.identity_savings == 200.0
    assert path.card_savings == 0.0
    assert path.portal_savings == 0.0
    assert path.final_price == 800.0
    assert path.effective_cost == 800.0


def test_stack_card_only():
    """Card present, no identity, no portal."""
    path = _stack_retailer_path(
        price_row=_mk_price_row("amazon", 500.0),
        identity_matches=[],
        card_match=_mk_card("amazon", rate=5.0),
        portal_matches=[],
    )
    assert path.identity_savings == 0.0
    assert path.card_savings == 25.0
    assert path.final_price == 500.0
    assert path.effective_cost == 475.0


def test_stack_portal_only():
    """Portal present, no identity, no card."""
    path = _stack_retailer_path(
        price_row=_mk_price_row("target", 100.0),
        identity_matches=[],
        card_match=None,
        portal_matches=[_mk_portal("target", rate=3.0)],
    )
    assert path.identity_savings == 0.0
    assert path.card_savings == 0.0
    assert path.portal_savings == 3.0
    assert path.final_price == 100.0
    assert path.effective_cost == 97.0


def test_tie_break_prefers_new_over_refurbished():
    """Two candidates with identical effective_cost — new wins."""
    new = _stack_retailer_path(
        price_row=_mk_price_row("best_buy", 200.0, condition="new"),
        identity_matches=[], card_match=None, portal_matches=[],
    )
    refurb = _stack_retailer_path(
        price_row=_mk_price_row("backmarket", 200.0, condition="refurbished"),
        identity_matches=[], card_match=None, portal_matches=[],
    )
    ordered = sorted([refurb, new], key=_rank_key)
    assert ordered[0].condition == "new"
    assert ordered[1].condition == "refurbished"


def test_brand_direct_callout_fires_on_high_identity_pct():
    """Samsung military 30% → callout with all required fields populated."""
    eligible = [
        _mk_identity(
            "samsung_direct",
            program_name="Samsung Military Program",
            savings=300.0,
            discount_value=30.0,
        ),
    ]
    callout = _build_brand_direct_callout(eligible)
    assert callout is not None
    assert callout.retailer_id == "samsung_direct"
    assert callout.discount_value == 30.0
    assert callout.program_name == "Samsung Military Program"


def test_brand_direct_callout_absent_without_direct_retailer():
    """Non-`_direct` retailer doesn't trigger callout even at 30%."""
    eligible = [
        _mk_identity(
            "amazon",
            program_name="Amazon Prime Discount",
            savings=300.0,
            discount_value=30.0,
        ),
    ]
    assert _build_brand_direct_callout(eligible) is None


def test_brand_direct_callout_absent_below_threshold():
    """Samsung 10% discount is below the 15% threshold — no callout."""
    eligible = [
        _mk_identity(
            "samsung_direct",
            program_name="Samsung Student Program",
            savings=100.0,
            discount_value=10.0,
        ),
    ]
    assert _build_brand_direct_callout(eligible) is None


def test_build_headline_includes_portal_and_card_sources():
    """Three-layer headline reads as retailer + via portal + with card."""
    winner = StackedPath(
        retailer_id="amazon",
        retailer_name="Amazon",
        base_price=500.0, final_price=500.0, effective_cost=475.0,
        total_savings=25.0,
        card_savings=25.0, card_source="Chase Freedom Flex",
        portal_savings=0.0, portal_source="rakuten",
        condition="new",
    )
    headline = _build_headline(winner)
    assert "Amazon" in headline
    assert "rakuten".title() in headline
    assert "Chase Freedom Flex" in headline


def test_build_why_empty_stack_returns_simple_copy():
    """Zero-stack winner gets the 'lowest available price' fallback."""
    winner = StackedPath(
        retailer_id="amazon",
        retailer_name="Amazon",
        base_price=500.0, final_price=500.0, effective_cost=500.0,
        total_savings=0.0, condition="new",
    )
    why = _build_why(winner)
    assert "Lowest available price" in why
    assert "Amazon" in why


# MARK: - Service-level (DB + fakeredis) tests


async def test_recommendation_stacks_all_three_layers_end_to_end(
    db_session, fake_redis
):
    """Full service path — identity + card + portal all applied."""
    await _seed_user(db_session)
    await _seed_retailer(db_session, "samsung_direct", display_name="Samsung.com")
    await _seed_retailer(db_session, "best_buy", display_name="Best Buy")
    await _seed_health(db_session, "samsung_direct")
    await _seed_health(db_session, "best_buy")
    await _seed_profile_military(db_session, MOCK_USER_ID)
    # Samsung product so the identity relevance filter doesn't drop
    # the samsung_direct program (see IdentityService.BRAND_SPECIFIC_RETAILERS).
    product = await _seed_product(
        db_session, name="Samsung Galaxy S25 Ultra", brand="Samsung"
    )
    await _seed_price(db_session, product.id, "samsung_direct", 1000.0)
    await _seed_price(db_session, product.id, "best_buy", 1050.0)
    await _seed_discount(
        db_session, "samsung_direct", program_name="Samsung Military", discount_value=30.0,
    )
    await _seed_portal(db_session, "rakuten", "samsung_direct", 4.0)
    await _seed_card(db_session, MOCK_USER_ID, base_rate=2.0)
    await db_session.flush()

    # Seed the Redis price cache so PriceAggregationService serves from
    # Redis without calling scraper containers.
    import json
    payload = {
        "product_id": str(product.id),
        "product_name": product.name,
        "prices": [
            {
                "retailer_id": "samsung_direct",
                "retailer_name": "Samsung.com",
                "price": 1000.0,
                "condition": "new",
                "url": "https://www.samsung.com/p",
                "is_available": True,
                "last_checked": datetime.now(UTC).isoformat(),
            },
            {
                "retailer_id": "best_buy",
                "retailer_name": "Best Buy",
                "price": 1050.0,
                "condition": "new",
                "url": "https://www.bestbuy.com/p",
                "is_available": True,
                "last_checked": datetime.now(UTC).isoformat(),
            },
        ],
        "retailer_results": [],
        "total_retailers": 2,
        "retailers_succeeded": 2,
        "retailers_failed": 0,
        "cached": True,
        "fetched_at": datetime.now(UTC).isoformat(),
    }
    await fake_redis.setex(
        f"prices:product:{product.id}", 600, json.dumps(payload)
    )

    service = RecommendationService(db_session, fake_redis)
    rec = await service.get_recommendation(MOCK_USER_ID, product.id)

    assert rec.winner.retailer_id == "samsung_direct"
    assert rec.winner.identity_savings > 0
    assert rec.winner.card_savings > 0
    assert rec.winner.portal_savings > 0
    assert rec.has_stackable_value is True
    assert rec.brand_direct_callout is not None
    assert rec.brand_direct_callout.retailer_id == "samsung_direct"
    assert len(rec.alternatives) == 1


async def test_recommendation_insufficient_data_raises(db_session, fake_redis):
    """Fewer than 2 usable retailer prices → InsufficientPriceDataError."""
    await _seed_user(db_session)
    await _seed_retailer(db_session, "amazon")
    await _seed_health(db_session, "amazon")
    product = await _seed_product(db_session)
    await _seed_price(db_session, product.id, "amazon", 100.0)
    await db_session.flush()

    import json
    await fake_redis.setex(
        f"prices:product:{product.id}", 600,
        json.dumps({
            "product_id": str(product.id),
            "product_name": product.name,
            "prices": [{
                "retailer_id": "amazon", "retailer_name": "Amazon",
                "price": 100.0, "condition": "new",
                "url": "https://www.amazon.com/p",
                "is_available": True,
                "last_checked": datetime.now(UTC).isoformat(),
            }],
            "retailer_results": [],
            "total_retailers": 1, "retailers_succeeded": 1, "retailers_failed": 0,
            "cached": True, "fetched_at": datetime.now(UTC).isoformat(),
        }),
    )

    service = RecommendationService(db_session, fake_redis)
    with pytest.raises(InsufficientPriceDataError):
        await service.get_recommendation(MOCK_USER_ID, product.id)


async def test_recommendation_excludes_inactive_retailer(db_session, fake_redis):
    """A price row for an inactive retailer is dropped from the stack."""
    await _seed_user(db_session)
    await _seed_retailer(db_session, "amazon", is_active=True)
    await _seed_retailer(db_session, "lowes", is_active=False)
    await _seed_retailer(db_session, "best_buy", is_active=True)
    await _seed_health(db_session, "amazon")
    await _seed_health(db_session, "best_buy")
    product = await _seed_product(db_session)
    await db_session.flush()

    import json
    payload = {
        "product_id": str(product.id),
        "product_name": product.name,
        "prices": [
            _wire_price("amazon", 100.0), _wire_price("lowes", 50.0),
            _wire_price("best_buy", 110.0),
        ],
        "retailer_results": [],
        "total_retailers": 3, "retailers_succeeded": 3, "retailers_failed": 0,
        "cached": True, "fetched_at": datetime.now(UTC).isoformat(),
    }
    await fake_redis.setex(f"prices:product:{product.id}", 600, json.dumps(payload))

    service = RecommendationService(db_session, fake_redis)
    rec = await service.get_recommendation(MOCK_USER_ID, product.id)
    retailer_ids = [rec.winner.retailer_id] + [a.retailer_id for a in rec.alternatives]
    assert "lowes" not in retailer_ids


async def test_recommendation_excludes_drift_flagged_retailer(db_session, fake_redis):
    """Retailer with health status != ok/healthy is excluded."""
    await _seed_user(db_session)
    await _seed_retailer(db_session, "amazon")
    await _seed_retailer(db_session, "walmart")
    await _seed_retailer(db_session, "best_buy")
    await _seed_health(db_session, "amazon", status="ok")
    await _seed_health(db_session, "walmart", status="selector_drift")
    await _seed_health(db_session, "best_buy", status="ok")
    product = await _seed_product(db_session)
    await db_session.flush()

    import json
    payload = {
        "product_id": str(product.id),
        "product_name": product.name,
        "prices": [
            _wire_price("amazon", 100.0), _wire_price("walmart", 50.0),
            _wire_price("best_buy", 110.0),
        ],
        "retailer_results": [],
        "total_retailers": 3, "retailers_succeeded": 3, "retailers_failed": 0,
        "cached": True, "fetched_at": datetime.now(UTC).isoformat(),
    }
    await fake_redis.setex(f"prices:product:{product.id}", 600, json.dumps(payload))

    service = RecommendationService(db_session, fake_redis)
    rec = await service.get_recommendation(MOCK_USER_ID, product.id)
    retailer_ids = [rec.winner.retailer_id] + [a.retailer_id for a in rec.alternatives]
    assert "walmart" not in retailer_ids


async def test_recommendation_cache_hit_on_repeat_call(db_session, fake_redis):
    """Second call within TTL returns cached=True."""
    await _seed_user(db_session)
    await _seed_retailer(db_session, "amazon")
    await _seed_retailer(db_session, "best_buy")
    await _seed_health(db_session, "amazon")
    await _seed_health(db_session, "best_buy")
    product = await _seed_product(db_session)
    await db_session.flush()

    import json
    payload = {
        "product_id": str(product.id),
        "product_name": product.name,
        "prices": [
            _wire_price("amazon", 100.0), _wire_price("best_buy", 110.0),
        ],
        "retailer_results": [],
        "total_retailers": 2, "retailers_succeeded": 2, "retailers_failed": 0,
        "cached": True, "fetched_at": datetime.now(UTC).isoformat(),
    }
    await fake_redis.setex(f"prices:product:{product.id}", 600, json.dumps(payload))

    service = RecommendationService(db_session, fake_redis)
    first = await service.get_recommendation(MOCK_USER_ID, product.id)
    second = await service.get_recommendation(MOCK_USER_ID, product.id)
    assert first.cached is False
    assert second.cached is True


async def test_recommendation_cache_busts_on_card_portfolio_change(
    db_session, fake_redis
):
    """Adding a user card flips the cache key suffix so the next call re-computes.

    Step 3f Pre-Fix #6 — the `:c<hash>` suffix hashes the sorted set of
    user_card ids. A new card shifts the hash; the v1 entry is unreachable
    via the new key and the caller sees cached=False.
    """
    await _seed_user(db_session)
    await _seed_retailer(db_session, "amazon")
    await _seed_retailer(db_session, "best_buy")
    await _seed_health(db_session, "amazon")
    await _seed_health(db_session, "best_buy")
    product = await _seed_product(db_session)
    await db_session.flush()

    import json as _json
    payload = {
        "product_id": str(product.id),
        "product_name": product.name,
        "prices": [
            _wire_price("amazon", 100.0), _wire_price("best_buy", 110.0),
        ],
        "retailer_results": [],
        "total_retailers": 2, "retailers_succeeded": 2, "retailers_failed": 0,
        "cached": True, "fetched_at": datetime.now(UTC).isoformat(),
    }
    await fake_redis.setex(f"prices:product:{product.id}", 600, _json.dumps(payload))

    service = RecommendationService(db_session, fake_redis)
    first = await service.get_recommendation(MOCK_USER_ID, product.id)
    assert first.cached is False

    # Hit again — should be cached.
    second = await service.get_recommendation(MOCK_USER_ID, product.id)
    assert second.cached is True

    # Add a card — the cache key suffix changes.
    program = CardRewardProgram(
        card_network="visa",
        card_issuer="chase",
        card_product="freedom_flex",
        card_display_name="Chase Freedom Flex",
        base_reward_rate=Decimal("1.0"),
        reward_currency="ultimate_rewards",
        point_value_cents=Decimal("1.25"),
        has_shopping_portal=True,
        annual_fee=Decimal("0.0"),
    )
    db_session.add(program)
    await db_session.flush()
    db_session.add(
        UserCard(
            user_id=MOCK_USER_ID,
            card_program_id=program.id,
            is_preferred=True,
        )
    )
    await db_session.flush()

    third = await service.get_recommendation(MOCK_USER_ID, product.id)
    assert third.cached is False


async def test_recommendation_cache_busts_on_portal_membership_toggle(
    db_session, fake_redis
):
    """Toggling a portal membership flag flips the `:p<hash>` cache segment.

    Step 3g-B — without this, a user toggling "I'm a Rakuten member" in
    Profile would keep seeing the SIGNUP_REFERRAL CTA for up to the
    15-min TTL. Same class of bug as the card-portfolio busting test
    above; covered with the same setup.
    """
    await _seed_user(db_session)
    await _seed_retailer(db_session, "amazon")
    await _seed_retailer(db_session, "best_buy")
    await _seed_health(db_session, "amazon")
    await _seed_health(db_session, "best_buy")
    product = await _seed_product(db_session)
    await db_session.flush()

    import json as _json
    payload = {
        "product_id": str(product.id),
        "product_name": product.name,
        "prices": [
            _wire_price("amazon", 100.0), _wire_price("best_buy", 110.0),
        ],
        "retailer_results": [],
        "total_retailers": 2, "retailers_succeeded": 2, "retailers_failed": 0,
        "cached": True, "fetched_at": datetime.now(UTC).isoformat(),
    }
    await fake_redis.setex(f"prices:product:{product.id}", 600, _json.dumps(payload))

    service = RecommendationService(db_session, fake_redis)
    first = await service.get_recommendation(
        MOCK_USER_ID, product.id, user_memberships={}
    )
    assert first.cached is False

    second = await service.get_recommendation(
        MOCK_USER_ID, product.id, user_memberships={}
    )
    assert second.cached is True

    # Toggle Rakuten membership on — the :p<hash> segment changes.
    third = await service.get_recommendation(
        MOCK_USER_ID, product.id, user_memberships={"rakuten": True}
    )
    assert third.cached is False

    # Toggle off again returns the same hash as the first call (False values
    # are dropped before hashing) so we get a cache hit on that key.
    fourth = await service.get_recommendation(
        MOCK_USER_ID, product.id, user_memberships={"rakuten": False}
    )
    assert fourth.cached is True


# MARK: - Endpoint-level tests


async def test_recommend_endpoint_404_on_unknown_product(client, db_session):
    """Unknown product_id → 404."""
    resp = await client.post(
        "/api/v1/recommend",
        json={"product_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["error"]["code"] == "PRODUCT_NOT_FOUND"


async def test_recommend_endpoint_422_on_insufficient_data(
    client, db_session, fake_redis
):
    """Product with <2 usable prices → 422 RECOMMEND_INSUFFICIENT_DATA."""
    await _seed_user(db_session)
    await _seed_retailer(db_session, "amazon")
    await _seed_health(db_session, "amazon")
    product = await _seed_product(db_session)
    await db_session.flush()

    import json
    await fake_redis.setex(
        f"prices:product:{product.id}", 600,
        json.dumps({
            "product_id": str(product.id),
            "product_name": product.name,
            "prices": [_wire_price("amazon", 100.0)],
            "retailer_results": [],
            "total_retailers": 1, "retailers_succeeded": 1, "retailers_failed": 0,
            "cached": True, "fetched_at": datetime.now(UTC).isoformat(),
        }),
    )

    resp = await client.post(
        "/api/v1/recommend", json={"product_id": str(product.id)}
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"]["code"] == "RECOMMEND_INSUFFICIENT_DATA"



# MARK: - Wire-shape helper


def _wire_price(retailer_id: str, price: float, condition: str = "new") -> dict:
    return {
        "retailer_id": retailer_id,
        "retailer_name": retailer_id.replace("_", " ").title(),
        "price": price,
        "condition": condition,
        "url": f"https://www.{retailer_id}.com/p",
        "is_available": True,
        "last_checked": datetime.now(UTC).isoformat(),
    }
