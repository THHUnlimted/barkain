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
        # Captured per-retailer location kwargs — keyed by retailer_id.
        # Added for the fb-marketplace-location step so tests can assert
        # the service forwarded slug/radius only to fb_marketplace.
        self.extract_one_kwargs: dict[str, dict] = {}

    async def _extract_one(
        self,
        retailer_id: str,
        query: str,
        product_name: str | None,
        upc: str | None,
        max_listings: int,
        fb_location_id: str | None = None,
        fb_radius_miles: int | None = None,
    ) -> ContainerResponse:
        self.extract_one_calls.append(retailer_id)
        self.extract_one_kwargs[retailer_id] = {
            "fb_location_id": fb_location_id,
            "fb_radius_miles": fb_radius_miles,
        }
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


# MARK: - query_override scoped cache (2026-04-19)


async def test_stream_query_override_writes_to_scoped_cache_key(db_session, fake_redis):
    """Bare-name override runs cache to `prices:product:{id}:q:<sha1>`, not the bare key."""
    from modules.m2_prices.service import (
        PriceAggregationService,
        REDIS_KEY_PREFIX,
        REDIS_KEY_QUERY_SUFFIX,
        _query_scope_digest,
    )

    product = await _seed_product(db_session)
    await _seed_retailers(db_session, ["amazon"])

    fake = _FakeContainerClient(responses={"amazon": _success_response("amazon")})
    service = PriceAggregationService(db=db_session, redis=fake_redis, container_client=fake)

    override = "Steam Deck OLED"
    async for _ in service.stream_prices(product.id, query_override=override):
        pass

    bare_key = f"{REDIS_KEY_PREFIX}{product.id}"
    scoped_key = (
        f"{REDIS_KEY_PREFIX}{product.id}"
        f"{REDIS_KEY_QUERY_SUFFIX}{_query_scope_digest(override)}"
    )

    # Scoped key was populated; bare-product key was NOT polluted by the override.
    assert await fake_redis.get(scoped_key) is not None
    assert await fake_redis.get(bare_key) is None


async def test_stream_query_override_replays_scoped_cache(db_session, fake_redis):
    """Second call with same override hits scoped cache and skips containers."""
    from modules.m2_prices.service import PriceAggregationService

    product = await _seed_product(db_session)
    await _seed_retailers(db_session, ["amazon"])

    fake = _FakeContainerClient(responses={"amazon": _success_response("amazon")})
    service = PriceAggregationService(db=db_session, redis=fake_redis, container_client=fake)

    override = "Steam Deck OLED"
    async for _ in service.stream_prices(product.id, query_override=override):
        pass
    first_calls = list(fake.extract_one_calls)

    async for _ in service.stream_prices(product.id, query_override=override):
        pass
    second_calls = fake.extract_one_calls[len(first_calls):]

    assert first_calls == ["amazon"]  # initial run dispatched
    assert second_calls == []          # second run was a cache replay


async def test_stream_query_override_does_not_serve_bare_cache(db_session, fake_redis):
    """A pre-populated BARE product cache must NOT be served to an override request."""
    from modules.m2_prices.service import PriceAggregationService, REDIS_KEY_PREFIX

    product = await _seed_product(db_session)
    await _seed_retailers(db_session, ["amazon"])

    bare_cached = {
        "product_id": str(product.id),
        "product_name": product.name,
        "prices": [{"retailer_id": "amazon", "retailer_name": "Amazon", "price": 1.0}],
        "retailer_results": [],
        "total_retailers": 1,
        "retailers_succeeded": 1,
        "retailers_failed": 0,
        "cached": True,
        "fetched_at": "2026-04-19T00:00:00+00:00",
    }
    await fake_redis.set(f"{REDIS_KEY_PREFIX}{product.id}", json.dumps(bare_cached))

    fake = _FakeContainerClient(responses={"amazon": _success_response("amazon", 99.0)})
    service = PriceAggregationService(db=db_session, redis=fake_redis, container_client=fake)

    events = []
    async for evt in service.stream_prices(product.id, query_override="Different Query"):
        events.append(evt)

    # The override run must dispatch fresh (not replay the bare-product cache).
    assert fake.extract_one_calls == ["amazon"]
    done = next(p for t, p in events if t == "done")
    # And the price the user sees is from the fresh run, not the planted cache.
    assert done["retailers_succeeded"] == 1


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


