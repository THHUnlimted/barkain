"""Tests for M5 Identity Profile — endpoints + service + discount matching."""

import time
from decimal import Decimal

from sqlalchemy import text

from app.core_models import Retailer
from modules.m1_product.models import Product
from modules.m2_prices.models import Price
from modules.m5_identity.models import DiscountProgram, UserDiscountProfile
from modules.m5_identity.service import IdentityService
from tests.conftest import MOCK_USER_ID


# MARK: - Helpers


async def _seed_user(db_session, user_id: str = MOCK_USER_ID) -> None:
    """Insert a users row — required for UserDiscountProfile FK."""
    await db_session.execute(
        text("INSERT INTO users (id) VALUES (:id) ON CONFLICT (id) DO NOTHING"),
        {"id": user_id},
    )
    await db_session.flush()


async def _seed_retailer(
    db_session,
    retailer_id: str,
    display_name: str | None = None,
    extraction_method: str = "agent_browser",
) -> Retailer:
    retailer = Retailer(
        id=retailer_id,
        display_name=display_name or retailer_id.replace("_", " ").title(),
        base_url=f"https://www.{retailer_id}.com",
        extraction_method=extraction_method,
        supports_identity=True,
    )
    db_session.add(retailer)
    await db_session.flush()
    return retailer


async def _seed_program(
    db_session,
    retailer_id: str,
    program_name: str,
    eligibility_type: str,
    *,
    discount_type: str = "percentage",
    discount_value: float | None = 10.0,
    discount_max_value: float | None = None,
    verification_method: str | None = "id_me",
    verification_url: str | None = "https://example.com/verify",
    url: str | None = "https://example.com/program",
    program_type: str = "identity",
    is_active: bool = True,
) -> DiscountProgram:
    program = DiscountProgram(
        retailer_id=retailer_id,
        program_name=program_name,
        program_type=program_type,
        eligibility_type=eligibility_type,
        discount_type=discount_type,
        discount_value=Decimal(str(discount_value)) if discount_value is not None else None,
        discount_max_value=(
            Decimal(str(discount_max_value)) if discount_max_value is not None else None
        ),
        verification_method=verification_method,
        verification_url=verification_url,
        url=url,
        is_active=is_active,
    )
    db_session.add(program)
    await db_session.flush()
    return program


async def _seed_product_with_price(
    db_session,
    retailer_id: str,
    price: float,
    *,
    name: str = "Test Product",
) -> Product:
    product = Product(
        name=name,
        brand="Test",
        upc="000000000000",
        category="test",
        source="test",
    )
    db_session.add(product)
    await db_session.flush()

    price_row = Price(
        product_id=product.id,
        retailer_id=retailer_id,
        price=Decimal(str(price)),
        condition="new",
        is_available=True,
    )
    db_session.add(price_row)
    await db_session.flush()
    return product


# MARK: - Profile CRUD (endpoint-level)


async def test_get_profile_returns_default_if_none(client, db_session):
    """GET /profile auto-creates an empty profile when none exists."""
    resp = await client.get("/api/v1/identity/profile")
    assert resp.status_code == 200
    data = resp.json()
    assert data["user_id"] == MOCK_USER_ID
    assert data["is_military"] is False
    assert data["is_student"] is False
    assert data["is_government"] is False


async def test_get_profile_existing(client, db_session):
    """GET /profile returns a pre-seeded profile faithfully."""
    await _seed_user(db_session)
    profile = UserDiscountProfile(
        user_id=MOCK_USER_ID,
        is_military=True,
        is_veteran=True,
    )
    db_session.add(profile)
    await db_session.flush()

    resp = await client.get("/api/v1/identity/profile")
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_military"] is True
    assert data["is_veteran"] is True
    assert data["is_student"] is False


