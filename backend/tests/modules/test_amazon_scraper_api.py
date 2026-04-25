"""Tests for M2 Amazon Scraper API adapter (Decodo).

Mirrors the structure of test_best_buy_api.py:
- is_configured() behavior
- Happy path: maps organic items → ContainerListing, drops sponsored
- price_strikethrough > price → original_price set; equal/missing → None
- ASIN missing or price missing → drop the item
- Missing auth → NOT_CONFIGURED (no network call)
- Decodo returning raw HTML (parse failure) → PARSE_ERROR
- 5xx → HTTP_ERROR with status code
- Connection failure → REQUEST_FAILED
- container_client routes amazon through the adapter when DECODO_SCRAPER_API_AUTH set
- container_client falls back to container path when auth missing
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.config import Settings
from modules.m2_prices.adapters.amazon_scraper_api import (
    fetch_amazon,
    is_configured,
)


def _cfg(**overrides) -> Settings:
    base = dict(DECODO_SCRAPER_API_AUTH="Basic dGVzdDp0ZXN0")
    base.update(overrides)
    return Settings(**base)


def _organic(
    asin: str = "B0FQFB8FMG",
    title: str = "AirPods Pro 3",
    price: float = 199.99,
    strikethrough: float | None = None,
    is_sponsored: bool = False,
) -> dict:
    return {
        "asin": asin,
        "title": title,
        "price": price,
        "currency": "USD",
        "price_strikethrough": strikethrough,
        "is_sponsored": is_sponsored,
        "is_prime": True,
        "rating": 4.5,
        "reviews_count": 1234,
        "url": f"/dp/{asin}",
        "url_image": "https://m.media-amazon.com/images/I/foo.jpg",
    }


def _decodo_response(organic: list[dict]) -> dict:
    """Wrap an organic list in Decodo's nested response envelope."""
    return {
        "results": [
            {
                "content": {
                    "results": {
                        "results": {
                            "organic": organic,
                            "paid": [],
                            "amazons_choices": [],
                            "suggested": [],
                        },
                        "url": "https://www.amazon.com/s?k=test",
                        "page": 1,
                        "total_results_count": 100,
                    }
                },
                "status_code": 200,
            }
        ]
    }


# MARK: - Configuration


def test_is_configured_requires_auth():
    assert is_configured(_cfg()) is True
    assert is_configured(_cfg(DECODO_SCRAPER_API_AUTH="")) is False


# MARK: - Happy path


@pytest.mark.asyncio
@respx.mock
async def test_fetch_amazon_happy_path_maps_organic():
    respx.post(host="scraper-api.decodo.com").mock(
        return_value=httpx.Response(
            200,
            json=_decodo_response([
                _organic(asin="A1", title="AirPods A", price=199.99, strikethrough=249.99),
                _organic(asin="A2", title="AirPods B", price=129.99, strikethrough=129.99),
            ]),
        )
    )
    resp = await fetch_amazon(query="AirPods", max_listings=5, cfg=_cfg())
    assert resp.error is None
    assert len(resp.listings) == 2
    assert resp.listings[0].title == "AirPods A"
    assert resp.listings[0].price == 199.99
    assert resp.listings[0].original_price == 249.99
    assert resp.listings[0].condition == "new"
    assert resp.listings[0].seller == "Amazon"
    assert resp.listings[0].is_third_party is False
    assert resp.listings[0].extraction_method == "amazon_scraper_api"
    # Equal strikethrough → no false markdown
    assert resp.listings[1].original_price is None
    # Relative URL was rewritten to canonical /dp/{asin}
    assert resp.listings[0].url == "https://www.amazon.com/dp/A1"
    assert resp.metadata.script_version == "amazon_scraper_api/1.0"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_amazon_drops_sponsored():
    respx.post(host="scraper-api.decodo.com").mock(
        return_value=httpx.Response(
            200,
            json=_decodo_response([
                _organic(asin="SPON", title="Paid", is_sponsored=True),
                _organic(asin="ORG", title="Organic"),
            ]),
        )
    )
    resp = await fetch_amazon(query="x", cfg=_cfg())
    assert len(resp.listings) == 1
    assert resp.listings[0].title == "Organic"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_amazon_drops_items_missing_asin_or_price():
    respx.post(host="scraper-api.decodo.com").mock(
        return_value=httpx.Response(
            200,
            json=_decodo_response([
                {"asin": "", "title": "no-asin", "price": 99.0},
                {"asin": "X1", "title": "no-price", "price": None},
                _organic(asin="OK", title="kept", price=49.99),
            ]),
        )
    )
    resp = await fetch_amazon(query="x", cfg=_cfg())
    assert len(resp.listings) == 1
    assert resp.listings[0].title == "kept"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_amazon_max_listings_caps_results():
    respx.post(host="scraper-api.decodo.com").mock(
        return_value=httpx.Response(
            200,
            json=_decodo_response([_organic(asin=f"A{i}") for i in range(20)]),
        )
    )
    resp = await fetch_amazon(query="x", max_listings=3, cfg=_cfg())
    assert len(resp.listings) == 3


