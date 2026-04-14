"""M11 Billing schemas — subscription status + RevenueCat webhook payloads."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


# MARK: - Status

class SubscriptionStatusResponse(BaseModel):
    """Server-authoritative view of a user's subscription tier.

    `is_active` is computed, not stored — an expired pro user with tier="pro"
    on the `users` row still returns `is_active=false` until the next webhook
    resolves. Clients should treat `is_active` as the single source of truth
    for backend-side gating.
    """

    model_config = ConfigDict(from_attributes=True)

    tier: str
    expires_at: datetime | None
    is_active: bool
    entitlement_id: str | None = None
