"""eBay Browse API adapter — replaces the ``ebay_new`` / ``ebay_used`` browser
container legs with direct HTTPS calls to ``api.ebay.com/buy/browse/v1``.

Why: the container-based scrapers for eBay were dead on arrival — selector
drift (2i-d-L3) and Chromium resource contention meant 0 listings per run on
a saturated ``t3.xlarge``. The public Browse API returns the same data in
sub-second latency with generous rate limits (5k calls/day free tier) and
doesn't require a browser fleet at all.

## Auth

App Access Token via ``client_credentials`` grant — no user consent, 2 hr
TTL, auto-refreshed by this module. Requires ``EBAY_APP_ID`` + ``EBAY_CERT_ID``
in the environment; when either is missing, ``is_configured()`` returns False
and the caller is expected to fall back to the container path. This keeps
local dev / CI / tests working without live credentials.

## Condition filter

eBay's condition system uses numeric IDs, not text. We split the two logical
retailers Barkain knows about into disjoint ID buckets:

- ``ebay_new``  → ``1000`` (New), ``1500`` (New other), ``1750`` (New w/ defects)
- ``ebay_used`` → ``2000`` (Certified refurb), ``2500`` (Seller refurb),
  ``3000`` (Used), ``4000`` (Very Good), ``5000`` (Good), ``6000`` (Acceptable)

Sending ``filter=conditions:{NEW}`` (text form) does NOT filter — this is a
common footgun and was how the initial smoke test returned mixed conditions.

## Contract

``fetch_ebay(retailer_id, query, ...) -> ContainerResponse`` matches the
walmart-adapter signature so ``container_client._extract_one`` can route to
it without special-casing. All failures are captured in
``response.error`` — the function never raises.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import UTC, datetime
from urllib.parse import quote_plus

import httpx

from app.config import Settings, settings as default_settings
from modules.m2_prices.schemas import (
    ContainerError,
    ContainerListing,
    ContainerMetadata,
    ContainerResponse,
)

logger = logging.getLogger("barkain.m2.ebay_browse_api")

# MARK: - Constants

_OAUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"
_SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
_MARKETPLACE = "EBAY_US"
_OAUTH_SCOPE = "https://api.ebay.com/oauth/api_scope"
_REQUEST_TIMEOUT = 15
_TOKEN_REFRESH_BUFFER = 60  # refresh 60 s before expiry

CONDITION_IDS: dict[str, list[int]] = {
    "ebay_new": [1000, 1500, 1750],
    "ebay_used": [2000, 2500, 3000, 4000, 5000, 6000],
}


# MARK: - Token cache
#
# Process-wide cache with a lock so concurrent requests don't fire N parallel
# ``client_credentials`` exchanges. Token payload + expiry wall-clock is
# enough — we don't need per-tenant caching (the App ID is global).

_token_cache: dict[str, float | str | None] = {
    "token": None,
    "expires_at": 0.0,
}
_token_lock = asyncio.Lock()


class EbayBrowseNotConfiguredError(RuntimeError):
    """Raised when the caller explicitly invokes the adapter without creds set."""


def is_configured(cfg: Settings | None = None) -> bool:
    """Return True iff both App ID and Cert ID are populated."""
    c = cfg or default_settings
    return bool(c.EBAY_APP_ID and c.EBAY_CERT_ID)


async def _get_app_token(cfg: Settings) -> str:
    """Return a valid App Access Token, refreshing via the OAuth endpoint if needed.

    Cached in-process. Refreshes ``_TOKEN_REFRESH_BUFFER`` seconds before
    expiry so a token that's about to lapse isn't handed to a caller.
    """
    async with _token_lock:
        now = time.time()
        token = _token_cache.get("token")
        expires_at = float(_token_cache.get("expires_at") or 0.0)
        if token and expires_at > now + _TOKEN_REFRESH_BUFFER:
            return str(token)

        if not is_configured(cfg):
            raise EbayBrowseNotConfiguredError(
                "EBAY_APP_ID and EBAY_CERT_ID must both be set to use the Browse API"
            )

        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            resp = await client.post(
                _OAUTH_URL,
                auth=(cfg.EBAY_APP_ID, cfg.EBAY_CERT_ID),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                content=f"grant_type=client_credentials&scope={quote_plus(_OAUTH_SCOPE)}",
            )
            resp.raise_for_status()
            payload = resp.json()

        _token_cache["token"] = payload["access_token"]
        _token_cache["expires_at"] = now + int(payload.get("expires_in", 7200))
        logger.info(
            "ebay.app_token refreshed expires_in=%ss", payload.get("expires_in")
        )
        return str(_token_cache["token"])


def _clear_token_cache() -> None:
    """Test helper — invalidate the in-process token cache."""
    _token_cache["token"] = None
    _token_cache["expires_at"] = 0.0


# MARK: - Partial-listing filter (gated by M2_EBAY_DROP_PARTIAL_LISTINGS)
#
# eBay sellers list empty boxes, parts, and lone accessories under the same
# search keywords as the real product. On used categories (laptops, phones)
# this dominates the cheap end of the price stream, making the rec engine
# pick a $20 box as the "best deal." This filter drops the obvious offenders
# by title pattern. Order matters less than completeness — false positives on
# real listings are worse than letting one box through, so phrases are kept
# specific (e.g. "box only", not "box").

_EBAY_PARTIAL_RE = re.compile(
    r"\b("
    r"box\s+only|empty\s+box|original\s+box\s+only|retail\s+box(?:\s+only)?|"
    r"packaging\s+only|just\s+the\s+box|"
    r"for\s+parts(?:\s+(?:or|&)\s+(?:not|repair))?|"
    r"not\s+working|as[- ]is|broken|cracked\s+screen|"
    r"charger\s+only|cable\s+only|adapter\s+only|power\s+(?:cord|brick)\s+only|"
    r"replacement\s+(?:parts|screen|battery|charger|keycap(?:s)?|lens|strap)|"
    r"manual\s+only|paperwork\s+only|stand\s+only|case\s+only|cover\s+only|"
    r"sticker(?:s)?\s+only|decal(?:s)?\s+only|"
    r"screen\s+protector(?:s)?$|"
    r"key\s*cap(?:s)?|keycap(?:s)?|keyset(?:s)?|"
    r"faceplate(?:s)?|skin(?:s)?\s+only|wrap\s+only|decal\s+wrap|"
    r"carry\s+(?:case|pouch|bag)\s+only|sleeve\s+only|"
    r"mount\s+only|dock\s+only|grip(?:s)?\s+only|"
    r"strap\s+only|band\s+only|"
    r"no\s+(?:battery|charger|hdd|ssd|os|hard\s+drive|remote)"
    r")\b",
    re.IGNORECASE,
)


def _is_partial_listing(title: str) -> bool:
    return bool(_EBAY_PARTIAL_RE.search(title or ""))


# MARK: - Response mapping


def _map_item_to_listing(item: dict) -> ContainerListing | None:
    """Map one Browse API ``itemSummary`` element to a ``ContainerListing``.

    Returns ``None`` if the item is missing a price or title (eBay occasionally
    omits either on auction-only listings or pulled results).
    """
    price = item.get("price") or {}
    title = item.get("title") or ""
    raw_value = price.get("value")
    if raw_value is None or not title:
        return None
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return None

    seller = (item.get("seller") or {}).get("username")
    condition_text = item.get("condition") or "new"
    condition_id = item.get("conditionId")
    is_new = str(condition_id) == "1000" if condition_id is not None else (
        condition_text.lower() == "new"
    )

    return ContainerListing(
        title=title,
        price=value,
        currency=price.get("currency", "USD"),
        url=item.get("itemWebUrl", "") or item.get("itemHref", ""),
        condition="new" if is_new else condition_text.lower(),
        is_available=True,
        image_url=(item.get("image") or {}).get("imageUrl"),
        seller=seller,
        is_third_party=True,  # every Browse API listing is from a third-party seller
        extraction_method="ebay_browse_api",
    )


# MARK: - Public entrypoint


async def fetch_ebay(
    *,
    retailer_id: str,
    query: str,
    product_name: str | None = None,
    upc: str | None = None,
    max_listings: int = 10,
    cfg: Settings | None = None,
) -> ContainerResponse:
    """Search eBay Browse API and return a normalized ``ContainerResponse``.

    ``retailer_id`` MUST be ``"ebay_new"`` or ``"ebay_used"``. The condition
    filter is derived from ``CONDITION_IDS``. ``upc`` and ``product_name``
    are accepted for signature parity with other adapters but not used — the
    Browse API's keyword search is more tolerant of product-name phrasing
    than eBay's UPC/GTIN filter, and keyword hits are what users actually see
    when searching eBay themselves.
    """
    c = cfg or default_settings
    extracted_at = datetime.now(UTC).isoformat()

    if retailer_id not in CONDITION_IDS:
        return ContainerResponse(
            retailer_id=retailer_id,
            query=query,
            error=ContainerError(
                code="INVALID_RETAILER",
                message=f"ebay_browse_api supports ebay_new/ebay_used, got {retailer_id!r}",
            ),
            metadata=ContainerMetadata(extracted_at=extracted_at),
        )

    try:
        token = await _get_app_token(c)
    except EbayBrowseNotConfiguredError as e:
        return ContainerResponse(
            retailer_id=retailer_id,
            query=query,
            error=ContainerError(code="NOT_CONFIGURED", message=str(e)),
            metadata=ContainerMetadata(extracted_at=extracted_at),
        )
    except httpx.HTTPError as e:
        logger.warning("ebay.oauth failed: %s", e)
        return ContainerResponse(
            retailer_id=retailer_id,
            query=query,
            error=ContainerError(
                code="OAUTH_FAILED",
                message=f"Failed to obtain app token: {e}",
            ),
            metadata=ContainerMetadata(extracted_at=extracted_at),
        )

    # eBay's filter DSL uses ``|`` as the OR-separator inside braces, NOT comma.
    # ``conditionIds:{1000,1500}`` silently doesn't filter; ``conditionIds:{1000|1500}`` works.
    condition_list = "|".join(str(i) for i in CONDITION_IDS[retailer_id])
    search_filter = f"conditionIds:{{{condition_list}}}"

    t0 = time.monotonic()
    params = {
        "q": query,
        "limit": max(1, min(max_listings, 50)),
        "filter": search_filter,
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": _MARKETPLACE,
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            resp = await client.get(_SEARCH_URL, params=params, headers=headers)
    except httpx.HTTPError as e:
        logger.warning("ebay.search request failed: %s", e)
        return ContainerResponse(
            retailer_id=retailer_id,
            query=query,
            extraction_time_ms=int((time.monotonic() - t0) * 1000),
            error=ContainerError(code="REQUEST_FAILED", message=str(e)),
            metadata=ContainerMetadata(extracted_at=extracted_at),
        )

    elapsed_ms = int((time.monotonic() - t0) * 1000)

    if resp.status_code >= 400:
        logger.warning(
            "ebay.search HTTP %d retailer=%s body=%s",
            resp.status_code, retailer_id, resp.text[:200],
        )
        # 401 likely means our cached token was invalidated server-side;
        # clear so the next call forces a refresh.
        if resp.status_code == 401:
            _clear_token_cache()
        return ContainerResponse(
            retailer_id=retailer_id,
            query=query,
            extraction_time_ms=elapsed_ms,
            error=ContainerError(
                code="HTTP_ERROR",
                message=f"Browse API returned HTTP {resp.status_code}",
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
            retailer_id=retailer_id,
            query=query,
            extraction_time_ms=elapsed_ms,
            error=ContainerError(code="PARSE_ERROR", message=str(e)),
            metadata=ContainerMetadata(extracted_at=extracted_at),
        )

    summaries = data.get("itemSummaries") or []
    listings: list[ContainerListing] = []
    dropped_partial = 0
    for item in summaries:
        if len(listings) >= max_listings:
            break
        if (
            default_settings.M2_EBAY_DROP_PARTIAL_LISTINGS
            and _is_partial_listing(item.get("title") or "")
        ):
            dropped_partial += 1
            continue
        listing = _map_item_to_listing(item)
        if listing is not None:
            listings.append(listing)
    if dropped_partial:
        logger.info(
            "ebay.search retailer=%s q=%r dropped_partial=%d",
            retailer_id, query, dropped_partial,
        )

    logger.info(
        "ebay.search retailer=%s q=%r total=%s returned=%d in %dms",
        retailer_id, query, data.get("total"), len(listings), elapsed_ms,
    )

    return ContainerResponse(
        retailer_id=retailer_id,
        query=query,
        extraction_time_ms=elapsed_ms,
        listings=listings,
        metadata=ContainerMetadata(
            url=str(resp.request.url),
            extracted_at=extracted_at,
            script_version="ebay_browse_api/1.0",
        ),
    )


# MARK: - Thumbnail-only lookup (pass 1 of SEARCH_THUMBNAIL_FALLBACK)
#
# Last-resort thumbnail backfill for M1 search rows that the primary
# providers didn't supply an image for. Free within eBay's rate limits
# (5k calls/day on the public tier), so we always try eBay before
# falling through to the paid Serper /search pass. Distinct from
# `fetch_ebay` above — no condition filter, no listing mapping, just
# the first item's image URL. Soft-fails on any error so the search
# pipeline never breaks because of a thumbnail call.


async def lookup_thumbnail(
    query: str,
    *,
    cfg: Settings | None = None,
) -> str | None:
    """Return the first item's ``image.imageUrl`` for ``query`` from eBay
    Browse API, or None on missing creds / non-200 / network error /
    empty results / missing image field.

    Caller is expected to compose ``query`` from brand + title (or just
    title when brand is unknown). No condition filter is applied — the
    goal is "find any listing whose photo represents this product",
    not "rank-correct retail price." Limit is hardcoded to 1 because we
    only want the first photo.
    """
    c = cfg or default_settings
    if not is_configured(c):
        return None
    cleaned = (query or "").strip()
    if not cleaned:
        return None

    try:
        token = await _get_app_token(c)
    except (EbayBrowseNotConfiguredError, httpx.HTTPError) as exc:
        logger.warning("ebay.thumbnail oauth failed: %r", exc)
        return None

    headers = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": _MARKETPLACE,
        "Content-Type": "application/json",
    }
    params = {"q": cleaned, "limit": 1}

    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            resp = await client.get(_SEARCH_URL, params=params, headers=headers)
    except httpx.HTTPError as exc:
        logger.warning("ebay.thumbnail request failed q=%r: %r", cleaned, exc)
        return None

    if resp.status_code == 401:
        # Same token-invalidation pattern as fetch_ebay.
        _clear_token_cache()
    if resp.status_code >= 400:
        logger.info(
            "ebay.thumbnail HTTP %d q=%r body=%s",
            resp.status_code, cleaned, resp.text[:200],
        )
        return None

    try:
        data = resp.json()
    except ValueError:
        return None

    summaries = data.get("itemSummaries") or []
    if not summaries:
        return None
    image = (summaries[0].get("image") or {}).get("imageUrl")
    if isinstance(image, str) and image.startswith(("http://", "https://")):
        return image
    return None
