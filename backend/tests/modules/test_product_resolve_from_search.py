"""Tests for M1 Product resolve-from-search — POST /api/v1/products/resolve-from-search.

Tap-time fallback for Gemini-sourced search results that lacked a UPC.
See ``backend/ai/prompts/device_to_upc.py`` for the prompt contract and
``ProductResolutionService.resolve_from_search`` for the service entry.
"""

from unittest.mock import AsyncMock, patch

import pytest

from modules.m1_product.models import Product

RESOLVE_FROM_SEARCH_URL = "/api/v1/products/resolve-from-search"


# MARK: - Request validation


@pytest.mark.asyncio
async def test_resolve_from_search_rejects_short_device_name(client):
    """device_name under 3 chars is rejected at the schema boundary (422)."""
    response = await client.post(
        RESOLVE_FROM_SEARCH_URL, json={"device_name": "ab"}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_resolve_from_search_rejects_missing_device_name(client):
    """Missing device_name is rejected as 422."""
    response = await client.post(
        RESOLVE_FROM_SEARCH_URL, json={"brand": "Apple"}
    )
    assert response.status_code == 422


# MARK: - Happy path


@pytest.mark.asyncio
async def test_resolve_from_search_success(client, db_session, fake_redis):
    """Gemini returns a UPC → delegates to resolve → persists product.

    Patches TWO callsites on the same module:
    - the device→UPC prompt call (returns ``{"upc": "...", ...}``)
    - the UPC→product prompt call used by the downstream ``resolve()`` path
    """
    derived_upc = "190198451736"

    async def fake_gemini(prompt, **kwargs):
        # First call (device→UPC): short digit string. Second call
        # (UPC→product): full product metadata dict. Dispatch on which
        # system instruction the service passed.
        system = kwargs.get("system_instruction", "") or ""
        if "device description" in system or "canonical 12-" in system or "Universal Product Code" not in system:
            # device_to_upc prompt
            return {"upc": derived_upc, "reasoning": "verified on apple.com"}
        # upc_lookup prompt
        return {"device_name": "Apple iPhone 8 64GB", "model": "iPhone 8"}

    with (
        patch(
            "modules.m1_product.service.gemini_generate_json",
            new_callable=AsyncMock,
            side_effect=fake_gemini,
        ) as mock_gemini,
        patch(
            "modules.m1_product.service.upcitemdb_lookup",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        response = await client.post(
            RESOLVE_FROM_SEARCH_URL,
            json={
                "device_name": "Apple iPhone 8 (64GB)",
                "brand": "Apple",
                "model": "iPhone 8",
            },
        )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["upc"] == derived_upc
    assert data["name"] == "Apple iPhone 8 64GB"
    assert data["source"] == "gemini_upc"
    # Both lookups fired: device→UPC AND UPC→product via the existing resolve chain.
    assert mock_gemini.call_count == 2


# MARK: - Gemini returns null → 404 UPC_NOT_FOUND_FOR_PRODUCT


@pytest.mark.asyncio
async def test_resolve_from_search_404_when_gemini_cannot_find_upc(
    client, db_session, fake_redis
):
    """Gemini returns null UPC on both attempts → 404 with specific error code."""
    with (
        patch(
            "modules.m1_product.service.gemini_generate_json",
            new_callable=AsyncMock,
            return_value={"upc": None, "reasoning": "unknown"},
        ) as mock_gemini,
        patch(
            "modules.m1_product.service.upcitemdb_lookup",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        response = await client.post(
            RESOLVE_FROM_SEARCH_URL,
            json={"device_name": "Unknown Mystery Gadget XYZ"},
        )

    assert response.status_code == 404
    body = response.json()
    assert body["detail"]["error"]["code"] == "UPC_NOT_FOUND_FOR_PRODUCT"
    # Called twice: initial + retry, both null.
    assert mock_gemini.call_count == 2


# MARK: - Malformed Gemini response → 404


@pytest.mark.asyncio
async def test_resolve_from_search_404_when_gemini_returns_invalid_upc(
    client, db_session, fake_redis
):
    """Gemini returns a non-digit UPC → treated as null → 404."""
    with (
        patch(
            "modules.m1_product.service.gemini_generate_json",
            new_callable=AsyncMock,
            return_value={"upc": "not-a-barcode", "reasoning": "garbled"},
        ),
        patch(
            "modules.m1_product.service.upcitemdb_lookup",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        response = await client.post(
            RESOLVE_FROM_SEARCH_URL,
            json={"device_name": "Some Product 2026"},
        )

    assert response.status_code == 404
    body = response.json()
    assert body["detail"]["error"]["code"] == "UPC_NOT_FOUND_FOR_PRODUCT"


# MARK: - Gemini exception is swallowed → 404


@pytest.mark.asyncio
async def test_resolve_from_search_404_when_gemini_raises(
    client, db_session, fake_redis
):
    """Gemini raising an exception is caught and surfaced as 404."""
    with (
        patch(
            "modules.m1_product.service.gemini_generate_json",
            new_callable=AsyncMock,
            side_effect=Exception("network glitch"),
        ),
        patch(
            "modules.m1_product.service.upcitemdb_lookup",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        response = await client.post(
            RESOLVE_FROM_SEARCH_URL,
            json={"device_name": "Apple iPhone 99"},
        )

    assert response.status_code == 404
    body = response.json()
    assert body["detail"]["error"]["code"] == "UPC_NOT_FOUND_FOR_PRODUCT"


# MARK: - Reuses persisted product on second call


# MARK: - Device→UPC Redis cache (skips Gemini + UPCitemdb on retry)


@pytest.mark.asyncio
async def test_resolve_from_search_writes_devupc_cache_on_success(
    client, db_session, fake_redis
):
    """A successful resolve writes the device→UPC mapping to Redis."""
    derived_upc = "190198451736"

    async def fake_gemini(prompt, **kwargs):
        # Mirror the existing happy-path test: dispatch on which prompt the
        # service passed (the device→UPC system text mentions "device
        # description"; the UPC→product one does not).
        system = kwargs.get("system_instruction", "") or ""
        # DEVICE_TO_UPC opens with "You receive a fully-specified product
        # description …" — a phrase absent from UPC_LOOKUP, which lets us
        # dispatch on which prompt the service passed.
        if "product description" in system:
            return {"upc": derived_upc, "reasoning": "verified"}
        return {"device_name": "Apple iPhone 8 64GB", "model": "iPhone 8"}

    with (
        patch(
            "modules.m1_product.service.gemini_generate_json",
            new_callable=AsyncMock,
            side_effect=fake_gemini,
        ),
        patch(
            "modules.m1_product.service.upcitemdb_lookup",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        response = await client.post(
            RESOLVE_FROM_SEARCH_URL,
            json={
                "device_name": "Apple iPhone 8 (64GB)",
                "brand": "Apple",
                "model": "iPhone 8",
            },
        )

    assert response.status_code == 200

    # Verify cache entry exists for the normalized name+brand pair.
    from modules.m1_product.service import ProductResolutionService
    cache_key = ProductResolutionService._devupc_cache_key(
        "Apple iPhone 8 (64GB)", "Apple"
    )
    cached = await fake_redis.get(cache_key)
    cached_str = cached if isinstance(cached, str) else cached.decode()
    assert cached_str == derived_upc


@pytest.mark.asyncio
async def test_resolve_from_search_devupc_cache_short_circuits_gemini(
    client, db_session, fake_redis
):
    """A pre-populated cache entry skips both Gemini and UPCitemdb calls."""
    cached_upc = "888888888888"
    existing = Product(
        upc=cached_upc, name="Cached Product", brand="Steam", source="seed"
    )
    db_session.add(existing)
    await db_session.flush()

    from modules.m1_product.service import ProductResolutionService
    cache_key = ProductResolutionService._devupc_cache_key(
        "Steam Deck OLED", "Valve"
    )
    await fake_redis.set(cache_key, cached_upc)

    gemini_mock = AsyncMock(return_value={"upc": None})
    upcitem_mock = AsyncMock(return_value=None)
    with (
        patch(
            "modules.m1_product.service.gemini_generate_json", gemini_mock,
        ),
        patch(
            "modules.m1_product.service.upcitemdb_lookup", upcitem_mock,
        ),
        patch(
            "modules.m1_product.upcitemdb.search_keyword",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        response = await client.post(
            RESOLVE_FROM_SEARCH_URL,
            json={"device_name": "Steam Deck OLED", "brand": "Valve"},
        )

    assert response.status_code == 200
    assert response.json()["upc"] == cached_upc
    # Cache hit means the device→UPC Gemini call must NOT fire. The downstream
    # `resolve()` is allowed to skip Gemini too because the product already
    # exists in DB.
    assert gemini_mock.call_count == 0


def test_devupc_cache_key_normalizes_whitespace_and_case():
    """Cache key normalizes case + whitespace so trivial variants share an entry."""
    from modules.m1_product.service import ProductResolutionService

    a = ProductResolutionService._devupc_cache_key("Steam Deck OLED", "Valve")
    b = ProductResolutionService._devupc_cache_key("  steam   DECK   oled  ", "VALVE")
    assert a == b


def test_devupc_cache_key_distinguishes_brand():
    """Different brands hash to different keys."""
    from modules.m1_product.service import ProductResolutionService

    same_name_diff_brand = (
        ProductResolutionService._devupc_cache_key("Pro Headphones", "Sony"),
        ProductResolutionService._devupc_cache_key("Pro Headphones", "Bose"),
    )
    assert same_name_diff_brand[0] != same_name_diff_brand[1]


@pytest.mark.asyncio
async def test_resolve_from_search_reuses_existing_product(
    client, db_session, fake_redis
):
    """If the derived UPC already exists in DB, the existing product is returned
    without a second cross-validation pass (hits the PG short-circuit in resolve).
    """
    existing_upc = "999000999000"
    existing = Product(
        upc=existing_upc,
        name="Old Product",
        brand="TestBrand",
        source="seed",
    )
    db_session.add(existing)
    await db_session.flush()
    existing_id = existing.id

    with (
        patch(
            "modules.m1_product.service.gemini_generate_json",
            new_callable=AsyncMock,
            return_value={"upc": existing_upc, "reasoning": "verified"},
        ) as mock_gemini,
        patch(
            "modules.m1_product.service.upcitemdb_lookup",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        response = await client.post(
            RESOLVE_FROM_SEARCH_URL,
            json={"device_name": "Old Product Latest Edition"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(existing_id)
    assert data["upc"] == existing_upc
    # Only the device→UPC Gemini call fires — PG hit short-circuits the rest.
    assert mock_gemini.call_count == 1
