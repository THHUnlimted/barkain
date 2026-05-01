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
    # Optional thumbnail the iOS client already has on hand for this product
    # (typically from a search-result row whose ``image_url`` was supplied by
    # the M1 thumbnail backfill cascade — eBay → Serper). The backend uses
    # this only when no upstream resolver (Gemini, UPCitemdb, Serper
    # synthesis) returned an image. Lets the search-row thumbnail flow
    # through to ``Product.image_url`` so the loading state and "Recently
    # sniffed" surface the same picture the user just tapped. Barcode
    # scans (Scanner path) leave this null.
    fallback_image_url: str | None = Field(default=None, max_length=2048)

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
    # ``"exact"`` for UPC-resolved rows, ``"provisional"`` for best-effort
    # rows persisted by ``/resolve-from-search`` when no UPC could be
    # derived. iOS reads this to render the "approximate match" banner
    # and skip the Recently Sniffed rail; older clients ignore the field.
    match_quality: Literal["exact", "provisional"] = "exact"
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

    demo-prep-1 Item 3 adds a confidence gate: the client forwards the
    search-result's ``confidence`` so the server can short-circuit with
    409 RESOLUTION_NEEDS_CONFIRMATION when the value falls below
    ``settings.LOW_CONFIDENCE_THRESHOLD``. Omit or set to None to skip
    the gate (preserves pre-demo-prep-1 behavior for any client that
    hasn't adopted the confidence field yet).
    """

    device_name: str = Field(..., min_length=3, max_length=300)
    brand: str | None = Field(default=None, max_length=120)
    model: str | None = Field(default=None, max_length=120)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    # Same purpose as ProductResolveRequest.fallback_image_url — the
    # search-row thumbnail (often a backfilled eBay/Serper image) so the
    # persisted product carries the picture the user tapped.
    fallback_image_url: str | None = Field(default=None, max_length=2048)
    # provisional-resolve: the user's original search string, forwarded so
    # a provisional Product row carries it in ``source_raw.search_query``
    # (the M2 stream auto-injects this as ``query_override`` for
    # provisional rows). Optional and additive — older clients omit it
    # and the behavior is unchanged when ``PROVISIONAL_RESOLVE_ENABLED``
    # is off.
    query: str | None = Field(default=None, max_length=300)

    model_config = {"protected_namespaces": ()}


class ResolveFromSearchConfirmRequest(BaseModel):
    """Request body for POST /api/v1/products/resolve-from-search/confirm.

    Called by the iOS client after the user has either confirmed or
    rejected a low-confidence resolution in the ``ConfirmationPromptView``
    sheet. On ``user_confirmed=true`` the backend runs the normal
    resolution path AND marks ``Product.source_raw.user_confirmed=True``
    so future scans of the same canonical product skip the dialog. On
    ``user_confirmed=false`` the backend just logs telemetry and returns
    an empty 200 (the client surface has already closed the sheet).

    ``query`` carries the original search string so telemetry can
    attribute confirmations / rejections back to a specific search —
    valuable signal for tuning ``LOW_CONFIDENCE_THRESHOLD``.
    """

    device_name: str = Field(..., min_length=3, max_length=300)
    brand: str | None = Field(default=None, max_length=120)
    model: str | None = Field(default=None, max_length=120)
    user_confirmed: bool
    query: str | None = Field(default=None, max_length=300)
    # Search-row thumbnail forwarded from the original confirmation prompt,
    # so the post-confirm persist also carries the user-tapped image.
    fallback_image_url: str | None = Field(default=None, max_length=2048)

    model_config = {"protected_namespaces": ()}


class ConfirmResolutionResponse(BaseModel):
    """Response body for POST /api/v1/products/resolve-from-search/confirm.

    When ``user_confirmed=true`` at the request layer, ``product`` carries
    the resolved canonical product (same shape as ``ProductResponse``).
    When ``user_confirmed=false``, ``product`` is None and the client
    re-opens search. Collapsing the two response shapes into one optional
    field keeps the client-side decoder simple at the cost of a nullable
    field — worth it for fewer branches on both sides.
    """

    product: ProductResponse | None = None
    logged: bool = True


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
    """Response for a text product search query.

    ``total_results`` is the count of rows in ``results`` after dedup +
    variant collapse + max_results cap — not the full underlying match
    count across sources. ``cascade_path`` names which tiers fired (e.g.
    ``"db"``, ``"db+tier2"``, ``"db+tier2+gemini"``, ``"gemini_first"``,
    ``"cached"``) so we can attribute slow queries to the right layer
    from iOS telemetry.
    """

    query: str
    results: list[ProductSearchResult]
    total_results: int
    cached: bool = False
    cascade_path: str | None = None


# MARK: - Error


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict = {}


class ErrorResponse(BaseModel):
    error: ErrorDetail
