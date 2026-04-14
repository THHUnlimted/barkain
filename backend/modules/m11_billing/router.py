"""M11 Billing router — GET /status + POST /webhook."""

import logging

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_current_user, get_db, get_redis
from app.errors import raise_http_error
from modules.m11_billing.schemas import SubscriptionStatusResponse
from modules.m11_billing.service import BillingService

logger = logging.getLogger("barkain.m11")

router = APIRouter(prefix="/api/v1/billing", tags=["billing"])


@router.get("/status", response_model=SubscriptionStatusResponse)
async def get_status(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionStatusResponse:
    """Return the current user's server-authoritative subscription status.

    No rate limit — cheap read, used on app launch for reconciliation
    against the RevenueCat SDK's local cache.
    """
    service = BillingService(db)
    return await service.get_subscription_status(user["user_id"])


@router.post("/webhook")
async def revenuecat_webhook(
    request: Request,
    authorization: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis = Depends(get_redis),
) -> dict:
    """Process a RevenueCat webhook.

    Auth is a shared bearer token configured in RevenueCat dashboard and
    stored as `REVENUECAT_WEBHOOK_SECRET`. Any auth failure returns 401 so
    RevenueCat's retry logic kicks in. Event processing is idempotent via
    Redis dedup (7 day TTL) so replays are safe.

    Always returns 200 when auth passes — even for unknown event types —
    to prevent RevenueCat from retrying on events we don't care about.
    """
    _verify_webhook_auth(authorization)

    payload = await request.json()
    service = BillingService(db)
    return await service.process_webhook(payload, redis_client)


def _verify_webhook_auth(authorization: str | None) -> None:
    """Validate the bearer token from RevenueCat against the configured secret.

    Raises 401 on any mismatch. The secret must be set; an empty secret is
    treated as misconfiguration and also rejects.
    """
    secret = settings.REVENUECAT_WEBHOOK_SECRET
    if not secret:
        logger.error("Webhook auth attempted but REVENUECAT_WEBHOOK_SECRET is unset")
        raise_http_error(
            status_code=401,
            code="WEBHOOK_AUTH_FAILED",
            message="Webhook secret not configured",
        )

    if not authorization or not authorization.startswith("Bearer "):
        raise_http_error(
            status_code=401,
            code="WEBHOOK_AUTH_FAILED",
            message="Missing or invalid webhook authorization header",
        )

    provided = authorization.removeprefix("Bearer ").strip()
    if provided != secret:
        raise_http_error(
            status_code=401,
            code="WEBHOOK_AUTH_FAILED",
            message="Invalid webhook authorization",
        )