# MARK: - fb_marketplace per-user location (fb-marketplace-location)


async def test_stream_forwards_fb_location_to_every_retailer_fake(db_session, fake_redis):
    """stream_prices threads fb_location_id / fb_radius_miles into _extract_one.

    The ContainerClient layer is responsible for gating which retailers
    actually see the id (fb_marketplace only — asserted separately in
    test_container_client.py). At the service layer we just verify the
    kwargs are forwarded, not dropped.
    """
    product = await _seed_product(db_session)
    await _seed_retailers(db_session, ["amazon", "fb_marketplace"])

    fake = _FakeContainerClient(
        responses={
            "amazon": _success_response("amazon"),
            "fb_marketplace": _success_response("fb_marketplace"),
        }
    )
    service = PriceAggregationService(db=db_session, redis=fake_redis, container_client=fake)

    async for _ in service.stream_prices(
        product.id, fb_location_id="112111905481230", fb_radius_miles=25
    ):
        pass

    assert set(fake.extract_one_calls) == {"amazon", "fb_marketplace"}
    for rid, kwargs in fake.extract_one_kwargs.items():
        assert kwargs["fb_location_id"] == "112111905481230", rid
        assert kwargs["fb_radius_miles"] == 25, rid


async def test_stream_location_writes_scoped_cache_key(db_session, fake_redis):
    """With a location set, cache bucket is `…:loc:<id>:r<miles>`, not the bare key."""
    from modules.m2_prices.service import REDIS_KEY_PREFIX

    product = await _seed_product(db_session)
    await _seed_retailers(db_session, ["fb_marketplace"])

    fake = _FakeContainerClient(responses={"fb_marketplace": _success_response("fb_marketplace")})
    service = PriceAggregationService(db=db_session, redis=fake_redis, container_client=fake)

    async for _ in service.stream_prices(
        product.id, fb_location_id="112111905481230", fb_radius_miles=25
    ):
        pass

    bare_key = f"{REDIS_KEY_PREFIX}{product.id}"
    scoped_key = f"{REDIS_KEY_PREFIX}{product.id}:loc:112111905481230:r25"

    assert await fake_redis.get(scoped_key) is not None
    # Bare-product key MUST stay empty so another user without a preference
    # doesn't pick up Brooklyn's fb_marketplace listings.
    assert await fake_redis.get(bare_key) is None


async def test_stream_location_different_ids_use_different_cache_buckets(
    db_session, fake_redis
):
    """Two users, two location IDs, two buckets — no cross-contamination."""
    product = await _seed_product(db_session)
    await _seed_retailers(db_session, ["fb_marketplace"])

    fake_a = _FakeContainerClient(
        responses={"fb_marketplace": _success_response("fb_marketplace", 100.0)}
    )
    service_a = PriceAggregationService(db=db_session, redis=fake_redis, container_client=fake_a)
    async for _ in service_a.stream_prices(
        product.id, fb_location_id="112111905481230", fb_radius_miles=25
    ):
        pass

    # Second user in a different metro must dispatch fresh (no cross-cache hit).
    fake_b = _FakeContainerClient(
        responses={"fb_marketplace": _success_response("fb_marketplace", 200.0)}
    )
    service_b = PriceAggregationService(db=db_session, redis=fake_redis, container_client=fake_b)
    async for _ in service_b.stream_prices(
        product.id, fb_location_id="108271525863730", fb_radius_miles=50
    ):
        pass

    assert fake_b.extract_one_calls == ["fb_marketplace"]


