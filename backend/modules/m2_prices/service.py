"""PriceAggregationService — full price comparison pipeline.

Pipeline:
1. Validate product exists in DB
2. Check Redis cache (6hr TTL)
3. Check PostgreSQL prices table (fresh within 6hr)
4. Dispatch to all 11 scraper containers in parallel
5. Normalize container listings → Price records
6. Upsert to prices table (UNIQUE on product_id+retailer_id+condition)
7. Append to price_history (TimescaleDB hypertable)
8. Cache result to Redis
9. Return sorted by price ascending
"""

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core_models import Retailer
from modules.m1_product.models import Product
from modules.m2_prices.container_client import ContainerClient
from modules.m2_prices.models import Price, PriceHistory
from modules.m2_prices.schemas import ContainerResponse

logger = logging.getLogger("barkain.m2")

REDIS_CACHE_TTL = 21600  # 6 hours — no partial invalidation by design; force_refresh bypasses (D9)
REDIS_KEY_PREFIX = "prices:product:"
DB_FRESHNESS_HOURS = 6


class ProductNotFoundError(Exception):
    """Raised when the requested product_id does not exist."""

    def __init__(self, product_id: str):
        self.product_id = product_id
        super().__init__(f"No product found with id {product_id}")


def _json_serializer(obj: object) -> str:
    """Custom JSON serializer for datetime and UUID."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, uuid.UUID):
        return str(obj)
    raise TypeError(f"Not JSON serializable: {type(obj)}")


class PriceAggregationService:
    """Orchestrates price comparison across all retailer containers."""

    def __init__(
        self,
        db: AsyncSession,
        redis: aioredis.Redis,
        container_client: ContainerClient | None = None,
    ):
        self.db = db
        self.redis = redis
        self.container_client = container_client or ContainerClient()

    async def get_prices(
        self, product_id: uuid.UUID, force_refresh: bool = False
    ) -> dict:
        """Full price comparison pipeline. Returns dict matching PriceComparisonResponse."""
        # Step 1: Validate product exists
        product = await self._validate_product(product_id)

        # Step 2: Check Redis cache
        if not force_refresh:
            cached = await self._check_redis(product_id)
            if cached is not None:
                logger.info("Price cache hit (Redis) for product %s", product_id)
                return cached

        # Step 3: Check DB for fresh prices
        if not force_refresh:
            db_result = await self._check_db_prices(product_id, product.name)
            if db_result is not None:
                logger.info("Price cache hit (DB) for product %s", product_id)
                await self._cache_to_redis(product_id, db_result)
                return db_result

        # Step 4: Dispatch to containers
        query = self._build_query(product)
        logger.info("Dispatching to containers for product %s: %s", product_id, query)
        responses = await self.container_client.extract_all(
            query=query,
            product_name=product.name,
            upc=product.upc,
        )

        # Step 5-8: Normalize, upsert, record history, build response
        now = datetime.now(UTC)
        prices_data: list[dict] = []
        succeeded = 0
        failed = 0
        history_offset = 0  # Microsecond offset to avoid PK collision on price_history

        for retailer_id, response in responses.items():
            if response.error is not None or not response.listings:
                failed += 1
                continue

            succeeded += 1
            best_listing = self._pick_best_listing(response)
            if best_listing is None:
                continue

            # Upsert to prices table
            await self._upsert_price(product_id, retailer_id, best_listing, now)

            # Append all listings to price_history (unique timestamp per record)
            for listing in response.listings:
                history_time = now + timedelta(microseconds=history_offset)
                history_offset += 1
                await self._append_price_history(
                    product_id, retailer_id, listing, history_time
                )

            prices_data.append(
                {
                    "retailer_id": retailer_id,
                    "price": best_listing.price,
                    "original_price": best_listing.original_price,
                    "currency": best_listing.currency or "USD",
                    "url": best_listing.url or None,
                    "condition": best_listing.condition or "new",
                    "is_available": (
                        best_listing.is_available
                        if best_listing.is_available is not None
                        else True
                    ),
                    "is_on_sale": (
                        best_listing.original_price is not None
                        and best_listing.price < best_listing.original_price
                    ),
                    "last_checked": now.isoformat(),
                }
            )

        await self.db.flush()

        # Step 9: Load retailer display names
        retailer_ids = [p["retailer_id"] for p in prices_data]
        names = await self._load_retailer_names(retailer_ids)
        for p in prices_data:
            p["retailer_name"] = names.get(p["retailer_id"], p["retailer_id"])

        # Sort by price ascending
        prices_data.sort(key=lambda p: p["price"])

        result = {
            "product_id": str(product_id),
            "product_name": product.name,
            "prices": prices_data,
            "total_retailers": len(responses),
            "retailers_succeeded": succeeded,
            "retailers_failed": failed,
            "cached": False,
            "fetched_at": now.isoformat(),
        }

        # Step 10: Cache to Redis
        await self._cache_to_redis(product_id, result)

        return result

    # MARK: - Private Helpers

    async def _validate_product(self, product_id: uuid.UUID) -> Product:
        """Load product from DB or raise ProductNotFoundError."""
        result = await self.db.execute(
            select(Product).where(Product.id == product_id)
        )
        product = result.scalar_one_or_none()
        if product is None:
            raise ProductNotFoundError(str(product_id))
        return product

    async def _check_redis(self, product_id: uuid.UUID) -> dict | None:
        """Check Redis for cached price comparison result."""
        cached = await self.redis.get(f"{REDIS_KEY_PREFIX}{product_id}")
        if cached is None:
            return None
        try:
            data = cached if isinstance(cached, str) else cached.decode()
            return json.loads(data)
        except (json.JSONDecodeError, UnicodeDecodeError):
            await self.redis.delete(f"{REDIS_KEY_PREFIX}{product_id}")
            return None

    async def _check_db_prices(
        self, product_id: uuid.UUID, product_name: str
    ) -> dict | None:
        """Check if fresh prices exist in the DB (within 6hr window)."""
        cutoff = datetime.now(UTC) - timedelta(hours=DB_FRESHNESS_HOURS)
        result = await self.db.execute(
            select(Price).where(
                Price.product_id == product_id,
                Price.last_checked > cutoff,
            )
        )
        prices = result.scalars().all()
        if not prices:
            return None

        # Load retailer names for these prices
        retailer_ids = list({p.retailer_id for p in prices})
        names = await self._load_retailer_names(retailer_ids)

        prices_data = []
        for p in prices:
            prices_data.append(
                {
                    "retailer_id": p.retailer_id,
                    "retailer_name": names.get(p.retailer_id, p.retailer_id),
                    "price": float(p.price),
                    "original_price": float(p.original_price) if p.original_price else None,
                    "currency": p.currency,
                    "url": p.url,
                    "condition": p.condition,
                    "is_available": p.is_available,
                    "is_on_sale": p.is_on_sale,
                    "last_checked": p.last_checked.isoformat(),
                }
            )

        prices_data.sort(key=lambda x: x["price"])

        return {
            "product_id": str(product_id),
            "product_name": product_name,
            "prices": prices_data,
            "total_retailers": len(prices_data),
            "retailers_succeeded": len(prices_data),
            "retailers_failed": 0,
            "cached": True,
            "fetched_at": prices[0].last_checked.isoformat(),
        }

    def _build_query(self, product: Product) -> str:
        """Build search query from product name and brand."""
        parts = [product.name]
        if product.brand:
            parts.append(product.brand)
        return " ".join(parts)

    def _pick_best_listing(self, response: ContainerResponse):
        """Pick the lowest-priced available listing from a container response.

        NOTE(D11): Keeps only the cheapest listing per retailer. All listings are
        recorded in price_history, but only the cheapest is shown. Phase 2 may
        expose seller-level pricing.
        """
        available = [item for item in response.listings if item.is_available]
        if not available:
            available = response.listings
        return min(available, key=lambda item: item.price) if available else None

    async def _upsert_price(
        self, product_id: uuid.UUID, retailer_id: str, listing, now: datetime
    ) -> None:
        """Upsert a price record using ON CONFLICT DO UPDATE."""
        condition = listing.condition or "new"
        is_on_sale = (
            listing.original_price is not None
            and listing.price < listing.original_price
        )

        stmt = pg_insert(Price).values(
            product_id=product_id,
            retailer_id=retailer_id,
            price=Decimal(str(listing.price)),
            original_price=(
                Decimal(str(listing.original_price))
                if listing.original_price
                else None
            ),
            currency=listing.currency or "USD",
            url=listing.url or None,
            condition=condition,
            is_available=(
                listing.is_available
                if listing.is_available is not None
                else True
            ),
            is_on_sale=is_on_sale,
            last_checked=now,
            updated_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["product_id", "retailer_id", "condition"],
            set_={
                "price": stmt.excluded.price,
                "original_price": stmt.excluded.original_price,
                "currency": stmt.excluded.currency,
                "url": stmt.excluded.url,
                "is_available": stmt.excluded.is_available,
                "is_on_sale": stmt.excluded.is_on_sale,
                "last_checked": stmt.excluded.last_checked,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        await self.db.execute(stmt)

    async def _append_price_history(
        self, product_id: uuid.UUID, retailer_id: str, listing, now: datetime
    ) -> None:
        """Append a record to the price_history hypertable."""
        record = PriceHistory(
            time=now,
            product_id=product_id,
            retailer_id=retailer_id,
            price=Decimal(str(listing.price)),
            original_price=(
                Decimal(str(listing.original_price))
                if listing.original_price
                else None
            ),
            condition=listing.condition or "new",
            is_available=(
                listing.is_available
                if listing.is_available is not None
                else True
            ),
            source="agent_browser",
        )
        self.db.add(record)

    async def _load_retailer_names(
        self, retailer_ids: list[str]
    ) -> dict[str, str]:
        """Load display names for retailers from the DB."""
        if not retailer_ids:
            return {}
        result = await self.db.execute(
            select(Retailer).where(Retailer.id.in_(retailer_ids))
        )
        retailers = result.scalars().all()
        return {r.id: r.display_name for r in retailers}

    async def _cache_to_redis(
        self, product_id: uuid.UUID, data: dict
    ) -> None:
        """Cache the price comparison result to Redis with 6hr TTL."""
        key = f"{REDIS_KEY_PREFIX}{product_id}"
        serialized = json.dumps(data, default=_json_serializer)
        await self.redis.set(key, serialized, ex=REDIS_CACHE_TTL)
