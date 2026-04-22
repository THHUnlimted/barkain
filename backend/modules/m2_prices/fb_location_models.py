"""SQLAlchemy model for ``fb_marketplace_locations``.

Cache of (city, state_code, country) → Facebook Marketplace numeric
location ID. See ``infrastructure/migrations/versions/0011_fb_marketplace_locations.py``
for rationale.

Constraints mirror the migration so ``Base.metadata.create_all`` in the
pytest schema bootstrap matches alembic exactly (parity pattern from
0003 / 0006 / 0009 / 0010).
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FbMarketplaceLocation(Base):
    __tablename__ = "fb_marketplace_locations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    country: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="US"
    )
    state_code: Mapped[str] = mapped_column(Text, nullable=False)
    city: Mapped[str] = mapped_column(Text, nullable=False)
    # NULL ⇒ tombstone for known-unresolvable inputs. We still persist the
    # row so repeated lookups short-circuit without burning search-engine
    # tokens; the weekly verifier re-checks a sample.
    location_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    canonical_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    resolved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )
    last_verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "country", "state_code", "city", name="uq_fb_marketplace_location"
        ),
        CheckConstraint(
            "state_code ~ '^[A-Z]{2}$'", name="chk_fb_marketplace_location_state"
        ),
        CheckConstraint(
            "source IN ('seed', 'startpage', 'ddg', 'brave', 'user', 'unresolved')",
            name="chk_fb_marketplace_location_source",
        ),
        Index(
            "idx_fb_marketplace_location_id",
            "location_id",
            postgresql_where=text("location_id IS NOT NULL"),
        ),
    )
