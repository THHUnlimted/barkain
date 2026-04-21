"""Add `is_young_adult` column to user_discount_profiles.

Benefits Expansion: introduces the 18–24 eligibility axis used by Amazon
Prime Young Adult and any future age-based brand programs. Separate from
`is_student` — GRADLiFE/GradBeans recent-grad coverage still rides the
existing student flag per Barkain policy, so this column exclusively
represents age, not enrollment.

Idempotent via `ADD COLUMN IF NOT EXISTS`. Mirrored on
``UserDiscountProfile.is_young_adult`` so ``Base.metadata.create_all``
(used by the pytest schema bootstrap) matches alembic — parity pattern
from 0003 / 0009.

``downgrade()`` drops the column.

Revision ID: 0010
Revises: 0009
"""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE user_discount_profiles
        ADD COLUMN IF NOT EXISTS is_young_adult BOOLEAN NOT NULL DEFAULT false
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE user_discount_profiles DROP COLUMN IF EXISTS is_young_adult"
    )
