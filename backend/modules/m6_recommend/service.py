"""RecommendationService — deterministic multi-layer stacking (Step 3e).

Zero LLM. One `asyncio.gather` over the existing identity / card / price /
portal services, then pure Python math. Target p95 < 150 ms.

Stacking model (conservative):
  final_price    = base_price - identity_savings     # sticker
  effective_cost = final_price - card - portal        # net of rebates
  total_savings  = identity + card + portal           # headline number

Card + portal are computed on the POST-identity price (we don't earn
rewards on money we never paid). Winner = min(effective_cost), with
condition (new > refurbished > used) and then a well-known-retailer
preference as tiebreakers.
"""

import asyncio
import hashlib
import json
import logging
import time
from decimal import Decimal
from uuid import UUID

import redis.asyncio as aioredis
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core_models import Retailer, RetailerHealth
from modules.m1_product.models import Product
from modules.m2_prices.service import PriceAggregationService
from modules.m5_identity.card_schemas import CardRecommendation
from modules.m5_identity.card_service import CardService
from modules.m5_identity.models import PortalBonus, UserCard, UserDiscountProfile
from modules.m5_identity.schemas import EligibleDiscount
from modules.m5_identity.service import IdentityService
from modules.m6_recommend.schemas import (
    BrandDirectCallout,
    Recommendation,
    StackedPath,
)
from modules.m13_portal.service import PortalMonetizationService

logger = logging.getLogger("barkain.m6")


# MARK: - Policy knobs

# Minimum retailer count below which we bail — recommending something
# when we only found one price is worse than showing nothing.
_MIN_RETAILER_COUNT = 2

# Retailers we prefer when two candidates tie on effective_cost + condition.
# Order matters — higher in the list wins. Facebook Marketplace and
# refurbished sellers sit at the bottom because the demo story works
# better when the call is "Amazon with your Chase card" than
# "Facebook Marketplace with cash".
_WELL_KNOWN_RETAILER_ORDER: tuple[str, ...] = (
    "amazon", "best_buy", "walmart", "target", "home_depot",
    "ebay_new", "backmarket", "ebay_used", "fb_marketplace",
)

# new > refurbished > used — tiebreak after effective_cost.
_CONDITION_RANK: dict[str, int] = {"new": 0, "refurbished": 1, "used": 2}

# Brand-direct callout threshold — below this we don't bother pinging
# users to verify their military/veteran status for a 10 % savings.
_BRAND_DIRECT_MIN_DISCOUNT_PCT = 15.0

# Redis cache — 15 min is long enough to spam-tap safe, short enough to
# not surface stale prices after a scraper run.
_CACHE_TTL_SECONDS = 15 * 60
_CACHE_KEY_PREFIX = "recommend:user:"


class InsufficientPriceDataError(Exception):
    """Raised when < 2 successful retailer prices — router maps to 422."""


class RecommendationProductNotFoundError(Exception):
    """Raised when the product_id doesn't exist — router maps to 404."""


# MARK: - Service


