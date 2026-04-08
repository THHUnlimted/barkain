"""Integration tests — end-to-end flows with mocked external dependencies.

Tests the full scan→resolve→prices pipeline through the HTTP API layer.
Gemini is mocked at the service level; containers at ContainerClient level.
"""

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.core_models import Retailer
from modules.m2_prices.schemas import (
    ContainerError,
    ContainerListing,
    ContainerResponse,
)

pytestmark = pytest.mark.asyncio


# MARK: - Helpers


async def _seed_retailers(db_session, retailer_ids: list[str]) -> None:
    """Create Retailer records for FK integrity."""
    for rid in retailer_ids:
        retailer = Retailer(
            id=rid,
            display_name=rid.replace("_", " ").title(),
            base_url=f"https://www.{rid}.com",
            extraction_method="agent_browser",
        )
        db_session.add(retailer)
    await db_session.flush()


def _make_container_response(
    retailer_id: str,
    price: float,
    original_price: float | None = None,
    condition: str = "new",
) -> ContainerResponse:
    """Build a successful ContainerResponse with one listing."""
    return ContainerResponse(
        retailer_id=retailer_id,
        query="Sony WH-1000XM5 Sony",
        extraction_time_ms=1500,
        listings=[
            ContainerListing(
                title=f"Sony WH-1000XM5 from {retailer_id}",
                price=price,
                original_price=original_price,
                currency="USD",
                url=f"https://{retailer_id}.com/product/123",
                condition=condition,
                is_available=True,
            )
        ],
    )


def _make_error_response(retailer_id: str) -> ContainerResponse:
    """Build a failed ContainerResponse."""
    return ContainerResponse(
        retailer_id=retailer_id,
        query="Sony WH-1000XM5 Sony",
        error=ContainerError(code="CONNECTION_FAILED", message="timeout"),
    )


GEMINI_PRODUCT_DATA = {
    "name": "Sony WH-1000XM5",
    "brand": "Sony",
    "category": "headphones",
    "description": "Wireless noise-cancelling headphones",
    "image_url": "https://example.com/xm5.jpg",
    "asin": "B0BSHPJHJ4",
}

ALL_RETAILER_IDS = [
    "amazon", "best_buy", "walmart", "target", "home_depot",
    "lowes", "ebay_new", "ebay_used", "sams_club", "backmarket",
    "fb_marketplace",
]


# MARK: - Full Flow Tests


async def test_full_flow_scan_resolve_then_prices(client, db_session):
    """POST /resolve → product created → GET /prices → sorted prices returned."""
    await _seed_retailers(db_session, ["amazon", "walmart", "target"])

    mock_responses = {
        "amazon": _make_container_response("amazon", 278.00),
        "walmart": _make_container_response("walmart", 289.99),
        "target": _make_container_response("target", 299.99),
    }

    # Step 1: Resolve product
    with patch(
        "modules.m1_product.service.gemini_generate_json",
        new_callable=AsyncMock,
        return_value=GEMINI_PRODUCT_DATA,
    ):
        resolve_resp = await client.post(
            "/api/v1/products/resolve",
            json={"upc": "012345678901"},
        )

    assert resolve_resp.status_code == 200
    product_data = resolve_resp.json()
    product_id = product_data["id"]
    assert product_data["name"] == "Sony WH-1000XM5"

    # Step 2: Get prices
    with patch(
        "modules.m2_prices.service.ContainerClient"
    ) as MockClient:
        instance = MockClient.return_value
        instance.extract_all = AsyncMock(return_value=mock_responses)

        prices_resp = await client.get(f"/api/v1/prices/{product_id}")

    assert prices_resp.status_code == 200
    prices_data = prices_resp.json()
    assert prices_data["product_id"] == product_id
    assert len(prices_data["prices"]) == 3
    assert prices_data["retailers_succeeded"] == 3
    assert prices_data["retailers_failed"] == 0
    # Verify sorted ascending
    price_values = [p["price"] for p in prices_data["prices"]]
    assert price_values == sorted(price_values)


