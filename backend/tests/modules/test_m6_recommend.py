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
    # Pass active rakuten membership so the seeded portal bonus stacks —
    # the service only applies portal cashback for memberships the user
    # has activated (otherwise the hero promises savings the Continue
    # button can't actually transit).
    rec = await service.get_recommendation(
        MOCK_USER_ID, product.id, user_memberships={"rakuten": True}
    )

    assert rec.winner.retailer_id == "samsung_direct"
    assert rec.winner.identity_savings > 0
    assert rec.winner.card_savings > 0
    assert rec.winner.portal_savings > 0
    assert rec.has_stackable_value is True
    assert rec.brand_direct_callout is not None
    assert rec.brand_direct_callout.retailer_id == "samsung_direct"
    assert len(rec.alternatives) == 1


async def test_recommendation_skips_portal_savings_for_inactive_membership(
    db_session, fake_redis
):
    """Without an active portal membership the receipt must not promise
    portal savings — Continue would route direct-retailer and the rebate
    would never post."""
    await _seed_user(db_session)
    await _seed_retailer(db_session, "samsung_direct", display_name="Samsung.com")
    await _seed_retailer(db_session, "best_buy", display_name="Best Buy")
    await _seed_health(db_session, "samsung_direct")
    await _seed_health(db_session, "best_buy")
    product = await _seed_product(
        db_session, name="Samsung Galaxy S25 Ultra", brand="Samsung"
    )
    await _seed_price(db_session, product.id, "samsung_direct", 1000.0)
    await _seed_price(db_session, product.id, "best_buy", 1050.0)
    await _seed_portal(db_session, "rakuten", "samsung_direct", 4.0)
    await db_session.flush()

    import json
    payload = {
        "product_id": str(product.id),
        "product_name": product.name,
        "prices": [
            {
                "retailer_id": "samsung_direct",
                "retailer_name": "Samsung.com",
                "price": 1000.0, "condition": "new",
                "url": "https://www.samsung.com/p",
                "is_available": True,
                "last_checked": datetime.now(UTC).isoformat(),
            },
            {
                "retailer_id": "best_buy",
                "retailer_name": "Best Buy",
                "price": 1050.0, "condition": "new",
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
    # User explicitly has rakuten DEACTIVATED — portal savings must not
    # be applied.
    rec = await service.get_recommendation(
        MOCK_USER_ID, product.id, user_memberships={"rakuten": False}
    )

    assert rec.winner.portal_savings == 0.0
    assert rec.winner.portal_source is None

    # And the no-memberships case (empty dict) should be identical.
    rec_empty = await service.get_recommendation(
        MOCK_USER_ID, product.id, force_refresh=True, user_memberships={}
    )
    assert rec_empty.winner.portal_savings == 0.0
    assert rec_empty.winner.portal_source is None


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



# MARK: - Inflight cache contamination guard (inflight-cache-1-L1)


async def test_recommendation_skips_cache_write_when_prices_came_from_inflight(
    db_session, fake_redis, caplog
):
    """When the prices payload comes from m2's in-flight bucket (mid-stream
    snapshot), the recommendation must NOT be persisted to M6's 15-min
    cache. Otherwise a provisional rec built from a 5/9 retailer snapshot
    would serve the same user for up to 15 min after the stream completes,
    masking the canonical 9/9 result.

    Also asserts the structured log line so future agents debugging
    "why is my rec stale" can grep for it.
    """
    import logging

    from modules.m2_prices.service import PriceAggregationService

    await _seed_user(db_session)
    await _seed_retailer(db_session, "amazon")
    await _seed_retailer(db_session, "best_buy")
    await _seed_health(db_session, "amazon")
    await _seed_health(db_session, "best_buy")
    product = await _seed_product(db_session)
    await db_session.flush()

    # Seed the inflight bucket directly via m2's writer — exactly what
    # `stream_prices` would do mid-run for each completed retailer.
    price_service = PriceAggregationService(db=db_session, redis=fake_redis)
    for rid, price in [("amazon", 100.0), ("best_buy", 110.0)]:
        await price_service._write_inflight(
            product.id,
            rid,
            price_payload=_wire_price(rid, price),
            result={
                "retailer_id": rid,
                "retailer_name": rid.replace("_", " ").title(),
                "status": "success",
            },
        )

    # No canonical Redis cache for this product — forces M6's get_prices
    # to fall through past Step 2 and hit the inflight bucket at Step 2.5.
    bare_canonical = f"prices:product:{product.id}"
    assert await fake_redis.get(bare_canonical) is None

    caplog.set_level(logging.INFO, logger="barkain.m6")

    service = RecommendationService(db_session, fake_redis)
    rec = await service.get_recommendation(MOCK_USER_ID, product.id)
    assert rec.cached is False  # fresh build, not a cache hit

    # CRITICAL: M6's cache key must NOT have been written.
    from modules.m6_recommend.service import _portal_membership_hash
    user_card_hash = await service._user_card_hash(MOCK_USER_ID)
    identity_hash = await service._identity_flag_hash(MOCK_USER_ID)
    portal_hash = _portal_membership_hash({})
    m6_cache_key = service._cache_key(
        MOCK_USER_ID, product.id, user_card_hash, identity_hash, portal_hash
    )
    assert await fake_redis.get(m6_cache_key) is None, (
        "M6 cache must not be written when prices came from inflight"
    )

    # Telemetry assertion — the structured log line is the only signal
    # to operators that a rec was built from a partial snapshot.
    # provisional-resolve renamed the log key to ``recommendation_skip_cache_write``
    # since the same skip-write branch now covers both inflight + provisional.
    assert any(
        "recommendation_skip_cache_write" in r.getMessage()
        and "inflight=True" in r.getMessage()
        for r in caplog.records
    ), [r.getMessage() for r in caplog.records]

    # Second call re-computes (no cache to hit) — the regression we're
    # protecting against is "second call returns the stale provisional".
    second = await service.get_recommendation(MOCK_USER_ID, product.id)
    assert second.cached is False


async def test_recommendation_skips_cache_write_for_provisional_product(
    db_session, fake_redis, caplog, monkeypatch
):
    """A provisional Product (persisted by /resolve-from-search when no UPC
    could be derived) MUST NOT be cached in M6's 15-min slot. The
    relevance picture for a provisional row can shift the moment a real
    UPC backfill upgrades it to canonical, and a cached snapshot would
    mask the upgrade for up to 15 min.

    Mocks ``price_service.get_prices`` to return a clean (non-inflight)
    payload so the only reason the cache write is skipped is the
    provisional marker — isolates the new branch from the existing
    inflight skip.
    """
    import logging

    await _seed_user(db_session)
    await _seed_retailer(db_session, "amazon")
    await _seed_retailer(db_session, "best_buy")
    await _seed_health(db_session, "amazon")
    await _seed_health(db_session, "best_buy")

    product = Product(
        upc=None,
        name="Steam Deck OLED 1TB Limited Edition",
        brand="Valve",
        source="provisional",
        source_raw={
            "provisional": True,
            "search_query": "Steam Deck OLED 1TB Limited Edition",
        },
    )
    db_session.add(product)
    await db_session.flush()

    # Stand in for a healthy 2-retailer canonical fetch — no `_inflight`
    # marker, so the skip-write must trigger purely on the provisional
    # tag the recommendation service sets in `_gather_inputs`.
    mock_payload = {
        "product_id": str(product.id),
        "product_name": product.name,
        "prices": [
            _wire_price("amazon", 100.0), _wire_price("best_buy", 110.0)
        ],
        "retailer_results": [],
        "total_retailers": 2,
        "retailers_succeeded": 2,
        "retailers_failed": 0,
        "cached": False,
        "fetched_at": datetime.now(UTC).isoformat(),
    }

    async def _stub_get_prices(*args, **kwargs):
        return dict(mock_payload)

    from modules.m2_prices.service import PriceAggregationService
    monkeypatch.setattr(
        PriceAggregationService, "get_prices", _stub_get_prices
    )

    caplog.set_level(logging.INFO, logger="barkain.m6")

    service = RecommendationService(db_session, fake_redis)
    rec = await service.get_recommendation(MOCK_USER_ID, product.id)
    assert rec.cached is False

    # CRITICAL: neither cache key shape (bare or scoped) was written.
    from modules.m6_recommend.service import _portal_membership_hash
    user_card_hash = await service._user_card_hash(MOCK_USER_ID)
    identity_hash = await service._identity_flag_hash(MOCK_USER_ID)
    portal_hash = _portal_membership_hash({})
    bare_key = service._cache_key(
        MOCK_USER_ID, product.id, user_card_hash, identity_hash, portal_hash
    )
    scoped_key = service._cache_key(
        MOCK_USER_ID, product.id, user_card_hash, identity_hash, portal_hash,
        query_override=product.name,
    )
    assert await fake_redis.get(bare_key) is None
    assert await fake_redis.get(scoped_key) is None, (
        "M6 cache must not be written for provisional rows"
    )

    # Telemetry: skip-write log line carries provisional=True (the new
    # signal) AND inflight=False (so operators can attribute correctly).
    assert any(
        "recommendation_skip_cache_write" in r.getMessage()
        and "provisional=True" in r.getMessage()
        and "inflight=False" in r.getMessage()
        for r in caplog.records
    ), [r.getMessage() for r in caplog.records]


async def test_recommendation_writes_cache_when_prices_came_from_canonical(
    db_session, fake_redis
):
    """Counter-test: a normal canonical-cache rec MUST still write to
    M6's cache. Otherwise the inflight-skip wiring accidentally disables
    all caching."""
    import json

    await _seed_user(db_session)
    await _seed_retailer(db_session, "amazon")
    await _seed_retailer(db_session, "best_buy")
    await _seed_health(db_session, "amazon")
    await _seed_health(db_session, "best_buy")
    product = await _seed_product(db_session)
    await db_session.flush()

    payload = {
        "product_id": str(product.id),
        "product_name": product.name,
        "prices": [_wire_price("amazon", 100.0), _wire_price("best_buy", 110.0)],
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
    assert rec.cached is False

    # Cache key MUST exist.
    from modules.m6_recommend.service import _portal_membership_hash
    user_card_hash = await service._user_card_hash(MOCK_USER_ID)
    identity_hash = await service._identity_flag_hash(MOCK_USER_ID)
    portal_hash = _portal_membership_hash({})
    m6_cache_key = service._cache_key(
        MOCK_USER_ID, product.id, user_card_hash, identity_hash, portal_hash
    )
    assert await fake_redis.get(m6_cache_key) is not None, (
        "canonical-source recs must still cache (regression guard for inflight-cache-1-L1)"
    )


# MARK: - query_override scope plumbing (inflight-cache-1-L2)


async def test_recommendation_with_query_override_reads_scoped_inflight(
    db_session, fake_redis
):
    """When iOS opens the SSE stream with a `query=Apple iPhone` bare-name
    override and then fires `/recommend?query_override=Apple iPhone`
    mid-stream, M6 must read the SCOPED inflight bucket — not the bare
    bucket. Pre-fix, M6 ignored query_override and read the bare bucket
    which would be empty (the optimistic-tap stream wrote SCOPED), causing
    a fall-through to dispatch and double the scrapers."""
    from modules.m2_prices.service import PriceAggregationService

    await _seed_user(db_session)
    await _seed_retailer(db_session, "amazon")
    await _seed_retailer(db_session, "best_buy")
    await _seed_health(db_session, "amazon")
    await _seed_health(db_session, "best_buy")
    product = await _seed_product(db_session)
    await db_session.flush()

    price_service = PriceAggregationService(db=db_session, redis=fake_redis)
    # Two distinct inflight buckets for the same product, one bare and one
    # scoped. M6 must pick the scoped one when query_override is passed.
    await price_service._write_inflight(
        product.id,
        "amazon",
        price_payload=_wire_price("amazon", 999.99),  # bare-bucket price
        result={"retailer_id": "amazon", "retailer_name": "Amazon", "status": "success"},
    )
    await price_service._write_inflight(
        product.id,
        "best_buy",
        price_payload=_wire_price("best_buy", 999.99),  # bare-bucket price
        result={"retailer_id": "best_buy", "retailer_name": "Best Buy", "status": "success"},
    )
    await price_service._write_inflight(
        product.id,
        "amazon",
        price_payload=_wire_price("amazon", 100.0),  # scoped-bucket price
        result={"retailer_id": "amazon", "retailer_name": "Amazon", "status": "success"},
        query_override="Apple iPhone",
    )
    await price_service._write_inflight(
        product.id,
        "best_buy",
        price_payload=_wire_price("best_buy", 110.0),  # scoped-bucket price
        result={"retailer_id": "best_buy", "retailer_name": "Best Buy", "status": "success"},
        query_override="Apple iPhone",
    )

    service = RecommendationService(db_session, fake_redis)
    rec = await service.get_recommendation(
        MOCK_USER_ID, product.id, query_override="Apple iPhone"
    )

    # Winner price MUST come from scoped bucket ($100), not bare ($999.99).
    assert rec.winner.base_price == 100.0, (
        f"Expected scoped-bucket price $100 but got {rec.winner.base_price}"
    )


async def test_recommendation_cache_isolated_by_query_override_scope(
    db_session, fake_redis
):
    """Same user + product + state, but different query_override → DIFFERENT
    cache keys. The two recs can legitimately differ because their inflight
    buckets differ; sharing a cache key would let one scope serve the other.

    This is the L2 analog of the v5 portal-membership cache-key bump."""
    import json

    await _seed_user(db_session)
    await _seed_retailer(db_session, "amazon")
    await _seed_retailer(db_session, "best_buy")
    await _seed_health(db_session, "amazon")
    await _seed_health(db_session, "best_buy")
    product = await _seed_product(db_session)
    await db_session.flush()

    # Bare canonical Redis cache — drives the no-override get_recommendation.
    bare_payload = {
        "product_id": str(product.id),
        "product_name": product.name,
        "prices": [_wire_price("amazon", 100.0), _wire_price("best_buy", 110.0)],
        "retailer_results": [],
        "total_retailers": 2,
        "retailers_succeeded": 2,
        "retailers_failed": 0,
        "cached": True,
        "fetched_at": datetime.now(UTC).isoformat(),
    }
    await fake_redis.setex(
        f"prices:product:{product.id}", 600, json.dumps(bare_payload)
    )

    # Scoped Redis cache for the override path.
    from modules.m2_prices.service import _query_scope_digest
    scoped_key = (
        f"prices:product:{product.id}:q:{_query_scope_digest('Apple iPhone')}"
    )
    scoped_payload = {
        **bare_payload,
        "prices": [_wire_price("amazon", 200.0), _wire_price("best_buy", 210.0)],
    }
    await fake_redis.setex(scoped_key, 600, json.dumps(scoped_payload))

    service = RecommendationService(db_session, fake_redis)
    bare_rec = await service.get_recommendation(MOCK_USER_ID, product.id)
    scoped_rec = await service.get_recommendation(
        MOCK_USER_ID, product.id, query_override="Apple iPhone"
    )

    assert bare_rec.winner.base_price == 100.0
    assert scoped_rec.winner.base_price == 200.0

    # Cache key isolation: each rec should have written to its OWN key.
    user_card_hash = await service._user_card_hash(MOCK_USER_ID)
    identity_hash = await service._identity_flag_hash(MOCK_USER_ID)
    from modules.m6_recommend.service import _portal_membership_hash
    portal_hash = _portal_membership_hash({})
    bare_cache_key = service._cache_key(
        MOCK_USER_ID, product.id, user_card_hash, identity_hash, portal_hash
    )
    scoped_cache_key = service._cache_key(
        MOCK_USER_ID,
        product.id,
        user_card_hash,
        identity_hash,
        portal_hash,
        query_override="Apple iPhone",
    )
    assert bare_cache_key != scoped_cache_key, (
        "query_override must produce a distinct cache key"
    )
    assert await fake_redis.get(bare_cache_key) is not None
    assert await fake_redis.get(scoped_cache_key) is not None

    # Re-call each path — both should hit their respective caches.
    bare_again = await service.get_recommendation(MOCK_USER_ID, product.id)
    scoped_again = await service.get_recommendation(
        MOCK_USER_ID, product.id, query_override="Apple iPhone"
    )
    assert bare_again.cached is True
    assert scoped_again.cached is True


async def test_recommendation_no_override_unchanged_by_l2_wiring(
    db_session, fake_redis
):
    """Regression guard: the existing barcode + SKU-search flow (no
    query_override) must continue to read the bare bucket and write to
    the bare cache key — same shape as before L2."""
    import json

    await _seed_user(db_session)
    await _seed_retailer(db_session, "amazon")
    await _seed_retailer(db_session, "best_buy")
    await _seed_health(db_session, "amazon")
    await _seed_health(db_session, "best_buy")
    product = await _seed_product(db_session)
    await db_session.flush()

    payload = {
        "product_id": str(product.id),
        "product_name": product.name,
        "prices": [_wire_price("amazon", 100.0), _wire_price("best_buy", 110.0)],
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
    assert rec.cached is False

    # Cache key MUST be the bare shape (no `:q...` segment) so existing
    # v5 entries stay reachable.
    user_card_hash = await service._user_card_hash(MOCK_USER_ID)
    identity_hash = await service._identity_flag_hash(MOCK_USER_ID)
    from modules.m6_recommend.service import _portal_membership_hash
    portal_hash = _portal_membership_hash({})
    expected_key = (
        f"recommend:user:{MOCK_USER_ID}:product:{product.id}"
        f":c{user_card_hash}:i{identity_hash}:p{portal_hash}:v5"
    )
    assert await fake_redis.get(expected_key) is not None, (
        "no-override callers must continue to read/write the bare v5 key"
    )


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
