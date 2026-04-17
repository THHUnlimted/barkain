"""IdentityService — profile CRUD + zero-LLM discount matching."""

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core_models import Retailer
from modules.m1_product.models import Product
from modules.m2_prices.models import Price
from modules.m5_identity.models import DiscountProgram, UserDiscountProfile
from modules.m5_identity.schemas import (
    EligibleDiscount,
    IdentityDiscountsResponse,
    IdentityProfileRequest,
)

logger = logging.getLogger("barkain.m5")


# MARK: - Product-relevance filters
#
# Identity discounts are matched by the user's identity flags (veteran,
# student, etc.) but a program is only USEFUL if the retailer actually
# stocks the product being viewed. Without this filter, veteran status on
# an iPhone 17 surfaces Samsung.com + LG.com + Lowe's discounts — none of
# which carry Apple phones. The data lives in two hardcoded maps below:
#
#   1. BRAND_SPECIFIC_RETAILERS — retailer_id → the ONE brand it sells.
#      If product.brand doesn't match, drop the discount.
#   2. RETAILER_CATEGORY_KEYWORDS — retailer_id → substrings that must
#      appear in product.category for the retailer to be plausible.
#
# Both filters are FAIL-OPEN: a product with null brand or null category
# sidesteps the gate. Rationale: missing data shouldn't silently hide
# relevant discounts; we only prune when we have clear disconfirming
# evidence. Tech debt: move to a DB column on retailers before the
# catalog grows past ~20 rows.

# Exact brand match (case-insensitive). A retailer not in this dict is
# treated as broad / multi-brand (amazon, home_depot, lowes, best_buy).
BRAND_SPECIFIC_RETAILERS: dict[str, str] = {
    "apple_direct": "apple",
    "samsung_direct": "samsung",
    "hp_direct": "hp",
    "dell_direct": "dell",
    "lenovo_direct": "lenovo",
    "lg_direct": "lg",
    "sony_direct": "sony",
    "microsoft_direct": "microsoft",
}

# Substring keywords that must appear in Product.category (the
# verbose Google product taxonomy string: "Electronics > Communications >
# Telephony > Mobile Phones"). A retailer not in this dict is unbounded.
RETAILER_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    # Home-improvement stores don't sell phones/tablets/laptops.
    "lowes": ("appliance", "kitchen", "home & garden", "garden", "tool"),
    "home_depot": ("appliance", "kitchen", "home & garden", "garden", "tool"),
    # Brand-direct tech stores — narrow to their tech category surface.
    # (Brand gate already handles the main filter; this is defense in depth.)
    "apple_direct": ("electronics", "phone", "tablet", "computer", "laptop", "audio", "watch"),
    "samsung_direct": ("electronics", "phone", "tablet", "television", "tv", "appliance", "audio"),
    "lg_direct": ("electronics", "television", "tv", "appliance", "audio", "kitchen"),
    "sony_direct": ("electronics", "television", "tv", "audio", "camera", "gaming"),
    "hp_direct": ("electronics", "computer", "laptop", "printer", "monitor"),
    "dell_direct": ("electronics", "computer", "laptop", "monitor"),
    "lenovo_direct": ("electronics", "computer", "laptop", "tablet"),
    "microsoft_direct": ("electronics", "computer", "laptop", "tablet", "gaming"),
}


def _retailer_covers_product(
    retailer_id: str,
    product_brand: str | None,
    product_category: str | None,
    product_name: str | None = None,
) -> bool:
    """Return True if ``retailer_id`` plausibly sells a product of this
    brand/category — applied post-identity-match to prune irrelevant rows.

    Fails open on missing data EXCEPT when there's strong disconfirming
    evidence: for a category-gated retailer (Lowe's/Home Depot), if the
    category is null we fall back to matching the ``product_name`` against
    the same keyword set. Many products arrive without a category (Gemini
    rows, UPCitemdb misses) but always have a name, so keyword-matching
    the name is the only way to keep "iPhone 17" out of Lowe's results.
    """
    # Brand gate.
    required_brand = BRAND_SPECIFIC_RETAILERS.get(retailer_id)
    if required_brand is not None and product_brand:
        if required_brand != product_brand.strip().lower():
            return False

    # Category gate — try category first, name as fallback.
    keywords = RETAILER_CATEGORY_KEYWORDS.get(retailer_id)
    if keywords:
        haystack = (product_category or "").lower() or (product_name or "").lower()
        if haystack and not any(kw in haystack for kw in keywords):
            return False

    return True