async def test_full_flow_empty_product_name(client, db_session):
    """Product with name but no brand still resolves and fetches prices."""
    await _seed_retailers(db_session, ["amazon"])

    gemini_data = {
        "name": "Unknown Gadget",
        "brand": None,
        "category": None,
    }

    with patch(
        "modules.m1_product.service.gemini_generate_json",
        new_callable=AsyncMock,
        return_value=gemini_data,
    ):
        resolve_resp = await client.post(
            "/api/v1/products/resolve",
            json={"upc": "111111111111"},
        )

    assert resolve_resp.status_code == 200
    product_id = resolve_resp.json()["id"]

    mock_responses = {
        "amazon": _make_container_response("amazon", 49.99),
    }

    with patch(
        "modules.m2_prices.service.ContainerClient"
    ) as MockClient:
        instance = MockClient.return_value
        instance.extract_all = AsyncMock(return_value=mock_responses)

        prices_resp = await client.get(f"/api/v1/prices/{product_id}")

    assert prices_resp.status_code == 200
    assert len(prices_resp.json()["prices"]) == 1


async def test_full_flow_missing_asin(client, db_session):
    """Product without ASIN field still resolves and prices work."""
    await _seed_retailers(db_session, ["walmart"])

    gemini_data = {
        "name": "Generic Speaker",
        "brand": "Acme",
        "category": "speakers",
    }

    with patch(
        "modules.m1_product.service.gemini_generate_json",
        new_callable=AsyncMock,
        return_value=gemini_data,
    ):
        resolve_resp = await client.post(
            "/api/v1/products/resolve",
            json={"upc": "222222222222"},
        )

    assert resolve_resp.status_code == 200
    product_id = resolve_resp.json()["id"]
    assert resolve_resp.json().get("asin") is None

    mock_responses = {
        "walmart": _make_container_response("walmart", 39.99),
    }

    with patch(
        "modules.m2_prices.service.ContainerClient"
    ) as MockClient:
        instance = MockClient.return_value
        instance.extract_all = AsyncMock(return_value=mock_responses)

        prices_resp = await client.get(f"/api/v1/prices/{product_id}")

    assert prices_resp.status_code == 200
    assert prices_resp.json()["retailers_succeeded"] == 1


async def test_full_flow_all_containers_timeout(client, db_session):
    """All 11 containers failing returns 200 with empty prices."""
    await _seed_retailers(db_session, ALL_RETAILER_IDS)

    # Resolve a product first
    with patch(
        "modules.m1_product.service.gemini_generate_json",
        new_callable=AsyncMock,
        return_value=GEMINI_PRODUCT_DATA,
    ):
        resolve_resp = await client.post(
            "/api/v1/products/resolve",
            json={"upc": "333333333333"},
        )

    product_id = resolve_resp.json()["id"]

    mock_responses = {rid: _make_error_response(rid) for rid in ALL_RETAILER_IDS}

    with patch(
        "modules.m2_prices.service.ContainerClient"
    ) as MockClient:
        instance = MockClient.return_value
        instance.extract_all = AsyncMock(return_value=mock_responses)

        prices_resp = await client.get(f"/api/v1/prices/{product_id}")

    assert prices_resp.status_code == 200
    data = prices_resp.json()
    assert data["prices"] == []
    assert data["retailers_failed"] == 11
    assert data["retailers_succeeded"] == 0


async def test_full_flow_partial_results(client, db_session):
    """3/11 succeed, 8 fail — correct counts and prices."""
    await _seed_retailers(db_session, ALL_RETAILER_IDS)

    with patch(
        "modules.m1_product.service.gemini_generate_json",
        new_callable=AsyncMock,
        return_value=GEMINI_PRODUCT_DATA,
    ):
        resolve_resp = await client.post(
            "/api/v1/products/resolve",
            json={"upc": "444444444444"},
        )

    product_id = resolve_resp.json()["id"]

    mock_responses = {}
    succeeding = ["amazon", "walmart", "target"]
    for rid in ALL_RETAILER_IDS:
        if rid in succeeding:
            mock_responses[rid] = _make_container_response(rid, 100.00 + len(rid))
        else:
            mock_responses[rid] = _make_error_response(rid)

    with patch(
        "modules.m2_prices.service.ContainerClient"
    ) as MockClient:
        instance = MockClient.return_value
        instance.extract_all = AsyncMock(return_value=mock_responses)

        prices_resp = await client.get(f"/api/v1/prices/{product_id}")

    data = prices_resp.json()
    assert data["retailers_succeeded"] == 3
    assert data["retailers_failed"] == 8
    assert len(data["prices"]) == 3


