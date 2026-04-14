"""Add is_government column to user_discount_profiles.

Step 2d: extends the identity profile to cover government employee discount
programs (Samsung, Dell, HP, LG, Microsoft all offer government tiers).
The other 15 identity booleans were created in 0001; this adds the 16th
so the full 9-group onboarding flow has schema backing.

Revision ID: 0003
Revises: 0002
"""

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_discount_profiles",
        sa.Column(
            "is_government",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("user_discount_profiles", "is_government")
