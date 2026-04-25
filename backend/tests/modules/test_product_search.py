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


# MARK: - Tier 2 noise filter (samsung flip 7 → cases-only class)


@pytest.mark.asyncio
async def test_tier2_only_cases_escalates_to_gemini(
    client, db_session, _stub_bestbuy_tier2, _stub_upcitemdb_tier2
):
    """Tier 2 returns only `Cell Phone Cases` rows → Gemini must fire."""
    _stub_bestbuy_tier2.return_value = [
        {
            "device_name": "Samsung - S24 Flipsuit Case - White",
            "brand": "Samsung", "model": "EF-MS921CWEGUS",
            "category": "Cell Phone Cases",
            "primary_upc": "887276832777", "confidence": 0.86,
        },
        {
            "device_name": "OtterBox - Thin Flex for Galaxy Z Flip7 - Clear",
            "brand": "OtterBox", "model": "77-95813",
            "category": "Cell Phone Cases",
            "primary_upc": "840304766307", "confidence": 0.74,
        },
    ]
    gemini_rows = [{
        "device_name": "Samsung Galaxy Z Flip 7", "brand": "Samsung",
        "model": "Galaxy Z Flip 7", "confidence": 0.95, "primary_upc": None,
    }]
    with patch(
        "modules.m1_product.search_service.gemini_generate_json",
        new_callable=AsyncMock, return_value=gemini_rows,
    ) as mock_gemini:
        response = await client.post(
            SEARCH_URL, json={"query": "samsung flip 7", "max_results": 5}
        )

    assert response.status_code == 200
    assert mock_gemini.call_count == 1, "Gemini must fire when Tier 2 is all cases"
    sources = {r["source"] for r in response.json()["results"]}
    assert "gemini" in sources


@pytest.mark.asyncio
async def test_tier2_only_applecare_escalates_to_gemini(
    client, db_session, _stub_bestbuy_tier2, _stub_upcitemdb_tier2
):
    """Tier 2 returns only AppleCare warranty rows → Gemini must fire."""
    _stub_bestbuy_tier2.return_value = [
        {
            "device_name": "AppleCare+ for iPhone - Monthly",
            "brand": "Apple", "category": "AppleCare Warranties",
            "primary_upc": "ac1", "confidence": 0.9,
        },
        {
            "device_name": "AppleCare+ for iPhone - 2 Year Plan",
            "brand": "Apple", "category": "AppleCare Warranties",
            "primary_upc": "ac2", "confidence": 0.86,
        },
    ]
    gemini_rows = [{
        "device_name": "Apple iPhone 17 Pro", "brand": "Apple",
        "model": "iPhone 17 Pro", "confidence": 0.97, "primary_upc": None,
    }]
    with patch(
        "modules.m1_product.search_service.gemini_generate_json",
        new_callable=AsyncMock, return_value=gemini_rows,
    ) as mock_gemini:
        response = await client.post(
            SEARCH_URL, json={"query": "iphone 17 pro", "max_results": 5}
        )

    assert response.status_code == 200
    assert mock_gemini.call_count == 1


@pytest.mark.asyncio
async def test_tier2_mixed_relevant_plus_noise_skips_gemini(
    client, db_session, _stub_bestbuy_tier2, _stub_upcitemdb_tier2
):
    """Tier 2 has at least one non-noise row → Gemini stays quiet (cost guard)."""
    _stub_bestbuy_tier2.return_value = [
        {
            "device_name": "ASUS - TUF Gaming RTX 5090 32GB",
            "brand": "ASUS", "category": "GPUs / Video Graphics Cards",
            "primary_upc": "rtx1", "confidence": 0.9,
        },
        {
            "device_name": "Standard Products - Monthly Best Buy Protection",
            "brand": "Best Buy", "category": "Protection Plans",
            "primary_upc": "p1", "confidence": 0.86,
        },
    ]
    with patch(
        "modules.m1_product.search_service.gemini_generate_json",
        new_callable=AsyncMock, return_value=[],
    ) as mock_gemini:
        response = await client.post(
            SEARCH_URL, json={"query": "rtx 5090", "max_results": 5}
        )

    assert response.status_code == 200
    assert mock_gemini.call_count == 0, "Real RTX 5090 row keeps cascade quiet"


