"""eBay sourcing adapter — GTIN search for active price band + competition.

Reuses the OAuth token cache from ``m2_prices/adapters/ebay_browse_api`` rather
than opening a second one: same App ID, same 2 h token, and two independent
caches would double the ``client_credentials`` traffic for nothing.

## Why ``gtin=`` and not keyword search

M2 searches eBay by keyword deliberately — for a consumer comparing prices,
keyword hits are what they'd see searching themselves, and the Browse API's
GTIN filter is stricter than a shopper's mental model.

Sourcing wants the opposite. We have an exact UPC from a distributor and the
question is "what is *this specific item* selling for, and how many people are
already selling it". A keyword search that returns a similar-but-different
model quietly answers a different question, and the answer becomes a purchase
order. So M15 uses ``gtin=``, and when it returns nothing that is a real
signal — "no eBay listing for this UPC" — not a reason to retry loosely.

## Competition count

``item_summary/search`` returns ``total`` — the number of active listings
matching the query. For a GTIN search that is a direct read on how many people
are selling the same item right now, which is the ``seller_count`` the unit-share
math needs. It counts *listings*, not distinct sellers (one seller with three
listings counts three), so it reads slightly pessimistic — the safe direction.

## Sold data

Active listings tell you supply, not demand. Sold-item history lives behind the
Marketplace Insights API, which requires a separate eBay approval.
``lookup_sold_count`` is the seam for it: flag-gated, returns ``None`` when
unapproved, and ``demand.py`` simply falls through to review velocity. Terapeak
inside Seller Hub is the free manual equivalent while approval is pending.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import httpx

from m15_sourcing.config import SourcingSettings as Settings, settings as default_settings
from m15_sourcing.ebay_token import (
    EbayBrowseNotConfiguredError,
    get_app_token as _get_app_token,
    is_configured,
)

logger = logging.getLogger("barkain.m15.ebay")

_SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
_MARKETPLACE = "EBAY_US"
_REQUEST_TIMEOUT = 15
_MAX_LISTINGS = 50

__all__ = ["EbayMatch", "is_configured", "lookup_by_gtin", "lookup_sold_count"]


def _to_decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


@dataclass(frozen=True)
class EbayMatch:
    """Active-listing summary for one GTIN on eBay."""

    found: bool
    gtin14: str | None = None
    total_active_listings: int | None = None
    lowest_price: Decimal | None = None
    median_price: Decimal | None = None
    highest_price: Decimal | None = None
    lowest_new_price: Decimal | None = None
    median_new_price: Decimal | None = None
    new_listing_count: int = 0
    used_listing_count: int = 0
    sample_title: str | None = None
    sample_item_id: str | None = None
    sample_url: str | None = None
    image_url: str | None = None
    category: str | None = None
    free_shipping_count: int = 0
    sold_count_90d: int | None = None
    error: str | None = None
    source: str = "ebay_browse_api"

    @property
    def listing_key(self) -> str | None:
        """Snapshot key. GTIN-scoped, not item-scoped.

        Individual eBay listings are ephemeral — they end, relist under a new
        ID, and take their history with them. The *market* for a GTIN is the
        thing with continuity, so that's what we track over time.
        """
        return f"gtin:{self.gtin14}" if self.gtin14 else self.sample_item_id

    @property
    def reference_price(self) -> Decimal | None:
        """The price to underwrite against.

        Median-of-new, not lowest-of-anything. The lowest active listing is
        routinely a damaged unit, a mispriced auction, or a seller exiting —
        pricing a purchase order off it is how a spreadsheet talks you into a
        loss. Falls back to overall median when there are no new listings.
        """
        return self.median_new_price or self.median_price

    def as_dict(self) -> dict[str, object]:
        return {
            "found": self.found,
            "total_active_listings": self.total_active_listings,
            "lowest_price": float(self.lowest_price) if self.lowest_price is not None else None,
            "median_price": float(self.median_price) if self.median_price is not None else None,
            "highest_price": float(self.highest_price)
            if self.highest_price is not None
            else None,
            "lowest_new_price": float(self.lowest_new_price)
            if self.lowest_new_price is not None
            else None,
            "median_new_price": float(self.median_new_price)
            if self.median_new_price is not None
            else None,
            "reference_price": float(self.reference_price)
            if self.reference_price is not None
            else None,
            "new_listing_count": self.new_listing_count,
            "used_listing_count": self.used_listing_count,
            "free_shipping_count": self.free_shipping_count,
            "sample_title": self.sample_title,
            "sample_item_id": self.sample_item_id,
            "sample_url": self.sample_url,
            "image_url": self.image_url,
            "category": self.category,
            "sold_count_90d": self.sold_count_90d,
            "error": self.error,
            "source": self.source,
        }


def _median(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / Decimal("2")


def _summarize(items: list[dict], gtin14: str | None, total: int | None) -> EbayMatch:
    new_prices: list[Decimal] = []
    all_prices: list[Decimal] = []
    used_count = 0
    free_shipping = 0
    sample: dict | None = None
    category: str | None = None

    for item in items:
        price = _to_decimal((item.get("price") or {}).get("value"))
        if price is None or price <= 0:
            continue
        all_prices.append(price)

        condition_id = str(item.get("conditionId") or "")
        # 1000/1500/1750 are eBay's new-family condition IDs. Anything else is
        # used/refurb, and mixing those into the reference price is how a
        # sourcing tool decides a $40 item sells for $22.
        if condition_id in ("1000", "1500", "1750"):
            new_prices.append(price)
        else:
            used_count += 1

        options = item.get("shippingOptions") or []
        for option in options:
            cost = _to_decimal((option.get("shippingCost") or {}).get("value"))
            if cost is not None and cost == 0:
                free_shipping += 1
                break

        if sample is None:
            sample = item
            category = (item.get("categories") or [{}])[0].get("categoryName")

    if not all_prices:
        return EbayMatch(found=False, gtin14=gtin14, total_active_listings=total or 0)

    return EbayMatch(
        found=True,
        gtin14=gtin14,
        total_active_listings=total if total is not None else len(items),
        lowest_price=min(all_prices),
        median_price=_median(all_prices),
        highest_price=max(all_prices),
        lowest_new_price=min(new_prices) if new_prices else None,
        median_new_price=_median(new_prices),
        new_listing_count=len(new_prices),
        used_listing_count=used_count,
        free_shipping_count=free_shipping,
        sample_title=(sample or {}).get("title"),
        sample_item_id=(sample or {}).get("legacyItemId") or (sample or {}).get("itemId"),
        sample_url=(sample or {}).get("itemWebUrl"),
        image_url=((sample or {}).get("image") or {}).get("imageUrl"),
        category=category,
    )


async def lookup_by_gtin(
    gtin: str,
    *,
    gtin14: str | None = None,
    cfg: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> EbayMatch:
    """Search eBay active listings by GTIN. Never raises.

    ``gtin`` should be the 12-digit UPC-A or 13-digit EAN, matching what the
    seller actually put in the listing's product identifier field.
    """
    c = cfg or default_settings

    try:
        token = await _get_app_token(c)
    except EbayBrowseNotConfiguredError:
        return EbayMatch(found=False, gtin14=gtin14, error="NOT_CONFIGURED")
    except httpx.HTTPError as exc:
        logger.warning("ebay_sourcing.oauth failed: %s", exc)
        return EbayMatch(found=False, gtin14=gtin14, error=f"OAUTH_FAILED: {exc}")

    params = {"gtin": gtin, "limit": _MAX_LISTINGS}
    headers = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": _MARKETPLACE,
        "Content-Type": "application/json",
    }

    t0 = time.monotonic()
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=_REQUEST_TIMEOUT)
    try:
        resp = await http.get(_SEARCH_URL, params=params, headers=headers)
    except httpx.HTTPError as exc:
        logger.warning("ebay_sourcing.search failed for %s: %s", gtin, exc)
        return EbayMatch(found=False, gtin14=gtin14, error=f"REQUEST_FAILED: {exc}")
    finally:
        if owns_client:
            await http.aclose()

    if resp.status_code == 429:
        return EbayMatch(found=False, gtin14=gtin14, error="RATE_LIMITED")
    if resp.status_code >= 400:
        body = (resp.text or "")[:160]
        logger.warning(
            "ebay_sourcing HTTP %d for %s (%.0f ms) body=%r",
            resp.status_code, gtin, (time.monotonic() - t0) * 1000, body,
        )
        return EbayMatch(found=False, gtin14=gtin14, error=f"HTTP_{resp.status_code}")

    try:
        data = resp.json()
    except ValueError:
        return EbayMatch(found=False, gtin14=gtin14, error="BAD_JSON")

    items = data.get("itemSummaries") or []
    total = data.get("total")
    if not items:
        # A real answer: nobody is selling this UPC on eBay right now.
        return EbayMatch(found=False, gtin14=gtin14, total_active_listings=0)

    return _summarize(items, gtin14, total if isinstance(total, int) else None)


async def lookup_sold_count(
    gtin: str,
    *,
    cfg: Settings | None = None,
    client: httpx.AsyncClient | None = None,  # noqa: ARG001 — used once approved
) -> int | None:
    """Trailing-90-day sold count via Marketplace Insights. ``None`` when unavailable.

    Gated on ``EBAY_MARKETPLACE_INSIGHTS_ENABLED`` because the API requires a
    separate eBay application approval that most accounts don't have. Returning
    ``None`` rather than raising lets ``demand.py`` fall through to review
    velocity without the caller branching — the seam exists so that flipping
    the flag after approval is a one-line change here, not a pipeline rewrite.
    """
    c = cfg or default_settings
    if not getattr(c, "EBAY_MARKETPLACE_INSIGHTS_ENABLED", False):
        return None
    if not is_configured(c):
        return None
    # Intentionally not implemented until the account is approved — shipping a
    # speculative request shape against an API we can't test would be worse
    # than an honest None. See docs/SOURCING_SCANNER.md §5 tier 1.
    logger.info(
        "ebay_sourcing.sold_count requested for %s but Marketplace Insights "
        "is flagged on without an implementation — returning None",
        gtin,
    )
    return None
