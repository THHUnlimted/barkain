"""Tests for M2 container client — HTTP dispatch to scraper containers."""

import json
from pathlib import Path

import httpx
import pytest
import respx

from modules.m2_prices.container_client import ContainerClient
from modules.m2_prices.schemas import ContainerResponse


# MARK: - Fixtures


FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "container_extract_response.json"


@pytest.fixture
def container_response_data() -> dict:
    return json.loads(FIXTURE_PATH.read_text())


@pytest.fixture
def client() -> ContainerClient:
    """ContainerClient with test-friendly config."""
    return ContainerClient.__new__(ContainerClient)


@pytest.fixture(autouse=True)
def _setup_client(client: ContainerClient):
    client.url_pattern = "http://localhost:{port}"
    client.timeout = 5
    client.retry_count = 1
    client.ports = {"walmart": 8083, "target": 8084, "best_buy": 8082}
    # Default to container path so existing tests exercise the legacy route.
    # Adapter routing is covered in test_walmart_http_adapter.py /
    # test_walmart_firecrawl_adapter.py.
    client.walmart_adapter_mode = "container"
    client._cfg = None


# MARK: - URL Resolution


def test_container_url_resolution(client: ContainerClient):
    """retailer_id maps to correct URL via port pattern."""
    assert client._get_container_url("walmart") == "http://localhost:8083"
    assert client._get_container_url("target") == "http://localhost:8084"
    assert client._get_container_url("best_buy") == "http://localhost:8082"


def test_container_url_unknown_retailer_raises(client: ContainerClient):
    """Unknown retailer_id raises ValueError."""
    with pytest.raises(ValueError, match="Unknown retailer_id"):
        client._get_container_url("nonexistent_retailer")


# MARK: - Extract (single container)


@pytest.mark.asyncio
@respx.mock
async def test_extract_success_returns_listings(
    client: ContainerClient, container_response_data: dict
):
    """Successful POST /extract returns parsed ContainerResponse with listings."""
    respx.post("http://localhost:8083/extract").mock(
        return_value=httpx.Response(200, json=container_response_data)
    )

    result = await client.extract("walmart", "Samsung 65 inch TV")

    assert isinstance(result, ContainerResponse)
    assert result.retailer_id == "walmart"
    assert result.error is None
    assert len(result.listings) == 3
    assert result.listings[0].title == 'Samsung 65" Class QLED 4K Smart TV'
    assert result.listings[0].price == 697.99
    assert result.extraction_time_ms == 4523


@pytest.mark.asyncio
@respx.mock
async def test_extract_timeout_returns_error(client: ContainerClient):
    """Timeout on POST /extract returns ContainerResponse with error."""
    respx.post("http://localhost:8083/extract").mock(
        side_effect=httpx.ReadTimeout("read timed out")
    )

    result = await client.extract("walmart", "Samsung TV")

    assert isinstance(result, ContainerResponse)
    assert result.retailer_id == "walmart"
    assert result.error is not None
    assert result.error.code == "CONNECTION_FAILED"
    assert result.listings == []


@pytest.mark.asyncio
@respx.mock
async def test_extract_connection_error_returns_error(client: ContainerClient):
    """Connection error returns ContainerResponse with error."""
    respx.post("http://localhost:8083/extract").mock(
        side_effect=httpx.ConnectError("connection refused")
    )

    result = await client.extract("walmart", "Samsung TV")

    assert isinstance(result, ContainerResponse)
    assert result.error is not None
    assert result.error.code == "CONNECTION_FAILED"
    assert result.listings == []


@pytest.mark.asyncio
@respx.mock
async def test_extract_http_500_returns_error(client: ContainerClient):
    """HTTP 500 from container returns ContainerResponse with error."""
    respx.post("http://localhost:8083/extract").mock(
        return_value=httpx.Response(500, text="Internal Server Error")
    )

    result = await client.extract("walmart", "Samsung TV")

    assert isinstance(result, ContainerResponse)
    assert result.error is not None
    assert result.error.code == "HTTP_ERROR"
    assert "500" in result.error.message


