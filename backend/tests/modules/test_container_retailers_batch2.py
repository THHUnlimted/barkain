"""Tests for batch 2 retailer container response parsing and parallel dispatch.

Validates that ContainerClient correctly handles responses from Best Buy, Home Depot,
Lowe's, eBay (new), eBay (used/refurb), and BackMarket containers.
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
def best_buy_response_data() -> dict:
    return json.loads((FIXTURES_DIR / "best_buy_extract_response.json").read_text())


@pytest.fixture
def home_depot_response_data() -> dict:
    return json.loads((FIXTURES_DIR / "home_depot_extract_response.json").read_text())


@pytest.fixture
def lowes_response_data() -> dict:
    return json.loads((FIXTURES_DIR / "lowes_extract_response.json").read_text())


@pytest.fixture
def ebay_new_response_data() -> dict:
    return json.loads((FIXTURES_DIR / "ebay_new_extract_response.json").read_text())


@pytest.fixture
def ebay_used_response_data() -> dict:
    return json.loads((FIXTURES_DIR / "ebay_used_extract_response.json").read_text())


@pytest.fixture
def backmarket_response_data() -> dict:
    return json.loads((FIXTURES_DIR / "backmarket_extract_response.json").read_text())


@pytest.fixture
def client() -> ContainerClient:
    """ContainerClient with batch 2 retailer ports configured."""
    return ContainerClient.__new__(ContainerClient)


@pytest.fixture(autouse=True)
def _setup_client(client: ContainerClient):
    client.url_pattern = "http://localhost:{port}"
    client.timeout = 5
    client.retry_count = 1
    client.ports = {
        "best_buy": 8082,
        "home_depot": 8085,
        "lowes": 8086,
        "ebay_new": 8087,
        "ebay_used": 8088,
        "backmarket": 8090,
    }


# MARK: - Response Parsing


def test_parse_best_buy_response(best_buy_response_data: dict):
    """Best Buy response parses correctly with sale prices."""
    response = ContainerResponse(**best_buy_response_data)

    assert response.retailer_id == "best_buy"
    assert len(response.listings) == 3
    assert response.listings[0].price == 897.99
    assert response.listings[0].original_price == 1199.99
    assert "bestbuy.com" in response.listings[0].url
    assert response.error is None


def test_parse_home_depot_response(home_depot_response_data: dict):
    """Home Depot response parses correctly."""
    response = ContainerResponse(**home_depot_response_data)

    assert response.retailer_id == "home_depot"
    assert len(response.listings) == 2
    assert response.listings[0].price == 99.00
    assert "homedepot.com" in response.listings[0].url
    assert response.error is None


def test_parse_lowes_response(lowes_response_data: dict):
    """Lowe's response parses correctly."""
    response = ContainerResponse(**lowes_response_data)

    assert response.retailer_id == "lowes"
    assert len(response.listings) == 2
    assert response.listings[1].original_price == 229.00
    assert "lowes.com" in response.listings[0].url
    assert response.error is None


def test_parse_ebay_new_all_new_condition(ebay_new_response_data: dict):
    """eBay (new) — ALL listings have condition 'new'."""
    response = ContainerResponse(**ebay_new_response_data)

    assert response.retailer_id == "ebay_new"
    assert len(response.listings) == 3
    for listing in response.listings:
        assert listing.condition == "new"


def test_parse_ebay_used_mixed_conditions(ebay_used_response_data: dict):
    """eBay (used) — listings have 'used' or 'refurbished' conditions."""
    response = ContainerResponse(**ebay_used_response_data)

    assert response.retailer_id == "ebay_used"
    assert len(response.listings) == 3
    conditions = {listing.condition for listing in response.listings}
    assert "used" in conditions
    assert "refurbished" in conditions


def test_parse_backmarket_all_refurbished(backmarket_response_data: dict):
    """BackMarket — ALL listings have condition 'refurbished'."""
    response = ContainerResponse(**backmarket_response_data)

    assert response.retailer_id == "backmarket"
    assert len(response.listings) == 2
    for listing in response.listings:
        assert listing.condition == "refurbished"
    # BackMarket includes seller info
    sellers = [listing.seller for listing in response.listings if listing.seller]
    assert len(sellers) >= 1


# MARK: - Parallel Dispatch


@pytest.mark.asyncio
@respx.mock
async def test_extract_all_six_batch2_retailers(
    client: ContainerClient,
    best_buy_response_data: dict,
    home_depot_response_data: dict,
    lowes_response_data: dict,
    ebay_new_response_data: dict,
    ebay_used_response_data: dict,
    backmarket_response_data: dict,
):
    """All 6 batch 2 containers succeed — returns dict with all results."""
    respx.post("http://localhost:8082/extract").mock(
        return_value=httpx.Response(200, json=best_buy_response_data)
    )
    respx.post("http://localhost:8085/extract").mock(
        return_value=httpx.Response(200, json=home_depot_response_data)
    )
    respx.post("http://localhost:8086/extract").mock(
        return_value=httpx.Response(200, json=lowes_response_data)
    )
    respx.post("http://localhost:8087/extract").mock(
        return_value=httpx.Response(200, json=ebay_new_response_data)
    )
    respx.post("http://localhost:8088/extract").mock(
        return_value=httpx.Response(200, json=ebay_used_response_data)
    )
    respx.post("http://localhost:8090/extract").mock(
        return_value=httpx.Response(200, json=backmarket_response_data)
    )

    results = await client.extract_all("test query")

    assert len(results) == 6
    for rid in ["best_buy", "home_depot", "lowes", "ebay_new", "ebay_used", "backmarket"]:
        assert rid in results
        assert results[rid].error is None


@pytest.mark.asyncio
@respx.mock
async def test_extract_all_batch2_partial_failure(
    client: ContainerClient,
    best_buy_response_data: dict,
    ebay_new_response_data: dict,
):
    """4 retailers fail, 2 succeed — partial results returned."""
    respx.post("http://localhost:8082/extract").mock(
        return_value=httpx.Response(200, json=best_buy_response_data)
    )
    respx.post("http://localhost:8085/extract").mock(
        side_effect=httpx.ConnectError("connection refused")
    )
    respx.post("http://localhost:8086/extract").mock(
        side_effect=httpx.ConnectError("connection refused")
    )
    respx.post("http://localhost:8087/extract").mock(
        return_value=httpx.Response(200, json=ebay_new_response_data)
    )
    respx.post("http://localhost:8088/extract").mock(
        side_effect=httpx.ConnectError("connection refused")
    )
    respx.post("http://localhost:8090/extract").mock(
        side_effect=httpx.ConnectError("connection refused")
    )

    results = await client.extract_all("test query")

    assert len(results) == 6
    assert results["best_buy"].error is None
    assert results["ebay_new"].error is None
    assert results["home_depot"].error is not None
    assert results["lowes"].error is not None
    assert results["ebay_used"].error is not None
    assert results["backmarket"].error is not None


def test_ebay_new_has_sellers(ebay_new_response_data: dict):
    """eBay (new) listings include seller information."""
    response = ContainerResponse(**ebay_new_response_data)

    sellers = [listing.seller for listing in response.listings if listing.seller]
    assert len(sellers) >= 2
    assert "techdeals_pro" in sellers
