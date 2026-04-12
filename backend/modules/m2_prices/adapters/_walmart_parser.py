"""Shared Walmart HTML → ContainerResponse parser.

Both the Decodo-proxy (`walmart_http.py`) and Firecrawl (`walmart_firecrawl.py`)
adapters fetch the same underlying Walmart search page and share the same
`__NEXT_DATA__` extraction logic. This module is the single source of truth
for that logic so adapter-specific fetchers stay small.

The Walmart search page server-renders its full product list into a
`<script id="__NEXT_DATA__" type="application/json">` tag at
`props.pageProps.initialData.searchResult.itemStacks[*].items`. We walk that
structure, filter out ads/sponsored placements, and emit one `ContainerListing`
per product.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime

from modules.m2_prices.schemas import (
    ContainerError,
    ContainerListing,
    ContainerMetadata,
    ContainerResponse,
)

logger = logging.getLogger("barkain.m2.walmart_parser")

# PerimeterX / other challenge page markers. If any of these appear in the
# response body we treat it as a bot challenge, not a real product page.
CHALLENGE_MARKERS = (
    "robot or human",
    "px-captcha",
    "press & hold",
    "access denied",
)

# Known Walmart first-party seller names (lowercase for comparison)
WALMART_FIRST_PARTY_SELLERS = frozenset({
    "walmart", "walmart.com", "walmart inc", "walmart inc.",
})

# Flexible `<script id="__NEXT_DATA__">` regex — tolerates any attribute order
# and whitespace between attributes.
_NEXT_DATA_RE = re.compile(
    r'<script\s+[^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
    re.DOTALL,
)


def detect_challenge(html: str) -> bool:
    """Return True if the HTML body looks like an anti-bot challenge page."""
    lowered = html.lower()
    return any(marker in lowered for marker in CHALLENGE_MARKERS)


def extract_listings(
    html: str,
    max_listings: int = 10,
    first_party_only: bool = True,
) -> list[ContainerListing]:
    """Extract up to `max_listings` product listings from Walmart search HTML.

    When `first_party_only` is True (default), third-party reseller listings
    are filtered out. If ALL listings are third-party, the cheapest one is
    returned with its `is_third_party` flag preserved so downstream code can
    decide what to do with it.

    Raises `ValueError` if the page has no `__NEXT_DATA__` block at all —
    the caller should treat that as a parse failure, not an empty result.
    """
    m = _NEXT_DATA_RE.search(html)
    if m is None:
        raise ValueError("__NEXT_DATA__ script tag not found in Walmart response")

    try:
        blob = json.loads(m.group(1))
    except json.JSONDecodeError as e:
        raise ValueError(f"failed to parse __NEXT_DATA__ JSON: {e}") from e

    items = _find_item_stack_items(blob)
    if not items:
        return []

    all_listings: list[ContainerListing] = []
    for raw in items:
        listing = _map_item_to_listing(raw)
        if listing is not None:
            all_listings.append(listing)

    if not first_party_only:
        return all_listings[:max_listings]

    first_party = [li for li in all_listings if not li.is_third_party]
    if first_party:
        return first_party[:max_listings]

    # All listings are third-party — return the cheapest one
    if all_listings:
        cheapest = min(all_listings, key=lambda li: li.price)
        return [cheapest]

    return []


def build_success_response(
    query: str,
    listings: list[ContainerListing],
    extraction_time_ms: int,
    source_url: str,
    extraction_method: str,
) -> ContainerResponse:
    """Build a walmart ContainerResponse from parsed listings."""
    return ContainerResponse(
        retailer_id="walmart",
        query=query,
        extraction_time_ms=extraction_time_ms,
        listings=[
            li.model_copy(update={"extraction_method": extraction_method})
            for li in listings
        ],
        metadata=ContainerMetadata(
            url=source_url,
            extracted_at=datetime.now(UTC).isoformat(),
            script_version="walmart-http-0.1.0",
            bot_detected=False,
        ),
    )


def build_error_response(
    query: str,
    code: str,
    message: str,
    extraction_time_ms: int = -1,
    details: dict | None = None,
) -> ContainerResponse:
    """Build a walmart ContainerResponse for an error case."""
    return ContainerResponse(
        retailer_id="walmart",
        query=query,
        extraction_time_ms=extraction_time_ms,
        listings=[],
        metadata=ContainerMetadata(
            extracted_at=datetime.now(UTC).isoformat(),
            bot_detected=(code == "CHALLENGE"),
        ),
        error=ContainerError(
            code=code,
            message=message,
            details=details or {},
        ),
    )


# MARK: - Private helpers


def _find_item_stack_items(blob: object, max_depth: int = 12) -> list[dict]:
    """Walk the __NEXT_DATA__ tree and return the first `itemStacks[*].items` list found."""
    stack: list[tuple[object, int]] = [(blob, 0)]
    while stack:
        node, depth = stack.pop()
        if depth > max_depth:
            continue
        if isinstance(node, dict):
            item_stacks = node.get("itemStacks")
            if isinstance(item_stacks, list):
                for s in item_stacks:
                    if isinstance(s, dict):
                        items = s.get("items")
                        if isinstance(items, list) and items:
                            # Filter out obvious non-products (ads, banners, etc.)
                            return [it for it in items if isinstance(it, dict)]
            for v in node.values():
                stack.append((v, depth + 1))
        elif isinstance(node, list):
            for v in node[:20]:  # cap list traversal
                stack.append((v, depth + 1))
    return []


def _map_item_to_listing(item: dict) -> ContainerListing | None:
    """Map a Walmart __NEXT_DATA__ item dict → ContainerListing, or None if unusable."""
    # Walmart marks ads/sponsored as type != "PRODUCT" or with isAd flags.
    if item.get("__typename") not in (None, "Product", "ProductItem"):
        return None
    if item.get("isSponsoredFlag") is True:
        return None

    name = item.get("name")
    if not isinstance(name, str) or not name.strip():
        return None

    price = _coerce_price(item.get("price") or _nested_price(item))
    if price is None or price <= 0:
        return None

    original = _coerce_price(_nested_original_price(item))

    canonical = item.get("canonicalUrl") or item.get("productPageUrl") or ""
    if canonical and canonical.startswith("/"):
        canonical = f"https://www.walmart.com{canonical}"

    image = _extract_image(item)

    # Walmart returns availability as "IN_STOCK" / "OUT_OF_STOCK" or a bool
    avail_raw = item.get("availabilityStatusV2", {}).get("value") if isinstance(
        item.get("availabilityStatusV2"), dict
    ) else item.get("availabilityStatus")
    is_available = True
    if isinstance(avail_raw, str):
        is_available = avail_raw.upper() == "IN_STOCK"
    elif isinstance(avail_raw, bool):
        is_available = avail_raw

    condition = "new"
    if "Pre-Owned" in name or "Refurbished" in name or "Restored" in name:
        condition = "used"

    # Classify first-party vs third-party seller
    seller_name = item.get("sellerName") or ""
    is_third_party = (
        bool(seller_name.strip())
        and seller_name.strip().lower() not in WALMART_FIRST_PARTY_SELLERS
    )

    return ContainerListing(
        title=name.strip()[:300],
        price=price,
        original_price=original,
        currency="USD",
        url=canonical,
        condition=condition,
        is_available=is_available,
        image_url=image,
        seller=seller_name.strip() or None,
        is_third_party=is_third_party,
        extraction_method="http_next_data",  # overridden by build_success_response
    )


def _coerce_price(raw: object) -> float | None:
    """Coerce a price-like field (int, float, str, or {"price": ...}) to float."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        cleaned = raw.replace("$", "").replace(",", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return None
    if isinstance(raw, dict):
        for key in ("price", "value", "linePrice"):
            if key in raw:
                return _coerce_price(raw[key])
    return None


def _nested_price(item: dict) -> object | None:
    """Walmart sometimes nests the current price under priceInfo.linePrice."""
    info = item.get("priceInfo")
    if isinstance(info, dict):
        line = info.get("linePrice")
        if line is not None:
            return line
        return info.get("currentPrice", {}).get("price") if isinstance(info.get("currentPrice"), dict) else None
    return None


def _nested_original_price(item: dict) -> object | None:
    info = item.get("priceInfo")
    if isinstance(info, dict):
        was = info.get("wasPrice")
        if isinstance(was, dict):
            return was.get("price")
        if was is not None:
            return was
    return None


def _extract_image(item: dict) -> str | None:
    """Extract a product image URL from whatever shape Walmart is using today."""
    img = item.get("imageInfo")
    if isinstance(img, dict):
        url = img.get("thumbnailUrl") or img.get("url")
        if isinstance(url, str) and url:
            return url
    thumb = item.get("image")
    if isinstance(thumb, str) and thumb:
        return thumb
    return None
