"""Tests for M2 Price Streaming (Step 2c) — SSE endpoint + stream_prices generator."""

import asyncio
import json
import uuid

import pytest

from app.core_models import Retailer
from modules.m1_product.models import Product
from modules.m2_prices.schemas import (
    ContainerError,
    ContainerListing,
    ContainerResponse,
)
from modules.m2_prices.service import PriceAggregationService


# MARK: - Helpers


async def _seed_product(db_session) -> Product:
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
    for rid in retailer_ids:
        retailer = Retailer(
            id=rid,
            display_name=rid.replace("_", " ").title(),
            base_url=f"https://www.{rid}.com",
            extraction_method="agent_browser",
        )
        db_session.add(retailer)
    await db_session.flush()


def _success_response(retailer_id: str, price: float = 299.99) -> ContainerResponse:
    return ContainerResponse(
        retailer_id=retailer_id,
        query="Sony WH-1000XM5 Sony",
        extraction_time_ms=1500,
        listings=[
            ContainerListing(
                title=f"Sony WH-1000XM5 Wireless Headphones from {retailer_id}",
                price=price,
                currency="USD",
                url=f"https://{retailer_id}.com/product/123",
                condition="new",
                is_available=True,
            )
        ],
    )


def _empty_response(retailer_id: str) -> ContainerResponse:
    return ContainerResponse(
        retailer_id=retailer_id,
        query="Sony WH-1000XM5 Sony",
        extraction_time_ms=1500,
        listings=[],
    )


def _error_response(retailer_id: str, code: str = "CONNECTION_FAILED") -> ContainerResponse:
    return ContainerResponse(
        retailer_id=retailer_id,
        query="Sony WH-1000XM5 Sony",
        error=ContainerError(code=code, message="simulated error"),
    )


class _FakeContainerClient:
    """Minimal stand-in for ContainerClient used in stream_prices tests.

    Exposes `ports` (iterated to discover retailers) and `_extract_one`
    (awaited per retailer). Optional per-retailer `delays_ms` lets tests
    force a specific completion order.
    """

    def __init__(
        self,
        responses: dict[str, ContainerResponse],
        delays_ms: dict[str, int] | None = None,
    ):
        # Ports dict doubles as the retailer list — values are unused in tests.
        self.ports = {rid: 8000 + i for i, rid in enumerate(responses)}
        self._responses = responses
        self._delays_ms = delays_ms or {}
        self.extract_one_calls: list[str] = []

    async def _extract_one(
        self,
        retailer_id: str,
        query: str,
        product_name: str | None,
        upc: str | None,
        max_listings: int,
    ) -> ContainerResponse:
        self.extract_one_calls.append(retailer_id)
        delay_ms = self._delays_ms.get(retailer_id, 0)
        if delay_ms:
            await asyncio.sleep(delay_ms / 1000)
        return self._responses[retailer_id]


async def _collect_events(service, product_id, force_refresh=False):
    events: list[tuple[str, dict]] = []
    async for event_type, payload in service.stream_prices(
        product_id, force_refresh=force_refresh
    ):
        events.append((event_type, payload))
    return events


async def _collect_sse_stream(response) -> list[tuple[str, dict]]:
    """Parse SSE wire bytes into (event_type, payload) tuples."""
    events: list[tuple[str, dict]] = []
    event_type: str | None = None
    data_lines: list[str] = []
    async for line in response.aiter_lines():
        if line == "":
            if data_lines:
                events.append((event_type, json.loads("\n".join(data_lines))))
            event_type, data_lines = None, []
        elif line.startswith("event:"):
            event_type = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].strip())
    # Flush any dangling event (stream closed without final blank line).
    if data_lines:
        events.append((event_type, json.loads("\n".join(data_lines))))
    return events


# MARK: - Service-level tests (stream_prices generator)


async def test_stream_yields_events_in_completion_order(db_session, fake_redis):
    """asyncio.as_completed should yield fastest retailer first."""
    product = await _seed_product(db_session)
    await _seed_retailers(db_session, ["amazon", "walmart", "best_buy"])

    fake = _FakeContainerClient(
        responses={
            "amazon": _success_response("amazon", 299.99),
            "walmart": _success_response("walmart", 289.99),
            "best_buy": _success_response("best_buy", 319.99),
        },
        delays_ms={"walmart": 5, "amazon": 15, "best_buy": 30},
    )
    service = PriceAggregationService(db=db_session, redis=fake_redis, container_client=fake)

    events = await _collect_events(service, product.id)

    retailer_events = [p["retailer_id"] for t, p in events if t == "retailer_result"]
    assert retailer_events == ["walmart", "amazon", "best_buy"]
    assert events[-1][0] == "done"
    assert events[-1][1]["retailers_succeeded"] == 3


