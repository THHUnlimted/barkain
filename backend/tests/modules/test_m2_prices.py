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


async def test_auth_required_returns_401(unauthed_client, without_demo_mode):
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


# MARK: - get_prices query_override threading (inflight-cache-1-L2)


async def test_get_prices_with_query_override_uses_override_as_dispatch_query(
    db_session, fake_redis
):
    """When the caller passes query_override, the dispatched container
    query AND the per-container product_name hint must be the override
    string — not the product's resolved name. Mirrors stream_prices.
    Without this, the parallel /recommend would dispatch with the wrong
    query and undo the bare-name search the SSE stream is running."""
    from modules.m2_prices.service import PriceAggregationService

    product = await _seed_product(db_session)
    await _seed_retailers(db_session, ["amazon"])

    captured_kwargs: dict = {}

    async def _capturing_extract_all(**kwargs):
        captured_kwargs.update(kwargs)
        return {"amazon": _make_container_response("amazon", 99.99)}

    mock_client = AsyncMock()
    mock_client.extract_all = _capturing_extract_all

    service = PriceAggregationService(
        db=db_session, redis=fake_redis, container_client=mock_client
    )
    await service.get_prices(
        product.id, force_refresh=True, query_override="Apple iPhone Any Variant"
    )

    assert captured_kwargs["query"] == "Apple iPhone Any Variant", (
        f"dispatch query should be the override string, got {captured_kwargs['query']!r}"
    )
    assert captured_kwargs["product_name"] == "Apple iPhone Any Variant", (
        f"product_name hint should also be override, got {captured_kwargs['product_name']!r}"
    )


