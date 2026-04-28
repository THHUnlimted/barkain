"""MiscRetailerService — Step 3n M14 misc-retailer slot.

Single-vendor (Serper Shopping) wrapper that fills the 10th data-source
slot in `PriceComparisonView` with merchants Barkain doesn't directly
scrape. Pipeline:

  1. Validate product exists in PG.
  2. Read Redis cache (`misc:{product_id}`, 6h TTL) → return hit.
  3. Read inflight key (`misc:inflight:{product_id}`, 30s TTL) → return
     partial state instead of double-dispatching the Serper call.
  4. Resolve query (override > product.name).
  5. Dispatch to the configured adapter (`MISC_RETAILER_ADAPTER`).
  6. Filter rows whose `source_normalized` matches a Barkain-scraped
     retailer (or its `*_direct` mirror) — `KNOWN_RETAILER_DOMAINS`.
  7. Cap to top-3 by `position`.
  8. Write Redis cache (canonical) + clear inflight.

Cache + inflight helpers live in this file directly, matching the
`m2_prices`/`m13_portal` precedent (PR #73 inflight code is in
`m2_prices/service.py`, not a separate `cache.py`). Inflight TTL is
30s — sized for Serper's 1.4–2.5 s p50, NOT the 120 s `m2_prices` uses
for the 9-scraper SSE fan-out where Best Buy can hit ~91 s p95.

Soft-fails Redis throughout. The slot is a "nice to have" enhancement;
a Redis outage degrades it to "no rows" rather than breaking the
price-comparison view.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from modules.m1_product.models import Product
from modules.m14_misc_retailer.adapters.base import MiscRetailerAdapter
from modules.m14_misc_retailer.schemas import MiscMerchantRow

if TYPE_CHECKING:
    pass

logger = logging.getLogger("barkain.m14")


# MARK: - Constants

MISC_REDIS_KEY_PREFIX = "misc:"
MISC_REDIS_INFLIGHT_KEY_PREFIX = "misc:inflight:"
MISC_REDIS_QUERY_SUFFIX = ":q:"

# 6 hours — same scale as the m2_prices canonical price cache. The cost
# of stale rows is "user sees a Chewy price that has since shifted by a
# dollar"; the cost of refreshing too often is Serper credit burn.
MISC_REDIS_CACHE_TTL_SEC = 6 * 3600

# 30 seconds — sized for Serper Shopping's 1.4–2.5 s p50 wall-clock.
# Singleflight window only needs to outlive a single Serper call; longer
# TTLs (the 120 s m2_prices uses) just retain stale partial state.
MISC_REDIS_INFLIGHT_TTL_SEC = 30

# Hard cap on rows surfaced to iOS. Three is the §Locked Decisions item
# 2 default; bumping requires a UX call. Server-side cap so an iOS bug
# can't accidentally render more than the agreed number.
MISC_MAX_ROWS = 3


# MARK: - Known-retailer filter
#
# 9 already-scraped retailers (post-2026-04-18 lowes/sams_club retirement)
# plus their direct-mirror identity-redirect targets (kept `is_active=True`
# for portal redirects but not scraped). Any Serper Shopping row whose
# `source_normalized` contains one of these tokens is dropped server-side
# before it reaches Redis cache or iOS — the slot exists to cover what
# Barkain doesn't already.
#
# Substring match by design: "Walmart" matches, "Walmart Business" matches,
# "Best Buy Outlet" matches "best buy", and Serper's source field uses the
# merchant display name (not the bare domain) so the tokens include both
# domain forms ("amazon.com") and display forms ("amazon", "best buy").

KNOWN_RETAILER_DOMAINS: frozenset[str] = frozenset({
    "amazon.com",
    "amazon",
    "bestbuy.com",
    "best buy",
    "walmart.com",
    "walmart",
    "target.com",
    "target",
    "homedepot.com",
    "home depot",
    "ebay.com",
    "ebay",
    "backmarket.com",
    "back market",
    "backmarket",
    "facebook.com",
    "facebook marketplace",
    "fb marketplace",
})


def is_known_retailer(source_normalized: str) -> bool:
    """True when Serper's `source` (already lowercase + whitespace-collapsed)
    matches a Barkain-scraped retailer or one of its mirrors. Substring
    containment — see module docstring for rationale."""
    if not source_normalized:
        return False
    return any(known in source_normalized for known in KNOWN_RETAILER_DOMAINS)


# MARK: - Adapter dispatch


def _build_adapter(mode: str) -> MiscRetailerAdapter:
    """Resolve `MISC_RETAILER_ADAPTER` to a live adapter instance.

    Unknown values fall through to the disabled adapter — same posture
    as `WALMART_ADAPTER`. The standby + fallback adapters return real
    instances whose `fetch()` raises NotImplementedError; this is
    deliberate so an accidental flag-flip is loud, not silently empty.
    """
    if mode == "serper_shopping":
        from modules.m14_misc_retailer.adapters.serper_shopping import (
            SerperShoppingAdapter,
        )
        return SerperShoppingAdapter()
    if mode == "google_shopping_container":
        from modules.m14_misc_retailer.adapters.google_shopping_container import (
            GoogleShoppingContainerAdapter,
        )
        return GoogleShoppingContainerAdapter()
    if mode == "decodo_serp_api":
        from modules.m14_misc_retailer.adapters.decodo_serp_api import (
            DecodoSerpApiAdapter,
        )
        return DecodoSerpApiAdapter()
    if mode == "oxylabs_serp_api":
        from modules.m14_misc_retailer.adapters.oxylabs_serp_api import (
            OxylabsSerpApiAdapter,
        )
        return OxylabsSerpApiAdapter()
    if mode == "brightdata_serp_api":
        from modules.m14_misc_retailer.adapters.brightdata_serp_api import (
            BrightDataSerpApiAdapter,
        )
        return BrightDataSerpApiAdapter()
    if mode != "disabled":
        logger.warning(
            "Unknown MISC_RETAILER_ADAPTER value %r — defaulting to disabled",
            mode,
        )
    from modules.m14_misc_retailer.adapters.disabled import DisabledAdapter
    return DisabledAdapter()


# MARK: - Errors


class ProductNotFoundError(Exception):
    """Raised when the requested product_id does not exist."""

    def __init__(self, product_id: uuid.UUID):
        self.product_id = product_id
        super().__init__(f"No product found with id {product_id}")


# MARK: - Service


class MiscRetailerService:
    """Resolve the misc-retailer slot for a single product.

    Construct per-request alongside an `AsyncSession` and a Redis client.
    Stateless apart from the injected dependencies; safe to instantiate
    in routers, workers, and the bench harness.
    """

    def __init__(
        self,
        db: AsyncSession,
        redis: aioredis.Redis,
        *,
        adapter: MiscRetailerAdapter | None = None,
    ):
        self.db = db
        self.redis = redis
        self.adapter = adapter or _build_adapter(settings.MISC_RETAILER_ADAPTER)

    # MARK: - Public API

    async def get_misc_retailers(
        self,
        product_id: uuid.UUID,
        *,
        query_override: str | None = None,
        force_refresh: bool = False,
    ) -> list[MiscMerchantRow]:
        """Resolve the misc-retailer slot, batch-shaped (no SSE)."""
        product = await self._validate_product(product_id)

        if not force_refresh:
            cached = await self._read_cache(product_id, query_override)
            if cached is not None:
                logger.info(
                    "misc cache hit (Redis) product=%s rows=%d",
                    product_id, len(cached),
                )
                return cached

            inflight = await self._read_inflight(product_id, query_override)
            if inflight is not None:
                logger.info(
                    "misc cache hit (inflight) product=%s rows=%d",
                    product_id, len(inflight),
                )
                return inflight

        query = (query_override or product.name or "").strip()
        if not query:
            return []

        await self._write_inflight(product_id, query_override, [])

        try:
            raw_rows = await self.adapter.fetch(query)
        except NotImplementedError:
            # The standby/fallback stubs raise this on purpose. Surface to
            # the caller so a misconfigured adapter is loud — but clean up
            # the inflight marker first so we don't leave a 30 s hold.
            await self._clear_inflight(product_id, query_override)
            raise
        except Exception:
            logger.exception(
                "misc adapter %s raised — degrading to empty list",
                type(self.adapter).__name__,
            )
            raw_rows = []

        filtered = [r for r in raw_rows if not is_known_retailer(r.source_normalized)]
        filtered.sort(key=lambda r: r.position)
        capped = filtered[:MISC_MAX_ROWS]

        await self._write_cache(product_id, query_override, capped)
        await self._clear_inflight(product_id, query_override)
        return capped

    async def stream_misc_retailers(
        self,
        product_id: uuid.UUID,
        *,
        query_override: str | None = None,
        force_refresh: bool = False,
    ) -> AsyncGenerator[tuple[str, dict], None]:
        """SSE-shaped variant.

        Serper Shopping is a single-call API — there's no per-merchant
        progress to stream. We yield each capped row as a `merchant_row`
        event for iOS-side parity with `m2_prices.stream_prices`, then
        close with a `done` event carrying the full row list.
        """
        rows = await self.get_misc_retailers(
            product_id,
            query_override=query_override,
            force_refresh=force_refresh,
        )
        for row in rows:
            yield "merchant_row", row.model_dump()
        yield "done", {
            "product_id": str(product_id),
            "rows": [r.model_dump() for r in rows],
            "cached": False,
            "fetched_at": datetime.now(UTC).isoformat(),
        }

    # MARK: - Product validation

    async def _validate_product(self, product_id: uuid.UUID) -> Product:
        result = await self.db.execute(select(Product).where(Product.id == product_id))
        product = result.scalar_one_or_none()
        if product is None:
            raise ProductNotFoundError(product_id)
        return product

    # MARK: - Cache helpers
    #
    # Mirrored from m2_prices/service.py PR #73 (`_inflight_key`,
    # `_write_inflight`, `_check_inflight`, `_clear_inflight`) but with the
    # `misc:` prefix and the smaller 30 s inflight TTL.

    @staticmethod
    def _query_digest(query_override: str | None) -> str:
        if not query_override:
            return ""
        normalized = " ".join(query_override.lower().split())
        return hashlib.sha1(normalized.encode("utf-8")).hexdigest()

    @classmethod
    def _cache_key(
        cls,
        product_id: uuid.UUID,
        query_override: str | None,
    ) -> str:
        key = f"{MISC_REDIS_KEY_PREFIX}{product_id}"
        if query_override:
            key += f"{MISC_REDIS_QUERY_SUFFIX}{cls._query_digest(query_override)}"
        return key

    @classmethod
    def _inflight_key(
        cls,
        product_id: uuid.UUID,
        query_override: str | None,
    ) -> str:
        key = f"{MISC_REDIS_INFLIGHT_KEY_PREFIX}{product_id}"
        if query_override:
            key += f"{MISC_REDIS_QUERY_SUFFIX}{cls._query_digest(query_override)}"
        return key

    async def _read_cache(
        self,
        product_id: uuid.UUID,
        query_override: str | None,
    ) -> list[MiscMerchantRow] | None:
        key = self._cache_key(product_id, query_override)
        try:
            raw = await self.redis.get(key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("misc cache read failed for %s: %s", product_id, exc)
            return None
        if raw is None:
            return None
        try:
            payload = json.loads(raw if isinstance(raw, str) else raw.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.warning("misc cache JSON decode failed for %s", product_id)
            return None
        if not isinstance(payload, list):
            return None
        rows: list[MiscMerchantRow] = []
        for entry in payload:
            try:
                rows.append(MiscMerchantRow.model_validate(entry))
            except Exception:  # noqa: BLE001
                continue
        return rows

    async def _write_cache(
        self,
        product_id: uuid.UUID,
        query_override: str | None,
        rows: list[MiscMerchantRow],
    ) -> None:
        key = self._cache_key(product_id, query_override)
        serialized = json.dumps([r.model_dump() for r in rows])
        try:
            await self.redis.set(key, serialized, ex=MISC_REDIS_CACHE_TTL_SEC)
        except Exception as exc:  # noqa: BLE001
            logger.warning("misc cache write failed for %s: %s", product_id, exc)

    async def _write_inflight(
        self,
        product_id: uuid.UUID,
        query_override: str | None,
        rows: list[MiscMerchantRow],
    ) -> None:
        """Pre-yield ordering (PR #73): write the inflight key BEFORE the
        adapter call so a parallel `get_misc_retailers` reads "stream in
        flight" instead of double-dispatching to Serper."""
        key = self._inflight_key(product_id, query_override)
        serialized = json.dumps([r.model_dump() for r in rows])
        try:
            await self.redis.set(key, serialized, ex=MISC_REDIS_INFLIGHT_TTL_SEC)
        except Exception as exc:  # noqa: BLE001
            logger.warning("misc inflight write failed for %s: %s", product_id, exc)

    async def _read_inflight(
        self,
        product_id: uuid.UUID,
        query_override: str | None,
    ) -> list[MiscMerchantRow] | None:
        key = self._inflight_key(product_id, query_override)
        try:
            raw = await self.redis.get(key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("misc inflight read failed for %s: %s", product_id, exc)
            return None
        if raw is None:
            return None
        try:
            payload = json.loads(raw if isinstance(raw, str) else raw.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        if not isinstance(payload, list):
            return []
        rows: list[MiscMerchantRow] = []
        for entry in payload:
            try:
                rows.append(MiscMerchantRow.model_validate(entry))
            except Exception:  # noqa: BLE001
                continue
        return rows

    async def _clear_inflight(
        self,
        product_id: uuid.UUID,
        query_override: str | None,
    ) -> None:
        key = self._inflight_key(product_id, query_override)
        try:
            await self.redis.delete(key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("misc inflight clear failed for %s: %s", product_id, exc)
