"""M12 Affiliate schemas — click request, tagged URL response, stats."""

import uuid

from pydantic import BaseModel, ConfigDict


# MARK: - Click request


class AffiliateClickRequest(BaseModel):
    """Body of POST /api/v1/affiliate/click.

    `product_id` is optional so taps can be logged even when the click
    originates from a context without a resolved product (edge case —
    never happens on the current iOS surface, but the column allows null).
    """

    model_config = ConfigDict(from_attributes=True)

    product_id: uuid.UUID | None = None
    retailer_id: str
    product_url: str
    # Step 3f — purchase interstitial records whether the user bypassed
    # the card-activation reminder. Persisted to affiliate_clicks.metadata
    # for post-demo analytics. Default false preserves the 2g contract.
    activation_skipped: bool = False
    # Step 3g-B — when the click came via a portal CTA (Rakuten / TopCashback
    # / BeFrugal), iOS sends both fields so funnel analytics can separate
    # MEMBER_DEEPLINK detours, SIGNUP_REFERRAL conversions, and GUIDED_ONLY
    # handoffs (the last is the signal that says "TopCashback approval would
    # unlock revenue from X% of flows"). Direct retailer taps (no portal)
    # leave both null. Validated server-side against the PortalCTAMode set.
    portal_event_type: str | None = None
    portal_source: str | None = None


# MARK: - Response envelopes


class AffiliateURLResponse(BaseModel):
    """Response from POST /api/v1/affiliate/click.

    Always returns a non-empty `affiliate_url` unless the caller passed an
    empty string. Unknown retailers pass the original URL through with
    `is_affiliated=false` and `network=None`.
    """

    model_config = ConfigDict(from_attributes=True)

    affiliate_url: str
    is_affiliated: bool
    network: str | None = None
    retailer_id: str


class AffiliateStatsResponse(BaseModel):
    """Response from GET /api/v1/affiliate/stats.

    `clicks_by_retailer` is a simple map (retailer_id → count) for the
    current user. `total_clicks` is the sum of values — callers can
    compute it themselves, but returning it avoids a client-side reduce.
    """

    model_config = ConfigDict(from_attributes=True)

    clicks_by_retailer: dict[str, int]
    total_clicks: int
