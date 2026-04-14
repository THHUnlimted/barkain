"""M5 Identity Profile router — GET/POST /profile + GET /discounts."""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db, get_rate_limiter
from modules.m5_identity.schemas import (
    EligibleDiscount,
    IdentityDiscountsResponse,
    IdentityProfileRequest,
    IdentityProfileResponse,
)
from modules.m5_identity.service import IdentityService

logger = logging.getLogger("barkain.m5")

router = APIRouter(prefix="/api/v1/identity", tags=["identity"])


@router.get("/profile", response_model=IdentityProfileResponse)
async def get_profile(
    user: dict = Depends(get_current_user),
    _rate: None = Depends(get_rate_limiter("general")),
    db: AsyncSession = Depends(get_db),
) -> IdentityProfileResponse:
    """Return the current user's identity profile.

    Auto-creates an empty profile on first call — the iOS client never needs
    to handle 404.
    """
    service = IdentityService(db)
    profile = await service.get_or_create_profile(user["user_id"])
    return IdentityProfileResponse.model_validate(profile)


@router.post("/profile", response_model=IdentityProfileResponse)
async def update_profile(
    body: IdentityProfileRequest,
    user: dict = Depends(get_current_user),
    _rate: None = Depends(get_rate_limiter("write")),
    db: AsyncSession = Depends(get_db),
) -> IdentityProfileResponse:
    """Full-replace upsert of the current user's identity profile.

    Missing request fields fall through to False. Send the full desired state
    on every save; do not attempt PATCH semantics.
    """
    service = IdentityService(db)
    profile = await service.update_profile(user["user_id"], body)
    return IdentityProfileResponse.model_validate(profile)


@router.get("/discounts", response_model=IdentityDiscountsResponse)
async def get_eligible_discounts(
    product_id: UUID | None = None,
    user: dict = Depends(get_current_user),
    _rate: None = Depends(get_rate_limiter("general")),
    db: AsyncSession = Depends(get_db),
) -> IdentityDiscountsResponse:
    """Discounts the current user qualifies for.

    Pass `?product_id=<uuid>` to compute `estimated_savings` against that
    product's current best price. Without it, savings are null.
    """
    service = IdentityService(db)
    return await service.get_eligible_discounts(user["user_id"], product_id)


@router.get("/discounts/all", response_model=list[EligibleDiscount])
async def list_all_programs(
    _user: dict = Depends(get_current_user),
    _rate: None = Depends(get_rate_limiter("general")),
    db: AsyncSession = Depends(get_db),
) -> list[EligibleDiscount]:
    """Browse view of every active discount program. No user scoping beyond auth."""
    service = IdentityService(db)
    return await service.get_all_programs()
