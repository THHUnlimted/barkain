"""Amazon adapter — replaces the ``amazon`` browser container leg with
direct HTTPS calls to Decodo's Scraper API (https://scraper-api.decodo.com).

Why: the agent-browser container for Amazon takes ~50 s per call (Amazon's
anti-bot makes short waits unreliable; we conservatively wait for the full
search grid render). Decodo's Scraper API ships a maintained Amazon parser
that returns structured JSON in ~3 s — ~16× faster, no DOM maintenance, and
the residential pool is rotated by Decodo so we don't carry IP-rep risk.

## Auth

Single Basic-Auth header (``Authorization: Basic <base64(user:pass)>``).
Requires ``DECODO_SCRAPER_API_AUTH`` in the environment, set to the literal
header value Decodo gives you in the dashboard (e.g. ``Basic VTAwMDAz...``).
When missing, ``is_configured()`` returns False and the caller falls back to
the container path — same auto-prefer pattern as ``best_buy_api`` /
``ebay_browse_api``.

## Request shape

POST https://scraper-api.decodo.com/v2/scrape
{
  "target": "amazon_search",
  "query": "<keyword>",
  "parse": true
}

``parse: true`` triggers Decodo's Amazon parser; the response nests
listings under ``content.results.results.organic[]``. ``page_from`` and
``sort_by`` are accepted but optional — we omit them to keep the payload
minimal.

## Contract

``fetch_amazon(query, ...) -> ContainerResponse`` matches the other adapter
signatures so ``container_client._extract_one`` can route to it without
special-casing. All failures are captured in ``response.error`` — never raises.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

import httpx

from app.config import Settings, settings as default_settings
from modules.m2_prices.schemas import (
    ContainerError,
    ContainerListing,
    ContainerMetadata,
    ContainerResponse,
)

logger = logging.getLogger("barkain.m2.amazon_scraper_api")

# MARK: - Constants

_SCRAPER_URL = "https://scraper-api.decodo.com/v2/scrape"
_TARGET = "amazon_search"
_REQUEST_TIMEOUT = 30  # Decodo's Amazon parser observed at 2.5–4.5 s; 30 s is generous.
_AMAZON_PRODUCT_URL = "https://www.amazon.com/dp/{asin}"


class AmazonNotConfiguredError(RuntimeError):
    """Raised if the caller invokes the adapter without ``DECODO_SCRAPER_API_AUTH``."""


def is_configured(cfg: Settings | None = None) -> bool:
    """Return True iff ``DECODO_SCRAPER_API_AUTH`` is populated."""
    c = cfg or default_settings
    return bool(c.DECODO_SCRAPER_API_AUTH)


# MARK: - Response mapping


def _map_organic_to_listing(item: dict) -> ContainerListing | None:
    """Map one Decodo-parsed organic Amazon item to a ``ContainerListing``.

    Returns ``None`` if the item lacks an ASIN or price (Decodo occasionally
    includes UI placeholders like "Sponsored brand banners" with no asin).
    """
    asin = item.get("asin")
    title = item.get("title") or ""
    price = item.get("price")
    if not asin or not title or price is None:
        return None
    try:
        price_f = float(price)
    except (TypeError, ValueError):
        return None

    # Strikethrough only when there's an actual markdown.
    strike = item.get("price_strikethrough")
    try:
        strike_f = float(strike) if strike is not None else None
    except (TypeError, ValueError):
        strike_f = None
    original_price = strike_f if strike_f is not None and strike_f > price_f else None

    # Prefer the canonical /dp/{asin} URL — Decodo sometimes returns
    # affiliate-style search-result URLs that 302 to the product page.
    url = item.get("url") or _AMAZON_PRODUCT_URL.format(asin=asin)
    if not url.startswith("http"):
        # Decodo returns relative URLs ("/Foo/dp/B0...") in some result rows.
        url = _AMAZON_PRODUCT_URL.format(asin=asin)

    return ContainerListing(
        title=title,
        price=price_f,
        original_price=original_price,
        currency=item.get("currency") or "USD",
        url=url,
        condition="new",
        is_available=True,  # organic results are sellable; OOS items are filtered upstream
        image_url=item.get("url_image"),
        seller="Amazon",
        is_third_party=False,
        extraction_method="amazon_scraper_api",
    )


# MARK: - Public entrypoint


async def fetch_amazon(
    *,
    query: str,
    product_name: str | None = None,
    upc: str | None = None,
    max_listings: int = 10,
    cfg: Settings | None = None,
) -> ContainerResponse:
    """Search Amazon via Decodo Scraper API and return a normalized ``ContainerResponse``.

    ``product_name`` and ``upc`` are accepted for signature parity but unused
    — Amazon's keyword search is the same surface as the container's. If a
    UPC search is ever needed, Decodo also accepts a ``url`` field pointing
    at ``https://www.amazon.com/s?k=<upc>`` with the same parser.

    Sponsored results (``is_sponsored=True``) are dropped to mirror the
    ebay/best_buy adapter behavior — the recommendation engine downstream
    expects organic-only data so paid placement doesn't pollute lowest-price.
    """
    c = cfg or default_settings
    extracted_at = datetime.now(UTC).isoformat()

    if not is_configured(c):
        return ContainerResponse(
            retailer_id="amazon",
            query=query,
            error=ContainerError(
                code="NOT_CONFIGURED",
                message="DECODO_SCRAPER_API_AUTH must be set to use the Scraper API",
            ),
            metadata=ContainerMetadata(extracted_at=extracted_at),
        )

    payload = {
        "target": _TARGET,
        "query": query,
        "parse": True,
    }
    headers = {
        "Authorization": c.DECODO_SCRAPER_API_AUTH,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            resp = await client.post(_SCRAPER_URL, json=payload, headers=headers)
    except httpx.HTTPError as e:
        logger.warning("amazon.search request failed: %s", e)
        return ContainerResponse(
            retailer_id="amazon",
            query=query,
            extraction_time_ms=int((time.monotonic() - t0) * 1000),
            error=ContainerError(code="REQUEST_FAILED", message=str(e)),
            metadata=ContainerMetadata(extracted_at=extracted_at),
        )

    elapsed_ms = int((time.monotonic() - t0) * 1000)

    if resp.status_code >= 400:
        logger.warning(
            "amazon.search HTTP %d body=%s",
            resp.status_code, resp.text[:200],
        )
        return ContainerResponse(
            retailer_id="amazon",
            query=query,
            extraction_time_ms=elapsed_ms,
            error=ContainerError(
                code="HTTP_ERROR",
                message=f"Scraper API returned HTTP {resp.status_code}",
                details={"status_code": resp.status_code, "body": resp.text[:500]},
            ),
            metadata=ContainerMetadata(extracted_at=extracted_at),
        )

    try:
        data = resp.json()
    except ValueError as e:
        return ContainerResponse(
            retailer_id="amazon",
            query=query,
            extraction_time_ms=elapsed_ms,
            error=ContainerError(code="PARSE_ERROR", message=str(e)),
            metadata=ContainerMetadata(extracted_at=extracted_at),
        )

    # Top-level shape: {"results":[{"content":{"results":{"results":{"organic":[...]}}}}]}
    # Decodo wraps the parsed payload twice — once for the API task, once for
    # the parser. Defensive .get() chain so a parser regression bubbles up as
    # NO_LISTINGS rather than KeyError.
    try:
        outer = (data.get("results") or [{}])[0]
        content = outer.get("content") or {}
        # When a parse fails Decodo returns content as a raw HTML string.
        if isinstance(content, str):
            return ContainerResponse(
                retailer_id="amazon",
                query=query,
                extraction_time_ms=elapsed_ms,
                error=ContainerError(
                    code="PARSE_ERROR",
                    message="Scraper API returned raw HTML instead of parsed payload",
                ),
                metadata=ContainerMetadata(extracted_at=extracted_at),
            )
        inner = content.get("results") or {}
        nested = inner.get("results") or {}
        organic = nested.get("organic") or []
    except (AttributeError, IndexError, TypeError) as e:
        return ContainerResponse(
            retailer_id="amazon",
            query=query,
            extraction_time_ms=elapsed_ms,
            error=ContainerError(code="PARSE_ERROR", message=str(e)),
            metadata=ContainerMetadata(extracted_at=extracted_at),
        )

    listings: list[ContainerListing] = []
    for item in organic:
        if item.get("is_sponsored"):
            continue
        listing = _map_organic_to_listing(item)
        if listing is not None:
            listings.append(listing)
        if len(listings) >= max_listings:
            break

    logger.info(
        "amazon.search q=%r organic=%d returned=%d in %dms",
        query, len(organic), len(listings), elapsed_ms,
    )

    # Decodo nests the source URL one level above the listings array; fall
    # back to an empty string so ContainerMetadata's str-typed `url` field
    # validates even when the parser response omits it.
    source_url = inner.get("url") or nested.get("url") or ""

    return ContainerResponse(
        retailer_id="amazon",
        query=query,
        extraction_time_ms=elapsed_ms,
        listings=listings,
        metadata=ContainerMetadata(
            url=source_url,
            extracted_at=extracted_at,
            script_version="amazon_scraper_api/1.0",
        ),
    )
