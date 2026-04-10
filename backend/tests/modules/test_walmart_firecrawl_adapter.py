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
