"""Pydantic request/response schemas for M2 Prices — container communication."""

from pydantic import BaseModel, field_validator


# MARK: - Container Request


class ContainerExtractRequest(BaseModel):
    """Request body sent to a scraper container's POST /extract."""

    query: str
    product_name: str | None = None
    upc: str | None = None
    max_listings: int = 10

    @field_validator("query")
    @classmethod
    def validate_query(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("query must not be empty")
        return v

    @field_validator("max_listings")
    @classmethod
    def validate_max_listings(cls, v: int) -> int:
        if v < 1 or v > 50:
            raise ValueError("max_listings must be between 1 and 50")
        return v


# MARK: - Container Response


class ContainerListing(BaseModel):
    """A single product listing extracted by a scraper container."""

    title: str
    price: float
    original_price: float | None = None
    currency: str = "USD"
    url: str = ""
    condition: str = "new"
    is_available: bool = True
    image_url: str | None = None
    seller: str | None = None
    extraction_method: str = "dom_eval"


class ContainerMetadata(BaseModel):
    """Extraction metadata returned by a scraper container."""

    url: str = ""
    extracted_at: str = ""
    script_version: str = ""
    bot_detected: bool = False


class ContainerError(BaseModel):
    """Error details from a failed extraction."""

    code: str
    message: str
    details: dict = {}


class ContainerResponse(BaseModel):
    """Full response from a scraper container's POST /extract."""

    retailer_id: str
    query: str
    extraction_time_ms: int = -1
    listings: list[ContainerListing] = []
    metadata: ContainerMetadata = ContainerMetadata()
    error: ContainerError | None = None


# MARK: - Health Check


class ContainerHealthResponse(BaseModel):
    """Response from a scraper container's GET /health."""

    status: str
    retailer_id: str
    script_version: str
    chromium_ready: bool
