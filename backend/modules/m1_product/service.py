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

import asyncio
import hashlib
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone

import redis.asyncio as aioredis
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ai.abstraction import gemini_generate_json
from ai.web_search import resolve_via_serper
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
from modules.m1_product.search_service import (
    _RELEVANCE_STOPWORDS,
    _query_strict_specs,
)
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
_PATTERN_UPC_RE = re.compile(r"^(\d)\1{11,12}$")  # all-same-digit (000…, 111…, etc.)


_RESOLVE_TOKEN_STRIP_RE = re.compile(r"^[\W_]+|[\W_]+$", re.UNICODE)


def _resolved_matches_query(
    query: str,
    query_brand: str | None,
    resolved_name: str,
    resolved_brand: str | None,
) -> bool:
    """Sanity-check that a UPC's canonical product reflects the user's query.

    Two gates, ANY miss → reject:

    1. **Brand gate** — the supplied ``query_brand`` (or, when absent, the
       leading meaningful alpha token of ``query``) must appear in the
       resolved name+brand haystack. Catches Toro→Greenworks: UPCitemdb
       maps `841821087104` to a Greenworks mower even though the user
       searched "Toro Recycler".
    2. **Strict-spec gate** — voltage tokens (40v/80v) and 4+digit
       pure-numeric model numbers (5200/6400) extracted from the query
       must echo back verbatim in the haystack. Catches Vitamix
       5200→Explorian E310 and Greenworks 40V→80V drift, where the
       upstream UPC database returns the wrong canonical row.

    Reuses ``_query_strict_specs`` so search-time and resolve-time use
    the same definition of "must match verbatim".
    """
    haystack = " ".join([
        (resolved_name or "").lower(),
        (resolved_brand or "").lower(),
    ])

    brand_token = (query_brand or "").strip().lower()
    if not brand_token:
        for raw in query.lower().split():
            tok = _RESOLVE_TOKEN_STRIP_RE.sub("", raw).strip()
            if (
                len(tok) >= 3
                and tok.isalpha()
                and tok not in _RELEVANCE_STOPWORDS
            ):
                brand_token = tok
                break
    if brand_token and brand_token not in haystack:
        return False

    for spec in _query_strict_specs(query):
        if spec not in haystack:
            return False

    return True


def _is_pattern_upc(upc: str) -> bool:
    """Reject obvious garbage UPCs (all-same-digit) before any external call.

    A real GS1 barcode never has all 12 or 13 digits identical. Catches the
    common test inputs (`000000000000`, `111111111111`) that otherwise cost
    one Gemini call and pollute the products table with a hallucinated row.
    Cheaper / more specific than a full GS1 mod-10 checksum, which would
    also reject many real legitimate UPCs that happen to fail it.
    """
    return bool(_PATTERN_UPC_RE.match(upc))


# thumbnail-coverage-L3: hosts known to hotlink-block our app traffic.
# When a UPC resolution surfaces an image URL on one of these hosts we
# refuse to persist it — the row is created with `image_url=NULL` so the
# scraper-backfill path stays eligible AND the iOS fallback chain
# (Serper image search → category icon) becomes the canonical render.
# Pre-fix: a single demandware row poisoned the cache for that UPC's
# lifetime because the backfill only refires on NULL. Match by suffix on
# the netloc so we cover both apex and CDN subdomains.
#
# Add hosts here when telemetry shows a sustained 4xx/5xx rate from
# them. Keep this list short — every entry forces an extra fallback
# round-trip on iOS, so don't add hosts that work for most users.
_KNOWN_BAD_IMAGE_HOSTS: tuple[str, ...] = (
    "demandware.net",
)


