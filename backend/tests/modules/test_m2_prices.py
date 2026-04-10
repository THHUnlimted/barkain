"""Tests for M2 Price Aggregation — service + endpoint."""

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.core_models import Retailer
from modules.m1_product.models import Product
from modules.m2_prices.models import Price, PriceHistory
from modules.m2_prices.schemas import (
    ContainerError,
    ContainerListing,
    ContainerResponse,
)

pytestmark = pytest.mark.asyncio


# MARK: - Helpers


async def _seed_product(db_session) -> Product:
    """Create a test product and flush to DB."""
    product = Product(
        name="Sony WH-1000XM5",
        brand="Sony",
        upc="012345678901",
        category="headphones",
        source="test",
    )
    db_session.add(product)
    await db_session.flush()
    return product


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


# MARK: - Cache Miss → Container Dispatch


async def test_cache_miss_dispatches_containers(client, db_session):
    """Cache miss triggers container dispatch, prices returned."""
    product = await _seed_product(db_session)
    await _seed_retailers(db_session, ["amazon", "walmart", "target"])

    mock_responses = {
        "amazon": _make_container_response("amazon", 278.00),
        "walmart": _make_container_response("walmart", 289.99),
        "target": _make_container_response("target", 299.99),
    }

    with patch(
        "modules.m2_prices.service.ContainerClient"
    ) as MockClient:
        instance = MockClient.return_value
        instance.extract_all = AsyncMock(return_value=mock_responses)

        resp = await client.get(f"/api/v1/prices/{product.id}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["cached"] is False
    assert data["retailers_succeeded"] == 3
    assert data["retailers_failed"] == 0
    assert len(data["prices"]) == 3
    assert data["product_name"] == "Sony WH-1000XM5"


# MARK: - Cache Hit (Redis)


async def test_redis_cache_hit(client, db_session, fake_redis):
    """Redis cache hit returns cached data without dispatching."""
    product = await _seed_product(db_session)

    cached_data = {
        "product_id": str(product.id),
        "product_name": "Sony WH-1000XM5",
        "prices": [
            {
                "retailer_id": "amazon",
                "retailer_name": "Amazon",
                "price": 278.00,
                "original_price": None,
                "currency": "USD",
                "url": "https://amazon.com/product",
                "condition": "new",
                "is_available": True,
                "is_on_sale": False,
                "last_checked": "2026-04-07T18:00:00+00:00",
            }
        ],
        "total_retailers": 11,
        "retailers_succeeded": 8,
        "retailers_failed": 3,
        "cached": True,
        "fetched_at": "2026-04-07T18:00:00+00:00",
    }
    await fake_redis.set(
        f"prices:product:{product.id}", json.dumps(cached_data)
    )

    with patch(
        "modules.m2_prices.service.ContainerClient"
    ) as MockClient:
        instance = MockClient.return_value
        instance.extract_all = AsyncMock()

        resp = await client.get(f"/api/v1/prices/{product.id}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["cached"] is True
    instance.extract_all.assert_not_called()


# MARK: - Cache Hit (DB, Redis miss)


async def test_db_cache_hit_backfills_redis(client, db_session, fake_redis):
    """Fresh DB prices serve response and backfill Redis."""
    product = await _seed_product(db_session)
    await _seed_retailers(db_session, ["amazon"])

    from datetime import UTC, datetime
    from decimal import Decimal

    # Seed a fresh price in DB
    price_record = Price(
        product_id=product.id,
        retailer_id="amazon",
        price=Decimal("278.00"),
        currency="USD",
        condition="new",
        is_available=True,
        is_on_sale=False,
        last_checked=datetime.now(UTC),
    )
    db_session.add(price_record)
    await db_session.flush()

    with patch(
        "modules.m2_prices.service.ContainerClient"
    ) as MockClient:
        instance = MockClient.return_value
        instance.extract_all = AsyncMock()

        resp = await client.get(f"/api/v1/prices/{product.id}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["cached"] is True
    instance.extract_all.assert_not_called()

    # Verify Redis was backfilled
    redis_val = await fake_redis.get(f"prices:product:{product.id}")
    assert redis_val is not None


# MARK: - Force Refresh


async def test_force_refresh_bypasses_cache(client, db_session, fake_redis):
    """force_refresh=true dispatches even when cache exists."""
    product = await _seed_product(db_session)
    await _seed_retailers(db_session, ["amazon"])

    # Pre-populate Redis
    cached_data = {
        "product_id": str(product.id),
        "product_name": "Sony WH-1000XM5",
        "prices": [],
        "total_retailers": 0,
        "retailers_succeeded": 0,
        "retailers_failed": 0,
        "cached": True,
        "fetched_at": "2026-04-07T18:00:00+00:00",
    }
    await fake_redis.set(
        f"prices:product:{product.id}", json.dumps(cached_data)
    )

    mock_responses = {
        "amazon": _make_container_response("amazon", 278.00),
    }

    with patch(
        "modules.m2_prices.service.ContainerClient"
    ) as MockClient:
        instance = MockClient.return_value
        instance.extract_all = AsyncMock(return_value=mock_responses)

        resp = await client.get(
            f"/api/v1/prices/{product.id}?force_refresh=true"
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["cached"] is False
    instance.extract_all.assert_called_once()


# MARK: - Sorting


async def test_prices_sorted_ascending(client, db_session):
    """Prices are returned sorted by price ascending (lowest first)."""
    product = await _seed_product(db_session)
    await _seed_retailers(db_session, ["amazon", "walmart", "target"])

    mock_responses = {
        "amazon": _make_container_response("amazon", 500.00),
        "walmart": _make_container_response("walmart", 200.00),
        "target": _make_container_response("target", 800.00),
    }

    with patch(
        "modules.m2_prices.service.ContainerClient"
    ) as MockClient:
        instance = MockClient.return_value
        instance.extract_all = AsyncMock(return_value=mock_responses)

        resp = await client.get(f"/api/v1/prices/{product.id}")

    data = resp.json()
    prices = [p["price"] for p in data["prices"]]
    assert prices == sorted(prices)
    assert prices == [200.00, 500.00, 800.00]


# MARK: - Partial Failure


async def test_partial_failure_correct_counts(client, db_session):
    """Partial container failures report correct succeeded/failed counts."""
    product = await _seed_product(db_session)
    await _seed_retailers(db_session, ["amazon", "walmart", "target"])

    mock_responses = {
        "amazon": _make_container_response("amazon", 278.00),
        "walmart": _make_container_response("walmart", 289.99),
        "target": _make_error_response("target"),
    }

    with patch(
        "modules.m2_prices.service.ContainerClient"
    ) as MockClient:
        instance = MockClient.return_value
        instance.extract_all = AsyncMock(return_value=mock_responses)

        resp = await client.get(f"/api/v1/prices/{product.id}")

    data = resp.json()
    assert data["retailers_succeeded"] == 2
    assert data["retailers_failed"] == 1
    assert len(data["prices"]) == 2


async def test_all_containers_fail_empty_prices(client, db_session):
    """All containers failing returns empty prices with correct counts."""
    product = await _seed_product(db_session)
    await _seed_retailers(db_session, ["amazon", "walmart", "target"])

    mock_responses = {
        "amazon": _make_error_response("amazon"),
        "walmart": _make_error_response("walmart"),
        "target": _make_error_response("target"),
    }

    with patch(
        "modules.m2_prices.service.ContainerClient"
    ) as MockClient:
        instance = MockClient.return_value
        instance.extract_all = AsyncMock(return_value=mock_responses)

        resp = await client.get(f"/api/v1/prices/{product.id}")

    data = resp.json()
    assert data["retailers_succeeded"] == 0
    assert data["retailers_failed"] == 3
    assert data["prices"] == []


# MARK: - Price History


async def test_price_history_records_created(client, db_session):
    """Container dispatch creates price_history records."""
    product = await _seed_product(db_session)
    await _seed_retailers(db_session, ["amazon", "walmart"])

    mock_responses = {
        "amazon": _make_container_response("amazon", 278.00),
        "walmart": _make_container_response("walmart", 289.99),
    }

    with patch(
        "modules.m2_prices.service.ContainerClient"
    ) as MockClient:
        instance = MockClient.return_value
        instance.extract_all = AsyncMock(return_value=mock_responses)

        resp = await client.get(f"/api/v1/prices/{product.id}")

    assert resp.status_code == 200

    from sqlalchemy import select, func

    result = await db_session.execute(
        select(func.count()).select_from(PriceHistory).where(
            PriceHistory.product_id == product.id
        )
    )
    count = result.scalar()
    assert count == 2


# MARK: - Upsert (Idempotency)


async def test_upsert_no_duplicates(client, db_session):
    """Calling twice with force_refresh produces no duplicate price rows."""
    product = await _seed_product(db_session)
    await _seed_retailers(db_session, ["amazon", "walmart"])

    mock_responses = {
        "amazon": _make_container_response("amazon", 278.00),
        "walmart": _make_container_response("walmart", 289.99),
    }

    with patch(
        "modules.m2_prices.service.ContainerClient"
    ) as MockClient:
        instance = MockClient.return_value
        instance.extract_all = AsyncMock(return_value=mock_responses)

        await client.get(f"/api/v1/prices/{product.id}")
        await client.get(
            f"/api/v1/prices/{product.id}?force_refresh=true"
        )

    from sqlalchemy import select, func

    result = await db_session.execute(
        select(func.count()).select_from(Price).where(
            Price.product_id == product.id
        )
    )
    count = result.scalar()
    assert count == 2  # One per retailer, not 4


# MARK: - is_on_sale Computation


async def test_is_on_sale_computed_correctly(client, db_session):
    """is_on_sale is True when original_price > price, False otherwise."""
    product = await _seed_product(db_session)
    await _seed_retailers(db_session, ["amazon", "walmart"])

    mock_responses = {
        "amazon": _make_container_response(
            "amazon", 278.00, original_price=399.99
        ),
        "walmart": _make_container_response("walmart", 289.99),
    }

    with patch(
        "modules.m2_prices.service.ContainerClient"
    ) as MockClient:
        instance = MockClient.return_value
        instance.extract_all = AsyncMock(return_value=mock_responses)

        resp = await client.get(f"/api/v1/prices/{product.id}")

    data = resp.json()
    prices_by_retailer = {p["retailer_id"]: p for p in data["prices"]}
    assert prices_by_retailer["amazon"]["is_on_sale"] is True
    assert prices_by_retailer["walmart"]["is_on_sale"] is False


# MARK: - Error Cases


async def test_nonexistent_product_returns_404(client):
    """Non-existent product_id returns 404."""
    fake_id = uuid.uuid4()
    resp = await client.get(f"/api/v1/prices/{fake_id}")

    assert resp.status_code == 404
    data = resp.json()
    assert data["detail"]["error"]["code"] == "PRODUCT_NOT_FOUND"


async def test_malformed_uuid_returns_422(client):
    """Malformed UUID in path returns 422."""
    resp = await client.get("/api/v1/prices/not-a-uuid")
    assert resp.status_code == 422


async def test_auth_required_returns_401(unauthed_client):
    """Request without auth returns 401."""
    fake_id = uuid.uuid4()
    resp = await unauthed_client.get(f"/api/v1/prices/{fake_id}")
    assert resp.status_code == 401


# MARK: - Pre-Fix: Shorter Redis TTL for empty results


async def test_empty_results_get_shorter_redis_ttl(db_session, fake_redis):
    """When all containers fail (0 results), Redis TTL should be 30 minutes."""
    from modules.m2_prices.service import (
        PriceAggregationService,
        REDIS_CACHE_TTL_EMPTY,
        REDIS_KEY_PREFIX,
    )

    product = await _seed_product(db_session)
    await _seed_retailers(db_session, ["amazon"])

    # All containers return errors
    error_response = ContainerResponse(
        retailer_id="amazon",
        query="test",
        extraction_time_ms=100,
        listings=[],
        error=ContainerError(code="TIMEOUT", message="timed out"),
    )
    mock_client = AsyncMock()
    mock_client.extract_all = AsyncMock(return_value={"amazon": error_response})

    service = PriceAggregationService(
        db=db_session, redis=fake_redis, container_client=mock_client,
    )
    await service.get_prices(product.id, force_refresh=True)

    # Verify shorter TTL was set
    key = f"{REDIS_KEY_PREFIX}{product.id}"
    ttl = await fake_redis.ttl(key)
    assert ttl <= REDIS_CACHE_TTL_EMPTY
    assert ttl > 0