class RecommendationService:
    """Deterministic stacking over Prices + Identity + Cards + Portals."""

    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self.db = db
        self.redis = redis
        self.price_service = PriceAggregationService(db, redis)
        self.identity_service = IdentityService(db)
        self.card_service = CardService(db)
        self.portal_service = PortalMonetizationService(db)

    # MARK: - Public entry point

    async def get_recommendation(
        self,
        user_id: str,
        product_id: UUID,
        *,
        force_refresh: bool = False,
        user_memberships: dict[str, bool] | None = None,
    ) -> Recommendation:
        """Build the full recommendation. Raises on insufficient data."""
        started = time.perf_counter()
        memberships = user_memberships or {}

        # Step 3f Pre-Fix #6 + 3g-B: cache key includes user-state hashes so
        # adding a card / flipping an identity flag / toggling a portal
        # membership all bust stale recs. Lookups are cheap (~5 ms combined,
        # all indexed by user_id; memberships hash is a pure-Python sort).
        user_card_hash = await self._user_card_hash(user_id)
        identity_hash = await self._identity_flag_hash(user_id)
        portal_hash = _portal_membership_hash(memberships)

        if not force_refresh:
            cached = await self._read_cache(
                user_id, product_id, user_card_hash, identity_hash, portal_hash
            )
            if cached is not None:
                return cached.model_copy(update={"cached": True})

        (
            product,
            prices_payload,
            identity_resp,
            cards_resp,
            portal_rows,
            active_retailer_ids,
            drift_flagged,
        ) = await self._gather_inputs(user_id, product_id)

        # Filter prices to the successful, active, healthy set.
        eligible_prices = self._filter_prices(
            prices_payload.get("prices", []),
            active_retailer_ids=active_retailer_ids,
            drift_flagged=drift_flagged,
        )
        if len(eligible_prices) < _MIN_RETAILER_COUNT:
            raise InsufficientPriceDataError(
                f"Only {len(eligible_prices)} usable prices for product {product_id}"
            )

        # Build per-retailer lookup maps so stacking is a dict lookup, not
        # an inner loop over the full identity/card/portal lists.
        identity_by_retailer = _group_by_retailer(
            identity_resp.eligible_discounts, attr="retailer_id"
        )
        card_by_retailer: dict[str, CardRecommendation] = {
            c.retailer_id: c for c in cards_resp.recommendations
        }
        # Only stack portal cashback for portals the user has activated.
        # Without this gate, the hero promises savings via a portal the
        # user has no path to transit on Continue, and the rebate never
        # posts. The signup-referral upsell still surfaces independently
        # via portal_ctas (resolve_cta_list emits SIGNUP_REFERRAL/
        # GUIDED_ONLY rows for inactive memberships).
        active_memberships = {k for k, v in memberships.items() if v}
        portal_by_retailer: dict[str, list[PortalBonus]] = {}
        for row in portal_rows:
            if row.portal_source in active_memberships:
                portal_by_retailer.setdefault(row.retailer_id, []).append(row)

        # Stack each candidate.
        candidates: list[StackedPath] = []
        for price in eligible_prices:
            path = _stack_retailer_path(
                price_row=price,
                identity_matches=identity_by_retailer.get(price["retailer_id"], []),
                card_match=card_by_retailer.get(price["retailer_id"]),
                portal_matches=portal_by_retailer.get(price["retailer_id"], []),
            )
            candidates.append(path)

        # Sort winner + alternatives.
        candidates.sort(key=_rank_key)
        winner = candidates[0]
        alternatives = candidates[1:3]

        # Step 3g-B: actionable portal CTAs for the winner. Only the winner
        # carries CTAs to keep the response payload tight; secondary-row
        # taps fetch their own CTAs via POST /api/v1/portal/cta if needed.
        # Failure → empty list (silent — same contract as identity/cards).
        try:
            winner_ctas = await self.portal_service.resolve_cta_list(
                retailer_id=winner.retailer_id,
                user_memberships=memberships,
            )
            winner = winner.model_copy(update={"portal_ctas": winner_ctas})
        except Exception as exc:  # noqa: BLE001
            logger.warning("portal CTA fold-in failed (non-fatal): %s", exc)

        # Brand-direct callout (scans identity, not retailer prices).
        callout = _build_brand_direct_callout(identity_resp.eligible_discounts)

        has_stackable = (
            winner.identity_savings > 0.0
            or winner.card_savings > 0.0
            or winner.portal_savings > 0.0
        )

        rec = Recommendation(
            product_id=product_id,
            product_name=product.name,
            winner=winner,
            headline=_build_headline(winner),
            why=_build_why(winner),
            alternatives=alternatives,
            brand_direct_callout=callout,
            has_stackable_value=has_stackable,
            compute_ms=int((time.perf_counter() - started) * 1000),
            cached=False,
        )

        await self._write_cache(
            user_id, product_id, rec, user_card_hash, identity_hash, portal_hash
        )
        return rec

    # MARK: - Input gathering

    async def _gather_inputs(
        self, user_id: str, product_id: UUID
    ) -> tuple[
        Product,
        dict,
        object,  # IdentityDiscountsResponse
        object,  # CardRecommendationsResponse
        list[PortalBonus],
        set[str],
        set[str],
    ]:
        """Run all input lookups in one `asyncio.gather`.

        Loads product row first (serially) because `get_prices` needs it to
        exist and we want a clean 404 path. Everything else fans out.
        """
        product = await self.db.get(Product, product_id)
        if product is None:
            raise RecommendationProductNotFoundError(str(product_id))

        (
            prices_payload,
            identity_resp,
            cards_resp,
            portal_rows,
            active_retailer_ids,
            drift_flagged,
        ) = await asyncio.gather(
            self.price_service.get_prices(product_id),
            self.identity_service.get_eligible_discounts(user_id, product_id),
            self.card_service.get_best_cards_for_product(user_id, product_id),
            self._load_portal_bonuses(),
            self._load_active_retailer_ids(),
            self._load_drift_flagged_retailer_ids(),
        )
        return (
            product,
            prices_payload,
            identity_resp,
            cards_resp,
            portal_rows,
            active_retailer_ids,
            drift_flagged,
        )

    async def _load_portal_bonuses(self) -> list[PortalBonus]:
        """All currently effective portal bonuses."""
        stmt = select(PortalBonus)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def _load_active_retailer_ids(self) -> set[str]:
        stmt = select(Retailer.id).where(Retailer.is_active.is_(True))
        result = await self.db.execute(stmt)
        return set(result.scalars().all())

    async def _load_drift_flagged_retailer_ids(self) -> set[str]:
        """Retailers whose health monitor reports anything but 'ok'.

        The health table is sparsely populated — a retailer with no row
        is implicitly healthy (the normal steady state). We only exclude
        retailers that have an explicit non-ok status.
        """
        stmt = select(RetailerHealth.retailer_id).where(
            and_(RetailerHealth.status != "ok", RetailerHealth.status != "healthy")
        )
        result = await self.db.execute(stmt)
        return set(result.scalars().all())

    @staticmethod
    def _filter_prices(
        price_rows: list[dict],
        *,
        active_retailer_ids: set[str],
        drift_flagged: set[str],
    ) -> list[dict]:
        """Drop rows for inactive retailers or retailers in a drift state.

        Accepts the m2_prices wire payload shape (list[dict]). The payload
        only includes retailers that produced a usable listing (status =
        "success" on the classifier), so we don't need to filter by status
        here — inactivity + drift is the remaining gate.
        """
        out: list[dict] = []
        for row in price_rows:
            rid = row.get("retailer_id")
            if not rid:
                continue
            if active_retailer_ids and rid not in active_retailer_ids:
                continue
            if rid in drift_flagged:
                continue
            out.append(row)
        return out

    # MARK: - Cache

    @staticmethod
    def _cache_key(
        user_id: str,
        product_id: UUID,
        user_card_hash: str,
        identity_hash: str,
        portal_hash: str,
    ) -> str:
        """Cache key scoped to user + product + card portfolio + identity flags
        + portal-membership state.

        Version bumped to v5 in 3g-B to add the `:p<portal_hash>` segment.
        Without it, toggling "I'm a Rakuten member" in Profile leaves the
        recommendation cached with the SIGNUP_REFERRAL CTA for up to the
        15-min TTL — same class of bug as "adding a card doesn't bust stale
        recs" that 3f's `:c<card_hash>` solved.

        Earlier versions:
        * v2 — used global lowest price (incorrect).
        * v3 — Prime Student membership_fee was scoped as product savings.
        * v4 — fixed identity scoping; no portal-membership signal.
        v1–v4 keys are not read and expire on their 15-min TTL naturally.
        """
        return (
            f"{_CACHE_KEY_PREFIX}{user_id}:product:{product_id}"
            f":c{user_card_hash}:i{identity_hash}:p{portal_hash}:v5"
        )

    async def _user_card_hash(self, user_id: str) -> str:
        """Short SHA-1 over the user's active card IDs (sorted, comma-joined).

        Empty portfolio → hash of empty string. Any add/remove shifts the
        hash, busting the cache.
        """
        stmt = select(UserCard.id).where(
            and_(UserCard.user_id == user_id, UserCard.is_active.is_(True))
        )
        rows = await self.db.execute(stmt)
        ids = sorted(str(row) for row in rows.scalars().all())
        return _stable_hash(",".join(ids))[:8]

    async def _identity_flag_hash(self, user_id: str) -> str:
        """Short SHA-1 over the user's identity boolean flags.

        No profile row → hash of empty JSON. Flipping any flag shifts the
        hash, busting the cache.
        """
        profile = await self.db.get(UserDiscountProfile, user_id)
        if profile is None:
            return _stable_hash("{}")[:8]
        flags = {
            "mil": profile.is_military,
            "vet": profile.is_veteran,
            "stu": profile.is_student,
            "tea": profile.is_teacher,
            "fir": profile.is_first_responder,
            "nur": profile.is_nurse,
            "hea": profile.is_healthcare_worker,
            "sen": profile.is_senior,
            "gov": profile.is_government,
            "aaa": profile.is_aaa_member,
            "arp": profile.is_aarp_member,
            "cos": profile.is_costco_member,
            "pri": profile.is_prime_member,
            "sam": profile.is_sams_member,
            "idm": profile.id_me_verified,
            "shr": profile.sheer_id_verified,
        }
        return _stable_hash(json.dumps(flags, sort_keys=True))[:8]

    async def _read_cache(
        self,
        user_id: str,
        product_id: UUID,
        user_card_hash: str,
        identity_hash: str,
        portal_hash: str,
    ) -> Recommendation | None:
        try:
            raw = await self.redis.get(
                self._cache_key(
                    user_id, product_id, user_card_hash, identity_hash, portal_hash
                )
            )
            if raw is None:
                return None
            payload = json.loads(
                raw.decode() if isinstance(raw, bytes) else str(raw)
            )
            return Recommendation.model_validate(payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning("recommend cache read failed: %s", exc)
            return None

    async def _write_cache(
        self,
        user_id: str,
        product_id: UUID,
        rec: Recommendation,
        user_card_hash: str,
        identity_hash: str,
        portal_hash: str,
    ) -> None:
        try:
            await self.redis.setex(
                self._cache_key(
                    user_id, product_id, user_card_hash, identity_hash, portal_hash
                ),
                _CACHE_TTL_SECONDS,
                rec.model_dump_json(),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("recommend cache write failed: %s", exc)


# MARK: - Pure stacking helpers (module-level so they're easy to unit test)


def _stack_retailer_path(
    *,
    price_row: dict,
    identity_matches: list[EligibleDiscount],
    card_match: CardRecommendation | None,
    portal_matches: list[PortalBonus],
) -> StackedPath:
    """Compose one retailer row's full path. Pure function, no I/O."""
    base = float(price_row["price"])

    # Layer 1 — identity discount, if any.
    identity_savings = 0.0
    identity_source: str | None = None
    if identity_matches:
        best = max(
            identity_matches,
            key=lambda d: d.estimated_savings or 0.0,
        )
        if best.estimated_savings and best.estimated_savings > 0:
            identity_savings = float(best.estimated_savings)
            identity_source = best.program_name
    post_identity_price = max(0.0, base - identity_savings)

    # Layer 2 — card reward on POST-identity price.
    card_savings = 0.0
    card_source: str | None = None
    if card_match is not None and card_match.reward_rate:
        card_savings = post_identity_price * (float(card_match.reward_rate) / 100.0)
        card_source = card_match.card_display_name

    # Layer 3 — best available portal for this retailer.
    portal_savings = 0.0
    portal_source: str | None = None
    if portal_matches:
        best_portal = max(portal_matches, key=lambda p: _decimal_to_float(p.bonus_value))
        rate = _decimal_to_float(best_portal.bonus_value)
        portal_savings = post_identity_price * (rate / 100.0)
        portal_source = best_portal.portal_source

    total_savings = identity_savings + card_savings + portal_savings
    final_price = base - identity_savings  # card + portal are deferred rebates
    effective_cost = final_price - card_savings - portal_savings

    return StackedPath(
        retailer_id=price_row["retailer_id"],
        retailer_name=price_row.get("retailer_name", price_row["retailer_id"]),
        base_price=round(base, 2),
        final_price=round(final_price, 2),
        effective_cost=round(effective_cost, 2),
        total_savings=round(total_savings, 2),
        identity_savings=round(identity_savings, 2),
        identity_source=identity_source,
        card_savings=round(card_savings, 2),
        card_source=card_source,
        portal_savings=round(portal_savings, 2),
        portal_source=portal_source,
        condition=price_row.get("condition") or "new",
        product_url=price_row.get("url"),
    )


def _rank_key(path: StackedPath) -> tuple:
    """Sort key — lowest effective_cost wins, then condition, then retailer.

    The retailer tiebreaker only matters when effective_cost and condition
    already tie, which means "same net out-of-pocket at the same condition".
    In that case we prefer Amazon-class retailers over FB Marketplace
    because the demo story reads cleaner.
    """
    condition_rank = _CONDITION_RANK.get(path.condition, 99)
    try:
        retailer_rank = _WELL_KNOWN_RETAILER_ORDER.index(path.retailer_id)
    except ValueError:
        retailer_rank = len(_WELL_KNOWN_RETAILER_ORDER)
    return (path.effective_cost, condition_rank, retailer_rank, path.retailer_id)


def _build_headline(winner: StackedPath) -> str:
    """Short, template-driven, same cadence every time.

    "Best Buy" / "Samsung.com via Rakuten" / "Amazon with Chase Freedom Flex" /
    "Walmart via Rakuten with Chase Amazon Visa"
    """
    parts: list[str] = [winner.retailer_name]
    if winner.portal_source:
        parts.append(f"via {winner.portal_source.title()}")
    if winner.card_source:
        parts.append(f"with {winner.card_source}")
    if len(parts) == 1:
        return parts[0]
    # " + " separator reads as a stacking sentence; first part is the
    # anchor, subsequent parts are modifiers.
    return parts[0] + " " + " ".join(parts[1:])


def _build_why(winner: StackedPath) -> str:
    """One-line "why this wins" copy. Only includes layers with savings > 0."""
    layers: list[str] = []
    if winner.identity_savings > 0 and winner.identity_source:
        layers.append(
            f"{winner.identity_source} saves ${winner.identity_savings:.2f}"
        )
    if winner.portal_savings > 0 and winner.portal_source:
        layers.append(
            f"{winner.portal_source.title()} gives {winner.portal_savings:.2f} back"
        )
    if winner.card_savings > 0 and winner.card_source:
        layers.append(
            f"{winner.card_source} earns ${winner.card_savings:.2f} in rewards"
        )
    if not layers:
        return f"Lowest available price at {winner.retailer_name}."
    joined = " + ".join(layers)
    return (
        f"Stacking {joined} beats the naive cheapest listing by "
        f"${winner.total_savings:.2f}."
    )


def _build_brand_direct_callout(
    eligible: list[EligibleDiscount],
) -> BrandDirectCallout | None:
    """Scan eligible discounts for a high-value brand-direct program.

    Only programs at `*_direct` retailers with ≥15 % percentage discounts
    qualify. Returns the single highest-discount program when multiple are
    eligible (typical case: Samsung military + Samsung student, we pick
    the one with the bigger percentage).
    """
    best: EligibleDiscount | None = None
    for disc in eligible:
        if not disc.retailer_id.endswith("_direct"):
            continue
        if disc.discount_type != "percentage":
            continue
        if (disc.discount_value or 0.0) < _BRAND_DIRECT_MIN_DISCOUNT_PCT:
            continue
        if best is None or (disc.discount_value or 0.0) > (
            best.discount_value or 0.0
        ):
            best = disc
    if best is None:
        return None
    return BrandDirectCallout(
        retailer_id=best.retailer_id,
        retailer_name=best.retailer_name,
        program_name=best.program_name,
        discount_value=float(best.discount_value or 0.0),
        discount_type=best.discount_type,
        purchase_url_template=best.url,
    )


def _group_by_retailer(items, *, attr: str) -> dict[str, list]:
    """Small helper — group a list by a retailer_id attribute."""
    out: dict[str, list] = {}
    for item in items:
        rid = getattr(item, attr, None)
        if not rid:
            continue
        out.setdefault(rid, []).append(item)
    return out


def _decimal_to_float(value) -> float:
    """PortalBonus.bonus_value is `Numeric` → `Decimal`. Cast safely."""
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


# MARK: - Deterministic-cache hash helpers (exposed for tests)


def _stable_hash(value: str) -> str:
    """Short SHA-1 digest used for cache-suffix tests."""
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]


def _portal_membership_hash(memberships: dict[str, bool]) -> str:
    """8-char SHA-1 over the user's *active* portal memberships.

    Falsy entries are dropped before hashing so {"rakuten": False} hashes
    the same as {} — flipping a toggle off and back on shouldn't bust
    cache twice. Empty memberships hash to the same digest every call.
    """
    active = sorted(k for k, v in memberships.items() if v)
    return _stable_hash(",".join(active))[:8]
