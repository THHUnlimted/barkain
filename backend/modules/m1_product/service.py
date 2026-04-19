"""ProductResolutionService — resolves UPC barcodes to canonical products.

Resolution chain:
1. Redis cache (24hr TTL, key: product:upc:{upc})
2. PostgreSQL (products table, query by upc)
3. Cross-validated resolution: Gemini + UPCitemdb second-opinion
4. Raise ProductNotFoundError if all fail

Cross-validation (Step 2b):
- Always calls UPCitemdb after Gemini to verify brand agreement.
- If brands match → trusts Gemini (richer name), enriched with UPCitemdb fields.
- If brands disagree → trusts UPCitemdb (barcode database > search engine).
- Confidence: 1.0 (agree), 0.7 (Gemini only), 0.5 (override), 0.3 (UPCitemdb only).
"""

import hashlib
import logging
import re
import uuid

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ai.abstraction import gemini_generate_json
from ai.prompts.device_to_upc import (
    DEVICE_TO_UPC_SYSTEM_INSTRUCTION,
    build_device_to_upc_prompt,
    build_device_to_upc_retry_prompt,
)
from ai.prompts.upc_lookup import (
    UPC_LOOKUP_SYSTEM_INSTRUCTION,
    build_upc_lookup_prompt,
    build_upc_retry_prompt,
)
from modules.m1_product.models import Product
from modules.m1_product.upcitemdb import lookup_upc as upcitemdb_lookup

logger = logging.getLogger("barkain.m1")

REDIS_CACHE_TTL = 86400  # 24 hours
REDIS_KEY_PREFIX = "product:upc:"

# Cache for `resolve_from_search` device-name → UPC lookups. Keyed by a
# normalized name+brand digest so that "Steam Deck OLED" and "  steam DECK
# oled  " hit the same entry. Spares the UPCitemdb trial endpoint (shared-IP
# rate limit) on retry, and skips the Gemini round-trip entirely on cache hits.
DEVUPC_CACHE_KEY_PREFIX = "product:devupc:"
DEVUPC_CACHE_TTL = 86400  # 24 hours


_UPC_RE = re.compile(r"^\d{12,13}$")


class ProductNotFoundError(Exception):
    """Raised when no source can resolve a UPC."""

    def __init__(self, upc: str):
        self.upc = upc
        super().__init__(f"No product found for UPC {upc}")


class UPCNotFoundForDescriptionError(Exception):
    """Raised when Gemini cannot resolve a device description to a UPC.

    Distinct from ``ProductNotFoundError`` (which means the UPC existed but
    no source identified a product) — here the UPC itself could not be
    derived from the description. The router maps this to HTTP 404 with a
    specific error code so the iOS client can surface a clearer message
    than the generic "product not found".
    """

    def __init__(self, device_name: str):
        self.device_name = device_name
        super().__init__(f"No UPC found for product description: {device_name!r}")


