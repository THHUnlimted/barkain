"""Best Buy Products API adapter — replaces the ``best_buy`` browser container
leg with direct HTTPS calls to ``api.bestbuy.com/v1/products``.

Why: the container-based scraper for Best Buy takes ~80–90 s per call (Best
Buy's product pages are JS-heavy and defeat short `networkidle` waits). The
public Products API returns the same data in ~150 ms with a generous free
tier (5 calls/sec, 50k/day).

## Auth

Single API key via query param (``apiKey=...``), no OAuth. Requires
``BESTBUY_API_KEY`` in the environment; when missing, ``is_configured()``
returns False and the caller is expected to fall back to the container path.

## URL shape

Best Buy's API uses an attribute-filter DSL in the path itself:

    GET /v1/products(search=<query>)?apiKey=...&format=json&pageSize=N&show=<fields>

The parentheses are literal and denote an attribute predicate. ``search=``
is a full-text match across name/description/etc. (more tolerant than
``name=``). URL-encode the query value inside the parens.

## Contract

``fetch_best_buy(retailer_id, query, ...) -> ContainerResponse`` matches the
walmart + ebay adapter signatures so ``container_client._extract_one`` can
route to it without special-casing. All failures are captured in
``response.error`` — the function never raises.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from urllib.parse import quote

import httpx

from app.config import Settings, settings as default_settings
from modules.m2_prices.schemas import (
    ContainerError,
    ContainerListing,
    ContainerMetadata,
    ContainerResponse,
)

logger = logging.getLogger("barkain.m2.best_buy_api")

# MARK: - Constants

_SEARCH_URL_TEMPLATE = "https://api.bestbuy.com/v1/products(search={query})"
# Fields we request from the API. Keep minimal — each additional attribute
# slows the query and bloats the response. Best Buy only sells new, so we
# don't request condition.
_SHOW_FIELDS = "sku,name,salePrice,regularPrice,url,image,onlineAvailability"
# `bestSellingRank.asc` surfaces popular SKUs first — a reasonable proxy for
# relevance when searching by keyword. The relevance scorer downstream
# re-ranks by model/variant match, so sort order matters less than coverage.
_SORT = "bestSellingRank.asc"
_REQUEST_TIMEOUT = 15


class BestBuyNotConfiguredError(RuntimeError):
    """Raised when the caller explicitly invokes the adapter without a key set."""


def is_configured(cfg: Settings | None = None) -> bool:
    """Return True iff ``BESTBUY_API_KEY`` is populated."""
    c = cfg or default_settings
    return bool(c.BESTBUY_API_KEY)


# MARK: - Response mapping


def _map_product_to_listing(product: dict) -> ContainerListing | None:
    """Map one Products-API product element to a ``ContainerListing``.

    Returns ``None`` if the product is missing a price or name (Best Buy
    occasionally ships sparse "placeholder" SKUs in category slots).
    """
    name = product.get("name") or ""
    sale_price = product.get("salePrice")
    regular_price = product.get("regularPrice")
    if not name or sale_price is None:
        return None
    try:
        price = float(sale_price)
        regular = float(regular_price) if regular_price is not None else None
    except (TypeError, ValueError):
        return None

    # Only surface original_price when there's an actual markdown. Same-value
    # salePrice/regularPrice is just Best Buy's default (no sale) and would
    # mislead the UI into showing a strikethrough.
    original_price = regular if regular is not None and regular > price else None

    return ContainerListing(
        title=name,
        price=price,
        original_price=original_price,
        currency="USD",
        url=product.get("url", ""),
        condition="new",
        is_available=bool(product.get("onlineAvailability", True)),
        image_url=product.get("image"),
        seller="Best Buy",
        is_third_party=False,
        extraction_method="best_buy_api",
    )


# MARK: - Public entrypoint


async def fetch_best_buy(
    *,
    query: str,
    product_name: str | None = None,
    upc: str | None = None,
    max_listings: int = 10,
    cfg: Settings | None = None,
) -> ContainerResponse:
    """Search Best Buy Products API and return a normalized ``ContainerResponse``.

    ``product_name`` and ``upc`` are accepted for signature parity with the
    other adapters but unused — Best Buy's ``search=`` parameter covers the
    same surface as the container's keyword search. (UPC-matching via
    ``upc=`` is separately possible but returns zero results for many legit
    products because not every listing has the UPC populated in their DB.)
    """
    c = cfg or default_settings
    extracted_at = datetime.now(UTC).isoformat()

    if not is_configured(c):
        return ContainerResponse(
            retailer_id="best_buy",
            query=query,
            error=ContainerError(
                code="NOT_CONFIGURED",
                message="BESTBUY_API_KEY must be set to use the Products API",
            ),
            metadata=ContainerMetadata(extracted_at=extracted_at),
        )

    # Quote the query for inclusion inside the `(search=...)` predicate.
    # `quote` (not `quote_plus`) — Best Buy expects `%20` not `+` inside
    # the parentheses, confirmed via live test.
    search_url = _SEARCH_URL_TEMPLATE.format(query=quote(query, safe=""))
    params = {
        "apiKey": c.BESTBUY_API_KEY,
        "format": "json",
        "pageSize": max(1, min(max_listings, 100)),
        "show": _SHOW_FIELDS,
        "sort": _SORT,
    }

    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            resp = await client.get(search_url, params=params)
    except httpx.HTTPError as e:
        logger.warning("best_buy.search request failed: %s", e)
        return ContainerResponse(
            retailer_id="best_buy",
            query=query,
            extraction_time_ms=int((time.monotonic() - t0) * 1000),
            error=ContainerError(code="REQUEST_FAILED", message=str(e)),
            metadata=ContainerMetadata(extracted_at=extracted_at),
        )

    elapsed_ms = int((time.monotonic() - t0) * 1000)

    if resp.status_code >= 400:
        logger.warning(
            "best_buy.search HTTP %d body=%s",
            resp.status_code, resp.text[:200],
        )
        return ContainerResponse(
            retailer_id="best_buy",
            query=query,
            extraction_time_ms=elapsed_ms,
            error=ContainerError(
                code="HTTP_ERROR",
                message=f"Products API returned HTTP {resp.status_code}",
                details={"status_code": resp.status_code, "body": resp.text[:500]},
            ),
            metadata=ContainerMetadata(
                url=str(resp.request.url),
                extracted_at=extracted_at,
            ),
        )

    try:
        data = resp.json()
    except ValueError as e:
        return ContainerResponse(
            retailer_id="best_buy",
            query=query,
            extraction_time_ms=elapsed_ms,
            error=ContainerError(code="PARSE_ERROR", message=str(e)),
            metadata=ContainerMetadata(extracted_at=extracted_at),
        )

    products = data.get("products") or []
    listings: list[ContainerListing] = []
    for product in products[:max_listings]:
        listing = _map_product_to_listing(product)
        if listing is not None:
            listings.append(listing)

    logger.info(
        "best_buy.search q=%r total=%s returned=%d in %dms",
        query, data.get("total"), len(listings), elapsed_ms,
    )

    return ContainerResponse(
        retailer_id="best_buy",
        query=query,
        extraction_time_ms=elapsed_ms,
        listings=listings,
        metadata=ContainerMetadata(
            url=str(resp.request.url),
            extracted_at=extracted_at,
            script_version="best_buy_api/1.0",
        ),
    )
