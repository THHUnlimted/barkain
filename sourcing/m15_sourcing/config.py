"""M15 Sourcing settings — self-contained so the module stays isolated.

This deliberately does **not** add fields to ``app.config.Settings``. The whole
sourcing scanner lives under ``sourcing/`` and touches nothing in the shared
backend until it's wired in on purpose. That means it can be reviewed, moved,
extracted into its own service, or deleted without a diff anywhere else.

Reads the same ``.env`` as the main app, so when it *is* wired in there's one
env file, not two. The only settings borrowed from the main app are the eBay
Browse credentials (``EBAY_APP_ID`` / ``EBAY_CERT_ID``), because the sourcing
adapter reuses M2's OAuth token cache rather than opening a second one.

To activate later:
  1. ``cp -r sourcing/m15_sourcing backend/modules/`` (or symlink it)
  2. ``cp sourcing/migrations/0013_sourcing_tables.py infrastructure/migrations/versions/``
  3. register ``SourcingRow`` & co. in ``backend/app/models.py``
  4. ``app.include_router(m15_sourcing_router)`` in ``backend/app/main.py``

Until then this file is the seam that keeps step 0 free.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class SourcingSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Walmart.io affiliate/search API ───────────────────────────────
    # Auth is an RSA-SHA256 signature over three headers, not an API key.
    # PRIVATE_KEY accepts PEM, \n-escaped PEM, or base64-encoded PEM so it
    # survives being pasted into a .env or a secrets manager.
    WALMART_IO_CONSUMER_ID: str = ""
    WALMART_IO_PRIVATE_KEY: str = ""
    WALMART_IO_KEY_VERSION: str = "1"

    # Adapter swap, same pattern as WALMART_ADAPTER / MISC_RETAILER_ADAPTER:
    #   "walmart_io"   — signed affiliate/search API (primary)
    #   "walmart_http" — Decodo residential-proxy scrape (fallback; the only
    #                    path that yields review counts and the
    #                    "N+ bought since yesterday" badge)
    #   "disabled"     — skip the Walmart leg entirely
    WALMART_SOURCING_ADAPTER: str = "walmart_io"

    # ── eBay ──────────────────────────────────────────────────────────
    # Browse credentials are shared with M2; repeated here so the module can
    # run standalone before it's wired into the app.
    EBAY_APP_ID: str = ""
    EBAY_CERT_ID: str = ""
    # Marketplace Insights (sold-item history) needs a separate eBay approval
    # beyond the Browse keyset. Off until approved — demand.py falls through to
    # review velocity, which is the whole reason the snapshot table exists.
    EBAY_MARKETPLACE_INSIGHTS_ENABLED: bool = False

    # ── Pipeline tuning ───────────────────────────────────────────────
    # Concurrency bounds simultaneous outbound calls; the adapters additionally
    # enforce a process-wide rate floor. Cache TTLs are long on purpose — a
    # wholesale match isn't price-sensitive by the minute, and aggressive
    # caching is also the rate-limit defense.
    SOURCING_MATCH_CONCURRENCY: int = 6
    SOURCING_MATCH_CACHE_TTL_WALMART: int = 43200  # 12 h
    SOURCING_MATCH_CACHE_TTL_EBAY: int = 21600     # 6 h
    SOURCING_MAX_ROWS: int = 10000

    # Share of buyers who leave a review — the load-bearing assumption behind
    # every velocity-based demand estimate. Varies by category by a factor of
    # several; every estimate derived from it is flagged `review_rate_assumed`.
    SOURCING_REVIEW_RATE: float = 0.02

    # Days of inventory to amortize WFS storage over when scoring.
    SOURCING_DAYS_ON_HAND: int = 60


settings = SourcingSettings()