@pytest.mark.asyncio
@respx.mock
async def test_fetch_amazon_request_payload_shape():
    """The POST body must be the minimal Decodo Amazon-parser payload — adding
    page_from / sort_by here triggers Decodo's validation 400 (verified live)."""
    captured: dict = {}

    def _capture(request):
        import json
        captured["body"] = json.loads(request.content.decode())
        captured["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json=_decodo_response([]))

    respx.post(host="scraper-api.decodo.com").mock(side_effect=_capture)
    await fetch_amazon(query="laptop", cfg=_cfg())
    assert captured["body"] == {"target": "amazon_search", "query": "laptop", "parse": True}
    assert captured["auth"] == "Basic dGVzdDp0ZXN0"


# MARK: - Error handling


@pytest.mark.asyncio
async def test_fetch_amazon_missing_auth_returns_not_configured():
    resp = await fetch_amazon(query="x", cfg=_cfg(DECODO_SCRAPER_API_AUTH=""))
    assert resp.error is not None
    assert resp.error.code == "NOT_CONFIGURED"
    assert resp.listings == []


@pytest.mark.asyncio
@respx.mock
async def test_fetch_amazon_raw_html_response_returns_parse_error():
    """When Decodo's parser fails it returns content as a raw HTML string
    instead of the nested results object — must not crash, must surface as
    PARSE_ERROR so the caller can fall back."""
    respx.post(host="scraper-api.decodo.com").mock(
        return_value=httpx.Response(
            200,
            json={"results": [{"content": "<html><body>blocked</body></html>"}]},
        )
    )
    resp = await fetch_amazon(query="x", cfg=_cfg())
    assert resp.error is not None
    assert resp.error.code == "PARSE_ERROR"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_amazon_500_returns_http_error():
    respx.post(host="scraper-api.decodo.com").mock(
        return_value=httpx.Response(500, text="upstream timeout")
    )
    resp = await fetch_amazon(query="x", cfg=_cfg())
    assert resp.error is not None
    assert resp.error.code == "HTTP_ERROR"
    assert resp.error.details["status_code"] == 500


@pytest.mark.asyncio
@respx.mock
async def test_fetch_amazon_connect_failure_returns_request_failed():
    respx.post(host="scraper-api.decodo.com").mock(
        side_effect=httpx.ConnectError("DNS fail")
    )
    resp = await fetch_amazon(query="x", cfg=_cfg())
    assert resp.error is not None
    assert resp.error.code == "REQUEST_FAILED"


# MARK: - container_client routing


@pytest.mark.asyncio
async def test_container_client_routes_amazon_through_adapter_when_configured(monkeypatch):
    """When DECODO_SCRAPER_API_AUTH is set, `_extract_one("amazon", ...)` MUST
    go through the API adapter and NOT hit the container."""
    from modules.m2_prices.container_client import ContainerClient

    called_with: dict = {}

    async def _fake_fetch(**kwargs):
        called_with.update(kwargs)
        from modules.m2_prices.schemas import ContainerResponse
        return ContainerResponse(retailer_id="amazon", query=kwargs["query"], listings=[])

    import modules.m2_prices.adapters.amazon_scraper_api as adapter_mod
    monkeypatch.setattr(adapter_mod, "fetch_amazon", _fake_fetch)

    client = ContainerClient(config=_cfg())
    resp = await client._extract_one("amazon", "airpods", None, None, 5)
    assert resp.retailer_id == "amazon"
    assert called_with["query"] == "airpods"
    assert called_with["max_listings"] == 5


@pytest.mark.asyncio
async def test_container_client_falls_back_to_container_when_auth_missing(monkeypatch):
    """Without DECODO_SCRAPER_API_AUTH the adapter is bypassed — call goes
    through the container HTTP path."""
    from modules.m2_prices.container_client import ContainerClient

    called_container = False

    async def _fake_extract(retailer_id, query, *args, **kwargs):
        nonlocal called_container
        called_container = True
        from modules.m2_prices.schemas import ContainerResponse
        return ContainerResponse(retailer_id=retailer_id, query=query, listings=[])

    client = ContainerClient(config=_cfg(DECODO_SCRAPER_API_AUTH=""))
    monkeypatch.setattr(client, "extract", _fake_extract)
    await client._extract_one("amazon", "airpods", None, None, 5)
    assert called_container is True


# MARK: - L1 brand-strip recovery (cat-rel-1-L1)


def test_extract_brand_from_url_finds_leading_alpha_segment():
    """Decodo URL slugs like /Weber-51040001-Q1200-... carry the brand."""
    from modules.m2_prices.adapters.amazon_scraper_api import _extract_brand_from_url

    assert _extract_brand_from_url(
        "/Weber-51040001-Q1200-Liquid-Propane/dp/B010ILB4KU/ref=sr_1_1"
    ) == "Weber"
    assert _extract_brand_from_url(
        "/Breville-BES870XL-Barista-Express-Espresso/dp/B00CH9OOMC"
    ) == "Breville"


def test_extract_brand_from_url_handles_absolute_urls():
    """Works on absolute https URLs too."""
    from modules.m2_prices.adapters.amazon_scraper_api import _extract_brand_from_url

    assert _extract_brand_from_url(
        "https://www.amazon.com/Weber-51040001-Q1200/dp/B010ILB4KU"
    ) == "Weber"


def test_extract_brand_from_url_rejects_dp_direct():
    """Direct /dp/{asin} URLs (no slug) → None (denylist filters "dp")."""
    from modules.m2_prices.adapters.amazon_scraper_api import _extract_brand_from_url

    assert _extract_brand_from_url("/dp/B0FQFB8FMG") is None
    assert _extract_brand_from_url("https://www.amazon.com/dp/B0FQFB8FMG") is None


def test_extract_brand_from_url_rejects_digit_led_slug():
    """Slugs starting with digits (product codes) → None."""
    from modules.m2_prices.adapters.amazon_scraper_api import _extract_brand_from_url

    assert _extract_brand_from_url("/304-Stainless-Steel-Burner/dp/B07ABC") is None


def test_extract_brand_from_url_returns_none_for_empty():
    """Empty / None URL → None (no crash)."""
    from modules.m2_prices.adapters.amazon_scraper_api import _extract_brand_from_url

    assert _extract_brand_from_url("") is None
    assert _extract_brand_from_url(None) is None


@pytest.mark.asyncio
@respx.mock
async def test_fetch_amazon_reinjects_brand_from_url_slug_when_title_stripped():
    """Decodo strips brand from title + ships empty manufacturer; the URL
    slug carries the brand. Adapter prepends it so downstream relevance
    scoring (Rule 3 brand check) sees a Weber-prefixed title.

    Reproduces the live `weber q1200` query: title "Q1200 Liquid Propane
    Portable Gas Grill" → "Weber Q1200 Liquid Propane Portable Gas Grill".
    """
    weber_organic = {
        "asin": "B010ILB4KU",
        "title": "Q1200 Liquid Propane Portable Gas Grill, Red",
        "price": 279.0,
        "currency": "USD",
        "manufacturer": "",
        "url": "/Weber-51040001-Q1200-Liquid-Propane/dp/B010ILB4KU/ref=sr_1_1",
        "url_image": "https://m.media-amazon.com/images/I/71pqcAsufxL.jpg",
        "is_sponsored": False,
    }
    respx.post(host="scraper-api.decodo.com").mock(
        return_value=httpx.Response(200, json=_decodo_response([weber_organic])),
    )

    resp = await fetch_amazon(query="weber q1200", cfg=_cfg())

    assert len(resp.listings) == 1
    assert resp.listings[0].title.startswith("Weber Q1200")


@pytest.mark.asyncio
@respx.mock
async def test_fetch_amazon_does_not_double_prefix_when_title_already_has_brand():
    """If the title already contains the brand, no prefix is added."""
    organic_with_brand = {
        "asin": "B0ABC",
        "title": "Sony WH-1000XM5 Wireless Headphones",
        "price": 349.99,
        "currency": "USD",
        "manufacturer": "",
        "url": "/Sony-WH-1000XM5-Wireless-Headphones/dp/B0ABC",
        "url_image": "https://example.com/img.jpg",
        "is_sponsored": False,
    }
    respx.post(host="scraper-api.decodo.com").mock(
        return_value=httpx.Response(200, json=_decodo_response([organic_with_brand])),
    )

    resp = await fetch_amazon(query="sony", cfg=_cfg())

    assert len(resp.listings) == 1
    assert resp.listings[0].title == "Sony WH-1000XM5 Wireless Headphones"
    # No double prefix.
    assert not resp.listings[0].title.startswith("Sony Sony")


@pytest.mark.asyncio
@respx.mock
async def test_fetch_amazon_skips_prefix_when_manufacturer_present():
    """Decodo populated `manufacturer` → trust it, don't touch the title."""
    organic = {
        "asin": "B0XYZ",
        "title": "Some Product Title",
        "price": 99.99,
        "currency": "USD",
        "manufacturer": "Apple",
        "url": "/Anker-Charging-Cable/dp/B0XYZ",
        "url_image": "https://example.com/img.jpg",
        "is_sponsored": False,
    }
    respx.post(host="scraper-api.decodo.com").mock(
        return_value=httpx.Response(200, json=_decodo_response([organic])),
    )

    resp = await fetch_amazon(query="cable", cfg=_cfg())

    assert len(resp.listings) == 1
    # Title untouched — manufacturer was non-empty.
    assert resp.listings[0].title == "Some Product Title"
