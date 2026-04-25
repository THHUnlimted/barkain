from datetime import UTC, datetime

import redis.asyncio as aioredis
import sqlalchemy
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import async_engine
from app.dependencies import get_redis
from app.ebay_webhook import router as ebay_webhook_router
from app.errors import make_error_detail
from app.middleware import setup_middleware
from modules.m1_product.router import router as m1_product_router
from modules.m2_prices.fb_location_router import router as m2_fb_location_router
from modules.m2_prices.health_router import router as health_router
from modules.m2_prices.router import router as m2_prices_router
from modules.m5_identity.card_router import router as m5_card_router
from modules.m5_identity.router import router as m5_identity_router
from modules.m6_recommend.router import router as m6_recommend_router
from modules.m11_billing.router import router as m11_billing_router
from modules.m12_affiliate.router import router as m12_affiliate_router
from modules.m13_portal.router import router as m13_portal_router

app = FastAPI(
    title="Barkain API",
    version=settings.APP_VERSION,
    docs_url="/api/docs" if settings.ENVIRONMENT == "development" else None,
    redoc_url="/api/redoc" if settings.ENVIRONMENT == "development" else None,
)

setup_middleware(app)


# Wrap FastAPI's default Pydantic 422 (RequestValidationError) into the
# canonical `{"detail": {"error": {"code", "message", "details"}}}` envelope
# so iOS APIClient.decodeErrorDetail surfaces a friendly message instead of
# falling through to "Validation failed". Picks the first error's `msg` for
# a single-line user-facing message; keeps the full structured errors under
# `details.errors` for telemetry.
@app.exception_handler(RequestValidationError)
async def _validation_exception_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    errors = exc.errors()
    first_msg = ""
    if errors:
        msg = errors[0].get("msg") or ""
        # Pydantic v2 prefixes with "Value error, " — strip for cleaner copy.
        first_msg = msg.removeprefix("Value error, ").strip()
    message = first_msg or "That input doesn't look right — give it another try."
    return JSONResponse(
        status_code=422,
        content={
            "detail": make_error_detail(
                code="VALIDATION_ERROR",
                message=message,
                details={"errors": [
                    {"loc": list(e.get("loc", [])), "msg": e.get("msg", ""), "type": e.get("type", "")}
                    for e in errors
                ]},
            )
        },
    )


app.include_router(m1_product_router)
app.include_router(m2_prices_router)
app.include_router(m2_fb_location_router)
app.include_router(health_router)
app.include_router(m5_identity_router)
app.include_router(m5_card_router)
app.include_router(m6_recommend_router)
app.include_router(m11_billing_router)
app.include_router(m12_affiliate_router)
app.include_router(m13_portal_router)
app.include_router(ebay_webhook_router)


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
