"""Health monitoring router — GET /api/v1/health/retailers."""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db, get_rate_limiter
from modules.m2_prices.health_monitor import HealthMonitorService

logger = logging.getLogger("barkain.health")

router = APIRouter(prefix="/api/v1/health", tags=["health"])


@router.get("/retailers")
async def get_retailer_health(
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Get health status of all retailer containers. No auth required."""
    service = HealthMonitorService(db=db)
    return await service.get_all_health()


@router.post("/retailers/check")
async def trigger_health_check(
    user: dict = Depends(get_current_user),
    _rate: None = Depends(get_rate_limiter("general")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Manually trigger health check on all containers. Requires auth."""
    service = HealthMonitorService(db=db)
    status_map = await service.check_all()
    return {"results": status_map}
