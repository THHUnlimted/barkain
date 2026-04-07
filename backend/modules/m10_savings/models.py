import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Receipt(Base):
    __tablename__ = "receipts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[str] = mapped_column(
        Text, ForeignKey("users.id"), nullable=False
    )
    retailer_id: Mapped[Optional[str]] = mapped_column(
        Text, ForeignKey("retailers.id"), nullable=True
    )
    store_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    receipt_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    subtotal: Mapped[Optional[Decimal]] = mapped_column(Numeric, nullable=True)
    tax: Mapped[Optional[Decimal]] = mapped_column(Numeric, nullable=True)
    total: Mapped[Optional[Decimal]] = mapped_column(Numeric, nullable=True)
    currency: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="USD"
    )
    ocr_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    savings_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric, nullable=True)
    scanned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()")
    )

    __table_args__ = (
        Index("idx_receipts_user", "user_id", scanned_at.desc()),
    )


class ReceiptItem(Base):
    __tablename__ = "receipt_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    receipt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("receipts.id", ondelete="CASCADE"),
        nullable=False,
    )
    product_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id"), nullable=True
    )
    item_name: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, server_default="1")
    unit_price: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    total_price: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    best_alt_price: Mapped[Optional[Decimal]] = mapped_column(Numeric, nullable=True)
    best_alt_retailer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    savings: Mapped[Optional[Decimal]] = mapped_column(Numeric, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()")
    )

    __table_args__ = (
        Index("idx_receipt_items_receipt", "receipt_id"),
        Index(
            "idx_receipt_items_product",
            "product_id",
            postgresql_where=text("product_id IS NOT NULL"),
        ),
    )
