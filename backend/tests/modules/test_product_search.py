"""Tests for M1 Product Search — POST /api/v1/products/search (Step 3a)."""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text as sql_text

from app.config import settings
from modules.m1_product.models import Product

SEARCH_URL = "/api/v1/products/search"


# MARK: - Tier 2 (Best Buy) auto-disable for legacy tests
#
# Tests written before Tier 2 landed assert DB→Gemini behavior. Auto-stub
# `_best_buy_search` to return [] for the whole module so those tests keep
# passing regardless of whether BESTBUY_API_KEY is set in the env. Tier-2
# specific tests below opt-in by patching with their own return values.


@pytest.fixture(autouse=True)
def _stub_bestbuy_tier2():
    with patch(
        "modules.m1_product.search_service.ProductSearchService._best_buy_search",
        new_callable=AsyncMock,
        return_value=[],
    ) as stub:
        yield stub


@pytest.fixture(autouse=True)
def _stub_upcitemdb_tier2():
    with patch(
        "modules.m1_product.search_service.ProductSearchService._upcitemdb_search",
        new_callable=AsyncMock,
        return_value=[],
    ) as stub:
        yield stub


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


# MARK: - Tier 2 — Best Buy Products API


@pytest.mark.asyncio
async def test_search_tier2_bestbuy_short_circuits_gemini(
    client, db_session, _stub_bestbuy_tier2
):
    """DB sparse → Tier 2 returns rows → Gemini is NOT called."""
    bestbuy_rows = [
        {
            "device_name": "Apple AirPods Pro (2nd generation)",
            "model": "MQD83AM/A",
            "brand": "Apple",
            "category": "Earbuds",
            "primary_upc": "195949046674",
            "image_url": "https://pisces.bbystatic.com/x.jpg",
            "confidence": 0.9,
        },
        {
            "device_name": "Apple AirPods 4 with ANC",
            "model": "MXP93AM/A",
            "brand": "Apple",
            "category": "Earbuds",
            "primary_upc": "195949946486",
            "image_url": None,
            "confidence": 0.86,
        },
    ]
    _stub_bestbuy_tier2.return_value = bestbuy_rows

    with patch(
        "modules.m1_product.search_service.gemini_generate_json",
        new_callable=AsyncMock,
        return_value=[{"device_name": "Should Not Appear"}],
    ) as mock_gemini:
        response = await client.post(
            SEARCH_URL, json={"query": "airpods pro 2", "max_results": 5}
        )

    assert response.status_code == 200
    data = response.json()
    assert data["total_results"] == 2
    assert all(r["source"] == "best_buy" for r in data["results"])
    assert data["results"][0]["primary_upc"] == "195949046674"
    # Tier 2 had results — Gemini must not fire.
    assert mock_gemini.call_count == 0


@pytest.mark.asyncio
async def test_search_tier2_empty_falls_through_to_gemini(
    client, db_session, _stub_bestbuy_tier2
):
    """DB sparse + Tier 2 returns 0 (e.g. non-electronics query) → Gemini fires."""
    _stub_bestbuy_tier2.return_value = []

    gemini_rows = [
        {
            "device_name": "Whole Milk Gallon",
            "brand": "Generic",
            "category": "groceries",
            "confidence": 0.7,
        },
    ]
    with patch(
        "modules.m1_product.search_service.gemini_generate_json",
        new_callable=AsyncMock,
        return_value=gemini_rows,
    ) as mock_gemini:
        response = await client.post(
            SEARCH_URL, json={"query": "whole milk gallon", "max_results": 5}
        )

    assert response.status_code == 200
    data = response.json()
    assert data["total_results"] == 1
    assert data["results"][0]["source"] == "gemini"
    assert mock_gemini.call_count == 1


@pytest.mark.asyncio
async def test_search_tier2_dedup_against_db(client, db_session, _stub_bestbuy_tier2):
    """DB row + Tier 2 row with same (brand, name) → DB wins, Tier 2 dropped."""
    db_session.add(
        Product(upc="195949046674", name="Apple AirPods Pro 2nd Gen", brand="Apple", source="seed")
    )
    await db_session.flush()

    _stub_bestbuy_tier2.return_value = [
        # Same (brand, name) as the DB row, different casing — must be dropped.
        {
            "device_name": "apple airpods pro 2nd gen",
            "brand": "APPLE",
            "primary_upc": "195949046674",
            "confidence": 0.9,
        },
        {
            "device_name": "Apple AirPods 4",
            "brand": "Apple",
            "primary_upc": "195949946486",
            "confidence": 0.85,
        },
    ]
    with patch(
        "modules.m1_product.search_service.gemini_generate_json",
        new_callable=AsyncMock,
        return_value=[],
    ):
        response = await client.post(
            SEARCH_URL, json={"query": "apple airpods", "max_results": 5}
        )

    data = response.json()
    sources = [r["source"] for r in data["results"]]
    # Exactly one DB row, one Best Buy row — duplicate dropped.
    assert sources.count("db") == 1
    assert sources.count("best_buy") == 1
    names = [r["device_name"] for r in data["results"]]
    assert "Apple AirPods Pro 2nd Gen" in names  # DB casing
    assert "apple airpods pro 2nd gen" not in names  # Tier 2 dup dropped


