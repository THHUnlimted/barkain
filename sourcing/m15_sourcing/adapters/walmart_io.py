"""Walmart.io Affiliate/Search API adapter — UPC → live listing.

## Auth

Walmart.io retired the old ``apiKey=`` query parameter. Current auth is an
RSA-SHA256 signature over a canonical string of three headers:

    WM_CONSUMER.ID          your consumer ID (UUID from the dashboard)
    WM_CONSUMER.INTIMESTAMP epoch milliseconds
    WM_SEC.KEY_VERSION      which of your uploaded public keys to verify against

The canonical string is those three values in **lexicographic order of header
name**, each followed by a newline. Sign it with the matching private key,
base64 the signature, send it as ``WM_SEC.AUTH_SIGNATURE``. Get the ordering or
the trailing newlines wrong and you get a 401 that says nothing useful — which
is why ``_canonical_string`` is separated out and unit-tested rather than
inlined into the request builder.

## Terms posture

The affiliate program expects you to drive affiliate traffic. A 3,000-row crunch
that returns 12 candidates and drives zero clicks is not what it's for. So:

- every response is cached (``service.py`` holds the Redis layer, 12 h default)
- outbound concurrency is bounded by the caller's semaphore
- ``_MIN_REQUEST_INTERVAL_S`` enforces a floor between calls process-wide
- product URLs keep the affiliate tag so the traffic we *do* drive is attributed

If credentials are absent, ``is_configured()`` returns False and the caller
falls back to the ``walmart_http`` residential-proxy path — the same
adapter-swap pattern as ``WALMART_ADAPTER`` and ``MISC_RETAILER_ADAPTER``.

## Never raises

Every failure comes back as ``WalmartMatch(found=False, error=...)``. One bad
row out of 3,000 must not abort a crunch.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import httpx

from m15_sourcing.config import SourcingSettings as Settings, settings as default_settings

logger = logging.getLogger("barkain.m15.walmart_io")

_BASE_URL = "https://developer.api.walmart.com/api-proxy/service/affil/product/v2"
_ITEMS_URL = f"{_BASE_URL}/items"
_REQUEST_TIMEOUT = 15

# Floor between outbound calls, process-wide. Not a substitute for the caller's
# semaphore — that bounds concurrency, this bounds *rate*. Both matter: six
# concurrent workers with no rate floor still burst 6 calls into one millisecond.
_MIN_REQUEST_INTERVAL_S = 0.12
_rate_lock = asyncio.Lock()
_last_request_at = 0.0


class WalmartIoNotConfiguredError(RuntimeError):
    """Raised when the adapter is invoked without credentials set."""


@dataclass(frozen=True)
class WalmartMatch:
    """One Walmart listing matched to a UPC. ``found=False`` means no listing."""

    found: bool
    gtin14: str | None = None
    item_id: str | None = None
    name: str | None = None
    brand: str | None = None
    category_path: str | None = None
    price: Decimal | None = None
    msrp: Decimal | None = None
    in_stock: bool | None = None
    review_count: int | None = None
    rating: float | None = None
    seller_count: int | None = None
    offer_type: str | None = None  # "ONLINE_ONLY" | "ONLINE_AND_STORE" | ...
    weight_lb: Decimal | None = None
    product_url: str | None = None
    image_url: str | None = None
    two_day_shipping: bool | None = None
    error: str | None = None
    source: str = "walmart_io"

    @property
    def listing_key(self) -> str | None:
        """Stable key for the snapshot table — Walmart's item ID, else the GTIN."""
        return self.item_id or self.gtin14

    def as_dict(self) -> dict[str, object]:
        return {
            "found": self.found,
            "item_id": self.item_id,
            "name": self.name,
            "brand": self.brand,
            "category_path": self.category_path,
            "price": float(self.price) if self.price is not None else None,
            "msrp": float(self.msrp) if self.msrp is not None else None,
            "in_stock": self.in_stock,
            "review_count": self.review_count,
            "rating": self.rating,
            "seller_count": self.seller_count,
            "offer_type": self.offer_type,
            "weight_lb": float(self.weight_lb) if self.weight_lb is not None else None,
            "product_url": self.product_url,
            "image_url": self.image_url,
            "two_day_shipping": self.two_day_shipping,
            "error": self.error,
            "source": self.source,
        }


