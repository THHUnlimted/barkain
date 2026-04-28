"""Tests for M14 misc-retailer slot (Step 3n).

Service-level tests fixture-up a Product row, then patch
`_serper_shopping_fetch` at the adapter import site. The autouse
`_serper_shopping_disabled` fixture in conftest already patches that
to None for every test; tests in this file override the patch with a
fixture payload when they want to exercise S.

Endpoint tests use the existing `client` fixture.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from modules.m1_product.models import Product
from modules.m14_misc_retailer.adapters.disabled import DisabledAdapter
from modules.m14_misc_retailer.adapters.serper_shopping import (
    SerperShoppingAdapter,
    _parse_price_cents,
    _normalize_source,
)
from modules.m14_misc_retailer.schemas import MiscMerchantRow
from modules.m14_misc_retailer.service import (
    KNOWN_RETAILER_DOMAINS,
    MISC_MAX_ROWS,
    MISC_REDIS_CACHE_TTL_SEC,
    MISC_REDIS_INFLIGHT_TTL_SEC,
    MiscRetailerService,
    ProductNotFoundError,
    is_known_retailer,
)


# MARK: - Fixture payloads


def _serper_payload(extras: list[dict] | None = None) -> list[dict]:
    base: list[dict[str, Any]] = [
        {
            "title": "Royal Canin Adult Maintenance Dog Food",
            "source": "Chewy",
            "link": "https://www.google.com/shopping/product/c1",
            "price": "$84.99",
            "rating": 4.7,
            "ratingCount": 1024,
            "productId": "rc-adult-12",
            "position": 1,
        },
        {
            "title": "Royal Canin",
            "source": "Petco",
            "link": "https://www.google.com/shopping/product/p1",
            "price": "$92.49",
            "rating": 4.6,
            "ratingCount": 800,
            "productId": "rc-adult-12-petco",
            "position": 2,
        },
        {
            "title": "Royal Canin Adult",
            "source": "Petflow",
            "link": "https://www.google.com/shopping/product/pf1",
            "price": "$78.99",
            "rating": None,
            "ratingCount": None,
            "productId": None,
            "position": 3,
        },
        {
            "title": "Royal Canin Adult Maintenance — Walmart",
            "source": "Walmart",
            "link": "https://www.google.com/shopping/product/w1",
            "price": "$80.00",
            "position": 4,
        },
        {
            "title": "Royal Canin Adult — Amazon",
            "source": "Amazon.com",
            "link": "https://www.google.com/shopping/product/a1",
            "price": "$83.50",
            "position": 5,
        },
    ]
    if extras:
        base.extend(extras)
    return base


async def _seed_product(db_session, *, name: str = "Royal Canin Adult") -> Product:
    product = Product(
        upc="0030111621207",
        name=name,
        brand="Royal Canin",
        category="Pet Supplies > Dog > Food",
        source="test",
    )
    db_session.add(product)
    await db_session.flush()
    return product


# MARK: - Pure-function helpers


def test_known_retailer_domains_covers_nine_active_retailers_plus_mirrors():
    # 9 retailers × 2 token forms (domain + display) ± Walmart + FB extras
    expected = {
        "amazon", "amazon.com", "best buy", "bestbuy.com",
        "walmart", "walmart.com", "target", "target.com",
        "home depot", "homedepot.com", "ebay", "ebay.com",
        "back market", "backmarket", "backmarket.com",
        "facebook.com", "facebook marketplace", "fb marketplace",
    }
    assert KNOWN_RETAILER_DOMAINS == frozenset(expected)


@pytest.mark.parametrize(
    "source_normalized, expected",
    [
        ("walmart", True),
        ("walmart business", True),  # substring match
        ("amazon.com", True),
        ("best buy outlet", True),
        ("ebay", True),
        ("chewy", False),
        ("petco.com", False),
        ("petflow", False),
        ("", False),
    ],
)
def test_is_known_retailer(source_normalized, expected):
    assert is_known_retailer(source_normalized) is expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("$20.98", 2098),
        ("$1,049.00", 104900),
        ("$0.99", 99),
        ("Free", None),
        ("$Free", None),
        ("", None),
        (None, None),
        (19.99, 1999),
        (20, 2000),
    ],
)
def test_parse_price_cents(raw, expected):
    assert _parse_price_cents(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Petco.com", "petco.com"),
        ("Pet Supplies Plus", "pet supplies plus"),
        ("  Chewy  ", "chewy"),
        ("WALMART", "walmart"),
        ("", ""),
    ],
)
def test_normalize_source(raw, expected):
    assert _normalize_source(raw) == expected


# MARK: - Adapter happy path


@pytest.mark.asyncio
async def test_serper_adapter_normalizes_and_skips_invalid_rows(monkeypatch):
    payload = _serper_payload(extras=[
        {"title": "", "source": "X", "link": "https://x", "price": "$1"},  # empty title
        {"title": "ok", "source": "", "link": "https://x", "price": "$1"},  # empty source
        {"title": "ok", "source": "Y", "link": "ftp://x", "price": "$1"},   # bad scheme
    ])
    monkeypatch.setattr(
        "modules.m14_misc_retailer.adapters.serper_shopping._serper_shopping_fetch",
        AsyncMock(return_value=payload),
    )

    adapter = SerperShoppingAdapter()
    rows = await adapter.fetch("royal canin")

    assert len(rows) == 5  # the 3 invalid entries dropped, all 5 base entries kept
    assert all(isinstance(r, MiscMerchantRow) for r in rows)
    assert rows[0].source_normalized == "chewy"
    assert rows[0].price_cents == 8499


# MARK: - Service: filter + cap + cache + inflight


@pytest.mark.asyncio
async def test_service_filters_known_retailers_and_caps(
    db_session, fake_redis, monkeypatch
):
    product = await _seed_product(db_session)
    monkeypatch.setattr(
        "modules.m14_misc_retailer.adapters.serper_shopping._serper_shopping_fetch",
        AsyncMock(return_value=_serper_payload()),
    )

    service = MiscRetailerService(
        db=db_session, redis=fake_redis, adapter=SerperShoppingAdapter()
    )
    rows = await service.get_misc_retailers(product.id)

    # 5 raw → 3 filtered (Walmart + Amazon dropped) → cap at MISC_MAX_ROWS=3.
    assert len(rows) == MISC_MAX_ROWS == 3
    sources = {r.source_normalized for r in rows}
    assert "walmart" not in sources
    assert "amazon.com" not in sources
    assert "amazon" not in sources
    assert sources == {"chewy", "petco", "petflow"}
    # Sorted by position ascending.
    assert [r.position for r in rows] == [1, 2, 3]


@pytest.mark.asyncio
async def test_service_writes_redis_cache_with_six_hour_ttl(
    db_session, fake_redis, monkeypatch
):
    product = await _seed_product(db_session)
    monkeypatch.setattr(
        "modules.m14_misc_retailer.adapters.serper_shopping._serper_shopping_fetch",
        AsyncMock(return_value=_serper_payload()),
    )

    service = MiscRetailerService(
        db=db_session, redis=fake_redis, adapter=SerperShoppingAdapter()
    )
    await service.get_misc_retailers(product.id)

    cache_key = f"misc:{product.id}"
    raw = await fake_redis.get(cache_key)
    assert raw is not None
    payload = json.loads(raw)
    assert isinstance(payload, list) and len(payload) == 3
    ttl = await fake_redis.ttl(cache_key)
    # Allow a small skew for time elapsed during the test.
    assert MISC_REDIS_CACHE_TTL_SEC - 10 < ttl <= MISC_REDIS_CACHE_TTL_SEC

    # Inflight key cleared after success.
    inflight_ttl = await fake_redis.ttl(f"misc:inflight:{product.id}")
    assert inflight_ttl == -2  # key absent


@pytest.mark.asyncio
async def test_service_cache_hit_short_circuits_adapter(
    db_session, fake_redis, monkeypatch
):
    product = await _seed_product(db_session)
    fetch_mock = AsyncMock(return_value=_serper_payload())
    monkeypatch.setattr(
        "modules.m14_misc_retailer.adapters.serper_shopping._serper_shopping_fetch",
        fetch_mock,
    )
    service = MiscRetailerService(
        db=db_session, redis=fake_redis, adapter=SerperShoppingAdapter()
    )

    await service.get_misc_retailers(product.id)
    assert fetch_mock.await_count == 1
    await service.get_misc_retailers(product.id)
    assert fetch_mock.await_count == 1  # cache hit, no second call


@pytest.mark.asyncio
async def test_service_inflight_singleflight(db_session, fake_redis, monkeypatch):
    """Two concurrent requests should singleflight on the inflight marker —
    only one Serper call. We use an asyncio.Event in the mock to make the
    first call park long enough that the second sees the inflight bucket."""
    product = await _seed_product(db_session)
    release = asyncio.Event()
    payload = _serper_payload()

    async def slow_fetch(_query):
        await release.wait()
        return payload

    monkeypatch.setattr(
        "modules.m14_misc_retailer.adapters.serper_shopping._serper_shopping_fetch",
        AsyncMock(side_effect=slow_fetch),
    )

    service_a = MiscRetailerService(
        db=db_session, redis=fake_redis, adapter=SerperShoppingAdapter()
    )
    service_b = MiscRetailerService(
        db=db_session, redis=fake_redis, adapter=SerperShoppingAdapter()
    )

    # Pre-write the inflight key by parking the first call in flight.
    task_a = asyncio.create_task(service_a.get_misc_retailers(product.id))
    # Yield to let task_a reach the adapter call (which writes inflight key
    # before awaiting the slow fetch).
    for _ in range(10):
        await asyncio.sleep(0)
        if await fake_redis.exists(f"misc:inflight:{product.id}"):
            break

    # Second caller should see the inflight key (empty, because no rows
    # yet) and NOT dispatch a second Serper fetch — `slow_fetch` would
    # otherwise hang on `release` and the test would time out.
    rows_b = await asyncio.wait_for(
        service_b.get_misc_retailers(product.id), timeout=1.0
    )
    assert rows_b == []

    release.set()
    rows_a = await asyncio.wait_for(task_a, timeout=2.0)
    assert len(rows_a) == 3


@pytest.mark.asyncio
async def test_service_inflight_pre_yield_ordering(
    db_session, fake_redis, monkeypatch
):
    """Inflight key MUST be written before the adapter is dispatched (PR #73
    pre-yield ordering)."""
    product = await _seed_product(db_session)
    captured: dict[str, bool] = {"inflight_seen_during_fetch": False}

    async def fetch_inspecting_redis(_query):
        captured["inflight_seen_during_fetch"] = bool(
            await fake_redis.exists(f"misc:inflight:{product.id}")
        )
        return _serper_payload()

    monkeypatch.setattr(
        "modules.m14_misc_retailer.adapters.serper_shopping._serper_shopping_fetch",
        AsyncMock(side_effect=fetch_inspecting_redis),
    )

    service = MiscRetailerService(
        db=db_session, redis=fake_redis, adapter=SerperShoppingAdapter()
    )
    await service.get_misc_retailers(product.id)

    assert captured["inflight_seen_during_fetch"] is True
    inflight_ttl_after = await fake_redis.ttl(f"misc:inflight:{product.id}")
    # Cleared after success — TTL on a missing key is -2 in fakeredis.
    assert inflight_ttl_after == -2


# MARK: - Disabled + stub adapters


@pytest.mark.asyncio
async def test_disabled_adapter_returns_empty_without_serper(
    db_session, fake_redis, monkeypatch
):
    product = await _seed_product(db_session)
    fetch_mock = AsyncMock(return_value=_serper_payload())
    monkeypatch.setattr(
        "modules.m14_misc_retailer.adapters.serper_shopping._serper_shopping_fetch",
        fetch_mock,
    )

    service = MiscRetailerService(
        db=db_session, redis=fake_redis, adapter=DisabledAdapter()
    )
    rows = await service.get_misc_retailers(product.id)

    assert rows == []
    fetch_mock.assert_not_awaited()


@pytest.mark.parametrize(
    "module_path, class_name",
    [
        (
            "modules.m14_misc_retailer.adapters.google_shopping_container",
            "GoogleShoppingContainerAdapter",
        ),
        (
            "modules.m14_misc_retailer.adapters.decodo_serp_api",
            "DecodoSerpApiAdapter",
        ),
        (
            "modules.m14_misc_retailer.adapters.oxylabs_serp_api",
            "OxylabsSerpApiAdapter",
        ),
        (
            "modules.m14_misc_retailer.adapters.brightdata_serp_api",
            "BrightDataSerpApiAdapter",
        ),
    ],
)
@pytest.mark.asyncio
async def test_stub_adapters_raise_not_implemented(module_path, class_name):
    import importlib

    module = importlib.import_module(module_path)
    adapter = getattr(module, class_name)()
    with pytest.raises(NotImplementedError):
        await adapter.fetch("anything")


# MARK: - Product validation


@pytest.mark.asyncio
async def test_unknown_product_raises(db_session, fake_redis):
    import uuid as _uuid

    service = MiscRetailerService(
        db=db_session, redis=fake_redis, adapter=DisabledAdapter()
    )
    with pytest.raises(ProductNotFoundError):
        await service.get_misc_retailers(_uuid.uuid4())


# MARK: - Endpoint smoke


@pytest.mark.asyncio
async def test_get_endpoint_returns_capped_filtered_rows(
    client, db_session, monkeypatch
):
    product = await _seed_product(db_session)
    await db_session.commit()

    monkeypatch.setattr(
        "modules.m14_misc_retailer.adapters.serper_shopping._serper_shopping_fetch",
        AsyncMock(return_value=_serper_payload()),
    )
    from app.config import settings

    monkeypatch.setattr(settings, "MISC_RETAILER_ADAPTER", "serper_shopping")

    response = await client.get(f"/api/v1/misc/{product.id}")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert len(body) == MISC_MAX_ROWS
    sources = {row["source_normalized"] for row in body}
    assert "walmart" not in sources
    assert "amazon.com" not in sources


@pytest.mark.asyncio
async def test_get_endpoint_404_for_unknown_product(client):
    import uuid as _uuid

    response = await client.get(f"/api/v1/misc/{_uuid.uuid4()}")
    assert response.status_code == 404
    body = response.json()
    assert body["detail"]["error"]["code"] == "PRODUCT_NOT_FOUND"


# MARK: - TTL constant sanity


def test_inflight_ttl_is_30_seconds_not_120():
    """Misc-retailer inflight TTL is sized for Serper Shopping's 1.4–2.5 s
    p50 wall-clock — NOT the 120 s `m2_prices` uses for the 9-scraper SSE
    fan-out where Best Buy can hit ~91 s p95. Pin the constant so a
    'helpful' refactor doesn't accidentally bump it back up."""
    assert MISC_REDIS_INFLIGHT_TTL_SEC == 30
