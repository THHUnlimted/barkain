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
        product: Product | None = None
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

            result = await self.db.execute(
                select(Product).where(Product.id == product_id)
            )
            product = result.scalar_one_or_none()

        if product is not None:
            unique = [
                (prog, rname)
                for prog, rname in unique
                if self._is_relevant(prog, product)
            ]

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

    # Maps brand-direct retailer IDs to the brand they sell.
    _BRAND_DIRECT_MAP: dict[str, str] = {
        "apple_direct": "apple",
        "samsung_direct": "samsung",
        "hp_direct": "hp",
        "dell_direct": "dell",
        "lenovo_direct": "lenovo",
        "microsoft_direct": "microsoft",
        "sony_direct": "sony",
        "lg_direct": "lg",
    }

    @staticmethod
    def _is_relevant(prog: DiscountProgram, product: "Product") -> bool:
        """Filter discount programs by product brand and category.

        Brand-direct retailers only show for matching brands. Programs with
        applies_to_categories only show when the product category overlaps.
        Universal retailers (Amazon, Best Buy, etc.) always pass.
        """
        retailer_brand = IdentityService._BRAND_DIRECT_MAP.get(prog.retailer_id)
        if retailer_brand is not None:
            product_brand = (product.brand or "").lower().strip()
            if retailer_brand != product_brand:
                return False

        if prog.applies_to_categories:
            product_cat = (product.category or "").lower()
            if not any(cat.lower() in product_cat for cat in prog.applies_to_categories):
                return False

        return True

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