@pytest.mark.asyncio
async def test_tier2_pixel_collision_escalates_to_gemini(
    client, db_session, _stub_bestbuy_tier2, _stub_upcitemdb_tier2
):
    """`pixel 10` → Mobile Pixels monitor collision → Gemini must fire."""
    _stub_bestbuy_tier2.return_value = [
        {
            "device_name": "Mobile Pixels - Fold 15.6\" LCD Monitor - Black",
            "brand": "Mobile Pixels", "category": "Portable Monitors",
            "primary_upc": "mp1", "confidence": 0.9,
        },
        {
            "device_name": "Mobile Pixels - Glance 16\" LCD Monitor - Black",
            "brand": "Mobile Pixels", "category": "Portable Monitors",
            "primary_upc": "mp2", "confidence": 0.86,
        },
    ]
    gemini_rows = [{
        "device_name": "Google Pixel 10", "brand": "Google",
        "model": "Pixel 10", "confidence": 0.96, "primary_upc": None,
    }]
    with patch(
        "modules.m1_product.search_service.gemini_generate_json",
        new_callable=AsyncMock, return_value=gemini_rows,
    ) as mock_gemini:
        response = await client.post(
            SEARCH_URL, json={"query": "pixel 10", "max_results": 5}
        )

    assert response.status_code == 200
    assert mock_gemini.call_count == 1


# MARK: - Tier 2 noise filter (brand + model-code relevance)


@pytest.mark.asyncio
async def test_tier2_offbrand_fuzzy_match_escalates_to_gemini(
    client, db_session, _stub_bestbuy_tier2, _stub_upcitemdb_tier2
):
    """`focal utopia 2022` → Panasonic lens + Kindle case + F1 game. None
    share a brand token with the query, so the cascade must escalate."""
    _stub_bestbuy_tier2.return_value = [
        {
            "device_name": "Panasonic - LUMIX S 26mm F8 Fixed Focal Length Pancake Lens",
            "brand": "Panasonic", "model": "S-R26",
            "category": "Camera Lenses",
            "primary_upc": "885170430082", "confidence": 0.86,
        },
        {
            "device_name": "SaharaCase - Venture Series Case for Amazon Kindle Paperwhite",
            "brand": "SaharaCase", "category": "Tablet Accessories",
            "primary_upc": "810091582671", "confidence": 0.74,
        },
    ]
    gemini_rows = [{
        "device_name": "Focal Utopia 2022 Open-Back Reference Headphones",
        "brand": "Focal", "model": "Utopia (2022)",
        "confidence": 0.95, "primary_upc": None,
    }]
    with patch(
        "modules.m1_product.search_service.gemini_generate_json",
        new_callable=AsyncMock, return_value=gemini_rows,
    ) as mock_gemini:
        response = await client.post(
            SEARCH_URL, json={"query": "focal utopia 2022", "max_results": 5}
        )

    assert response.status_code == 200
    assert mock_gemini.call_count == 1, "off-brand fuzzy matches must escalate"
    sources = {r["source"] for r in response.json()["results"]}
    assert "gemini" in sources


