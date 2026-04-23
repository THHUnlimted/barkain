"""M13 Portal router — POST /api/v1/portal/cta (Step 3g)."""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db, get_rate_limiter
from modules.m13_portal.schemas import (
    PortalCTAResolveRequest,
    PortalCTAResolveResponse,
)
from modules.m13_portal.service import PortalMonetizationService

logger = logging.getLogger("barkain.m13")

router = APIRouter(prefix="/api/v1/portal", tags=["portal"])


@router.post("/cta", response_model=PortalCTAResolveResponse)
async def resolve_cta(
    request: PortalCTAResolveRequest,
    user: dict = Depends(get_current_user),
    _rate: None = Depends(get_rate_limiter("general")),
    db: AsyncSession = Depends(get_db),
) -> PortalCTAResolveResponse:
    """Resolve the per-retailer portal CTA list.

    iOS calls this once per retailer when rendering the purchase
    interstitial portal row (Step 3g-B). The response is small and
    derived from a small constant table, so no caching is needed at
    this layer — the recommendation cache (m6) carries CTAs through
    to the iOS layer in the common path; this endpoint exists for the
    secondary "tap any retailer" entry that bypasses /recommend.
    """
    service = PortalMonetizationService(db)
    ctas = await service.resolve_cta_list(
        retailer_id=request.retailer_id,
        user_memberships=request.user_memberships,
    )
    return PortalCTAResolveResponse(
        retailer_id=request.retailer_id,
        ctas=ctas,
    )
