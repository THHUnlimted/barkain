"""BillingService — subscription status + RevenueCat webhook processing.

Zero-LLM, pure SQL. All business logic lives here; the router is a thin
HTTP wrapper. Tests mount this service directly against the fixtures DB.
"""

import logging
from datetime import UTC, datetime

import redis.asyncio as aioredis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from modules.m11_billing.schemas import SubscriptionStatusResponse

logger = logging.getLogger("barkain.m11")


# Tier cache key pattern — see dependencies.py::get_rate_limiter. Bust on
# every webhook that touches tier state so rate limiters see changes within
# the cache TTL (60s).
TIER_CACHE_KEY = "tier:{user_id}"

# 7 days — long enough that RevenueCat's redelivery window (typically < 24h)
# is fully covered without unbounded key growth.
EVENT_DEDUP_TTL_SECONDS = 7 * 24 * 60 * 60

# Event types that mutate subscription state. RevenueCat documents additional
# event types (SUBSCRIBER_ALIAS, TRANSFER, etc.) that we acknowledge with a
# 200 but don't process.
STATE_CHANGING_EVENTS: frozenset[str] = frozenset(
    {
        "INITIAL_PURCHASE",
        "RENEWAL",
        "NON_RENEWING_PURCHASE",
        "PRODUCT_CHANGE",
        "UNCANCELLATION",
        "CANCELLATION",
        "EXPIRATION",
    }
)


