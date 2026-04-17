"""ProductSearchService — resolves free-text product queries to a ranked list.

Flow:
1. Normalize the query (lowercase, collapse whitespace, strip surrounding punctuation).
2. Check Redis (24h TTL, key: ``search:query:{sha256[:16]}:{max_results}``).
3. DB fuzzy match on ``products.name`` via pg_trgm similarity (threshold 0.3,
   backed by ``idx_products_name_trgm`` from migration 0007).
4. If the DB returns fewer than 3 rows OR the top similarity is below 0.5,
   fall back to Gemini with Google Search grounding (system instruction in
   ``ai/prompts/product_search.py``).
5. Dedupe Gemini results against DB results on normalized ``(brand, name)``.
6. Cache the merged response. Gemini results are NOT persisted to the
   ``products`` table — persistence happens on tap via the standard
   ``/products/resolve`` path (Step 3a Decision D5).

Rationale for the 24h Redis cache: text queries are repeated across users
more than UPCs are (brand + category searches are long-tail but heavily
reused); 24h matches the existing ``product:upc:`` TTL so cache-eviction
bookkeeping is uniform.
"""

import hashlib
import logging
import re

import redis.asyncio as aioredis
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from ai.abstraction import gemini_generate_json
from ai.prompts.product_search import (
    PRODUCT_SEARCH_SYSTEM_INSTRUCTION,
    build_product_search_prompt,
    build_product_search_retry_prompt,
)
from modules.m1_product.schemas import ProductSearchResponse, ProductSearchResult

logger = logging.getLogger("barkain.m1.search")

REDIS_KEY_PREFIX = "search:query:"
REDIS_CACHE_TTL = 86400  # 24 hours
TRGM_THRESHOLD = 0.3
GEMINI_FALLBACK_MIN_RESULTS = 3
GEMINI_FALLBACK_SIMILARITY = 0.5

_WHITESPACE_RE = re.compile(r"\s+")
_STRIP_PUNCT_RE = re.compile(r"^[\W_]+|[\W_]+$", re.UNICODE)


def _normalize(query: str) -> str:
    """Lowercase, collapse internal whitespace, strip leading/trailing punctuation."""
    lowered = query.lower()
    stripped = _STRIP_PUNCT_RE.sub("", lowered)
    return _WHITESPACE_RE.sub(" ", stripped).strip()


def _dedup_key(brand: str | None, name: str) -> tuple[str, str]:
    """Stable identity tuple for Gemini↔DB dedup (Step 3a D10)."""
    return ((brand or "").strip().lower(), name.strip().lower())


