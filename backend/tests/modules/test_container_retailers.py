"""Tests for batch 1 retailer container response parsing and parallel dispatch.

Validates that ContainerClient correctly handles responses from Amazon, Walmart,
Target, Sam's Club, and Facebook Marketplace containers.
"""

import json
from pathlib import Path

import httpx
import pytest
import respx

from modules.m2_prices.container_client import ContainerClient
from modules.m2_prices.schemas import ContainerResponse


# MARK: - Fixtures


FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def amazon_response_data() -> dict:
    return json.loads((FIXTURES_DIR / "amazon_extract_response.json").read_text())


@pytest.fixture
def walmart_response_data() -> dict:
    return json.loads((FIXTURES_DIR / "walmart_extract_response.json").read_text())


@pytest.fixture
def target_response_data() -> dict:
    return json.loads((FIXTURES_DIR / "target_extract_response.json").read_text())


@pytest.fixture
def sams_club_response_data() -> dict:
    return json.loads((FIXTURES_DIR / "sams_club_extract_response.json").read_text())


@pytest.fixture
def fb_marketplace_response_data() -> dict:
    return json.loads((FIXTURES_DIR / "fb_marketplace_extract_response.json").read_text())


@pytest.fixture
def client() -> ContainerClient:
    """ContainerClient with batch 1 retailer ports configured."""
    c = ContainerClient.__new__(ContainerClient)
    return c


@pytest.fixture(autouse=True)
def _setup_client(client: ContainerClient):
    client.url_pattern = "http://localhost:{port}"
    client.timeout = 5
    client.retry_count = 1
    client.ports = {
        "amazon": 8081,
        "walmart": 8083,
        "target": 8084,
        "sams_club": 8089,
        "fb_marketplace": 8091,
    }


# MARK: - Response Parsing


def test_parse_amazon_response(amazon_response_data: dict):
    """Amazon response parses correctly — retailer_id, listings, URL format."""
    response = ContainerResponse(**amazon_response_data)

    assert response.retailer_id == "amazon"
    assert len(response.listings) == 3
    assert response.listings[0].title == 'Samsung 65" Class QLED 4K Smart TV QN65Q80CAFXZA'
    assert response.listings[0].price == 897.99
    assert response.listings[0].original_price == 1197.99
    assert "amazon.com" in response.listings[0].url
    assert response.error is None


def test_parse_walmart_response(walmart_response_data: dict):
    """Walmart response parses correctly — multi-span price handled."""
    response = ContainerResponse(**walmart_response_data)

    assert response.retailer_id == "walmart"
    assert len(response.listings) == 3
    assert response.listings[1].price == 447.99
    assert response.listings[1].original_price == 529.99
    assert "walmart.com" in response.listings[0].url
    assert response.error is None


def test_parse_target_response_sale_price(target_response_data: dict):
    """Target response distinguishes sale price from regular price."""
    response = ContainerResponse(**target_response_data)

    assert response.retailer_id == "target"
    assert len(response.listings) == 3

    # First listing has a sale price (original_price > price)
    sale_item = response.listings[0]
    assert sale_item.price == 279.99
    assert sale_item.original_price == 399.99
    assert sale_item.original_price > sale_item.price

    # Second listing has no sale (original_price is None)
    regular_item = response.listings[1]
    assert regular_item.original_price is None


def test_parse_sams_club_response(sams_club_response_data: dict):
    """Sam's Club response parses correctly — fewer listings typical for club store."""
    response = ContainerResponse(**sams_club_response_data)

    assert response.retailer_id == "sams_club"
    assert len(response.listings) == 2
    assert response.listings[0].price == 679.00
    assert "samsclub.com" in response.listings[0].url
    assert response.error is None


def test_parse_fb_marketplace_all_used(fb_marketplace_response_data: dict):
    """Facebook Marketplace — ALL listings have condition 'used'."""
    response = ContainerResponse(**fb_marketplace_response_data)

    assert response.retailer_id == "fb_marketplace"
    assert len(response.listings) == 3
    for listing in response.listings:
        assert listing.condition == "used"


