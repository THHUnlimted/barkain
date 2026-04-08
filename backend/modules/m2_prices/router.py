"""M2 Price Aggregation router — GET /api/v1/prices/{product_id}."""

import logging
import uuid

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db, get_rate_limiter, get_redis
from modules.m2_prices.schemas import PriceComparisonResponse
from modules.m2_prices.service import PriceAggregationService, ProductNotFoundError

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
    user: dict = Depends(get_current_user),
    _rate: None = Depends(get_rate_limiter("general")),
    db: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis = Depends(get_redis),
) -> PriceComparisonResponse:
    """Get price comparison for a product across all retailers."""
    service = PriceAggregationService(db=db, redis=redis_client)
    try:
        result = await service.get_prices(product_id, force_refresh=force_refresh)
        return PriceComparisonResponse.model_validate(result)
    except ProductNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "PRODUCT_NOT_FOUND",
                    "message": f"No product found with id {product_id}",
                    "details": {"product_id": str(product_id)},
                }
            },
        )