async def test_stream_endpoint_accepts_location_query_params(client, db_session):
    """Router accepts fb_location_id + fb_radius_miles and opens the stream."""
    from unittest.mock import patch

    product = await _seed_product(db_session)
    await _seed_retailers(db_session, ["fb_marketplace"])

    fake = _FakeContainerClient(responses={"fb_marketplace": _success_response("fb_marketplace")})

    with patch("modules.m2_prices.service.ContainerClient", return_value=fake):
        async with client.stream(
            "GET",
            f"/api/v1/prices/{product.id}/stream",
            params={"fb_location_id": "112111905481230", "fb_radius_miles": 25},
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            async for _ in response.aiter_bytes():
                pass

    # The router forwarded the id into _extract_one for fb_marketplace.
    assert fake.extract_one_kwargs["fb_marketplace"] == {
        "fb_location_id": "112111905481230",
        "fb_radius_miles": 25,
    }


async def test_stream_fb_marketplace_flags_default_when_no_location_id(
    db_session, fake_redis
):
    """When the user hasn't picked a Marketplace location, the container
    falls back to its baked `sanfrancisco` env default. The fb_marketplace
    price payload must carry `location_default_used=True` so iOS can show
    a "Using SF default" pill (fb-resolver-followups L12)."""
    product = await _seed_product(db_session)
    await _seed_retailers(db_session, ["amazon", "fb_marketplace"])

    fake = _FakeContainerClient(
        responses={
            "amazon": _success_response("amazon"),
            "fb_marketplace": _success_response("fb_marketplace"),
        }
    )
    service = PriceAggregationService(
        db=db_session, redis=fake_redis, container_client=fake
    )

    fb_payload = None
    amazon_payload = None
    async for event_type, payload in service.stream_prices(product.id):
        if event_type != "retailer_result":
            continue
        if payload["retailer_id"] == "fb_marketplace":
            fb_payload = payload
        elif payload["retailer_id"] == "amazon":
            amazon_payload = payload

    assert fb_payload is not None
    assert fb_payload["price"]["location_default_used"] is True
    # Other retailers' payloads must be unchanged — no flag pollution.
    assert amazon_payload is not None
    assert "location_default_used" not in amazon_payload["price"]


async def test_stream_fb_marketplace_does_not_flag_when_location_id_present(
    db_session, fake_redis
):
    """When the user has saved a Marketplace location, the flag is
    omitted — iOS hides the pill (fb-resolver-followups L12)."""
    product = await _seed_product(db_session)
    await _seed_retailers(db_session, ["fb_marketplace"])

    fake = _FakeContainerClient(
        responses={"fb_marketplace": _success_response("fb_marketplace")}
    )
    service = PriceAggregationService(
        db=db_session, redis=fake_redis, container_client=fake
    )

    fb_payload = None
    async for event_type, payload in service.stream_prices(
        product.id, fb_location_id="112111905481230", fb_radius_miles=25
    ):
        if event_type == "retailer_result" and payload["retailer_id"] == "fb_marketplace":
            fb_payload = payload

    assert fb_payload is not None
    assert "location_default_used" not in fb_payload["price"]


async def test_stream_endpoint_422_on_bad_location_id(client, db_session):
    """Non-numeric id must 422 at the router boundary before SSE opens.

    Surfacing the error as a normal HTTP 422 (instead of a mid-stream
    SSE event the client has to parse) is important for iOS — the stream
    consumer expects events, not validation failures.
    """
    product = await _seed_product(db_session)
    await _seed_retailers(db_session, ["fb_marketplace"])

    resp = await client.get(
        f"/api/v1/prices/{product.id}/stream",
        params={"fb_location_id": "not a number"},
    )
    assert resp.status_code == 422
    assert not resp.headers.get("content-type", "").startswith("text/event-stream")
