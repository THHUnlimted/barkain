import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


# MARK: - User Discount Profiles

class UserDiscountProfile(Base):
    __tablename__ = "user_discount_profiles"

    user_id: Mapped[str] = mapped_column(
        Text, ForeignKey("users.id"), primary_key=True
    )
    # Identity attributes
    is_military: Mapped[bool] = mapped_column(Boolean, server_default="false")
    is_veteran: Mapped[bool] = mapped_column(Boolean, server_default="false")
    is_student: Mapped[bool] = mapped_column(Boolean, server_default="false")
    is_teacher: Mapped[bool] = mapped_column(Boolean, server_default="false")
    is_first_responder: Mapped[bool] = mapped_column(Boolean, server_default="false")
    is_nurse: Mapped[bool] = mapped_column(Boolean, server_default="false")
    is_healthcare_worker: Mapped[bool] = mapped_column(Boolean, server_default="false")
    is_senior: Mapped[bool] = mapped_column(Boolean, server_default="false")
    is_aaa_member: Mapped[bool] = mapped_column(Boolean, server_default="false")
    is_aarp_member: Mapped[bool] = mapped_column(Boolean, server_default="false")
    email_domain: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    employer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    alumni_school: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    union_membership: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Memberships
    is_costco_member: Mapped[bool] = mapped_column(Boolean, server_default="false")
    is_prime_member: Mapped[bool] = mapped_column(Boolean, server_default="false")
    is_sams_member: Mapped[bool] = mapped_column(Boolean, server_default="false")
    # Verification
    id_me_verified: Mapped[bool] = mapped_column(Boolean, server_default="false")
    sheer_id_verified: Mapped[bool] = mapped_column(Boolean, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()")
    )


# MARK: - Discount Programs

class DiscountProgram(Base):
    __tablename__ = "discount_programs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    retailer_id: Mapped[str] = mapped_column(
        Text, ForeignKey("retailers.id"), nullable=False
    )
    program_name: Mapped[str] = mapped_column(Text, nullable=False)
    program_type: Mapped[str] = mapped_column(Text, nullable=False)
    eligibility_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    discount_type: Mapped[str] = mapped_column(Text, nullable=False)
    discount_value: Mapped[Optional[Decimal]] = mapped_column(Numeric, nullable=True)
    discount_max_value: Mapped[Optional[Decimal]] = mapped_column(
        Numeric, nullable=True
    )
    discount_details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    applies_to_categories: Mapped[Optional[list[str]]] = mapped_column(
        ARRAY(Text), nullable=True
    )
    excluded_categories: Mapped[Optional[list[str]]] = mapped_column(
        ARRAY(Text), nullable=True
    )
    excluded_brands: Mapped[Optional[list[str]]] = mapped_column(
        ARRAY(Text), nullable=True
    )
    minimum_purchase: Mapped[Optional[Decimal]] = mapped_column(Numeric, nullable=True)
    stackable: Mapped[bool] = mapped_column(Boolean, server_default="false")
    stacks_with: Mapped[Optional[list[str]]] = mapped_column(
        ARRAY(Text), nullable=True
    )
    verification_method: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    verification_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    last_verified: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_verified_by: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    effective_from: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    effective_until: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()")
    )

    __table_args__ = (
        UniqueConstraint("retailer_id", "program_name", "eligibility_type"),
        Index(
            "idx_discount_programs_lookup",
            "retailer_id",
            "program_type",
            "is_active",
            postgresql_where=text("is_active = true"),
        ),
        Index(
            "idx_discount_programs_eligibility",
            "eligibility_type",
            "is_active",
            postgresql_where=text("is_active = true"),
        ),
    )


# MARK: - Card Reward Programs

class CardRewardProgram(Base):
    __tablename__ = "card_reward_programs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    card_network: Mapped[str] = mapped_column(Text, nullable=False)
    card_issuer: Mapped[str] = mapped_column(Text, nullable=False)
    card_product: Mapped[str] = mapped_column(Text, nullable=False)
    card_display_name: Mapped[str] = mapped_column(Text, nullable=False)
    base_reward_rate: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    reward_currency: Mapped[str] = mapped_column(Text, nullable=False)
    point_value_cents: Mapped[Optional[Decimal]] = mapped_column(
        Numeric, nullable=True
    )
    category_bonuses: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    has_shopping_portal: Mapped[bool] = mapped_column(Boolean, server_default="false")
    portal_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    portal_base_rate: Mapped[Optional[Decimal]] = mapped_column(
        Numeric, nullable=True
    )
    annual_fee: Mapped[Decimal] = mapped_column(Numeric, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()")
    )


# MARK: - Rotating Categories

class RotatingCategory(Base):
    __tablename__ = "rotating_categories"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    card_program_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("card_reward_programs.id"), nullable=False
    )
    quarter: Mapped[str] = mapped_column(Text, nullable=False)
    categories: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    bonus_rate: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    activation_required: Mapped[bool] = mapped_column(Boolean, server_default="true")
    activation_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cap_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric, nullable=True)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_until: Mapped[date] = mapped_column(Date, nullable=False)
    last_verified: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (UniqueConstraint("card_program_id", "quarter"),)


# MARK: - User Cards

class UserCard(Base):
    __tablename__ = "user_cards"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[str] = mapped_column(
        Text, ForeignKey("users.id"), nullable=False
    )
    card_program_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("card_reward_programs.id"), nullable=False
    )
    nickname: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_preferred: Mapped[bool] = mapped_column(Boolean, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()")
    )

    __table_args__ = (
        UniqueConstraint("user_id", "card_program_id"),
        Index(
            "idx_user_cards_user",
            "user_id",
            postgresql_where=text("is_active = true"),
        ),
    )


# MARK: - User Category Selections

class UserCategorySelection(Base):
    __tablename__ = "user_category_selections"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[str] = mapped_column(
        Text, ForeignKey("users.id"), nullable=False
    )
    card_program_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("card_reward_programs.id"), nullable=False
    )
    selected_categories: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_until: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()")
    )

    __table_args__ = (
        UniqueConstraint("user_id", "card_program_id", "effective_from"),
    )


# MARK: - Portal Bonuses

class PortalBonus(Base):
    __tablename__ = "portal_bonuses"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    portal_source: Mapped[str] = mapped_column(Text, nullable=False)
    retailer_id: Mapped[str] = mapped_column(
        Text, ForeignKey("retailers.id"), nullable=False
    )
    bonus_type: Mapped[str] = mapped_column(Text, nullable=False)
    bonus_value: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    normal_value: Mapped[Optional[Decimal]] = mapped_column(Numeric, nullable=True)
    is_elevated: Mapped[Optional[bool]] = mapped_column(
        Boolean,
        Computed(
            "bonus_value > COALESCE(normal_value, 0) * 1.5",
            persisted=True,
        ),
    )
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    effective_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_verified: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    verified_by: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()")
    )

    __table_args__ = (
        Index(
            "idx_portal_bonuses_active",
            "retailer_id",
            "effective_until",
        ),
    )