@pytest.mark.asyncio
async def test_tier2_missing_model_code_escalates_to_gemini(
    client, db_session, _stub_bestbuy_tier2, _stub_upcitemdb_tier2
):
    """`lg 27gp950` → LG Q6 phone + Best Buy water filter. Brand matches on
    one row, but neither contains the `27gp950` model code, so both must
    flag as noise and the cascade escalates."""
    _stub_bestbuy_tier2.return_value = [
        {
            "device_name": "LG - Geek Squad Certified Refurbished Q6 4G LTE with 32GB Memory",
            "brand": "LG", "model": "LM-X220MA.AUSAPL",
            "category": "Smartphones",
            "primary_upc": "400062023366", "confidence": 0.86,
        },
        {
            "device_name": "Best Buy essentials - NSF 42/53 Water Filter Replacement",
            "brand": "Best Buy essentials", "category": "Water Filters",
            "primary_upc": "600603321948", "confidence": 0.74,
        },
    ]
    gemini_rows = [{
        "device_name": "LG UltraGear 27GP950-B 27\" Nano IPS 4K Gaming Monitor",
        "brand": "LG", "model": "27GP950-B",
        "confidence": 0.95, "primary_upc": "719192640245",
    }]
    with patch(
        "modules.m1_product.search_service.gemini_generate_json",
        new_callable=AsyncMock, return_value=gemini_rows,
    ) as mock_gemini:
        response = await client.post(
            SEARCH_URL, json={"query": "lg 27gp950", "max_results": 5}
        )

    assert response.status_code == 200
    assert mock_gemini.call_count == 1, "model-code miss must escalate even when brand matches"


@pytest.mark.asyncio
async def test_tier2_brand_and_model_match_skips_gemini(
    client, db_session, _stub_bestbuy_tier2, _stub_upcitemdb_tier2
):
    """`sony wh-1000xm5` → real Sony WH-1000XM5 rows → Gemini stays quiet.
    Cost guard for the new relevance check."""
    _stub_bestbuy_tier2.return_value = [
        {
            "device_name": "Sony - WH-1000XM5 Wireless Noise Cancelling Over-the-Ear Headphones - Black",
            "brand": "Sony", "model": "WH-1000XM5",
            "category": "Headphones",
            "primary_upc": "027242923232", "confidence": 0.9,
        },
    ]
    with patch(
        "modules.m1_product.search_service.gemini_generate_json",
        new_callable=AsyncMock, return_value=[],
    ) as mock_gemini:
        response = await client.post(
            SEARCH_URL, json={"query": "sony wh-1000xm5", "max_results": 5}
        )

    assert response.status_code == 200
    assert mock_gemini.call_count == 0, "real brand+model match keeps cascade quiet"


@pytest.mark.asyncio
async def test_tier2_noise_stripped_from_output_even_when_legit_hit_exists(
    client, db_session, _stub_bestbuy_tier2, _stub_upcitemdb_tier2
):
    """Regression (fix/search-merge-noise): BBY noise + 1 UPCitemdb legit hit
    should return ONLY the legit hit — noise must not crowd it out at merge
    time even though its presence keeps Gemini from escalating.

    Reproduces the `iphone air` field bug: BBY returned 5 noise rows
    (AppleCare / Airbnb gift cards / Medify Air purifiers) with confidence
    0.9→0.54, UPCitemdb returned 1 real iPhone Air row with confidence ≤0.5.
    Pre-fix: all 6 rows merged, BBY noise outranked UPCitemdb by confidence,
    the real hit fell below `max_results=5`. Post-fix: noise dropped pre-merge,
    only the UPCitemdb hit survives.
    """
    _stub_bestbuy_tier2.return_value = [
        {
            "device_name": "AppleCare+ for iPhone - Monthly",
            "brand": "AppleCare", "model": "APPLECARE+ IPHONE AIR MON",
            "category": "AppleCare Warranties",
            "primary_upc": "ac1", "confidence": 0.9,
        },
        {
            "device_name": "Airbnb - $100 Gift Card [Digital]",
            "brand": "Airbnb", "model": "AIRBNB $100 DIGITAL.COM",
            "category": "All Specialty Gift Cards",
            "primary_upc": "ab1", "confidence": 0.86,
        },
        {
            "device_name": "Medify Air - MA-15 Portable Air Purifier",
            "brand": "Medify Air", "model": "MA-15-S1",
            "category": "Portable Air Purifiers",
            "primary_upc": "ma1", "confidence": 0.82,
        },
    ]
    _stub_upcitemdb_tier2.return_value = [
        {
            "device_name": "Apple iPhone Air 256GB - Sky Blue",
            "brand": "Apple", "model": "iPhone Air",
            "category": None,
            "primary_upc": "195949000001", "confidence": 0.5,
        },
    ]
    with patch(
        "modules.m1_product.search_service.gemini_generate_json",
        new_callable=AsyncMock, return_value=[],
    ) as mock_gemini:
        response = await client.post(
            SEARCH_URL, json={"query": "iphone air", "max_results": 5}
        )

    assert response.status_code == 200
    body = response.json()
    # Gemini does NOT fire — one UPCitemdb row passed the filter, so Tier 2
    # is not empty. But the 3 BBY noise rows must be absent from the output.
    assert mock_gemini.call_count == 0
    sources = [r["source"] for r in body["results"]]
    brands = [r["brand"] for r in body["results"]]
    assert "AppleCare" not in brands
    assert "Airbnb" not in brands
    assert "Medify Air" not in brands
    # The real iPhone Air must survive.
    assert any("iPhone Air" in r["device_name"] for r in body["results"])
    # And it must be from UPCitemdb (which our stub mapped to source=best_buy
    # alias per search_service convention — relax to either source).
    assert all(s in {"best_buy", "upcitemdb"} for s in sources)


