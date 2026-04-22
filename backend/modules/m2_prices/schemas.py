"""Pydantic request/response schemas for M2 Prices — container communication + API response."""

import re
import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, field_validator

_FB_LOCATION_ID_PATTERN = re.compile(r"\d+")


# MARK: - Container Request


class ContainerExtractRequest(BaseModel):
    """Request body sent to a scraper container's POST /extract.

    ``fb_location_id`` + ``fb_radius_km`` are routed only to the
    fb_marketplace container (ignored by every other retailer). They
    let the backend override the baked-in ``FB_MARKETPLACE_LOCATION``
    env default with a user-resolved numeric location ID + search
    radius. Miles → km conversion happens in ``ContainerClient`` at
    the adapter boundary so callers can keep speaking miles.
    """

    query: str
    product_name: str | None = None
    upc: str | None = None
    max_listings: int = 10
    fb_location_id: str | None = None
    fb_radius_km: int | None = None

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

    @field_validator("fb_location_id")
    @classmethod
    def validate_fb_location_id(cls, v: str | None) -> str | None:
        # FB Page IDs are positive bigints; we accept them as strings
        # to avoid iOS Int64 round-trip narrowing. Empty → None so the
        # container falls back to its env default.
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        if len(v) > 30:
            raise ValueError("fb_location_id must be 30 chars or fewer")
        if not _FB_LOCATION_ID_PATTERN.fullmatch(v):
            raise ValueError("fb_location_id must be a positive integer")
        return v

    @field_validator("fb_radius_km")
    @classmethod
    def validate_fb_radius_km(cls, v: int | None) -> int | None:
        # 800 km ≈ 500 mi, the outer iOS-side cap. FB silently clamps
        # anything higher but we want to reject obvious nonsense early.
        if v is None:
            return None
        if v < 1 or v > 800:
            raise ValueError("fb_radius_km must be between 1 and 800")
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
    is_third_party: bool = False
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


# MARK: - API Response


class PriceResponse(BaseModel):
    """Single retailer price in the comparison response."""

    retailer_id: str
    retailer_name: str
    price: float
    original_price: float | None = None
    currency: str = "USD"
    url: str | None = None
    condition: str = "new"
    is_available: bool = True
    is_on_sale: bool = False
    last_checked: datetime


class RetailerStatus(str, Enum):
    """Per-retailer outcome of a price comparison run.

    - SUCCESS: retailer returned at least one listing that passed relevance scoring
    - NO_MATCH: retailer was reachable but produced no usable listing (returned 0 items,
      all items were filtered by relevance, or returned a bot-detection / challenge page).
      Render as "Not found" — the product isn't available or identifiable at this retailer.
    - UNAVAILABLE: retailer was unreachable (connection failed, HTTP 5xx, container offline).
      Render as "Unavailable" — a true outage, not a lack of results.
    """

    SUCCESS = "success"
    NO_MATCH = "no_match"
    UNAVAILABLE = "unavailable"


class RetailerResult(BaseModel):
    """Per-retailer status for the full 11-retailer set, regardless of outcome."""

    retailer_id: str
    retailer_name: str
    status: RetailerStatus


class PriceComparisonResponse(BaseModel):
    """Full price comparison response across all retailers."""

    product_id: uuid.UUID
    product_name: str
    prices: list[PriceResponse]
    retailer_results: list[RetailerResult] = []
    total_retailers: int
    retailers_succeeded: int
    retailers_failed: int
    cached: bool
    fetched_at: datetime
