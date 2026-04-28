"""M14 misc-retailer router (Step 3n).

Two endpoints:
  - GET `/api/v1/misc/{product_id}`        — batch-shaped, returns the
    capped row list directly. Used by the iOS layer when it has time
    to await the full result before rendering.
  - GET `/api/v1/misc/{product_id}/stream` — SSE-shaped, yields each
    capped row as a `merchant_row` event followed by a `done` event.
    Mirrors `m2_prices.stream_prices_endpoint` shape so the existing
    iOS byte-level SSE splitter works without modification.

Same auth + rate-limit posture as M2 (`get_current_user` + `general`
bucket). The `?query=` override threads through to the service layer
and scopes the cache + inflight bucket to the same `:q:<sha1>` key
shape `m2_prices` uses, so a generic-search-tap flow doesn't collide
with the SKU-resolved cache.
"""

from __future__ import annotations

import logging
import uuid

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db, get_rate_limiter, get_redis
from app.errors import raise_http_error
from modules.m2_prices.sse import SSE_HEADERS, sse_event
from modules.m14_misc_retailer.schemas import MiscMerchantRow
from modules.m14_misc_retailer.service import (
    MiscRetailerService,
    ProductNotFoundError,
)

logger = logging.getLogger("barkain.m14")

router = APIRouter(prefix="/api/v1/misc", tags=["misc-retailer"])


@router.get(
    "/{product_id}",
    response_model=list[MiscMerchantRow],
    responses={
        404: {"description": "Product not found"},
        422: {"description": "Invalid product_id format"},
    },
)
async def get_misc_retailers_endpoint(
    product_id: uuid.UUID,
    query: str | None = None,
    force_refresh: bool = False,
    user: dict = Depends(get_current_user),  # noqa: ARG001
    _rate: None = Depends(get_rate_limiter("general")),
    db: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis = Depends(get_redis),
) -> list[MiscMerchantRow]:
    service = MiscRetailerService(db=db, redis=redis_client)
    try:
        return await service.get_misc_retailers(
            product_id,
            query_override=query,
            force_refresh=force_refresh,
        )
    except ProductNotFoundError:
        raise_http_error(
            404,
            "PRODUCT_NOT_FOUND",
            "We couldn't find that product.",
            {"product_id": str(product_id)},
        )


@router.get(
    "/{product_id}/stream",
    responses={
        404: {"description": "Product not found"},
        422: {"description": "Invalid product_id format"},
    },
)
async def stream_misc_retailers_endpoint(
    product_id: uuid.UUID,
    query: str | None = None,
    force_refresh: bool = False,
    user: dict = Depends(get_current_user),  # noqa: ARG001
    _rate: None = Depends(get_rate_limiter("general")),
    db: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis = Depends(get_redis),
) -> StreamingResponse:
    service = MiscRetailerService(db=db, redis=redis_client)

    # Validate before opening the stream so 404 is a normal HTTPException,
    # not a mid-stream event the iOS client has to special-case.
    try:
        await service._validate_product(product_id)
    except ProductNotFoundError:
        raise_http_error(
            404,
            "PRODUCT_NOT_FOUND",
            "We couldn't find that product.",
            {"product_id": str(product_id)},
        )

    async def event_stream():
        async for event_type, payload in service.stream_misc_retailers(
            product_id,
            query_override=query,
            force_refresh=force_refresh,
        ):
            yield sse_event(event_type, payload)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