def is_configured(cfg: Settings | None = None) -> bool:
    c = cfg or default_settings
    return bool(c.WALMART_IO_CONSUMER_ID and c.WALMART_IO_PRIVATE_KEY)


# MARK: - Request signing


def canonical_string(consumer_id: str, timestamp_ms: str, key_version: str) -> str:
    """Build the string Walmart.io expects to be signed.

    Header values in **lexicographic order of header name**
    (``WM_CONSUMER.ID`` < ``WM_CONSUMER.INTIMESTAMP`` < ``WM_SEC.KEY_VERSION``),
    each terminated by a newline. The trailing newline on the final value is
    required — omitting it is the single most common cause of a 401 here.
    """
    return f"{consumer_id}\n{timestamp_ms}\n{key_version}\n"


def _load_private_key(raw: str):
    """Accept a PEM key as literal text, ``\\n``-escaped text, or base64 PEM."""
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    material = raw.strip()
    if "\\n" in material and "-----BEGIN" in material:
        material = material.replace("\\n", "\n")
    if "-----BEGIN" not in material:
        # Env vars carrying a whole PEM are painful; base64 is the usual dodge.
        try:
            material = base64.b64decode(material).decode("utf-8")
        except Exception as exc:  # noqa: BLE001 — surfaced as a config error
            raise WalmartIoNotConfiguredError(
                "WALMART_IO_PRIVATE_KEY is neither PEM nor base64-encoded PEM"
            ) from exc
    return load_pem_private_key(material.encode("utf-8"), password=None)