# MARK: - Parallel Dispatch


@pytest.mark.asyncio
@respx.mock
async def test_extract_all_five_retailers(
    client: ContainerClient,
    amazon_response_data: dict,
    walmart_response_data: dict,
    target_response_data: dict,
    sams_club_response_data: dict,
    fb_marketplace_response_data: dict,
):
    """All 5 batch 1 containers succeed — returns dict with all results."""
    respx.post("http://localhost:8081/extract").mock(
        return_value=httpx.Response(200, json=amazon_response_data)
    )
    respx.post("http://localhost:8083/extract").mock(
        return_value=httpx.Response(200, json=walmart_response_data)
    )
    respx.post("http://localhost:8084/extract").mock(
        return_value=httpx.Response(200, json=target_response_data)
    )
    respx.post("http://localhost:8089/extract").mock(
        return_value=httpx.Response(200, json=sams_club_response_data)
    )
    respx.post("http://localhost:8091/extract").mock(
        return_value=httpx.Response(200, json=fb_marketplace_response_data)
    )

    results = await client.extract_all("Samsung TV")

    assert len(results) == 5
    for rid in ["amazon", "walmart", "target", "sams_club", "fb_marketplace"]:
        assert rid in results
        assert results[rid].error is None


@pytest.mark.asyncio
@respx.mock
async def test_extract_all_mixed_success_failure(
    client: ContainerClient,
    amazon_response_data: dict,
    walmart_response_data: dict,
    target_response_data: dict,
):
    """3 retailers succeed, 2 fail — partial results returned."""
    respx.post("http://localhost:8081/extract").mock(
        return_value=httpx.Response(200, json=amazon_response_data)
    )
    respx.post("http://localhost:8083/extract").mock(
        return_value=httpx.Response(200, json=walmart_response_data)
    )
    respx.post("http://localhost:8084/extract").mock(
        return_value=httpx.Response(200, json=target_response_data)
    )
    respx.post("http://localhost:8089/extract").mock(
        side_effect=httpx.ConnectError("connection refused")
    )
    respx.post("http://localhost:8091/extract").mock(
        side_effect=httpx.ConnectError("connection refused")
    )

    results = await client.extract_all("Samsung TV")

    assert len(results) == 5
    assert results["amazon"].error is None
    assert results["walmart"].error is None
    assert results["target"].error is None
    assert results["sams_club"].error is not None
    assert results["fb_marketplace"].error is not None


@pytest.mark.asyncio
@respx.mock
async def test_extract_all_returns_correct_retailer_ids(
    client: ContainerClient,
    amazon_response_data: dict,
    target_response_data: dict,
):
    """Keys in returned dict match requested retailer IDs."""
    respx.post("http://localhost:8081/extract").mock(
        return_value=httpx.Response(200, json=amazon_response_data)
    )
    respx.post("http://localhost:8084/extract").mock(
        return_value=httpx.Response(200, json=target_response_data)
    )

    results = await client.extract_all(
        "Sony headphones", retailer_ids=["amazon", "target"]
    )

    assert set(results.keys()) == {"amazon", "target"}


# MARK: - Metadata and Field Validation


def test_amazon_response_valid_metadata(amazon_response_data: dict):
    """Amazon response has valid metadata fields."""
    response = ContainerResponse(**amazon_response_data)

    assert "amazon.com" in response.metadata.url
    assert response.metadata.extracted_at != ""
    assert response.metadata.bot_detected is False
    assert response.metadata.script_version == "0.1.0"


def test_fb_marketplace_has_sellers(fb_marketplace_response_data: dict):
    """Facebook Marketplace listings include seller information."""
    response = ContainerResponse(**fb_marketplace_response_data)

    sellers = [listing.seller for listing in response.listings if listing.seller is not None]
    assert len(sellers) >= 1
    assert "John D." in sellers
