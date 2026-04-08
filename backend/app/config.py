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

    # Rate Limiting
    RATE_LIMIT_GENERAL: int = 60
    RATE_LIMIT_WRITE: int = 30
    RATE_LIMIT_AI: int = 10

    # AI — Product Resolution
    GEMINI_API_KEY: str = ""
    UPCITEMDB_API_KEY: str = ""

    # App
    APP_VERSION: str = "0.1.0"

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


settings = Settings()
