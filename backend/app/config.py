from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import find_dotenv


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=find_dotenv(usecwd=True),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://app:localdev@localhost:5432/barkain"
    TEST_DATABASE_URL: str = "postgresql+asyncpg://app:test@localhost:5433/barkain_test"

    # Cache
    REDIS_URL: str = "redis://localhost:6379/0"

    # Auth (Clerk)
    CLERK_SECRET_KEY: str = ""
    CLERK_PUBLISHABLE_KEY: str = ""

    # Environment
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "DEBUG"
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:8000"
    # When True, the API short-circuits Clerk auth and rate-limit user
    # resolution to a deterministic "demo_user" id. Read via `settings.DEMO_MODE`
    # so monkeypatch.setenv works in tests (the previous BARKAIN_DEMO_MODE
    # os.getenv was cached at import time).
    DEMO_MODE: bool = False

    # Rate Limiting
    RATE_LIMIT_GENERAL: int = 60
    RATE_LIMIT_WRITE: int = 30
    RATE_LIMIT_AI: int = 10
    # Pro subscribers get their tier-resolved limit multiplied by this factor.
    # Tier resolution is cached in Redis for 60s; webhook handlers bust the key
    # on state changes so upgrades take effect within the cache TTL.
    RATE_LIMIT_PRO_MULTIPLIER: int = 2
    # FB Marketplace location resolver. Hard cap, no pro multiplier — this
    # bucket protects a shared external-budget resource (Decodo bytes +
    # search-engine tokens), not a user-tier feature. Singleflight only
    # dedupes identical (country, state, city) triples; distinct cities
    # from one bursty client still hit every engine.
    RATE_LIMIT_FB_LOCATION_RESOLVE: int = 5

    # Billing (Step 2f — M11 Billing / RevenueCat)
    REVENUECAT_WEBHOOK_SECRET: str = ""

    # AI — Product Resolution
    GEMINI_API_KEY: str = ""
    UPCITEMDB_API_KEY: str = ""
    # Serper SERP API key for the AI resolve leg's E-then-B path. When set,
    # m1_product first attempts UPC resolution via Serper top-5 organic →
    # Gemini synthesis (fast, cheap), then falls back to grounded Gemini on
    # null. When empty, the path soft-skips Serper and runs grounded only.
    # See bench/vendor-migrate-1 for the validation. Get one at serper.dev.
    SERPER_API_KEY: str = ""

    # AI — Watchdog / Anthropic
    ANTHROPIC_API_KEY: str = ""
    WATCHDOG_TEST_QUERY: str = "Sony WH-1000XM5"
    WATCHDOG_SLACK_WEBHOOK: str = ""

    # App
    APP_VERSION: str = "0.2.0"

    # Containers (agent-browser scraper infrastructure)
    CONTAINER_URL_PATTERN: str = "http://localhost:{port}"
    CONTAINER_TIMEOUT_SECONDS: int = 30
    CONTAINER_RETRY_COUNT: int = 1
    # 8086 (lowes) retired 2026-04-18 (deterministic ~143 s hang).
    # 8089 (sams_club) retired 2026-04-18 (~77 s + 1.4 MB Decodo per scan
    # vs sub-second / KB-class API alternatives — not worth the bandwidth).
    CONTAINER_PORTS: dict = {
        "amazon": 8081,
        "best_buy": 8082,
        "walmart": 8083,
        "target": 8084,
        "home_depot": 8085,
        "ebay_new": 8087,
        "ebay_used": 8088,
        "backmarket": 8090,
        "fb_marketplace": 8091,
    }

    # Walmart adapter routing — selects which path handles walmart scrapes.
    # Valid values: "decodo_http" (default, production path via Decodo US
    # residential proxy), "firecrawl" (legacy demo path — Firecrawl's upstream
    # pool is currently caught by PerimeterX 100% of the time, kept selectable
    # for future recovery), "container" (legacy browser container, broken).
    # See docs/SCRAPING_AGENT_ARCHITECTURE.md App. A–C.
    WALMART_ADAPTER: str = "decodo_http"

    # Firecrawl — managed scraping service (demo path for walmart).
    FIRECRAWL_API_KEY: str = ""

    # Decodo — residential proxy (production path for walmart).
    # Username will be automatically prefixed with "user-" and suffixed with
    # "-country-us" if not already present, so you can set DECODO_PROXY_USER to
    # the bare username from your Decodo dashboard.
    DECODO_PROXY_USER: str = ""
    DECODO_PROXY_PASS: str = ""
    # HOST may be either bare ("gate.decodo.com") or host:port. Containers'
    # proxy_relay.py reads HOST + PORT separately; walmart_http accepts either
    # form (see _build_proxy_url). Keep both vars in /etc/barkain-scrapers.env
    # so both consumers agree.
    DECODO_PROXY_HOST: str = "gate.decodo.com"
    DECODO_PROXY_PORT: int = 7000

    # Affiliate Programs (Step 2g — M12 Affiliate URL Routing)
    AMAZON_ASSOCIATE_TAG: str = ""          # "barkain-20" in production
    EBAY_CAMPAIGN_ID: str = ""              # "5339148665" in production
    WALMART_AFFILIATE_ID: str = ""          # Empty until Impact Radius approval
    AFFILIATE_WEBHOOK_SECRET: str = ""      # Bearer token for /conversion (placeholder)

    # eBay Marketplace Account Deletion webhook (GDPR — required for Browse API prod access).
    # The token is an opaque 32-80 char string we pick and paste into the eBay developer
    # portal. The endpoint is the fully-qualified public HTTPS URL eBay sends GETs+POSTs to.
    # Both must match exactly between here and the portal — the challenge hash is
    # SHA-256(challenge_code + token + endpoint); any drift breaks verification.
    EBAY_VERIFICATION_TOKEN: str = ""
    EBAY_ACCOUNT_DELETION_ENDPOINT: str = ""

    # eBay Browse API credentials (App ID + Cert ID from the developer portal
    # "Production Keyset"). When both are set the ebay_new / ebay_used retailer
    # legs are served from the Browse API (sub-second, reliable) instead of the
    # browser-container scraper. When unset, they fall back to the container
    # path — the same pattern as WALMART_ADAPTER. Tokens are auto-refreshed via
    # the client_credentials grant, 2 hr TTL, cached in-process.
    EBAY_APP_ID: str = ""
    EBAY_CERT_ID: str = ""

    # EXPERIMENT (revertable): swap Tier 2 UPCitemdb for eBay Browse keyword
    # search in ProductSearchService. Off by default — flip to True to A/B.
    SEARCH_TIER2_USE_EBAY: bool = False
    # EXPERIMENT: when an eBay item exposes a `gtin`, surface it as
    # `primary_upc` on the search row. Lets the iOS tap take the fast
    # /resolve UPC path when the UPC is already in the products cache.
    SEARCH_TIER2_EBAY_USE_GTIN: bool = False
    # EXPERIMENT: force eBay rows to omit `primary_upc` so iOS skips the
    # /resolve UPC round-trip entirely and goes straight to
    # /resolve-from-search. Wins precedence over USE_GTIN if both on.
    SEARCH_TIER2_EBAY_SKIP_UPC: bool = False
    # EXPERIMENT (revertable): drop "box only", "for parts", "charger only"
    # style listings from the M2 ebay_browse_api price stream. Especially
    # noisy on used categories (laptops, phones).
    M2_EBAY_DROP_PARTIAL_LISTINGS: bool = False

    # demo-prep-1 Item 3: confidence gate on /resolve-from-search. When the
    # client-supplied search-result confidence falls below this threshold,
    # the endpoint returns 409 RESOLUTION_NEEDS_CONFIRMATION instead of
    # silently resolving the best-guess. The iOS client then renders a
    # confirmation sheet and re-calls the `/resolve-from-search/confirm`
    # endpoint on user affirmation. Env-tunable so demo-week can dial it
    # down to 0.50 if F&F are hitting the dialog too often.
    LOW_CONFIDENCE_THRESHOLD: float = 0.70

    # Best Buy Products API key. When set, the best_buy retailer leg is served
    # from the Products API (~150 ms per call) instead of the browser-container
    # scraper (~80–90 s). Same fallback pattern as EBAY_APP_ID — missing key
    # routes through the container path.
    BESTBUY_API_KEY: str = ""

    # Decodo Scraper API auth header (Basic auth). When set, the amazon
    # retailer leg is served from Decodo's maintained Amazon parser
    # (~3 s, structured JSON) instead of the browser-container scraper
    # (~50 s). Set to the literal header value from the Decodo dashboard,
    # e.g. "Basic VTAwMDAz...". Same fallback pattern as the other API
    # adapters — missing value routes through the container path.
    DECODO_SCRAPER_API_AUTH: str = ""

    # SQS / Background Workers (Step 2h)
    # LocalStack override for dev; empty string in prod so boto3 resolves
    # the real AWS SQS endpoint from the default credential chain.
    SQS_ENDPOINT_URL: str = ""
    SQS_REGION: str = "us-east-1"

    # Worker cadence tuning (Step 2h)
    PRICE_INGESTION_STALE_HOURS: int = 6
    DISCOUNT_VERIFICATION_STALE_DAYS: int = 7
    DISCOUNT_VERIFICATION_FAILURE_THRESHOLD: int = 3

    # Portal Monetization (Step 3g)
    # Feature flag — when False, PortalMonetizationService.resolve_cta_list
    # short-circuits to GUIDED_ONLY for every portal, regardless of membership
    # toggles or populated referral URLs. Demo / test environments leave it
    # off so signup-attribution links never fire from a non-prod surface.
    PORTAL_MONETIZATION_ENABLED: bool = False
    RAKUTEN_REFERRAL_URL: str = ""
    BEFRUGAL_REFERRAL_URL: str = ""
    TOPCASHBACK_FLEXOFFERS_PUB_ID: str = ""
    TOPCASHBACK_FLEXOFFERS_LINK_TEMPLATE: str = ""

    # Resend (Step 3g — ops alerts for portal worker failures)
    RESEND_API_KEY: str = ""
    RESEND_ALERT_FROM: str = ""
    RESEND_ALERT_TO: str = ""


settings = Settings()
