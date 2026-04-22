"""M2 Price Aggregation router — GET /api/v1/prices/{product_id} (+ /stream)."""

import logging
import uuid

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db, get_rate_limiter, get_redis
from app.errors import raise_http_error
from modules.m2_prices.schemas import PriceComparisonResponse
from modules.m2_prices.service import PriceAggregationService, ProductNotFoundError
from modules.m2_prices.sse import SSE_HEADERS, sse_event

# Shared fb_marketplace location query params. Validation lives here so a
# bad id 422s at the router boundary — returning the error mid-stream
# after SSE has opened is confusing for the iOS client (it expects events,
# not validation failures).
_FB_LOCATION_ID_PATTERN = r"^\d{1,30}$"

logger = logging.getLogger("barkain.m2")

router = APIRouter(prefix="/api/v1/prices", tags=["prices"])


@router.get(
    "/{product_id}",
    response_model=PriceComparisonResponse,
    status_code=200,
    responses={
        404: {"description": "Product not found"},
        422: {"description": "Invalid product_id format"},
    },
)
async def get_prices(
    product_id: uuid.UUID,
    force_refresh: bool = False,
    fb_location_id: str | None = Query(default=None, pattern=_FB_LOCATION_ID_PATTERN),
    fb_radius_miles: int | None = Query(default=None, ge=1, le=500),
    user: dict = Depends(get_current_user),
    _rate: None = Depends(get_rate_limiter("general")),
    db: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis = Depends(get_redis),
) -> PriceComparisonResponse:
    """Get price comparison for a product across all retailers.

    ``fb_location_id`` / ``fb_radius_miles`` are routed to the FB
    Marketplace container only — they let the caller override the baked-in
    city default (see `containers/fb_marketplace/extract.sh`). Radius is
    miles at the API boundary and converted to km inside
    ``ContainerClient`` on the way to the container.
    """
    service = PriceAggregationService(db=db, redis=redis_client)
    try:
        result = await service.get_prices(
            product_id,
            force_refresh=force_refresh,
            fb_location_id=fb_location_id,
            fb_radius_miles=fb_radius_miles,
        )
        return PriceComparisonResponse.model_validate(result)
    except ProductNotFoundError:
        raise_http_error(404, "PRODUCT_NOT_FOUND", f"No product found with id {product_id}", {"product_id": str(product_id)})


# MARK: - Streaming (Step 2c)


@router.get(
    "/{product_id}/stream",
    responses={
        404: {"description": "Product not found"},
        422: {"description": "Invalid product_id format"},
    },
)
async def stream_prices_endpoint(
    product_id: uuid.UUID,
    force_refresh: bool = False,
    query: str | None = None,
    fb_location_id: str | None = Query(default=None, pattern=_FB_LOCATION_ID_PATTERN),
    fb_radius_miles: int | None = Query(default=None, ge=1, le=500),
    user: dict = Depends(get_current_user),
    _rate: None = Depends(get_rate_limiter("general")),
    db: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis = Depends(get_redis),
) -> StreamingResponse:
    """Stream per-retailer price results as Server-Sent Events (SSE).

    Each retailer yields a `retailer_result` event the moment its data lands
    (walmart ~12s, amazon ~30s, best_buy ~91s). Terminates with a `done` event
    summarizing the run, or an `error` event on pipeline failure.

    Cache hits replay all events instantly. `?force_refresh=true` bypasses cache.
    ``fb_location_id`` + ``fb_radius_miles`` are forwarded only to the
    fb_marketplace container and carve out a per-location cache bucket.
    Radius is miles at the API boundary; km conversion happens at the
    container adapter in ``ContainerClient.extract``.
    """
    service = PriceAggregationService(db=db, redis=redis_client)

    # Validate BEFORE opening the stream so 404 is a normal HTTPException,
    # not a mid-stream event the client has to parse.
    try:
        await service._validate_product(product_id)
    except ProductNotFoundError:
        raise_http_error(
            404,
            "PRODUCT_NOT_FOUND",
            f"No product found with id {product_id}",
            {"product_id": str(product_id)},
        )

    async def event_stream():
        async for event_type, payload in service.stream_prices(
            product_id,
            force_refresh=force_refresh,
            query_override=query,
            fb_location_id=fb_location_id,
            fb_radius_miles=fb_radius_miles,
        ):
            yield sse_event(event_type, payload)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
