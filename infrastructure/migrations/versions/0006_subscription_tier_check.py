"""subscription_tier CHECK constraint.

Step 2i-b: adds a database-level guard that ``users.subscription_tier`` only
ever holds the values the rate-limit and billing code understand
(``'free'`` or ``'pro'``). Until now the column was an unconstrained TEXT
field with a server default of ``'free'``; only ``BillingService`` writes
to it, but the DB itself had no defense if a future caller (or a manual
psql session) tried to set ``'enterprise'``, ``'trial'``, ``NULL``-via-
type-coercion bug, etc.

Idempotent via the standard ``DO $$ ... END $$`` PG block so dev databases
that already have a constraint with the same name don't blow up the
migration. Mirrored on ``User.__table_args__`` (``app/core_models.py``) so
``Base.metadata.create_all`` produces the same schema the test fixtures
use — same parity pattern as Step 2f migration 0004 and Step 2h migration
0005.

Revision ID: 0006
Revises: 0005
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'chk_subscription_tier'
            ) THEN
                ALTER TABLE users
                ADD CONSTRAINT chk_subscription_tier
                CHECK (subscription_tier IN ('free', 'pro'));
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS chk_subscription_tier")
