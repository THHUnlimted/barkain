"""Tests for M2 eBay Browse API adapter.

8 tests:
- OAuth exchange: token minted, cached, refreshed on expiry
- 401 from search clears the token cache
- Happy path: maps itemSummaries → ContainerListing
- Invalid retailer_id returns INVALID_RETAILER error
- is_configured() behavior
- condition filter is numeric (conditionIds), not text
- Search HTTP 5xx returns HTTP_ERROR with status code in details
- Malformed item (no price) is silently dropped, not crashed
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.config import Settings
from modules.m2_prices.adapters import ebay_browse_api
from modules.m2_prices.adapters.ebay_browse_api import (
    CONDITION_IDS,
    _clear_token_cache,
    _get_app_token,
    fetch_ebay,
    is_configured,
)


# MARK: - Helpers


def _cfg(**overrides) -> Settings:
    base = dict(EBAY_APP_ID="test-app-id", EBAY_CERT_ID="test-cert-id")
    base.update(overrides)
    return Settings(**base)


def _item(
    title: str = "Apple AirPods Pro 2",
    price: float = 199.99,
    condition: str = "New",
    condition_id: str = "1000",
    seller: str = "apple_authorized",
) -> dict:
    return {
        "title": title,
        "price": {"value": str(price), "currency": "USD"},
        "condition": condition,
        "conditionId": condition_id,
        "seller": {"username": seller},
        "image": {"imageUrl": "https://img.ebay/x.jpg"},
        "itemWebUrl": "https://www.ebay.com/itm/1",
    }


@pytest.fixture(autouse=True)
def _reset_token_cache():
    _clear_token_cache()
    yield
    _clear_token_cache()


# MARK: - Configuration


def test_is_configured_requires_both_id_and_cert():
    assert is_configured(_cfg()) is True
    assert is_configured(_cfg(EBAY_APP_ID="")) is False
    assert is_configured(_cfg(EBAY_CERT_ID="")) is False


# MARK: - OAuth


@pytest.mark.asyncio
@respx.mock
async def test_get_app_token_mints_and_caches():
    """First call hits OAuth; second call reuses the cached token."""
    route = respx.post("https://api.ebay.com/identity/v1/oauth2/token").mock(
        return_value=httpx.Response(
            200, json={"access_token": "tok-abc", "expires_in": 7200}
        )
    )
    cfg = _cfg()
    t1 = await _get_app_token(cfg)
    t2 = await _get_app_token(cfg)
    assert t1 == "tok-abc"
    assert t2 == "tok-abc"
    assert route.call_count == 1


# MARK: - Search happy path


@pytest.mark.asyncio
@respx.mock
async def test_fetch_ebay_happy_path_maps_items():
    respx.post("https://api.ebay.com/identity/v1/oauth2/token").mock(
        return_value=httpx.Response(
            200, json={"access_token": "tok", "expires_in": 7200}
        )
    )
    respx.get("https://api.ebay.com/buy/browse/v1/item_summary/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "total": 1234,
                "itemSummaries": [
                    _item(title="AirPods Pro 2 A", price=149.99, condition_id="1000"),
                    _item(title="AirPods Pro 2 B", price=129.99, condition_id="1000"),
                ],
            },
        )
    )
    resp = await fetch_ebay(
        retailer_id="ebay_new",
        query="Apple AirPods Pro 2",
        max_listings=5,
        cfg=_cfg(),
    )
    assert resp.error is None
    assert len(resp.listings) == 2
    assert resp.listings[0].title == "AirPods Pro 2 A"
    assert resp.listings[0].price == 149.99
    assert resp.listings[0].condition == "new"
    assert resp.listings[0].extraction_method == "ebay_browse_api"
    assert resp.metadata.script_version == "ebay_browse_api/1.0"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_ebay_condition_filter_is_numeric_conditionIds():
    """The filter param must be ``conditionIds:{1000,...}`` (numeric), not
    ``conditions:{NEW}`` (text) — the text form returns mixed conditions."""
    respx.post("https://api.ebay.com/identity/v1/oauth2/token").mock(
        return_value=httpx.Response(
            200, json={"access_token": "tok", "expires_in": 7200}
        )
    )
    captured = {}
    def _capture(request):
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"itemSummaries": []})

    respx.get("https://api.ebay.com/buy/browse/v1/item_summary/search").mock(
        side_effect=_capture
    )
    await fetch_ebay(
        retailer_id="ebay_used",
        query="x",
        max_listings=3,
        cfg=_cfg(),
    )
    url = captured["url"]
    assert "conditionIds" in url
    for cid in CONDITION_IDS["ebay_used"]:
        assert str(cid) in url
    # eBay's filter separator is ``|`` (OR), not ``,``. Silent no-op otherwise.
    expected_ids = "|".join(str(i) for i in CONDITION_IDS["ebay_used"])
    assert expected_ids in url or expected_ids.replace("|", "%7C") in url


# MARK: - Error handling


@pytest.mark.asyncio
async def test_fetch_ebay_invalid_retailer_id():
    resp = await fetch_ebay(
        retailer_id="not_a_real_ebay",
        query="x",
        cfg=_cfg(),
    )
    assert resp.error is not None
    assert resp.error.code == "INVALID_RETAILER"
    assert resp.listings == []


@pytest.mark.asyncio
@respx.mock
async def test_fetch_ebay_401_clears_token_cache():
    """A 401 from Browse API invalidates the cached token so the next call refreshes."""
    respx.post("https://api.ebay.com/identity/v1/oauth2/token").mock(
        return_value=httpx.Response(
            200, json={"access_token": "tok", "expires_in": 7200}
        )
    )
    respx.get("https://api.ebay.com/buy/browse/v1/item_summary/search").mock(
        return_value=httpx.Response(401, json={"errors": [{"message": "expired"}]})
    )
    resp = await fetch_ebay(retailer_id="ebay_new", query="x", cfg=_cfg())
    assert resp.error is not None
    assert resp.error.code == "HTTP_ERROR"
    assert resp.error.details["status_code"] == 401
    # Token cache should have been cleared
    assert ebay_browse_api._token_cache["token"] is None


@pytest.mark.asyncio
@respx.mock
async def test_fetch_ebay_5xx_returns_http_error():
    respx.post("https://api.ebay.com/identity/v1/oauth2/token").mock(
        return_value=httpx.Response(
            200, json={"access_token": "tok", "expires_in": 7200}
        )
    )
    respx.get("https://api.ebay.com/buy/browse/v1/item_summary/search").mock(
        return_value=httpx.Response(503, text="Service Unavailable")
    )
    resp = await fetch_ebay(retailer_id="ebay_new", query="x", cfg=_cfg())
    assert resp.error is not None
    assert resp.error.code == "HTTP_ERROR"
    assert resp.error.details["status_code"] == 503


@pytest.mark.asyncio
@respx.mock
async def test_fetch_ebay_drops_malformed_items_without_crashing():
    respx.post("https://api.ebay.com/identity/v1/oauth2/token").mock(
        return_value=httpx.Response(
            200, json={"access_token": "tok", "expires_in": 7200}
        )
    )
    respx.get("https://api.ebay.com/buy/browse/v1/item_summary/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "itemSummaries": [
                    {"title": "no price here"},  # missing price → dropped
                    _item(title="Valid", price=99.0),
                    {"price": {"value": "10"}},  # missing title → dropped
                ]
            },
        )
    )
    resp = await fetch_ebay(retailer_id="ebay_new", query="x", cfg=_cfg())
    assert resp.error is None
    assert len(resp.listings) == 1
    assert resp.listings[0].title == "Valid"
