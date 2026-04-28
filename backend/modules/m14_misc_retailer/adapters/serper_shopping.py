"""Primary adapter — Serper Shopping API wrapper (Step 3n).

Calls the thumbnail-stripped `_serper_shopping_fetch` helper in
`backend/ai/web_search.py` and normalizes the structured items into
`MiscMerchantRow` instances. No filtering, no cap — both happen one
layer up in `MiscRetailerService`.

Empirical baseline (v3 investigation, 2026-04-27, 5 calls):
- p50 1.7 s, range 1.4–2.5 s
- 19–40 items per call, 78 unique retailers across 209 items
- 85.6 % of items came from non-Barkain-scraped retailers
- 2 credits per call ($0.002 at Starter pricing)
"""

from __future__ import annotations

import logging
import re

from ai.web_search import _serper_shopping_fetch
from modules.m14_misc_retailer.adapters.base import MiscRetailerAdapter
from modules.m14_misc_retailer.schemas import MiscMerchantRow

logger = logging.getLogger("barkain.m14.serper_shopping")


# 3n: Price strings come back as "$20.98", "$1,049.00", "$0.99", and rare
# unparseable tokens like "Free", "$Free", or empty. The cents value
# becomes the primary sort key on the iOS layer; unparseable falls
# through to None and sorts last.
_PRICE_RE = re.compile(r"\$\s*([\d,]+(?:\.\d{1,2})?)")


def _parse_price_cents(raw: object) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        try:
            return int(round(float(raw) * 100))
        except (ValueError, OverflowError):
            return None
    if not isinstance(raw, str):
        return None
    match = _PRICE_RE.search(raw)
    if not match:
        return None
    try:
        return int(round(float(match.group(1).replace(",", "")) * 100))
    except ValueError:
        return None


def _normalize_source(raw: object) -> str:
    if not isinstance(raw, str):
        return ""
    return " ".join(raw.lower().split())


def _coerce_int(raw: object) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        try:
            return int(raw)
        except (ValueError, OverflowError):
            return None
    if isinstance(raw, str):
        try:
            return int(raw.replace(",", "").strip())
        except ValueError:
            return None
    return None


def _coerce_float(raw: object) -> float | None:
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        try:
            return float(raw.strip())
        except ValueError:
            return None
    return None


class SerperShoppingAdapter(MiscRetailerAdapter):
    async def fetch(self, query: str) -> list[MiscMerchantRow]:
        items = await _serper_shopping_fetch(query)
        if items is None:
            logger.info(
                "SerperShoppingAdapter: helper returned None for query %r — degrading to empty list",
                query,
            )
            return []

        rows: list[MiscMerchantRow] = []
        for idx, item in enumerate(items, start=1):
            title = item.get("title")
            source = item.get("source")
            link = item.get("link")
            if not isinstance(title, str) or not title.strip():
                continue
            if not isinstance(source, str) or not source.strip():
                continue
            if not isinstance(link, str) or not link.startswith(("http://", "https://")):
                continue
            position_raw = item.get("position")
            position = _coerce_int(position_raw)
            if position is None:
                position = idx
            rows.append(
                MiscMerchantRow(
                    title=title.strip(),
                    source=source.strip(),
                    source_normalized=_normalize_source(source),
                    link=link,
                    price=str(item.get("price") or ""),
                    price_cents=_parse_price_cents(item.get("price")),
                    rating=_coerce_float(item.get("rating")),
                    rating_count=_coerce_int(item.get("ratingCount")),
                    product_id=item.get("productId") if isinstance(item.get("productId"), str) else None,
                    position=position,
                )
            )
        return rows
