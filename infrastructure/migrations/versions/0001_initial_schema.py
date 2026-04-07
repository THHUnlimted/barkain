"""Initial schema — all 21 tables

Revision ID: 0001
Revises:
Create Date: 2026-04-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # TimescaleDB extension
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE")

    # ── 1. users ──────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("email", sa.Text, nullable=True),
        sa.Column("display_name", sa.Text, nullable=True),
        sa.Column(
            "subscription_tier", sa.Text, nullable=False, server_default="free"
        ),
        sa.Column("subscription_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("onboarding_completed", sa.Boolean, server_default="false"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")
        ),
    )

    # ── 2. retailers ──────────────────────────────────────────────
    op.create_table(
        "retailers",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("display_name", sa.Text, nullable=False),
        sa.Column("base_url", sa.Text, nullable=False),
        sa.Column("logo_url", sa.Text, nullable=True),
        sa.Column("extraction_method", sa.Text, nullable=False),
        sa.Column("supports_coupons", sa.Boolean, server_default="false"),
        sa.Column("supports_identity", sa.Boolean, server_default="false"),
        sa.Column("supports_portals", sa.Boolean, server_default="false"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")
        ),
    )

    # ── 3. products ───────────────────────────────────────────────
    op.create_table(
        "products",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("upc", sa.Text, unique=True, nullable=True),
        sa.Column("asin", sa.Text, nullable=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("brand", sa.Text, nullable=True),
        sa.Column("category", sa.Text, nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("image_url", sa.Text, nullable=True),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("source_raw", JSONB, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")
        ),
    )
    op.create_index(
        "idx_products_upc",
        "products",
        ["upc"],
        postgresql_where=sa.text("upc IS NOT NULL"),
    )
    op.create_index(
        "idx_products_asin",
        "products",
        ["asin"],
        postgresql_where=sa.text("asin IS NOT NULL"),
    )
    op.create_index(
        "idx_products_category",
        "products",
        ["category"],
        postgresql_where=sa.text("category IS NOT NULL"),
    )

    # ── 4. prices ─────────────────────────────────────────────────
    op.create_table(
        "prices",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "product_id",
            UUID(as_uuid=True),
            sa.ForeignKey("products.id"),
            nullable=False,
        ),
        sa.Column(
            "retailer_id", sa.Text, sa.ForeignKey("retailers.id"), nullable=False
        ),
        sa.Column("price", sa.Numeric, nullable=False),
        sa.Column("original_price", sa.Numeric, nullable=True),
        sa.Column("currency", sa.Text, nullable=False, server_default="USD"),
        sa.Column("url", sa.Text, nullable=True),
        sa.Column("affiliate_url", sa.Text, nullable=True),
        sa.Column("condition", sa.Text, nullable=False, server_default="new"),
        sa.Column("is_available", sa.Boolean, server_default="true"),
        sa.Column("is_on_sale", sa.Boolean, server_default="false"),
        sa.Column(
            "last_checked",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")
        ),
        sa.UniqueConstraint("product_id", "retailer_id", "condition"),
    )
    op.create_index("idx_prices_product", "prices", ["product_id"])
    op.create_index("idx_prices_retailer", "prices", ["retailer_id"])
    op.create_index("idx_prices_last_checked", "prices", ["last_checked"])

    # ── 5. price_history (TimescaleDB hypertable) ─────────────────
    op.create_table(
        "price_history",
        sa.Column(
            "time",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("product_id", UUID(as_uuid=True), nullable=False),
        sa.Column("retailer_id", sa.Text, nullable=False),
        sa.Column("price", sa.Numeric, nullable=False),
        sa.Column("original_price", sa.Numeric, nullable=True),
        sa.Column("condition", sa.Text, nullable=False, server_default="new"),
        sa.Column("is_available", sa.Boolean, server_default="true"),
        sa.Column("source", sa.Text, nullable=False, server_default="api"),
    )
    op.execute("SELECT create_hypertable('price_history', 'time')")
    op.create_index(
        "idx_price_history_product_time",
        "price_history",
        ["product_id", sa.text("time DESC")],
    )
    op.create_index(
        "idx_price_history_retailer_time",
        "price_history",
        ["retailer_id", sa.text("time DESC")],
    )

    # ── 6. user_discount_profiles ─────────────────────────────────
    op.create_table(
        "user_discount_profiles",
        sa.Column(
            "user_id", sa.Text, sa.ForeignKey("users.id"), primary_key=True
        ),
        sa.Column("is_military", sa.Boolean, server_default="false"),
        sa.Column("is_veteran", sa.Boolean, server_default="false"),
        sa.Column("is_student", sa.Boolean, server_default="false"),
        sa.Column("is_teacher", sa.Boolean, server_default="false"),
        sa.Column("is_first_responder", sa.Boolean, server_default="false"),
        sa.Column("is_nurse", sa.Boolean, server_default="false"),
        sa.Column("is_healthcare_worker", sa.Boolean, server_default="false"),
        sa.Column("is_senior", sa.Boolean, server_default="false"),
        sa.Column("is_aaa_member", sa.Boolean, server_default="false"),
        sa.Column("is_aarp_member", sa.Boolean, server_default="false"),
        sa.Column("email_domain", sa.Text, nullable=True),
        sa.Column("employer", sa.Text, nullable=True),
        sa.Column("alumni_school", sa.Text, nullable=True),
        sa.Column("union_membership", sa.Text, nullable=True),
        sa.Column("is_costco_member", sa.Boolean, server_default="false"),
        sa.Column("is_prime_member", sa.Boolean, server_default="false"),
        sa.Column("is_sams_member", sa.Boolean, server_default="false"),
        sa.Column("id_me_verified", sa.Boolean, server_default="false"),
        sa.Column("sheer_id_verified", sa.Boolean, server_default="false"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")
        ),
    )

    # ── 7. discount_programs ──────────────────────────────────────
    op.create_table(
        "discount_programs",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "retailer_id", sa.Text, sa.ForeignKey("retailers.id"), nullable=False
        ),
        sa.Column("program_name", sa.Text, nullable=False),
        sa.Column("program_type", sa.Text, nullable=False),
        sa.Column("eligibility_type", sa.Text, nullable=True),
        sa.Column("discount_type", sa.Text, nullable=False),
        sa.Column("discount_value", sa.Numeric, nullable=True),
        sa.Column("discount_max_value", sa.Numeric, nullable=True),
        sa.Column("discount_details", sa.Text, nullable=True),
        sa.Column("applies_to_categories", ARRAY(sa.Text), nullable=True),
        sa.Column("excluded_categories", ARRAY(sa.Text), nullable=True),
        sa.Column("excluded_brands", ARRAY(sa.Text), nullable=True),
        sa.Column("minimum_purchase", sa.Numeric, nullable=True),
        sa.Column("stackable", sa.Boolean, server_default="false"),
        sa.Column("stacks_with", ARRAY(sa.Text), nullable=True),
        sa.Column("verification_method", sa.Text, nullable=True),
        sa.Column("verification_url", sa.Text, nullable=True),
        sa.Column("url", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("last_verified", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_verified_by", sa.Text, nullable=True),
        sa.Column("effective_from", sa.Date, nullable=True),
        sa.Column("effective_until", sa.Date, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")
        ),
        sa.UniqueConstraint("retailer_id", "program_name", "eligibility_type"),
    )
    op.create_index(
        "idx_discount_programs_lookup",
        "discount_programs",
        ["retailer_id", "program_type", "is_active"],
        postgresql_where=sa.text("is_active = true"),
    )
    op.create_index(
        "idx_discount_programs_eligibility",
        "discount_programs",
        ["eligibility_type", "is_active"],
        postgresql_where=sa.text("is_active = true"),
    )

    # ── 8. card_reward_programs ───────────────────────────────────
    op.create_table(
        "card_reward_programs",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("card_network", sa.Text, nullable=False),
        sa.Column("card_issuer", sa.Text, nullable=False),
        sa.Column("card_product", sa.Text, nullable=False),
        sa.Column("card_display_name", sa.Text, nullable=False),
        sa.Column("base_reward_rate", sa.Numeric, nullable=False),
        sa.Column("reward_currency", sa.Text, nullable=False),
        sa.Column("point_value_cents", sa.Numeric, nullable=True),
        sa.Column(
            "category_bonuses",
            JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("has_shopping_portal", sa.Boolean, server_default="false"),
        sa.Column("portal_url", sa.Text, nullable=True),
        sa.Column("portal_base_rate", sa.Numeric, nullable=True),
        sa.Column("annual_fee", sa.Numeric, server_default="0"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")
        ),
    )

    # ── 9. rotating_categories ────────────────────────────────────
    op.create_table(
        "rotating_categories",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "card_program_id",
            UUID(as_uuid=True),
            sa.ForeignKey("card_reward_programs.id"),
            nullable=False,
        ),
        sa.Column("quarter", sa.Text, nullable=False),
        sa.Column("categories", ARRAY(sa.Text), nullable=False),
        sa.Column("bonus_rate", sa.Numeric, nullable=False),
        sa.Column("activation_required", sa.Boolean, server_default="true"),
        sa.Column("activation_url", sa.Text, nullable=True),
        sa.Column("cap_amount", sa.Numeric, nullable=True),
        sa.Column("effective_from", sa.Date, nullable=False),
        sa.Column("effective_until", sa.Date, nullable=False),
        sa.Column("last_verified", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("card_program_id", "quarter"),
    )

    # ── 10. user_cards ────────────────────────────────────────────
    op.create_table(
        "user_cards",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", sa.Text, sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "card_program_id",
            UUID(as_uuid=True),
            sa.ForeignKey("card_reward_programs.id"),
            nullable=False,
        ),
        sa.Column("nickname", sa.Text, nullable=True),
        sa.Column("is_preferred", sa.Boolean, server_default="false"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column(
            "added_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")
        ),
        sa.UniqueConstraint("user_id", "card_program_id"),
    )
    op.create_index(
        "idx_user_cards_user",
        "user_cards",
        ["user_id"],
        postgresql_where=sa.text("is_active = true"),
    )

    # ── 11. user_category_selections ──────────────────────────────
    op.create_table(
        "user_category_selections",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", sa.Text, sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "card_program_id",
            UUID(as_uuid=True),
            sa.ForeignKey("card_reward_programs.id"),
            nullable=False,
        ),
        sa.Column("selected_categories", ARRAY(sa.Text), nullable=False),
        sa.Column("effective_from", sa.Date, nullable=False),
        sa.Column("effective_until", sa.Date, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")
        ),
        sa.UniqueConstraint("user_id", "card_program_id", "effective_from"),
    )

    # ── 12. portal_bonuses (with GENERATED column is_elevated) ────
    op.execute(
        """
        CREATE TABLE portal_bonuses (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            portal_source TEXT NOT NULL,
            retailer_id TEXT NOT NULL REFERENCES retailers(id),
            bonus_type TEXT NOT NULL,
            bonus_value NUMERIC NOT NULL,
            normal_value NUMERIC,
            is_elevated BOOLEAN GENERATED ALWAYS AS (
                bonus_value > COALESCE(normal_value, 0) * 1.5
            ) STORED,
            effective_from TIMESTAMPTZ NOT NULL,
            effective_until TIMESTAMPTZ,
            last_verified TIMESTAMPTZ,
            verified_by TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """
    )
    op.create_index(
        "idx_portal_bonuses_active",
        "portal_bonuses",
        ["retailer_id", "effective_until"],
    )

    # ── 13. listings ──────────────────────────────────────────────
    op.create_table(
        "listings",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "product_id",
            UUID(as_uuid=True),
            sa.ForeignKey("products.id"),
            nullable=False,
        ),
        sa.Column(
            "retailer_id", sa.Text, sa.ForeignKey("retailers.id"), nullable=False
        ),
        sa.Column("external_id", sa.Text, nullable=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("price", sa.Numeric, nullable=False),
        sa.Column("currency", sa.Text, nullable=False, server_default="USD"),
        sa.Column("condition", sa.Text, nullable=False),
        sa.Column("seller_name", sa.Text, nullable=True),
        sa.Column("seller_rating", sa.Numeric, nullable=True),
        sa.Column("seller_reviews", sa.Integer, nullable=True),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("image_url", sa.Text, nullable=True),
        sa.Column("shipping_cost", sa.Numeric, nullable=True),
        sa.Column("returns_accepted", sa.Boolean, nullable=True),
        sa.Column("warranty_info", sa.Text, nullable=True),
        sa.Column("listing_age_days", sa.Integer, nullable=True),
        sa.Column("quality_score", sa.Numeric, nullable=True),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("retailer_id", "external_id"),
    )
    op.create_index(
        "idx_listings_product",
        "listings",
        ["product_id", "is_active"],
        postgresql_where=sa.text("is_active = true"),
    )

    # ── 14. coupon_cache (with GENERATED column confidence_score) ─
    op.execute(
        """
        CREATE TABLE coupon_cache (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            retailer_id TEXT NOT NULL REFERENCES retailers(id),
            code TEXT NOT NULL,
            description TEXT,
            discount_type TEXT NOT NULL,
            discount_value NUMERIC,
            minimum_purchase NUMERIC,
            applies_to TEXT[],
            source TEXT NOT NULL,
            validation_status TEXT NOT NULL DEFAULT 'unvalidated',
            last_validated TIMESTAMPTZ,
            validated_by TEXT,
            validation_notes TEXT,
            success_count INTEGER DEFAULT 0,
            failure_count INTEGER DEFAULT 0,
            confidence_score NUMERIC GENERATED ALWAYS AS (
                CASE WHEN (success_count + failure_count) = 0 THEN 0.5
                ELSE success_count::numeric / (success_count + failure_count)
                END
            ) STORED,
            discovered_at TIMESTAMPTZ DEFAULT NOW(),
            expires_at TIMESTAMPTZ,
            is_active BOOLEAN DEFAULT true,
            UNIQUE (retailer_id, code)
        )
        """
    )

    # ── 15. receipts ──────────────────────────────────────────────
    op.create_table(
        "receipts",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", sa.Text, sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "retailer_id", sa.Text, sa.ForeignKey("retailers.id"), nullable=True
        ),
        sa.Column("store_name", sa.Text, nullable=True),
        sa.Column("receipt_date", sa.Date, nullable=True),
        sa.Column("subtotal", sa.Numeric, nullable=True),
        sa.Column("tax", sa.Numeric, nullable=True),
        sa.Column("total", sa.Numeric, nullable=True),
        sa.Column("currency", sa.Text, nullable=False, server_default="USD"),
        sa.Column("ocr_text", sa.Text, nullable=True),
        sa.Column("savings_amount", sa.Numeric, nullable=True),
        sa.Column(
            "scanned_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")
        ),
    )
    op.create_index(
        "idx_receipts_user",
        "receipts",
        ["user_id", sa.text("scanned_at DESC")],
    )

    # ── 16. receipt_items ─────────────────────────────────────────
    op.create_table(
        "receipt_items",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "receipt_id",
            UUID(as_uuid=True),
            sa.ForeignKey("receipts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "product_id",
            UUID(as_uuid=True),
            sa.ForeignKey("products.id"),
            nullable=True,
        ),
        sa.Column("item_name", sa.Text, nullable=False),
        sa.Column("quantity", sa.Integer, server_default="1"),
        sa.Column("unit_price", sa.Numeric, nullable=False),
        sa.Column("total_price", sa.Numeric, nullable=False),
        sa.Column("best_alt_price", sa.Numeric, nullable=True),
        sa.Column("best_alt_retailer", sa.Text, nullable=True),
        sa.Column("savings", sa.Numeric, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")
        ),
    )
    op.create_index("idx_receipt_items_receipt", "receipt_items", ["receipt_id"])
    op.create_index(
        "idx_receipt_items_product",
        "receipt_items",
        ["product_id"],
        postgresql_where=sa.text("product_id IS NOT NULL"),
    )

    # ── 17. watched_items ─────────────────────────────────────────
    op.create_table(
        "watched_items",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", sa.Text, sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "product_id",
            UUID(as_uuid=True),
            sa.ForeignKey("products.id"),
            nullable=False,
        ),
        sa.Column("target_price", sa.Numeric, nullable=True),
        sa.Column("watch_until", sa.Date, nullable=True),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("last_notified", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")
        ),
        sa.UniqueConstraint("user_id", "product_id"),
    )
    op.create_index(
        "idx_watched_items_active",
        "watched_items",
        ["product_id", "is_active"],
        postgresql_where=sa.text("is_active = true"),
    )

    # ── 18. affiliate_clicks ──────────────────────────────────────
    op.create_table(
        "affiliate_clicks",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", sa.Text, sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "product_id",
            UUID(as_uuid=True),
            sa.ForeignKey("products.id"),
            nullable=True,
        ),
        sa.Column(
            "retailer_id", sa.Text, sa.ForeignKey("retailers.id"), nullable=False
        ),
        sa.Column("affiliate_network", sa.Text, nullable=False),
        sa.Column("click_url", sa.Text, nullable=False),
        sa.Column(
            "clicked_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("converted", sa.Boolean, nullable=True),
        sa.Column("commission", sa.Numeric, nullable=True),
        sa.Column("conversion_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_affiliate_clicks_user",
        "affiliate_clicks",
        ["user_id", sa.text("clicked_at DESC")],
    )
    op.create_index(
        "idx_affiliate_clicks_retailer",
        "affiliate_clicks",
        ["retailer_id", sa.text("clicked_at DESC")],
    )

    # ── 19. prediction_cache ──────────────────────────────────────
    op.create_table(
        "prediction_cache",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "product_id",
            UUID(as_uuid=True),
            sa.ForeignKey("products.id"),
            nullable=False,
        ),
        sa.Column("prediction_type", sa.Text, nullable=False),
        sa.Column("result", JSONB, nullable=False),
        sa.Column("model_version", sa.Text, nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("product_id", "prediction_type"),
    )
    op.create_index(
        "idx_prediction_cache_expiry",
        "prediction_cache",
        ["expires_at"],
    )

    # ── 20. retailer_health ───────────────────────────────────────
    op.create_table(
        "retailer_health",
        sa.Column(
            "retailer_id",
            sa.Text,
            sa.ForeignKey("retailers.id"),
            primary_key=True,
        ),
        sa.Column("status", sa.Text, nullable=False, server_default="healthy"),
        sa.Column(
            "consecutive_failures", sa.Integer, nullable=False, server_default="0"
        ),
        sa.Column(
            "last_successful_extract", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("last_failed_extract", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_healed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heal_attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("max_heal_attempts", sa.Integer, nullable=False, server_default="3"),
        sa.Column(
            "script_version", sa.Text, nullable=False, server_default="0.0.0"
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    # ── 21. watchdog_events ───────────────────────────────────────
    op.create_table(
        "watchdog_events",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "retailer_id", sa.Text, sa.ForeignKey("retailers.id"), nullable=False
        ),
        sa.Column("event_type", sa.Text, nullable=False),
        sa.Column("diagnosis", sa.Text, nullable=False),
        sa.Column("action_taken", sa.Text, nullable=False),
        sa.Column("success", sa.Boolean, nullable=False),
        sa.Column("old_selectors", JSONB, nullable=True),
        sa.Column("new_selectors", JSONB, nullable=True),
        sa.Column("llm_model", sa.Text, nullable=True),
        sa.Column("llm_tokens_used", sa.Integer, nullable=True),
        sa.Column("error_details", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "idx_watchdog_retailer_time",
        "watchdog_events",
        ["retailer_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_table("watchdog_events")
    op.drop_table("retailer_health")
    op.drop_table("prediction_cache")
    op.drop_table("affiliate_clicks")
    op.drop_table("watched_items")
    op.drop_table("receipt_items")
    op.drop_table("receipts")
    op.drop_table("coupon_cache")
    op.drop_table("listings")
    op.drop_table("portal_bonuses")
    op.drop_table("user_category_selections")
    op.drop_table("user_cards")
    op.drop_table("rotating_categories")
    op.drop_table("card_reward_programs")
    op.drop_table("discount_programs")
    op.drop_table("user_discount_profiles")
    op.drop_table("price_history")
    op.drop_table("prices")
    op.drop_table("products")
    op.drop_table("retailers")
    op.drop_table("users")
    op.execute("DROP EXTENSION IF EXISTS timescaledb CASCADE")
