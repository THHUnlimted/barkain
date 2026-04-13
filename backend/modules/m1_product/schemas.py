"""Pydantic request/response schemas for M1 Product Resolution."""

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, field_validator


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


# MARK: - Error


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict = {}


class ErrorResponse(BaseModel):
    error: ErrorDetail
