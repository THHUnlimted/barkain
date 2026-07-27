"""M15 Sourcing — sourcing_lists, sourcing_rows, listing_snapshots, brand_access.

Backs the wholesale sourcing scanner (docs/SOURCING_SCANNER.md): a distributor
price list is uploaded, every row is normalized + matched + priced + scored, and
the listings involved are snapshotted over time to build the demand dataset.

``listing_snapshots`` is a TimescaleDB hypertable on ``captured_at`` — same
pattern as ``price_history`` from 0001. Its PK must include the partitioning
column, hence ``(channel, listing_key, captured_at)`` (the lesson from 0002).

Mirrored on the model ``__table_args__`` so ``Base.metadata.create_all`` (the
pytest bootstrap) matches alembic. Parity pattern from 0003 / 0006 / 0009 /
0010 / 0011 / 0012.

Revision ID: 0013
Revises: 0012
"""

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS sourcing_lists (
            id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id           TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name              TEXT NOT NULL,
            source_filename   TEXT,
            supplier          TEXT,
            status            TEXT NOT NULL DEFAULT 'ingested',
            row_count         INTEGER NOT NULL DEFAULT 0,
            usable_row_count  INTEGER NOT NULL DEFAULT 0,
            scored_row_count  INTEGER NOT NULL DEFAULT 0,
            column_mapping    JSONB,
            ingest_stats      JSONB,
            thresholds        JSONB,
            verdict_summary   JSONB,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            crunched_at       TIMESTAMPTZ,
            CONSTRAINT chk_sourcing_list_status
                CHECK (status IN ('ingested', 'crunching', 'complete', 'failed'))
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_sourcing_lists_user_created
            ON sourcing_lists (user_id, created_at DESC)
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS sourcing_rows (
            id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            list_id                   UUID NOT NULL
                                      REFERENCES sourcing_lists(id) ON DELETE CASCADE,
            row_index                 INTEGER NOT NULL,
            status                    TEXT NOT NULL DEFAULT 'pending',
            raw                       JSONB,
            raw_upc                   TEXT,
            gtin14                    TEXT,
            upc_method                TEXT,
            upc_warnings              JSONB,
            description               TEXT,
            brand                     TEXT,
            sku                       TEXT,
            unit_cost                 NUMERIC,
            case_cost                 NUMERIC,
            case_pack                 INTEGER,
            moq                       INTEGER,
            msrp                      NUMERIC,
            minimum_buy_cost          NUMERIC,
            match                     JSONB,
            channels                  JSONB,
            verdict                   TEXT,
            best_channel              TEXT,
            projected_monthly_profit  NUMERIC,
            errors                    JSONB,
            created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT chk_sourcing_row_status
                CHECK (status IN ('pending', 'matched', 'scored', 'skipped', 'error')),
            CONSTRAINT chk_sourcing_row_verdict
                CHECK (verdict IS NULL OR verdict IN ('pass', 'watch', 'fail')),
            CONSTRAINT uq_sourcing_row_list_index UNIQUE (list_id, row_index)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_sourcing_rows_list_rank
            ON sourcing_rows (list_id, projected_monthly_profit DESC)
            WHERE verdict IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_sourcing_rows_gtin
            ON sourcing_rows (gtin14) WHERE gtin14 IS NOT NULL
        """
    )

    # ── listing_snapshots (TimescaleDB hypertable) ────────────────────
    # PK includes captured_at because Timescale requires the partitioning
    # column in every unique constraint (0002's lesson, learned the hard way).
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS listing_snapshots (
            captured_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            channel           TEXT NOT NULL,
            listing_key       TEXT NOT NULL,
            gtin14            TEXT,
            price             NUMERIC,
            review_count      INTEGER,
            rating            NUMERIC,
            seller_count      INTEGER,
            sold_count_90d    INTEGER,
            bought_badge_min  INTEGER,
            in_stock          BOOLEAN,
            raw               JSONB,
            CONSTRAINT chk_listing_snapshot_channel
                CHECK (channel IN ('walmart', 'ebay'))
        )
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'listing_snapshots_pkey'
            ) THEN
                ALTER TABLE listing_snapshots
                    ADD PRIMARY KEY (channel, listing_key, captured_at);
            END IF;
        END $$
        """
    )
    # `if_not_exists` keeps the migration replayable against a partially
    # applied DB; `migrate_data` moves any rows written before the conversion.
    op.execute(
        """
        SELECT create_hypertable(
            'listing_snapshots', 'captured_at',
            if_not_exists => TRUE, migrate_data => TRUE
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_listing_snapshots_gtin_time
            ON listing_snapshots (gtin14, captured_at DESC)
            WHERE gtin14 IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_listing_snapshots_key_time
            ON listing_snapshots (channel, listing_key, captured_at DESC)
        """
    )

    # ── forecast vs actual ────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS sourcing_forecasts (
            id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id                  TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            row_id                   UUID REFERENCES sourcing_rows(id) ON DELETE SET NULL,
            sku                      TEXT NOT NULL,
            gtin14                   TEXT,
            channel                  TEXT NOT NULL,
            category                 TEXT,
            predicted_monthly_units  NUMERIC,
            predicted_net_per_unit   NUMERIC,
            signal_tier              TEXT,
            fee_schedule_version     TEXT,
            thresholds               JSONB,
            predicted_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT chk_forecast_channel
                CHECK (channel IN ('walmart', 'ebay', 'amazon'))
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_sourcing_forecasts_sku
            ON sourcing_forecasts (user_id, sku, channel, predicted_at DESC)
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS sourcing_actuals (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id          TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            sku              TEXT NOT NULL,
            gtin14           TEXT,
            channel          TEXT NOT NULL,
            window_start     TIMESTAMPTZ NOT NULL,
            window_end       TIMESTAMPTZ NOT NULL,
            units_sold       INTEGER NOT NULL DEFAULT 0,
            gross_revenue    NUMERIC,
            total_fees       NUMERIC,
            net_proceeds     NUMERIC,
            impressions      INTEGER,
            listing_views    INTEGER,
            conversion_rate  NUMERIC,
            source           TEXT,
            raw              JSONB,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT chk_actual_channel
                CHECK (channel IN ('walmart', 'ebay', 'amazon')),
            CONSTRAINT uq_sourcing_actual_window
                UNIQUE (user_id, sku, channel, window_start, window_end)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_sourcing_actuals_sku
            ON sourcing_actuals (user_id, sku, channel, window_end DESC)
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS brand_access (
            id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id            TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            brand_normalized   TEXT NOT NULL,
            brand_display      TEXT,
            status             TEXT NOT NULL DEFAULT 'unknown',
            distributor_name   TEXT,
            distributor_email  TEXT,
            gated_on           JSONB,
            notes              TEXT,
            inquiry_sent_at    TIMESTAMPTZ,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT chk_brand_access_status
                CHECK (status IN ('authorized', 'restricted', 'pending', 'unknown')),
            CONSTRAINT uq_brand_access_user_brand UNIQUE (user_id, brand_normalized)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS brand_access")
    op.execute("DROP TABLE IF EXISTS sourcing_actuals")
    op.execute("DROP TABLE IF EXISTS sourcing_forecasts")
    op.execute("DROP TABLE IF EXISTS listing_snapshots")
    op.execute("DROP TABLE IF EXISTS sourcing_rows")
    op.execute("DROP TABLE IF EXISTS sourcing_lists")