class ProductSearchService:
    """Text-query → ranked product list service."""

    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self.db = db
        self.redis = redis

    # MARK: - Public entry point

    async def search(
        self, query: str, max_results: int = 10
    ) -> ProductSearchResponse:
        normalized = _normalize(query)
        if len(normalized) < 3:
            # Pydantic already rejects at the router boundary, but a normalized
            # query can still shrink below 3 chars if the input was mostly
            # punctuation. Return empty rather than raising — the UI renders
            # "No results" cleanly.
            return ProductSearchResponse(
                query=query, results=[], total_results=0, cached=False
            )

        cache_key = self._cache_key(normalized, max_results)
        cached = await self.redis.get(cache_key)
        if cached:
            payload = cached if isinstance(cached, str) else cached.decode()
            try:
                response = ProductSearchResponse.model_validate_json(payload)
                return response.model_copy(update={"cached": True})
            except ValueError:
                logger.warning("Corrupt cache entry for key %s — refreshing", cache_key)
                await self.redis.delete(cache_key)

        db_rows = await self._fuzzy_match_db(normalized, max_results)
        top_similarity = db_rows[0]["sim"] if db_rows else 0.0
        needs_gemini = (
            len(db_rows) < GEMINI_FALLBACK_MIN_RESULTS
            or top_similarity < GEMINI_FALLBACK_SIMILARITY
        )

        gemini_rows: list[dict] = []
        if needs_gemini:
            gemini_rows = await self._gemini_search(normalized, max_results)

        merged = self._merge(db_rows, gemini_rows, max_results)
        response = ProductSearchResponse(
            query=query,
            results=merged,
            total_results=len(merged),
            cached=False,
        )

        try:
            await self.redis.set(
                cache_key, response.model_dump_json(), ex=REDIS_CACHE_TTL
            )
        except Exception:
            logger.warning("Failed to cache search response for key %s", cache_key, exc_info=True)

        return response

    # MARK: - Cache key

    @staticmethod
    def _cache_key(normalized_query: str, max_results: int) -> str:
        digest = hashlib.sha256(normalized_query.encode("utf-8")).hexdigest()[:16]
        return f"{REDIS_KEY_PREFIX}{digest}:{max_results}"

    # MARK: - DB fuzzy match

    async def _fuzzy_match_db(
        self, normalized_query: str, max_results: int
    ) -> list[dict]:
        """Fuzzy match ``products.name`` via pg_trgm similarity.

        Returns dicts (not ORM instances) with the fields needed to build a
        ``ProductSearchResult``. Uses ``set_limit`` to align the ``%``
        operator with our threshold — the default 0.3 is already what we
        want, but setting it explicitly keeps the query self-documenting.
        """
        # Note: set_limit is session-local; safe to call per-request.
        await self.db.execute(
            sql_text("SELECT set_limit(:threshold)"),
            {"threshold": TRGM_THRESHOLD},
        )
        result = await self.db.execute(
            sql_text(
                """
                SELECT
                    id,
                    upc,
                    name,
                    brand,
                    category,
                    image_url,
                    source_raw,
                    similarity(name, :q) AS sim
                FROM products
                WHERE name % :q
                ORDER BY sim DESC
                LIMIT :n
                """
            ),
            {"q": normalized_query, "n": max_results},
        )
        return [dict(row._mapping) for row in result]

    # MARK: - Gemini fallback

    async def _gemini_search(
        self, normalized_query: str, max_results: int
    ) -> list[dict]:
        """Call Gemini for a ranked list; retry once on null/malformed response."""
        try:
            prompt = build_product_search_prompt(normalized_query, max_results)
            raw = await gemini_generate_json(
                prompt,
                system_instruction=PRODUCT_SEARCH_SYSTEM_INSTRUCTION,
            )
            results = _extract_gemini_list(raw)

            if not results:
                logger.info(
                    "Gemini returned empty/null for query %r, retrying", normalized_query
                )
                retry = build_product_search_retry_prompt(normalized_query)
                raw = await gemini_generate_json(
                    retry,
                    system_instruction=PRODUCT_SEARCH_SYSTEM_INSTRUCTION,
                )
                results = _extract_gemini_list(raw)

            return results
        except Exception:
            logger.warning(
                "Gemini search failed for query %r", normalized_query, exc_info=True
            )
            return []

    # MARK: - Merge + rank

    @staticmethod
    def _merge(
        db_rows: list[dict], gemini_rows: list[dict], max_results: int
    ) -> list[ProductSearchResult]:
        """Combine DB and Gemini rows, dedupe by (brand, name), cap at max_results.

        DB rows come first (higher trust — they've been resolved at least once),
        ordered by trigram similarity DESC. Gemini-only rows follow,
        ordered by confidence DESC. Any Gemini row whose (brand, name) matches
        a DB row is dropped.
        """
        merged: list[ProductSearchResult] = []
        seen: set[tuple[str, str]] = set()

        for row in db_rows:
            name = row["name"]
            brand = row.get("brand")
            key = _dedup_key(brand, name)
            if key in seen:
                continue
            seen.add(key)

            # pull gemini_model out of source_raw (same convention as ProductResponse)
            source_raw = row.get("source_raw") or {}
            model = source_raw.get("gemini_model") if isinstance(source_raw, dict) else None
            confidence = float(row.get("sim") or 0.0)

            merged.append(
                ProductSearchResult(
                    device_name=name,
                    model=model,
                    brand=brand,
                    category=row.get("category"),
                    confidence=confidence,
                    primary_upc=row.get("upc"),
                    source="db",
                    product_id=row["id"],
                    image_url=row.get("image_url"),
                )
            )

        for row in gemini_rows:
            name = row.get("device_name") or ""
            if not name:
                continue
            brand = row.get("brand")
            key = _dedup_key(brand, name)
            if key in seen:
                continue
            seen.add(key)

            try:
                confidence = float(row.get("confidence", 0.0))
            except (TypeError, ValueError):
                confidence = 0.0

            merged.append(
                ProductSearchResult(
                    device_name=name,
                    model=row.get("model"),
                    brand=brand,
                    category=row.get("category"),
                    confidence=confidence,
                    primary_upc=row.get("primary_upc"),
                    source="gemini",
                    product_id=None,
                    image_url=None,
                )
            )

        return merged[:max_results]


def _extract_gemini_list(raw) -> list[dict]:
    """Gemini may return a bare JSON array or ``{"results": [...]}``.

    ``gemini_generate_json`` normalizes to a Python object but doesn't
    enforce a top-level type — accept both shapes defensively.
    """
    if isinstance(raw, list):
        return [r for r in raw if isinstance(r, dict)]
    if isinstance(raw, dict):
        for key in ("results", "products", "items"):
            if isinstance(raw.get(key), list):
                return [r for r in raw[key] if isinstance(r, dict)]
    return []
