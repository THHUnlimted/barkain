"""Tests for M2 Best Buy Products API adapter.

Mirror of test_ebay_browse_api.py structure:
- is_configured() behavior
- Happy path: maps products → ContainerListing
- salePrice < regularPrice → original_price is set (markdown)
- salePrice == regularPrice → original_price is None (no false strikethrough)
- onlineAvailability=False → is_available=False
- Missing key → NOT_CONFIGURED error (not crash)
- 403 invalid key → HTTP_ERROR with status code in details
- Malformed product (no name / no price) silently dropped
- container_client routes best_buy through the adapter when configured
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.config import Settings
from modules.m2_prices.adapters.best_buy_api import (
    fetch_best_buy,
    is_configured,
)


# MARK: - Helpers


def _cfg(**overrides) -> Settings:
    base = dict(BESTBUY_API_KEY="test-key-abc")
    base.update(overrides)
    return Settings(**base)


def _product(
    sku: int = 6565876,
    name: str = "Apple - AirPods Pro 2",
    sale_price: float = 199.99,
    regular_price: float = 249.99,
    online_availability: bool = True,
) -> dict:
    return {
        "sku": sku,
        "name": name,
        "salePrice": sale_price,
        "regularPrice": regular_price,
        "url": f"https://api.bestbuy.com/click/-/{sku}/pdp",
        "image": "https://pisces.bbystatic.com/x.jpg",
        "onlineAvailability": online_availability,
    }


# MARK: - Configuration


def test_is_configured_requires_key():
    assert is_configured(_cfg()) is True
    assert is_configured(_cfg(BESTBUY_API_KEY="")) is False


# MARK: - Happy path


@pytest.mark.asyncio
@respx.mock
async def test_fetch_best_buy_happy_path_maps_products():
    respx.get(host="api.bestbuy.com").mock(
        return_value=httpx.Response(
            200,
            json={
                "total": 190,
                "products": [
                    _product(sku=1, name="AirPods A", sale_price=199.99, regular_price=249.99),
                    _product(sku=2, name="AirPods B", sale_price=129.99, regular_price=129.99),
                ],
            },
        )
    )
    resp = await fetch_best_buy(query="AirPods", max_listings=5, cfg=_cfg())
    assert resp.error is None
    assert len(resp.listings) == 2
    assert resp.listings[0].title == "AirPods A"
    assert resp.listings[0].price == 199.99
    assert resp.listings[0].original_price == 249.99  # markdown present
    assert resp.listings[0].condition == "new"
    assert resp.listings[0].seller == "Best Buy"
    assert resp.listings[0].is_third_party is False
    assert resp.listings[0].extraction_method == "best_buy_api"
    # Same price on both fields — no false strikethrough
    assert resp.listings[1].original_price is None
    assert resp.metadata.script_version == "best_buy_api/1.0"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_best_buy_online_availability_false_maps_unavailable():
    respx.get(host="api.bestbuy.com").mock(
        return_value=httpx.Response(
            200,
            json={"products": [_product(online_availability=False)]},
        )
    )
    resp = await fetch_best_buy(query="x", cfg=_cfg())
    assert len(resp.listings) == 1
    assert resp.listings[0].is_available is False


@pytest.mark.asyncio
@respx.mock
async def test_fetch_best_buy_query_is_url_encoded_in_search_predicate():
    """Multi-word queries must be encoded *inside* the `(search=...)` parens.
    Best Buy expects `%20`-style encoding there, not `+`."""
    captured: dict[str, str] = {}

    def _capture(request):
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"products": []})

    respx.get(host="api.bestbuy.com").mock(side_effect=_capture)
    await fetch_best_buy(query="Apple AirPods Pro 2", cfg=_cfg())
    url = captured["url"]
    # The query must be encoded inside the parens — %20 form.
    assert "search=Apple%20AirPods%20Pro%202" in url
    assert "apiKey=test-key-abc" in url


# MARK: - Error handling


@pytest.mark.asyncio
async def test_fetch_best_buy_missing_key_returns_not_configured():
    resp = await fetch_best_buy(query="x", cfg=_cfg(BESTBUY_API_KEY=""))
    assert resp.error is not None
    assert resp.error.code == "NOT_CONFIGURED"
    assert resp.listings == []
    # Note: no HTTP call was made — adapter shortcircuits before hitting the network.


@pytest.mark.asyncio
@respx.mock
async def test_fetch_best_buy_403_invalid_key_returns_http_error():
    respx.get(host="api.bestbuy.com").mock(
        return_value=httpx.Response(403, text="Invalid API key")
    )
    resp = await fetch_best_buy(query="x", cfg=_cfg())
    assert resp.error is not None
    assert resp.error.code == "HTTP_ERROR"
    assert resp.error.details["status_code"] == 403


@pytest.mark.asyncio
@respx.mock
async def test_fetch_best_buy_drops_malformed_products_without_crashing():
    respx.get(host="api.bestbuy.com").mock(
        return_value=httpx.Response(
            200,
            json={
                "products": [
                    {"sku": 1},  # no name, no price → dropped
                    _product(name="Valid", sale_price=99.0),
                    {"name": "Price-less", "salePrice": None},  # dropped
                ]
            },
        )
    )
    resp = await fetch_best_buy(query="x", cfg=_cfg())
    assert resp.error is None
    assert len(resp.listings) == 1
    assert resp.listings[0].title == "Valid"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_best_buy_request_failure_returns_request_failed():
    respx.get(host="api.bestbuy.com").mock(side_effect=httpx.ConnectError("DNS fail"))
    resp = await fetch_best_buy(query="x", cfg=_cfg())
    assert resp.error is not None
    assert resp.error.code == "REQUEST_FAILED"


# MARK: - Query sanitizer


def test_sanitize_query_strips_parens_and_commas():
    from modules.m2_prices.adapters.best_buy_api import _sanitize_query

    assert (
        _sanitize_query("Apple iPhone 14 128GB (Blue, MPVR3LL/A)")
        == "Apple iPhone 14 128GB Blue MPVR3LL A"
    )


def test_sanitize_query_strips_plus_sign():
    from modules.m2_prices.adapters.best_buy_api import _sanitize_query

    assert (
        _sanitize_query("AppleCare+ for iPhone 14 (2-Year Plan)")
        == "AppleCare for iPhone 14 2-Year Plan"
    )


def test_sanitize_query_preserves_model_hyphen():
    """Hyphens in model numbers (e.g. WH-1000XM5) are preserved."""
    from modules.m2_prices.adapters.best_buy_api import _sanitize_query

    assert (
        _sanitize_query("Sony WH-1000XM5 Wireless Headphones")
        == "Sony WH-1000XM5 Wireless Headphones"
    )


def test_sanitize_query_collapses_multiple_spaces():
    from modules.m2_prices.adapters.best_buy_api import _sanitize_query

    assert _sanitize_query("  foo  &  bar  ,  baz  ") == "foo bar baz"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_best_buy_dsl_query_is_sanitized_before_encoding():
    """Hostile query sent through the adapter arrives at Best Buy without DSL chars."""
    captured_url: dict[str, str] = {}

    def _record(request):
        captured_url["url"] = str(request.url)
        return httpx.Response(200, json={"products": []})

    respx.get(host="api.bestbuy.com").mock(side_effect=_record)

    await fetch_best_buy(
        query="Apple iPhone 14 (Blue, MPVR3LL/A)", cfg=_cfg()
    )

    url = captured_url["url"]
    # DSL-hostile chars must not appear inside the search predicate.
    # The parens around `(search=...)` are the template's, not the query's —
    # confirm the first `(` is followed by `search=` and the query body
    # carries no literal `(`, `)`, `,`, `/`, `+`.
    payload_start = url.index("(search=") + len("(search=")
    payload_end = url.index(")?", payload_start)
    payload = url[payload_start:payload_end]
    for bad in ("%28", "%29", "%2C", "%2F", "%2B", "(", ")", ",", "/", "+"):
        assert bad not in payload, f"found {bad!r} in payload {payload!r}"


# MARK: - Retry on 429 / 5xx


@pytest.mark.asyncio
@respx.mock
async def test_fetch_best_buy_429_then_success(monkeypatch):
    """429 on attempt 1, 200 on attempt 2 → returns listings, sleeps once."""
    from modules.m2_prices.adapters import best_buy_api as adapter_mod

    sleep_calls: list[float] = []

    async def _fake_sleep(s: float) -> None:
        sleep_calls.append(s)

    monkeypatch.setattr(adapter_mod.asyncio, "sleep", _fake_sleep)

    route = respx.get(host="api.bestbuy.com").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0.3"}, text="rate limited"),
            httpx.Response(200, json={"products": [_product()]}),
        ]
    )

    resp = await fetch_best_buy(query="airpods", cfg=_cfg())

    assert resp.error is None
    assert len(resp.listings) == 1
    assert route.call_count == 2
    assert sleep_calls == [0.3]


@pytest.mark.asyncio
@respx.mock
async def test_fetch_best_buy_503_twice_returns_http_error(monkeypatch):
    """503 on both attempts → returns HTTP_ERROR after the budget is spent."""
    from modules.m2_prices.adapters import best_buy_api as adapter_mod

    async def _fake_sleep(s: float) -> None:
        return None

    monkeypatch.setattr(adapter_mod.asyncio, "sleep", _fake_sleep)

    route = respx.get(host="api.bestbuy.com").mock(
        return_value=httpx.Response(503, text="service down")
    )

    resp = await fetch_best_buy(query="airpods", cfg=_cfg())

    assert resp.error is not None
    assert resp.error.code == "HTTP_ERROR"
    assert resp.error.details["status_code"] == 503
    assert resp.error.details["attempts"] == 2
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_fetch_best_buy_403_no_retry(monkeypatch):
    """403 (auth failure) is NOT retried — single call, no sleep."""
    from modules.m2_prices.adapters import best_buy_api as adapter_mod

    sleep_calls: list[float] = []

    async def _fake_sleep(s: float) -> None:
        sleep_calls.append(s)

    monkeypatch.setattr(adapter_mod.asyncio, "sleep", _fake_sleep)

    route = respx.get(host="api.bestbuy.com").mock(
        return_value=httpx.Response(403, text="invalid key")
    )

    resp = await fetch_best_buy(query="airpods", cfg=_cfg())

    assert resp.error is not None
    assert resp.error.code == "HTTP_ERROR"
    assert resp.error.details["status_code"] == 403
    assert route.call_count == 1
    assert sleep_calls == []


def test_parse_retry_after_handles_seconds_form():
    from modules.m2_prices.adapters.best_buy_api import _parse_retry_after

    assert _parse_retry_after("1.5") == 1.5


def test_parse_retry_after_caps_at_max_delay():
    from modules.m2_prices.adapters.best_buy_api import (
        _RETRY_MAX_DELAY_S,
        _parse_retry_after,
    )

    assert _parse_retry_after("999") == _RETRY_MAX_DELAY_S


def test_parse_retry_after_falls_back_when_missing():
    from modules.m2_prices.adapters.best_buy_api import (
        _RETRY_DEFAULT_DELAY_S,
        _parse_retry_after,
    )

    assert _parse_retry_after(None) == _RETRY_DEFAULT_DELAY_S
    assert _parse_retry_after("Wed, 21 Oct 2026 07:28:00 GMT") == _RETRY_DEFAULT_DELAY_S


# MARK: - container_client routing


@pytest.mark.asyncio
async def test_container_client_routes_best_buy_through_adapter_when_configured(monkeypatch):
    """When BESTBUY_API_KEY is set, `_extract_one("best_buy", ...)` must NOT
    hit the container HTTP endpoint — it must go through the API adapter."""
    from modules.m2_prices.container_client import ContainerClient

    called_with: dict[str, object] = {}

    async def _fake_fetch(**kwargs):
        called_with.update(kwargs)
        from modules.m2_prices.schemas import ContainerResponse
        return ContainerResponse(
            retailer_id="best_buy",
            query=kwargs["query"],
            listings=[],
        )

    import modules.m2_prices.adapters.best_buy_api as adapter_mod
    monkeypatch.setattr(adapter_mod, "fetch_best_buy", _fake_fetch)

    cfg = _cfg()
    client = ContainerClient(config=cfg)
    resp = await client._extract_one("best_buy", "airpods", None, None, 5)
    assert resp.retailer_id == "best_buy"
    assert called_with["query"] == "airpods"
    assert called_with["max_listings"] == 5


@pytest.mark.asyncio
async def test_container_client_falls_back_to_container_when_key_missing(monkeypatch):
    """Without BESTBUY_API_KEY, the adapter is not used — the call falls
    through to the regular container HTTP path."""
    from modules.m2_prices.container_client import ContainerClient

    called_container = False

    async def _fake_extract(retailer_id, query, *args, **kwargs):
        nonlocal called_container
        called_container = True
        from modules.m2_prices.schemas import ContainerResponse
        return ContainerResponse(retailer_id=retailer_id, query=query, listings=[])

    cfg = _cfg(BESTBUY_API_KEY="")
    client = ContainerClient(config=cfg)
    monkeypatch.setattr(client, "extract", _fake_extract)
    await client._extract_one("best_buy", "airpods", None, None, 5)
    assert called_container is True
