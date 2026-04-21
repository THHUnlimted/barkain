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

import asyncio
import hashlib
import logging
import re
import time
from urllib.parse import quote

import httpx
import redis.asyncio as aioredis
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from ai.abstraction import gemini_generate_json
from ai.prompts.product_search import (
    PRODUCT_SEARCH_SYSTEM_INSTRUCTION,
    build_product_search_prompt,
    build_product_search_retry_prompt,
)
from app.config import settings
from modules.m1_product import upcitemdb
from modules.m1_product.schemas import ProductSearchResponse, ProductSearchResult

logger = logging.getLogger("barkain.m1.search")

REDIS_KEY_PREFIX = "search:query:"
REDIS_CACHE_TTL = 86400  # 24 hours
TRGM_THRESHOLD = 0.3
TIER_FALLBACK_MIN_RESULTS = 3
TIER_FALLBACK_SIMILARITY = 0.5

# Tier 2: Best Buy Products API. Same endpoint the M2 best_buy_api adapter uses,
# but tuned for product picking — returns name/brand/upc/image instead of price.
_BESTBUY_SEARCH_URL = "https://api.bestbuy.com/v1/products(search={query})"
_BESTBUY_SHOW_FIELDS = (
    "sku,name,manufacturer,modelNumber,upc,image,categoryPath.name"
)
_BESTBUY_SORT = "bestSellingRank.asc"
_BESTBUY_TIMEOUT = 5

# Brand-only query detection. When a query is just a manufacturer name (e.g.
# "Apple", "Sony"), Best Buy + UPCitemdb both flood with accessories/cases
# rather than the actual flagship products. Skip Tier 2 entirely and let
# Gemini surface the canonical product line. List is intentionally small —
# add only when a clear pattern of accessory-flooding emerges.
_BRAND_ONLY_TERMS: frozenset[str] = frozenset({
    "apple", "samsung", "sony", "lg", "google", "microsoft", "bose",
    "beats", "jbl", "sennheiser", "dell", "hp", "lenovo", "asus", "acer",
    "razer", "logitech", "anker", "dyson", "shark", "bissell", "kitchenaid",
    "cuisinart", "ninja", "instant pot", "philips", "panasonic", "canon",
    "nikon", "gopro", "dji", "garmin", "fitbit", "amazon", "roku", "tcl",
    "vizio", "hisense", "nintendo", "playstation", "xbox",
})


def _is_brand_only_query(normalized_query: str) -> bool:
    """True iff the query is just a manufacturer name with no model/qualifier."""
    return normalized_query in _BRAND_ONLY_TERMS


# Tier 2 noise filter — when Best Buy / UPCitemdb return ONLY accessories,
# warranties, gift cards, games-for-platform, or peripheral collisions
# (e.g. "pixel 10" → Mobile Pixels monitors, "iphone 17 pro" → AppleCare,
# "switch 2" → games), the cascade currently swallows the result and skips
# Gemini. This filter classifies a Tier 2 row as noise so the cascade can
# treat "Tier 2 returned only noise" the same as "Tier 2 returned nothing"
# and escalate to Gemini. See probe data in CHANGELOG (Step 3d hardening).
_TIER2_NOISE_CATEGORY_TOKENS: tuple[str, ...] = (
    "case",  # "Cell Phone Cases", "Samsung Galaxy Cases"
    "warrant",  # "AppleCare Warranties"
    "applecare",
    "subscription",  # "Gaming Subscriptions"
    "gift card",
    "specialty gift",  # "All Specialty Gift Cards"
    "protection",  # "Protection Plans", "Best Buy Protection"
    "monitor",  # "Portable Monitors" — pixel 10 collision with Mobile Pixels
    "physical video game",  # switch 2 → games-for-switch
    "service",
    "digital signage",  # "samsung flip 7" → "Samsung 75in FLIP PRO Interactive"
    "charger",  # "Portable Chargers" — samsung z flip 7 → SaharaCase chargers
    "screen protector",
)
_TIER2_NOISE_TITLE_TOKENS: tuple[str, ...] = (
    "applecare",
    "protection plan",
    "best buy protection",
    "gift card",
    "warranty",
    "subscription",
    "membership card",
    "belt clip",  # SaharaCase accessory pattern
    "skin case",
)