@pytest.mark.asyncio
@respx.mock
async def test_extract_retries_on_timeout_then_succeeds(
    client: ContainerClient, container_response_data: dict
):
    """Retry after timeout succeeds on second attempt."""
    route = respx.post("http://localhost:8083/extract")
    route.side_effect = [
        httpx.ReadTimeout("read timed out"),
        httpx.Response(200, json=container_response_data),
    ]

    result = await client.extract("walmart", "Samsung 65 inch TV")

    assert result.error is None
    assert len(result.listings) == 3
    assert route.call_count == 2


# MARK: - Extract All (parallel dispatch)


@pytest.mark.asyncio
@respx.mock
async def test_extract_all_all_succeed(
    client: ContainerClient, container_response_data: dict
):
    """All containers succeed — returns dict of all results."""
    for port in [8082, 8083, 8084]:
        data = {**container_response_data, "retailer_id": f"r{port}"}
        respx.post(f"http://localhost:{port}/extract").mock(
            return_value=httpx.Response(200, json=data)
        )

    results = await client.extract_all("Samsung TV")

    assert len(results) == 3
    for rid in ["walmart", "target", "best_buy"]:
        assert rid in results
        assert results[rid].error is None


@pytest.mark.asyncio
@respx.mock
async def test_extract_all_partial_failure(
    client: ContainerClient, container_response_data: dict
):
    """One container fails, others succeed — returns mixed results."""
    respx.post("http://localhost:8082/extract").mock(
        return_value=httpx.Response(200, json=container_response_data)
    )
    respx.post("http://localhost:8083/extract").mock(
        side_effect=httpx.ConnectError("connection refused")
    )
    respx.post("http://localhost:8084/extract").mock(
        return_value=httpx.Response(200, json=container_response_data)
    )

    results = await client.extract_all("Samsung TV")

    assert len(results) == 3
    assert results["best_buy"].error is None
    assert results["target"].error is None
    assert results["walmart"].error is not None


@pytest.mark.asyncio
@respx.mock
async def test_extract_all_all_fail(client: ContainerClient):
    """All containers fail — returns dict of error responses."""
    for port in [8082, 8083, 8084]:
        respx.post(f"http://localhost:{port}/extract").mock(
            side_effect=httpx.ConnectError("connection refused")
        )

    results = await client.extract_all("Samsung TV")

    assert len(results) == 3
    for rid in ["walmart", "target", "best_buy"]:
        assert results[rid].error is not None
        assert results[rid].listings == []


@pytest.mark.asyncio
@respx.mock
async def test_extract_all_with_specific_retailer_ids(
    client: ContainerClient, container_response_data: dict
):
    """Only specified retailer_ids are queried."""
    respx.post("http://localhost:8083/extract").mock(
        return_value=httpx.Response(200, json=container_response_data)
    )

    results = await client.extract_all("Samsung TV", retailer_ids=["walmart"])

    assert len(results) == 1
    assert "walmart" in results
    assert "target" not in results


# MARK: - Health Check


@pytest.mark.asyncio
@respx.mock
async def test_health_check_healthy(client: ContainerClient):
    """Healthy container returns proper health response."""
    respx.get("http://localhost:8083/health").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "healthy",
                "retailer_id": "walmart",
                "script_version": "0.1.0",
                "chromium_ready": True,
            },
        )
    )

    result = await client.health_check("walmart")

    assert result.status == "healthy"
    assert result.retailer_id == "walmart"
    assert result.chromium_ready is True


@pytest.mark.asyncio
@respx.mock
async def test_health_check_timeout_returns_unhealthy(client: ContainerClient):
    """Timeout on health check returns unhealthy response."""
    respx.get("http://localhost:8083/health").mock(
        side_effect=httpx.ReadTimeout("read timed out")
    )

    result = await client.health_check("walmart")

    assert result.status == "unhealthy"
    assert result.retailer_id == "walmart"
    assert result.chromium_ready is False


# MARK: - Response Normalization


@pytest.mark.asyncio
async def test_response_normalization(container_response_data: dict):
    """Raw JSON dict correctly parses into ContainerResponse with typed listings."""
    response = ContainerResponse(**container_response_data)

    assert response.retailer_id == "walmart"
    assert len(response.listings) == 3
    assert response.listings[0].price == 697.99
    assert response.listings[0].original_price == 999.99
    assert response.listings[2].seller == "Samsung Official"
    assert response.metadata.bot_detected is False
    assert response.error is None
