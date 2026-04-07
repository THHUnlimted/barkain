import pytest

from app.config import settings


@pytest.mark.asyncio
async def test_rate_limit_allows_under_threshold(client):
    # Default general limit is 60, just verify a few requests succeed
    for _ in range(3):
        response = await client.get("/api/v1/test-rate-limit")
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_rate_limit_blocks_after_threshold(client):
    # Temporarily lower the limit
    original = settings.RATE_LIMIT_GENERAL
    settings.RATE_LIMIT_GENERAL = 3
    try:
        for _ in range(3):
            response = await client.get("/api/v1/test-rate-limit")
            assert response.status_code == 200

        # 4th request should be blocked
        response = await client.get("/api/v1/test-rate-limit")
        assert response.status_code == 429
        data = response.json()
        assert data["detail"]["error"]["code"] == "RATE_LIMITED"
    finally:
        settings.RATE_LIMIT_GENERAL = original


@pytest.mark.asyncio
async def test_rate_limit_returns_retry_after_header(client):
    original = settings.RATE_LIMIT_GENERAL
    settings.RATE_LIMIT_GENERAL = 1
    try:
        await client.get("/api/v1/test-rate-limit")
        response = await client.get("/api/v1/test-rate-limit")
        assert response.status_code == 429
        assert "retry-after" in response.headers
    finally:
        settings.RATE_LIMIT_GENERAL = original
