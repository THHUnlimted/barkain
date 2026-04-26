"""M6 Recommendation Engine router — `POST /api/v1/recommend` (Step 3e)."""

import logging

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db, get_rate_limiter, get_redis
from app.errors import raise_http_error
from modules.m2_prices.service import ProductNotFoundError
from modules.m6_recommend.schemas import Recommendation, RecommendationRequest
from modules.m6_recommend.service import (
    InsufficientPriceDataError,
    RecommendationProductNotFoundError,
    RecommendationService,
)

logger = logging.getLogger("barkain.m6")

router = APIRouter(prefix="/api/v1", tags=["recommend"])


@router.post(
    "/recommend",
    response_model=Recommendation,
    status_code=200,
    responses={
        404: {"description": "Product not found"},
        422: {"description": "Insufficient price data (< 2 successful retailers)"},
        429: {"description": "Rate limit exceeded"},
    },
)
async def recommend(
    body: RecommendationRequest,
    user: dict = Depends(get_current_user),
    _rate: None = Depends(get_rate_limiter("general")),
    db: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis = Depends(get_redis),
) -> Recommendation:
    """Compute the single best purchase path for a product.

    Deterministic stacking: identity + card + portal. No LLM. Target p95
    under 150 ms. See `modules/m6_recommend/service.py` for the full
    algorithm.
    """
    service = RecommendationService(db=db, redis=redis_client)
    try:
        return await service.get_recommendation(
            user["user_id"],
            body.product_id,
            force_refresh=body.force_refresh,
            user_memberships=body.user_memberships,
            query_override=body.query_override,
        )
    except RecommendationProductNotFoundError:
        raise_http_error(
            404,
            "PRODUCT_NOT_FOUND",
            "We couldn't find that product.",
            {"product_id": str(body.product_id)},
        )
    except ProductNotFoundError:
        # PriceAggregationService raises its own ProductNotFoundError — map
        # it to the same public error code so the iOS client only has to
        # handle one shape.
        raise_http_error(
            404,
            "PRODUCT_NOT_FOUND",
            "We couldn't find that product.",
            {"product_id": str(body.product_id)},
        )
    except InsufficientPriceDataError as exc:
        # iOS renders its own localized copy on this 422 — the engineer-
        # tone exception message is kept in the response only as a debug
        # signal for telemetry / log correlation, never surfaced to UI.
        raise_http_error(
            422,
            "RECOMMEND_INSUFFICIENT_DATA",
            "We couldn't pick a best option for this one yet.",
            {"product_id": str(body.product_id), "debug_reason": str(exc)},
        )