class BillingService:
    """Subscription status + webhook event processor."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # MARK: - Status

    async def get_subscription_status(
        self, user_id: str
    ) -> SubscriptionStatusResponse:
        """Return the computed subscription status for a user.

        Missing user row → free tier (not an error). This matches the rate
        limiter's default behavior and lets the iOS client call /status on
        launch without pre-seeding a users row.
        """
        row = await self.db.execute(
            text(
                "SELECT subscription_tier, subscription_expires_at "
                "FROM users WHERE id = :user_id"
            ),
            {"user_id": user_id},
        )
        record = row.first()

        if record is None:
            return SubscriptionStatusResponse(
                tier="free",
                expires_at=None,
                is_active=False,
                entitlement_id=None,
            )

        tier = record[0] or "free"
        expires_at = record[1]
        is_active = self._is_active(tier, expires_at)
        # If the row says "pro" but the subscription has expired, report free
        # to the client. The row stays "pro" until the next webhook lands —
        # this avoids mutating DB state from a read path.
        effective_tier = tier if is_active else "free"

        return SubscriptionStatusResponse(
            tier=effective_tier,
            expires_at=expires_at,
            is_active=is_active,
            entitlement_id="Barkain Pro" if is_active else None,
        )

    # MARK: - Webhook

    async def process_webhook(
        self,
        payload: dict,
        redis_client: aioredis.Redis,
    ) -> dict:
        """Process a RevenueCat webhook payload.

        RevenueCat envelope shape::

            {
                "event": {
                    "type": "INITIAL_PURCHASE",
                    "id": "RCEVT_...",
                    "app_user_id": "demo_user",
                    "expiration_at_ms": 1735689600000,
                    ...
                },
                "api_version": "1.0"
            }

        Returns a small status dict suitable for the HTTP 200 body.

        Idempotent: the same `event.id` processed twice is a no-op. Unknown
        event types return 200 with `action="acknowledged"` — never retry.
        """
        event = payload.get("event") or {}
        event_type = str(event.get("type") or "")
        event_id = str(event.get("id") or "")
        app_user_id = str(event.get("app_user_id") or "")

        if not event_type or not event_id or not app_user_id:
            logger.warning(
                "Webhook missing required fields: type=%s id=%s user=%s",
                event_type,
                event_id,
                app_user_id,
            )
            return {"ok": True, "action": "ignored", "reason": "missing_fields"}

        # Idempotency via Redis SETNX. Falls open on Redis errors — logging a
        # warning rather than 500'ing. RevenueCat will retry on 5xx but the
        # dedup window is a defense-in-depth layer, not the authority.
        try:
            dedup_key = f"revenuecat:processed:{event_id}"
            acquired = await redis_client.set(
                dedup_key, "1", nx=True, ex=EVENT_DEDUP_TTL_SECONDS
            )
            if not acquired:
                logger.info(
                    "Webhook duplicate event dropped: type=%s id=%s",
                    event_type,
                    event_id,
                )
                return {"ok": True, "action": "duplicate"}
        except Exception as e:  # noqa: BLE001
            logger.warning("Webhook dedup check failed (continuing): %s", e)

        if event_type not in STATE_CHANGING_EVENTS:
            logger.info(
                "Webhook acknowledged non-state event: type=%s id=%s",
                event_type,
                event_id,
            )
            return {"ok": True, "action": "acknowledged", "type": event_type}

        # Resolve the target tier + expiration for this event. All writes are
        # SET (not deltas) so a replayed event would produce the same DB row.
        tier, expires_at = self._resolve_state(event_type, event)

        # Upsert the users row first (FK safety, demo mode parity). Matches
        # the m5_identity.get_or_create_profile pattern.
        await self.db.execute(
            text(
                "INSERT INTO users (id, subscription_tier, subscription_expires_at) "
                "VALUES (:id, :tier, :expires) "
                "ON CONFLICT (id) DO UPDATE SET "
                "subscription_tier = EXCLUDED.subscription_tier, "
                "subscription_expires_at = EXCLUDED.subscription_expires_at, "
                "updated_at = NOW()"
            ),
            {"id": app_user_id, "tier": tier, "expires": expires_at},
        )
        await self.db.flush()

        # Bust the rate-limiter tier cache so the new tier applies within a
        # few seconds even if the 60s TTL hasn't elapsed.
        try:
            await redis_client.delete(TIER_CACHE_KEY.format(user_id=app_user_id))
        except Exception as e:  # noqa: BLE001
            logger.warning("Tier cache bust failed (non-fatal): %s", e)

        logger.info(
            "Webhook processed: type=%s user=%s tier=%s expires=%s",
            event_type,
            app_user_id,
            tier,
            expires_at,
        )
        return {
            "ok": True,
            "action": "processed",
            "type": event_type,
            "tier": tier,
        }

    # MARK: - Helpers

    @staticmethod
    def _is_active(tier: str, expires_at: datetime | None) -> bool:
        if tier != "pro":
            return False
        if expires_at is None:
            # Lifetime purchase (NON_RENEWING_PURCHASE) — never expires.
            return True
        # Normalize tz to be defensive against DB drivers returning naive dt.
        now = datetime.now(UTC)
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        return expires_at > now

    @staticmethod
    def _resolve_state(
        event_type: str, event: dict
    ) -> tuple[str, datetime | None]:
        """Map an event to the target (tier, expires_at) pair.

        - INITIAL_PURCHASE, RENEWAL, PRODUCT_CHANGE, UNCANCELLATION → pro,
          expires_at from event.expiration_at_ms (ms since epoch).
        - NON_RENEWING_PURCHASE → pro with expires_at=None (lifetime).
        - CANCELLATION → pro with the existing expiration (the user keeps
          pro until the period ends). The event still carries
          expiration_at_ms so we SET it from the event for consistency.
        - EXPIRATION → free, expires_at cleared.
        """
        expires_at = _parse_expiration_ms(event.get("expiration_at_ms"))

        if event_type == "EXPIRATION":
            return "free", None
        if event_type == "NON_RENEWING_PURCHASE":
            return "pro", None
        # All other state-changing events set pro + expiration from the event.
        return "pro", expires_at


def _parse_expiration_ms(value: object) -> datetime | None:
    """Convert RevenueCat `expiration_at_ms` (int or string) to UTC datetime."""
    if value is None:
        return None
    try:
        ms = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(ms / 1000, tz=UTC)