def _filter_known_bad_image_url(url: str | None) -> str | None:
    """Return None for image URLs whose host hotlink-blocks our traffic.

    Returns the input verbatim for any other URL (including None or empty).
    Suffix-matches the netloc so subdomains like
    `images.salsify.com.demandware.net` also drop. Soft-fails on parse
    errors — a malformed URL returns the input unchanged so the existing
    persist path can decide what to do with it.
    """
    if not url:
        return url
    try:
        from urllib.parse import urlparse

        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return url
    for bad in _KNOWN_BAD_IMAGE_HOSTS:
        if host == bad or host.endswith("." + bad):
            logger.info(
                "Dropping known-bad image host %s for persisted product (url=%s)",
                bad, url,
            )
            return None
    return url


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

    cat-rel-1-L2-ux: ``reasoning`` carries Gemini's stated explanation for
    refusing to commit to a UPC (multi-variant SKU, dealer-only stock,
    etc.) when present. The router includes it in the error envelope's
    ``details`` so iOS can show *why* we came back empty instead of the
    generic "couldn't find this one" copy.
    """

    def __init__(self, device_name: str, reasoning: str | None = None):
        self.device_name = device_name
        self.reasoning = reasoning
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
        *,
        fallback_image_url: str | None = None,
        search_query: str | None = None,
        allow_provisional: bool = False,
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

        ``allow_provisional`` (gated at the router by
        ``settings.PROVISIONAL_RESOLVE_ENABLED``) flips the "no UPC at all"
        branch from a ``UPCNotFoundForDescriptionError`` into a best-effort
        provisional persist via :meth:`_persist_provisional`. Only the
        upstream-empty branch is converted — the cache-mismatch and
        post-resolve-mismatch branches still raise so the relevance gates
        keep authority over canonical rows. ``search_query`` is the user's
        original search string (forwarded to ``source_raw`` so the M2
        stream can auto-inject a ``?query=`` override).

        Raises:
            UPCNotFoundForDescriptionError: neither stage produced a UPC
                (or a relevance-gate rejected the resolved canonical
                product); when ``allow_provisional`` is set, the
                upstream-empty branch persists a provisional row instead.
            ProductNotFoundError: UPC was derived but no source identified a product.
        """
        cache_key = self._devupc_cache_key(device_name, brand)
        cached_upc = await self._get_cached_devupc(cache_key)
        if cached_upc:
            logger.info(
                "device→UPC cache hit: %r (brand=%s) → %s", device_name, brand, cached_upc
            )
            cached_product = await self.resolve(cached_upc)
            if not _resolved_matches_query(
                device_name, brand, cached_product.name, cached_product.brand
            ):
                # Pre-fix entries can persist in Redis up to 24h. Drop the
                # bad mapping so the next attempt re-runs both upstreams.
                logger.warning(
                    "Cached UPC %s resolves to %r but does not match query %r — invalidating",
                    cached_upc, cached_product.name, device_name,
                )
                try:
                    await self.redis.delete(cache_key)
                except Exception:
                    logger.warning(
                        "device→UPC cache delete failed for %s", cache_key, exc_info=True
                    )
                raise UPCNotFoundForDescriptionError(device_name)
            return cached_product

        # Fire Gemini + UPCitemdb in parallel. Previously sequential, which
        # added UPCitemdb's 10s cap on top of Gemini's ~10-15s for every
        # resolve-from-search tap — ~20s median wall time. With gather, the
        # total is max(T_gemini, T_upcitemdb) ≈ Gemini's budget. Gemini is
        # still preferred when both return a UPC (opinionated single-SKU
        # pick beats UPCitemdb's keyword-search top hit).
        gemini_result, upcitemdb_result = await asyncio.gather(
            self._lookup_upc_from_description(device_name, brand, model),
            self._lookup_upc_from_upcitemdb(device_name, brand),
            return_exceptions=True,
        )
        # Gemini leg returns ``(upc, reasoning)`` — extract both. Treat any
        # other shape (legacy tests, exception) as "no signal".
        gemini_upc: str | None = None
        gemini_reasoning: str | None = None
        if isinstance(gemini_result, tuple) and len(gemini_result) == 2:
            gemini_upc, gemini_reasoning = gemini_result
        elif isinstance(gemini_result, BaseException):
            logger.warning(
                "Gemini device→UPC raised for %r: %s",
                device_name, gemini_result,
            )
        upcitemdb_upc = upcitemdb_result if isinstance(upcitemdb_result, str) else None
        if isinstance(upcitemdb_result, BaseException):
            logger.warning(
                "UPCitemdb fallback raised for %r: %s",
                device_name, upcitemdb_result,
            )

        upc = gemini_upc or upcitemdb_upc
        if not upc:
            # No UPC from either upstream. With ``allow_provisional`` the
            # router opts the user into a best-effort row keyed on the
            # search query; the M2 stream auto-injects ``?query=`` and
            # the relevance gates (model-number hard, brand-bleed, 0.4
            # token overlap) become the safety net at price-fetch time.
            if allow_provisional:
                logger.info(
                    "resolve-from-search: persisting provisional row for %r "
                    "(no UPC from Gemini or UPCitemdb; reason=%r)",
                    device_name, gemini_reasoning,
                )
                return await self._persist_provisional(
                    device_name=device_name,
                    brand=brand,
                    model=model,
                    search_query=search_query,
                    fallback_image_url=fallback_image_url,
                    gemini_no_upc_reason=gemini_reasoning,
                )
            # cat-rel-1-L2-ux: pass Gemini's stated reason through so the
            # router can include it in the 404 envelope and iOS can show
            # *why* we came back empty (multi-variant SKU, dealer-only,
            # discontinued, etc.) instead of the generic copy.
            raise UPCNotFoundForDescriptionError(
                device_name, reasoning=gemini_reasoning
            )

        # Resolve the UPC to a canonical Product (may persist a new row).
        # We sanity-check the result against the user's query AFTER persistence
        # because the row itself is real — it just isn't what the user asked
        # for. Leaving it in PG benefits future scans of the right barcode;
        # we just refuse to surface it for this query.
        product = await self.resolve(upc, fallback_image_url=fallback_image_url)
        if not _resolved_matches_query(device_name, brand, product.name, product.brand):
            logger.warning(
                "Resolved product %r (upc=%s, brand=%s) does not match query %r — rejecting",
                product.name, upc, product.brand, device_name,
            )
            raise UPCNotFoundForDescriptionError(
                device_name, reasoning=gemini_reasoning
            )

        await self._cache_devupc(cache_key, upc)
        return product

    async def resolve_from_search_confirmed(
        self,
        device_name: str,
        brand: str | None = None,
        model: str | None = None,
        *,
        fallback_image_url: str | None = None,
        search_query: str | None = None,
        allow_provisional: bool = False,
    ) -> Product:
        """demo-prep-1 Item 3: resolve a low-confidence tap that the user
        confirmed in the ``ConfirmationPromptView`` sheet. Runs the same
        resolution path as :meth:`resolve_from_search`, then tags the
        persisted ``Product.source_raw.user_confirmed = True`` so repeat
        scans of the same canonical product skip the dialog in the
        future (the confidence check lives in the router layer, which
        only fires when the client supplies ``confidence`` — future
        scans won't need a gate because we trust the confirmed row).

        ``allow_provisional`` and ``search_query`` flow through to
        :meth:`resolve_from_search` so the confirm path can also persist a
        provisional row when the user re-affirmed a low-confidence pick
        whose Gemini+UPCitemdb upstream came back empty.
        """
        product = await self.resolve_from_search(
            device_name, brand=brand, model=model,
            fallback_image_url=fallback_image_url,
            search_query=search_query,
            allow_provisional=allow_provisional,
        )
        raw = dict(product.source_raw) if isinstance(product.source_raw, dict) else {}
        if not raw.get("user_confirmed"):
            raw["user_confirmed"] = True
            product.source_raw = raw
            await self.db.flush()
        return product

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
    ) -> tuple[str | None, str | None]:
        """Call Gemini to convert a device description into a canonical UPC.

        Retries once with a broader prompt if the first attempt returns
        null. Returns ``(upc, reasoning)`` — both Optional. ``upc`` is a
        validated 12/13-digit string when Gemini commits; ``reasoning`` is
        Gemini's stated explanation when it refused (e.g. "Multiple SKU
        variants — recommend scanning the barcode"), surfaced to iOS via
        ``UPCNotFoundForDescriptionError.reasoning`` so the user sees why
        we came back empty (cat-rel-1-L2-ux). Truncated to 200 chars.

        Both fields are None on transport / parse failures — the caller
        cannot distinguish a soft "Gemini refused" from a hard "Gemini
        crashed", but the upstream UPCitemdb leg is identical in both
        cases so the distinction doesn't change behavior.
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
                return upc, None

            reasoning = ""
            if isinstance(raw, dict):
                reasoning = str(raw.get("reasoning") or "")[:200]
            logger.info(
                "Gemini could not resolve device→UPC after retry: %r reason=%r",
                device_name, reasoning,
            )
            return None, (reasoning or None)
        except Exception:
            logger.warning(
                "Gemini device→UPC lookup failed for %r", device_name, exc_info=True
            )
            return None, None

    async def resolve(
        self, upc: str, *, fallback_image_url: str | None = None
    ) -> Product:
        """Resolve a UPC to a Product, checking all sources in order.

        Args:
            upc: Validated 12-13 digit UPC string.
            fallback_image_url: Optional thumbnail forwarded by the iOS
                client (typically a search-row image populated by the M1
                thumbnail-backfill cascade). Used ONLY at first-persist
                time when no upstream resolver returned an image — never
                overrides an existing ``Product.image_url``, never re-fires
                for cached or already-persisted UPCs.

        Returns:
            Product ORM instance (existing or newly created).

        Raises:
            ProductNotFoundError: If no source can resolve the UPC.
        """
        # Pattern-UPC guard: short-circuit obvious garbage (000000000000,
        # 111111111111, etc.) before burning a Gemini call. Without this,
        # Gemini hallucinates a plausible product for any 12-digit string
        # and we persist the hallucination to PG forever.
        if _is_pattern_upc(upc):
            logger.info("Rejecting pattern UPC pre-resolution: %s", upc)
            raise ProductNotFoundError(upc)

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
        product = await self._resolve_with_cross_validation(
            upc, fallback_image_url=fallback_image_url
        )
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

    async def _resolve_with_cross_validation(
        self, upc: str, *, fallback_image_url: str | None = None
    ) -> Product | None:
        """Resolve UPC by querying Gemini and UPCitemdb, then cross-validating.

        Always attempts both sources for maximum accuracy. Falls back gracefully
        when one or both fail.

        Fires both upstreams in parallel (was sequential before
        fix/resolve-cross-val-parallel). Gemini's retry-on-null prompt
        still runs when the first pass returns null — it catches real
        products where Gemini's default prompt is too narrow
        (``test_gemini_null_retry_then_success`` covers the niche
        electronics case). The savings from parallelizing the initial
        calls cut the 404 path from ~30s to ~20s on its own.
        """
        gemini_result, upcitemdb_result = await asyncio.gather(
            self._get_gemini_data(upc, allow_retry=False),
            self._get_upcitemdb_data(upc),
            return_exceptions=True,
        )
        gemini_data = gemini_result if isinstance(gemini_result, dict) else None
        upcitemdb_data = upcitemdb_result if isinstance(upcitemdb_result, dict) else None
        if isinstance(gemini_result, BaseException):
            logger.warning("Gemini resolution raised for UPC %s: %s", upc, gemini_result)
        if isinstance(upcitemdb_result, BaseException):
            logger.warning("UPCitemdb resolution raised for UPC %s: %s", upc, upcitemdb_result)

        # Retry Gemini with the broader prompt on first-pass null. This
        # preserves the legacy behavior where the second prompt rescues
        # products that the opinionated first prompt refused to commit to.
        if gemini_data is None:
            gemini_data = await self._get_gemini_data_retry(upc)

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
        return await self._persist_product(
            upc, product_data, source_label,
            fallback_image_url=fallback_image_url,
        )

    async def _get_gemini_data(self, upc: str, *, allow_retry: bool = True) -> dict | None:
        """Resolve a UPC via Serper-then-grounded.

        E-then-B: try ``resolve_via_serper`` first (Serper SERP top-5 →
        Gemini synthesis without grounding, ``thinking_budget=0``); on
        None fall back to the grounded path. Bench-validated in
        bench/vendor-migrate-1: on user-verified UPCs the Serper path
        hit 100 % recall vs the grounded path's 53 %, with p50 latency
        47 % lower and per-call cost ~36× cheaper. The grounded
        fallback covers Serper-coverage gaps (obscure SKUs, non-US
        retail).

        ``allow_retry=True`` (the legacy behavior) retries the grounded
        path once with a broader prompt if the first attempt returns
        null. In the parallel cross-validation path the retry is driven
        externally via ``_get_gemini_data_retry`` so we can gate it on
        UPCitemdb's outcome; callers from that path pass
        ``allow_retry=False``. The Serper path itself does not retry —
        if it fails or returns null we go straight to grounded.
        """
        # E (Serper synthesis) — fast/cheap path
        try:
            serper_result = await resolve_via_serper(upc)
        except Exception:
            logger.warning(
                "Serper synthesis raised for UPC %s — falling back to grounded",
                upc, exc_info=True,
            )
            serper_result = None

        if serper_result is not None:
            logger.info(
                "UPC %s resolved via Serper synthesis: name=%r model=%r",
                upc, serper_result.get("name"), serper_result.get("gemini_model"),
            )
            return serper_result

        # B (grounded Gemini) — fallback
        try:
            prompt = build_upc_lookup_prompt(upc)
            raw = await gemini_generate_json(
                prompt,
                system_instruction=UPC_LOOKUP_SYSTEM_INSTRUCTION,
            )

            device_name = raw.get("device_name")
            model = raw.get("model")

            # Retry once with broader prompt if null — legacy sequential path.
            if not device_name and allow_retry:
                logger.info("Gemini returned null for UPC %s, retrying with broader prompt", upc)
                retry_prompt = build_upc_retry_prompt(upc)
                raw = await gemini_generate_json(
                    retry_prompt,
                    system_instruction=UPC_LOOKUP_SYSTEM_INSTRUCTION,
                )
                device_name = raw.get("device_name")
                model = raw.get("model")

            if not device_name:
                if allow_retry:
                    logger.info("Gemini could not identify UPC %s after retry", upc)
                else:
                    logger.info("Gemini first pass returned null for UPC %s", upc)
                return None

            return {"name": device_name, "gemini_model": model}
        except Exception:
            logger.warning(
                "Gemini resolution failed for UPC %s", upc, exc_info=True
            )
            return None

    async def _get_gemini_data_retry(self, upc: str) -> dict | None:
        """Second Gemini call with the broader retry prompt.

        Separated from ``_get_gemini_data`` so the parallel cross-val
        path can run the first Gemini call concurrently with UPCitemdb,
        then decide whether the retry is worth paying for based on
        UPCitemdb's outcome.
        """
        try:
            retry_prompt = build_upc_retry_prompt(upc)
            raw = await gemini_generate_json(
                retry_prompt,
                system_instruction=UPC_LOOKUP_SYSTEM_INSTRUCTION,
            )
            device_name = raw.get("device_name")
            model = raw.get("model")
            if not device_name:
                logger.info("Gemini retry still null for UPC %s", upc)
                return None
            return {"name": device_name, "gemini_model": model}
        except Exception:
            logger.warning("Gemini retry failed for UPC %s", upc, exc_info=True)
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
                # Brands agree — trust Gemini name, enrich with UPCitemdb fields.
                # Prefer UPCitemdb image (consistently a manufacturer CDN), but
                # fall back to whatever Serper extracted when UPCitemdb has none.
                return (
                    {
                        "name": gemini_name,
                        "gemini_model": gemini_data.get("gemini_model"),
                        "brand": upcitemdb_data.get("brand"),
                        "category": upcitemdb_data.get("category"),
                        "description": upcitemdb_data.get("description"),
                        "image_url": (
                            upcitemdb_data.get("image_url")
                            or gemini_data.get("image_url")
                        ),
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
        self, upc: str, data: dict, source: str,
        *, fallback_image_url: str | None = None,
    ) -> Product:
        """Create or fetch a Product record and cache to Redis.

        Handles concurrent insert race conditions via IntegrityError.

        ``fallback_image_url`` is the iOS-supplied search-row thumbnail.
        Used ONLY when no upstream resolver returned an image (or the
        upstream image was hotlink-blocked). Goes through the same
        bad-host filter so a blocklisted fallback still produces NULL.
        """
        # thumbnail-coverage-L3: filter out image URLs from hosts that are
        # known to hotlink-block our app traffic. Persisting them poisons
        # the cache for the lifetime of the row — the iOS fallback chain
        # papers over it for the user, but only when `Product.image_url`
        # is NULL (the backfill never refires for non-null rows). Skipping
        # the persist forces NULL up front so the fallback chain becomes
        # the canonical path for these hosts.
        image_url = _filter_known_bad_image_url(data.get("image_url"))
        if image_url is None and fallback_image_url:
            # Same blocklist applies — a search-row thumbnail might also
            # be on a hotlink-blocked host (especially after the eBay or
            # Serper backfill in M1's search pipeline). Treat the fallback
            # the same as any upstream image_url.
            image_url = _filter_known_bad_image_url(fallback_image_url)
            if image_url is not None:
                logger.info(
                    "Persisting iOS-supplied fallback thumbnail for upc=%s",
                    upc,
                )

        product = Product(
            upc=upc,
            name=data["name"],
            brand=data.get("brand"),
            category=data.get("category"),
            description=data.get("description"),
            image_url=image_url,
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

    async def _persist_provisional(
        self,
        *,
        device_name: str,
        brand: str | None,
        model: str | None,
        search_query: str | None,
        fallback_image_url: str | None,
        gemini_no_upc_reason: str | None,
    ) -> Product:
        """Persist a best-effort Product when no UPC could be derived.

        Lets ``/resolve-from-search`` keep the user moving instead of 404'ing
        on real-but-narrow SKUs (Steam Deck OLED 1TB LE, ThinkPad X1 Carbon
        Gen 12 full-spec, Milwaukee 2960-22 kit, Traeger TFB97RLG) where
        Gemini refuses to commit and UPCitemdb has no row. The persisted
        Product carries:

        * ``upc=NULL`` (so the unique-on-non-null index doesn't apply)
        * ``source="provisional"`` (telemetry + filter handle)
        * ``source_raw["provisional"]=True`` (drives ``match_quality`` +
          M2 query auto-injection + iOS hero banner)
        * ``source_raw["search_query"]`` (the user's original string —
          forwarded to the price stream as ``query_override``)

        Dedup window: a matching ``(name, brand, source='provisional')``
        row created in the last 7 days is reused so re-tapping the same
        dead-end query in a session doesn't keep spawning rows. There's
        no natural unique key here (multiple users can search the same
        string) so dedup is a soft-best-effort, not a constraint.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        norm_brand = (brand or "").strip()
        existing_stmt = (
            select(Product)
            .where(
                Product.source == "provisional",
                Product.name == device_name,
                func.coalesce(Product.brand, "") == norm_brand,
                Product.created_at > cutoff,
            )
            .order_by(Product.created_at.desc())
            .limit(1)
        )
        existing = (await self.db.execute(existing_stmt)).scalar_one_or_none()
        if existing is not None:
            logger.info(
                "resolve-from-search: reusing provisional row %s for %r "
                "(within 7-day window)",
                existing.id, device_name,
            )
            return existing

        image_url = _filter_known_bad_image_url(fallback_image_url)
        source_raw: dict[str, object] = {
            "provisional": True,
            "device_name": device_name,
            "brand": brand,
            "model": model,
            "search_query": search_query,
            "created_via": "resolve-from-search",
        }
        if gemini_no_upc_reason:
            source_raw["gemini_no_upc_reason"] = gemini_no_upc_reason

        product = Product(
            upc=None,
            name=device_name,
            brand=brand,
            category=None,
            description=None,
            image_url=image_url,
            asin=None,
            source="provisional",
            source_raw=source_raw,
        )
        self.db.add(product)
        await self.db.flush()
        logger.info(
            "resolve-from-search: persisted provisional row %s for %r",
            product.id, device_name,
        )
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
