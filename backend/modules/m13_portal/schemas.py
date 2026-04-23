"""Pydantic schemas for M13 Portal Monetization (Step 3g)."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict


# MARK: - CTA Mode


class PortalCTAMode(str, Enum):
    """Three discrete states for "what should the portal pill do".

    The mode drives both the CTA label and the URL the iOS layer hands to
    SFSafariViewController. Order is by user value: deeplink > signup >
    homepage. iOS does not branch on the mode itself — it renders cta_url
    + cta_label as-is — but the disclosure pill renders only for
    SIGNUP_REFERRAL.
    """

    MEMBER_DEEPLINK = "member_deeplink"
    SIGNUP_REFERRAL = "signup_referral"
    GUIDED_ONLY = "guided_only"


# MARK: - CTA response


class PortalCTA(BaseModel):
    """One actionable portal recommendation for a given retailer.

    Returned in lists by the resolver — one element per active portal that
    has a current bonus row for the retailer. Sorted by bonus_rate_percent
    descending so the iOS layer can render the top-N without re-sorting.

    `last_verified` is included so iOS can surface a small "as of …"
    timestamp on long-stale bonuses (the 24h staleness gate prevents the
    pill from rendering at all past that threshold, but a bonus verified
    23h ago is still legitimately old).
    """

    model_config = ConfigDict(from_attributes=True)

    portal_source: str
    display_name: str
    mode: PortalCTAMode
    bonus_rate_percent: float
    bonus_is_elevated: bool
    cta_url: str
    cta_label: str
    signup_promo_copy: str | None = None
    last_verified: datetime | None = None
    disclosure_required: bool = False


# MARK: - Endpoint request


class PortalCTAResolveRequest(BaseModel):
    """Body for ``POST /api/v1/portal/cta``.

    `user_memberships` is a sparse map of portal_source → True for portals
    the user reports being a member of. Missing keys are treated as
    non-member; explicit False is also non-member (round-trip parity with
    the iOS UserDefaults wrapper). The resolver consults this dict to
    decide MEMBER_DEEPLINK vs SIGNUP_REFERRAL/GUIDED_ONLY per portal.
    """

    model_config = ConfigDict(from_attributes=True)

    retailer_id: str
    user_memberships: dict[str, bool] = {}


class PortalCTAResolveResponse(BaseModel):
    """Response wrapper around the sorted CTA list."""

    model_config = ConfigDict(from_attributes=True)

    retailer_id: str
    ctas: list[PortalCTA]
