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

    # Billing (Step 2f — M11 Billing / RevenueCat)
    REVENUECAT_WEBHOOK_SECRET: str = ""

    # AI — Product Resolution
    GEMINI_API_KEY: str = ""
    UPCITEMDB_API_KEY: str = ""

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
    CONTAINER_PORTS: dict = {
        "amazon": 8081,
        "best_buy": 8082,
        "walmart": 8083,
        "target": 8084,
        "home_depot": 8085,
        "lowes": 8086,
        "ebay_new": 8087,
        "ebay_used": 8088,
        "sams_club": 8089,
        "backmarket": 8090,
        "fb_marketplace": 8091,
    }

    # Walmart adapter routing — selects which path handles walmart scrapes.
    # Valid values: "container" (legacy browser container, default), "firecrawl"
    # (demo path via Firecrawl managed API), "decodo_http" (production path via
    # Decodo residential proxy). See docs/SCRAPING_AGENT_ARCHITECTURE.md App. A–C.
    WALMART_ADAPTER: str = "container"

    # Firecrawl — managed scraping service (demo path for walmart).
    FIRECRAWL_API_KEY: str = ""

    # Decodo — residential proxy (production path for walmart).
    # Username will be automatically prefixed with "user-" and suffixed with
    # "-country-us" if not already present, so you can set DECODO_PROXY_USER to
    # the bare username from your Decodo dashboard.
    DECODO_PROXY_USER: str = ""
    DECODO_PROXY_PASS: str = ""
    DECODO_PROXY_HOST: str = "gate.decodo.com:7000"

    # Affiliate Programs (Step 2g — M12 Affiliate URL Routing)
    AMAZON_ASSOCIATE_TAG: str = ""          # "barkain-20" in production
    EBAY_CAMPAIGN_ID: str = ""              # "5339148665" in production
    WALMART_AFFILIATE_ID: str = ""          # Empty until Impact Radius approval
    AFFILIATE_WEBHOOK_SECRET: str = ""      # Bearer token for /conversion (placeholder)

    # SQS / Background Workers (Step 2h)
    # LocalStack override for dev; empty string in prod so boto3 resolves
    # the real AWS SQS endpoint from the default credential chain.
    SQS_ENDPOINT_URL: str = ""
    SQS_REGION: str = "us-east-1"

    # Worker cadence tuning (Step 2h)
    PRICE_INGESTION_STALE_HOURS: int = 6
    DISCOUNT_VERIFICATION_STALE_DAYS: int = 7
    DISCOUNT_VERIFICATION_FAILURE_THRESHOLD: int = 3


settings = Settings()
