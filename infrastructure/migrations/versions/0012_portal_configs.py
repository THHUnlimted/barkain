"""Create ``portal_configs`` — display + promo + alerting state for shopping portals.

Step 3g splits portal data into three layers:
    1. Secrets (referral URLs, FlexOffers credentials) → ``.env``.
    2. Display + promo metadata (this table) — changes on promo cadence,
       not on credential lifecycle. Edited via ``scripts/seed_portal_configs.py``
       or a future admin script.
    3. Stable constants (display name, logo URL) → Python module constants.

The alerting columns (``consecutive_failures``, ``last_alerted_at``) live
here too because they're the cheapest place to track per-portal worker
health: the worker already touches one row per portal per run, so writing
the counter is a free side effect of the upsert path.

Five rows seeded by ``scripts/seed_portal_configs.py``: rakuten /
topcashback / befrugal active, chase_shop / capital_one_shopping inactive
(deferred — auth-gated portals not in scope for 3g).

Mirrored on ``PortalConfig.__table_args__`` so ``Base.metadata.create_all``
(pytest bootstrap) matches alembic. Parity pattern from 0003 / 0006 /
0009 / 0010 / 0011.

Revision ID: 0012
Revises: 0011
"""

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS portal_configs (
            id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            portal_source         TEXT NOT NULL UNIQUE,
            display_name          TEXT NOT NULL,
            homepage_url          TEXT NOT NULL,
            signup_promo_amount   NUMERIC,
            signup_promo_copy     TEXT,
            signup_promo_ends_at  TIMESTAMPTZ,
            is_active             BOOLEAN NOT NULL DEFAULT TRUE,
            consecutive_failures  INTEGER NOT NULL DEFAULT 0,
            last_alerted_at       TIMESTAMPTZ,
            created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_portal_configs_active "
        "ON portal_configs (is_active) WHERE is_active = TRUE"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS portal_configs")
