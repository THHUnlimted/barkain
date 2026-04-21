"""Add JSONB `metadata` column to affiliate_clicks.

Step 3f: the purchase interstitial records whether the user bypassed
the card activation reminder via `activation_skipped`. We persist this
into a JSONB column so future flags (e.g., portal guidance engagement
in 3g) land in the same bag without a migration per flag.

Idempotent via `ADD COLUMN IF NOT EXISTS`. Mirrored on
``AffiliateClick.__table_args__``-adjacent column definition in
``modules/m12_affiliate/models.py`` so ``Base.metadata.create_all``
(used by the pytest schema bootstrap) matches alembic's view of the
world — parity pattern from 0004/0005/0006/0007.

``downgrade()`` drops the column.

Revision ID: 0008
Revises: 0007
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE affiliate_clicks
        ADD COLUMN IF NOT EXISTS metadata JSONB
        NOT NULL DEFAULT '{}'::jsonb
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE affiliate_clicks DROP COLUMN IF EXISTS metadata")
