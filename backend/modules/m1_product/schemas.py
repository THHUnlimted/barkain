"""Pydantic request/response schemas for M1 Product Resolution + Search."""

import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


# MARK: - Request


class ProductResolveRequest(BaseModel):
    """Request body for POST /api/v1/products/resolve."""

    upc: str

    @field_validator("upc")
    @classmethod
    def validate_upc(cls, v: str) -> str:
        """UPC must be a 12 or 13 digit numeric string."""
        v = v.strip()
        if not re.match(r"^\d{12,13}$", v):
            raise ValueError("UPC must be a 12 or 13 digit numeric string")
        return v


# MARK: - Response


class ProductResponse(BaseModel):
    """Response for a resolved product."""

    id: uuid.UUID
    upc: str | None
    asin: str | None
    name: str
    model: str | None = None
    brand: str | None
    category: str | None
    description: str | None
    image_url: str | None
    source: str
    confidence: float = 0.0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True, "protected_namespaces": ()}


# MARK: - Search (Step 3a)


class ProductSearchRequest(BaseModel):
    """Request body for POST /api/v1/products/search."""

    query: str = Field(..., min_length=3, max_length=200)
    max_results: int = Field(10, ge=1, le=20)
    # When true: bypass Redis cache, always run Gemini (in addition to DB/Tier 2),
    # and merge Gemini results in. Wired to the iOS "deep search" hint when the
    # debounced result set didn't substring-match the typed query.
    force_gemini: bool = False


class ResolveFromSearchRequest(BaseModel):
    """Request body for POST /api/v1/products/resolve-from-search.

    Used when the iOS client taps a Gemini-sourced search result that had
    ``primary_upc=null``. The backend runs a targeted Gemini device→UPC
    lookup and then delegates to the normal ``/resolve`` path so the product
    is persisted and returned in the same shape as ``/resolve``.
    """

    device_name: str = Field(..., min_length=3, max_length=300)
    brand: str | None = Field(default=None, max_length=120)
    model: str | None = Field(default=None, max_length=120)

    model_config = {"protected_namespaces": ()}


class ProductSearchResult(BaseModel):
    """A single result in a product search response.

    Shape parallels ``ProductResponse`` but without DB-required fields —
    Gemini-only rows have no persisted Product row until the user taps the
    result and we run the standard ``/products/resolve`` path.
    """

    device_name: str
    model: str | None = None
    brand: str | None = None
    category: str | None = None
    confidence: float = 0.0
    primary_upc: str | None = None
    source: Literal["db", "best_buy", "upcitemdb", "gemini", "generic"]
    product_id: uuid.UUID | None = None  # populated only for source="db"
    image_url: str | None = None

    model_config = {"protected_namespaces": ()}


class ProductSearchResponse(BaseModel):
    """Response for a text product search query."""

    query: str
    results: list[ProductSearchResult]
    total_results: int
    cached: bool = False


# MARK: - Error


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict = {}


class ErrorResponse(BaseModel):
    error: ErrorDetail
