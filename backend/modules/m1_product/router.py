"""M1 Product Resolution router — POST /api/v1/products/resolve."""

import logging

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db, get_rate_limiter, get_redis
from modules.m1_product.schemas import ProductResolveRequest, ProductResponse
from modules.m1_product.service import (
    ProductNotFoundError,
    ProductResolutionService,
)

logger = logging.getLogger("barkain.m1")

router = APIRouter(prefix="/api/v1/products", tags=["products"])


@router.post(
    "/resolve",
    response_model=ProductResponse,
    status_code=200,
    responses={
        404: {"description": "Product not found for given UPC"},
        422: {"description": "Invalid UPC format"},
    },
)
async def resolve_product(
    body: ProductResolveRequest,
    user: dict = Depends(get_current_user),
    _rate: None = Depends(get_rate_limiter("general")),
    db: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis = Depends(get_redis),
) -> ProductResponse:
    """Resolve a UPC barcode to a canonical product."""
    service = ProductResolutionService(db=db, redis=redis_client)
    try:
        product = await service.resolve(body.upc)
        return ProductResponse.model_validate(product)
    except ProductNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "PRODUCT_NOT_FOUND",
                    "message": f"No product found for UPC {body.upc}",
                    "details": {"upc": body.upc},
                }
            },
        )
