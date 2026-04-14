from datetime import UTC, datetime

import redis.asyncio as aioredis
import sqlalchemy
from fastapi import Depends, FastAPI

from app.config import settings
from app.database import async_engine
from app.dependencies import get_redis
from app.middleware import setup_middleware
from modules.m1_product.router import router as m1_product_router
from modules.m2_prices.health_router import router as health_router
from modules.m2_prices.router import router as m2_prices_router
from modules.m5_identity.router import router as m5_identity_router

app = FastAPI(
    title="Barkain API",
    version=settings.APP_VERSION,
    docs_url="/api/docs" if settings.ENVIRONMENT == "development" else None,
    redoc_url="/api/redoc" if settings.ENVIRONMENT == "development" else None,
)

setup_middleware(app)
app.include_router(m1_product_router)
app.include_router(m2_prices_router)
app.include_router(health_router)
app.include_router(m5_identity_router)


@app.get("/api/v1/health")
async def health_check(redis_client: aioredis.Redis = Depends(get_redis)):
    """Health check — no auth required."""
    result = {
        "status": "healthy",
        "version": settings.APP_VERSION,
        "timestamp": datetime.now(UTC).isoformat(),
        "database": "unhealthy",
        "redis": "unhealthy",
    }

    # Check database
    try:
        async with async_engine.connect() as conn:
            await conn.execute(sqlalchemy.text("SELECT 1"))
        result["database"] = "healthy"
    except Exception:
        result["status"] = "degraded"

    # Check Redis
    try:
        await redis_client.ping()
        result["redis"] = "healthy"
    except Exception:
        result["status"] = "degraded"

    return result