async def test_get_prices_with_query_override_skips_db_cache_short_circuit(
    db_session, fake_redis
):
    """A bare-name override stream wrote SCOPED data; the prices table
    rows have no scope tag. Falling through to the DB cache on a
    query_override call would serve a cross-scope row (SKU-resolved row
    served to a bare-name caller, or vice versa). Mirror's stream_prices'
    same guard."""
    from datetime import UTC, datetime
    from decimal import Decimal

    from modules.m2_prices.models import Price
    from modules.m2_prices.service import PriceAggregationService

    product = await _seed_product(db_session)
    await _seed_retailers(db_session, ["amazon"])

    # Seed a fresh DB price — would be served by _check_db_prices in
    # the no-override path.
    db_session.add(
        Price(
            product_id=product.id,
            retailer_id="amazon",
            price=Decimal("500.00"),
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

    # Container client is dispatched ONLY when DB cache is correctly skipped.
    mock_client = AsyncMock()
    mock_client.extract_all = AsyncMock(
        return_value={"amazon": _make_container_response("amazon", 100.00)}
    )

    service = PriceAggregationService(
        db=db_session, redis=fake_redis, container_client=mock_client
    )
    result = await service.get_prices(
        product.id, query_override="Apple iPhone Any Variant"
    )

    # Must dispatch (DB skipped). Resulting price = the dispatched 100.00,
    # not the seeded DB row's 500.00.
    mock_client.extract_all.assert_awaited_once()
    assert result["prices"][0]["price"] == 100.00


# MARK: - Relevance Scoring (Step 2b)


def test_relevance_model_number_match():
    """Listing with matching model number gets score > 0.4."""
    from modules.m2_prices.service import _score_listing_relevance

    product = Product(name="Sony WH-1000XM5 Wireless Headphones", brand="Sony", source="test")
    score = _score_listing_relevance("Sony WH-1000XM5 Wireless Noise Canceling Headphones", product)
    assert score >= 0.4


def test_relevance_model_number_mismatch():
    """Listing with different model number gets score = 0.0."""
    from modules.m2_prices.service import _score_listing_relevance

    product = Product(name="Apple Mac mini M4", brand="Apple", source="test")
    score = _score_listing_relevance("Apple Mac mini M2 Desktop Computer", product)
    assert score == 0.0


def test_relevance_brand_mismatch():
    """Listing from wrong brand gets score = 0.0."""
    from modules.m2_prices.service import _score_listing_relevance

    product = Product(name="Sony WH-1000XM5", brand="Sony", source="test")
    score = _score_listing_relevance("Bose QuietComfort 45 Headphones", product)
    assert score == 0.0


def test_relevance_no_model_number_token_overlap():
    """Product without model numbers falls through to token overlap."""
    from modules.m2_prices.service import _score_listing_relevance

    product = Product(name="Wireless Headphones Premium Audio", brand=None, source="test")
    score = _score_listing_relevance("Wireless Headphones Premium Audio Black Edition", product)
    assert score >= 0.4


def test_relevance_low_token_overlap():
    """Low token overlap gets filtered out."""
    from modules.m2_prices.service import _score_listing_relevance

    product = Product(name="Sony WH-1000XM5 Wireless Headphones", brand="Sony", source="test")
    score = _score_listing_relevance("Sony Phone Case Black Protective Cover", product)
    assert score == 0.0


async def test_relevance_all_filtered_returns_none(db_session):
    """When all listings fail relevance, _pick_best_listing returns None."""
    from modules.m2_prices.service import PriceAggregationService

    product = Product(name="Apple Mac mini M4 Desktop", brand="Apple", source="test")
    response = ContainerResponse(
        retailer_id="amazon",
        query="Apple Mac mini M4",
        listings=[
            ContainerListing(title="Apple Mac mini M2 Desktop Computer", price=499.00),
            ContainerListing(title="Dell Inspiron Desktop Tower", price=399.00),
        ],
    )

    service = PriceAggregationService.__new__(PriceAggregationService)
    result, score = service._pick_best_listing(response, product)
    assert result is None


async def test_relevance_zero_price_still_filtered(db_session):
    """Zero-price listings are excluded even with good title match."""
    from modules.m2_prices.service import PriceAggregationService

    product = Product(name="Sony WH-1000XM5 Wireless Headphones", brand="Sony", source="test")
    response = ContainerResponse(
        retailer_id="amazon",
        query="Sony WH-1000XM5",
        listings=[
            ContainerListing(title="Sony WH-1000XM5 Wireless Headphones", price=0.0),
        ],
    )

    service = PriceAggregationService.__new__(PriceAggregationService)
    result, score = service._pick_best_listing(response, product)
    assert result is None


async def test_relevance_cheapest_after_filter(db_session):
    """After relevance filter, cheapest of the survivors is picked."""
    from modules.m2_prices.service import PriceAggregationService

    product = Product(name="Sony WH-1000XM5 Wireless Headphones", brand="Sony", source="test")
    response = ContainerResponse(
        retailer_id="amazon",
        query="Sony WH-1000XM5",
        listings=[
            ContainerListing(title="Sony WH-1000XM5 Wireless Headphones Black", price=348.00),
            ContainerListing(title="Sony WH-1000XM5 Wireless Headphones Silver", price=278.00),
            ContainerListing(title="Sony WH-1000XM5 Wireless Noise Canceling", price=299.99),
        ],
    )

    service = PriceAggregationService.__new__(PriceAggregationService)
    result, score = service._pick_best_listing(response, product)
    assert result is not None
    assert result.price == 278.00
    assert score >= 0.4


# MARK: - Gemini model field relevance (Step 2b-final)


def test_relevance_generation_marker_distinguishes_galaxy_buds():
    """Gemini's `model` field with (1st Gen) blocks 2nd-gen listings via ordinal equality."""
    from modules.m2_prices.service import _score_listing_relevance

    product = Product(
        name="Samsung Galaxy Buds Pro",
        brand="Samsung",
        source="gemini_validated",
        source_raw={"gemini_model": "Galaxy Buds Pro (1st Gen)"},
    )
    score = _score_listing_relevance(
        "Samsung Galaxy Buds 2 Pro Wireless Earbuds", product
    )
    assert score == 0.0


def test_relevance_generation_marker_passes_exact_match():
    """Same product + listing that contains the matching 1st Gen marker passes."""
    from modules.m2_prices.service import _score_listing_relevance

    product = Product(
        name="Samsung Galaxy Buds Pro",
        brand="Samsung",
        source="gemini_validated",
        source_raw={"gemini_model": "Galaxy Buds Pro (1st Gen)"},
    )
    score = _score_listing_relevance(
        "Samsung Galaxy Buds Pro 1st Gen Wireless Earbuds", product
    )
    assert score >= 0.4


def test_relevance_gpu_model_distinguishes_rtx_4090():
    """GPU _MODEL_PATTERNS[5] + gemini_model reject RTX 4080 listings for an RTX 4090 product."""
    from modules.m2_prices.service import _score_listing_relevance

    product = Product(
        name="NVIDIA GeForce RTX 4090",
        brand="NVIDIA",
        source="gemini_validated",
        source_raw={"gemini_model": "RTX 4090"},
    )
    score = _score_listing_relevance(
        "MSI NVIDIA GeForce RTX 4080 Founders Edition 16GB", product
    )
    assert score == 0.0


def test_relevance_gpu_model_passes_exact_match():
    """RTX 4090 product vs RTX 4090 listing: hard gate + all downstream rules pass."""
    from modules.m2_prices.service import _score_listing_relevance

    product = Product(
        name="NVIDIA GeForce RTX 4090",
        brand="NVIDIA",
        source="gemini_validated",
        source_raw={"gemini_model": "RTX 4090"},
    )
    score = _score_listing_relevance(
        "ASUS NVIDIA GeForce RTX 4090 TUF Gaming OC Edition 24GB", product
    )
    assert score >= 0.4


def test_relevance_no_gemini_model_backward_compat():
    """Product with source_raw=None scores identically to pre-upgrade code."""
    from modules.m2_prices.service import _score_listing_relevance

    product = Product(
        name="Sony WH-1000XM5 Wireless Headphones",
        brand="Sony",
        source="test",
        source_raw=None,
    )
    score = _score_listing_relevance(
        "Sony WH-1000XM5 Wireless Noise Canceling Headphones", product
    )
    assert score >= 0.4


# MARK: - Apple variant disambiguation (chip + display size — disagreement-only)


def test_extract_apple_chip_tokens_finds_bare_chip():
    """M1/M2/M3/M4 with no suffix normalize to 'm1'/'m2'/'m3'/'m4'."""
    from modules.m2_prices.service import _extract_apple_chip_tokens

    assert _extract_apple_chip_tokens("Apple MacBook Air M1 13-inch") == {"m1"}
    assert _extract_apple_chip_tokens("Apple iPad Pro M4 11-inch") == {"m4"}
    assert _extract_apple_chip_tokens("MacBook Air with Apple M2 chip") == {"m2"}


def test_extract_apple_chip_tokens_finds_pro_max_ultra_suffix():
    """Pro/Max/Ultra suffix is captured and lowercased."""
    from modules.m2_prices.service import _extract_apple_chip_tokens

    assert _extract_apple_chip_tokens("MacBook Pro 14 M3 Pro 18GB") == {"m3 pro"}
    assert _extract_apple_chip_tokens("MacBook Pro 16 M3 Max 36GB") == {"m3 max"}
    assert _extract_apple_chip_tokens("Mac Studio M2 Ultra 192GB") == {"m2 ultra"}


def test_extract_apple_chip_tokens_skips_non_apple_collisions():
    """Logitech M310, M16 carbines, MS220 etc. must not false-match."""
    from modules.m2_prices.service import _extract_apple_chip_tokens

    # 1-digit anchor: \b...M[1-4]\b — M310 is digit-then-digit, no boundary
    assert _extract_apple_chip_tokens("Logitech M310 Wireless Mouse") == set()
    # M16 has \b after 'M1' between '1' and '6' — both digits, not a boundary
    assert _extract_apple_chip_tokens("M16 carbine accessory") == set()
    # MS220 — leading char is 'S' not a digit, fails [1-4] class
    assert _extract_apple_chip_tokens("Belkin MS220 Cable") == set()
    # M1234 SKU — digit-digit run after M1, no boundary
    assert _extract_apple_chip_tokens("Yamaha M1234 Receiver") == set()
    # Nothing apple-shaped
    assert _extract_apple_chip_tokens("Sony WH-1000XM5 Wireless Headphones") == set()


def test_extract_apple_display_size_tokens_finds_inch_variants():
    """11/13/14/15/16 with -inch / inch / inches / inch all normalize to digit string."""
    from modules.m2_prices.service import _extract_apple_display_size_tokens

    assert _extract_apple_display_size_tokens("MacBook Pro 14-inch M3") == {"14"}
    assert _extract_apple_display_size_tokens("MacBook Air 13 inch") == {"13"}
    assert _extract_apple_display_size_tokens("iPad Pro 11inch 2024") == {"11"}
    assert _extract_apple_display_size_tokens("16 inches MacBook Pro") == {"16"}


def test_extract_apple_display_size_tokens_skips_out_of_range():
    """Sizes outside 11–16 (knives, monitors, TVs) don't match."""
    from modules.m2_prices.service import _extract_apple_display_size_tokens

    assert _extract_apple_display_size_tokens("Wusthof 8-inch chef knife") == set()
    assert _extract_apple_display_size_tokens("Dell UltraSharp 27-inch Monitor") == set()
    assert _extract_apple_display_size_tokens("Samsung 55-inch QLED TV") == set()


def test_relevance_chip_disagreement_rejects_m3_listing_for_m4_product():
    """The user's reported bug: M4 iPad Pro query → eBay surfaces M3 listing → reject."""
    from modules.m2_prices.service import _score_listing_relevance

    # Even when product.name lacks "M4" itself, gemini_model carries the chip
    # token forward into Rule 2c.
    product = Product(
        name="Apple iPad Pro 11-inch (2024)",
        brand="Apple",
        source="gemini_validated",
        source_raw={"gemini_model": "iPad Pro 11-inch M4"},
    )
    score = _score_listing_relevance(
        "Apple iPad Pro M3 11-inch 256GB Space Gray Wi-Fi", product
    )
    assert score == 0.0


def test_relevance_chip_match_passes_when_both_sides_emit_same_chip():
    """M4 product + M4 listing: rule 2c is satisfied, downstream rules apply normally."""
    from modules.m2_prices.service import _score_listing_relevance

    product = Product(
        name="Apple iPad Pro 11-inch (2024)",
        brand="Apple",
        source="gemini_validated",
        source_raw={"gemini_model": "iPad Pro 11-inch M4"},
    )
    score = _score_listing_relevance(
        "Apple iPad Pro 11-inch M4 256GB Wi-Fi Space Black", product
    )
    assert score >= 0.4


def test_relevance_chip_omitted_in_listing_still_passes():
    """Used eBay/FB sellers often omit chip — must not over-reject genuine matches.

    This is the load-bearing safeguard for keeping coverage on second-hand listings
    where sellers describe size/storage/year but skip the chip name. Disagreement-
    only semantic: only reject when both sides emit a chip and they differ.
    """
    from modules.m2_prices.service import _score_listing_relevance

    product = Product(
        name="Apple MacBook Air 13-inch",
        brand="Apple",
        source="gemini_validated",
        source_raw={"gemini_model": "MacBook Air M2 13-inch"},
    )
    # Listing mentions year + size + storage but no chip — common eBay shape.
    score = _score_listing_relevance(
        "Apple MacBook Air 13-inch 2022 8GB 256GB Midnight Excellent Condition",
        product,
    )
    assert score >= 0.4


def test_relevance_chip_pro_max_distinguished_from_base():
    """M3 Pro listing must not match M3 base product — multi-token chip equality.

    Documented limitation: this test verifies the normalize step works when both
    sides emit explicit suffixes. It does NOT enforce the "M3 base must reject
    M3 Pro" case because user-query intent is ambiguous (is "macbook pro m3"
    asking for base or any-M3-tier?). That negative-match feature was deliberately
    cut from this PR.
    """
    from modules.m2_prices.service import _score_listing_relevance

    product = Product(
        name="Apple MacBook Pro 14-inch",
        brand="Apple",
        source="gemini_validated",
        source_raw={"gemini_model": "MacBook Pro 14-inch M3 Max 36GB"},
    )
    score = _score_listing_relevance(
        "Apple MacBook Pro 14-inch M3 Pro 18GB 512GB Space Black", product
    )
    assert score == 0.0  # {m3 max} != {m3 pro}


def test_relevance_size_disagreement_rejects_15_listing_for_13_product():
    """MacBook Air M2 13" query → 15" listing → reject (different SKU, different price)."""
    from modules.m2_prices.service import _score_listing_relevance

    product = Product(
        name="Apple MacBook Air M2",
        brand="Apple",
        source="gemini_validated",
        source_raw={"gemini_model": "MacBook Air M2 13-inch"},
    )
    score = _score_listing_relevance(
        "Apple MacBook Air M2 15-inch 8GB 256GB Midnight", product
    )
    assert score == 0.0


def test_relevance_size_omitted_in_listing_still_passes():
    """Listing without inch token is allowed even when product specifies size."""
    from modules.m2_prices.service import _score_listing_relevance

    product = Product(
        name="Apple MacBook Air M2",
        brand="Apple",
        source="gemini_validated",
        source_raw={"gemini_model": "MacBook Air M2 13-inch"},
    )
    score = _score_listing_relevance(
        "Apple MacBook Air M2 256GB Midnight 8GB RAM", product
    )
    assert score >= 0.4


def test_relevance_chip_rejection_emits_telemetry_log(caplog):
    """Rule 2c emits a structured log line on rejection so silent zero-results are observable.

    The disagreement-only gate can reject ALL listings for a product if Gemini
    stored the wrong chip on the canonical — and the failure mode looks identical
    to "no retailers had this product" from the user side. Log every rejection so
    we can detect the pattern in production telemetry.

    Listing is shaped so Rule 1 (existing identifier hard gate) passes via the
    "Pro 11" identifier — chip mismatch is then the load-bearing rejection at
    Rule 2c. This mirrors the realistic eBay used-iPad listing shape.
    """
    import logging
    from modules.m2_prices.service import _score_listing_relevance

    product = Product(
        name="Apple iPad Pro 11",
        brand="Apple",
        source="gemini_validated",
        source_raw={"gemini_model": "iPad Pro 11 M4"},
    )
    with caplog.at_level(logging.INFO, logger="barkain.m2"):
        score = _score_listing_relevance(
            "Apple iPad Pro 11 M3 256GB Space Gray Wi-Fi", product,
            retailer_id="ebay_browse_api",
        )
    assert score == 0.0
    assert any(
        "apple_variant_gate_rejected" in r.getMessage() and "rule=2c" in r.getMessage()
        for r in caplog.records
    ), "expected a Rule 2c rejection log line"


def test_relevance_size_rejection_emits_telemetry_log(caplog):
    """Rule 2d emits the same structured log line on size disagreement.

    Both sides share the same chip ("M2") but different display sizes, so Rule
    2c passes and Rule 2d is the rejecting rule.
    """
    import logging
    from modules.m2_prices.service import _score_listing_relevance

    product = Product(
        name="Apple MacBook Air M2 13",
        brand="Apple",
        source="gemini_validated",
        source_raw={"gemini_model": "MacBook Air M2 13-inch"},
    )
    with caplog.at_level(logging.INFO, logger="barkain.m2"):
        score = _score_listing_relevance(
            "Apple MacBook Air M2 15-inch 8GB 256GB Midnight", product,
            retailer_id="amazon_scraper_api",
        )
    assert score == 0.0
    assert any(
        "apple_variant_gate_rejected" in r.getMessage() and "rule=2d" in r.getMessage()
        for r in caplog.records
    ), "expected a Rule 2d rejection log line"


def test_relevance_demo_check_evergreen_macbook_air_m1_still_passes():
    """Critical regression guard: demo-check uses MBA M1 UPC 194252056639 as evergreen.

    Per CLAUDE.md the demo-check threshold is 5/9 retailers. If this PR
    accidentally tightens chip/size enforcement so that real M1 listings
    fail, the F&F demo breaks. Listing here is the typical eBay used-MBA
    shape (chip + size present, both sides agree).
    """
    from modules.m2_prices.service import _score_listing_relevance

    product = Product(
        name="Apple MacBook Air M1 13-inch (2020)",
        brand="Apple",
        source="gemini_validated",
        source_raw={"gemini_model": "MacBook Air M1 13-inch"},
    )
    score = _score_listing_relevance(
        "Apple MacBook Air 13.3-inch M1 8GB 256GB Space Gray (2020)", product
    )
    assert score >= 0.4


# MARK: - Platform-suffix accessory filter (Amazon-only)


def test_platform_suffix_helper_rejects_game_with_console_tail():
    """'NBA 2K25 - Nintendo Switch 2' is detected as a tail-descriptor pattern."""
    from modules.m2_prices.service import _is_platform_suffix_accessory

    assert _is_platform_suffix_accessory(
        "NBA 2K25 - Nintendo Switch 2", ["Switch 2"]
    ) is True


def test_platform_suffix_helper_rejects_paren_form():
    """'Mario Kart 9 (Nintendo Switch 2)' is detected via opening-paren separator."""
    from modules.m2_prices.service import _is_platform_suffix_accessory

    assert _is_platform_suffix_accessory(
        "Mario Kart 9 (Nintendo Switch 2)", ["Switch 2"]
    ) is True


def test_platform_suffix_helper_keeps_console_at_start():
    """Listing whose identifier appears at the start (the actual device) is kept."""
    from modules.m2_prices.service import _is_platform_suffix_accessory

    assert _is_platform_suffix_accessory(
        "Nintendo Switch 2 - Black Edition Console", ["Switch 2"]
    ) is False


def test_platform_suffix_helper_keeps_bundle():
    """Bundle keyword preserves the listing even with game tokens present."""
    from modules.m2_prices.service import _is_platform_suffix_accessory

    assert _is_platform_suffix_accessory(
        "NBA 2K25 + Nintendo Switch 2 Console Bundle", ["Switch 2"]
    ) is False


def test_platform_suffix_helper_no_separator_no_match():
    """Without a separator before the identifier, the pattern does not trigger."""
    from modules.m2_prices.service import _is_platform_suffix_accessory

    assert _is_platform_suffix_accessory(
        "Nintendo Switch 2 OLED Console", ["Switch 2"]
    ) is False


async def test_pick_best_listing_amazon_drops_platform_suffix_game(db_session):
    """For Amazon, '2K - Nintendo Switch 2' is dropped so the actual console price wins."""
    from modules.m2_prices.service import PriceAggregationService

    product = Product(name="Nintendo Switch 2", brand="Nintendo", source="test")
    response = ContainerResponse(
        retailer_id="amazon",
        query="Nintendo Switch 2",
        listings=[
            ContainerListing(title="NBA 2K25 - Nintendo Switch 2", price=59.99),
            ContainerListing(title="Nintendo Switch 2 Console with Joy-Con", price=449.99),
        ],
    )

    service = PriceAggregationService.__new__(PriceAggregationService)
    result, score = service._pick_best_listing(response, product)
    assert result is not None
    assert result.price == 449.99
    assert "NBA" not in result.title


async def test_pick_best_listing_amazon_keeps_bundle(db_session):
    """Bundles with game + console pass the Amazon filter (bundle token present)."""
    from modules.m2_prices.service import PriceAggregationService

    product = Product(name="Nintendo Switch 2", brand="Nintendo", source="test")
    response = ContainerResponse(
        retailer_id="amazon",
        query="Nintendo Switch 2",
        listings=[
            ContainerListing(
                title="Nintendo Switch 2 + Mario Kart 9 Console Bundle",
                price=499.99,
            ),
        ],
    )

    service = PriceAggregationService.__new__(PriceAggregationService)
    result, score = service._pick_best_listing(response, product)
    assert result is not None
    assert result.price == 499.99


async def test_pick_best_listing_non_amazon_keeps_platform_suffix(db_session):
    """Filter is Amazon-scoped: Walmart still picks the cheap '2K - Switch 2' listing."""
    from modules.m2_prices.service import PriceAggregationService

    product = Product(name="Nintendo Switch 2", brand="Nintendo", source="test")
    response = ContainerResponse(
        retailer_id="walmart",
        query="Nintendo Switch 2",
        listings=[
            ContainerListing(title="NBA 2K25 - Nintendo Switch 2", price=59.99),
            ContainerListing(title="Nintendo Switch 2 Console with Joy-Con", price=449.99),
        ],
    )

    service = PriceAggregationService.__new__(PriceAggregationService)
    result, score = service._pick_best_listing(response, product)
    assert result is not None
    assert result.price == 59.99  # filter doesn't run for non-amazon


# MARK: - Post-2b-val Hardening Unit Tests (Step 2b-final)


def test_clean_product_name_strips_supplier_code():
    """Supplier-code parentheticals (all-caps + digits) are stripped."""
    from modules.m2_prices.service import _clean_product_name

    assert _clean_product_name("iPhone 16 (CBC998000002407)") == "iPhone 16"


def test_clean_product_name_strips_alphanumeric_code():
    """All-caps alphanumeric supplier codes are stripped."""
    from modules.m2_prices.service import _clean_product_name

    assert _clean_product_name("JBL Flip 6 (JBLFLIP6TEALAM)") == "JBL Flip 6"


def test_clean_product_name_preserves_color_paren():
    """Lowercase parentheticals (color descriptors) are preserved."""
    from modules.m2_prices.service import _clean_product_name

    assert _clean_product_name("JBL Flip 6 (Teal)") == "JBL Flip 6 (Teal)"


def test_clean_product_name_preserves_generation_paren():
    """Generation markers with lowercase letters are preserved — feed the ordinal check."""
    from modules.m2_prices.service import _clean_product_name

    assert _clean_product_name("Galaxy Buds Pro (1st Gen)") == "Galaxy Buds Pro (1st Gen)"


def test_is_accessory_listing_rejects_screen_protector():
    """Screen protector listing is flagged when product is not itself an accessory."""
    from modules.m2_prices.service import _is_accessory_listing

    assert (
        _is_accessory_listing(
            "iPhone 16 Screen Protector Tempered Glass", {"iphone", "16"}
        )
        is True
    )


def test_is_accessory_listing_rejects_case():
    """Compatible-with case listing is flagged via accessory phrase regex."""
    from modules.m2_prices.service import _is_accessory_listing

    assert (
        _is_accessory_listing(
            "Compatible with iPhone 16 Rugged Case", {"iphone", "16"}
        )
        is True
    )


def test_is_accessory_listing_passes_real_product():
    """Real phone listing (no accessory keywords) is not flagged."""
    from modules.m2_prices.service import _is_accessory_listing

    assert (
        _is_accessory_listing(
            "Apple iPhone 16 Pro Max 256GB Unlocked", {"iphone", "pro", "max"}
        )
        is False
    )


def test_is_accessory_listing_skipped_when_product_is_case():
    """If the product itself is a case, accessory filter is disabled."""
    from modules.m2_prices.service import _is_accessory_listing

    assert (
        _is_accessory_listing(
            "Rugged Case for iPhone", {"rugged", "case"}
        )
        is False
    )


def test_is_accessory_listing_rejects_third_party_upgrade_service():
    """eBay 'Steam Deck OLED RAM Upgrade Service' is flagged via 'service' token."""
    from modules.m2_prices.service import _is_accessory_listing

    assert (
        _is_accessory_listing(
            "Valve Steam Deck OLED 32GB RAM/VRAM WORLDWIDE Upgrade Service",
            {"valve", "steam", "deck"},
        )
        is True
    )


def test_is_accessory_listing_rejects_repair_service():
    """Repair-service listings are flagged."""
    from modules.m2_prices.service import _is_accessory_listing

    assert (
        _is_accessory_listing(
            "PS5 Console Liquid Damage Repair Service",
            {"ps5", "console"},
        )
        is True
    )


def test_is_accessory_listing_rejects_modded_console():
    """Modded/modding listings are flagged when the product itself isn't a mod."""
    from modules.m2_prices.service import _is_accessory_listing

    assert (
        _is_accessory_listing(
            "Xbox Series X Custom Modded Controller — RGB Edition",
            {"xbox", "series", "x"},
        )
        is True
    )


def test_ident_to_regex_word_boundary_rejects_prefix():
    """'iPhone 16' regex does NOT match 'iPhone 16e' — word-boundary anchored."""
    from modules.m2_prices.service import _ident_to_regex

    pattern = _ident_to_regex("iPhone 16")
    assert pattern.search("Apple iPhone 16e 128GB") is None


def test_ident_to_regex_matches_exact():
    """'iPhone 16' regex matches 'iPhone 16 Pro' (Pro is after a space, still word-bounded)."""
    from modules.m2_prices.service import _ident_to_regex

    pattern = _ident_to_regex("iPhone 16")
    assert pattern.search("Apple iPhone 16 Pro 256GB") is not None


def test_ident_to_regex_flexible_whitespace():
    """Internal whitespace in the identifier loosens to \\s+ for the regex."""
    from modules.m2_prices.service import _ident_to_regex

    pattern = _ident_to_regex("Flip 6")
    assert pattern.search("JBL Flip  6 Portable Speaker") is not None  # double space


def test_variant_token_equality_rejects_pro_max_for_pro():
    """Product 'iPhone 16 Pro' must not match listing 'iPhone 16 Pro Max'."""
    from modules.m2_prices.service import _score_listing_relevance

    product = Product(name="Apple iPhone 16 Pro", brand="Apple", source="test")
    score = _score_listing_relevance(
        "Apple iPhone 16 Pro Max 256GB Natural Titanium", product
    )
    assert score == 0.0


def test_variant_token_equality_accepts_same_variant():
    """Product 'iPhone 16 Pro' matches listing 'iPhone 16 Pro 256GB'."""
    from modules.m2_prices.service import _score_listing_relevance

    product = Product(name="Apple iPhone 16 Pro", brand="Apple", source="test")
    score = _score_listing_relevance(
        "Apple iPhone 16 Pro 256GB Natural Titanium Unlocked", product
    )
    assert score >= 0.4


def test_classify_error_status_challenge_maps_to_unavailable():
    """CHALLENGE error code (bot block) maps to 'unavailable' not 'no_match'."""
    from modules.m2_prices.service import _classify_error_status

    assert _classify_error_status("CHALLENGE") == "unavailable"


def test_classify_error_status_unknown_maps_to_no_match():
    """Unknown error codes default to 'no_match' (the safe fallback)."""
    from modules.m2_prices.service import _classify_error_status

    assert _classify_error_status("SOME_UNKNOWN_CODE") == "no_match"


@pytest.mark.parametrize(
    "code",
    [
        "CONNECTION_FAILED",
        "GATHER_ERROR",
        "HTTP_ERROR",
        "CLIENT_ERROR",
        "CHALLENGE",
        "PARSE_ERROR",
        "BOT_DETECTED",
        "TIMEOUT",
    ],
)
def test_classify_error_status_all_unavailable_codes(code):
    """Every member of _UNAVAILABLE_ERROR_CODES maps to 'unavailable'."""
    from modules.m2_prices.service import _classify_error_status, _UNAVAILABLE_ERROR_CODES

    assert code in _UNAVAILABLE_ERROR_CODES
    assert _classify_error_status(code) == "unavailable"


async def test_retailer_results_mixed_statuses_end_to_end(client, db_session):
    """3 retailers: success, no_match (empty listings), unavailable (CHALLENGE) — each maps correctly."""
    product = await _seed_product(db_session)
    await _seed_retailers(db_session, ["amazon", "walmart", "target"])

    mock_responses = {
        "amazon": _make_container_response("amazon", 278.00),
        "walmart": ContainerResponse(
            retailer_id="walmart",
            query="Sony WH-1000XM5 Sony",
            extraction_time_ms=500,
            listings=[],
        ),
        "target": ContainerResponse(
            retailer_id="target",
            query="Sony WH-1000XM5 Sony",
            error=ContainerError(code="CHALLENGE", message="bot block"),
        ),
    }

    with patch("modules.m2_prices.service.ContainerClient") as MockClient:
        instance = MockClient.return_value
        instance.extract_all = AsyncMock(return_value=mock_responses)

        resp = await client.get(f"/api/v1/prices/{product.id}")

    assert resp.status_code == 200
    data = resp.json()
    statuses = {r["retailer_id"]: r["status"] for r in data["retailer_results"]}
    assert statuses == {
        "amazon": "success",
        "walmart": "no_match",
        "target": "unavailable",
    }


# MARK: - Marketplace relevance hardening (search-relevance-pack-1)


def test_extract_model_identifiers_emits_family_prefix():
    """Long hyphenated SKUs also emit a 4-digit family prefix.

    Razer sellers routinely list ``RZ07-0074`` instead of the full
    ``RZ07-00740100``; the family stem must pass the model-number gate.
    """
    from modules.m2_prices.service import _extract_model_identifiers
    out = _extract_model_identifiers("RZ07-00740100")
    assert "RZ07-00740100" in out
    assert "RZ07-0074" in out


def test_extract_model_identifiers_no_prefix_on_short_models():
    """Short SKUs like 'WH-1000XM5' don't generate a prefix (nothing to strip)."""
    from modules.m2_prices.service import _extract_model_identifiers
    out = _extract_model_identifiers("WH-1000XM5")
    # Single entry, no truncated variant emitted.
    assert out == ["WH-1000XM5"]


def test_extract_model_identifiers_catches_gaming_peripheral_sku():
    """Logitech G-series SKUs (G613, G915, G413) extract as model identifiers.

    Before the `[A-Z]{1,2}\\d{3,4}` pattern was added, the G-prefix continuous
    SKUs weren't captured — and a `G613` product's model gate silently passed
    a `G915` listing, letting Amazon's organic ranking swap models.
    """
    from modules.m2_prices.service import _extract_model_identifiers
    assert "G613" in _extract_model_identifiers("Logitech G613 Wireless")
    assert "G915" in _extract_model_identifiers("Logitech G915 X Lightspeed")
    assert "G413" in _extract_model_identifiers("Logitech G413 SE")


def test_extract_model_identifiers_catches_digit_led_appliance_sku():
    """5-digit + optional trailing letter SKUs (Hamilton Beach 49981A,
    Bissell 15999, Greenworks 24252) extract as identifiers.

    cat-rel-1-L3: pre-fix every _MODEL_PATTERNS entry required a leading
    letter prefix, so digit-led catalog numbers used by Hamilton Beach and
    similar brands never tripped the FB Marketplace soft model gate.
    """
    from modules.m2_prices.service import _extract_model_identifiers
    assert "49981A" in _extract_model_identifiers("Hamilton Beach 49981A Food Processor")
    assert "49963A" in _extract_model_identifiers("Hamilton Beach 49963A 14-Cup")
    assert "49988" in _extract_model_identifiers("Hamilton Beach 49988 Programmable Coffee Maker")
    assert "15999" in _extract_model_identifiers("Bissell 15999 BigGreen Carpet Cleaner")
    assert "24252" in _extract_model_identifiers("Greenworks 24252 16-Inch Mower")


def test_extract_model_identifiers_skips_capacity_units():
    """The digit-led pattern's negative lookahead skips BTU, mAh, lbs, etc.

    Otherwise "12000 BTU air conditioner" or "10000 mAh power bank" would
    extract the capacity number as a model SKU and trip the soft gate on
    legit listings that don't echo the same number.
    """
    from modules.m2_prices.service import _extract_model_identifiers
    # 12000 BTU should NOT be extracted (capacity, not model).
    out = _extract_model_identifiers("LG 12000 BTU Window Air Conditioner")
    assert "12000" not in out
    # 10000 mAh same — no model code in this title.
    out = _extract_model_identifiers("Anker 10000 mAh Portable Charger")
    assert "10000" not in out
    # Lowercase units also skipped (re.IGNORECASE on the lookahead).
    out = _extract_model_identifiers("LG 12000 btu Window AC")
    assert "12000" not in out


def test_extract_model_identifiers_does_not_collide_with_capacity_specs():
    """4-digit specs (1080P resolution, 4090Ti GPU) stay outside the 5-digit
    floor — this is the protection against false positives that justifies
    the 5-digit anchor over a more permissive 4-digit one.
    """
    from modules.m2_prices.service import _extract_model_identifiers
    out = _extract_model_identifiers("Sony BRAVIA 65-inch QLED 1080p")
    assert "1080" not in out
    assert "1080p" not in (s.lower() for s in out)
    out = _extract_model_identifiers("NVIDIA RTX 4090Ti 24GB")
    # 4090Ti gets caught by the 1-2-letter+digits gaming pattern via "RTX 4090"
    # GPU pattern, but the digit-led pattern itself MUST NOT emit "4090Ti".
    # Verify by checking that pattern-8's specific shape (5+ digits) doesn't fire.
    assert all(not (s[:5].isdigit() and len(s) >= 5) for s in out if s.startswith("4090"))


def test_score_rejects_g915_for_g613_product():
    """G613 product must reject a G915 Amazon listing at the model gate."""
    from modules.m2_prices.service import _score_listing_relevance
    product = Product(
        name="Logitech G613 Lightspeed Wireless Mechanical Gaming Keyboard",
        brand="Logitech",
        source="upcitemdb",
        source_raw={"gemini_model": None, "upcitemdb_raw": {"model": "920-008386"}},
    )
    score = _score_listing_relevance(
        "Logitech G915 X Lightspeed Low-Profile Wireless Gaming Keyboard", product
    )
    assert score == 0.0, "G915 must not pass as G613"


def test_score_listing_reads_upcitemdb_model():
    """Product resolved via UPCitemdb (gemini_model=None) still carries its
    model identifier when ``source_raw.upcitemdb_raw.model`` is populated.
    Razer Ornata must NOT match when the resolved product is an Orbweaver.
    """
    from modules.m2_prices.service import _score_listing_relevance

    product = Product(
        name="Razer Orbweaver Mechanical PC Gaming Keypad",
        brand="Razer",
        source="upcitemdb",
        source_raw={
            "gemini_model": None,
            "upcitemdb_raw": {"model": "RZ07-00740100-R3U1"},
        },
    )
    # Walmart returned this for an Orbweaver query — wrong product.
    ornata_score = _score_listing_relevance(
        "Razer Ornata V3 X Full-Size Wired Membrane Gaming Keyboard", product
    )
    assert ornata_score == 0.0, "Ornata must fail the model gate"

    # Legit eBay listing that uses the family-stem "RZ07-0074" must still pass.
    stem_score = _score_listing_relevance(
        "Razer Orbweaver RZ07-0074 Mechanical Gaming Keypad Green LEDs Open Box",
        product,
    )
    assert stem_score >= 0.4, "Family-stem listing must survive"


def test_fb_marketplace_soft_gate_allows_model_less_listings():
    """FB sellers often omit the model code; the soft gate keeps real listings."""
    from modules.m2_prices.service import _score_listing_relevance

    product = Product(
        name="Razer Orbweaver Chroma Gaming Keypad",
        brand="Razer",
        source="upcitemdb",
        source_raw={
            "gemini_model": None,
            "upcitemdb_raw": {"model": "RZ07-01440100-R3U1"},
        },
    )
    # No model code, real device — FB only.
    score_fb = _score_listing_relevance(
        "Razer Orbweaver Chroma Adjustable Mechanical Gaming Keypad",
        product,
        retailer_id="fb_marketplace",
    )
    assert 0.4 <= score_fb <= 0.5, "FB soft gate caps at 0.5 when model is absent"

    # Same listing on eBay — hard gate rejects (sellers there are expected
    # to include the code).
    score_ebay = _score_listing_relevance(
        "Razer Orbweaver Chroma Adjustable Mechanical Gaming Keypad",
        product,
        retailer_id="ebay_new",
    )
    assert score_ebay == 0.0


def test_pick_best_listing_price_outlier_filter_drops_keycaps():
    """Marketplace price-outlier filter drops sub-40% outliers when we have
    a usable sample (≥4 listings) — e.g. $14 keycaps vs a $50-median keypad pool.
    """
    from modules.m2_prices.service import PriceAggregationService
    from modules.m2_prices.schemas import ContainerListing, ContainerResponse

    product = Product(
        name="Razer Orbweaver Chroma Gaming Keypad",
        brand="Razer",
        source="upcitemdb",
        source_raw={
            "gemini_model": None,
            "upcitemdb_raw": {"model": "RZ07-01440100-R3U1"},
        },
    )
    listings = [
        ContainerListing(
            title="Razer Orbweaver Chroma Keycaps Replacement Set",
            price=14.00, currency="USD", is_new=True, is_available=True,
        ),
        ContainerListing(
            title="Razer Orbweaver Chroma RZ07-0144 Keypad",
            price=50.00, currency="USD", is_new=True, is_available=True,
        ),
        ContainerListing(
            title="Razer Orbweaver Chroma RZ07-0144 Gaming Keypad",
            price=65.00, currency="USD", is_new=True, is_available=True,
        ),
        ContainerListing(
            title="Razer Orbweaver Chroma RZ07-0144 Mechanical",
            price=70.00, currency="USD", is_new=True, is_available=True,
        ),
    ]
    response = ContainerResponse(
        retailer_id="ebay_new", query="razer orbweaver", listings=listings,
    )
    svc = PriceAggregationService.__new__(PriceAggregationService)
    best, _ = svc._pick_best_listing(response, product)
    # Median is 57.5 → floor 23. The $14 keycaps is out. Of the survivors,
    # the cheapest relevance-passing listing wins.
    assert best is not None
    assert best.price >= 40.0
    assert "keycap" not in best.title.lower()


# --- interstitial-parity-1 follow-up: FB Marketplace listing-level model
# strictness. Pre-fix the soft gate capped score at 0.5 but the underlying
# 0.4 RELEVANCE_THRESHOLD let drip-tray / accessory listings (overlap ≈ 0.5
# with brand + 2-3 generic tokens) survive — Breville BES870XL espresso
# machine ($499 retail) showed $18.95 hero on FB drip-tray; Weber Q1200
# ($199) showed $15.99 on grill-cover. Fix: when soft gate is active,
# require raw token overlap >= 0.6 before the cap.


def test_fb_soft_gate_rejects_drip_tray_when_model_missing():
    """Breville drip-tray listing — shares brand + generic tokens but lacks
    the distinguishing 'Barista'/'Express' tokens. Pre-fix this returned 0.5
    (passes 0.4 threshold, becomes BEST BARKAIN at $18.95). Post-fix
    overlap = 3/6 = 0.5 < 0.6 floor → 0.0 (rejected).
    """
    from modules.m2_prices.service import _score_listing_relevance

    product = Product(
        name="Breville The Barista Express Espresso Machine BES870XL",
        brand="Breville",
        source="upcitemdb",
        source_raw=None,
    )
    score = _score_listing_relevance(
        "Breville drip tray for espresso machine",
        product,
        retailer_id="fb_marketplace",
    )
    assert score == 0.0, (
        f"FB drip-tray listing must be rejected when model code missing, "
        f"got score={score}"
    )


def test_fb_soft_gate_keeps_legit_listing_when_model_missing():
    """A genuine seller listing without the SKU should still pass — overlap
    is high (5/6) so 0.6 floor is cleared; capped at 0.5 to reflect the
    missing-model penalty.
    """
    from modules.m2_prices.service import _score_listing_relevance

    product = Product(
        name="Breville The Barista Express Espresso Machine BES870XL",
        brand="Breville",
        source="upcitemdb",
        source_raw=None,
    )
    score = _score_listing_relevance(
        "Breville Barista Express espresso machine 15 bar stainless",
        product,
        retailer_id="fb_marketplace",
    )
    assert 0.4 <= score <= 0.5, (
        f"Legit FB listing must still pass at the soft-gate cap, got {score}"
    )


def test_fb_soft_gate_rejects_grill_cover():
    """Weber Q1200 grill cover — shares {weber, grill} but lacks Q1200 model
    + 'portable propane' descriptors. Overlap drops below 0.6 floor.
    """
    from modules.m2_prices.service import _score_listing_relevance

    product = Product(
        name="Weber Q1200 Portable Liquid Propane Gas Grill Black",
        brand="Weber",
        source="upcitemdb",
        source_raw=None,
    )
    score = _score_listing_relevance(
        "Weber portable grill cover",
        product,
        retailer_id="fb_marketplace",
    )
    assert score == 0.0


def test_fb_soft_gate_unchanged_for_non_fb_retailer():
    """eBay path is hard-gate: model required, no soft fallback. The 0.6
    overlap floor only applies when soft gate is active.
    """
    from modules.m2_prices.service import _score_listing_relevance

    product = Product(
        name="Breville The Barista Express Espresso Machine BES870XL",
        brand="Breville",
        source="upcitemdb",
        source_raw=None,
    )
    # Same drip-tray listing on eBay — model missing → hard-gate reject (0.0).
    score = _score_listing_relevance(
        "Breville drip tray for espresso machine",
        product,
        retailer_id="ebay_new",
    )
    assert score == 0.0


def test_extract_model_normalizes_single_letter_space_digits():
    """Weber Q1200 stored as 'Weber Q 1200' (Gemini space-separated form)
    must yield Q1200 as a model identifier. Pre-fix the FB soft gate
    didn't fire because no identifiers were extracted, leaving $15.99
    grill-cover listings to win the hero. Post-fix Q1200 IS extracted
    so the soft gate trips on listings missing the model code.
    """
    from modules.m2_prices.service import _extract_model_identifiers

    idents = _extract_model_identifiers("Weber Q 1200 1-Burner Propane Gas Grill")
    assert any("Q1200" in i.upper() for i in idents), (
        f"Q 1200 should normalize to Q1200, got {idents}"
    )

    # Negative control: single-letter + 2-digit form ("Q 12") shouldn't
    # collapse — too generic, would match prose fragments. Pattern requires
    # 3-4 digits.
    idents = _extract_model_identifiers("Use Q 12 of these in the recipe")
    assert not any("Q12" in i.upper() for i in idents)


def test_brand_match_falls_back_to_product_name_first_word():
    """Cuisinart UPCs come back from UPCitemdb with brand='Conair Corporation'
    (parent company). Real Cuisinart listings never say Conair. Pre-fix
    Rule 3 rejected every Cuisinart listing on its own → 0/9 success on
    every Cuisinart probe. Post-fix the leading word of product.name
    ('Cuisinart') is accepted as a sub-brand fallback.

    Uses a single-token product name to keep the test focused on Rule 3.
    Multi-word names trigger the model-pattern hard gate at Rule 1, which
    is a separate concern.
    """
    from modules.m2_prices.service import _score_listing_relevance

    product = Product(
        name="Cuisinart Food Processor",
        brand="Conair Corporation",
        source="upcitemdb",
        source_raw=None,
    )
    score = _score_listing_relevance(
        "Cuisinart Premium 7-Cup Food Processor White",
        product,
        retailer_id="amazon",
    )
    assert score > 0.0, (
        f"Cuisinart listing must pass via product.name fallback, got {score}"
    )


def test_third_party_for_brand_template_rejected():
    """Uniflasy / OEM / generic third-party replacement parts use the
    template "{their brand} … for {real brand} {model}" and pass the
    basic brand-presence check (Weber appears in title). Rule 3b rejects
    them by detecting the third-party leading word + "for {brand}"
    preposition.
    """
    from modules.m2_prices.service import _score_listing_relevance

    product = Product(
        name="Weber Q 1200 1-Burner Propane Gas Grill Black",
        brand="Weber",
        source="upcitemdb",
        source_raw=None,
    )
    # Real Amazon listings (multiple ASINs share the pattern) — both
    # third-party-brand-led and digit-led titles, all carrying "for Weber"
    # in the title body.
    for title in (
        "Uniflasy 60040 17 Inch Grill Burner Tube for Weber Q1200 Q1000 Q100",
        "304 Stainless Steel 60040 Grill Burner Tube for Weber Q1000, Q1200",
        "6FT for Weber Adapter Hose for Weber Q Series, for Weber Traveler",
        "Burner for Weber Q100, Q120, Q1000, Q1200, Baby Q Gas Grill 17inch",
    ):
        score = _score_listing_relevance(title, product, retailer_id="amazon")
        assert score == 0.0, (
            f"Third-party 'for Weber' replacement listing must be rejected, "
            f"title={title!r} got {score}"
        )

    # Negative control: actual Weber-branded grill listing must still pass.
    score_real = _score_listing_relevance(
        "Weber Q1200 Liquid Propane Portable Gas Grill, Black",
        product,
        retailer_id="amazon",
    )
    assert score_real > 0.0

    # NOTE: Decodo-stripped Amazon titles (e.g., "Q1200 Liquid Propane …
    # Titanium" without the "Weber" prefix) currently fail Rule 3 outright
    # because no brand candidate appears in the title. That's a separate
    # pre-existing adapter issue — accepting it as the price of demo
    # safety: Amazon shows "not found" rather than a $15.99 burner tube.


def test_brand_match_fallback_does_not_open_unrelated_brands():
    """The fallback only fires when the product.name leading word is
    actually in the listing — so a Whirlpool listing for a 'Cuisinart 7 Cup'
    product still gets rejected (no 'cuisinart' anywhere on a Whirlpool
    blender title).
    """
    from modules.m2_prices.service import _score_listing_relevance

    product = Product(
        name="Cuisinart 7 Cup Food Processor",
        brand="Conair Corporation",
        source="upcitemdb",
        source_raw=None,
    )
    # Whirlpool listing — neither "Conair" nor "Cuisinart" present → reject.
    score = _score_listing_relevance(
        "Whirlpool 7-Cup Food Processor Stainless",
        product,
        retailer_id="amazon",
    )
    assert score == 0.0