async def test_stream_success_payload_contains_full_price(db_session, fake_redis):
    product = await _seed_product(db_session)
    await _seed_retailers(db_session, ["amazon"])

    fake = _FakeContainerClient(
        responses={"amazon": _success_response("amazon", 278.00)}
    )
    service = PriceAggregationService(db=db_session, redis=fake_redis, container_client=fake)

    events = await _collect_events(service, product.id)

    success = next(p for t, p in events if t == "retailer_result")
    assert success["status"] == "success"
    assert success["retailer_id"] == "amazon"
    assert success["price"] is not None
    assert success["price"]["price"] == 278.00
    assert success["price"]["currency"] == "USD"
    assert success["price"]["condition"] == "new"
    assert success["price"]["is_available"] is True
    assert "last_checked" in success["price"]


async def test_stream_empty_listings_yields_no_match(db_session, fake_redis):
    product = await _seed_product(db_session)
    await _seed_retailers(db_session, ["target"])

    fake = _FakeContainerClient(responses={"target": _empty_response("target")})
    service = PriceAggregationService(db=db_session, redis=fake_redis, container_client=fake)

    events = await _collect_events(service, product.id)

    retailer_evt = next(p for t, p in events if t == "retailer_result")
    assert retailer_evt["status"] == "no_match"
    assert retailer_evt["price"] is None
    assert events[-1][1]["retailers_failed"] == 1


async def test_stream_connection_failed_yields_unavailable(db_session, fake_redis):
    product = await _seed_product(db_session)
    await _seed_retailers(db_session, ["home_depot"])

    fake = _FakeContainerClient(
        responses={"home_depot": _error_response("home_depot", "CONNECTION_FAILED")}
    )
    service = PriceAggregationService(db=db_session, redis=fake_redis, container_client=fake)

    events = await _collect_events(service, product.id)

    retailer_evt = next(p for t, p in events if t == "retailer_result")
    assert retailer_evt["status"] == "unavailable"
    assert retailer_evt["price"] is None


async def test_stream_redis_cache_hit_short_circuits(db_session, fake_redis):
    """Cache hit replays all events without calling containers."""
    product = await _seed_product(db_session)
    await _seed_retailers(db_session, ["amazon", "walmart"])

    cached = {
        "product_id": str(product.id),
        "product_name": product.name,
        "prices": [
            {
                "retailer_id": "amazon",
                "retailer_name": "Amazon",
                "price": 278.00,
                "original_price": None,
                "currency": "USD",
                "url": "https://amazon.com/p",
                "condition": "new",
                "is_available": True,
                "is_on_sale": False,
                "last_checked": "2026-04-13T10:00:00+00:00",
            }
        ],
        "retailer_results": [
            {"retailer_id": "amazon", "retailer_name": "Amazon", "status": "success"},
            {"retailer_id": "walmart", "retailer_name": "Walmart", "status": "no_match"},
        ],
        "total_retailers": 2,
        "retailers_succeeded": 1,
        "retailers_failed": 1,
        "cached": True,
        "fetched_at": "2026-04-13T10:00:00+00:00",
    }
    await fake_redis.set(f"prices:product:{product.id}", json.dumps(cached))

    fake = _FakeContainerClient(
        responses={
            "amazon": _success_response("amazon"),
            "walmart": _empty_response("walmart"),
        }
    )
    service = PriceAggregationService(db=db_session, redis=fake_redis, container_client=fake)

    events = await _collect_events(service, product.id)

    # No container calls when cache hit
    assert fake.extract_one_calls == []
    # All cached retailers replayed
    retailer_events = [(p["retailer_id"], p["status"]) for t, p in events if t == "retailer_result"]
    assert ("amazon", "success") in retailer_events
    assert ("walmart", "no_match") in retailer_events
    # Success event has price, no_match has null
    for t, p in events:
        if t == "retailer_result":
            if p["status"] == "success":
                assert p["price"] is not None
                assert p["price"]["price"] == 278.00
            else:
                assert p["price"] is None
    # Done event marks cached
    done = next(p for t, p in events if t == "done")
    assert done["cached"] is True