@pytest.mark.asyncio
async def test_tier2_rtx5090_title_matches_without_brand_token(
    client, db_session, _stub_bestbuy_tier2, _stub_upcitemdb_tier2
):
    """`rtx 5090` has no brand token in the query (NVIDIA is implicit) —
    the ASUS TUF row matches on title tokens, so it passes the relevance
    check. Guards against the new filter being too aggressive on
    model-family queries where the brand is implied."""
    _stub_bestbuy_tier2.return_value = [
        {
            "device_name": "ASUS - TUF Gaming RTX 5090 32GB GDDR7 PCI Express 5.0 Graphics Card",
            "brand": "ASUS", "model": "TUF-RTX5090-32G-GAMING",
            "category": "GPUs / Video Graphics Cards",
            "primary_upc": "192876962152", "confidence": 0.9,
        },
    ]
    with patch(
        "modules.m1_product.search_service.gemini_generate_json",
        new_callable=AsyncMock, return_value=[],
    ) as mock_gemini:
        response = await client.post(
            SEARCH_URL, json={"query": "rtx 5090", "max_results": 5}
        )

    assert response.status_code == 200
    assert mock_gemini.call_count == 0, "title-level query match keeps cascade quiet"


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


# MARK: - Tiered confidence merge (fix/search-merge-confidence)


def test_rank_key_strong_bby_beats_weak_db():
    """A strong-confidence non-DB row outranks a weak DB row.

    Regression: "Nintendo Switch OLED" returned DB "Switch 2" (pg_trgm
    sim 0.49) as #1 ahead of a Best Buy OLED-category row at confidence
    0.66 because the old `_merge()` unconditionally prepended DB rows.
    """
    from modules.m1_product.schemas import ProductSearchResult
    from modules.m1_product.search_service import _rank_key

    weak_db = ProductSearchResult(
        device_name="Nintendo Switch 2 Console 256GB", source="db",
        confidence=0.49, primary_upc="045496885816",
    )
    strong_bby = ProductSearchResult(
        device_name="Nintendo Switch OLED Model", source="best_buy",
        confidence=0.66, primary_upc="045496453435",
    )
    # Sort ascending on the key — lower key = higher rank.
    assert _rank_key(strong_bby) < _rank_key(weak_db)


def test_rank_key_strong_db_still_beats_strong_bby():
    """Within the strong tier, source priority (DB > BBY) is the tiebreaker."""
    from modules.m1_product.schemas import ProductSearchResult
    from modules.m1_product.search_service import _rank_key

    strong_db = ProductSearchResult(
        device_name="Apple iPhone 16 Pro 256GB", source="db", confidence=0.80,
    )
    strong_bby = ProductSearchResult(
        device_name="Apple iPhone 16 Pro 256GB (BBY)", source="best_buy", confidence=0.90,
    )
    assert _rank_key(strong_db) < _rank_key(strong_bby)