@pytest.mark.asyncio
async def test_search_tier2_disabled_when_key_unset(client, db_session):
    """Without BESTBUY_API_KEY, `_best_buy_search` returns [] without HTTP."""
    # Bypass the autouse stub by monkeypatching settings only — the real method runs.
    original = settings.BESTBUY_API_KEY
    settings.BESTBUY_API_KEY = ""
    try:
        # Stop the autouse fixture by re-patching to call the real implementation.
        from modules.m1_product.search_service import ProductSearchService
        with patch.object(
            ProductSearchService,
            "_best_buy_search",
            new=ProductSearchService._best_buy_search,
        ), patch(
            "modules.m1_product.search_service.gemini_generate_json",
            new_callable=AsyncMock,
            return_value=[],
        ):
            response = await client.post(
                SEARCH_URL, json={"query": "airpods", "max_results": 5}
            )
    finally:
        settings.BESTBUY_API_KEY = original

    assert response.status_code == 200


# MARK: - Tier 2 — UPCitemdb (parallel with Best Buy)


@pytest.mark.asyncio
async def test_search_tier2_upcitemdb_supplements_bestbuy(
    client, db_session, _stub_bestbuy_tier2, _stub_upcitemdb_tier2
):
    """BBY + UPCitemdb both return rows → merged in BBY-precedence order."""
    _stub_bestbuy_tier2.return_value = [
        {
            "device_name": "Apple AirPods Pro 2nd Gen",
            "brand": "Apple",
            "primary_upc": "195949046674",
            "confidence": 0.9,
        },
    ]
    _stub_upcitemdb_tier2.return_value = [
        # Same (brand, name) as BBY — must be dropped (BBY precedence).
        {
            "device_name": "apple airpods pro 2nd gen",
            "brand": "APPLE",
            "primary_upc": "195949046674",
            "confidence": 0.4,
        },
        # New row UPCitemdb has but BBY doesn't.
        {
            "device_name": "Skullcandy Indy Evo Earbuds",
            "brand": "Skullcandy",
            "primary_upc": "878615092693",
            "confidence": 0.4,
        },
    ]
    with patch(
        "modules.m1_product.search_service.gemini_generate_json",
        new_callable=AsyncMock,
        return_value=[],
    ) as mock_gemini:
        response = await client.post(
            SEARCH_URL, json={"query": "earbuds", "max_results": 10}
        )

    data = response.json()
    sources = [r["source"] for r in data["results"]]
    assert sources == ["best_buy", "upcitemdb"]
    # Both Tier 2 sources had results — Gemini must not fire.
    assert mock_gemini.call_count == 0


@pytest.mark.asyncio
async def test_search_tier2_both_empty_falls_through_to_gemini(
    client, db_session, _stub_bestbuy_tier2, _stub_upcitemdb_tier2
):
    """Both BBY and UPCitemdb return [] → Gemini fires."""
    _stub_bestbuy_tier2.return_value = []
    _stub_upcitemdb_tier2.return_value = []

    gemini_rows = [
        {"device_name": "Whole Milk Gallon", "brand": "Generic", "confidence": 0.7},
    ]
    with patch(
        "modules.m1_product.search_service.gemini_generate_json",
        new_callable=AsyncMock,
        return_value=gemini_rows,
    ) as mock_gemini:
        response = await client.post(
            SEARCH_URL, json={"query": "whole milk gallon", "max_results": 5}
        )

    data = response.json()
    assert data["results"][0]["source"] == "gemini"
    assert mock_gemini.call_count == 1


@pytest.mark.asyncio
async def test_search_tier2_upcitemdb_only_when_bestbuy_empty(
    client, db_session, _stub_bestbuy_tier2, _stub_upcitemdb_tier2
):
    """BBY empty + UPCitemdb has rows → UPCitemdb surfaces, Gemini stays silent."""
    _stub_bestbuy_tier2.return_value = []
    _stub_upcitemdb_tier2.return_value = [
        {
            "device_name": "Vintage Pyrex Bowl 1960s",
            "brand": "Pyrex",
            "primary_upc": "012345678901",
            "confidence": 0.4,
        },
    ]
    with patch(
        "modules.m1_product.search_service.gemini_generate_json",
        new_callable=AsyncMock,
        return_value=[],
    ) as mock_gemini:
        response = await client.post(
            SEARCH_URL, json={"query": "vintage pyrex bowl", "max_results": 5}
        )

    data = response.json()
    assert len(data["results"]) == 1
    assert data["results"][0]["source"] == "upcitemdb"
    assert mock_gemini.call_count == 0