# Short, generic query tokens that carry no brand/model signal — excluding
# them from the relevance check stops the filter from being fooled by
# titles that happen to share a common English word. Bare keys only; we
# tokenise lowercase before lookup.
_RELEVANCE_STOPWORDS: frozenset[str] = frozenset({
    "the", "and", "with", "for", "pro", "max", "mini", "plus", "ultra",
    "new", "gen", "generation", "inch", "laptop", "desktop", "tablet",
    "phone", "headphones", "earbuds", "tv", "smart", "case", "wireless",
    "bluetooth", "series", "edition", "model", "version",
})

# Model-code pattern: 4+ characters, contains both a digit and a letter.
# Matches `wh-1000xm5`, `27gp950`, `phn16s-71`, `m2-ultra`, but intentionally
# NOT pure-digit tokens (`2022`, `5090`) — those either refer to years or
# get caught by the generic relevance check below.
_MODEL_CODE_RE = re.compile(r"[a-z0-9][a-z0-9-]{3,}", re.IGNORECASE)


def _meaningful_query_tokens(normalized_query: str) -> list[str]:
    """Query tokens used to decide if a Tier 2 row is on-topic.

    Lowercased, length >= 3, stripped of surrounding punctuation. Generic
    stopwords ("pro", "max", "laptop", ...) are excluded so a row that
    only matches on those words doesn't escape the noise filter.
    """
    tokens: list[str] = []
    for raw in normalized_query.lower().split():
        tok = _STRIP_PUNCT_RE.sub("", raw).strip()
        if len(tok) < 3:
            continue
        if tok in _RELEVANCE_STOPWORDS:
            continue
        tokens.append(tok)
    return tokens


def _query_model_codes(normalized_query: str) -> list[str]:
    """Model-code-like tokens from the query — digits+letters, 4+ chars.

    These are the user's strongest relevance signal. If the query contains
    one of these and the row's title/model doesn't echo it back, the row
    is almost certainly wrong regardless of brand or category.
    """
    out: list[str] = []
    for raw in normalized_query.lower().split():
        tok = _STRIP_PUNCT_RE.sub("", raw).strip()
        if len(tok) < 4:
            continue
        has_digit = any(c.isdigit() for c in tok)
        has_alpha = any(c.isalpha() for c in tok)
        if has_digit and has_alpha:
            out.append(tok)
    return out


def _is_tier2_noise(row: dict, *, query: str | None = None) -> bool:
    """Classify a Tier 2 row as accessory/service/peripheral noise.

    Used to decide whether to escalate to Gemini even when Tier 2 returned
    rows. Returning True here does NOT drop the row from the merged response
    on its own — it contributes to the "no relevant Tier 2 hits" signal
    that gates the Tier 3 fire, and (when Gemini escalated and returned
    something) also drops it from the merged results so flagship hits
    aren't crowded out.

    Two layers:

    1. Category + title denylists (unchanged) — catches explicit accessory
       / service / warranty / monitor / gift-card patterns.
    2. Relevance check against the user's query — catches Best Buy's
       famous off-topic fuzzy matches (e.g. `focal utopia 2022` → Panasonic
       lens, `lg 27gp950` → LG Q6 phone, `leica q3` → KEF Q3 speakers).
       Runs only when `query` is passed — existing unit tests that call
       `_is_tier2_noise(row)` keep working.
    """
    category = (row.get("category") or "").lower()
    if any(token in category for token in _TIER2_NOISE_CATEGORY_TOKENS):
        return True
    title = (row.get("device_name") or row.get("name") or "").lower()
    if any(token in title for token in _TIER2_NOISE_TITLE_TOKENS):
        return True
    if query is None:
        return False

    # Relevance bag: everything the row gives us that could echo back the
    # user's query. Substring match is intentional — model codes live
    # inside longer SKUs (`WH-1000XM5` inside `Sony WH-1000XM5 Wireless`).
    haystack = " ".join([
        title,
        (row.get("brand") or "").lower(),
        (row.get("model") or "").lower(),
    ])

    # Hard requirement: any user-provided model code must appear verbatim
    # in the row's title/brand/model. Digit+letter tokens are too specific
    # to tolerate a mismatch — if the user typed `27gp950`, a row without
    # `27gp950` is the wrong product, full stop.
    for code in _query_model_codes(query):
        if code not in haystack:
            return True

    # Soft requirement: strict majority of meaningful query tokens must
    # appear in the haystack. Catches `leica q3` → KEF Q3 (no `leica`) and
    # `framework laptop 16` → LG gram (no `framework`), while leaving
    # genuine matches like `sony wh-1000xm5` → Sony WH-1000XM5 intact.
    meaningful = _meaningful_query_tokens(query)
    if not meaningful:
        return False
    hits = sum(1 for tok in meaningful if tok in haystack)
    if hits * 2 <= len(meaningful):
        return True

    return False