class ProductResolutionService:
    """Resolves a UPC barcode to a canonical Product record."""

    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self.db = db
        self.redis = redis

    async def resolve_from_search(
        self,
        device_name: str,
        brand: str | None = None,
        model: str | None = None,
    ) -> Product:
        """Resolve a Gemini-sourced search result (no UPC yet) to a canonical Product.

        Resolution order:
        0. Redis device→UPC cache (24h TTL) — short-circuits both network calls
           on retries of the same name+brand pair.
        1. Targeted Gemini ``device → UPC`` lookup (fast, opinionated).
        2. UPCitemdb keyword search filtered by brand match (broader catalog;
           catches products like "iPhone 12" where Gemini refuses to commit
           to a single UPC because Apple SKUs vary by carrier/storage/color).

        Then delegates to :meth:`resolve` for the standard Gemini + UPCitemdb
        cross-validation and Redis caching paths.

        Raises:
            UPCNotFoundForDescriptionError: neither stage produced a UPC.
            ProductNotFoundError: UPC was derived but no source identified a product.
        """
        cache_key = self._devupc_cache_key(device_name, brand)
        cached_upc = await self._get_cached_devupc(cache_key)
        if cached_upc:
            logger.info(
                "device→UPC cache hit: %r (brand=%s) → %s", device_name, brand, cached_upc
            )
            return await self.resolve(cached_upc)

        upc = await self._lookup_upc_from_description(device_name, brand, model)
        if not upc:
            upc = await self._lookup_upc_from_upcitemdb(device_name, brand)
        if not upc:
            raise UPCNotFoundForDescriptionError(device_name)

        await self._cache_devupc(cache_key, upc)
        return await self.resolve(upc)

    @staticmethod
    def _devupc_cache_key(device_name: str, brand: str | None) -> str:
        """Build a stable Redis key from a (device_name, brand) pair.

        Normalizes whitespace + casing so trivially different inputs
        ("Steam Deck OLED" vs " steam  deck  oled ") share an entry. SHA-1
        keeps the key short, predictable, and free of redis-special chars.
        """
        normalized = " ".join((device_name or "").lower().split())
        brand_norm = " ".join((brand or "").lower().split())
        digest = hashlib.sha1(
            f"{normalized}|{brand_norm}".encode("utf-8")
        ).hexdigest()
        return f"{DEVUPC_CACHE_KEY_PREFIX}{digest}"

    async def _get_cached_devupc(self, cache_key: str) -> str | None:
        """Fetch a cached UPC for a normalized device-name key, or None on miss."""
        try:
            cached = await self.redis.get(cache_key)
        except Exception:
            logger.warning("device→UPC cache read failed for %s", cache_key, exc_info=True)
            return None
        if not cached:
            return None
        return cached if isinstance(cached, str) else cached.decode()

    async def _cache_devupc(self, cache_key: str, upc: str) -> None:
        """Store a successful device→UPC mapping with the standard TTL."""
        try:
            await self.redis.set(cache_key, upc, ex=DEVUPC_CACHE_TTL)
        except Exception:
            logger.warning("device→UPC cache write failed for %s", cache_key, exc_info=True)

    async def _lookup_upc_from_upcitemdb(
        self, device_name: str, brand: str | None
    ) -> str | None:
        """Brand-filtered UPCitemdb keyword fallback.

        Picks the first row whose brand matches (case-insensitive) AND whose
        title contains the device name's distinctive tokens. Returns None on
        rate-limit / network error / no acceptable match — the caller treats
        absence and failure identically.
        """
        from modules.m1_product import upcitemdb  # local: avoid circular import

        try:
            rows = await upcitemdb.search_keyword(device_name, max_results=15)
        except Exception:
            logger.warning("UPCitemdb fallback failed for %r", device_name, exc_info=True)
            return None
        if not rows:
            return None
        target_brand = (brand or "").strip().lower()
        # Pull longest non-trivial token from device name to gate accessory noise.
        tokens = [t for t in device_name.lower().split() if len(t) >= 4]
        for row in rows:
            row_brand = (row.get("brand") or "").strip().lower()
            row_title = (row.get("device_name") or "").lower()
            if target_brand and row_brand != target_brand:
                continue
            if tokens and not any(t in row_title for t in tokens):
                continue
            upc = row.get("primary_upc")
            if upc:
                logger.info(
                    "UPCitemdb resolved device→UPC: %r (brand=%s) → %s",
                    device_name, brand, upc,
                )
                return upc
        return None

    async def _lookup_upc_from_description(
        self,
        device_name: str,
        brand: str | None,
        model: str | None,
    ) -> str | None:
        """Call Gemini to convert a device description into a canonical UPC.

        Retries once with a broader prompt if the first attempt returns
        null. Returns a validated 12/13-digit string or None.
        """
        try:
            prompt = build_device_to_upc_prompt(device_name, brand, model)
            raw = await gemini_generate_json(
                prompt,
                system_instruction=DEVICE_TO_UPC_SYSTEM_INSTRUCTION,
            )
            upc = _extract_upc(raw)

            if not upc:
                logger.info(
                    "Gemini returned null UPC for device %r, retrying", device_name
                )
                retry = build_device_to_upc_retry_prompt(device_name, brand, model)
                raw = await gemini_generate_json(
                    retry,
                    system_instruction=DEVICE_TO_UPC_SYSTEM_INSTRUCTION,
                )
                upc = _extract_upc(raw)

            if upc:
                logger.info("Gemini resolved device→UPC: %r → %s", device_name, upc)
            else:
                logger.info(
                    "Gemini could not resolve device→UPC after retry: %r", device_name
                )
            return upc
        except Exception:
            logger.warning(
                "Gemini device→UPC lookup failed for %r", device_name, exc_info=True
            )
            return None

    async def resolve(self, upc: str) -> Product:
        """Resolve a UPC to a Product, checking all sources in order.

        Args:
            upc: Validated 12-13 digit UPC string.

        Returns:
            Product ORM instance (existing or newly created).

        Raises:
            ProductNotFoundError: If no source can resolve the UPC.
        """
        # Step 1: Redis cache
        product = await self._check_redis(upc)
        if product:
            logger.info("Product resolved from Redis cache: upc=%s", upc)
            return product

        # Step 2: PostgreSQL
        product = await self._check_postgres(upc)
        if product:
            logger.info("Product resolved from PostgreSQL: upc=%s", upc)
            await self._cache_to_redis(upc, product)
            return product

        # Step 3: Cross-validated resolution (Gemini + UPCitemdb)
        product = await self._resolve_with_cross_validation(upc)
        if product:
            return product

        # Step 4: All sources exhausted
        raise ProductNotFoundError(upc)

    # MARK: - Cache Checks

    async def _check_redis(self, upc: str) -> Product | None:
        """Check Redis for a cached product UUID, then load from DB."""
        cached = await self.redis.get(f"{REDIS_KEY_PREFIX}{upc}")
        if not cached:
            return None

        product_id = cached if isinstance(cached, str) else cached.decode()
        try:
            parsed_id = uuid.UUID(product_id)
        except ValueError:
            await self.redis.delete(f"{REDIS_KEY_PREFIX}{upc}")
            return None

        result = await self.db.execute(
            select(Product).where(Product.id == parsed_id)
        )
        product = result.scalar_one_or_none()

        if not product:
            # Stale cache — product was deleted
            await self.redis.delete(f"{REDIS_KEY_PREFIX}{upc}")
        return product

    async def _check_postgres(self, upc: str) -> Product | None:
        """Query products table by UPC."""
        result = await self.db.execute(
            select(Product).where(Product.upc == upc)
        )
        return result.scalar_one_or_none()

    # MARK: - Cross-Validated Resolution

    async def _resolve_with_cross_validation(self, upc: str) -> Product | None:
        """Resolve UPC by querying Gemini and UPCitemdb, then cross-validating.

        Always attempts both sources for maximum accuracy. Falls back gracefully
        when one or both fail.
        """
        gemini_data = await self._get_gemini_data(upc)
        upcitemdb_data = await self._get_upcitemdb_data(upc)

        result = self._cross_validate(gemini_data, upcitemdb_data)
        if result is None:
            return None

        product_data, confidence, source_label = result

        # Pull gemini_model out of product_data so it doesn't leak into
        # _persist_product (Product has no `model` column — it lives in source_raw).
        gemini_model = product_data.pop("gemini_model", None)

        # Store both raw responses and confidence in source_raw.
        # Use shallow copies to avoid circular references (product_data may
        # BE one of the raw dicts when _cross_validate returns it directly).
        product_data["source_raw"] = {
            "confidence": confidence,
            "gemini_model": gemini_model,
            "gemini_raw": dict(gemini_data) if gemini_data else None,
            "upcitemdb_raw": dict(upcitemdb_data) if upcitemdb_data else None,
        }

        logger.info(
            "Product resolved via %s (confidence=%.1f): upc=%s name=%s",
            source_label, confidence, upc, product_data.get("name", "?"),
        )
        return await self._persist_product(upc, product_data, source_label)

    async def _get_gemini_data(self, upc: str) -> dict | None:
        """Call Gemini API to resolve UPC. Returns raw dict or None.

        Retries once with a broader prompt if the first attempt returns null.
        """
        try:
            prompt = build_upc_lookup_prompt(upc)
            raw = await gemini_generate_json(
                prompt,
                system_instruction=UPC_LOOKUP_SYSTEM_INSTRUCTION,
            )

            device_name = raw.get("device_name")
            model = raw.get("model")

            # Retry once with broader prompt if null
            if not device_name:
                logger.info("Gemini returned null for UPC %s, retrying with broader prompt", upc)
                retry_prompt = build_upc_retry_prompt(upc)
                raw = await gemini_generate_json(
                    retry_prompt,
                    system_instruction=UPC_LOOKUP_SYSTEM_INSTRUCTION,
                )
                device_name = raw.get("device_name")
                model = raw.get("model")

            if not device_name:
                logger.info("Gemini could not identify UPC %s after retry", upc)
                return None

            return {"name": device_name, "gemini_model": model}
        except Exception:
            logger.warning(
                "Gemini resolution failed for UPC %s", upc, exc_info=True
            )
            return None

    async def _get_upcitemdb_data(self, upc: str) -> dict | None:
        """Call UPCitemdb API. Returns structured dict with name/brand/category or None."""
        try:
            data = await upcitemdb_lookup(upc)
            if not data or not data.get("name"):
                return None
            return data
        except Exception:
            logger.warning(
                "UPCitemdb resolution failed for UPC %s", upc, exc_info=True
            )
            return None

    @staticmethod
    def _cross_validate(
        gemini_data: dict | None,
        upcitemdb_data: dict | None,
    ) -> tuple[dict, float, str] | None:
        """Compare Gemini and UPCitemdb results, pick the winner.

        Returns:
            (product_data, confidence, source_label) or None if both failed.
        """
        if gemini_data and upcitemdb_data:
            # Both sources returned data — check brand agreement
            upcitemdb_brand = (upcitemdb_data.get("brand") or "").strip()
            gemini_name = gemini_data.get("name", "")

            if upcitemdb_brand and upcitemdb_brand.lower() in gemini_name.lower():
                # Brands agree — trust Gemini name, enrich with UPCitemdb fields
                return (
                    {
                        "name": gemini_name,
                        "gemini_model": gemini_data.get("gemini_model"),
                        "brand": upcitemdb_data.get("brand"),
                        "category": upcitemdb_data.get("category"),
                        "description": upcitemdb_data.get("description"),
                        "image_url": upcitemdb_data.get("image_url"),
                        "asin": upcitemdb_data.get("asin"),
                    },
                    1.0,
                    "gemini_validated",
                )
            else:
                # Brands disagree — trust UPCitemdb (barcode DB > search engine)
                return (upcitemdb_data, 0.5, "upcitemdb_override")

        if gemini_data:
            # Gemini only — UPCitemdb returned nothing
            return (gemini_data, 0.7, "gemini_upc")

        if upcitemdb_data:
            # UPCitemdb only — Gemini failed
            return (upcitemdb_data, 0.3, "upcitemdb")

        # Both failed
        return None

    # MARK: - Persistence

    async def _persist_product(
        self, upc: str, data: dict, source: str
    ) -> Product:
        """Create or fetch a Product record and cache to Redis.

        Handles concurrent insert race conditions via IntegrityError.
        """
        product = Product(
            upc=upc,
            name=data["name"],
            brand=data.get("brand"),
            category=data.get("category"),
            description=data.get("description"),
            image_url=data.get("image_url"),
            asin=data.get("asin"),
            source=source,
            source_raw=data.get("source_raw", data),
        )
        self.db.add(product)

        try:
            await self.db.flush()
        except IntegrityError:
            # Concurrent insert for same UPC — load the existing record.
            # SAFETY(D5): This rollback is safe. We use flush() (not commit()),
            # so the outer session lifecycle in get_db() is unaffected — get_db()
            # will still commit or rollback the full transaction. The rollback
            # here only clears the failed flush within the same transaction.
            await self.db.rollback()
            existing = await self._check_postgres(upc)
            if existing:
                await self._cache_to_redis(upc, existing)
                return existing
            raise  # Should not happen, but re-raise if it does

        await self._cache_to_redis(upc, product)
        return product

    async def _cache_to_redis(self, upc: str, product: Product) -> None:
        """Cache product UUID in Redis with 24hr TTL."""
        await self.redis.set(
            f"{REDIS_KEY_PREFIX}{upc}",
            str(product.id),
            ex=REDIS_CACHE_TTL,
        )


def _extract_upc(raw) -> str | None:
    """Pull a validated 12/13-digit UPC string out of a Gemini device→UPC response.

    Gemini may return ``{"upc": "0279..."}`` or a bare dict shaped slightly
    differently on retry. Be defensive: unwrap, coerce to str, validate with
    the same regex the resolve request uses, reject anything else.
    """
    if not isinstance(raw, dict):
        return None
    candidate = raw.get("upc")
    if candidate is None:
        return None
    if not isinstance(candidate, str):
        candidate = str(candidate)
    candidate = candidate.strip()
    if not _UPC_RE.match(candidate):
        return None
    return candidate
