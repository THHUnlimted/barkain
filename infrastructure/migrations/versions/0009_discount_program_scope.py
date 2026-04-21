"""Add `scope` column to discount_programs.

3f-hotfix: Prime Student was seeded as a 50 % percentage discount, but
that 50 % applies to the Prime membership fee ($7.99/mo), NOT to the
product price. Without a scope marker, identity-savings math multiplied
50 % against a MacBook and claimed "$500 savings" — false.

`scope` values:
  - 'product'        — percentage applies to the product's sale price (default)
  - 'membership_fee' — applies to an ancillary membership fee, not the product
  - 'shipping'       — reserved for future shipping-discount programs

Only Prime Student flips to `membership_fee` today; all 51 identity
programs stay `product` and retain the current estimated-savings math.

Idempotent via `ADD COLUMN IF NOT EXISTS`. Mirrored on
``DiscountProgram.__table_args__`` so ``Base.metadata.create_all``
(used by the pytest schema bootstrap) matches alembic — parity pattern
from 0004/0005/0006/0007/0008.

``downgrade()`` drops the column.

Revision ID: 0009
Revises: 0008
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE discount_programs
        ADD COLUMN IF NOT EXISTS scope TEXT NOT NULL DEFAULT 'product'
        """
    )
    op.execute(
        """
        ALTER TABLE discount_programs
        DROP CONSTRAINT IF EXISTS chk_discount_programs_scope
        """
    )
    op.execute(
        """
        ALTER TABLE discount_programs
        ADD CONSTRAINT chk_discount_programs_scope
        CHECK (scope IN ('product', 'membership_fee', 'shipping'))
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE discount_programs "
        "DROP CONSTRAINT IF EXISTS chk_discount_programs_scope"
    )
    op.execute("ALTER TABLE discount_programs DROP COLUMN IF EXISTS scope")
