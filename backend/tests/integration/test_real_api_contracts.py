"""Real-API contract tests — validate live service responses match expected schemas.

These tests hit live APIs and cost real money/quota. They are NOT for CI —
they're for the developer to run manually before a live demo session.

Run with:
    BARKAIN_RUN_INTEGRATION_TESTS=1 pytest -m integration --tb=short

Each test has its own skip condition (missing API key, container not running).
"""

import os
import socket

import httpx
import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("BARKAIN_RUN_INTEGRATION_TESTS"),
        reason="Set BARKAIN_RUN_INTEGRATION_TESTS=1 to run",
    ),
]

FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
UPCITEMDB_API_KEY = os.environ.get("UPCITEMDB_API_KEY", "")

TEST_QUERY = "Sony WH-1000XM5"
TEST_UPC = "027242923782"  # Sony WH-1000XM5


def _port_open(port: int) -> bool:
    """Check if a TCP port is accepting connections on localhost."""
    try:
        with socket.create_connection(("localhost", port), timeout=2):
            return True
    except (ConnectionRefusedError, TimeoutError, OSError):
        return False


# MARK: - Firecrawl


@pytest.mark.asyncio
@pytest.mark.skipif(not FIRECRAWL_API_KEY, reason="FIRECRAWL_API_KEY not set")
async def test_firecrawl_v2_request_shape():
    """POST to Firecrawl v2 /scrape returns 200 with data key."""
    from urllib.parse import quote_plus

    url = f"https://www.walmart.com/search?q={quote_plus(TEST_QUERY)}"
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            "https://api.firecrawl.dev/v1/scrape",
            json={"url": url, "formats": ["rawHtml"], "location": {"country": "US"}},
            headers={
                "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
                "Content-Type": "application/json",
            },
        )

    assert resp.status_code == 200, f"Firecrawl returned {resp.status_code}: {resp.text[:500]}"
    data = resp.json()
    assert data.get("success") is True
    assert "data" in data
    assert "rawHtml" in data["data"]


@pytest.mark.asyncio
@pytest.mark.skipif(not FIRECRAWL_API_KEY, reason="FIRECRAWL_API_KEY not set")
async def test_firecrawl_listing_schema():
    """Parse Firecrawl response through _walmart_parser; listings have title, price > 0, url."""
    from urllib.parse import quote_plus

    from modules.m2_prices.adapters._walmart_parser import extract_listings

    url = f"https://www.walmart.com/search?q={quote_plus(TEST_QUERY)}"
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            "https://api.firecrawl.dev/v1/scrape",
            json={"url": url, "formats": ["rawHtml"], "location": {"country": "US"}},
            headers={
                "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
                "Content-Type": "application/json",
            },
        )

    html = resp.json()["data"]["rawHtml"]
    listings = extract_listings(html)

    assert len(listings) > 0, "No listings parsed from Firecrawl response"
    for li in listings:
        assert li.title, f"Empty title in listing: {li}"
        assert li.price > 0, f"Zero/negative price in listing: {li}"
        assert li.url, f"Empty URL in listing: {li}"


# MARK: - Amazon Container


@pytest.mark.asyncio
@pytest.mark.skipif(not _port_open(8081), reason="Amazon container not running on port 8081")
async def test_amazon_container_extract():
    """POST /extract to Amazon container returns listings with full titles."""
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            "http://localhost:8081/extract",
            json={"query": TEST_QUERY, "max_listings": 5},
        )

    assert resp.status_code == 200
    data = resp.json()
    listings = data.get("listings", [])
    assert len(listings) > 0, "Amazon container returned 0 listings"

    for li in listings:
        assert li["price"] > 0, f"Zero price: {li}"
        # SP-9: title should NOT be just a brand name
        assert len(li["title"].split()) >= 2, f"Title looks like brand-only: {li['title']}"


# MARK: - Best Buy Container


@pytest.mark.asyncio
@pytest.mark.skipif(not _port_open(8082), reason="Best Buy container not running on port 8082")
async def test_best_buy_container_extract():
    """POST /extract to Best Buy container returns listings with title, price, url."""
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            "http://localhost:8082/extract",
            json={"query": TEST_QUERY, "max_listings": 5},
        )

    assert resp.status_code == 200
    data = resp.json()
    listings = data.get("listings", [])
    assert len(listings) > 0, "Best Buy container returned 0 listings"

    for li in listings:
        assert li["title"], f"Empty title: {li}"
        assert li["price"] > 0, f"Zero price: {li}"
        assert li["url"], f"Empty URL: {li}"


# MARK: - UPCitemdb


@pytest.mark.asyncio
@pytest.mark.skipif(not UPCITEMDB_API_KEY, reason="UPCITEMDB_API_KEY not set")
async def test_upcitemdb_lookup():
    """Known UPC returns product with brand field via UPCitemdb API."""
    from modules.m1_product.upcitemdb import lookup_upc

    result = await lookup_upc(TEST_UPC)
    assert result is not None, f"UPCitemdb returned None for {TEST_UPC}"
    assert result.get("brand"), f"No brand in UPCitemdb response: {result}"
    assert result.get("name"), f"No name in UPCitemdb response: {result}"


# MARK: - Gemini


@pytest.mark.asyncio
@pytest.mark.skipif(not GEMINI_API_KEY, reason="GEMINI_API_KEY not set")
async def test_gemini_upc_resolve():
    """Known UPC resolves to product name containing expected brand via Gemini."""
    from ai.abstraction import gemini_generate_json
    from ai.prompts.upc_lookup import UPC_LOOKUP_SYSTEM_INSTRUCTION, build_upc_lookup_prompt

    prompt = build_upc_lookup_prompt(TEST_UPC)
    raw = await gemini_generate_json(prompt, system_instruction=UPC_LOOKUP_SYSTEM_INSTRUCTION)

    device_name = raw.get("device_name")
    assert device_name is not None, f"Gemini returned null for {TEST_UPC}: {raw}"
    assert "sony" in device_name.lower(), f"Expected 'Sony' in Gemini result: {device_name}"
