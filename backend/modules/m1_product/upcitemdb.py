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
        images = item.get("images", [])

        return {
            "name": item.get("title", ""),
            "brand": item.get("brand", ""),
            "category": item.get("category", ""),
            "description": item.get("description", ""),
            "asin": item.get("asin"),
            "image_url": images[0] if images else None,
        }
    except Exception:
        logger.warning("UPCitemdb lookup failed for UPC %s", upc, exc_info=True)
        return None