def test_rank_key_weak_sources_keep_tier_order():
    """Weak-tier rows preserve DB > BBY > UPCitemdb > Gemini ordering."""
    from modules.m1_product.schemas import ProductSearchResult
    from modules.m1_product.search_service import _rank_key

    weak_db = ProductSearchResult(device_name="a", source="db", confidence=0.30)
    weak_bby = ProductSearchResult(device_name="b", source="best_buy", confidence=0.30)
    weak_upc = ProductSearchResult(device_name="c", source="upcitemdb", confidence=0.30)
    weak_gem = ProductSearchResult(device_name="d", source="gemini", confidence=0.30)
    assert _rank_key(weak_db) < _rank_key(weak_bby) < _rank_key(weak_upc) < _rank_key(weak_gem)


@pytest.mark.asyncio
async def test_cascade_path_populated_on_response(client, db_session, fake_redis):
    """cascade_path surfaces which tiers fired so iOS telemetry can attribute p95."""
    with patch(
        "modules.m1_product.search_service.gemini_generate_json",
        new_callable=AsyncMock,
        return_value=[],
    ):
        response = await client.post(
            SEARCH_URL, json={"query": "no-matches-expected-zzzxxx", "max_results": 5}
        )
    assert response.status_code == 200
    data = response.json()
    # With no DB/Tier2/Gemini hits the cascade either fires gemini (empty
    # result) or reports "empty" — both are valid paths, but the field
    # MUST be populated on every fresh response.
    assert data.get("cascade_path") is not None
    assert data["cascade_path"] in ("gemini", "tier2+gemini", "empty", "db", "db+tier2", "db+tier2+gemini")


def test_is_tier2_noise_filters_controller_accessories():
    """Best Buy surfaces KontrolFreek thumbsticks + Video Game Accessories as
    the top `PS5 Controller` results. Both must be classified as noise so the
    cascade escalates to Gemini and Sony DualSense lands first.
    """
    from modules.m1_product.search_service import _is_tier2_noise
    thumbstick_row = {
        "device_name": "KontrolFreek - Call of Duty Jugger-Nog Performance "
                       "Thumbsticks for Gaming Controllers",
        "brand": "KontrolFreek",
        "category": "Gaming Controller Accessories",
        "primary_upc": "810164143808",
    }
    case_row = {
        "device_name": "SCUF - Universal Controller Protection Case for PS5",
        "brand": "SCUF",
        "category": "Video Game Accessories",
        "primary_upc": "840370269009",
    }
    real_controller = {
        "device_name": "Sony Interactive Entertainment - DualSense "
                       "Wireless Controller for PS5",
        "brand": "Sony Interactive Entertainment",
        "category": "Gaming Controllers",
        "primary_upc": "711719023197",
    }
    assert _is_tier2_noise(thumbstick_row, query="ps5 controller") is True
    assert _is_tier2_noise(case_row, query="ps5 controller") is True
    assert _is_tier2_noise(real_controller, query="ps5 controller") is False


# --- interstitial-parity-1 follow-up: brand-gate + strict-spec rejection
# Pre-Fix the noise filter let cross-brand and sub-SKU drift through:
# Toro Recycler returned Greenworks mowers, Vitamix 5200 returned Explorian
# E310, Greenworks 40V returned 80V backpack. Three layered rules now:
#  - leading meaningful query token (brand) must appear in row haystack
#  - voltage tokens (40v / 80v) must match verbatim
#  - 4+ digit pure-numeric model tokens (5200 / 6400) must match verbatim