_WHITESPACE_RE = re.compile(r"\s+")
_STRIP_PUNCT_RE = re.compile(r"^[\W_]+|[\W_]+$", re.UNICODE)

# MARK: - Variant collapsing
#
# Catalog APIs return SKU-level rows — Best Buy and UPCitemdb each list
# "iPhone 16 256GB Black", "iPhone 16 256GB Blue", "iPhone 16 128GB Black"
# as separate products. For text search we want one row per *generic*
# product unless the user explicitly asked for a spec dimension. Then on
# tap (the resolve-from-search path) we let the catalog re-disambiguate.
#
# Strategy: strip spec tokens the user did NOT type from each title, then
# group rows by the stripped name and pick a representative.

_STORAGE_RE = re.compile(r"\b\d+\s?(?:GB|TB|MB)\b", re.IGNORECASE)
_SIZE_INCH_RE = re.compile(r"\b\d+(?:\.\d+)?[\"”]\s?", re.IGNORECASE)
_SIZE_INCH_WORD_RE = re.compile(r"\b\d+(?:\.\d+)?[- ]?inch\b", re.IGNORECASE)
_CARRIER_RE = re.compile(
    r"\b(?:unlocked|verizon|at&?t|t-?mobile|sprint|boost|cricket|mint|"
    r"xfinity|us\s?cellular|spectrum|straight\s?talk|tracfone)\b",
    re.IGNORECASE,
)
_WARRANTY_RE = re.compile(
    r"\b(?:applecare\+?|geek\s?squad|protection\s?plan|warranty|service\s?plan)\b",
    re.IGNORECASE,
)
_PARENS_RE = re.compile(r"\([^)]*\)")  # "(2nd generation)", "(USB-C)", etc.

_COLOR_TOKENS: frozenset[str] = frozenset({
    "black", "white", "blue", "red", "pink", "purple", "green", "yellow",
    "gold", "silver", "gray", "grey", "midnight", "starlight", "titanium",
    "natural", "graphite", "alpine", "deep", "sierra", "rose", "coral",
    "lavender", "teal", "mint", "ivory", "charcoal", "platinum", "navy",
    "ultramarine", "desert", "stellar", "phantom", "cream", "olive",
    "bronze", "copper",
})

# Short connecting words that appear in color phrases ("space gray",
# "deep purple") — included so multi-word colors get fully stripped.
_COLOR_MODIFIERS: frozenset[str] = frozenset({"space", "deep", "rose"})


def _strip_specs(title: str, *, keep_storage: bool, keep_color: bool) -> str:
    """Remove variant tokens not retained by the user query.

    Always strips warranty/carrier/parenthetical noise. Conditionally keeps
    storage and color tokens depending on whether the original query
    referenced them.
    """
    s = _PARENS_RE.sub(" ", title)
    s = _WARRANTY_RE.sub(" ", s)
    s = _CARRIER_RE.sub(" ", s)
    if not keep_storage:
        s = _STORAGE_RE.sub(" ", s)
        s = _SIZE_INCH_RE.sub(" ", s)
        s = _SIZE_INCH_WORD_RE.sub(" ", s)
    if not keep_color:
        # Word-by-word color strip — pure regex on each color is messy
        # because some tokens ("Pink") double as model names.
        out: list[str] = []
        for word in s.split():
            cleaned = re.sub(r"[^\w]", "", word).lower()
            if cleaned in _COLOR_TOKENS or cleaned in _COLOR_MODIFIERS:
                continue
            out.append(word)
        s = " ".join(out)
    # Collapse trailing model codes like "MTJV3AM/A" — uppercase alnum slug
    # at the end of the title that doesn't look like a real word.
    s = re.sub(r"\b[A-Z0-9]{4,}/[A-Z0-9]+\b", " ", s)
    return _WHITESPACE_RE.sub(" ", s).strip(" -–—,.").lower()


