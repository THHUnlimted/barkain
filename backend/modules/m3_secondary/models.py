import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Listing(Base):
    __tablename__ = "listings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id"), nullable=False
    )
    retailer_id: Mapped[str] = mapped_column(
        Text, ForeignKey("retailers.id"), nullable=False
    )
    external_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    currency: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="USD"
    )
    condition: Mapped[str] = mapped_column(Text, nullable=False)
    seller_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    seller_rating: Mapped[Optional[Decimal]] = mapped_column(Numeric, nullable=True)
    seller_reviews: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    image_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    shipping_cost: Mapped[Optional[Decimal]] = mapped_column(Numeric, nullable=True)
    returns_accepted: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    warranty_info: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    listing_age_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    quality_score: Mapped[Optional[Decimal]] = mapped_column(Numeric, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("retailer_id", "external_id"),
        Index(
            "idx_listings_product",
            "product_id",
            "is_active",
            postgresql_where=text("is_active = true"),
        ),
    )
