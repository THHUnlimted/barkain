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

import asyncio
import hashlib
import json
import logging
import re
import uuid
from collections.abc import AsyncGenerator
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
from modules.m2_prices.schemas import ContainerListing, ContainerResponse

logger = logging.getLogger("barkain.m2")

REDIS_CACHE_TTL = 21600  # 6 hours — no partial invalidation by design; force_refresh bypasses (D9)
REDIS_CACHE_TTL_EMPTY = 1800  # 30 minutes for 0-result responses — users re-scanning get fresh attempts sooner
REDIS_CACHE_TTL_QUERY = 1800  # 30 minutes for bare-name (query_override) results — fresher than the SKU cache
REDIS_KEY_PREFIX = "prices:product:"
REDIS_KEY_QUERY_SUFFIX = ":q:"  # appended with sha1 hex digest of the override query


def _query_scope_digest(query: str) -> str:
    """SHA-1 hex digest of a normalized query — short, predictable, redis-safe."""
    normalized = " ".join(query.lower().split())
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()
DB_FRESHNESS_HOURS = 6


class ProductNotFoundError(Exception):
    """Raised when the requested product_id does not exist."""

    def __init__(self, product_id: str):
        self.product_id = product_id
        super().__init__(f"No product found with id {product_id}")


# Container error codes that represent a failure to search — render as
# "Unavailable" in the UI. This includes outages (CONNECTION_FAILED, HTTP_ERROR)
# AND cases where the scraper was blocked before it could actually search
# (CHALLENGE = PerimeterX / anti-bot page, PARSE_ERROR = response unintelligible,
# BOT_DETECTED = explicit bot flag). These are all "we couldn't determine anything",
# which is distinct from "we searched and the retailer doesn't carry this product".
_UNAVAILABLE_ERROR_CODES = frozenset({
    "CONNECTION_FAILED",
    "GATHER_ERROR",
    "HTTP_ERROR",
    "CLIENT_ERROR",
    "CHALLENGE",
    "PARSE_ERROR",
    "BOT_DETECTED",
    "TIMEOUT",
})


def _classify_error_status(code: str) -> str:
    """Map a ContainerError.code to a RetailerStatus value (string form).

    Any error code that means "we never got usable search results" → unavailable.
    Only an empty-but-successful response (handled elsewhere) → no_match.
    """
    if code in _UNAVAILABLE_ERROR_CODES:
        return "unavailable"
    return "no_match"


