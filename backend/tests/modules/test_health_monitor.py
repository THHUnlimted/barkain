"""Tests for health monitoring service."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core_models import Retailer
from modules.m2_prices.health_monitor import HealthMonitorService
from modules.m2_prices.schemas import ContainerHealthResponse


# MARK: - Helpers


async def _seed_retailer(db_session, retailer_id: str = "amazon") -> Retailer:
    """Seed a retailer row so FK constraints pass."""
    retailer = Retailer(
        id=retailer_id,
        display_name=retailer_id.replace("_", " ").title(),
        base_url=f"https://www.{retailer_id}.com",
        extraction_method="agent_browser",
    )
    db_session.add(retailer)
    await db_session.flush()
    return retailer


# MARK: - check_one


@pytest.mark.asyncio
async def test_check_one_healthy(db_session):
    """Given a healthy container, update health record to healthy."""
    await _seed_retailer(db_session, "amazon")

    mock_client = MagicMock()
    mock_client.health_check = AsyncMock(
        return_value=ContainerHealthResponse(
            status="healthy",
            retailer_id="amazon",
            script_version="0.1.0",
            chromium_ready=True,
        )
    )

    service = HealthMonitorService(db=db_session, container_client=mock_client)
    status = await service.check_one("amazon")
    assert status == "healthy"


@pytest.mark.asyncio
async def test_check_one_unhealthy(db_session):
    """Given an unhealthy container, update health record accordingly."""
    await _seed_retailer(db_session, "amazon")

    mock_client = MagicMock()
    mock_client.health_check = AsyncMock(
        return_value=ContainerHealthResponse(
            status="unhealthy",
            retailer_id="amazon",
            script_version="unknown",
            chromium_ready=False,
        )
    )

    service = HealthMonitorService(db=db_session, container_client=mock_client)
    status = await service.check_one("amazon")
    assert status == "unhealthy"


@pytest.mark.asyncio
async def test_check_all_returns_status_map(db_session):
    """Given multiple containers, check_all returns status for each."""
    mock_client = MagicMock()
    mock_client.health_check = AsyncMock(
        return_value=ContainerHealthResponse(
            status="healthy",
            retailer_id="test",
            script_version="0.1.0",
            chromium_ready=True,
        )
    )

    service = HealthMonitorService(db=db_session, container_client=mock_client)
    result = await service.check_all()

    # Should have an entry for each container port
    assert len(result) > 0
    assert all(status in ("healthy", "unhealthy", "error") for status in result.values())


@pytest.mark.asyncio
async def test_consecutive_failures_tracked(db_session):
    """Given repeated failures, consecutive_failures counter increments."""
    await _seed_retailer(db_session, "walmart")

    mock_client = MagicMock()
    mock_client.health_check = AsyncMock(
        return_value=ContainerHealthResponse(
            status="unhealthy",
            retailer_id="walmart",
            script_version="0.1.0",
            chromium_ready=False,
        )
    )

    service = HealthMonitorService(db=db_session, container_client=mock_client)

    # Check 3 times — should increment consecutive_failures
    for _ in range(3):
        await service.check_one("walmart")

    health = await service.get_all_health()
    walmart_health = [h for h in health if h["retailer_id"] == "walmart"]
    assert walmart_health
    assert walmart_health[0]["consecutive_failures"] >= 3


# MARK: - GET /api/v1/health/retailers endpoint


@pytest.mark.asyncio
async def test_get_retailer_health_endpoint(client):
    """GET /api/v1/health/retailers returns a list."""
    resp = await client.get("/api/v1/health/retailers")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
