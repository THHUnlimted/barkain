"""Card catalog unique index on (card_issuer, card_product).

Step 2f (PF-1): migration 0001 doesn't include the unique index that
`scripts/seed_card_catalog.py` relies on for its ON CONFLICT upsert. The
seed script previously lazy-created the index at runtime via
`CREATE UNIQUE INDEX IF NOT EXISTS`. This migration takes ownership so
schema management stays in Alembic.

Idempotent on upgrade via ``IF NOT EXISTS`` because existing dev and prod
DBs already have the index from the old seed-script path. Downgrade uses
``IF EXISTS`` for symmetry. The index is ALSO declared on the
``CardRewardProgram`` model's ``__table_args__`` so the test DB fixture
(``Base.metadata.create_all``) gets it on fresh schemas without running
alembic — the two definitions are identical and kept in sync.

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_card_reward_programs_product "
        "ON card_reward_programs (card_issuer, card_product)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_card_reward_programs_product")