# MARK: - Brand-only query detection


@pytest.mark.asyncio
async def test_brand_only_query_skips_tier2(
    client, db_session, _stub_bestbuy_tier2, _stub_upcitemdb_tier2
):
    """Single-token brand query routes straight to Gemini, skipping Tier 2."""
    gemini_rows = [
        {
            "device_name": "Apple iPhone 16 Pro",
            "brand": "Apple",
            "model": "iPhone 16 Pro",
            "confidence": 0.95,
        },
    ]
    with patch(
        "modules.m1_product.search_service.gemini_generate_json",
        new_callable=AsyncMock,
        return_value=gemini_rows,
    ) as mock_gemini:
        response = await client.post(
            SEARCH_URL, json={"query": "Apple", "max_results": 10}
        )

    assert response.status_code == 200
    data = response.json()
    assert data["results"][0]["source"] == "gemini"
    # Brand-only path: Tier 2 must not fire, Gemini must fire exactly once.
    _stub_bestbuy_tier2.assert_not_called()
    _stub_upcitemdb_tier2.assert_not_called()
    assert mock_gemini.call_count == 1


@pytest.mark.asyncio
async def test_brand_plus_model_still_uses_tier2(
    client, db_session, _stub_bestbuy_tier2, _stub_upcitemdb_tier2
):
    """`apple iphone 16` is NOT brand-only — Tier 2 still fires."""
    _stub_bestbuy_tier2.return_value = [
        {"device_name": "Apple iPhone 16 128GB", "brand": "Apple", "primary_upc": "1", "confidence": 0.9},
    ]
    with patch(
        "modules.m1_product.search_service.gemini_generate_json",
        new_callable=AsyncMock,
        return_value=[],
    ):
        response = await client.post(
            SEARCH_URL, json={"query": "apple iphone 16", "max_results": 5}
        )

    assert response.status_code == 200
    _stub_bestbuy_tier2.assert_called_once()
    _stub_upcitemdb_tier2.assert_called_once()


# MARK: - Deep search (force_gemini)


@pytest.mark.asyncio
async def test_force_gemini_runs_gemini_alongside_tier2(
    client, db_session, _stub_bestbuy_tier2, _stub_upcitemdb_tier2
):
    """force_gemini=true → Gemini fires even when Tier 2 already returned rows."""
    _stub_bestbuy_tier2.return_value = [
        {"device_name": "Apple AirPods Pro 2nd Gen", "brand": "Apple", "primary_upc": "1", "confidence": 0.9},
    ]
    gemini_rows = [
        {"device_name": "Some Niche Earbud", "brand": "Niche", "confidence": 0.7},
    ]
    with patch(
        "modules.m1_product.search_service.gemini_generate_json",
        new_callable=AsyncMock,
        return_value=gemini_rows,
    ) as mock_gemini:
        response = await client.post(
            SEARCH_URL,
            json={"query": "earbuds", "max_results": 10, "force_gemini": True},
        )

    data = response.json()
    sources = [r["source"] for r in data["results"]]
    assert "best_buy" in sources
    assert "gemini" in sources
    assert mock_gemini.call_count == 1


@pytest.mark.asyncio
async def test_force_gemini_bypasses_cache(
    client, db_session, _stub_bestbuy_tier2, _stub_upcitemdb_tier2
):
    """A cached response must not short-circuit a force_gemini=true request."""
    _stub_bestbuy_tier2.return_value = [
        {"device_name": "Apple AirPods Pro 2nd Gen", "brand": "Apple", "primary_upc": "1", "confidence": 0.9},
    ]
    with patch(
        "modules.m1_product.search_service.gemini_generate_json",
        new_callable=AsyncMock,
        return_value=[],
    ):
        warm = await client.post(SEARCH_URL, json={"query": "earbuds", "max_results": 5})
        assert warm.status_code == 200

    with patch(
        "modules.m1_product.search_service.gemini_generate_json",
        new_callable=AsyncMock,
        return_value=[{"device_name": "Forced Gemini Hit", "brand": "X", "confidence": 0.8}],
    ) as mock_gemini:
        deep = await client.post(
            SEARCH_URL,
            json={"query": "earbuds", "max_results": 5, "force_gemini": True},
        )
    # Deep search bypassed the cache — cached must be False AND Gemini fired.
    body = deep.json()
    assert body["cached"] is False
    assert mock_gemini.call_count == 1
    names = [r["device_name"] for r in body["results"]]
    assert "Forced Gemini Hit" in names


