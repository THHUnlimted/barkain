"""Tests for M2 walmart_http adapter — Decodo residential proxy path.

Mocks `httpx.AsyncClient` via respx. The adapter's proxy URL is read from
settings so we construct a throwaway Settings with the required fields.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from app.config import Settings
from modules.m2_prices.adapters import _walmart_parser, walmart_http
from modules.m2_prices.adapters.walmart_http import _build_proxy_url, fetch_walmart


@pytest.fixture(autouse=True)
def _no_backoff_sleep(monkeypatch):
    """Disable the CHALLENGE retry back-off so tests don't actually sleep."""
    monkeypatch.setattr(walmart_http, "_CHALLENGE_BACKOFF_RANGE_S", (0, 0))


# MARK: - Fixtures

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"
NEXT_DATA_SAMPLE = (FIXTURE_DIR / "walmart_next_data_sample.html").read_text(
    encoding="utf-8"
)
CHALLENGE_SAMPLE = (FIXTURE_DIR / "walmart_challenge_sample.html").read_text(
    encoding="utf-8"
)


def _test_settings(**overrides) -> Settings:
    """Build a Settings instance with Decodo creds populated for tests."""
    base = dict(
        DECODO_PROXY_USER="testuser",
        DECODO_PROXY_PASS="testpass=",
        DECODO_PROXY_HOST="proxy.test:7000",
        WALMART_ADAPTER="decodo_http",
    )
    base.update(overrides)
    return Settings(**base)


# MARK: - Proxy URL builder


def test_build_proxy_url_adds_user_prefix_and_country_suffix():
    cfg = _test_settings(DECODO_PROXY_USER="bareusername")
    url = _build_proxy_url(cfg)
    assert url.startswith("http://user-bareusername-country-us:")
    assert "@proxy.test:7000" in url


def test_build_proxy_url_does_not_double_prefix():
    cfg = _test_settings(DECODO_PROXY_USER="user-alreadyprefixed-country-us")
    url = _build_proxy_url(cfg)
    # Should not become "user-user-alreadyprefixed..."
    assert url.count("user-") == 1


def test_build_proxy_url_url_encodes_password_special_chars():
    cfg = _test_settings(DECODO_PROXY_PASS="a=b@c:d")
    url = _build_proxy_url(cfg)
    # '=' → %3D, '@' → %40, ':' → %3A
    assert "a%3Db%40c%3Ad" in url


def test_build_proxy_url_raises_when_credentials_missing():
    from modules.m2_prices.adapters.walmart_http import DecodoNotConfiguredError

    cfg = _test_settings(DECODO_PROXY_USER="", DECODO_PROXY_PASS="")
    with pytest.raises(DecodoNotConfiguredError):
        _build_proxy_url(cfg)


def test_build_proxy_url_appends_port_when_host_is_bare():
    """Bare hostname must get DECODO_PROXY_PORT appended.

    Without this, httpx defaults to port 80 and silently times out at the
    full request timeout (Decodo only listens on 7000) — observed live on
    2026-04-18 when /etc/barkain-scrapers.env used the proxy_relay
    convention (separate HOST + PORT) instead of the combined form.
    """
    cfg = _test_settings(DECODO_PROXY_HOST="proxy.test", DECODO_PROXY_PORT=7000)
    url = _build_proxy_url(cfg)
    assert "@proxy.test:7000" in url


def test_build_proxy_url_keeps_combined_host_port_intact():
    cfg = _test_settings(DECODO_PROXY_HOST="proxy.test:7000", DECODO_PROXY_PORT=9999)
    url = _build_proxy_url(cfg)
    # Combined form wins; PORT is ignored.
    assert "@proxy.test:7000" in url
    assert ":9999" not in url


# MARK: - fetch_walmart happy path