def build_auth_headers(cfg: Settings, *, timestamp_ms: str | None = None) -> dict[str, str]:
    """Sign a request and return the four ``WM_*`` headers."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    if not is_configured(cfg):
        raise WalmartIoNotConfiguredError(
            "WALMART_IO_CONSUMER_ID and WALMART_IO_PRIVATE_KEY must both be set"
        )

    consumer_id = cfg.WALMART_IO_CONSUMER_ID
    key_version = str(cfg.WALMART_IO_KEY_VERSION or "1")
    stamp = timestamp_ms or str(int(time.time() * 1000))

    private_key = _load_private_key(cfg.WALMART_IO_PRIVATE_KEY)
    signature = private_key.sign(
        canonical_string(consumer_id, stamp, key_version).encode("utf-8"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return {
        "WM_CONSUMER.ID": consumer_id,
        "WM_CONSUMER.INTIMESTAMP": stamp,
        "WM_SEC.KEY_VERSION": key_version,
        "WM_SEC.AUTH_SIGNATURE": base64.b64encode(signature).decode("ascii"),
        "Accept": "application/json",
    }


# MARK: - Response mapping

_WEIGHT_RE = re.compile(r"([\d.]+)\s*(lb|lbs|pound|pounds|oz|ounce|ounces|kg|g)\b", re.I)


def _to_decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def parse_weight_lb(value: object) -> Decimal | None:
    """Normalize Walmart's ``weight`` field to pounds.

    The API is inconsistent: sometimes a bare number (already pounds), sometimes
    a string with units. Getting this wrong shifts the WFS fee by a whole tier,
    so unrecognized formats return ``None`` (→ ``assumed_weight``) rather than a
    number that might be ounces.
    """
    if value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        return _to_decimal(value)

    text = str(value).strip()
    if not text:
        return None
    bare = _to_decimal(text)
    if bare is not None:
        return bare

    match = _WEIGHT_RE.search(text)
    if not match:
        return None
    amount = _to_decimal(match.group(1))
    if amount is None:
        return None
    unit = match.group(2).lower()
    if unit in ("lb", "lbs", "pound", "pounds"):
        return amount
    if unit in ("oz", "ounce", "ounces"):
        return amount / Decimal("16")
    if unit == "kg":
        return amount * Decimal("2.20462")
    if unit == "g":
        return amount * Decimal("0.00220462")
    return None


def _map_item(item: dict, gtin14: str | None) -> WalmartMatch:
    """Map one Walmart.io ``items[]`` element to a ``WalmartMatch``."""
    # `salePrice` is the current selling price; `msrp` is list. Buy-box price is
    # what we compute margin against, so salePrice wins and msrp is context.
    price = _to_decimal(item.get("salePrice"))
    if price is None:
        price = _to_decimal(item.get("price"))

    stock = item.get("stock")
    in_stock = None
    if isinstance(stock, str):
        in_stock = stock.strip().lower() in ("available", "in stock", "instock")
    elif item.get("availableOnline") is not None:
        in_stock = bool(item.get("availableOnline"))

    return WalmartMatch(
        found=True,
        gtin14=gtin14,
        item_id=str(item.get("itemId")) if item.get("itemId") is not None else None,
        name=item.get("name"),
        brand=item.get("brandName") or item.get("brand"),
        category_path=item.get("categoryPath"),
        price=price,
        msrp=_to_decimal(item.get("msrp")),
        in_stock=in_stock,
        review_count=item.get("numReviews") if isinstance(item.get("numReviews"), int) else None,
        rating=float(item["customerRating"])
        if _to_decimal(item.get("customerRating")) is not None
        else None,
        # Walmart.io doesn't expose an offer/seller count on the item payload.
        # `sellerInfo` names the current buy-box winner only, so we record its
        # presence (a third-party name means at least one non-Walmart seller)
        # and leave the true count to the scrape path.
        seller_count=None,
        offer_type=item.get("offerType"),
        weight_lb=parse_weight_lb(item.get("weight")),
        product_url=item.get("affiliateAddToCartUrl")
        or item.get("productTrackingUrl")
        or item.get("productUrl"),
        image_url=item.get("largeImage") or item.get("mediumImage") or item.get("thumbnailImage"),
        two_day_shipping=item.get("twoThreeDayShippingRate") is not None or None,
    )


# MARK: - Public entrypoint


async def lookup_by_upc(
    upc: str,
    *,
    gtin14: str | None = None,
    cfg: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> WalmartMatch:
    """Look up one UPC on Walmart. Never raises.

    ``upc`` should be the 12-digit UPC-A (or 13-digit EAN) — Walmart's index
    doesn't recognize a zero-padded GTIN-14.
    """
    c = cfg or default_settings

    if not is_configured(c):
        return WalmartMatch(
            found=False, gtin14=gtin14, error="NOT_CONFIGURED", source="walmart_io"
        )

    try:
        headers = build_auth_headers(c)
    except WalmartIoNotConfiguredError as exc:
        return WalmartMatch(found=False, gtin14=gtin14, error=str(exc), source="walmart_io")
    except Exception:
        logger.warning("walmart_io.sign failed", exc_info=True)
        return WalmartMatch(
            found=False, gtin14=gtin14, error="SIGNING_FAILED", source="walmart_io"
        )

    # Process-wide rate floor. Held across the sleep so concurrent callers
    # queue rather than all reading the same stale `_last_request_at`.
    global _last_request_at
    async with _rate_lock:
        elapsed = time.monotonic() - _last_request_at
        if elapsed < _MIN_REQUEST_INTERVAL_S:
            await asyncio.sleep(_MIN_REQUEST_INTERVAL_S - elapsed)
        _last_request_at = time.monotonic()

    params = {"upc": upc}
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=_REQUEST_TIMEOUT)
    try:
        resp = await http.get(_ITEMS_URL, params=params, headers=headers)
    except httpx.HTTPError as exc:
        logger.warning("walmart_io.request failed for %s: %s", upc, exc)
        return WalmartMatch(
            found=False, gtin14=gtin14, error=f"REQUEST_FAILED: {exc}", source="walmart_io"
        )
    finally:
        if owns_client:
            await http.aclose()

    # 404 is the *expected* answer for a UPC Walmart doesn't carry, which is
    # most of a distributor list. It's a clean "no match", not an error.
    if resp.status_code == 404:
        return WalmartMatch(found=False, gtin14=gtin14, source="walmart_io")
    if resp.status_code == 429:
        return WalmartMatch(
            found=False, gtin14=gtin14, error="RATE_LIMITED", source="walmart_io"
        )
    if resp.status_code >= 400:
        body = (resp.text or "")[:160]
        logger.warning("walmart_io HTTP %d for %s (body=%r)", resp.status_code, upc, body)
        return WalmartMatch(
            found=False,
            gtin14=gtin14,
            error=f"HTTP_{resp.status_code}",
            source="walmart_io",
        )

    try:
        data = resp.json()
    except ValueError:
        return WalmartMatch(
            found=False, gtin14=gtin14, error="BAD_JSON", source="walmart_io"
        )

    items = data.get("items") or []
    if not items:
        return WalmartMatch(found=False, gtin14=gtin14, source="walmart_io")

    return _map_item(items[0], gtin14)
