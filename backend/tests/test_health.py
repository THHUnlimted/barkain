import pytest

from app.config import settings


@pytest.mark.asyncio
async def test_health_returns_200(client):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_health_returns_status_fields(client):
    data = (await client.get("/api/v1/health")).json()
    assert "status" in data
    assert "database" in data
    assert "redis" in data
    assert "timestamp" in data


@pytest.mark.asyncio
async def test_health_returns_version(client):
    data = (await client.get("/api/v1/health")).json()
    assert data["version"] == settings.APP_VERSION


@pytest.mark.asyncio
async def test_health_no_auth_required(unauthed_client):
    response = await unauthed_client.get("/api/v1/health")
    assert response.status_code == 200
