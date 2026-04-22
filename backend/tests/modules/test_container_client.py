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
def _setup_client(client: ContainerClient, monkeypatch):
    client.url_pattern = "http://localhost:{port}"
    client.timeout = 5
    client.retry_count = 1
    client.ports = {"walmart": 8083, "target": 8084, "best_buy": 8082}
    # Default to container path so existing tests exercise the legacy route.
    # Adapter routing is covered in test_walmart_http_adapter.py /
    # test_walmart_firecrawl_adapter.py.
    client.walmart_adapter_mode = "container"
    client._cfg = None
    # Step 3f Pre-Fix #4: the BBY / Amazon API adapters auto-prefer when
    # their keys are set. `.env` populates both for dev runs, which means
    # `extract_all` routes best_buy away from the port-8082 mock and hits
    # `api.bestbuy.com` (unmocked by respx, test fails). Force keys empty
    # so these tests exercise the container dispatch they're written for.
    from app.config import settings
    monkeypatch.setattr(settings, "BESTBUY_API_KEY", "")
    monkeypatch.setattr(settings, "DECODO_SCRAPER_API_AUTH", "")


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


# MARK: - fb_marketplace per-user location (fb-marketplace-location)


def test_container_extract_request_validates_fb_location_slug():
    """ContainerExtractRequest enforces the same [a-z0-9_] shape FB slugs use."""
    from modules.m2_prices.schemas import ContainerExtractRequest

    # Happy path
    req = ContainerExtractRequest(query="tv", fb_location_slug="brooklyn")
    assert req.fb_location_slug == "brooklyn"

    # Normalized to lowercase
    req = ContainerExtractRequest(query="tv", fb_location_slug="BROOKLYN")
    assert req.fb_location_slug == "brooklyn"

    # Empty string → None (user cleared it)
    req = ContainerExtractRequest(query="tv", fb_location_slug="")
    assert req.fb_location_slug is None

    # Bad chars rejected
    with pytest.raises(ValueError, match="may only contain"):
        ContainerExtractRequest(query="tv", fb_location_slug="not a slug")

    with pytest.raises(ValueError, match="64 chars"):
        ContainerExtractRequest(query="tv", fb_location_slug="a" * 65)


def test_container_extract_request_validates_fb_radius_miles():
    """Radius must be a plausible mileage."""
    from modules.m2_prices.schemas import ContainerExtractRequest

    ContainerExtractRequest(query="tv", fb_radius_miles=25)
    ContainerExtractRequest(query="tv", fb_radius_miles=1)
    ContainerExtractRequest(query="tv", fb_radius_miles=500)

    with pytest.raises(ValueError, match="between 1 and 500"):
        ContainerExtractRequest(query="tv", fb_radius_miles=0)
    with pytest.raises(ValueError, match="between 1 and 500"):
        ContainerExtractRequest(query="tv", fb_radius_miles=501)


@pytest.mark.asyncio
@respx.mock
async def test_extract_forwards_location_to_fb_marketplace_only(
    client: ContainerClient, container_response_data: dict
):
    """Location fields reach the fb_marketplace payload and NO other retailer.

    Every other retailer's POST body must have `fb_location_slug=None` and
    `fb_radius_miles=None` regardless of what the caller passed. The filter
    lives in `ContainerClient.extract` so every downstream path respects it
    — if we ever add a second location-aware retailer, re-gate here.
    """
    # Point fb_marketplace + target at a local port so the fake HTTP client
    # can record what each received.
    client.ports = {**client.ports, "fb_marketplace": 8091}

    fb_body: list[dict] = []
    other_body: list[dict] = []

    def _capture_fb(request):
        fb_body.append(json.loads(request.content))
        return httpx.Response(200, json=container_response_data)

    def _capture_other(request):
        other_body.append(json.loads(request.content))
        return httpx.Response(200, json=container_response_data)

    respx.post("http://localhost:8091/extract").mock(side_effect=_capture_fb)
    respx.post("http://localhost:8084/extract").mock(side_effect=_capture_other)

    await client.extract(
        "fb_marketplace",
        "sofa",
        fb_location_slug="brooklyn",
        fb_radius_miles=25,
    )
    await client.extract(
        "target",
        "sofa",
        fb_location_slug="brooklyn",
        fb_radius_miles=25,
    )

    assert fb_body[0]["fb_location_slug"] == "brooklyn"
    assert fb_body[0]["fb_radius_miles"] == 25

    # Non-fb_marketplace retailers must have the fields nulled out.
    assert other_body[0]["fb_location_slug"] is None
    assert other_body[0]["fb_radius_miles"] is None


def test_cache_key_includes_location_suffix_when_slug_set():
    """_cache_key gains a `:loc:<slug>:r<radius>` suffix for fb-specific buckets."""
    import uuid as _uuid

    from modules.m2_prices.service import PriceAggregationService, REDIS_KEY_PREFIX

    pid = _uuid.UUID("00000000-0000-0000-0000-000000000001")

    # No slug → bare key (preserves pre-existing callers / cache hits).
    assert PriceAggregationService._cache_key(pid, None) == f"{REDIS_KEY_PREFIX}{pid}"

    # Slug only — unknown radius placeholder keeps the shape consistent.
    assert (
        PriceAggregationService._cache_key(pid, None, "brooklyn", None)
        == f"{REDIS_KEY_PREFIX}{pid}:loc:brooklyn:rx"
    )

    # Slug + radius — numeric suffix.
    assert (
        PriceAggregationService._cache_key(pid, None, "brooklyn", 25)
        == f"{REDIS_KEY_PREFIX}{pid}:loc:brooklyn:r25"
    )

    # Different slug → different bucket (no cross-city cache hits).
    assert PriceAggregationService._cache_key(
        pid, None, "brooklyn", 25
    ) != PriceAggregationService._cache_key(pid, None, "austin", 25)
