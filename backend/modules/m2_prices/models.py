import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Price(Base):
    __tablename__ = "prices"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id"), nullable=False
    )
    retailer_id: Mapped[str] = mapped_column(
        Text, ForeignKey("retailers.id"), nullable=False
    )
    price: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    original_price: Mapped[Optional[Decimal]] = mapped_column(Numeric, nullable=True)
    currency: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="USD"
    )
    url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    affiliate_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    condition: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="new"
    )
    is_available: Mapped[bool] = mapped_column(Boolean, server_default="true")
    is_on_sale: Mapped[bool] = mapped_column(Boolean, server_default="false")
    last_checked: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()")
    )

    __table_args__ = (
        UniqueConstraint("product_id", "retailer_id", "condition"),
        Index("idx_prices_product", "product_id"),
        Index("idx_prices_retailer", "retailer_id"),
        Index("idx_prices_last_checked", "last_checked"),
    )


class PriceHistory(Base):
    """Append-only historical prices. Converted to TimescaleDB hypertable via migration."""

    __tablename__ = "price_history"

    # NOTE(D4): Single-column PK on `time` is required by TimescaleDB hypertable.
    # Composite PK (time + product_id + retailer_id) would be ideal but requires
    # recreating the hypertable. Microsecond offset in service.py prevents
    # collisions within a single dispatch. Deferred to Phase 2.
    time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, server_default=text("NOW()")
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    retailer_id: Mapped[str] = mapped_column(Text, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    original_price: Mapped[Optional[Decimal]] = mapped_column(Numeric, nullable=True)
    condition: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="new"
    )
    is_available: Mapped[bool] = mapped_column(Boolean, server_default="true")
    source: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="api"
    )

    __table_args__ = (
        Index("idx_price_history_product_time", "product_id", time.desc()),
        Index("idx_price_history_retailer_time", "retailer_id", time.desc()),
    )
