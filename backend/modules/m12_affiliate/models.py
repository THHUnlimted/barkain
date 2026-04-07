import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Numeric, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AffiliateClick(Base):
    __tablename__ = "affiliate_clicks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[str] = mapped_column(
        Text, ForeignKey("users.id"), nullable=False
    )
    product_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id"), nullable=True
    )
    retailer_id: Mapped[str] = mapped_column(
        Text, ForeignKey("retailers.id"), nullable=False
    )
    affiliate_network: Mapped[str] = mapped_column(Text, nullable=False)
    click_url: Mapped[str] = mapped_column(Text, nullable=False)
    clicked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )
    converted: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    commission: Mapped[Optional[Decimal]] = mapped_column(Numeric, nullable=True)
    conversion_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("idx_affiliate_clicks_user", "user_id", clicked_at.desc()),
        Index("idx_affiliate_clicks_retailer", "retailer_id", clicked_at.desc()),
    )