class IdentityService:
    """Profile CRUD and zero-LLM discount matching via pure SQL."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # MARK: - Profile CRUD

    async def get_or_create_profile(self, user_id: str) -> UserDiscountProfile:
        """Return the user's identity profile, creating a default one if missing.

        Upserts a `users` row first so the FK is always satisfied — the Clerk
        JWT path (and the demo stub) doesn't go through a user-creation webhook,
        so GET /api/v1/identity/profile is the first touchpoint where we learn
        about a user.
        """
        await self.db.execute(
            text("INSERT INTO users (id) VALUES (:id) ON CONFLICT (id) DO NOTHING"),
            {"id": user_id},
        )

        result = await self.db.execute(
            select(UserDiscountProfile).where(UserDiscountProfile.user_id == user_id)
        )
        profile = result.scalar_one_or_none()
        if profile is not None:
            return profile

        profile = UserDiscountProfile(user_id=user_id)
        self.db.add(profile)
        try:
            await self.db.flush()
        except IntegrityError:
            # Concurrent first-touch for the same user_id. Safe: flush() only
            # clears the failed insert within this transaction; outer get_db()
            # still owns the commit/rollback lifecycle.
            await self.db.rollback()
            result = await self.db.execute(
                select(UserDiscountProfile).where(
                    UserDiscountProfile.user_id == user_id
                )
            )
            return result.scalar_one()
        return profile

    async def update_profile(
        self, user_id: str, data: IdentityProfileRequest
    ) -> UserDiscountProfile:
        """Full-replace upsert. Missing request fields fall through to False."""
        profile = await self.get_or_create_profile(user_id)
        for field, value in data.model_dump().items():
            setattr(profile, field, value)
        profile.updated_at = datetime.now(UTC)
        await self.db.flush()
        return profile

    # MARK: - Discount Matching (zero-LLM, pure SQL)

    async def get_eligible_discounts(
        self, user_id: str, product_id: UUID | None
    ) -> IdentityDiscountsResponse:
        """Match the user's identity flags against active discount programs.

        Uses `idx_discount_programs_eligibility` (partial index on is_active).
        Deduplicates programs by `(retailer_id, program_name)` so that a
        single program seeded across 9 eligibility_type rows surfaces as one
        card per matched user.

        When `product_id` is provided, computes `estimated_savings` against
        the product's current best available price.
        """
        profile = await self._load_profile(user_id)
        active_types = self._active_eligibility_types(profile)
        if not active_types:
            return IdentityDiscountsResponse(
                eligible_discounts=[], identity_groups_active=[]
            )

        stmt = (
            select(DiscountProgram, Retailer.display_name)
            .join(Retailer, Retailer.id == DiscountProgram.retailer_id)
            .where(DiscountProgram.eligibility_type.in_(active_types))
            .where(DiscountProgram.is_active.is_(True))
        )
        rows = (await self.db.execute(stmt)).all()

        # Dedup by (retailer_id, program_name) — Samsung Offer Program is seeded
        # across 8+ eligibility rows; surface as ONE card for any user who matches.
        seen: set[tuple[str, str]] = set()
        unique: list[tuple[DiscountProgram, str]] = []
        for prog, retailer_name in rows:
            key = (prog.retailer_id, prog.program_name)
            if key in seen:
                continue
            seen.add(key)
            unique.append((prog, retailer_name))

        best_price: float | None = None
        product_brand: str | None = None
        product_category: str | None = None
        product_name: str | None = None
        if product_id is not None:
            result = await self.db.execute(
                select(Price.price)
                .where(Price.product_id == product_id)
                .where(Price.is_available.is_(True))
                .order_by(Price.price.asc())
                .limit(1)
            )
            raw = result.scalar_one_or_none()
            best_price = float(raw) if raw is not None else None

            # Pull brand + category + name for the relevance gate.
            prod_row = await self.db.execute(
                select(Product.brand, Product.category, Product.name).where(
                    Product.id == product_id
                )
            )
            prod_tuple = prod_row.one_or_none()
            if prod_tuple is not None:
                product_brand, product_category, product_name = prod_tuple

        # Filter out discounts whose retailer can't plausibly stock this
        # product (see BRAND_SPECIFIC_RETAILERS + RETAILER_CATEGORY_KEYWORDS).
        # Skip the gate entirely when product_id is None (browse view).
        if product_id is not None and (product_brand or product_category or product_name):
            before = len(unique)
            unique = [
                (prog, rname)
                for prog, rname in unique
                if _retailer_covers_product(
                    prog.retailer_id, product_brand, product_category, product_name
                )
            ]
            dropped = before - len(unique)
            if dropped:
                logger.debug(
                    "Identity relevance filter: dropped %d/%d programs "
                    "(brand=%s category=%s name=%s)",
                    dropped, before, product_brand, product_category, product_name,
                )

        discounts = [self._build(prog, rname, best_price) for prog, rname in unique]
        # Sort: highest estimated savings first, then highest discount_value
        # (for the no-product-id case), then alphabetical program_name for stability
        discounts.sort(
            key=lambda d: (
                -(d.estimated_savings or 0.0),
                -(d.discount_value or 0.0),
                d.program_name,
            )
        )

        logger.debug(
            "Identity match: user=%s groups=%s programs=%d",
            user_id,
            active_types,
            len(discounts),
        )
        return IdentityDiscountsResponse(
            eligible_discounts=discounts, identity_groups_active=active_types
        )

    async def get_all_programs(self) -> list[EligibleDiscount]:
        """All active discount programs (browse view). No user-specific savings."""
        stmt = (
            select(DiscountProgram, Retailer.display_name)
            .join(Retailer, Retailer.id == DiscountProgram.retailer_id)
            .where(DiscountProgram.is_active.is_(True))
        )
        rows = (await self.db.execute(stmt)).all()
        # Same dedup logic so browse view matches the matched-discounts view shape.
        seen: set[tuple[str, str]] = set()
        result: list[EligibleDiscount] = []
        for prog, rname in rows:
            key = (prog.retailer_id, prog.program_name)
            if key in seen:
                continue
            seen.add(key)
            result.append(self._build(prog, rname, best_price=None))
        result.sort(key=lambda d: (d.retailer_name, d.program_name))
        return result

    # MARK: - Helpers

    async def _load_profile(self, user_id: str) -> UserDiscountProfile | None:
        """Non-upserting read of an existing profile."""
        result = await self.db.execute(
            select(UserDiscountProfile).where(UserDiscountProfile.user_id == user_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _active_eligibility_types(
        profile: UserDiscountProfile | None,
    ) -> list[str]:
        """Map profile booleans to the 9-string eligibility_type vocabulary."""
        if profile is None:
            return []
        mapping = {
            "military": profile.is_military,
            "veteran": profile.is_veteran,
            "student": profile.is_student,
            "teacher": profile.is_teacher,
            "first_responder": profile.is_first_responder,
            "nurse": profile.is_nurse,
            "healthcare_worker": profile.is_healthcare_worker,
            "senior": profile.is_senior,
            "government": profile.is_government,
        }
        return [k for k, v in mapping.items() if v]

    @staticmethod
    def _build(
        prog: DiscountProgram,
        retailer_name: str,
        best_price: float | None,
    ) -> EligibleDiscount:
        """Build an EligibleDiscount, computing estimated_savings when possible."""
        discount_value = (
            float(prog.discount_value) if prog.discount_value is not None else None
        )
        discount_max_value = (
            float(prog.discount_max_value)
            if prog.discount_max_value is not None
            else None
        )

        estimated: float | None = None
        if (
            prog.discount_type == "percentage"
            and discount_value is not None
            and best_price is not None
        ):
            raw = best_price * discount_value / 100.0
            estimated = (
                min(raw, discount_max_value) if discount_max_value is not None else raw
            )
        elif prog.discount_type == "fixed_amount" and discount_value is not None:
            estimated = (
                min(discount_value, discount_max_value)
                if discount_max_value is not None
                else discount_value
            )

        return EligibleDiscount(
            program_id=prog.id,
            retailer_id=prog.retailer_id,
            retailer_name=retailer_name,
            program_name=prog.program_name,
            eligibility_type=prog.eligibility_type,
            discount_type=prog.discount_type,
            discount_value=discount_value,
            discount_max_value=discount_max_value,
            discount_details=prog.discount_details,
            verification_method=prog.verification_method,
            verification_url=prog.verification_url,
            url=prog.url,
            estimated_savings=estimated,
        )