async def test_stream_db_cache_hit(db_session, fake_redis):
    """Fresh DB prices (no Redis) replay + cache back."""
    from datetime import UTC, datetime
    from decimal import Decimal

    from modules.m2_prices.models import Price

    product = await _seed_product(db_session)
    await _seed_retailers(db_session, ["amazon"])

    db_session.add(
        Price(
            product_id=product.id,
            retailer_id="amazon",
            price=Decimal("278.00"),
            currency="USD",
            condition="new",
            url="https://amazon.com/p",
            is_available=True,
            is_on_sale=False,
            last_checked=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )
    await db_session.flush()

    fake = _FakeContainerClient(responses={"amazon": _success_response("amazon")})
    service = PriceAggregationService(db=db_session, redis=fake_redis, container_client=fake)

    events = await _collect_events(service, product.id)

    assert fake.extract_one_calls == []
    done = next(p for t, p in events if t == "done")
    assert done["cached"] is True
    # After DB hit, result should be cached back to Redis
    cached = await fake_redis.get(f"prices:product:{product.id}")
    assert cached is not None


async def test_stream_force_refresh_bypasses_cache(db_session, fake_redis):
    product = await _seed_product(db_session)
    await _seed_retailers(db_session, ["amazon"])

    # Pre-populate Redis cache
    cached = {
        "product_id": str(product.id),
        "product_name": product.name,
        "prices": [],
        "retailer_results": [],
        "total_retailers": 0,
        "retailers_succeeded": 0,
        "retailers_failed": 0,
        "cached": True,
        "fetched_at": "2026-04-13T10:00:00+00:00",
    }
    await fake_redis.set(f"prices:product:{product.id}", json.dumps(cached))

    fake = _FakeContainerClient(responses={"amazon": _success_response("amazon")})
    service = PriceAggregationService(db=db_session, redis=fake_redis, container_client=fake)

    events = await _collect_events(service, product.id, force_refresh=True)

    # Containers were called despite cache
    assert fake.extract_one_calls == ["amazon"]
    done = next(p for t, p in events if t == "done")
    assert done["cached"] is False


# MARK: - Endpoint-level tests (HTTP SSE)


async def test_stream_endpoint_returns_sse_content_type(client, db_session):
    from unittest.mock import patch

    product = await _seed_product(db_session)
    await _seed_retailers(db_session, ["amazon"])

    fake = _FakeContainerClient(responses={"amazon": _success_response("amazon")})

    with patch("modules.m2_prices.service.ContainerClient", return_value=fake):
        async with client.stream(
            "GET", f"/api/v1/prices/{product.id}/stream"
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            assert "no-cache" in response.headers.get("cache-control", "")
            # Drain the stream to avoid a dangling connection warning.
            async for _ in response.aiter_bytes():
                pass


async def test_stream_endpoint_404_before_stream_opens(client, db_session):
    unknown_id = uuid.uuid4()
    resp = await client.get(f"/api/v1/prices/{unknown_id}/stream")
    assert resp.status_code == 404
    body = resp.json()
    # FastAPI wraps HTTPException.detail in {"detail": <content>}.
    assert body["detail"]["error"]["code"] == "PRODUCT_NOT_FOUND"
    # 404 must be a real JSON response, not an SSE payload
    assert not resp.headers.get("content-type", "").startswith("text/event-stream")


async def test_stream_endpoint_events_parse_correctly(client, db_session):
    """End-to-end: parse SSE wire bytes and verify event sequence + done summary."""
    from unittest.mock import patch

    product = await _seed_product(db_session)
    await _seed_retailers(db_session, ["amazon", "walmart", "target"])

    fake = _FakeContainerClient(
        responses={
            "amazon": _success_response("amazon", 299.99),
            "walmart": _success_response("walmart", 289.99),
            "target": _error_response("target", "CONNECTION_FAILED"),
        },
        delays_ms={"walmart": 2, "amazon": 5, "target": 10},
    )

    with patch("modules.m2_prices.service.ContainerClient", return_value=fake):
        async with client.stream(
            "GET", f"/api/v1/prices/{product.id}/stream"
        ) as response:
            assert response.status_code == 200
            events = await _collect_sse_stream(response)

    retailer_events = [(e, p["retailer_id"]) for e, p in events if e == "retailer_result"]
    assert len(retailer_events) == 3
    # Completion order: walmart → amazon → target
    assert [r for _, r in retailer_events] == ["walmart", "amazon", "target"]

    statuses = {p["retailer_id"]: p["status"] for e, p in events if e == "retailer_result"}
    assert statuses["walmart"] == "success"
    assert statuses["amazon"] == "success"
    assert statuses["target"] == "unavailable"

    assert events[-1][0] == "done"
    done = events[-1][1]
    assert done["total_retailers"] == 3
    assert done["retailers_succeeded"] == 2
    assert done["retailers_failed"] == 1
    assert done["cached"] is False


# MARK: - Regression coverage


async def test_stream_prices_unknown_product_raises(db_session, fake_redis):
    """Unknown product must raise ProductNotFoundError BEFORE yielding any events."""
    from modules.m2_prices.service import ProductNotFoundError

    fake = _FakeContainerClient(responses={})
    service = PriceAggregationService(db=db_session, redis=fake_redis, container_client=fake)

    with pytest.raises(ProductNotFoundError):
        # Consuming the first item triggers validation.
        async for _ in service.stream_prices(uuid.uuid4()):
            break
