"""FastAPI router for the FB Marketplace location resolver.

Single endpoint: ``POST /api/v1/fb-location/resolve``.

Called by iOS ``LocationPickerSheet`` after ``CLGeocoder`` produces a
city + state from the user's location. Returns the numeric FB
Marketplace location ID that iOS then saves in ``LocationPreferences``
and forwards with every ``/prices/{id}/stream`` request.

Auth + rate-limited to keep the Decodo budget (and search-engine token
bucket) safe from anyone firing novel cities at the endpoint.
"""

from __future__ import annotations

import logging

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db, get_rate_limiter, get_redis
from modules.m2_prices.adapters.fb_marketplace_location_resolver import (
    FbLocationResolver,
)

logger = logging.getLogger("barkain.m2.fb_location")

router = APIRouter(prefix="/api/v1/fb-location", tags=["fb-location"])


# MARK: - Schemas


class ResolveFbLocationRequest(BaseModel):
    """Request body for ``POST /api/v1/fb-location/resolve``."""

    city: str = Field(..., min_length=1, max_length=128)
    state: str = Field(..., min_length=2, max_length=2)
    country: str = Field(default="US", min_length=2, max_length=2)

    @field_validator("state", "country")
    @classmethod
    def _upper_two(cls, v: str) -> str:
        v = v.strip().upper()
        if len(v) != 2 or not v.isalpha():
            raise ValueError("must be a two-letter country/state code")
        return v

    @field_validator("city")
    @classmethod
    def _trim_city(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("city must not be empty")
        return v


class ResolveFbLocationResponse(BaseModel):
    """Response body. ``location_id`` is a string because FB IDs are
    bigints and iOS ``Int`` round-tripping through ``JSONDecoder`` can
    silently narrow for IDs > 2^53. Cheap to stringify, safer over the
    wire."""

    location_id: str | None
    canonical_name: str | None
    verified: bool
    source: str


# MARK: - Endpoint


@router.post(
    "/resolve",
    response_model=ResolveFbLocationResponse,
    responses={
        401: {"description": "Unauthorized"},
        422: {"description": "Invalid city / state"},
        429: {"description": "Resolver engines throttled — retry shortly"},
    },
)
async def resolve_fb_location(
    req: ResolveFbLocationRequest,
    user: dict = Depends(get_current_user),
    # Writes burn Decodo + search-engine tokens, so use the 'write' bucket
    # (default 30/min free, pro multiplied). Typical user hits this once
    # when they pick a location, and cache covers subsequent reads from
    # the same client.
    _rate: None = Depends(get_rate_limiter("write")),
    db: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis = Depends(get_redis),
) -> ResolveFbLocationResponse:
    """Resolve a (city, state) pair to a numeric FB Marketplace location ID.

    Three-tier: Redis → Postgres → live search-engine resolver (with
    singleflight + per-engine token bucket). See
    ``adapters/fb_marketplace_location_resolver.py`` for the algorithm.

    When all engines are throttled simultaneously, returns HTTP 429 so
    the client retries shortly rather than being handed a spurious
    ``unresolved`` tombstone.
    """
    resolver = FbLocationResolver(db=db, redis=redis_client)
    try:
        resolved = await resolver.resolve(
            city=req.city, state_code=req.state, country=req.country
        )
    finally:
        await resolver.aclose()

    if resolved.source == "throttled":
        raise HTTPException(
            status_code=429,
            headers={"Retry-After": "300"},
            detail={
                "error": {
                    "code": "RESOLVER_THROTTLED",
                    "message": (
                        "All search engines are throttled right now. "
                        "Try again in a few minutes."
                    ),
                    "details": {"retry_after_seconds": 300},
                }
            },
        )

    logger.info(
        "resolve_fb_location user=%s city=%s,%s → id=%s source=%s verified=%s",
        user.get("user_id"),
        req.city,
        req.state,
        resolved.location_id,
        resolved.source,
        resolved.verified,
    )

    return ResolveFbLocationResponse(
        location_id=str(resolved.location_id) if resolved.location_id else None,
        canonical_name=resolved.canonical_name,
        verified=resolved.verified,
        source=resolved.source,
    )
