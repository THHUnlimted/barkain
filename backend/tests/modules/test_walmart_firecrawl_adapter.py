"""Tests for M2 walmart_firecrawl adapter — demo path via Firecrawl API."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from app.config import Settings
from modules.m2_prices.adapters.walmart_firecrawl import fetch_walmart

# MARK: - Fixtures

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"
NEXT_DATA_SAMPLE = (FIXTURE_DIR / "walmart_next_data_sample.html").read_text(
    encoding="utf-8"
)
CHALLENGE_SAMPLE = (FIXTURE_DIR / "walmart_challenge_sample.html").read_text(
    encoding="utf-8"
)


def _test_settings(**overrides) -> Settings:
    base = dict(
        FIRECRAWL_API_KEY="fc-test-key",
        WALMART_ADAPTER="firecrawl",
    )
    base.update(overrides)
    return Settings(**base)


# MARK: - Happy path


@pytest.mark.asyncio
@respx.mock
async def test_firecrawl_success_returns_listings():
    cfg = _test_settings()
    respx.post("https://api.firecrawl.dev/v1/scrape").mock(
        return_value=httpx.Response(
            200,
            json={"success": True, "data": {"rawHtml": NEXT_DATA_SAMPLE}},
        )
    )

    result = await fetch_walmart(query="Apple AirPods Pro", cfg=cfg)

    assert result.error is None
    assert len(result.listings) == 4
    assert result.listings[0].extraction_method == "firecrawl_next_data"


@pytest.mark.asyncio
@respx.mock
async def test_firecrawl_sends_bearer_auth_and_country():
    cfg = _test_settings(FIRECRAWL_API_KEY="fc-mykey")
    route = respx.post("https://api.firecrawl.dev/v1/scrape").mock(
        return_value=httpx.Response(
            200, json={"success": True, "data": {"rawHtml": NEXT_DATA_SAMPLE}}
        )
    )

    await fetch_walmart(query="test", cfg=cfg)

    assert route.called
    req = route.calls[0].request
    assert req.headers["authorization"] == "Bearer fc-mykey"
    body = req.content.decode()
    assert '"country": "US"' in body or '"country":"US"' in body
    assert '"rawHtml"' in body


# MARK: - Error paths


@pytest.mark.asyncio
async def test_firecrawl_without_api_key_reports_adapter_error():
    cfg = _test_settings(FIRECRAWL_API_KEY="")
    result = await fetch_walmart(query="test", cfg=cfg)
    assert result.error is not None
    assert result.error.code == "ADAPTER_NOT_CONFIGURED"


@pytest.mark.asyncio
@respx.mock
async def test_firecrawl_http_error_is_surfaced():
    cfg = _test_settings()
    respx.post("https://api.firecrawl.dev/v1/scrape").mock(
        return_value=httpx.Response(429, text="rate limited")
    )

    result = await fetch_walmart(query="test", cfg=cfg)

    assert result.error is not None
    assert result.error.code == "FIRECRAWL_HTTP_ERROR"
    assert result.error.details["status_code"] == 429


@pytest.mark.asyncio
@respx.mock
async def test_firecrawl_success_false_is_surfaced():
    cfg = _test_settings()
    respx.post("https://api.firecrawl.dev/v1/scrape").mock(
        return_value=httpx.Response(
            200, json={"success": False, "error": "site unreachable"}
        )
    )

    result = await fetch_walmart(query="test", cfg=cfg)

    assert result.error is not None
    assert result.error.code == "FIRECRAWL_UNSUCCESSFUL"


@pytest.mark.asyncio
@respx.mock
async def test_firecrawl_challenge_in_response_is_reported():
    """Unexpected but possible — Firecrawl returns a challenge page verbatim."""
    cfg = _test_settings()
    respx.post("https://api.firecrawl.dev/v1/scrape").mock(
        return_value=httpx.Response(
            200, json={"success": True, "data": {"rawHtml": CHALLENGE_SAMPLE}}
        )
    )

    result = await fetch_walmart(query="test", cfg=cfg)

    assert result.error is not None
    assert result.error.code == "CHALLENGE"


@pytest.mark.asyncio
@respx.mock
async def test_firecrawl_empty_body_is_reported():
    cfg = _test_settings()
    respx.post("https://api.firecrawl.dev/v1/scrape").mock(
        return_value=httpx.Response(
            200, json={"success": True, "data": {"rawHtml": ""}}
        )
    )

    result = await fetch_walmart(query="test", cfg=cfg)

    assert result.error is not None
    assert result.error.code == "FIRECRAWL_EMPTY_BODY"


# MARK: - First-Party Filter (Step 2b — SP-L5)


def test_walmart_first_party_seller_kept():
    """Walmart.com seller is NOT marked as third-party."""
    from modules.m2_prices.adapters._walmart_parser import _map_item_to_listing

    item = {
        "name": "Sony WH-1000XM5 Headphones",
        "price": 278.00,
        "sellerName": "Walmart.com",
        "canonicalUrl": "/ip/12345",
    }
    listing = _map_item_to_listing(item)
    assert listing is not None
    assert listing.is_third_party is False
    assert listing.seller == "Walmart.com"


def test_walmart_third_party_seller_filtered():
    """Third-party seller listings are filtered by extract_listings when first_party_only=True."""
    from modules.m2_prices.adapters._walmart_parser import extract_listings

    # Build minimal HTML with __NEXT_DATA__ containing one Walmart and one third-party item
    items_json = [
        {"name": "Sony WH-1000XM5", "price": 278.00, "sellerName": "Walmart.com", "canonicalUrl": "/ip/1"},
        {"name": "Sony WH-1000XM5", "price": 250.00, "sellerName": "RHEA Store", "canonicalUrl": "/ip/2"},
    ]
    import json as _json

    next_data = {"props": {"pageProps": {"initialData": {"searchResult": {"itemStacks": [{"items": items_json}]}}}}}
    html = f'<script id="__NEXT_DATA__" type="application/json">{_json.dumps(next_data)}</script>'

    listings = extract_listings(html, first_party_only=True)
    assert len(listings) == 1
    assert listings[0].seller == "Walmart.com"
    assert listings[0].is_third_party is False


def test_walmart_all_third_party_returns_cheapest():
    """When ALL listings are third-party, returns the cheapest one."""
    from modules.m2_prices.adapters._walmart_parser import extract_listings

    items_json = [
        {"name": "Sony WH-1000XM5", "price": 300.00, "sellerName": "SellerA", "canonicalUrl": "/ip/1"},
        {"name": "Sony WH-1000XM5", "price": 250.00, "sellerName": "SellerB", "canonicalUrl": "/ip/2"},
    ]
    import json as _json

    next_data = {"props": {"pageProps": {"initialData": {"searchResult": {"itemStacks": [{"items": items_json}]}}}}}
    html = f'<script id="__NEXT_DATA__" type="application/json">{_json.dumps(next_data)}</script>'

    listings = extract_listings(html, first_party_only=True)
    assert len(listings) == 1
    assert listings[0].price == 250.00
    assert listings[0].is_third_party is True


def test_walmart_first_party_filter_disabled():
    """With first_party_only=False, all listings are returned."""
    from modules.m2_prices.adapters._walmart_parser import extract_listings

    items_json = [
        {"name": "Sony WH-1000XM5", "price": 278.00, "sellerName": "Walmart.com", "canonicalUrl": "/ip/1"},
        {"name": "Sony WH-1000XM5", "price": 250.00, "sellerName": "RHEA Store", "canonicalUrl": "/ip/2"},
    ]
    import json as _json

    next_data = {"props": {"pageProps": {"initialData": {"searchResult": {"itemStacks": [{"items": items_json}]}}}}}
    html = f'<script id="__NEXT_DATA__" type="application/json">{_json.dumps(next_data)}</script>'

    listings = extract_listings(html, first_party_only=False)
    assert len(listings) == 2
