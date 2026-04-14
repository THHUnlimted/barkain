"""Pydantic schemas for M5 Identity Profile endpoints."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

# Shared vocabulary — seed script + service both depend on this list.
# Changing this tuple is a breaking change: update the seed lint test,
# the IdentityService._active_eligibility_types mapping, and any
# UserDiscountProfile.is_* boolean the new type maps to.
ELIGIBILITY_TYPES: tuple[str, ...] = (
    "military",
    "veteran",
    "student",
    "teacher",
    "first_responder",
    "nurse",
    "healthcare_worker",
    "senior",
    "government",
)


# MARK: - Profile


class IdentityProfileRequest(BaseModel):
    """Create or update identity profile — all fields optional, defaulting to False.

    POST /api/v1/identity/profile is a full replace: any field missing from
    the request body defaults to False in the stored profile.
    """

    is_military: bool = False
    is_veteran: bool = False
    is_student: bool = False
    is_teacher: bool = False
    is_first_responder: bool = False
    is_nurse: bool = False
    is_healthcare_worker: bool = False
    is_senior: bool = False
    is_government: bool = False
    is_aaa_member: bool = False
    is_aarp_member: bool = False
    is_costco_member: bool = False
    is_prime_member: bool = False
    is_sams_member: bool = False
    id_me_verified: bool = False
    sheer_id_verified: bool = False


class IdentityProfileResponse(IdentityProfileRequest):
    """Current user's identity profile, returned on GET or POST."""

    user_id: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, protected_namespaces=())


# MARK: - Discounts


class EligibleDiscount(BaseModel):
    """A single identity discount the user qualifies for.

    `estimated_savings` is computed against the product's best available price
    when the caller supplies `product_id=` to GET /api/v1/identity/discounts.
    Without a product context, it's always null.
    """

    program_id: UUID
    retailer_id: str
    retailer_name: str
    program_name: str
    eligibility_type: str | None = None
    discount_type: str
    discount_value: float | None = None
    discount_max_value: float | None = None
    discount_details: str | None = None
    verification_method: str | None = None
    verification_url: str | None = None
    url: str | None = None
    estimated_savings: float | None = None

    model_config = ConfigDict(from_attributes=True, protected_namespaces=())


class IdentityDiscountsResponse(BaseModel):
    """Discounts the user qualifies for, given their current identity profile."""

    eligible_discounts: list[EligibleDiscount]
    identity_groups_active: list[str]