@pytest.mark.asyncio
@respx.mock
async def test_fetch_walmart_success_returns_listings():
    """A 200 response with __NEXT_DATA__ yields parsed ContainerListings."""
    cfg = _test_settings()
    respx.get("https://www.walmart.com/search").mock(
        return_value=httpx.Response(
            200,
            text=NEXT_DATA_SAMPLE,
            headers={"content-type": "text/html"},
        )
    )

    result = await fetch_walmart(query="Apple AirPods Pro", cfg=cfg)

    assert result.retailer_id == "walmart"
    assert result.error is None
    assert result.query == "Apple AirPods Pro"
    # 4 real products in fixture (sponsored placement filtered out)
    assert len(result.listings) == 4
    assert result.listings[0].title == "Apple AirPods Pro 3"
    assert result.listings[0].price == 224.0
    assert result.listings[0].condition == "new"
    assert result.listings[0].is_available is True
    assert result.listings[0].extraction_method == "decodo_http_next_data"
    # Restored is Walmart's factory-refurb program — maps to "refurbished", not "used".
    restored = next(it for it in result.listings if "Restored" in it.title)
    assert restored.condition == "refurbished"
    assert restored.original_price == 249.0


@pytest.mark.asyncio
@respx.mock
async def test_fetch_walmart_max_listings_caps_results():
    """max_listings parameter limits the number of returned items."""
    cfg = _test_settings()
    respx.get("https://www.walmart.com/search").mock(
        return_value=httpx.Response(200, text=NEXT_DATA_SAMPLE)
    )

    result = await fetch_walmart(query="test", max_listings=2, cfg=cfg)
    assert len(result.listings) == 2


# MARK: - Challenge retry


@pytest.mark.asyncio
@respx.mock
async def test_fetch_walmart_challenge_all_attempts_then_surfaces_error():
    """Challenge on all attempts → returns CHALLENGE error after the full budget."""
    cfg = _test_settings()
    route = respx.get("https://www.walmart.com/search").mock(
        return_value=httpx.Response(200, text=CHALLENGE_SAMPLE)
    )

    result = await fetch_walmart(query="test", cfg=cfg)

    assert result.error is not None
    assert result.error.code == "CHALLENGE"
    assert result.metadata.bot_detected is True
    assert len(result.listings) == 0
    # Initial + 4 retries — challenge-only retry budget exhausted (5 total).
    assert route.call_count == walmart_http.CHALLENGE_MAX_ATTEMPTS == 5


@pytest.mark.asyncio
@respx.mock
async def test_fetch_walmart_challenge_backoff_runs_between_retries(monkeypatch):
    """Back-off sleeps once per retry interval — N-1 sleeps for N attempts."""
    cfg = _test_settings()
    sleep_calls: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr(walmart_http.asyncio, "sleep", _fake_sleep)
    monkeypatch.setattr(walmart_http, "_CHALLENGE_BACKOFF_RANGE_S", (0.5, 0.5))

    respx.get("https://www.walmart.com/search").mock(
        return_value=httpx.Response(200, text=CHALLENGE_SAMPLE)
    )

    result = await fetch_walmart(query="test", cfg=cfg)

    assert result.error is not None and result.error.code == "CHALLENGE"
    # 5 attempts → 4 sleeps between them, none after the final attempt.
    assert len(sleep_calls) == walmart_http.CHALLENGE_MAX_ATTEMPTS - 1
    assert all(s == 0.5 for s in sleep_calls)


@pytest.mark.asyncio
@respx.mock
async def test_fetch_walmart_retry_succeeds_on_second_attempt():
    """Challenge on attempt 1, success on attempt 2 → returns listings."""
    cfg = _test_settings()
    route = respx.get("https://www.walmart.com/search").mock(
        side_effect=[
            httpx.Response(200, text=CHALLENGE_SAMPLE),
            httpx.Response(200, text=NEXT_DATA_SAMPLE),
        ]
    )

    result = await fetch_walmart(query="test", cfg=cfg)

    assert result.error is None
    assert len(result.listings) == 4
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_fetch_walmart_retry_succeeds_on_third_attempt():
    """Challenge on attempts 1 & 2, success on attempt 3 → returns listings."""
    cfg = _test_settings()
    route = respx.get("https://www.walmart.com/search").mock(
        side_effect=[
            httpx.Response(200, text=CHALLENGE_SAMPLE),
            httpx.Response(200, text=CHALLENGE_SAMPLE),
            httpx.Response(200, text=NEXT_DATA_SAMPLE),
        ]
    )

    result = await fetch_walmart(query="test", cfg=cfg)

    assert result.error is None
    assert len(result.listings) == 4
    assert route.call_count == 3


# MARK: - Error paths (fail-fast: no retry except on CHALLENGE)


