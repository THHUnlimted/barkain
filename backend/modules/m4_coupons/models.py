import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    Computed,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CouponCache(Base):
    __tablename__ = "coupon_cache"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    retailer_id: Mapped[str] = mapped_column(
        Text, ForeignKey("retailers.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    discount_type: Mapped[str] = mapped_column(Text, nullable=False)
    discount_value: Mapped[Optional[Decimal]] = mapped_column(Numeric, nullable=True)
    minimum_purchase: Mapped[Optional[Decimal]] = mapped_column(Numeric, nullable=True)
    applies_to: Mapped[Optional[list[str]]] = mapped_column(
        ARRAY(Text), nullable=True
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    validation_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="unvalidated"
    )
    last_validated: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    validated_by: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    validation_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    success_count: Mapped[int] = mapped_column(Integer, server_default="0")
    failure_count: Mapped[int] = mapped_column(Integer, server_default="0")
    confidence_score: Mapped[Optional[Decimal]] = mapped_column(
        Numeric,
        Computed(
            "CASE WHEN (success_count + failure_count) = 0 THEN 0.5 "
            "ELSE success_count::numeric / (success_count + failure_count) END",
            persisted=True,
        ),
    )
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()")
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")

    __table_args__ = (UniqueConstraint("retailer_id", "code"),)
