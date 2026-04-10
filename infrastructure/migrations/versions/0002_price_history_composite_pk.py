"""Add composite PK (product_id, retailer_id, time) to price_history.

Resolves D4: Single-column PK on `time` caused collision risk during batch inserts.
TimescaleDB requires the partitioning column (`time`) in any unique constraint,
so the composite PK includes it.

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # TimescaleDB hypertables support ALTER TABLE for PK changes
    # as long as the partitioning column (time) is included.
    op.execute("ALTER TABLE price_history DROP CONSTRAINT IF EXISTS price_history_pkey")
    op.execute(
        "ALTER TABLE price_history ADD PRIMARY KEY (product_id, retailer_id, time)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE price_history DROP CONSTRAINT IF EXISTS price_history_pkey")
    op.execute("ALTER TABLE price_history ADD PRIMARY KEY (time)")
