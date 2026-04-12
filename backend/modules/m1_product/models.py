import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Index, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Product(Base):
    __tablename__ = "products"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    upc: Mapped[Optional[str]] = mapped_column(Text, unique=True, nullable=True)
    asin: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    brand: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    image_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    source_raw: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()")
    )

    @property
    def confidence(self) -> float:
        """Resolution confidence score from cross-validation, stored in source_raw."""
        if self.source_raw and isinstance(self.source_raw, dict):
            return self.source_raw.get("confidence", 0.0)
        return 0.0

    __table_args__ = (
        Index("idx_products_upc", "upc", postgresql_where=text("upc IS NOT NULL")),
        Index("idx_products_asin", "asin", postgresql_where=text("asin IS NOT NULL")),
        Index(
            "idx_products_category",
            "category",
            postgresql_where=text("category IS NOT NULL"),
        ),
    )