async def test_create_profile_via_post(client, db_session):
    """POST /profile creates a new profile with the requested flags."""
    resp = await client.post(
        "/api/v1/identity/profile",
        json={"is_military": True, "is_student": True, "id_me_verified": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_military"] is True
    assert data["is_student"] is True
    assert data["id_me_verified"] is True
    assert data["is_veteran"] is False  # unset fields default False


async def test_update_profile_is_full_replace(client, db_session):
    """POST with a partial body clears unmentioned flags (full-replace semantics)."""
    # Start: is_military=True, is_student=True
    await client.post(
        "/api/v1/identity/profile",
        json={"is_military": True, "is_student": True},
    )
    # Replace with just is_student=True
    resp = await client.post(
        "/api/v1/identity/profile",
        json={"is_student": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_military"] is False, "is_military should be cleared by full replace"
    assert data["is_student"] is True


# MARK: - Discount Matching (service-level)


async def test_eligible_discounts_no_flags(db_session):
    """User with all flags false → empty discount list."""
    await _seed_user(db_session)
    await _seed_retailer(db_session, "samsung_direct")
    await _seed_program(
        db_session, "samsung_direct", "Samsung Offer Program", "military",
        discount_value=30,
    )

    service = IdentityService(db_session)
    profile = UserDiscountProfile(user_id=MOCK_USER_ID)  # all false
    db_session.add(profile)
    await db_session.flush()

    resp = await service.get_eligible_discounts(MOCK_USER_ID, product_id=None)
    assert resp.eligible_discounts == []
    assert resp.identity_groups_active == []


async def test_eligible_discounts_military_matches_brands(db_session):
    """is_military=True surfaces Samsung, Apple, HP military programs."""
    await _seed_user(db_session)
    await _seed_retailer(db_session, "samsung_direct")
    await _seed_retailer(db_session, "apple_direct")
    await _seed_retailer(db_session, "hp_direct")
    await _seed_program(db_session, "samsung_direct", "Samsung Offer Program", "military", discount_value=30)
    await _seed_program(db_session, "apple_direct", "Military Discount", "military", discount_value=10)
    await _seed_program(db_session, "hp_direct", "Frontline Heroes", "military", discount_value=40)

    profile = UserDiscountProfile(user_id=MOCK_USER_ID, is_military=True)
    db_session.add(profile)
    await db_session.flush()

    service = IdentityService(db_session)
    resp = await service.get_eligible_discounts(MOCK_USER_ID, product_id=None)

    retailers = {d.retailer_id for d in resp.eligible_discounts}
    assert retailers == {"samsung_direct", "apple_direct", "hp_direct"}
    assert "military" in resp.identity_groups_active


async def test_eligible_discounts_multi_group_union(db_session):
    """is_military + is_student returns the union of both groups, deduped."""
    await _seed_user(db_session)
    await _seed_retailer(db_session, "samsung_direct")
    await _seed_retailer(db_session, "apple_direct")
    # Samsung covers both (seeded as two rows)
    await _seed_program(db_session, "samsung_direct", "Samsung Offer Program", "military", discount_value=30)
    await _seed_program(db_session, "samsung_direct", "Samsung Offer Program", "student", discount_value=30)
    await _seed_program(db_session, "apple_direct", "Military Discount", "military", discount_value=10)
    await _seed_program(db_session, "apple_direct", "Education Pricing", "student", discount_value=5)

    profile = UserDiscountProfile(user_id=MOCK_USER_ID, is_military=True, is_student=True)
    db_session.add(profile)
    await db_session.flush()

    service = IdentityService(db_session)
    resp = await service.get_eligible_discounts(MOCK_USER_ID, product_id=None)

    # 3 unique programs: Samsung (dedup), Apple Military, Apple Education
    names = {(d.retailer_id, d.program_name) for d in resp.eligible_discounts}
    assert names == {
        ("samsung_direct", "Samsung Offer Program"),
        ("apple_direct", "Military Discount"),
        ("apple_direct", "Education Pricing"),
    }
    assert set(resp.identity_groups_active) == {"military", "student"}


async def test_eligible_discounts_dedup_samsung(db_session):
    """Samsung seeded across 8 eligibility types surfaces as ONE card per user."""
    await _seed_user(db_session)
    await _seed_retailer(db_session, "samsung_direct")
    for etype in ("military", "veteran", "first_responder", "student", "teacher", "nurse", "healthcare_worker", "government"):
        await _seed_program(
            db_session,
            "samsung_direct",
            "Samsung Offer Program",
            etype,
            discount_value=30,
        )

    # User matches 3 of the 8 types
    profile = UserDiscountProfile(
        user_id=MOCK_USER_ID,
        is_military=True,
        is_student=True,
        is_nurse=True,
    )
    db_session.add(profile)
    await db_session.flush()

    service = IdentityService(db_session)
    resp = await service.get_eligible_discounts(MOCK_USER_ID, product_id=None)

    samsung_cards = [
        d for d in resp.eligible_discounts if d.retailer_id == "samsung_direct"
    ]
    assert len(samsung_cards) == 1, (
        f"Expected 1 Samsung card after dedup, got {len(samsung_cards)}"
    )


async def test_eligible_discounts_inactive_excluded(db_session):
    """Programs with is_active=false are never surfaced."""
    await _seed_user(db_session)
    await _seed_retailer(db_session, "samsung_direct")
    await _seed_program(
        db_session, "samsung_direct", "Active Program", "military", discount_value=30
    )
    await _seed_program(
        db_session,
        "samsung_direct",
        "Retired Program",
        "military",
        discount_value=50,
        is_active=False,
    )

    profile = UserDiscountProfile(user_id=MOCK_USER_ID, is_military=True)
    db_session.add(profile)
    await db_session.flush()

    service = IdentityService(db_session)
    resp = await service.get_eligible_discounts(MOCK_USER_ID, product_id=None)

    names = {d.program_name for d in resp.eligible_discounts}
    assert "Active Program" in names
    assert "Retired Program" not in names


# MARK: - Savings math


async def test_eligible_discounts_percentage_savings(db_session):
    """30% discount on $1500 best price → $450 savings."""
    await _seed_user(db_session)
    await _seed_retailer(db_session, "samsung_direct")
    await _seed_retailer(db_session, "walmart_test")
    product = await _seed_product_with_price(db_session, "walmart_test", 1500.00)
    await _seed_program(
        db_session, "samsung_direct", "Samsung Offer Program", "military", discount_value=30
    )

    profile = UserDiscountProfile(user_id=MOCK_USER_ID, is_military=True)
    db_session.add(profile)
    await db_session.flush()

    service = IdentityService(db_session)
    resp = await service.get_eligible_discounts(MOCK_USER_ID, product_id=product.id)

    assert len(resp.eligible_discounts) == 1
    assert resp.eligible_discounts[0].estimated_savings == 450.0


async def test_eligible_discounts_cap_applied(db_session):
    """10% of $10000 = $1000 but cap of $400 → capped at $400."""
    await _seed_user(db_session)
    await _seed_retailer(db_session, "home_depot_test")
    await _seed_retailer(db_session, "walmart_test")
    product = await _seed_product_with_price(db_session, "walmart_test", 10000.00)
    await _seed_program(
        db_session,
        "home_depot_test",
        "Military Discount",
        "military",
        discount_value=10,
        discount_max_value=400,
    )

    profile = UserDiscountProfile(user_id=MOCK_USER_ID, is_military=True)
    db_session.add(profile)
    await db_session.flush()

    service = IdentityService(db_session)
    resp = await service.get_eligible_discounts(MOCK_USER_ID, product_id=product.id)

    assert len(resp.eligible_discounts) == 1
    assert resp.eligible_discounts[0].estimated_savings == 400.0


async def test_eligible_discounts_fixed_amount(db_session):
    """fixed_amount discount returns discount_value regardless of best price."""
    await _seed_user(db_session)
    await _seed_retailer(db_session, "samsung_direct")
    await _seed_retailer(db_session, "walmart_test")
    product = await _seed_product_with_price(db_session, "walmart_test", 1500.00)
    await _seed_program(
        db_session,
        "samsung_direct",
        "$50 off coupon",
        "military",
        discount_type="fixed_amount",
        discount_value=50,
    )

    profile = UserDiscountProfile(user_id=MOCK_USER_ID, is_military=True)
    db_session.add(profile)
    await db_session.flush()

    service = IdentityService(db_session)
    resp = await service.get_eligible_discounts(MOCK_USER_ID, product_id=product.id)

    assert resp.eligible_discounts[0].estimated_savings == 50.0


async def test_eligible_discounts_no_product_id_no_savings(db_session):
    """Without product_id, estimated_savings is always null."""
    await _seed_user(db_session)
    await _seed_retailer(db_session, "samsung_direct")
    await _seed_program(
        db_session, "samsung_direct", "Samsung Offer Program", "military", discount_value=30
    )

    profile = UserDiscountProfile(user_id=MOCK_USER_ID, is_military=True)
    db_session.add(profile)
    await db_session.flush()

    service = IdentityService(db_session)
    resp = await service.get_eligible_discounts(MOCK_USER_ID, product_id=None)

    assert resp.eligible_discounts[0].estimated_savings is None


async def test_eligible_discounts_no_prices_no_savings(db_session):
    """If product exists but has no prices yet, estimated_savings is null."""
    await _seed_user(db_session)
    await _seed_retailer(db_session, "samsung_direct")
    product = Product(
        name="Unpriced Product", upc="111111111111", source="test"
    )
    db_session.add(product)
    await db_session.flush()
    await _seed_program(
        db_session, "samsung_direct", "Samsung Offer Program", "military", discount_value=30
    )

    profile = UserDiscountProfile(user_id=MOCK_USER_ID, is_military=True)
    db_session.add(profile)
    await db_session.flush()

    service = IdentityService(db_session)
    resp = await service.get_eligible_discounts(MOCK_USER_ID, product_id=product.id)

    assert resp.eligible_discounts[0].estimated_savings is None


# MARK: - /discounts endpoint


async def test_discounts_endpoint_returns_empty_for_new_user(client, db_session):
    """GET /discounts for a user with no profile returns an empty list."""
    resp = await client.get("/api/v1/identity/discounts")
    assert resp.status_code == 200
    data = resp.json()
    assert data["eligible_discounts"] == []
    assert data["identity_groups_active"] == []


async def test_discounts_endpoint_after_profile_update(client, db_session):
    """POST profile → GET discounts flows end-to-end through the API."""
    await _seed_retailer(db_session, "samsung_direct")
    await _seed_program(
        db_session, "samsung_direct", "Samsung Offer Program", "military", discount_value=30
    )

    post_resp = await client.post(
        "/api/v1/identity/profile", json={"is_military": True}
    )
    assert post_resp.status_code == 200

    get_resp = await client.get("/api/v1/identity/discounts")
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert len(data["eligible_discounts"]) == 1
    assert data["eligible_discounts"][0]["retailer_id"] == "samsung_direct"
    assert "military" in data["identity_groups_active"]


async def test_all_programs_endpoint(client, db_session):
    """GET /discounts/all returns only active programs."""
    await _seed_retailer(db_session, "samsung_direct")
    await _seed_retailer(db_session, "apple_direct")
    await _seed_program(
        db_session, "samsung_direct", "Active A", "military", discount_value=30
    )
    await _seed_program(
        db_session,
        "apple_direct",
        "Retired B",
        "military",
        discount_value=20,
        is_active=False,
    )

    resp = await client.get("/api/v1/identity/discounts/all")
    assert resp.status_code == 200
    names = {p["program_name"] for p in resp.json()}
    assert "Active A" in names
    assert "Retired B" not in names


# MARK: - Performance gate


async def test_discount_query_performance(db_session):
    """Median of 5 matching runs must complete in < 150ms (CI slack; 50ms local target)."""
    await _seed_user(db_session)
    # Seed 11 retailers and ~50 programs (similar scale to production)
    retailer_ids = [
        "samsung_direct",
        "apple_direct",
        "hp_direct",
        "dell_direct",
        "lenovo_direct",
        "microsoft_direct",
        "sony_direct",
        "lg_direct",
        "home_depot_test",
        "lowes_test",
        "amazon_test",
    ]
    for rid in retailer_ids:
        await _seed_retailer(db_session, rid)

    eligibility_types = [
        "military",
        "veteran",
        "student",
        "teacher",
        "first_responder",
        "nurse",
        "healthcare_worker",
        "senior",
        "government",
    ]
    for rid in retailer_ids:
        for etype in eligibility_types[:6]:  # 6 programs per retailer = 66 total
            await _seed_program(
                db_session,
                rid,
                f"Program {rid}",
                etype,
                discount_value=20,
            )

    profile = UserDiscountProfile(
        user_id=MOCK_USER_ID,
        is_military=True,
        is_student=True,
        is_teacher=True,
    )
    db_session.add(profile)
    await db_session.flush()

    service = IdentityService(db_session)

    timings: list[float] = []
    for _ in range(5):
        start = time.perf_counter()
        await service.get_eligible_discounts(MOCK_USER_ID, product_id=None)
        timings.append(time.perf_counter() - start)

    median = sorted(timings)[2]
    assert median < 0.15, (
        f"Median query time {median * 1000:.1f}ms exceeds 150ms CI bound "
        f"(target: 50ms local-dev)"
    )