def test_is_tier2_noise_rejects_cross_brand_drift():
    """Toro Recycler search must NOT surface Greenworks/WORX mowers."""
    from modules.m1_product.search_service import _is_tier2_noise

    greenworks_row = {
        "device_name": "Greenworks 24V (2x24V) 21-Inch Self-Propelled Lawn Mower",
        "brand": "Greenworks",
        "model": "2532502",
        "category": "Lawn Mowers",
    }
    worx_row = {
        "device_name": "WORX - Nitro WG760 40V 21-Inch Self-Propelled Lawn Mower",
        "brand": "WORX",
        "model": "WG760",
        "category": "Lawn Mowers",
    }
    real_toro = {
        "device_name": "Toro Recycler 22 in. SmartStow Self-Propelled Mower",
        "brand": "Toro",
        "model": "21466",
        "category": "Lawn Mowers",
    }
    q = "Toro Recycler 22 inch self propelled mower"
    assert _is_tier2_noise(greenworks_row, query=q) is True
    assert _is_tier2_noise(worx_row, query=q) is True
    assert _is_tier2_noise(real_toro, query=q) is False


def test_is_tier2_noise_rejects_voltage_drift():
    """Greenworks 40V cordless must NOT surface 80V variants of the same brand."""
    from modules.m1_product.search_service import _is_tier2_noise

    g80_row = {
        "device_name": "Greenworks - 80V 690 CFM 165 MPH Cordless Backpack Leaf Blower",
        "brand": "Greenworks",
        "model": "2421402COVT",
        "category": "Leaf Blowers",
    }
    g40_row = {
        "device_name": "Greenworks 40V Cordless Leaf Blower with Battery",
        "brand": "Greenworks",
        "model": "GBL40320",
        "category": "Leaf Blowers",
    }
    q = "Greenworks 40V cordless leaf blower"
    assert _is_tier2_noise(g80_row, query=q) is True
    assert _is_tier2_noise(g40_row, query=q) is False


def test_is_tier2_noise_rejects_pure_digit_sub_sku_drift():
    """Vitamix 5200 search must NOT surface a different Vitamix model
    (E310 / 64068) — pure-digit model token requires verbatim match.
    """
    from modules.m1_product.search_service import _is_tier2_noise

    e310_row = {
        "device_name": "Vitamix - Explorian E310 Blender - Black",
        "brand": "Vitamix",
        "model": "64068",
        "category": "Full-Size Blenders",
    }
    real_5200 = {
        "device_name": "Vitamix 5200 Series 64-oz Blender Black",
        "brand": "Vitamix",
        "model": "5200",
        "category": "Full-Size Blenders",
    }
    q = "Vitamix 5200 blender"
    assert _is_tier2_noise(e310_row, query=q) is True
    assert _is_tier2_noise(real_5200, query=q) is False


def test_is_tier2_noise_preserves_brand_subsidiary_match():
    """Anker → Soundcore subsidiary (brand mismatch but query token in title)
    must still pass — the brand-gate is a haystack substring check, not a
    brand-field equality.
    """
    from modules.m1_product.search_service import _is_tier2_noise

    soundcore_row = {
        "device_name": "Soundcore - by Anker Liberty 4 NC Noise Canceling Earbuds",
        "brand": "Soundcore",
        "model": "A3947Z11",
        "category": "All Headphones",
    }
    q = "Anker Liberty 4 NC earbuds"
    assert _is_tier2_noise(soundcore_row, query=q) is False


def test_query_strict_specs_extracts_voltage_and_pure_digits():
    from modules.m1_product.search_service import _query_strict_specs

    assert _query_strict_specs("Greenworks 40V leaf blower") == ["40v"]
    assert _query_strict_specs("Vitamix 5200 blender") == ["5200"]
    assert _query_strict_specs("DeWalt 20V Max drill") == ["20v"]
    # 3-digit pure-numeric is NOT treated as a strict spec — too generic.
    assert _query_strict_specs("iPhone 16 Pro 256GB") == []
    # Mixed digit+letter (handled by _query_model_codes) is excluded here.
    assert _query_strict_specs("WH-1000XM5 Sony") == []