async def test_full_flow_duplicate_upc_uses_cache(client, db_session, fake_redis):
    """Second resolve for same UPC returns cached product, no Gemini call."""
    # First resolve
    with patch(
        "modules.m1_product.service.gemini_generate_json",
        new_callable=AsyncMock,
        return_value=GEMINI_PRODUCT_DATA,
    ) as mock_gemini:
        resp1 = await client.post(
            "/api/v1/products/resolve",
            json={"upc": "555555555555"},
        )
        assert resp1.status_code == 200
        assert mock_gemini.call_count == 1

    product_id_1 = resp1.json()["id"]

    # Second resolve — should hit Redis cache, no Gemini call
    with patch(
        "modules.m1_product.service.gemini_generate_json",
        new_callable=AsyncMock,
        return_value=GEMINI_PRODUCT_DATA,
    ) as mock_gemini_2:
        resp2 = await client.post(
            "/api/v1/products/resolve",
            json={"upc": "555555555555"},
        )
        assert resp2.status_code == 200
        mock_gemini_2.assert_not_called()

    assert resp2.json()["id"] == product_id_1


async def test_full_flow_force_refresh(client, db_session, fake_redis):
    """force_refresh=true re-dispatches containers even with cached data."""
    await _seed_retailers(db_session, ["amazon"])

    with patch(
        "modules.m1_product.service.gemini_generate_json",
        new_callable=AsyncMock,
        return_value=GEMINI_PRODUCT_DATA,
    ):
        resolve_resp = await client.post(
            "/api/v1/products/resolve",
            json={"upc": "666666666666"},
        )

    product_id = resolve_resp.json()["id"]

    # Seed Redis with stale cache
    stale_cache = {
        "product_id": product_id,
        "product_name": "Sony WH-1000XM5",
        "prices": [],
        "total_retailers": 0,
        "retailers_succeeded": 0,
        "retailers_failed": 0,
        "cached": True,
        "fetched_at": "2026-04-01T00:00:00+00:00",
    }
    await fake_redis.set(f"prices:product:{product_id}", json.dumps(stale_cache))

    mock_responses = {
        "amazon": _make_container_response("amazon", 278.00),
    }

    with patch(
        "modules.m2_prices.service.ContainerClient"
    ) as MockClient:
        instance = MockClient.return_value
        instance.extract_all = AsyncMock(return_value=mock_responses)

        prices_resp = await client.get(
            f"/api/v1/prices/{product_id}?force_refresh=true"
        )

    assert prices_resp.status_code == 200
    data = prices_resp.json()
    assert data["cached"] is False
    assert len(data["prices"]) == 1
    instance.extract_all.assert_called_once()


# MARK: - Error Format Audit


async def test_error_format_health_no_auth(unauthed_client):
    """GET /health succeeds without auth and returns status field."""
    resp = await unauthed_client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data


async def test_error_format_401_unauthorized(unauthed_client):
    """GET /prices without auth returns 401 with structured error."""
    fake_id = uuid.uuid4()
    resp = await unauthed_client.get(f"/api/v1/prices/{fake_id}")
    assert resp.status_code == 401
    data = resp.json()
    assert data["detail"]["error"]["code"] == "UNAUTHORIZED"


async def test_error_format_404_product(client):
    """GET /prices with nonexistent product returns 404 structured error."""
    fake_id = uuid.uuid4()
    resp = await client.get(f"/api/v1/prices/{fake_id}")
    assert resp.status_code == 404
    data = resp.json()
    assert data["detail"]["error"]["code"] == "PRODUCT_NOT_FOUND"


async def test_error_format_422_invalid_upc(client):
    """POST /resolve with invalid UPC returns 422."""
    resp = await client.post(
        "/api/v1/products/resolve",
        json={"upc": "abc"},
    )
    assert resp.status_code == 422


async def test_error_format_422_invalid_uuid(client):
    """GET /prices with malformed UUID returns 422."""
    resp = await client.get("/api/v1/prices/not-a-uuid")
    assert resp.status_code == 422
