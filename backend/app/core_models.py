import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


# MARK: - Users

class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    email: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    display_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    subscription_tier: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="free"
    )
    subscription_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    onboarding_completed: Mapped[bool] = mapped_column(
        Boolean, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()")
    )


# MARK: - Retailers

class Retailer(Base):
    __tablename__ = "retailers"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    logo_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extraction_method: Mapped[str] = mapped_column(Text, nullable=False)
    supports_coupons: Mapped[bool] = mapped_column(
        Boolean, server_default="false"
    )
    supports_identity: Mapped[bool] = mapped_column(
        Boolean, server_default="false"
    )
    supports_portals: Mapped[bool] = mapped_column(
        Boolean, server_default="false"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()")
    )


# MARK: - Retailer Health

class RetailerHealth(Base):
    __tablename__ = "retailer_health"

    retailer_id: Mapped[str] = mapped_column(
        Text, ForeignKey("retailers.id"), primary_key=True
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="healthy"
    )
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    last_successful_extract: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_failed_extract: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_healed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    heal_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    max_heal_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="3"
    )
    script_version: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="0.0.0"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )


# MARK: - Watchdog Events

class WatchdogEvent(Base):
    __tablename__ = "watchdog_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    retailer_id: Mapped[str] = mapped_column(
        Text, ForeignKey("retailers.id"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    diagnosis: Mapped[str] = mapped_column(Text, nullable=False)
    action_taken: Mapped[str] = mapped_column(Text, nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    old_selectors: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    new_selectors: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    llm_model: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    llm_tokens_used: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error_details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )


# MARK: - Prediction Cache

class PredictionCache(Base):
    __tablename__ = "prediction_cache"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id"), nullable=False
    )
    prediction_type: Mapped[str] = mapped_column(Text, nullable=False)
    result: Mapped[dict] = mapped_column(JSONB, nullable=False)
    model_version: Mapped[str] = mapped_column(Text, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        {"comment": "Cached price prediction results"},
    )
