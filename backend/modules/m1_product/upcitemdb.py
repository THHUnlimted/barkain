"""UPCitemdb API client — backup source for UPC product resolution.

Free tier: 100 requests/day. Used only when Gemini API fails.
"""

import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger("barkain.m1")

UPCITEMDB_TRIAL_URL = "https://api.upcitemdb.com/prod/trial/lookup"
UPCITEMDB_PAID_URL = "https://api.upcitemdb.com/prod/v1/lookup"
UPCITEMDB_TRIAL_SEARCH_URL = "https://api.upcitemdb.com/prod/trial/search"
UPCITEMDB_PAID_SEARCH_URL = "https://api.upcitemdb.com/prod/v1/search"
TIMEOUT_SECONDS = 10


async def lookup_upc(upc: str) -> dict[str, Any] | None:
    """Look up a UPC via UPCitemdb API.

    Args:
        upc: A 12 or 13 digit UPC/EAN barcode string.

    Returns:
        Dict with product fields (name, brand, category, description,
        asin, image_url) or None if not found or API error.
    """
    if settings.UPCITEMDB_API_KEY:
        url = UPCITEMDB_PAID_URL
        headers = {"user_key": settings.UPCITEMDB_API_KEY}
    else:
        url = UPCITEMDB_TRIAL_URL
        headers = {}

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            resp = await client.get(
                url,
                params={"upc": upc},
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()

        items = data.get("items", [])
        if not items:
            logger.warning("UPCitemdb returned no items for UPC %s", upc)
            return None

        item = items[0]
        images = [u for u in (item.get("images") or []) if isinstance(u, str) and u]

        return {
            "name": item.get("title", ""),
            "brand": item.get("brand", ""),
            "category": item.get("category", ""),
            "description": item.get("description", ""),
            "asin": item.get("asin"),
            "image_url": images[0] if images else None,
            # Full list (deduped, non-empty) so callers can fall back when
            # images[0] 404s. Persisted into source_raw, not Product.image_url.
            "image_urls": images,
            "model": (item.get("model") or "").strip() or None,
        }
    except httpx.HTTPStatusError as e:
        # 400/404 from upstream is expected for food UPCs, malformed
        # 13-digit EANs, etc. Log status + body snippet without the full
        # traceback — otherwise every unknown UPC spams the log with a
        # 10-line stack.
        body = (e.response.text or "")[:120]
        logger.warning(
            "UPCitemdb HTTP %d for UPC %s (body=%r)",
            e.response.status_code, upc, body,
        )
        return None
    except Exception:
        logger.warning("UPCitemdb lookup failed for UPC %s", upc, exc_info=True)
        return None


async def search_keyword(query: str, max_results: int = 10) -> list[dict[str, Any]]:
    """Keyword search via UPCitemdb `/search` endpoint.

    Trial endpoint allows no key but is rate-capped (~100/day shared IP);
    paid endpoint via `UPCITEMDB_API_KEY` is 5k/day. Returns a list of dicts
    shaped for `ProductSearchService._merge` (device_name/brand/category
    /primary_upc/image_url/confidence). Empty list on any failure — caller
    treats absence and error identically.

    `match_mode=1` (exact word match) cuts the worst accessory noise vs
    `match_mode=0`'s loose contains-match. Result ordering is by relevance
    inside the API.
    """
    if settings.UPCITEMDB_API_KEY:
        url = UPCITEMDB_PAID_SEARCH_URL
        headers = {"user_key": settings.UPCITEMDB_API_KEY}
    else:
        url = UPCITEMDB_TRIAL_SEARCH_URL
        headers = {}

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            resp = await client.get(
                url,
                params={"s": query, "match_mode": 1},
                headers=headers,
            )
        if resp.status_code == 429:
            logger.warning("UPCitemdb search rate-limited for %r", query)
            return []
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as e:
        body = (e.response.text or "")[:120]
        logger.warning(
            "UPCitemdb search HTTP %d for %r (body=%r)",
            e.response.status_code, query, body,
        )
        return []
    except Exception:
        logger.warning("UPCitemdb search failed for %r", query, exc_info=True)
        return []

    items = data.get("items") or []
    rows: list[dict[str, Any]] = []
    for item in items[:max_results]:
        title = (item.get("title") or "").strip()
        if not title:
            continue
        images = item.get("images") or []
        rows.append({
            "device_name": title,
            "brand": (item.get("brand") or "").strip() or None,
            "category": (item.get("category") or "").strip() or None,
            "primary_upc": item.get("upc"),
            "image_url": images[0] if images else None,
            "model": (item.get("model") or "").strip() or None,
            # Cap UPCitemdb confidence below Best Buy's floor (0.5) so they
            # sort beneath BBY rows when both make it past dedup.
            "confidence": max(0.3, 0.5 - 0.02 * len(rows)),
        })
    return rows