def _strip_specs_preserve_case(title: str, *, keep_storage: bool, keep_color: bool) -> str:
    """Same as `_strip_specs` but preserves original casing for display.

    Used to build the generic-row label, which is shown to the user.
    """
    s = _PARENS_RE.sub(" ", title)
    s = _WARRANTY_RE.sub(" ", s)
    s = _CARRIER_RE.sub(" ", s)
    if not keep_storage:
        s = _STORAGE_RE.sub(" ", s)
        s = _SIZE_INCH_RE.sub(" ", s)
        s = _SIZE_INCH_WORD_RE.sub(" ", s)
    if not keep_color:
        out: list[str] = []
        for word in s.split():
            cleaned = re.sub(r"[^\w]", "", word).lower()
            if cleaned in _COLOR_TOKENS or cleaned in _COLOR_MODIFIERS:
                continue
            out.append(word)
        s = " ".join(out)
    s = re.sub(r"\b[A-Z0-9]{4,}/[A-Z0-9]+\b", " ", s)
    return _WHITESPACE_RE.sub(" ", s).strip(" -–—,.")


def _query_keeps_storage(normalized_query: str) -> bool:
    return bool(_STORAGE_RE.search(normalized_query)
                or _SIZE_INCH_RE.search(normalized_query)
                or _SIZE_INCH_WORD_RE.search(normalized_query))


