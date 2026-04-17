"""Tests for M1 Product Search — POST /api/v1/products/search (Step 3a)."""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text as sql_text

from app.config import settings
from modules.m1_product.models import Product

SEARCH_URL = "/api/v1/products/search"


# MARK: - Query validation


@pytest.mark.asyncio
async def test_search_rejects_short_query(client):
    """Query shorter than 3 characters returns 422."""
    response = await client.post(SEARCH_URL, json={"query": "ab"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_search_rejects_empty_query(client):
    """Empty query returns 422 (min_length=3 on the schema)."""
    response = await client.post(SEARCH_URL, json={"query": ""})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_search_pagination_cap(client):
    """max_results above the cap of 20 returns 422."""
    response = await client.post(
        SEARCH_URL, json={"query": "iphone", "max_results": 50}
    )
    assert response.status_code == 422


# MARK: - Normalization + caching


@pytest.mark.asyncio
async def test_search_normalizes_query(client, db_session, fake_redis):
    """Equivalent queries with different casing/whitespace hit the same cache key.

    First call warms the cache; second call (different casing, extra whitespace)
    MUST return ``cached=true`` and MUST NOT call Gemini.
    """
    # Seed 3 matching products so DB path fills and Gemini isn't needed.
    for name in (
        "Apple iPhone 16 Pro Max 256GB",
        "Apple iPhone 16 Pro 128GB",
        "Apple iPhone 16 128GB",
    ):
        db_session.add(Product(upc=None, name=name, brand="Apple", source="seed"))
    await db_session.flush()

    with patch(
        "modules.m1_product.search_service.gemini_generate_json",
        new_callable=AsyncMock,
        return_value=[],
    ) as mock_gemini:
        first = await client.post(
            SEARCH_URL, json={"query": "  iPhone 16  ", "max_results": 5}
        )
        assert first.status_code == 200
        assert first.json()["cached"] is False
        first_ai_calls = mock_gemini.call_count

        second = await client.post(
            SEARCH_URL, json={"query": "iphone 16", "max_results": 5}
        )
        assert second.status_code == 200
        assert second.json()["cached"] is True

    # Second call must not increment Gemini calls — identical cache keys across
    # casing/whitespace variants means the second request short-circuits.
    assert mock_gemini.call_count == first_ai_calls


# MARK: - DB fuzzy match


@pytest.mark.asyncio
async def test_search_db_fuzzy_match(client, db_session):
    """Seed three iPhones; search for 'iphone' returns them all with source=db."""
    names = [
        "Apple iPhone 16 Pro Max 256GB",
        "Apple iPhone 16 Pro 128GB",
        "Apple iPhone 16 128GB",
    ]
    for n in names:
        db_session.add(Product(upc=None, name=n, brand="Apple", source="seed"))
    await db_session.flush()

    with patch(
        "modules.m1_product.search_service.gemini_generate_json",
        new_callable=AsyncMock,
        return_value=[],
    ):
        response = await client.post(
            SEARCH_URL, json={"query": "iPhone 16", "max_results": 5}
        )

    assert response.status_code == 200
    data = response.json()
    assert data["total_results"] >= 3
    db_rows = [r for r in data["results"] if r["source"] == "db"]
    assert len(db_rows) >= 3
    for row in db_rows[:3]:
        assert "iPhone 16" in row["device_name"]
        assert row["product_id"] is not None


# MARK: - Cache hit short-circuit


@pytest.mark.asyncio
async def test_search_cache_hit(client, db_session):
    """Second identical search returns ``cached=true`` and does not call Gemini."""
    db_session.add(
        Product(upc=None, name="Sony WH-1000XM5 Headphones", brand="Sony", source="seed")
    )
    await db_session.flush()

    with patch(
        "modules.m1_product.search_service.gemini_generate_json",
        new_callable=AsyncMock,
        return_value=[],
    ) as mock_gemini:
        first = await client.post(
            SEARCH_URL, json={"query": "sony wh-1000xm5", "max_results": 5}
        )
        assert first.status_code == 200
        assert first.json()["cached"] is False
        first_ai_calls = mock_gemini.call_count

        second = await client.post(
            SEARCH_URL, json={"query": "sony wh-1000xm5", "max_results": 5}
        )
        assert second.status_code == 200
        assert second.json()["cached"] is True

    # Second call must not increment Gemini call count (cache hit).
    assert mock_gemini.call_count == first_ai_calls


# MARK: - Gemini fallback


@pytest.mark.asyncio
async def test_search_gemini_fallback(client, db_session):
    """DB returns 0 rows → Gemini is called and its results are surfaced."""
    # Empty DB — no products matching "obscure_gadget".
    gemini_return = [
        {
            "device_name": "Obscure Gadget Pro",
            "model": "OG-Pro-2025",
            "brand": "Obscure",
            "category": "electronics",
            "confidence": 0.88,
            "primary_upc": "012345678901",
        },
        {
            "device_name": "Obscure Gadget Lite",
            "model": "OG-Lite",
            "brand": "Obscure",
            "category": "electronics",
            "confidence": 0.62,
            "primary_upc": None,
        },
        {
            "device_name": "Obscure Gadget Mini",
            "model": "OG-Mini",
            "brand": "Obscure",
            "category": "electronics",
            "confidence": 0.45,
            "primary_upc": None,
        },
    ]
    with patch(
        "modules.m1_product.search_service.gemini_generate_json",
        new_callable=AsyncMock,
        return_value=gemini_return,
    ) as mock_gemini:
        response = await client.post(
            SEARCH_URL, json={"query": "obscure gadget widget", "max_results": 5}
        )

    assert response.status_code == 200
    data = response.json()
    assert data["total_results"] == 3
    sources = [r["source"] for r in data["results"]]
    assert sources == ["gemini", "gemini", "gemini"]
    assert data["results"][0]["device_name"] == "Obscure Gadget Pro"
    assert data["results"][0]["primary_upc"] == "012345678901"
    # First call — cache miss — Gemini invoked exactly once.
    assert mock_gemini.call_count == 1


# MARK: - Dedup DB vs Gemini


@pytest.mark.asyncio
async def test_search_gemini_dedup(client, db_session):
    """DB returns 2, Gemini returns 3 (1 duplicate by brand+name) → merged list of 4."""
    db_session.add(
        Product(upc=None, name="Sony WH-1000XM5", brand="Sony", source="seed")
    )
    db_session.add(
        Product(upc=None, name="Sony WH-1000XM4", brand="Sony", source="seed")
    )
    await db_session.flush()

    gemini_return = [
        # Duplicate of a DB row (same brand + name, different casing)
        {
            "device_name": "sony wh-1000xm5",
            "model": "WH-1000XM5",
            "brand": "sony",
            "category": "headphones",
            "confidence": 0.97,
            "primary_upc": "027242924864",
        },
        {
            "device_name": "Sony WF-1000XM5",
            "model": "WF-1000XM5",
            "brand": "Sony",
            "category": "earbuds",
            "confidence": 0.55,
            "primary_upc": "027242925236",
        },
        {
            "device_name": "Sony LinkBuds S",
            "model": "WF-LS900N",
            "brand": "Sony",
            "category": "earbuds",
            "confidence": 0.40,
            "primary_upc": None,
        },
    ]

    with patch(
        "modules.m1_product.search_service.gemini_generate_json",
        new_callable=AsyncMock,
        return_value=gemini_return,
    ):
        response = await client.post(
            SEARCH_URL, json={"query": "sony", "max_results": 10}
        )

    assert response.status_code == 200
    data = response.json()
    # Expect: 2 DB rows + 2 non-duplicate Gemini rows = 4
    assert data["total_results"] == 4
    sources = [r["source"] for r in data["results"]]
    assert sources.count("db") == 2
    assert sources.count("gemini") == 2
    # Duplicate should have been dropped — only the DB version of WH-1000XM5 survives
    names = [r["device_name"] for r in data["results"]]
    assert "Sony WH-1000XM5" in names  # DB casing
    assert "sony wh-1000xm5" not in names  # Gemini duplicate dropped


# MARK: - Rate limit


@pytest.mark.asyncio
async def test_search_rate_limit(client, db_session):
    """Exceeding RATE_LIMIT_GENERAL returns 429."""
    db_session.add(
        Product(upc=None, name="Bose QuietComfort", brand="Bose", source="seed")
    )
    await db_session.flush()

    original = settings.RATE_LIMIT_GENERAL
    settings.RATE_LIMIT_GENERAL = 3
    try:
        with patch(
            "modules.m1_product.search_service.gemini_generate_json",
            new_callable=AsyncMock,
            return_value=[],
        ):
            # 3 requests at the limit — all succeed. Use slightly different
            # queries so Redis cache doesn't absorb them (same cache key would
            # still route through the rate limiter, but explicit distinct
            # calls make the intent clearer).
            for i in range(3):
                resp = await client.post(
                    SEARCH_URL, json={"query": f"bose query {i}", "max_results": 5}
                )
                assert resp.status_code == 200

            # 4th request — over the limit.
            resp = await client.post(
                SEARCH_URL, json={"query": "bose query 4", "max_results": 5}
            )
            assert resp.status_code == 429
            body = resp.json()
            assert body["detail"]["error"]["code"] == "RATE_LIMITED"
    finally:
        settings.RATE_LIMIT_GENERAL = original


# MARK: - Migration 0007 schema sanity


@pytest.mark.asyncio
async def test_search_pg_trgm_index_exists(db_session):
    """Migration 0007 applied — ``idx_products_name_trgm`` is present."""
    result = await db_session.execute(
        sql_text(
            "SELECT indexname FROM pg_indexes WHERE indexname = 'idx_products_name_trgm'"
        )
    )
    row = result.scalar_one_or_none()
    assert row == "idx_products_name_trgm"
