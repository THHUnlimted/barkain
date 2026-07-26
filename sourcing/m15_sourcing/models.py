"""M15 Sourcing — SQLAlchemy models.

Four tables:

``sourcing_lists``    one uploaded distributor price list
``sourcing_rows``     one line of that list, plus its match / economics / verdict
``listing_snapshots`` time series of listing observations — the demand dataset
``brand_access``      per-brand distributor + gating ledger

## Why sourcing rows don't write to ``products``

A distributor list is 3,000 *speculative* UPCs; most will never be bought and
many won't resolve at all. Writing them into the consumer ``products`` table
would pollute Recently Sniffed, dilute the pg_trgm search index, and blow out
the resolve cache with rows nobody asked for. M15 owns its own storage and
reaches into M1/M2 only for adapters.

## Why ``listing_snapshots`` is keyed on a channel-scoped listing key

Snapshots outlive the sourcing row that created them — that's the whole point
of the dataset. Keying on ``(channel, listing_key, captured_at)`` rather than
on ``sourcing_row_id`` means the history survives list deletion and is shared
across every user who ever sources the same item. ``listing_key`` is the
channel's own identifier (Walmart ``itemId``, eBay legacy item ID), falling
back to the GTIN when the channel doesn't give us one.

Constraints are mirrored in ``__table_args__`` so ``Base.metadata.create_all``
(the pytest bootstrap) matches Alembic — the parity pattern from 0003 / 0006 /
0009 / 0010 / 0011 / 0012.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# Lifecycle of a list. `ingested` → `crunching` → `complete`, or `failed`.
LIST_STATUSES = ("ingested", "crunching", "complete", "failed")

# Per-row pipeline state, so a crunch that dies halfway can resume instead of
# re-spending every API call.
ROW_STATUSES = ("pending", "matched", "scored", "skipped", "error")

BRAND_STATUSES = ("authorized", "restricted", "pending", "unknown")

CHANNELS = ("walmart", "ebay")


class SourcingList(Base):
    __tablename__ = "sourcing_lists"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[str] = mapped_column(
        Text, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    source_filename: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    supplier: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="ingested")

    row_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    usable_row_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    scored_row_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )

    # Column mapping + normalization stats from ingest, so the UI can explain
    # "we read your 'Your Price' column as unit cost" without re-parsing.
    column_mapping: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    ingest_stats: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    # Thresholds are stored per list, not per user: the bar for a $4 consumable
    # list is not the bar for a $200 tool list, and buyers genuinely run both.
    thresholds: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    verdict_summary: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()")
    )
    crunched_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('ingested', 'crunching', 'complete', 'failed')",
            name="chk_sourcing_list_status",
        ),
        Index("idx_sourcing_lists_user_created", "user_id", text("created_at DESC")),
    )


class SourcingRow(Base):
    __tablename__ = "sourcing_rows"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    list_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sourcing_lists.id", ondelete="CASCADE"),
        nullable=False,
    )
    row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")

    # ── Distributor-supplied ──────────────────────────────────────────
    raw: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    raw_upc: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    gtin14: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    upc_method: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    upc_warnings: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    brand: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sku: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    unit_cost: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)
    case_cost: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)
    case_pack: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    moq: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    msrp: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)
    minimum_buy_cost: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)

    # ── Pipeline output ───────────────────────────────────────────────
    # `match` holds the per-channel listing data as fetched (price, item id,
    # seller count, reviews). `channels` holds the scored economics. Keeping
    # them separate means re-scoring with new thresholds is free — no refetch.
    match: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    channels: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    verdict: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    best_channel: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    projected_monthly_profit: Mapped[Optional[float]] = mapped_column(
        Numeric, nullable=True
    )
    errors: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()")
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'matched', 'scored', 'skipped', 'error')",
            name="chk_sourcing_row_status",
        ),
        CheckConstraint(
            "verdict IS NULL OR verdict IN ('pass', 'watch', 'fail')",
            name="chk_sourcing_row_verdict",
        ),
        UniqueConstraint("list_id", "row_index", name="uq_sourcing_row_list_index"),
        # The candidates query: rows of one list, best first. Partial on
        # `verdict IS NOT NULL` keeps the index off the un-crunched majority
        # during the window when a 3,000-row list is half-scored.
        Index(
            "idx_sourcing_rows_list_rank",
            "list_id",
            text("projected_monthly_profit DESC"),
            postgresql_where=text("verdict IS NOT NULL"),
        ),
        Index(
            "idx_sourcing_rows_gtin",
            "gtin14",
            postgresql_where=text("gtin14 IS NOT NULL"),
        ),
    )


class ListingSnapshot(Base):
    """One observation of one listing. TimescaleDB hypertable on ``captured_at``.

    This is the proprietary dataset — the thing a competitor who launches later
    cannot backfill, because you cannot go back and observe last month's review
    count. Written by ``workers/sourcing_snapshots.py`` on a cron; read by
    ``demand.py`` for review velocity and ``scoring.py`` for price stability.
    """

    __tablename__ = "listing_snapshots"

    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, server_default=text("NOW()")
    )
    channel: Mapped[str] = mapped_column(Text, primary_key=True)
    listing_key: Mapped[str] = mapped_column(Text, primary_key=True)

    gtin14: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    price: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)
    review_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rating: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)
    seller_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sold_count_90d: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    bought_badge_min: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    in_stock: Mapped[Optional[bool]] = mapped_column(nullable=True)
    raw: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "channel IN ('walmart', 'ebay')", name="chk_listing_snapshot_channel"
        ),
        Index(
            "idx_listing_snapshots_gtin_time",
            "gtin14",
            text("captured_at DESC"),
            postgresql_where=text("gtin14 IS NOT NULL"),
        ),
        Index(
            "idx_listing_snapshots_key_time",
            "channel",
            "listing_key",
            text("captured_at DESC"),
        ),
    )


class BrandAccess(Base):
    """Per-brand distributor + gating ledger.

    The part software can't automate (see ``docs/SOURCING_SCANNER.md`` §7).
    ``brand_normalized`` is the lookup key — ``lower(trim(brand))`` — because
    distributor lists spell the same brand four ways across three files.
    """

    __tablename__ = "brand_access"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[str] = mapped_column(
        Text, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    brand_normalized: Mapped[str] = mapped_column(Text, nullable=False)
    brand_display: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="unknown")
    distributor_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    distributor_email: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Which channels gate this brand, e.g. ["walmart"]. Kept as an array-ish
    # JSONB rather than a column per channel so adding Amazon later is a data
    # change, not a migration.
    gated_on: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    inquiry_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()")
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('authorized', 'restricted', 'pending', 'unknown')",
            name="chk_brand_access_status",
        ),
        UniqueConstraint(
            "user_id", "brand_normalized", name="uq_brand_access_user_brand"
        ),
    )
