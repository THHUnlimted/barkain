"""M12 Affiliate router — /click + /stats + /conversion (placeholder)."""

import logging

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_current_user, get_db, get_rate_limiter
from app.errors import raise_http_error
from modules.m12_affiliate.schemas import (
    AffiliateClickRequest,
    AffiliateStatsResponse,
    AffiliateURLResponse,
)
from modules.m12_affiliate.service import AffiliateService

logger = logging.getLogger("barkain.m12")

router = APIRouter(prefix="/api/v1/affiliate", tags=["affiliate"])


@router.post("/click", response_model=AffiliateURLResponse)
async def log_click(
    request: AffiliateClickRequest,
    user: dict = Depends(get_current_user),
    _rate: None = Depends(get_rate_limiter("general")),
    db: AsyncSession = Depends(get_db),
) -> AffiliateURLResponse:
    """Tag a retailer URL, log the click, and return the tagged URL.

    The iOS client calls this before opening any retailer URL so it never
    constructs affiliate URLs locally — the backend is the single authority.
    """
    service = AffiliateService(db)
    return await service.log_click(user["user_id"], request)


@router.get("/stats", response_model=AffiliateStatsResponse)
async def get_stats(
    user: dict = Depends(get_current_user),
    _rate: None = Depends(get_rate_limiter("general")),
    db: AsyncSession = Depends(get_db),
) -> AffiliateStatsResponse:
    """Return the current user's click counts grouped by retailer."""
    service = AffiliateService(db)
    return await service.get_user_stats(user["user_id"])


@router.post("/conversion")
async def conversion_webhook(
    request: Request,
    authorization: str | None = Header(None),
) -> dict:
    """Placeholder conversion webhook.

    When `AFFILIATE_WEBHOOK_SECRET` is set, requires an `Authorization:
    Bearer <secret>` header. When unset, accepts any request (permissive
    placeholder mode — lets the endpoint be wired in staging before the
    affiliate networks are actually configured).

    Always returns 200 when auth passes so networks don't retry on
    acknowledgement-only events.
    """
    secret = settings.AFFILIATE_WEBHOOK_SECRET
    if secret:
        if not authorization or not authorization.startswith("Bearer "):
            raise_http_error(
                status_code=401,
                code="AFFILIATE_WEBHOOK_AUTH_FAILED",
                message="Missing or invalid webhook authorization header",
            )
        provided = authorization.removeprefix("Bearer ").strip()
        if provided != secret:
            raise_http_error(
                status_code=401,
                code="AFFILIATE_WEBHOOK_AUTH_FAILED",
                message="Invalid webhook authorization",
            )
    else:
        logger.warning(
            "Affiliate conversion webhook accepted permissively — "
            "configure AFFILIATE_WEBHOOK_SECRET for real conversion tracking."
        )

    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        payload = {"_raw_body_unparseable": True}

    logger.info("Affiliate conversion payload (placeholder): %s", payload)
    return {"ok": True, "action": "acknowledged"}
