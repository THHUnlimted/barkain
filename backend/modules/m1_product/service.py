"""ProductResolutionService — resolves UPC barcodes to canonical products.

Resolution chain:
1. Redis cache (24hr TTL, key: product:upc:{upc})
2. PostgreSQL (products table, query by upc)
3. Gemini API (via ai.abstraction)
4. UPCitemdb API (backup, free 100/day)
5. Raise ProductNotFoundError if all fail
"""

import logging
import uuid

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ai.abstraction import gemini_generate_json
from ai.prompts.upc_lookup import build_upc_lookup_prompt
from modules.m1_product.models import Product
from modules.m1_product.upcitemdb import lookup_upc as upcitemdb_lookup

logger = logging.getLogger("barkain.m1")

REDIS_CACHE_TTL = 86400  # 24 hours
REDIS_KEY_PREFIX = "product:upc:"


class ProductNotFoundError(Exception):
    """Raised when no source can resolve a UPC."""

    def __init__(self, upc: str):
        self.upc = upc
        super().__init__(f"No product found for UPC {upc}")


class ProductResolutionService:
    """Resolves a UPC barcode to a canonical Product record."""

    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self.db = db
        self.redis = redis

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

        # Step 3: Gemini API
        product = await self._resolve_via_gemini(upc)
        if product:
            logger.info("Product resolved via Gemini API: upc=%s", upc)
            return product

        # Step 4: UPCitemdb
        product = await self._resolve_via_upcitemdb(upc)
        if product:
            logger.info("Product resolved via UPCitemdb: upc=%s", upc)
            return product

        # Step 5: All sources exhausted
        raise ProductNotFoundError(upc)

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

    async def _resolve_via_gemini(self, upc: str) -> Product | None:
        """Call Gemini API to resolve UPC, persist to DB, cache to Redis."""
        try:
            prompt = build_upc_lookup_prompt(upc)
            data = await gemini_generate_json(prompt)

            if data.get("error") == "unknown_upc":
                logger.info("Gemini could not identify UPC %s", upc)
                return None

            if not data.get("name"):
                logger.warning("Gemini returned no name for UPC %s", upc)
                return None

            return await self._persist_product(upc, data, "gemini")
        except Exception:
            logger.warning(
                "Gemini resolution failed for UPC %s", upc, exc_info=True
            )
            return None

    async def _resolve_via_upcitemdb(self, upc: str) -> Product | None:
        """Call UPCitemdb API to resolve UPC, persist to DB, cache to Redis."""
        try:
            data = await upcitemdb_lookup(upc)
            if not data or not data.get("name"):
                return None

            return await self._persist_product(upc, data, "upcitemdb")
        except Exception:
            logger.warning(
                "UPCitemdb resolution failed for UPC %s", upc, exc_info=True
            )
            return None

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
            source_raw=data,
        )
        self.db.add(product)

        try:
            await self.db.flush()
        except IntegrityError:
            # Concurrent insert for same UPC — load the existing record
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
