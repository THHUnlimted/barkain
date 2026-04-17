"""pg_trgm extension + GIN index on products.name for text search.

Step 3a: ships the Product Text Search feature. The ``/api/v1/products/search``
endpoint runs fuzzy matches on ``products.name`` via the pg_trgm similarity
operator (``%``) and falls back to Gemini only when the DB has too few
high-confidence candidates. The GIN index makes the trigram lookup scale past
a few thousand products — at launch the table is small enough that a seq scan
would work, but we add the index now so search latency stays sub-10ms as the
cache warms.

Idempotent via the standard ``DO $$ ... END $$`` PG block and ``CREATE ...
IF NOT EXISTS`` guards so dev databases that partially ran this migration
don't blow up on rerun. Mirrored on ``Product.__table_args__`` in
``app/core_models.py`` so ``Base.metadata.create_all`` (used by the test
fixtures) produces the same schema — same parity pattern as migrations 0004,
0005, 0006.

``downgrade()`` drops the INDEX only, NOT the extension — other indexes may
depend on pg_trgm in future migrations, and dropping the extension would
cascade-drop them.

Revision ID: 0007
Revises: 0006
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes WHERE indexname = 'idx_products_name_trgm'
            ) THEN
                CREATE INDEX idx_products_name_trgm
                ON products USING gin (name gin_trgm_ops);
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_products_name_trgm")
    # Intentionally NOT dropping the pg_trgm extension — other indexes may
    # depend on it in future migrations.
