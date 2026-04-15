"""Background worker constraints.

Step 2h: adds two things the Step 2h workers need.

1. ``portal_bonuses`` gets a unique index on ``(portal_source, retailer_id)``
   so the portal rate scraping worker can upsert via a standard SELECT /
   INSERT / UPDATE flow without racing on duplicates. Migration 0001 ships
   no such index. Idempotent via ``IF NOT EXISTS`` (matches the 0004
   pattern) so existing dev databases upgrade cleanly.

2. ``discount_programs`` gets a ``consecutive_failures`` INTEGER column
   (NOT NULL, default 0). The discount verification worker increments the
   counter on hard failures (HTTP 4xx/5xx/network) and deactivates the
   program once it hits
   ``settings.DISCOUNT_VERIFICATION_FAILURE_THRESHOLD`` (default 3).
   ``server_default="0"`` ensures existing rows back-fill without a data
   migration; the SQLAlchemy model also sets ``default=0`` so freshly
   constructed in-memory instances don't hold ``None`` before flush.

Both definitions are mirrored on the ``PortalBonus`` and ``DiscountProgram``
model ``__table_args__`` / column definitions so ``Base.metadata.create_all``
produces the same schema the test fixtures use (same pattern as Step 2f
migration 0004).

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_portal_bonuses_upsert "
        "ON portal_bonuses (portal_source, retailer_id)"
    )
    op.add_column(
        "discount_programs",
        sa.Column(
            "consecutive_failures",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("discount_programs", "consecutive_failures")
    op.execute("DROP INDEX IF EXISTS idx_portal_bonuses_upsert")
