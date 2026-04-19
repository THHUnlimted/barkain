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

import asyncio
import logging
import re
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

# Retry budget for transient upstream failures. Initial attempt + 1 retry on
# rate-limit (429) or server-side error (5xx). Other 4xx (e.g. 403 invalid key)
# and network errors fail fast — they don't recover within a useful window.
# Bumped from 1 → 2 (2026-04-19) after observing intermittent "unavailable"
# in the UI for Best Buy when the free tier (5 calls/sec) was momentarily
# exhausted by concurrent searches.
BESTBUY_MAX_ATTEMPTS = 2
_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})

# Back-off used between retries when no `Retry-After` header is present.
# Capped to keep the worst-case failure path fast.
_RETRY_DEFAULT_DELAY_S = 0.5
_RETRY_MAX_DELAY_S = 2.0


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


# Characters that break Best Buy's `(search=...)` DSL even after URL-encoding.
# `(` and `)` are predicate delimiters; `,` is an in-predicate list separator;
# `+`, `/`, `*`, `:`, `&`, `\` are operators or URL-significant. Observed live
# 400 in 2026-04-19 logs on resolved product names like
# "Apple iPhone 14 128GB (Blue, MPVR3LL/A)" and "AppleCare+ for iPhone 14
# (2-Year Plan)" — the parens + slash + plus combination produced
# `400 Couldn't understand …`. Hyphens are preserved (model numbers like
# `WH-1000XM5`).
_BBY_DSL_BAD_CHARS = re.compile(r"[()\\,+/*:&]")


def _sanitize_query(query: str) -> str:
    """Strip Best Buy DSL-hostile characters and collapse whitespace.

    Replaces each bad char with a space (rather than removing it) so multi-word
    titles like "(Blue, MPVR3LL/A)" become "Blue MPVR3LL A" instead of
    "BlueMPVR3LLA" — the search engine can still match on the surviving tokens.
    """
    cleaned = _BBY_DSL_BAD_CHARS.sub(" ", query)
    return " ".join(cleaned.split())


def _parse_retry_after(header_value: str | None) -> float:
    """Parse the value of an HTTP ``Retry-After`` header into seconds.

    Best Buy returns the integer-seconds form; the HTTP-date form is rare in
    practice but we accept it defensively. Falls back to the default delay
    when the header is missing or unparseable. The result is clamped to
    ``_RETRY_MAX_DELAY_S`` so a hostile/buggy upstream can't stall us.
    """
    if not header_value:
        return _RETRY_DEFAULT_DELAY_S
    try:
        return min(max(float(header_value), 0.0), _RETRY_MAX_DELAY_S)
    except ValueError:
        # HTTP-date form (e.g. "Wed, 21 Oct 2015 07:28:00 GMT"). Don't bother
        # parsing — fall back to the default delay rather than implement the
        # whole RFC 7231 §7.1.3 grammar for a path Best Buy doesn't actually use.
        return _RETRY_DEFAULT_DELAY_S


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

    # Sanitize then quote. Sanitization strips DSL-breaking chars BEFORE URL
    # encoding because Best Buy's parser interprets `(`, `)`, `,`, `+`, `/`
    # as DSL syntax even when percent-encoded (verified live 2026-04-19).
    # `quote` (not `quote_plus`) — Best Buy expects `%20` not `+` inside the
    # parentheses, confirmed via live test.
    sanitized_query = _sanitize_query(query)
    search_url = _SEARCH_URL_TEMPLATE.format(
        query=quote(sanitized_query, safe="")
    )
    params = {
        "apiKey": c.BESTBUY_API_KEY,
        "format": "json",
        "pageSize": max(1, min(max_listings, 100)),
        "show": _SHOW_FIELDS,
        "sort": _SORT,
    }

    t0 = time.monotonic()
    resp: httpx.Response | None = None
    attempts = 0

    # Retry loop: only triggers on `_RETRYABLE_STATUSES` (429 / 5xx). Other
    # 4xx and network errors fail fast — see the comment on
    # `BESTBUY_MAX_ATTEMPTS` for rationale.
    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
        while attempts < BESTBUY_MAX_ATTEMPTS:
            attempts += 1
            try:
                resp = await client.get(search_url, params=params)
            except httpx.HTTPError as e:
                logger.warning(
                    "best_buy.search request failed (attempt %d/%d): %s",
                    attempts, BESTBUY_MAX_ATTEMPTS, e,
                )
                return ContainerResponse(
                    retailer_id="best_buy",
                    query=query,
                    extraction_time_ms=int((time.monotonic() - t0) * 1000),
                    error=ContainerError(
                        code="REQUEST_FAILED",
                        message=str(e),
                        details={"attempt": attempts},
                    ),
                    metadata=ContainerMetadata(extracted_at=extracted_at),
                )

            if (
                resp.status_code in _RETRYABLE_STATUSES
                and attempts < BESTBUY_MAX_ATTEMPTS
            ):
                delay = _parse_retry_after(resp.headers.get("Retry-After"))
                logger.warning(
                    "best_buy.search HTTP %d on attempt %d/%d — sleeping %.2fs before retry",
                    resp.status_code, attempts, BESTBUY_MAX_ATTEMPTS, delay,
                )
                await asyncio.sleep(delay)
                continue

            break

    assert resp is not None  # loop guarantees one assignment before break/return.
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    if resp.status_code >= 400:
        logger.warning(
            "best_buy.search HTTP %d body=%s (attempts=%d)",
            resp.status_code, resp.text[:200], attempts,
        )
        return ContainerResponse(
            retailer_id="best_buy",
            query=query,
            extraction_time_ms=elapsed_ms,
            error=ContainerError(
                code="HTTP_ERROR",
                message=f"Products API returned HTTP {resp.status_code}",
                details={
                    "status_code": resp.status_code,
                    "body": resp.text[:500],
                    "attempts": attempts,
                },
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
