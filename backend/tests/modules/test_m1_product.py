"""Tests for M1 Product Resolution — POST /api/v1/products/resolve."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from modules.m1_product.models import Product

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
RESOLVE_URL = "/api/v1/products/resolve"
VALID_UPC = "027242923782"


# MARK: - Fixtures


@pytest.fixture
def gemini_fixture() -> dict:
    with open(FIXTURES_DIR / "gemini_upc_response.json") as f:
        return json.load(f)


@pytest.fixture
def upcitemdb_fixture() -> dict:
    with open(FIXTURES_DIR / "upcitemdb_response.json") as f:
        return json.load(f)


# MARK: - UPC Validation


@pytest.mark.asyncio
async def test_resolve_rejects_invalid_upc_too_short(client):
    """UPC with fewer than 12 digits returns 422."""
    response = await client.post(RESOLVE_URL, json={"upc": "12345"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_resolve_rejects_invalid_upc_non_numeric(client):
    """UPC with non-numeric characters returns 422."""
    response = await client.post(RESOLVE_URL, json={"upc": "01234567890A"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_resolve_rejects_missing_upc(client):
    """Request without 'upc' field returns 422."""
    response = await client.post(RESOLVE_URL, json={})
    assert response.status_code == 422


# MARK: - Validation envelope shape (sim-edge-case-fixes-v1)


@pytest.mark.asyncio
async def test_validation_422_uses_wrapped_envelope(client):
    """Pydantic 422s should match the canonical {detail:{error:{...}}} shape
    so iOS APIClient.decodeErrorDetail surfaces a friendly message instead
    of falling through to "Validation failed". Regression for sim Edge-Case
    Findings #1 and #5.
    """
    response = await client.post(RESOLVE_URL, json={"upc": "12345"})
    assert response.status_code == 422
    body = response.json()
    assert "detail" in body
    detail = body["detail"]
    # The wrapped envelope wraps a single `error` dict, not a list (which is
    # what FastAPI's default Pydantic 422 returns).
    assert isinstance(detail, dict)
    assert "error" in detail
    err = detail["error"]
    assert err["code"] == "VALIDATION_ERROR"
    assert isinstance(err.get("message"), str) and err["message"]
    # Structured per-field errors stay available under details for telemetry.
    assert isinstance(err.get("details"), dict)
    assert isinstance(err["details"].get("errors"), list)


# MARK: - Pattern-UPC guard (sim-edge-case-fixes-v1)


@pytest.mark.asyncio
async def test_resolve_rejects_pattern_upc_all_zeros_without_calling_gemini(
    client, db_session, fake_redis
):
    """`000000000000` short-circuits to 404 before Gemini is invoked.

    Regression for sim Edge-Case Finding #6 — Gemini hallucinated
    "ORGANIC BLUE CORN TORTILLA CHIPS" for this UPC and the result was
    persisted to PG. Cheaper to reject the obvious pattern up front.
    """
    with (
        patch(
            "modules.m1_product.service.gemini_generate_json",
            new_callable=AsyncMock,
        ) as mock_gemini,
        patch(
            "modules.m1_product.service.upcitemdb_lookup",
            new_callable=AsyncMock,
        ) as mock_upcitemdb,
    ):
        response = await client.post(RESOLVE_URL, json={"upc": "000000000000"})
    assert response.status_code == 404
    body = response.json()
    assert body["detail"]["error"]["code"] == "PRODUCT_NOT_FOUND"
    mock_gemini.assert_not_called()
    mock_upcitemdb.assert_not_called()


@pytest.mark.asyncio
async def test_resolve_rejects_pattern_upc_all_ones_without_calling_gemini(
    client, db_session, fake_redis
):
    """All-same-digit reject covers `111111111111` too (not just zeros)."""
    with (
        patch(
            "modules.m1_product.service.gemini_generate_json",
            new_callable=AsyncMock,
        ) as mock_gemini,
        patch(
            "modules.m1_product.service.upcitemdb_lookup",
            new_callable=AsyncMock,
        ) as mock_upcitemdb,
    ):
        response = await client.post(RESOLVE_URL, json={"upc": "111111111111"})
    assert response.status_code == 404
    mock_gemini.assert_not_called()
    mock_upcitemdb.assert_not_called()


# MARK: - Auth


@pytest.mark.asyncio
async def test_resolve_requires_auth(unauthed_client, without_demo_mode):
    """Request without auth returns 401."""
    response = await unauthed_client.post(
        RESOLVE_URL, json={"upc": VALID_UPC}
    )
    assert response.status_code == 401


# MARK: - Resolution Chain: Redis Cache Hit


@pytest.mark.asyncio
async def test_resolve_returns_product_from_redis_cache(
    client, db_session, fake_redis
):
    """When product is cached in Redis, returns it without hitting Gemini."""
    # Given: a product exists in DB and its ID is cached in Redis
    product = Product(
        upc=VALID_UPC,
        name="Sony WH-1000XM5 Wireless Noise Canceling Headphones",
        brand="Sony",
        category="Electronics",
        source="gemini",
    )
    db_session.add(product)
    await db_session.flush()

    await fake_redis.set(
        f"product:upc:{VALID_UPC}", str(product.id), ex=86400
    )

    # When: resolve is called
    response = await client.post(RESOLVE_URL, json={"upc": VALID_UPC})

    # Then: returns 200 with product data
    assert response.status_code == 200
    data = response.json()
    assert data["upc"] == VALID_UPC
    assert data["name"] == "Sony WH-1000XM5 Wireless Noise Canceling Headphones"


# MARK: - Resolution Chain: PostgreSQL Hit


@pytest.mark.asyncio
async def test_resolve_returns_product_from_postgres(
    client, db_session, fake_redis
):
    """When product exists in DB but not Redis, returns it and caches."""
    # Given: a product exists in DB, Redis is empty
    product = Product(
        upc=VALID_UPC,
        name="Sony WH-1000XM5 Wireless Noise Canceling Headphones",
        brand="Sony",
        category="Electronics",
        source="gemini",
    )
    db_session.add(product)
    await db_session.flush()

    # When: resolve is called
    response = await client.post(RESOLVE_URL, json={"upc": VALID_UPC})

    # Then: returns 200 and product is now cached in Redis
    assert response.status_code == 200
    cached = await fake_redis.get(f"product:upc:{VALID_UPC}")
    assert cached is not None


# MARK: - Resolution Chain: Gemini API


@pytest.mark.asyncio
async def test_resolve_calls_gemini_on_cache_miss(
    client, db_session, fake_redis, gemini_fixture
):
    """When Redis and DB are empty, calls Gemini and persists result."""
    with (
        patch(
            "modules.m1_product.service.gemini_generate_json",
            new_callable=AsyncMock,
            return_value=gemini_fixture,
        ) as mock_gemini,
        patch(
            "modules.m1_product.service.upcitemdb_lookup",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        response = await client.post(RESOLVE_URL, json={"upc": VALID_UPC})

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == gemini_fixture["device_name"]
    assert data["source"] == "gemini_upc"
    mock_gemini.assert_called_once()


# MARK: - Resolution Chain: UPCitemdb Fallback


@pytest.mark.asyncio
async def test_resolve_falls_back_to_upcitemdb(
    client, db_session, fake_redis, upcitemdb_fixture
):
    """When Gemini fails, falls back to UPCitemdb."""
    upcitemdb_product = {
        "name": upcitemdb_fixture["items"][0]["title"],
        "brand": upcitemdb_fixture["items"][0]["brand"],
        "category": upcitemdb_fixture["items"][0]["category"],
        "description": upcitemdb_fixture["items"][0]["description"],
        "asin": upcitemdb_fixture["items"][0]["asin"],
        "image_url": upcitemdb_fixture["items"][0]["images"][0],
    }
    with (
        patch(
            "modules.m1_product.service.gemini_generate_json",
            new_callable=AsyncMock,
            side_effect=Exception("Gemini API error"),
        ),
        patch(
            "modules.m1_product.service.upcitemdb_lookup",
            new_callable=AsyncMock,
            return_value=upcitemdb_product,
        ),
    ):
        response = await client.post(RESOLVE_URL, json={"upc": VALID_UPC})

    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "upcitemdb"


# MARK: - Resolution Chain: 404


@pytest.mark.asyncio
async def test_resolve_returns_404_when_all_sources_fail(
    client, db_session, fake_redis
):
    """When all sources fail, returns 404 with PRODUCT_NOT_FOUND error."""
    with (
        patch(
            "modules.m1_product.service.gemini_generate_json",
            new_callable=AsyncMock,
            return_value={"error": "unknown_upc"},
        ),
        patch(
            "modules.m1_product.service.upcitemdb_lookup",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        response = await client.post(RESOLVE_URL, json={"upc": VALID_UPC})

    assert response.status_code == 404
    data = response.json()
    assert data["detail"]["error"]["code"] == "PRODUCT_NOT_FOUND"


# MARK: - Response Shape


@pytest.mark.asyncio
async def test_resolve_response_contains_required_fields(
    client, db_session, fake_redis, gemini_fixture
):
    """Response includes all expected fields."""
    with (
        patch(
            "modules.m1_product.service.gemini_generate_json",
            new_callable=AsyncMock,
            return_value=gemini_fixture,
        ),
        patch(
            "modules.m1_product.service.upcitemdb_lookup",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        response = await client.post(RESOLVE_URL, json={"upc": VALID_UPC})

    assert response.status_code == 200
    data = response.json()
    required_fields = {
        "id", "upc", "name", "brand", "category",
        "source", "confidence", "created_at", "updated_at",
    }
    assert required_fields.issubset(data.keys())


# MARK: - 13-digit EAN


@pytest.mark.asyncio
async def test_resolve_accepts_13_digit_ean(
    client, db_session, fake_redis, gemini_fixture
):
    """13-digit EAN barcode is accepted."""
    with (
        patch(
            "modules.m1_product.service.gemini_generate_json",
            new_callable=AsyncMock,
            return_value=gemini_fixture,
        ),
        patch(
            "modules.m1_product.service.upcitemdb_lookup",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        response = await client.post(
            RESOLVE_URL, json={"upc": "0027242923782"}
        )

    assert response.status_code == 200


# MARK: - Idempotency


@pytest.mark.asyncio
async def test_resolve_same_upc_twice_uses_cache(
    client, db_session, fake_redis, gemini_fixture
):
    """Second resolve for same UPC uses cached result, not Gemini."""
    with (
        patch(
            "modules.m1_product.service.gemini_generate_json",
            new_callable=AsyncMock,
            return_value=gemini_fixture,
        ) as mock_gemini,
        patch(
            "modules.m1_product.service.upcitemdb_lookup",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        # First call — hits Gemini
        response1 = await client.post(RESOLVE_URL, json={"upc": VALID_UPC})
        assert response1.status_code == 200

        # Second call — should use Redis cache
        response2 = await client.post(RESOLVE_URL, json={"upc": VALID_UPC})
        assert response2.status_code == 200

    # Gemini should only have been called once
    assert mock_gemini.call_count == 1

    # Both responses should return the same product
    assert response1.json()["id"] == response2.json()["id"]


# MARK: - Gemini null retry (Pre-Fix 1.3)


@pytest.mark.asyncio
async def test_gemini_null_retry_then_success(client, db_session, fake_redis):
    """Given Gemini returns null on first attempt, retry succeeds on second."""
    null_response = {"device_name": None, "model": None}
    success_response = {"device_name": "Sony WH-1000XM5 Wireless Headphones", "model": "WH-1000XM5"}

    with (
        patch(
            "modules.m1_product.service.gemini_generate_json",
            new_callable=AsyncMock,
            side_effect=[null_response, success_response],
        ) as mock_gemini,
        patch(
            "modules.m1_product.service.upcitemdb_lookup",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        response = await client.post(RESOLVE_URL, json={"upc": "887276789880"})
        assert response.status_code == 200
        data = response.json()
        assert "Sony" in data["name"]
        # Called twice: initial + retry
        assert mock_gemini.call_count == 2


@pytest.mark.asyncio
async def test_gemini_null_retry_both_null_falls_to_upcitemdb(
    client, db_session, fake_redis
):
    """Given Gemini returns null twice, falls through to UPCitemdb."""
    null_response = {"device_name": None, "model": None}
    upcitemdb_result = {
        "name": "Sony WH-1000XM5 Wireless Noise Canceling Headphones",
        "brand": "Sony",
        "category": "Electronics > Audio > Headphones",
        "description": "Premium wireless noise canceling headphones.",
        "asin": "B09XS7JWHH",
        "image_url": "https://example.com/image.jpg",
    }

    with (
        patch(
            "modules.m1_product.service.gemini_generate_json",
            new_callable=AsyncMock,
            side_effect=[null_response, null_response],
        ),
        patch(
            "modules.m1_product.service.upcitemdb_lookup",
            new_callable=AsyncMock,
            return_value=upcitemdb_result,
        ),
    ):
        response = await client.post(RESOLVE_URL, json={"upc": "887276789880"})
        assert response.status_code == 200
        assert "Sony" in response.json()["name"]


# MARK: - Cross-Validation (Step 2b)


CROSS_UPC = "194253397953"


@pytest.mark.asyncio
async def test_cross_validate_both_agree(client, db_session, fake_redis):
    """When Gemini and UPCitemdb agree on brand, Gemini name wins with confidence=1.0."""
    gemini_response = {
        "device_name": "Sony WH-1000XM5 Wireless Headphones (WH1000XM5/B)",
        "model": "WH-1000XM5",
    }
    upcitemdb_result = {
        "name": "Sony WH-1000XM5 Wireless Noise Canceling Headphones",
        "brand": "Sony",
        "category": "Electronics > Audio > Headphones",
        "description": "Premium noise canceling headphones.",
        "asin": "B09XS7JWHH",
        "image_url": "https://example.com/image.jpg",
    }

    with (
        patch(
            "modules.m1_product.service.gemini_generate_json",
            new_callable=AsyncMock,
            return_value=gemini_response,
        ),
        patch(
            "modules.m1_product.service.upcitemdb_lookup",
            new_callable=AsyncMock,
            return_value=upcitemdb_result,
        ),
    ):
        response = await client.post(RESOLVE_URL, json={"upc": CROSS_UPC})

    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "gemini_validated"
    assert data["confidence"] == 1.0
    assert "WH-1000XM5" in data["name"]
    assert data["brand"] == "Sony"


@pytest.mark.asyncio
async def test_cross_validate_brand_mismatch(client, db_session, fake_redis):
    """When Gemini and UPCitemdb disagree on brand, UPCitemdb wins with confidence=0.5."""
    gemini_response = {
        "device_name": "Energizer CR2032 Lithium Battery Pack",
        "model": "CR2032",
    }
    upcitemdb_result = {
        "name": "Sony WH-1000XM5 Wireless Noise Canceling Headphones",
        "brand": "Sony",
        "category": "Electronics > Audio > Headphones",
        "description": "Premium noise canceling headphones.",
        "asin": "B09XS7JWHH",
        "image_url": "https://example.com/image.jpg",
    }

    with (
        patch(
            "modules.m1_product.service.gemini_generate_json",
            new_callable=AsyncMock,
            return_value=gemini_response,
        ),
        patch(
            "modules.m1_product.service.upcitemdb_lookup",
            new_callable=AsyncMock,
            return_value=upcitemdb_result,
        ),
    ):
        response = await client.post(RESOLVE_URL, json={"upc": CROSS_UPC})

    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "upcitemdb_override"
    assert data["confidence"] == 0.5
    assert data["brand"] == "Sony"


@pytest.mark.asyncio
async def test_cross_validate_gemini_only(client, db_session, fake_redis):
    """When UPCitemdb returns nothing, Gemini wins with confidence=0.7."""
    gemini_response = {
        "device_name": "Sony WH-1000XM5 Wireless Headphones",
        "model": "WH-1000XM5",
    }

    with (
        patch(
            "modules.m1_product.service.gemini_generate_json",
            new_callable=AsyncMock,
            return_value=gemini_response,
        ),
        patch(
            "modules.m1_product.service.upcitemdb_lookup",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        response = await client.post(RESOLVE_URL, json={"upc": CROSS_UPC})

    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "gemini_upc"
    assert data["confidence"] == 0.7


@pytest.mark.asyncio
async def test_cross_validate_upcitemdb_only(client, db_session, fake_redis):
    """When Gemini fails, UPCitemdb wins with confidence=0.3."""
    upcitemdb_result = {
        "name": "Sony WH-1000XM5 Wireless Noise Canceling Headphones",
        "brand": "Sony",
        "category": "Electronics > Audio > Headphones",
        "description": "Premium noise canceling headphones.",
        "asin": "B09XS7JWHH",
        "image_url": "https://example.com/image.jpg",
    }

    with (
        patch(
            "modules.m1_product.service.gemini_generate_json",
            new_callable=AsyncMock,
            side_effect=Exception("Gemini API error"),
        ),
        patch(
            "modules.m1_product.service.upcitemdb_lookup",
            new_callable=AsyncMock,
            return_value=upcitemdb_result,
        ),
    ):
        response = await client.post(RESOLVE_URL, json={"upc": CROSS_UPC})

    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "upcitemdb"
    assert data["confidence"] == 0.3


@pytest.mark.asyncio
async def test_cross_validate_both_fail(client, db_session, fake_redis):
    """When both sources fail, returns 404."""
    with (
        patch(
            "modules.m1_product.service.gemini_generate_json",
            new_callable=AsyncMock,
            return_value={"device_name": None, "model": None},
        ),
        patch(
            "modules.m1_product.service.upcitemdb_lookup",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        response = await client.post(RESOLVE_URL, json={"upc": CROSS_UPC})

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_redis_cache_skips_cross_validation(
    client, db_session, fake_redis
):
    """Redis cache hit skips both Gemini and UPCitemdb calls entirely."""
    product = Product(
        upc=CROSS_UPC,
        name="Sony WH-1000XM5",
        brand="Sony",
        source="gemini_validated",
        source_raw={"confidence": 1.0},
    )
    db_session.add(product)
    await db_session.flush()
    await fake_redis.set(f"product:upc:{CROSS_UPC}", str(product.id), ex=86400)

    with (
        patch(
            "modules.m1_product.service.gemini_generate_json",
            new_callable=AsyncMock,
        ) as mock_gemini,
        patch(
            "modules.m1_product.service.upcitemdb_lookup",
            new_callable=AsyncMock,
        ) as mock_upcitemdb,
    ):
        response = await client.post(RESOLVE_URL, json={"upc": CROSS_UPC})

    assert response.status_code == 200
    data = response.json()
    assert data["confidence"] == 1.0
    mock_gemini.assert_not_called()
    mock_upcitemdb.assert_not_called()


# MARK: - Gemini model field (Step 2b-final)


@pytest.mark.asyncio
async def test_resolve_exposes_gemini_model_field(client, db_session, fake_redis):
    """When Gemini returns a model field, it is stored in source_raw and exposed on the response."""
    gemini_response = {
        "device_name": "Sony WH-1000XM5 Wireless Noise Canceling Headphones (WH1000XM5/B)",
        "model": "WH-1000XM5",
    }
    upcitemdb_result = {
        "name": "Sony WH-1000XM5 Wireless Noise Canceling Headphones",
        "brand": "Sony",
        "category": "Electronics > Audio > Headphones",
        "description": "Premium noise canceling headphones.",
        "asin": "B09XS7JWHH",
        "image_url": "https://example.com/image.jpg",
    }

    with (
        patch(
            "modules.m1_product.service.gemini_generate_json",
            new_callable=AsyncMock,
            return_value=gemini_response,
        ),
        patch(
            "modules.m1_product.service.upcitemdb_lookup",
            new_callable=AsyncMock,
            return_value=upcitemdb_result,
        ),
    ):
        response = await client.post(RESOLVE_URL, json={"upc": CROSS_UPC})

    assert response.status_code == 200
    data = response.json()
    assert data["model"] == "WH-1000XM5"
    assert data["source"] == "gemini_validated"

    # Verify the DB row actually persisted gemini_model in source_raw
    from sqlalchemy import select

    from modules.m1_product.models import Product as ProductModel

    db_row = (
        await db_session.execute(
            select(ProductModel).where(ProductModel.upc == CROSS_UPC)
        )
    ).scalar_one()
    assert db_row.source_raw is not None
    assert db_row.source_raw.get("gemini_model") == "WH-1000XM5"
    assert db_row.model == "WH-1000XM5"  # @property reads source_raw.gemini_model


@pytest.mark.asyncio
async def test_resolve_handles_null_gemini_model(client, db_session, fake_redis):
    """When Gemini returns model: null, resolution still succeeds and model is None in response."""
    gemini_response = {
        "device_name": "Sony WH-1000XM5 Wireless Headphones",
        "model": None,
    }

    with (
        patch(
            "modules.m1_product.service.gemini_generate_json",
            new_callable=AsyncMock,
            return_value=gemini_response,
        ),
        patch(
            "modules.m1_product.service.upcitemdb_lookup",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        response = await client.post(RESOLVE_URL, json={"upc": CROSS_UPC})

    assert response.status_code == 200
    data = response.json()
    assert data["model"] is None
    assert data["name"] == "Sony WH-1000XM5 Wireless Headphones"
    assert data["source"] == "gemini_upc"


# MARK: - Serper-then-grounded wire-up (vendor-migrate-1)


@pytest.mark.asyncio
async def test_resolve_uses_serper_when_serper_returns_value(
    client, db_session, fake_redis
):
    """When ``resolve_via_serper`` returns a result, the grounded path is
    NOT called — Serper-then-grounded short-circuits on Serper success.

    This is the load-bearing latency win: the grounded path takes ~3s p50,
    Serper synthesis takes ~1.6s p50. If a future change accidentally
    calls grounded anyway, the latency win evaporates without anyone
    noticing for weeks.
    """
    serper_result = {
        "name": "Apple iPad Air 13-inch (M4) Wi-Fi 128GB",
        "gemini_model": "MV2C3LL/A",
    }

    with (
        patch(
            "modules.m1_product.service.resolve_via_serper",
            new_callable=AsyncMock,
            return_value=serper_result,
        ),
        patch(
            "modules.m1_product.service.gemini_generate_json",
            new_callable=AsyncMock,
        ) as mock_grounded,
        patch(
            "modules.m1_product.service.upcitemdb_lookup",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        response = await client.post(RESOLVE_URL, json={"upc": "195950797817"})

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Apple iPad Air 13-inch (M4) Wi-Fi 128GB"
    assert data["source"] == "gemini_upc"
    mock_grounded.assert_not_called(), (
        "Grounded Gemini must not fire when Serper synthesis succeeds — "
        "the whole point of the E-then-B wire-up is to skip grounded on the happy path"
    )


@pytest.mark.asyncio
async def test_resolve_falls_back_to_grounded_when_serper_returns_none(
    client, db_session, fake_redis, gemini_fixture
):
    """When Serper returns None (missing key, no coverage, etc.), the
    grounded path IS called — coverage-gap UPCs still resolve.

    The bench measured Serper hits ~85-100 % of real-world UPCs but
    leaves a non-trivial tail of obscure SKUs and non-US-retail products
    where its index has nothing useful. The grounded fallback is the
    safety net for those.
    """
    with (
        patch(
            "modules.m1_product.service.resolve_via_serper",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "modules.m1_product.service.gemini_generate_json",
            new_callable=AsyncMock,
            return_value=gemini_fixture,
        ) as mock_grounded,
        patch(
            "modules.m1_product.service.upcitemdb_lookup",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        response = await client.post(RESOLVE_URL, json={"upc": VALID_UPC})

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == gemini_fixture["device_name"]
    mock_grounded.assert_called_once(), (
        "Grounded Gemini must fire when Serper returns None — otherwise "
        "we regress on every Serper-coverage gap"
    )


@pytest.mark.asyncio
async def test_resolve_falls_back_to_grounded_when_serper_raises(
    client, db_session, fake_redis, gemini_fixture
):
    """When ``resolve_via_serper`` raises an unexpected exception, the
    request must NOT crash — grounded fallback runs as if Serper returned
    None. Defensive: web_search.py already swallows known errors but a
    future bug there must not propagate to the user."""
    with (
        patch(
            "modules.m1_product.service.resolve_via_serper",
            new_callable=AsyncMock,
            side_effect=RuntimeError("unexpected serper failure"),
        ),
        patch(
            "modules.m1_product.service.gemini_generate_json",
            new_callable=AsyncMock,
            return_value=gemini_fixture,
        ) as mock_grounded,
        patch(
            "modules.m1_product.service.upcitemdb_lookup",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        response = await client.post(RESOLVE_URL, json={"upc": VALID_UPC})

    assert response.status_code == 200
    mock_grounded.assert_called_once()
