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


# MARK: - Auth


@pytest.mark.asyncio
async def test_resolve_requires_auth(unauthed_client):
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
    with patch(
        "modules.m1_product.service.gemini_generate_json",
        new_callable=AsyncMock,
    ) as mock_gemini:
        mock_gemini.return_value = gemini_fixture

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
    with patch(
        "modules.m1_product.service.gemini_generate_json",
        new_callable=AsyncMock,
        return_value=gemini_fixture,
    ):
        response = await client.post(RESOLVE_URL, json={"upc": VALID_UPC})

    assert response.status_code == 200
    data = response.json()
    required_fields = {
        "id", "upc", "name", "brand", "category",
        "source", "created_at", "updated_at",
    }
    assert required_fields.issubset(data.keys())


# MARK: - 13-digit EAN


@pytest.mark.asyncio
async def test_resolve_accepts_13_digit_ean(
    client, db_session, fake_redis, gemini_fixture
):
    """13-digit EAN barcode is accepted."""
    with patch(
        "modules.m1_product.service.gemini_generate_json",
        new_callable=AsyncMock,
        return_value=gemini_fixture,
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
    with patch(
        "modules.m1_product.service.gemini_generate_json",
        new_callable=AsyncMock,
        return_value=gemini_fixture,
    ) as mock_gemini:
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
