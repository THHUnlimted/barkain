"""Create ``fb_marketplace_locations`` — cache of (city, state) → FB numeric Page ID.

Facebook Marketplace's search URL takes a numeric location ID
(``/marketplace/112111905481230/search?...``). The slug form we used
previously (``/marketplace/brooklyn/``) silently redirects to a generic
category page when the slug doesn't match FB's canonical list, and the
proxy's egress IP then decides the geo — which is how a NY-based user
saw California listings. This table caches the resolved numeric ID per
(country, state_code, normalized_city) so we only hit the live search-
engine resolver on first lookup; subsequent requests short-circuit.

Rows come from two sources:
    - bulk seed (``scripts/seed_fb_marketplace_locations.py`` — top US metros)
    - on-demand resolver called from ``POST /api/v1/fb-location/resolve``

Tombstones (``location_id IS NULL``, ``source = 'unresolved'``) stop
retry storms for genuinely FB-less places (unincorporated towns, typos)
for 30 days before the weekly verifier gets a chance to re-try.

Mirrored on ``FbMarketplaceLocation.__table_args__`` so ``Base.metadata.
create_all`` (pytest bootstrap) matches alembic. Parity pattern from
0003 / 0006 / 0009 / 0010.

Revision ID: 0011
Revises: 0010
"""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS fb_marketplace_locations (
            id                  SERIAL PRIMARY KEY,
            country             TEXT NOT NULL DEFAULT 'US',
            state_code          TEXT NOT NULL,
            city                TEXT NOT NULL,
            location_id         BIGINT,
            canonical_name      TEXT,
            verified            BOOLEAN NOT NULL DEFAULT FALSE,
            source              TEXT NOT NULL,
            resolved_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_verified_at    TIMESTAMPTZ,
            CONSTRAINT uq_fb_marketplace_location
                UNIQUE (country, state_code, city),
            CONSTRAINT chk_fb_marketplace_location_state
                CHECK (state_code ~ '^[A-Z]{2}$'),
            CONSTRAINT chk_fb_marketplace_location_source
                CHECK (source IN ('seed', 'startpage', 'ddg', 'brave', 'user', 'unresolved'))
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_fb_marketplace_location_id "
        "ON fb_marketplace_locations (location_id) "
        "WHERE location_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS fb_marketplace_locations")
