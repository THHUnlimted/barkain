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


# MARK: - cat-rel-1-L2-ux: Gemini reasoning surfaces in 404 envelope


@pytest.mark.asyncio
async def test_resolve_from_search_404_includes_gemini_reasoning_in_details(
    client, db_session, fake_redis
):
    """When Gemini refused with a stated reason, the 404 envelope's
    ``details.reasoning`` carries that string so iOS can show *why* the
    product couldn't be pinned (multi-variant SKU, dealer-only stock,
    discontinued line) instead of the generic copy. cat-rel-1-L2-ux.
    """
    refusal_reason = (
        "Multiple SKU variants exist for this Husqvarna model — please "
        "scan the barcode for an exact match."
    )
    with (
        patch(
            "modules.m1_product.service.gemini_generate_json",
            new_callable=AsyncMock,
            return_value={"upc": None, "reasoning": refusal_reason},
        ),
        patch(
            "modules.m1_product.service.upcitemdb_lookup",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        response = await client.post(
            RESOLVE_FROM_SEARCH_URL,
            json={"device_name": "Husqvarna 460 Rancher chainsaw"},
        )

    assert response.status_code == 404
    error = response.json()["detail"]["error"]
    assert error["code"] == "UPC_NOT_FOUND_FOR_PRODUCT"
    # Reasoning is the load-bearing assertion — it must reach the client.
    assert error["details"]["reasoning"] == refusal_reason
    # Existing device_name details field is still preserved.
    assert error["details"]["device_name"] == "Husqvarna 460 Rancher chainsaw"


@pytest.mark.asyncio
async def test_resolve_from_search_404_omits_reasoning_when_gemini_silent(
    client, db_session, fake_redis
):
    """When Gemini returned null UPC AND null reasoning (or transport
    failure), the 404 envelope should NOT have a ``reasoning`` key. iOS
    falls back to the generic 'couldn't find this one' copy in that case.
    """
    with (
        patch(
            "modules.m1_product.service.gemini_generate_json",
            new_callable=AsyncMock,
            side_effect=Exception("transport flake"),
        ),
        patch(
            "modules.m1_product.service.upcitemdb_lookup",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        response = await client.post(
            RESOLVE_FROM_SEARCH_URL,
            json={"device_name": "Untraceable Gadget 9000"},
        )

    assert response.status_code == 404
    error = response.json()["detail"]["error"]
    assert error["code"] == "UPC_NOT_FOUND_FOR_PRODUCT"
    # Absence is the assertion: iOS branches on `details.reasoning` being
    # nil to choose the generic copy.
    assert "reasoning" not in error["details"]


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
    cached_upc = "888888888889"
    existing = Product(
        upc=cached_upc,
        name="Valve Steam Deck OLED 1TB",
        brand="Valve",
        source="seed",
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


# MARK: - demo-prep-1 Item 3: confidence gate + /confirm endpoint


CONFIRM_URL = "/api/v1/products/resolve-from-search/confirm"


@pytest.mark.asyncio
async def test_resolve_from_search_409_below_confidence_threshold(
    client, db_session, fake_redis
):
    """Client forwards a low-confidence value → router short-circuits with
    409 RESOLUTION_NEEDS_CONFIRMATION before any Gemini call fires."""
    with (
        patch(
            "modules.m1_product.service.gemini_generate_json",
            new_callable=AsyncMock,
            return_value={"upc": "190198451736"},
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
                "device_name": "Mystery Gadget Pro",
                "brand": None,
                "model": None,
                "confidence": 0.42,
            },
        )

    assert response.status_code == 409
    body = response.json()
    assert body["detail"]["error"]["code"] == "RESOLUTION_NEEDS_CONFIRMATION"
    details = body["detail"]["error"]["details"]
    assert details["device_name"] == "Mystery Gadget Pro"
    assert details["confidence"] == 0.42
    # Threshold is exposed in the 409 body so the client can differentiate
    # from other 409s and also surface it in debug builds.
    assert "threshold" in details
    # Gate fires BEFORE any service call — zero Gemini invocations on a 409.
    assert mock_gemini.call_count == 0


@pytest.mark.asyncio
async def test_resolve_from_search_200_when_confidence_above_threshold(
    client, db_session, fake_redis
):
    """High-confidence resolution path remains unchanged — the gate only
    fires below the threshold (default 0.70)."""
    derived_upc = "190198451736"

    async def fake_gemini(prompt, **kwargs):
        system = kwargs.get("system_instruction", "") or ""
        if "device description" in system or "canonical 12-" in system or "Universal Product Code" not in system:
            return {"upc": derived_upc, "reasoning": "high-confidence match"}
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
                "confidence": 0.91,
            },
        )

    assert response.status_code == 200, response.text
    assert response.json()["upc"] == derived_upc


@pytest.mark.asyncio
async def test_resolve_from_search_200_when_confidence_omitted(
    client, db_session, fake_redis
):
    """Backwards compat: clients that predate demo-prep-1 (no confidence
    field) continue to get the pre-gate behavior — no 409s, resolution
    runs unconditionally."""
    derived_upc = "190198451736"

    async def fake_gemini(prompt, **kwargs):
        system = kwargs.get("system_instruction", "") or ""
        if "device description" in system or "canonical 12-" in system or "Universal Product Code" not in system:
            return {"upc": derived_upc}
        return {"device_name": "Legacy Product", "model": None}

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
            json={"device_name": "Legacy Product"},  # no confidence field
        )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_confirm_user_confirmed_true_runs_resolution_and_marks_flag(
    client, db_session, fake_redis
):
    """user_confirmed=true → runs resolution, marks source_raw.user_confirmed=True."""
    derived_upc = "190198451736"

    async def fake_gemini(prompt, **kwargs):
        system = kwargs.get("system_instruction", "") or ""
        if "device description" in system or "canonical 12-" in system or "Universal Product Code" not in system:
            return {"upc": derived_upc}
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
            CONFIRM_URL,
            json={
                "device_name": "Apple iPhone 8 (64GB)",
                "brand": "Apple",
                "model": "iPhone 8",
                "user_confirmed": True,
                "query": "iphone 8",
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["logged"] is True
    assert body["product"] is not None
    assert body["product"]["upc"] == derived_upc

    # Verify the persistent flag landed in source_raw — future scans of the
    # same canonical product can skip the confirmation dialog.
    from sqlalchemy import select

    stmt = select(Product).where(Product.upc == derived_upc)
    result = await db_session.execute(stmt)
    product = result.scalar_one()
    assert isinstance(product.source_raw, dict)
    assert product.source_raw.get("user_confirmed") is True


@pytest.mark.asyncio
async def test_confirm_user_confirmed_false_logs_and_returns_empty(
    client, db_session, fake_redis
):
    """user_confirmed=false → no resolution, no product persisted, returns
    empty product + logged=True for telemetry."""
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
        response = await client.post(
            CONFIRM_URL,
            json={
                "device_name": "Mystery Gadget Pro",
                "user_confirmed": False,
                "query": "mystery gadget",
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["product"] is None
    assert body["logged"] is True
    # Rejection path must NOT touch any resolution backend — neither Gemini
    # nor UPCitemdb should be called.
    assert mock_gemini.call_count == 0
    assert mock_upcitemdb.call_count == 0


# MARK: - L4 post-resolve sanity check (cat-rel-1-L4)


def test_resolved_matches_query_passes_when_specs_and_brand_align():
    """Happy path: brand + strict-spec match → True."""
    from modules.m1_product.service import _resolved_matches_query

    assert _resolved_matches_query(
        query="Vitamix 5200",
        query_brand="Vitamix",
        resolved_name="Vitamix 5200 Variable Speed Blender",
        resolved_brand="Vitamix",
    ) is True


def test_resolved_matches_query_rejects_pure_digit_drift():
    """4+digit pure-numeric model in query missing from resolved name → False.

    UPCitemdb maps 703113640681 to Vitamix Explorian E310; pre-fix the
    user got E310 prices for a 5200 query.
    """
    from modules.m1_product.service import _resolved_matches_query

    assert _resolved_matches_query(
        query="Vitamix 5200",
        query_brand="Vitamix",
        resolved_name="Vitamix Explorian E310 Series Blender",
        resolved_brand="Vitamix",
    ) is False


def test_resolved_matches_query_rejects_voltage_drift():
    """Voltage spec drift (40V → 80V) → False."""
    from modules.m1_product.service import _resolved_matches_query

    assert _resolved_matches_query(
        query="Greenworks 40V Mower",
        query_brand="Greenworks",
        resolved_name="Greenworks 80V Backpack Blower",
        resolved_brand="Greenworks",
    ) is False


def test_resolved_matches_query_rejects_brand_mismatch():
    """Query brand absent from resolved haystack → False (Toro→Greenworks)."""
    from modules.m1_product.service import _resolved_matches_query

    assert _resolved_matches_query(
        query="Toro Recycler",
        query_brand="Toro",
        resolved_name="Greenworks 21-Inch Push Mower",
        resolved_brand="Greenworks",
    ) is False


def test_resolved_matches_query_falls_back_to_query_leading_token_when_brand_absent():
    """No brand param → leading meaningful query token serves as brand check."""
    from modules.m1_product.service import _resolved_matches_query

    assert _resolved_matches_query(
        query="Vitamix 5200",
        query_brand=None,
        resolved_name="Explorian E310 Series Blender",
        resolved_brand=None,
    ) is False


def test_resolved_matches_query_passes_with_no_strict_specs():
    """Query has no voltage or 4+digit token → only brand gate runs."""
    from modules.m1_product.service import _resolved_matches_query

    # iPhone 16: "16" is 2 digits, below the 4-digit floor → no strict spec.
    assert _resolved_matches_query(
        query="iPhone 16 Pro",
        query_brand="Apple",
        resolved_name="Apple iPhone 16 Pro 256GB",
        resolved_brand="Apple",
    ) is True


def test_resolved_matches_query_passes_when_brand_in_resolved_name_only():
    """Brand check uses name+brand haystack, not just resolved_brand field."""
    from modules.m1_product.service import _resolved_matches_query

    # UPCitemdb sometimes returns an empty brand field but keeps the brand
    # in the name string ("Anker Soundcore Q30 Headphones", brand=None).
    assert _resolved_matches_query(
        query="Anker Q30",
        query_brand="Anker",
        resolved_name="Anker Soundcore Q30 Wireless Headphones",
        resolved_brand=None,
    ) is True


@pytest.mark.asyncio
async def test_resolve_from_search_404_when_resolved_drifts_on_voltage(
    client, db_session, fake_redis
):
    """Greenworks 40V query → upstream resolves to 80V backpack blower → 404.

    Catches `cat-rel-1-L4`: UPCitemdb maps 841821092511 to Greenworks 80V
    even when the user asked for the 40V mower.
    """
    derived_upc = "841821092511"

    async def fake_gemini(prompt, **kwargs):
        system = kwargs.get("system_instruction", "") or ""
        if "Universal Product Code" not in system:
            return {"upc": derived_upc, "reasoning": "matched"}
        return {
            "device_name": "Greenworks 80V Backpack Blower",
            "model": "BPB80L01",
        }

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
                "device_name": "Greenworks 40V Mower",
                "brand": "Greenworks",
            },
        )

    assert response.status_code == 404
    body = response.json()
    assert body["detail"]["error"]["code"] == "UPC_NOT_FOUND_FOR_PRODUCT"


@pytest.mark.asyncio
async def test_resolve_from_search_404_when_resolved_drifts_on_pure_digit_model(
    client, db_session, fake_redis
):
    """Vitamix 5200 query → upstream resolves to Explorian E310 → 404."""
    derived_upc = "703113640681"

    async def fake_gemini(prompt, **kwargs):
        system = kwargs.get("system_instruction", "") or ""
        if "Universal Product Code" not in system:
            return {"upc": derived_upc, "reasoning": "matched"}
        return {
            "device_name": "Vitamix Explorian E310 Series Blender",
            "model": "E310",
        }

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
            json={"device_name": "Vitamix 5200", "brand": "Vitamix"},
        )

    assert response.status_code == 404
    body = response.json()
    assert body["detail"]["error"]["code"] == "UPC_NOT_FOUND_FOR_PRODUCT"


@pytest.mark.asyncio
async def test_gemini_null_logs_reasoning_for_obscure_sku_diagnosis(
    client, db_session, fake_redis, caplog
):
    """When Gemini returns null on the retry pass, its stated reason is
    logged. This is the only diagnostic signal for cat-rel-1-L2 cases
    (Husqvarna 130BT, ASUS Chromebook CX1) where the SKU is genuinely
    unverifiable. Forcing a UPC here is rejected — Gemini correctly
    refuses to guess, per the prompt's anti-hallucination contract.
    """
    import logging

    null_reason = (
        "Major US retailers do not currently stock the Husqvarna 130BT, "
        "and search results only return the model number 965102208."
    )

    async def fake_gemini(prompt, **kwargs):
        # Both passes return null, with reasoning explaining why.
        return {"upc": None, "reasoning": null_reason}

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
        patch(
            "modules.m1_product.upcitemdb.search_keyword",
            new_callable=AsyncMock,
            return_value=[],
        ),
        caplog.at_level(logging.INFO, logger="barkain.m1"),
    ):
        response = await client.post(
            RESOLVE_FROM_SEARCH_URL,
            json={
                "device_name": "Husqvarna 130BT 29.5cc Backpack Leaf Blower",
                "brand": "Husqvarna",
                "model": "130BT",
            },
        )

    assert response.status_code == 404
    # Reasoning is on the retry-null log line.
    matched = [
        r for r in caplog.records
        if "could not resolve device→UPC after retry" in r.getMessage()
        and "Husqvarna 130BT" in r.getMessage()
        and "Major US retailers do not currently stock" in r.getMessage()
    ]
    assert matched, (
        "Gemini's null-reasoning must be in the log line for cat-rel-1-L2 diagnosis. "
        f"Got: {[r.getMessage() for r in caplog.records]}"
    )


@pytest.mark.asyncio
async def test_resolve_from_search_invalidates_bad_cache_entry(
    client, db_session, fake_redis
):
    """A pre-fix cached UPC pointing at a wrong canonical → rejected, key deleted.

    Pre-fix Redis entries can map (Vitamix 5200) → 703113640681 (E310).
    On cache hit the resolve still runs through the sanity check and
    deletes the bad entry so the next attempt re-fires both upstreams.
    """
    cached_upc = "703113640681"
    existing = Product(
        upc=cached_upc,
        name="Vitamix Explorian E310 Series Blender",
        brand="Vitamix",
        source="seed",
    )
    db_session.add(existing)
    await db_session.flush()

    from modules.m1_product.service import ProductResolutionService
    cache_key = ProductResolutionService._devupc_cache_key("Vitamix 5200", "Vitamix")
    await fake_redis.set(cache_key, cached_upc)

    with (
        patch(
            "modules.m1_product.service.gemini_generate_json",
            new_callable=AsyncMock,
            return_value={"upc": None},
        ),
        patch(
            "modules.m1_product.service.upcitemdb_lookup",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        response = await client.post(
            RESOLVE_FROM_SEARCH_URL,
            json={"device_name": "Vitamix 5200", "brand": "Vitamix"},
        )

    assert response.status_code == 404
    assert await fake_redis.get(cache_key) is None
