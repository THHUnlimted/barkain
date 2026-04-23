"""M13 Portal Monetization — SQLAlchemy models (Step 3g).

One table: ``portal_configs``. The bonus rate data lives in
``portal_bonuses`` (m5_identity.models, owned by the portal_rates worker)
because that's where it's been written since Step 2h. This module owns
display + promo + alerting metadata only.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    Numeric,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


# MARK: - PortalConfig

class PortalConfig(Base):
    __tablename__ = "portal_configs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    portal_source: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    homepage_url: Mapped[str] = mapped_column(Text, nullable=False)
    signup_promo_amount: Mapped[Optional[Decimal]] = mapped_column(
        Numeric, nullable=True
    )
    signup_promo_copy: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    signup_promo_ends_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    last_alerted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )

    __table_args__ = (
        Index(
            "idx_portal_configs_active",
            "is_active",
            postgresql_where=text("is_active = TRUE"),
        ),
    )
