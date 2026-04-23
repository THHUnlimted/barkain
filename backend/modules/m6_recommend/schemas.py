"""Pydantic schemas for M6 Recommendation Engine (Step 3e).

Deterministic stacking output — no LLM shapes here. All monetary fields
are `float` (iOS `Double` decoder breaks on stringified `Decimal` JSON,
so the convention across the codebase is float-everywhere for price math).
"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from modules.m13_portal.schemas import PortalCTA


# MARK: - Request


class RecommendationRequest(BaseModel):
    """Body for `POST /api/v1/recommend`.

    `user_memberships` carries the user's self-reported portal-membership
    state (Step 3g-B). Sparse map of portal_source → True. The service
    folds this into the cache-key hash so toggling "I'm a Rakuten member"
    busts stale recs immediately — same class of bug as adding a card
    that 3f's `:c<sha1(card_ids)>` pattern solved. Missing keys are
    treated as non-member; explicit False is also non-member.
    """

    product_id: UUID
    force_refresh: bool = False
    user_memberships: dict[str, bool] = Field(default_factory=dict)


# MARK: - Stacked Path


class StackedPath(BaseModel):
    """One retailer candidate with its full identity + card + portal stack.

    `final_price` is what shows on the checkout page — `base_price -
    identity_savings`. Card rewards and portal cashback are deferred rebates,
    not sticker discounts, so they don't fold into `final_price`. The
    `effective_cost` field (net of rebates) is what we use to rank candidates
    because it represents the user's true out-of-pocket over time.
    """

    retailer_id: str
    retailer_name: str
    base_price: float
    final_price: float
    effective_cost: float
    total_savings: float

    identity_savings: float = 0.0
    identity_source: str | None = None

    card_savings: float = 0.0
    card_source: str | None = None

    portal_savings: float = 0.0
    portal_source: str | None = None

    # Step 3g-B: actionable portal CTAs for this retailer (member deeplink
    # vs signup referral vs guided-only). Only the winner carries a
    # populated list; alternatives default to [] to keep the response tight.
    portal_ctas: list[PortalCTA] = Field(default_factory=list)

    condition: str = "new"
    product_url: str | None = None

    model_config = ConfigDict(protected_namespaces=())


# MARK: - Brand-direct callout (3j fold-in)


class BrandDirectCallout(BaseModel):
    """Secondary recommendation card for a brand-direct program ≥15 %.

    Fires when an eligible identity program exists at a `*_direct` retailer
    (samsung_direct, apple_direct, etc.) with `discount_value >= 15.0`.
    Rendered as a smaller pill under the main hero — "Also: 30% off at
    Samsung.com with your military ID." The iOS layer drops the user into
    the in-app browser pointed at `purchase_url_template`.
    """

    retailer_id: str
    retailer_name: str
    program_name: str
    discount_value: float
    discount_type: str
    purchase_url_template: str | None = None


# MARK: - Recommendation response


class Recommendation(BaseModel):
    """Top-level response from `POST /api/v1/recommend`.

    `has_stackable_value` is true when any of identity / card / portal
    savings were non-zero on the winner — iOS uses it to pick between the
    generic "lowest price at X" headline and the multi-layer "stacking …
    beats the naive cheapest by $N" copy.
    """

    product_id: UUID
    product_name: str
    winner: StackedPath
    headline: str
    why: str
    alternatives: list[StackedPath]
    brand_direct_callout: BrandDirectCallout | None = None
    has_stackable_value: bool
    compute_ms: int
    cached: bool

    model_config = ConfigDict(protected_namespaces=())