def _query_keeps_color(normalized_query: str) -> bool:
    tokens = {re.sub(r"[^\w]", "", t).lower() for t in normalized_query.split()}
    return bool(tokens & _COLOR_TOKENS)


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
        self, query: str, max_results: int = 10, *, force_gemini: bool = False
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
        # `force_gemini` (the iOS "deep search" hint) bypasses the cache so the
        # user always gets a fresh Gemini sweep — caching the deep-search
        # response would defeat the whole purpose on the next identical query.
        cached = None if force_gemini else await self.redis.get(cache_key)
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
        needs_fallback = (
            len(db_rows) < TIER_FALLBACK_MIN_RESULTS
            or top_similarity < TIER_FALLBACK_SIMILARITY
        )

        bestbuy_rows: list[dict] = []
        upcitemdb_rows: list[dict] = []
        gemini_rows: list[dict] = []
        if needs_fallback or force_gemini:
            if _is_brand_only_query(normalized):
                # Brand-only queries ("apple", "sony") flood Tier 2 with
                # accessories. Skip BBY+UPCitemdb and ask Gemini for flagship
                # products directly.
                logger.info("brand-only query %r — skipping Tier 2", normalized)
                gemini_rows = await self._gemini_search(normalized, max_results)
            else:
                # Tier 2: fire Best Buy Products API + UPCitemdb keyword
                # search in parallel — total wall time = max(BBY, UPC) ~150-300 ms.
                # Both ephemeral, no DB writes.
                bestbuy_rows, upcitemdb_rows = await asyncio.gather(
                    self._best_buy_search(normalized, max_results),
                    self._upcitemdb_search(normalized, max_results),
                )
                # Tier 3: Gemini fires when forced (deep-search hint), when
                # both Tier 2 sources returned nothing (genuine long-tail:
                # groceries, apparel, hand tools), OR when every Tier 2 row
                # is accessory/service/peripheral noise (cases, AppleCare,
                # gift cards, monitors-named-Pixel, games-for-Switch). The
                # noise check resolves the "samsung flip 7 → cases only"
                # class of failures.
                relevant_tier2 = [
                    row for row in (*bestbuy_rows, *upcitemdb_rows)
                    if not _is_tier2_noise(row, query=normalized)
                ]
                escalate_to_gemini = force_gemini or not relevant_tier2
                if escalate_to_gemini:
                    gemini_rows = await self._gemini_search(normalized, max_results)
                # Noise suppression: if Gemini was escalated specifically
                # because Tier 2 was all noise (cases / AppleCare / monitors
                # named Pixel / games-for-Switch / off-brand fuzzy hits),
                # the noise rows must NOT crowd out Gemini's real flagship
                # hits at merge time. Skip suppression when Gemini itself
                # returned nothing — half-noisy answer beats none.
                if escalate_to_gemini and not force_gemini and gemini_rows:
                    bestbuy_rows = [
                        r for r in bestbuy_rows if not _is_tier2_noise(r, query=normalized)
                    ]
                    upcitemdb_rows = [
                        r for r in upcitemdb_rows if not _is_tier2_noise(r, query=normalized)
                    ]

        merged = self._merge(
            db_rows, bestbuy_rows, upcitemdb_rows, gemini_rows, max_results,
            gemini_first=force_gemini,
        )
        # Variant collapse: SKU-level rows ("iPhone 16 256GB Black", "iPhone
        # 16 256GB Blue", ...) → one generic row unless the user's query
        # already pinned the spec dimension. UPC scan path doesn't go through
        # here, so variant precision is preserved on tap.
        merged = _collapse_variants(merged, normalized, max_results)
        response = ProductSearchResponse(
            query=query,
            results=merged,
            total_results=len(merged),
            cached=False,
        )

        # Persist deep-search responses too — the cascade ran the full Gemini
        # sweep so subsequent normal queries benefit from the richer results.
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

    # MARK: - Best Buy Products API (Tier 2)

    async def _best_buy_search(
        self, normalized_query: str, max_results: int
    ) -> list[dict]:
        """Hit Best Buy Products API for product picker results.

        Returns dicts shaped for `_merge` (device_name/brand/model/upc/image
        /category). Empty list when the API key is unset, the request fails,
        or zero products match — the caller treats all three identically.
        """
        api_key = settings.BESTBUY_API_KEY
        if not api_key:
            return []

        url = _BESTBUY_SEARCH_URL.format(query=quote(normalized_query, safe=""))
        params = {
            "apiKey": api_key,
            "format": "json",
            "pageSize": max(1, min(max_results, 25)),
            "show": _BESTBUY_SHOW_FIELDS,
            "sort": _BESTBUY_SORT,
        }

        t0 = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=_BESTBUY_TIMEOUT) as client:
                resp = await client.get(url, params=params)
        except httpx.HTTPError as e:
            logger.warning("best_buy search request failed for %r: %s", normalized_query, e)
            return []

        elapsed_ms = int((time.monotonic() - t0) * 1000)
        if resp.status_code >= 400:
            logger.warning(
                "best_buy search HTTP %d for %r body=%s",
                resp.status_code, normalized_query, resp.text[:200],
            )
            return []

        try:
            products = (resp.json() or {}).get("products") or []
        except ValueError:
            logger.warning("best_buy search returned non-JSON for %r", normalized_query)
            return []

        rows: list[dict] = []
        for p in products[:max_results]:
            name = p.get("name")
            if not name:
                continue
            cat_path = p.get("categoryPath") or []
            # Walk leaf-first; Best Buy nests deepest = most specific category.
            category = cat_path[-1].get("name") if cat_path else None
            rows.append({
                "device_name": name,
                "model": p.get("modelNumber"),
                "brand": p.get("manufacturer"),
                "category": category,
                "primary_upc": p.get("upc"),
                "image_url": p.get("image"),
                # Confidence proxy: Best Buy ranks by best-seller, so position
                # encodes relevance. Linear decay from 0.9 → 0.5 across pageSize.
                "confidence": max(0.5, 0.9 - 0.04 * len(rows)),
            })
        logger.info(
            "best_buy search q=%r returned=%d in %dms",
            normalized_query, len(rows), elapsed_ms,
        )
        return rows

    # MARK: - UPCitemdb (Tier 2, parallel with Best Buy)

    async def _upcitemdb_search(
        self, normalized_query: str, max_results: int
    ) -> list[dict]:
        """Wrap `upcitemdb.search_keyword` so the cascade can mock just this method.

        Returns rows shaped for `_merge` with `source="best_buy"` collision
        avoided — the dedup key is `(brand, name)` and BBY rows are added
        first, so any duplicate UPCitemdb row is dropped silently.
        """
        return await upcitemdb.search_keyword(normalized_query, max_results)

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
        db_rows: list[dict],
        bestbuy_rows: list[dict],
        upcitemdb_rows: list[dict],
        gemini_rows: list[dict],
        max_results: int,
        *,
        gemini_first: bool = False,
    ) -> list[ProductSearchResult]:
        """Combine DB, Best Buy, UPCitemdb, and Gemini rows; dedupe by (brand, name); cap at max_results.

        Default priority: DB > Best Buy > UPCitemdb > Gemini. DB rows carry
        a real product_id and the highest trust. Best Buy rows are
        authoritative SKUs+UPCs from the live catalog. UPCitemdb fills in
        broader catalog gaps but data quality is uneven (often empty
        brand/category, accessory-heavy). Gemini handles the long tail.

        ``gemini_first=True`` (the deep-search hint path) flips the order
        so Gemini rows surface first — when the user invoked deep search,
        the existing Tier 2 results were already on screen and didn't
        match what they wanted, so promoting Gemini up top is the relevance
        signal the UI should reflect.

        Any later-tier row whose (brand, name) matches an earlier-tier row
        is dropped silently — Best Buy precedence over UPCitemdb is the
        whole point of firing them in parallel.
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

        for row in bestbuy_rows:
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
                    source="best_buy",
                    product_id=None,
                    image_url=row.get("image_url"),
                )
            )

        for row in upcitemdb_rows:
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
                    source="upcitemdb",
                    product_id=None,
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

        if gemini_first:
            # Stable partition: Gemini rows to the front, everything else in
            # original order behind them. Stable so DB > BBY > UPC ordering
            # is preserved within each partition.
            gemini = [r for r in merged if r.source == "gemini"]
            others = [r for r in merged if r.source != "gemini"]
            merged = gemini + others

        return merged[:max_results]


def _collapse_variants(
    results: list[ProductSearchResult],
    normalized_query: str,
    max_results: int,
) -> list[ProductSearchResult]:
    """Collapse SKU-level variants and prepend a generic row per group.

    Group by `(brand_lower, stripped_title)` where stripped_title removes
    spec dimensions the user did NOT type. For groups with 2+ variants:
      - emit a synthetic `source="generic"` row first (no UPC, generic
        device_name) so the user can tap "any iPhone 16" without committing
        to a specific color/storage/carrier;
      - then emit the variant rows behind it so the user can still pick a
        specific SKU if they want.
    For singleton groups, emit the row as-is.

    Note: tapping a generic row routes through resolve-from-search and the
    persisted Product takes its name from whatever UPCitemdb/Gemini returns
    for the resolved variant — so the iOS price comparison currently uses
    that variant's name when querying retailer containers. Container-side
    "search the generic name" is a separate change (price stream needs an
    optional `query` override).
    """
    keep_storage = _query_keeps_storage(normalized_query)
    keep_color = _query_keeps_color(normalized_query)

    groups: dict[tuple[str, str], list[ProductSearchResult]] = {}
    order: list[tuple[str, str]] = []
    for r in results:
        stripped = _strip_specs(
            r.device_name, keep_storage=keep_storage, keep_color=keep_color
        )
        key = ((r.brand or "").strip().lower(), stripped or r.device_name.lower())
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(r)

    collapsed: list[ProductSearchResult] = []
    for key in order:
        bucket = groups[key]
        if len(bucket) == 1:
            collapsed.append(bucket[0])
            continue
        rep = bucket[0]
        shortest = min(bucket, key=lambda x: len(x.device_name))
        # Build the generic name by stripping spec tokens from the shortest
        # variant's title in its ORIGINAL casing (don't lowercase). Keeps
        # "iPhone" and brand names readable.
        generic_name = _strip_specs_preserve_case(
            shortest.device_name, keep_storage=keep_storage, keep_color=keep_color
        ).strip() or shortest.device_name
        # Skip the synthetic row when the stripped name landed empty or
        # identical to the rep — nothing to add.
        if generic_name and generic_name.lower() != rep.device_name.lower():
            collapsed.append(ProductSearchResult(
                device_name=generic_name,
                model=None,
                brand=rep.brand,
                category=rep.category,
                confidence=max(r.confidence for r in bucket),
                primary_upc=None,
                source="generic",
                product_id=None,
                image_url=rep.image_url,
            ))
        # Append the variant rows behind the generic row so the user can
        # still pick a specific SKU.
        collapsed.extend(bucket)

    return collapsed[:max_results]


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