@pytest.mark.asyncio
@respx.mock
async def test_fetch_walmart_http_error_fails_fast_no_retry():
    """HTTP 500 → HTTP_ERROR surfaced after a single call; no retry."""
    cfg = _test_settings()
    route = respx.get("https://www.walmart.com/search").mock(
        return_value=httpx.Response(500, text="boom")
    )

    result = await fetch_walmart(query="test", cfg=cfg)

    assert result.error is not None
    assert result.error.code == "HTTP_ERROR"
    assert result.error.details["status_code"] == 500
    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_fetch_walmart_missing_next_data_fails_fast_no_retry():
    """200 response with no __NEXT_DATA__ tag → PARSE_ERROR after a single call."""
    cfg = _test_settings()
    route = respx.get("https://www.walmart.com/search").mock(
        return_value=httpx.Response(200, text="<html><body>no data</body></html>")
    )

    result = await fetch_walmart(query="test", cfg=cfg)

    assert result.error is not None
    assert result.error.code == "PARSE_ERROR"
    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_fetch_walmart_timeout_fails_fast_no_retry():
    """httpx.TimeoutException → TIMEOUT error after a single call."""
    cfg = _test_settings()
    route = respx.get("https://www.walmart.com/search").mock(
        side_effect=httpx.ReadTimeout("timeout")
    )

    result = await fetch_walmart(query="test", cfg=cfg)

    assert result.error is not None
    assert result.error.code == "TIMEOUT"
    assert route.call_count == 1


@pytest.mark.asyncio
async def test_fetch_walmart_without_credentials_reports_adapter_error():
    """Missing DECODO_PROXY_USER/PASS → ADAPTER_NOT_CONFIGURED."""
    cfg = _test_settings(DECODO_PROXY_USER="", DECODO_PROXY_PASS="")

    result = await fetch_walmart(query="test", cfg=cfg)

    assert result.error is not None
    assert result.error.code == "ADAPTER_NOT_CONFIGURED"
    assert "DECODO_PROXY_USER" in result.error.message


# MARK: - Proxy Scoping Regression Guards (SP-decodo-scoping, 2026-04-17)


@pytest.mark.asyncio
@respx.mock
async def test_fetch_walmart_makes_exactly_one_request_per_call():
    """The Decodo-scoped HTTP adapter is a single GET per invocation — it must
    never follow subresource URLs from the returned HTML. Any future refactor
    that accidentally adds image/script fetching would inflate per-scrape
    bandwidth by 10–100× on paid residential bytes."""
    cfg = _test_settings()
    route = respx.get("https://www.walmart.com/search").mock(
        return_value=httpx.Response(
            200, text=NEXT_DATA_SAMPLE, headers={"content-type": "text/html"}
        )
    )

    result = await fetch_walmart(query="one-shot", cfg=cfg)

    assert result.error is None
    assert route.call_count == 1, (
        f"walmart_http must make exactly one request per call, made {route.call_count}. "
        "A subresource loader has likely been accidentally introduced."
    )


# MARK: - Parser-specific edge cases


def test_parser_filters_sponsored_items():
    listings = _walmart_parser.extract_listings(NEXT_DATA_SAMPLE, max_listings=10)
    titles = [it.title for it in listings]
    assert "Sponsored Placement" not in titles


def test_parser_marks_out_of_stock_items():
    listings = _walmart_parser.extract_listings(NEXT_DATA_SAMPLE, max_listings=10)
    oos = next(it for it in listings if it.title == "Apple AirPods Max")
    assert oos.is_available is False


def test_parser_makes_canonical_urls_absolute():
    listings = _walmart_parser.extract_listings(NEXT_DATA_SAMPLE, max_listings=10)
    for it in listings:
        if it.url:
            assert it.url.startswith("https://www.walmart.com")


def test_parser_raises_on_missing_next_data():
    with pytest.raises(ValueError, match="__NEXT_DATA__"):
        _walmart_parser.extract_listings("<html><body>nope</body></html>")


def test_parser_detects_challenge_markers():
    assert _walmart_parser.detect_challenge(CHALLENGE_SAMPLE) is True
    assert _walmart_parser.detect_challenge(NEXT_DATA_SAMPLE) is False