def _json_serializer(obj: object) -> str:
    """Custom JSON serializer for datetime and UUID."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, uuid.UUID):
        return str(obj)
    raise TypeError(f"Not JSON serializable: {type(obj)}")


# MARK: - Relevance Scoring

_MODEL_PATTERNS = [
    # Letters + digits (optional hyphen between letters and digits, trailing alpha/digit).
    # Matches WH-1000XM5, WH1000XM5/B, SM-G998, MDR-1A.
    re.compile(r'[A-Z]{1,3}-?\d{1,2}-?\d{3,5}[A-Z]*\d*(?:/[A-Z0-9]+)?', re.IGNORECASE),
    # M-series / generation markers (M1, M4, Gen 3, Series X, v2).
    re.compile(r'\b(?:M[1-9]\d?|Gen\s*\d+|Series\s*[A-Z0-9]+|v\d+)\b', re.IGNORECASE),
    # Title-case word + digit model names (e.g. "Flip 6", "Clip 5", "Stick 4K").
    # No IGNORECASE — model words are written as Title Case in product listings,
    # so we avoid matching random prose like "with 2 microphones".
    re.compile(r'\b[A-Z][a-z]{2,8}\s+\d+[A-Z]?\b'),
    # camelCase word + digit (e.g. "iPhone 16", "iPad 12", "iMac 24", "eReader 3").
    # Apple/Amazon brand naming: first letter lowercase, second uppercase, rest lowercase,
    # then a digit. Requires a word boundary so "onPro 5" (in running text) doesn't match.
    re.compile(r'\b[a-z][A-Z][a-z]{2,8}\s+\d+[A-Z]?\b'),
    # Brand camelCase + digit (e.g. "AirPods 2", "PlayStation 5", "MacBook 14").
    # Two title-case segments joined with no space (brand name camelCasing), then digit.
    re.compile(r'\b[A-Z][a-z]+[A-Z][a-z]+\s+\d+[A-Z]?\b'),
    # GPU-style: 2-5 uppercase letters + space + 3-5 digits (RTX 4090, GTX 1080, RX 7900).
    # Fed by Gemini's new `model` field — distinguishes RTX 4090 from RTX 4080 at the
    # hard-gate layer since the ident_to_regex is word-bounded.
    re.compile(r'\b[A-Z]{2,5}\s+\d{3,5}\b'),
    # Gaming-peripheral SKU: 1-2 uppercase letters immediately followed by 3-4
    # digits and an optional trailing letter. Matches Logitech G613/G915/G413,
    # Razer DeathAdder V2, Corsair K70, Razer Huntsman V3, many headset codes.
    # Uppercase-anchored (no IGNORECASE) so "a123" in running prose doesn't
    # inflate false-positive rate. Required to split G613 from G915 at the
    # model-number hard gate — otherwise Amazon's organic ranking swaps them.
    re.compile(r'\b[A-Z]{1,2}\d{3,4}[A-Z]?\b'),
]

# Variant / sub-model discriminator words. If two titles disagree on which of
# these words they contain, they describe different SKUs and must not match each
# other. Covers iPhone 16 vs 16 Pro/Plus/Max, iPad Air vs iPad Pro, PS5 Slim Disc
# vs PS5 Slim Digital, Nintendo Switch vs Switch OLED vs Switch Lite, etc.
_VARIANT_TOKENS = frozenset({
    "pro", "plus", "max", "mini", "ultra", "lite", "slim", "air",
    "digital", "disc",
    "se", "xl",
    "cellular", "wifi", "gps",
    "oled",
})

# Ordinal/generation marker tokens. Gemini's `model` field emits "(1st Gen)" for
# 1st-gen products that would otherwise token-overlap with later generations
# (e.g. "Galaxy Buds Pro (1st Gen)" vs "Galaxy Buds 2 Pro"). If product and
# listing disagree on which ordinals they contain, they are different generations.
# Symmetric — protects both directions. Trade-off: a real 1st-gen product whose
# retailer listing omits the "1st Gen" marker will fail this rule; in practice
# Gemini emits the marker only when it's load-bearing.
_ORDINAL_TOKENS = frozenset({
    "1st", "2nd", "3rd", "4th", "5th", "6th", "7th", "8th", "9th", "10th",
})

# NOTE: Size/spec patterns (256GB, 27", 11-inch) used to be in _MODEL_PATTERNS,
# but they were letting iPhone SE slip through for an iPhone 16 query — both titles
# contain "256GB", so any() matched on the spec alone. Specs are still captured
# through token overlap; they just don't act as a hard gate anymore.


# Supplier / catalog codes that Gemini or UPCitemdb sometimes bake into product names,
# e.g. "Apple iPhone 16 256GB Black (CBC998000002407)" or "… (JBLFLIP6TEALAM)". These
# codes never appear in retailer listing titles and break both search queries (Amazon's
# fuzzy matcher falls back to the wrong product) and the relevance hard gate. Strip them
# before using product.name for queries or relevance scoring. Descriptive parentheticals
# like "(Teal)", "(Black)", or "(1st gen)" are kept because their content has a lowercase
# letter or an internal space.
_PRODUCT_CODE_IN_PAREN = re.compile(r"\s*\(\s*[A-Z0-9][A-Z0-9.\-/]{4,}\s*\)")


def _clean_product_name(name: str) -> str:
    """Strip supplier/catalog codes from a resolved product name."""
    cleaned = _PRODUCT_CODE_IN_PAREN.sub("", name)
    return re.sub(r"\s+", " ", cleaned).strip()

_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "for", "with", "in", "of", "to",
    "is", "it", "by", "on", "at", "from", "new", "black", "white",
})

# Keywords that signal a listing is an accessory for the product, not the product
# itself. Match on whole words in the listing title. If the product name ALSO contains
# any of these tokens we do not apply the filter (e.g. a user searching for a "case"
# legitimately wants case listings).
_ACCESSORY_KEYWORDS = frozenset({
    "case", "cases", "cover", "covers", "protector", "protectors", "skin", "skins",
    "charger", "chargers", "cable", "cables", "adapter", "adapters", "dock", "docks",
    "stand", "stands", "mount", "mounts", "holder", "holders", "strap", "straps",
    "pouch", "bag", "sleeve", "sleeves",
    "compatible",
    "replacement",
    "accessory", "accessories",
    # Third-party service / repair / mod listings — surfaced mostly on eBay
    # where sellers list services as items (e.g. "Steam Deck OLED 32GB RAM
    # Upgrade Service"). The user wanted the device, not someone offering to
    # modify it.
    "service", "services",
    "repair", "repairs",
    "modding", "modded",
    "refurbishment",
})
# Pattern for "for iPhone", "fits iPad", "designed for" — prepositional accessory markers.
_ACCESSORY_PHRASE_RE = re.compile(
    r"\b(?:for|fits|designed\s+for|compatible\s+with)\s+(?:apple|sony|samsung|jbl|bose|google|microsoft|the|your|new)?\s*(?:i?Phone|i?Pad|i?Mac|AirPods|Galaxy|Pixel|Surface|MacBook|Watch)\b",
    re.IGNORECASE,
)


def _is_accessory_listing(listing_title: str, product_tokens: set[str]) -> bool:
    """Return True if the listing title looks like an accessory FOR a product,
    not the product itself. Skipped if the resolved product name contains any
    of the accessory keywords (so someone searching for a case gets cases)."""
    if not listing_title:
        return False
    # If the product itself is an accessory, don't filter.
    if product_tokens & _ACCESSORY_KEYWORDS:
        return False
    lower = listing_title.lower()
    tokens = set(re.findall(r"[a-z0-9]+", lower))
    if tokens & _ACCESSORY_KEYWORDS:
        return True
    if _ACCESSORY_PHRASE_RE.search(listing_title):
        return True
    return False


# Hardware-intent tokens that indicate a listing IS the device (or a bundle that
# includes the device), not a game/accessory FOR it. If any of these appear in a
# listing title, the platform-suffix filter (`_is_platform_suffix_accessory`) is
# skipped — so "Nintendo Switch 2 Bundle with Mario Kart" survives even though
# the game token is present.
_HARDWARE_INTENT_TOKENS = frozenset({
    "bundle", "bundles", "console", "consoles", "system", "systems",
    "hardware", "edition",
})

# Separator tokens that introduce a tail descriptor in a listing title.
# Whitespace-padded "-", "–", "—", ":", "|", "/" or an opening "(".
_SEPARATOR_BEFORE_IDENT_RE = re.compile(r"\s[\-\u2013\u2014:|/]\s|\s\(")


def _is_platform_suffix_accessory(
    listing_title: str, product_identifiers: list[str]
) -> bool:
    """Detect '[Game/Accessory Name] - [Platform]' tail-descriptor pattern.

    Amazon's organic search for console queries (e.g. "Nintendo Switch 2") is
    flooded with games and peripherals whose titles encode the platform as a
    tail descriptor: "NBA 2K25 - Nintendo Switch 2", "Mario Kart 9
    (Nintendo Switch 2)". The token-overlap and brand-match rules in
    `_score_listing_relevance` accept these because the platform name is
    fully present in the title.

    Returns True only when ALL of:
      1. The listing has a hit on one of the product identifiers
         (e.g. "Switch 2") AFTER a separator (-, (, |, :, /).
      2. The leading text (before the separator) has >=2 substantive tokens.
      3. The listing does NOT contain any hardware-intent token
         (bundle / console / system / edition / hardware) — bundles pass.

    Amazon-scoped: called only from `_pick_best_listing` when
    `response.retailer_id == "amazon"`. Other retailers don't surface this
    pattern at meaningful rates in observed data.
    """
    if not product_identifiers or len(listing_title) < 12:
        return False

    title_tokens = _tokenize(listing_title)
    if title_tokens & _HARDWARE_INTENT_TOKENS:
        return False

    for ident in product_identifiers:
        match = _ident_to_regex(ident).search(listing_title)
        if not match:
            continue
        leading = listing_title[: match.start()]
        if not _SEPARATOR_BEFORE_IDENT_RE.search(leading):
            continue
        leading_tokens = _tokenize(leading)
        if len(leading_tokens) >= 2:
            return True
    return False


_BRAND_SUFFIXES = re.compile(r'\s*(?:Inc\.?|Corp\.?|LLC|Ltd\.?|Co\.?)$', re.IGNORECASE)

RELEVANCE_THRESHOLD = 0.4

# Marketplace retailers benefit from a price-outlier pass: sellers list
# accessories, parts, and plain wrong listings at a fraction of the real
# product's price. Drop anything <40 % of the retailer's own median when
# we have at least 4 listings to trust the median.
_MARKETPLACE_RETAILERS: frozenset[str] = frozenset({
    "ebay_new", "ebay_used", "fb_marketplace",
})
_PRICE_OUTLIER_FLOOR = 0.40
_PRICE_OUTLIER_MIN_SAMPLE = 4

# fb_marketplace sellers routinely post genuine listings without the
# manufacturer model code ("Razer Orbweaver Chroma" instead of
# "RZ07-01440100-R3U1"). Applying the model-number hard gate there
# drops real listings and leaves only misclassified ones. For FB only,
# a listing missing the model gets a soft penalty (0.5) instead of 0.0
# as long as brand + token overlap clear the bar.
_MODEL_SOFT_GATE_RETAILERS: frozenset[str] = frozenset({"fb_marketplace"})


# Captures the "family stem" of a hyphenated SKU — for a match like
# RZ07-00740100, the stem is RZ07-0074 (letters + first digit group + first 4
# digits of the second group) and the tail is the remaining variant digits.
_LONG_MODEL_PREFIX_RE = re.compile(
    r"^([A-Z]{1,3}-?\d{1,2}-?\d{4})(\d{2,})$", re.IGNORECASE
)


def _extract_model_identifiers(name: str) -> list[str]:
    """Extract model numbers from a product name (spec-only patterns excluded).

    For long variant-coded models (8+ digit block after the letter prefix), also
    emit a 4-digit "family" prefix. Example: RZ07-00740100 → [RZ07-00740100,
    RZ07-0074]. Sellers routinely list the family stem without the full variant
    suffix ("Razer Orbweaver RZ07-0074"), and requiring the full code drops
    legitimate listings. The 4-digit floor is deliberate: 3 digits would be too
    permissive (too many unrelated products share a 3-digit prefix).
    """
    identifiers: list[str] = []
    for pattern in _MODEL_PATTERNS:
        identifiers.extend(pattern.findall(name))
    extra_prefixes: list[str] = []
    for ident in identifiers:
        m = _LONG_MODEL_PREFIX_RE.match(ident)
        if m:
            extra_prefixes.append(m.group(1))
    return identifiers + extra_prefixes


def _tokenize(text: str) -> set[str]:
    """Lowercase, strip punctuation, remove stopwords."""
    tokens = re.findall(r'[a-z0-9]+', text.lower())
    return {t for t in tokens if t not in _STOPWORDS and len(t) > 1}


def _ident_to_regex(ident: str) -> re.Pattern:
    """Build a case-insensitive regex with word-boundary anchors for an identifier.

    Whitespace in the identifier is loosened to ``\\s+`` so "Flip 6" matches any
    whitespace between the word and the digit. The ``\\b`` anchors prevent spurious
    prefix matches — "iPhone 16" must NOT match "iPhone 16e" (a different model)
    or "iPhone 160" (hypothetical).
    """
    parts = [re.escape(p) for p in re.split(r'\s+', ident.strip()) if p]
    body = r'\s+'.join(parts)
    return re.compile(r'(?<!\w)' + body + r'(?!\w)', re.IGNORECASE)


def _score_listing_relevance(
    listing_title: str,
    product: Product,
    retailer_id: str | None = None,
) -> float:
    """Score how relevant a listing title is to the resolved product (0.0–1.0).

    Rules applied in order:
    0. Accessory filter: reject listings that are cases/covers/protectors/etc.
       when the product itself is not an accessory.
    1. Model number hard gate: if product has strong identifiers, at least one
       must appear in the listing title with word-boundary anchors
       (so "iPhone 16" doesn't match "iPhone 16e").
    2. Variant token equality: if product and listing differ in which variant
       words they contain ({pro, plus, max, mini, disc, digital, ...}), they're
       different SKUs — reject.
    2b. Ordinal equality: same check over generation markers (1st / 2nd / 3rd …)
        fed by Gemini's `model` field.
    3. Brand match: product.brand must appear in listing title.
    4. Token overlap tiebreaker: |intersection| / |product_tokens|.
    """
    clean_name = _clean_product_name(product.name)
    product_identifiers = _extract_model_identifiers(clean_name)
    product_tokens_set = _tokenize(clean_name)

    # Pull richer `model` identifiers from source_raw if present.
    # The model field adds generation markers ("1st Gen"), clean model numbers
    # ("RTX 4090"), and capacity ("256GB") that product.name may lack. Union
    # identifiers + tokens so downstream rules see both signals.
    #
    # Two source lanes:
    #   - Gemini-sourced products store the richer string at source_raw.gemini_model
    #   - UPCitemdb-sourced products store the raw API payload at
    #     source_raw.upcitemdb_raw; the canonical model lives at its .model key.
    # Missing either one silently falls through — the baseline product.name
    # extraction above already ran.
    extra_model_strings: list[str] = []
    if product.source_raw and isinstance(product.source_raw, dict):
        gm = product.source_raw.get("gemini_model")
        if gm:
            extra_model_strings.append(gm)
        upc_raw = product.source_raw.get("upcitemdb_raw")
        if isinstance(upc_raw, dict):
            um = upc_raw.get("model")
            if um:
                extra_model_strings.append(um)
    for m in extra_model_strings:
        clean_model = _clean_product_name(m)
        product_identifiers = product_identifiers + _extract_model_identifiers(clean_model)
        product_tokens_set = product_tokens_set | _tokenize(clean_model)

    title_lower = listing_title.lower()
    listing_tokens = _tokenize(listing_title)

    # Rule 0: Accessory filter (rejects "case/cover/protector/compatible with X" listings)
    if _is_accessory_listing(listing_title, product_tokens_set):
        return 0.0

    # Rule 1: Model number hard gate (word-boundary regex, not substring).
    # For soft-gate retailers (e.g. fb_marketplace, where sellers routinely
    # skip the model code) we don't reject outright — instead we cap the
    # final score at 0.5 so a listing can still pass only if brand +
    # token overlap carry it. Tracked via ``model_missing`` below.
    model_missing = False
    if product_identifiers:
        patterns = [_ident_to_regex(ident) for ident in product_identifiers]
        if not any(p.search(listing_title) for p in patterns):
            if retailer_id not in _MODEL_SOFT_GATE_RETAILERS:
                return 0.0
            model_missing = True

    # Rule 2: Variant token equality — product and listing must agree on which
    # sub-variant words they contain (pro / plus / max / disc / digital / …).
    product_variants = product_tokens_set & _VARIANT_TOKENS
    listing_variants = listing_tokens & _VARIANT_TOKENS
    if product_variants != listing_variants:
        return 0.0

    # Rule 2b: Ordinal/generation marker equality. Gemini's `model` field emits
    # "(1st Gen)" for 1st-gen products that would otherwise token-overlap with
    # later generations. {1st} != {} rejects "Galaxy Buds 2 Pro" for a
    # "Galaxy Buds Pro (1st Gen)" query. Symmetric.
    product_ordinals = product_tokens_set & _ORDINAL_TOKENS
    listing_ordinals = listing_tokens & _ORDINAL_TOKENS
    if product_ordinals != listing_ordinals:
        return 0.0

    # Rule 3: Brand match (skip if brand is unknown)
    if product.brand:
        clean_brand = _BRAND_SUFFIXES.sub("", product.brand).strip()
        if clean_brand and clean_brand.lower() not in title_lower:
            return 0.0

    # Rule 4: Token overlap (use cleaned name so supplier codes don't pollute tokens)
    product_tokens = product_tokens_set

    if not product_tokens:
        return 0.5  # Can't score — assume passable

    overlap = len(product_tokens & listing_tokens)
    score = overlap / len(product_tokens)

    if model_missing:
        score = min(score, 0.5)

    return score if score >= RELEVANCE_THRESHOLD else 0.0


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
        self,
        product_id: uuid.UUID,
        force_refresh: bool = False,
        fb_location_id: str | None = None,
        fb_radius_miles: int | None = None,
    ) -> dict:
        """Full price comparison pipeline. Returns dict matching PriceComparisonResponse.

        ``fb_location_id`` / ``fb_radius_miles`` scope the FB Marketplace
        leg (and therefore the cache bucket) to the caller's chosen city.
        Omitting them shares the env-default bucket with other callers.
        """
        # Step 1: Validate product exists
        product = await self._validate_product(product_id)

        # Step 2: Check Redis cache
        if not force_refresh:
            cached = await self._check_redis(
                product_id,
                fb_location_id=fb_location_id,
                fb_radius_miles=fb_radius_miles,
            )
            if cached is not None:
                logger.info("Price cache hit (Redis) for product %s", product_id)
                return cached

        # Step 3: Check DB for fresh prices
        if not force_refresh:
            db_result = await self._check_db_prices(product_id, product.name)
            if db_result is not None:
                logger.info("Price cache hit (DB) for product %s", product_id)
                await self._cache_to_redis(
                    product_id,
                    db_result,
                    fb_location_id=fb_location_id,
                    fb_radius_miles=fb_radius_miles,
                )
                return db_result

        # Step 4: Dispatch to containers
        query = self._build_query(product)
        logger.info("Dispatching to containers for product %s: %s", product_id, query)
        responses = await self.container_client.extract_all(
            query=query,
            product_name=product.name,
            upc=product.upc,
            fb_location_id=fb_location_id,
            fb_radius_miles=fb_radius_miles,
        )

        # Step 5-8: Normalize, upsert, record history, build response
        now = datetime.now(UTC)
        prices_data: list[dict] = []
        retailer_results: list[dict] = []  # per-retailer status for all 11
        succeeded = 0
        failed = 0
        history_offset = 0  # Microsecond offset to avoid PK collision on price_history

        # Pre-load all retailer display names so we can label every row, even failed ones.
        all_retailer_ids = list(responses.keys())
        all_retailer_names = await self._load_retailer_names(all_retailer_ids)

        for retailer_id, response in responses.items():
            retailer_name = all_retailer_names.get(retailer_id, retailer_id)
            result, price_payload, best_listing = self._classify_retailer_result(
                retailer_id, retailer_name, response, product, now,
                fb_location_id=fb_location_id,
            )
            retailer_results.append(result)

            if result["status"] == "success":
                succeeded += 1
                await self._upsert_price(product_id, retailer_id, best_listing, now)
                # Append all listings to price_history (unique timestamp per record)
                for listing in response.listings:
                    history_time = now + timedelta(microseconds=history_offset)
                    history_offset += 1
                    await self._append_price_history(
                        product_id, retailer_id, listing, history_time
                    )
                prices_data.append(price_payload)
            else:
                failed += 1

        await self.db.flush()

        # Sort by price ascending. retailer_name is already inlined by
        # _classify_retailer_result, so the previous "Step 9" name-merge
        # loop was removed in 2i-b.
        prices_data.sort(key=lambda p: p["price"])

        # Sort retailer_results so success rows come first, then no_match, then unavailable.
        _status_order = {"success": 0, "no_match": 1, "unavailable": 2}
        retailer_results.sort(
            key=lambda r: (_status_order.get(r["status"], 99), r["retailer_name"])
        )

        result = {
            "product_id": str(product_id),
            "product_name": product.name,
            "prices": prices_data,
            "retailer_results": retailer_results,
            "total_retailers": len(responses),
            "retailers_succeeded": succeeded,
            "retailers_failed": failed,
            "cached": False,
            "fetched_at": now.isoformat(),
        }

        # Step 10: Cache to Redis
        await self._cache_to_redis(
            product_id,
            result,
            fb_location_id=fb_location_id,
            fb_radius_miles=fb_radius_miles,
        )

        return result

    # MARK: - Streaming (Step 2c)

    async def stream_prices(
        self,
        product_id: uuid.UUID,
        force_refresh: bool = False,
        query_override: str | None = None,
        fb_location_id: str | None = None,
        fb_radius_miles: int | None = None,
    ) -> AsyncGenerator[tuple[str, dict], None]:
        """Yield per-retailer SSE events (`retailer_result`, `done`, `error`) as
        results arrive. Uses `asyncio.as_completed` over per-retailer tasks so
        the iPhone sees each retailer the moment it finishes — Walmart ~12s,
        Amazon ~30s, and Best Buy ~91s arrive independently instead of the
        caller waiting ~120s for the whole batch.

        Classification of each retailer response is delegated to
        ``_classify_retailer_result`` so this path and ``get_prices`` agree
        on status mapping and price payload shape (extracted in 2i-b).
        The two methods still differ in iteration strategy (as_completed vs
        serial dict iteration) and emission semantics (yields events vs
        accumulates a dict) — that's why they're not merged.
        """
        product = await self._validate_product(product_id)

        # `query_override` (sent by iOS when the user tapped a generic search
        # row like "Apple iPhone 16 [Any variant]") replaces both the search
        # query AND the per-container product_name hint so retailers search
        # the bare generic string instead of the resolved variant's title.
        #
        # Cache strategy:
        #   - Bare-name overrides use a SCOPED key (`…:q:<sha1>`) with a
        #     30-min TTL — separate namespace from the SKU-resolved cache so
        #     a generic "Steam Deck OLED" search can't pollute a specific
        #     "Steam Deck OLED 512GB" run, and vice versa. Repeats of the
        #     same generic query within 30 min replay deterministically.
        #   - Non-override runs use the bare product key (6h TTL).
        # `force_refresh=True` still bypasses both.

        # Cache path — replay stored results and short-circuit.
        if not force_refresh:
            cached = await self._check_redis(
                product_id,
                query_override,
                fb_location_id=fb_location_id,
                fb_radius_miles=fb_radius_miles,
            )
            if cached is None and not query_override and not fb_location_id:
                # DB freshness short-circuit applies only to unscoped runs.
                # A bare-name override asked for a different interpretation;
                # a location override asked for different-city results; in
                # either case the prices table has no notion of "which
                # scope produced this row", so falling through to the DB
                # would serve stale or wrong data. Safer to dispatch fresh.
                cached = await self._check_db_prices(product_id, product.name)
                if cached is not None:
                    await self._cache_to_redis(
                        product_id,
                        cached,
                        fb_location_id=fb_location_id,
                        fb_radius_miles=fb_radius_miles,
                    )
            if cached is not None:
                logger.info(
                    "stream_prices cache hit for product %s (override=%s)",
                    product_id,
                    bool(query_override),
                )
                prices_by_rid = {
                    p["retailer_id"]: p for p in cached.get("prices", [])
                }
                for r in cached.get("retailer_results", []):
                    yield (
                        "retailer_result",
                        {
                            "retailer_id": r["retailer_id"],
                            "retailer_name": r["retailer_name"],
                            "status": r["status"],
                            "price": prices_by_rid.get(r["retailer_id"]),
                        },
                    )
                yield (
                    "done",
                    {
                        "product_id": str(product_id),
                        "product_name": cached.get("product_name", product.name),
                        "total_retailers": cached.get("total_retailers", 0),
                        "retailers_succeeded": cached.get("retailers_succeeded", 0),
                        "retailers_failed": cached.get("retailers_failed", 0),
                        "cached": True,
                        "fetched_at": cached.get("fetched_at"),
                    },
                )
                return

        # Live path — dispatch every retailer, yield as each completes.
        query = query_override if query_override else self._build_query(product)
        # When the override is in play, drop the variant-specific name hint
        # too — otherwise containers might still latch onto the SKU title.
        product_name_for_containers = (
            query_override if query_override else product.name
        )
        ids = list(self.container_client.ports.keys())
        names = await self._load_retailer_names(ids)
        logger.info(
            "stream_prices dispatching %d retailers for product %s: %s%s",
            len(ids),
            product_id,
            query,
            " (override)" if query_override else "",
        )

        async def _fetch_one(rid: str) -> tuple[str, ContainerResponse]:
            resp = await self.container_client._extract_one(
                rid,
                query,
                product_name_for_containers,
                product.upc,
                10,
                fb_location_id=fb_location_id,
                fb_radius_miles=fb_radius_miles,
            )
            return rid, resp

        tasks = [asyncio.create_task(_fetch_one(rid)) for rid in ids]

        now = datetime.now(UTC)
        prices_data: list[dict] = []
        retailer_results: list[dict] = []
        succeeded = 0
        failed = 0
        history_offset = 0

        try:
            for fut in asyncio.as_completed(tasks):
                retailer_id, response = await fut
                retailer_name = names.get(retailer_id, retailer_id)
                result, price_payload, best_listing = self._classify_retailer_result(
                    retailer_id, retailer_name, response, product, now,
                    fb_location_id=fb_location_id,
                )
                retailer_results.append(result)

                if result["status"] == "success":
                    succeeded += 1
                    await self._upsert_price(
                        product_id, retailer_id, best_listing, now
                    )
                    for listing in response.listings:
                        history_time = now + timedelta(microseconds=history_offset)
                        history_offset += 1
                        await self._append_price_history(
                            product_id, retailer_id, listing, history_time
                        )
                    prices_data.append(price_payload)
                else:
                    failed += 1

                yield ("retailer_result", {**result, "price": price_payload})

            await self.db.flush()
        except asyncio.CancelledError:
            # Client disconnected — cancel pending tasks and propagate.
            for t in tasks:
                t.cancel()
            raise
        except Exception as e:
            logger.exception("stream_prices pipeline error")
            yield ("error", {"code": "STREAM_ERROR", "message": str(e)})
            return

        # Sort + cache the aggregate (same shape get_prices builds).
        prices_data.sort(key=lambda p: p["price"])
        _status_order = {"success": 0, "no_match": 1, "unavailable": 2}
        retailer_results.sort(
            key=lambda r: (
                _status_order.get(r["status"], 99),
                r["retailer_name"],
            )
        )

        final = {
            "product_id": str(product_id),
            "product_name": product.name,
            "prices": prices_data,
            "retailer_results": retailer_results,
            "total_retailers": len(ids),
            "retailers_succeeded": succeeded,
            "retailers_failed": failed,
            "cached": False,
            "fetched_at": now.isoformat(),
        }
        # Bare-name override runs cache to a SCOPED key (30min TTL) so the
        # next user tapping the same "Any variant" row gets a deterministic
        # replay; non-override runs cache to the bare product key (6h TTL).
        # Per-location marketplace runs add a further ``:loc:…`` suffix.
        # The namespaces are disjoint, so no path can pollute another.
        await self._cache_to_redis(
            product_id,
            final,
            query_override,
            fb_location_id=fb_location_id,
            fb_radius_miles=fb_radius_miles,
        )

        yield (
            "done",
            {
                "product_id": str(product_id),
                "product_name": product.name,
                "total_retailers": len(ids),
                "retailers_succeeded": succeeded,
                "retailers_failed": failed,
                "cached": False,
                "fetched_at": now.isoformat(),
            },
        )

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

    async def _check_redis(
        self,
        product_id: uuid.UUID,
        query_override: str | None = None,
        fb_location_id: str | None = None,
        fb_radius_miles: int | None = None,
    ) -> dict | None:
        """Check Redis for a cached price comparison result.

        When ``query_override`` is supplied, looks up the scoped key
        (``…:q:<sha1>``) instead of the bare product key — that's the cache
        for bare-name "Any variant" generic-row searches, kept separate so it
        can't pollute or be polluted by SKU-specific runs. When
        ``fb_location_id`` is set, the key also carries a ``:loc:…`` suffix
        so per-user marketplace location doesn't leak between callers.
        """
        key = self._cache_key(
            product_id, query_override, fb_location_id, fb_radius_miles
        )
        cached = await self.redis.get(key)
        if cached is None:
            return None
        try:
            data = cached if isinstance(cached, str) else cached.decode()
            return json.loads(data)
        except (json.JSONDecodeError, UnicodeDecodeError):
            await self.redis.delete(key)
            return None

    @staticmethod
    def _cache_key(
        product_id: uuid.UUID,
        query_override: str | None,
        fb_location_id: str | None = None,
        fb_radius_miles: int | None = None,
    ) -> str:
        """Compose the Redis cache key for a price comparison.

        Bare product key for SKU-resolved runs; scoped key (suffix
        ``:q:<sha1>``) for bare-name override runs. When a user supplies a
        non-default fb_marketplace location, an additional
        ``:loc:<id>:r<miles>`` suffix fences their results away from the
        env-default bucket so two users on different coasts don't collide.
        We keep radius in miles (user-intent unit) even though the
        container receives km — two users picking 25 mi vs 15 mi in the
        same metro are asking different questions and deserve different
        buckets. The namespaces are intentionally disjoint — one cannot
        serve another.
        """
        key = f"{REDIS_KEY_PREFIX}{product_id}"
        if query_override:
            key += f"{REDIS_KEY_QUERY_SUFFIX}{_query_scope_digest(query_override)}"
        if fb_location_id:
            radius_label = str(fb_radius_miles) if fb_radius_miles else "x"
            key += f":loc:{fb_location_id}:r{radius_label}"
        return key

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

        # DB cache path only retains rows that produced prices. We don't know why
        # other retailers failed in the original run, so only label the known-good
        # ones here. The iOS side treats an absent entry as "not shown".
        retailer_results = [
            {
                "retailer_id": p["retailer_id"],
                "retailer_name": p["retailer_name"],
                "status": "success",
            }
            for p in prices_data
        ]

        return {
            "product_id": str(product_id),
            "product_name": product_name,
            "prices": prices_data,
            "retailer_results": retailer_results,
            "total_retailers": len(prices_data),
            "retailers_succeeded": len(prices_data),
            "retailers_failed": 0,
            "cached": True,
            "fetched_at": prices[0].last_checked.isoformat(),
        }

    def _build_query(self, product: Product) -> str:
        """Build search query from product name and brand.

        Supplier codes (e.g. the CBC… in 'Apple iPhone 16 256GB Black (CBC998000002407)')
        are stripped — retailer search engines fuzzy-match on them and return the wrong
        product. Descriptive parentheticals like '(Teal)' are preserved.
        """
        parts = [_clean_product_name(product.name)]
        if product.brand:
            parts.append(product.brand)
        return " ".join(parts)

    def _pick_best_listing(
        self, response: ContainerResponse, product: Product
    ) -> tuple | tuple[None, float]:
        """Pick the lowest-priced, relevance-filtered listing from a container response.

        Returns (listing, relevance_score) or (None, 0.0).

        NOTE(D11): Keeps only the cheapest listing per retailer. All listings are
        recorded in price_history, but only the cheapest is shown.

        Filters:
        1. Price > 0 (parse failure guard — SP-7)
        2. Amazon-only: drop platform-suffix games/accessories (e.g. "NBA 2K25 -
           Nintendo Switch 2") — Amazon's organic ranking surfaces them above
           the actual console; bundles/console/system listings are kept.
        3. Relevance score >= 0.4 (wrong-product guard — SP-10)
        4. Availability preference (available > unavailable)
        5. Cheapest wins among survivors
        """
        # Filter zero-price parse failures
        valid = [item for item in response.listings if item.price and item.price > 0]
        if not valid:
            return None, 0.0

        # Amazon-only platform-suffix filter (e.g. drops "NBA 2K25 - Nintendo
        # Switch 2" when looking for the Switch 2 console). Other retailers
        # don't show this pattern at meaningful rates.
        if response.retailer_id == "amazon":
            product_identifiers = _extract_model_identifiers(
                _clean_product_name(product.name)
            )
            if product.source_raw and isinstance(product.source_raw, dict):
                gemini_model = product.source_raw.get("gemini_model")
                if gemini_model:
                    product_identifiers = product_identifiers + _extract_model_identifiers(
                        _clean_product_name(gemini_model)
                    )
            if product_identifiers:
                valid = [
                    item for item in valid
                    if not _is_platform_suffix_accessory(item.title, product_identifiers)
                ]
                if not valid:
                    return None, 0.0

        # Marketplace price-outlier filter: on eBay/FB, sellers list empty
        # boxes, parts, and wrong products at a fraction of the real price.
        # Use the retailer's own median (not a fixed cash floor) so every
        # product category calibrates itself. Min-sample 4 keeps a retailer
        # with 1–3 listings from dropping everything on a weak median.
        if (
            response.retailer_id in _MARKETPLACE_RETAILERS
            and len(valid) >= _PRICE_OUTLIER_MIN_SAMPLE
        ):
            from statistics import median
            med = median(item.price for item in valid)
            if med > 0:
                floor = med * _PRICE_OUTLIER_FLOOR
                valid = [item for item in valid if item.price >= floor]
                if not valid:
                    return None, 0.0

        # Score and filter by relevance
        scored = []
        for item in valid:
            score = _score_listing_relevance(
                item.title, product, retailer_id=response.retailer_id
            )
            if score >= RELEVANCE_THRESHOLD:
                scored.append((item, score))

        if not scored:
            return None, 0.0

        # Prefer available listings
        available = [(item, s) for item, s in scored if item.is_available]
        if not available:
            available = scored

        best_item, best_score = min(available, key=lambda pair: pair[0].price)
        return best_item, best_score

    def _classify_retailer_result(
        self,
        retailer_id: str,
        retailer_name: str,
        response: ContainerResponse,
        product: Product,
        now: datetime,
        fb_location_id: str | None = None,
    ) -> tuple[dict, dict | None, ContainerListing | None]:
        """Classify a single container response into normalized output.

        Pure function over the response — no DB writes, no SSE emission.
        Both ``get_prices()`` (batch) and ``stream_prices()`` (SSE) call this
        to produce the same classification, then handle persistence and
        emission separately. Extracted in 2i-b to delete ~40 lines of
        duplicated branch logic; the previous in-line implementations had
        already drifted apart slightly (stream embedded ``retailer_name``
        in the price payload directly while batch added it later) and the
        risk was that a bug fix in one wouldn't propagate.

        ``fb_location_id`` (when provided) is used for one thing only:
        flagging the fb_marketplace row's ``location_default_used`` so iOS
        can show a "Using SF default — set your city in Profile" pill when
        the user never picked a location. The flag is added only to the
        fb_marketplace row to keep other retailers' payloads unchanged.

        Returns a tuple of ``(retailer_result, price_payload, best_listing)``:

        - ``retailer_result``: dict with ``retailer_id``, ``retailer_name``,
          ``status`` — appended to the per-retailer status list in both paths.
        - ``price_payload``: dict matching the wire shape (with
          ``retailer_name`` already inlined) on success, ``None`` otherwise.
        - ``best_listing``: the chosen ``ContainerListing`` on success
          (caller uses it for ``_upsert_price``), ``None`` otherwise.
        """
        if response.error is not None:
            status = _classify_error_status(response.error.code)
            return (
                {"retailer_id": retailer_id, "retailer_name": retailer_name, "status": status},
                None,
                None,
            )

        if not response.listings:
            return (
                {"retailer_id": retailer_id, "retailer_name": retailer_name, "status": "no_match"},
                None,
                None,
            )

        best_listing, relevance = self._pick_best_listing(response, product)
        if best_listing is None:
            return (
                {"retailer_id": retailer_id, "retailer_name": retailer_name, "status": "no_match"},
                None,
                None,
            )

        price_payload = {
            "retailer_id": retailer_id,
            "retailer_name": retailer_name,
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
            "relevance_score": relevance,
        }
        # Scope the flag to fb_marketplace so other retailers' payloads
        # stay byte-identical to the pre-followup shape. Only emit when
        # the container fell back to its baked default (no location_id
        # supplied at request time) — the iOS pill key.
        if retailer_id == "fb_marketplace" and not fb_location_id:
            price_payload["location_default_used"] = True
        return (
            {"retailer_id": retailer_id, "retailer_name": retailer_name, "status": "success"},
            price_payload,
            best_listing,
        )

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
        self,
        product_id: uuid.UUID,
        data: dict,
        query_override: str | None = None,
        fb_location_id: str | None = None,
        fb_radius_miles: int | None = None,
    ) -> None:
        """Cache the price comparison result to Redis.

        - Bare product key (``query_override`` None): 6h TTL when there are
          prices, 30min when empty (so users re-scanning get fresh attempts
          sooner).
        - Scoped query key (``query_override`` set): 30min TTL regardless,
          since bare-name runs are inherently fuzzier and we want to refresh
          them sooner; still uses the empty-result TTL when there are no
          prices to ensure the same fast retry semantics.
        - Location-scoped key (``fb_location_id`` set): same TTL rule as
          the bare key — the per-location suffix simply keeps distinct
          users' FB Marketplace results from leaking across city buckets.
        """
        key = self._cache_key(
            product_id, query_override, fb_location_id, fb_radius_miles
        )
        serialized = json.dumps(data, default=_json_serializer)
        if query_override:
            ttl = REDIS_CACHE_TTL_QUERY
        elif not data.get("prices"):
            ttl = REDIS_CACHE_TTL_EMPTY
        else:
            ttl = REDIS_CACHE_TTL
        await self.redis.set(key, serialized, ex=ttl)
