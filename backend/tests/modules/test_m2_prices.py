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