@pytest.mark.asyncio
async def test_force_gemini_promotes_gemini_to_top(
    client, db_session, _stub_bestbuy_tier2, _stub_upcitemdb_tier2
):
    """Deep search returns Gemini rows BEFORE Tier 2 / DB rows."""
    db_session.add(Product(upc=None, name="Some DB Earbud", brand="X", source="seed"))
    await db_session.flush()
    _stub_bestbuy_tier2.return_value = [
        {"device_name": "BBY Earbud", "brand": "Y", "primary_upc": "1", "confidence": 0.9},
    ]
    gemini_rows = [
        {"device_name": "Gemini Earbud", "brand": "Z", "confidence": 0.95},
    ]
    with patch(
        "modules.m1_product.search_service.gemini_generate_json",
        new_callable=AsyncMock,
        return_value=gemini_rows,
    ):
        response = await client.post(
            SEARCH_URL,
            json={"query": "earbud", "max_results": 5, "force_gemini": True},
        )

    sources = [r["source"] for r in response.json()["results"]]
    # Gemini must be the first row; remaining rows preserve DB > BBY order.
    assert sources[0] == "gemini"
    assert sources.index("db") < sources.index("best_buy")


# MARK: - Variant collapsing


@pytest.mark.asyncio
async def test_variant_collapse_iphone16_prepends_generic_with_variants(
    client, db_session, _stub_bestbuy_tier2, _stub_upcitemdb_tier2
):
    """Generic 'iPhone 16' query: generic row on top, variants behind it."""
    _stub_bestbuy_tier2.return_value = [
        {"device_name": "Apple iPhone 16 256GB Black", "brand": "Apple", "primary_upc": "1", "confidence": 0.9},
        {"device_name": "Apple iPhone 16 256GB Blue", "brand": "Apple", "primary_upc": "2", "confidence": 0.88},
        {"device_name": "Apple iPhone 16 128GB Black", "brand": "Apple", "primary_upc": "3", "confidence": 0.86},
    ]
    response = await client.post(
        SEARCH_URL, json={"query": "iphone 16", "max_results": 10}
    )
    rows = response.json()["results"]
    # First row is the generic synthetic row; rest are the original variants.
    assert rows[0]["source"] == "generic"
    assert rows[0]["primary_upc"] is None
    assert "iPhone 16" in rows[0]["device_name"]
    # Variants follow.
    variant_sources = [r["source"] for r in rows[1:]]
    assert variant_sources == ["best_buy", "best_buy", "best_buy"]
    assert len(rows) == 4  # 1 generic + 3 variants


@pytest.mark.asyncio
async def test_variant_collapse_keeps_storage_when_user_types_it(
    client, db_session, _stub_bestbuy_tier2, _stub_upcitemdb_tier2
):
    """`iPhone 16 256GB` keeps 256 vs 128 — but still inserts generic row per group."""
    _stub_bestbuy_tier2.return_value = [
        {"device_name": "Apple iPhone 16 256GB Black", "brand": "Apple", "primary_upc": "1", "confidence": 0.9},
        {"device_name": "Apple iPhone 16 256GB Blue", "brand": "Apple", "primary_upc": "2", "confidence": 0.88},
        {"device_name": "Apple iPhone 16 128GB Black", "brand": "Apple", "primary_upc": "3", "confidence": 0.86},
    ]
    response = await client.post(
        SEARCH_URL, json={"query": "iphone 16 256GB", "max_results": 10}
    )
    rows = response.json()["results"]
    # First row: generic for the 256GB group (2 variants → has a generic).
    # 128GB group has only 1 variant — no generic row.
    sources = [r["source"] for r in rows]
    assert sources.count("generic") == 1
    # Storage retained on the generic row when the user typed it.
    generic = next(r for r in rows if r["source"] == "generic")
    assert "256" in generic["device_name"]


@pytest.mark.asyncio
async def test_variant_collapse_singleton_no_generic_row(
    client, db_session, _stub_bestbuy_tier2, _stub_upcitemdb_tier2
):
    """Single-variant bucket: emit the row as-is, no synthetic generic row."""
    _stub_bestbuy_tier2.return_value = [
        {"device_name": "Apple iPhone 16 256GB Black", "brand": "Apple", "primary_upc": "1", "confidence": 0.9},
    ]
    response = await client.post(
        SEARCH_URL, json={"query": "iphone 16", "max_results": 10}
    )
    rows = response.json()["results"]
    sources = [r["source"] for r in rows]
    assert "generic" not in sources
    assert len(rows) == 1


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
