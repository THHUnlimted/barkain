"""M13 PortalMonetizationService — resolve per-retailer portal CTAs (Step 3g).

Pure SQL + Python decision tree, no LLM, no external calls. Operates on:

  * ``portal_configs`` (display name + homepage + signup promo)  — m13
  * ``portal_bonuses`` (per-portal-per-retailer cashback rate)   — m5_identity
  * Settings (referral URLs + feature flag)                       — env

The decision tree per portal:
    1. PORTAL_MONETIZATION_ENABLED=False → GUIDED_ONLY (homepage URL).
       Demo / test environments never fire signup attribution.
    2. last_verified is None or older than 24h → skip this portal entirely.
       Stale rates are worse than no rates — users compare against the
       displayed number and complain when checkout doesn't match.
    3. user is a member → MEMBER_DEEPLINK. URL routes through the portal's
       store page so the portal registers the click before sending the
       user on to the retailer. Falls through to SIGNUP_REFERRAL (or
       GUIDED_ONLY) when no slug mapping exists for this (portal, retailer)
       pair — degrade cleanly, don't drop the row.
    4. user is not a member + referral credential populated →
       SIGNUP_REFERRAL with disclosure_required=True (FTC compliance) and
       the current promo copy from portal_configs.
    5. otherwise → GUIDED_ONLY (homepage URL).

Picking the top CTA when multiple portals offer rates for the same
retailer: sort by (bonus_rate_percent DESC, portal_source ASC) for a
deterministic tiebreak, log skipped/rejected candidates at DEBUG so a
future operator can see *why* one was preferred without instrumenting the
code path. Lesson carried from PR #52's extractor postfix — first-match-
wins is a latent ordering bug.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from modules.m5_identity.models import PortalBonus
from modules.m13_portal.models import PortalConfig
from modules.m13_portal.schemas import PortalCTA, PortalCTAMode

logger = logging.getLogger("barkain.m13")


# MARK: - Tunables

# A portal_bonuses row older than this is treated as missing. Cron cadence
# is 6h; 24h = up to 3 missed runs before the pill vanishes for that portal.
_STALENESS_THRESHOLD = timedelta(hours=24)

# Cap on how many CTAs we hand back for a single retailer. Three is the
# max the interstitial mock shows; more clutters the sheet.
_MAX_CTAS_PER_RETAILER = 3


# MARK: - Retailer → portal-slug mapping
#
# Hand-maintained dict per (portal, retailer) pair. Add new pairs as we
# verify the portal hosts a per-retailer page. Missing pairs degrade
# gracefully — the resolver falls through to SIGNUP_REFERRAL/GUIDED_ONLY
# instead of dropping the row.
#
# Slugs verified against live portal pages 2026-04-22. If a portal renames
# a retailer page, log shows up at DEBUG via _log_rejected_candidates and
# the fix is a one-line dict update.

_RETAILER_TO_PORTAL_SLUG: dict[str, dict[str, str]] = {
    "rakuten": {
        "amazon": "amazon.com",
        "best_buy": "bestbuy.com",
        "walmart": "walmart.com",
        "target": "target.com",
        "home_depot": "homedepot.com",
        "ebay_new": "ebay.com",
        "ebay_used": "ebay.com",
        "backmarket": "backmarket.com",
        "samsung_direct": "samsung.com",
        "apple_direct": "apple.com",
    },
    "topcashback": {
        "amazon": "amazon-com",
        "best_buy": "best-buy",
        "walmart": "walmart-com",
        "target": "target-com",
        "home_depot": "the-home-depot",
        "ebay_new": "ebay-com",
        "ebay_used": "ebay-com",
        "backmarket": "back-market-us",
        "samsung_direct": "samsung-com",
        "apple_direct": "apple-com",
    },
    "befrugal": {
        "amazon": "Amazon",
        "best_buy": "BestBuy",
        "walmart": "Walmart",
        "target": "Target",
        "home_depot": "Home-Depot",
        "ebay_new": "eBay",
        "ebay_used": "eBay",
        "backmarket": "Back-Market",
        "samsung_direct": "Samsung",
        "apple_direct": "Apple",
    },
}


def _build_member_deeplink(portal_source: str, retailer_id: str) -> str | None:
    """Return the portal's per-retailer store URL, or None if unmapped."""
    portal_slugs = _RETAILER_TO_PORTAL_SLUG.get(portal_source, {})
    slug = portal_slugs.get(retailer_id)
    if slug is None:
        return None
    if portal_source == "rakuten":
        return f"https://www.rakuten.com/{slug}.htm"
    if portal_source == "topcashback":
        return f"https://www.topcashback.com/{slug}/"
    if portal_source == "befrugal":
        return f"https://www.befrugal.com/store/{slug}/"
    return None


# MARK: - Service


class PortalMonetizationService:
    """Resolve the best portal CTAs for a given retailer."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def resolve_cta_list(
        self,
        retailer_id: str,
        *,
        user_memberships: dict[str, bool] | None = None,
    ) -> list[PortalCTA]:
        """Build the per-retailer CTA list (sorted, deduped, capped).

        Returns up to ``_MAX_CTAS_PER_RETAILER`` entries. Empty list when
        no active portals have a current bonus for this retailer.
        """
        memberships = user_memberships or {}

        configs = await self._load_active_configs()
        if not configs:
            return []

        bonuses_by_portal = await self._load_bonuses_for_retailer(
            retailer_id, [c.portal_source for c in configs]
        )

        ctas: list[PortalCTA] = []
        rejected: list[tuple[str, str]] = []  # (portal, reason)

        for config in configs:
            bonus = bonuses_by_portal.get(config.portal_source)
            if bonus is None:
                rejected.append((config.portal_source, "no_bonus_row"))
                continue
            if not _is_fresh(bonus.last_verified):
                rejected.append((config.portal_source, "stale_bonus"))
                continue

            cta = self._build_cta(
                config=config,
                bonus=bonus,
                retailer_id=retailer_id,
                is_member=memberships.get(config.portal_source, False),
            )
            ctas.append(cta)

        if rejected:
            _log_rejected_candidates(retailer_id, rejected)

        ctas.sort(
            key=lambda c: (-c.bonus_rate_percent, c.portal_source),
        )
        return ctas[:_MAX_CTAS_PER_RETAILER]

    # MARK: - Loaders

    async def _load_active_configs(self) -> list[PortalConfig]:
        stmt = select(PortalConfig).where(PortalConfig.is_active.is_(True))
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def _load_bonuses_for_retailer(
        self,
        retailer_id: str,
        portal_sources: list[str],
    ) -> dict[str, PortalBonus]:
        """Load PortalBonus rows keyed by portal_source for one retailer.

        ``portal_bonuses`` has a unique constraint on (portal_source,
        retailer_id) so at most one row per portal — no need to dedupe.
        """
        if not portal_sources:
            return {}
        stmt = select(PortalBonus).where(
            PortalBonus.retailer_id == retailer_id,
            PortalBonus.portal_source.in_(portal_sources),
        )
        result = await self.db.execute(stmt)
        return {row.portal_source: row for row in result.scalars().all()}

    # MARK: - Decision tree

    def _build_cta(
        self,
        *,
        config: PortalConfig,
        bonus: PortalBonus,
        retailer_id: str,
        is_member: bool,
    ) -> PortalCTA:
        """Apply the 5-step decision tree to one (config, bonus) pair."""
        rate = float(bonus.bonus_value)
        elevated = bool(bonus.is_elevated)
        last_verified = bonus.last_verified

        # Feature-flag short-circuit (rule 1).
        if not settings.PORTAL_MONETIZATION_ENABLED:
            return PortalCTA(
                portal_source=config.portal_source,
                display_name=config.display_name,
                mode=PortalCTAMode.GUIDED_ONLY,
                bonus_rate_percent=rate,
                bonus_is_elevated=elevated,
                cta_url=config.homepage_url,
                cta_label=_label_guided(config.display_name, rate),
                last_verified=last_verified,
            )

        # Member path (rule 3) with graceful fallthrough.
        if is_member:
            deeplink = _build_member_deeplink(config.portal_source, retailer_id)
            if deeplink is not None:
                return PortalCTA(
                    portal_source=config.portal_source,
                    display_name=config.display_name,
                    mode=PortalCTAMode.MEMBER_DEEPLINK,
                    bonus_rate_percent=rate,
                    bonus_is_elevated=elevated,
                    cta_url=deeplink,
                    cta_label=_label_deeplink(config.display_name, rate),
                    last_verified=last_verified,
                )
            logger.debug(
                "m13: member fallthrough — no slug for (%s, %s)",
                config.portal_source,
                retailer_id,
            )

        # Signup-referral path (rule 4).
        referral_url = _referral_url_for(config.portal_source)
        if referral_url:
            return PortalCTA(
                portal_source=config.portal_source,
                display_name=config.display_name,
                mode=PortalCTAMode.SIGNUP_REFERRAL,
                bonus_rate_percent=rate,
                bonus_is_elevated=elevated,
                cta_url=referral_url,
                cta_label=_label_signup(config.display_name, config.signup_promo_amount),
                signup_promo_copy=config.signup_promo_copy,
                last_verified=last_verified,
                disclosure_required=True,
            )

        # Guided-only fallback (rule 5).
        return PortalCTA(
            portal_source=config.portal_source,
            display_name=config.display_name,
            mode=PortalCTAMode.GUIDED_ONLY,
            bonus_rate_percent=rate,
            bonus_is_elevated=elevated,
            cta_url=config.homepage_url,
            cta_label=_label_guided(config.display_name, rate),
            last_verified=last_verified,
        )


# MARK: - Helpers


def _is_fresh(last_verified: datetime | None) -> bool:
    """True if the bonus row was verified within the staleness window.

    A row with last_verified=None is treated as stale; the worker writes
    a timestamp on every successful upsert, so missing means "never
    verified" rather than "fresh by default".
    """
    if last_verified is None:
        return False
    if last_verified.tzinfo is None:
        last_verified = last_verified.replace(tzinfo=UTC)
    return datetime.now(UTC) - last_verified <= _STALENESS_THRESHOLD


def _referral_url_for(portal_source: str) -> str:
    """Return the populated referral URL for a portal, or empty string.

    TopCashback's referral path is templated through FlexOffers; we only
    return a usable URL when both the pub ID and the link template are
    set, so a half-configured environment falls through to GUIDED_ONLY
    instead of producing a broken link.
    """
    if portal_source == "rakuten":
        return settings.RAKUTEN_REFERRAL_URL or ""
    if portal_source == "befrugal":
        return settings.BEFRUGAL_REFERRAL_URL or ""
    if portal_source == "topcashback":
        pub = settings.TOPCASHBACK_FLEXOFFERS_PUB_ID
        template = settings.TOPCASHBACK_FLEXOFFERS_LINK_TEMPLATE
        if pub and template:
            # Caller-side substitution — avoids constructing a malformed URL
            # when the template doesn't include {pub}.
            return template.replace("{pub}", pub)
        return ""
    return ""


def _label_deeplink(display_name: str, rate: float) -> str:
    return f"Open {display_name} for {_format_rate(rate)} back"


def _label_signup(display_name: str, promo_amount) -> str:
    if promo_amount is not None and float(promo_amount) > 0:
        return f"Sign up for {display_name} — ${int(float(promo_amount))} bonus"
    return f"Sign up for {display_name}"


def _label_guided(display_name: str, rate: float) -> str:
    return f"Open {display_name} first for {_format_rate(rate)} back"


def _format_rate(rate: float) -> str:
    if rate == int(rate):
        return f"{int(rate)}%"
    return f"{rate:.1f}%"


def _log_rejected_candidates(
    retailer_id: str, rejected: list[tuple[str, str]]
) -> None:
    """DEBUG-level log of why each portal was skipped for one retailer.

    Cheap visibility — when a future operator sees an unexpected pill
    selection, the log shows which other portals were considered and
    why each was skipped. Lesson from PR #52 (the extractor postfix
    that grew out of opaque first-match-wins ordering).
    """
    if not logger.isEnabledFor(logging.DEBUG):
        return
    for portal, reason in rejected:
        logger.debug(
            "m13: skipped portal=%s for retailer=%s reason=%s",
            portal,
            retailer_id,
            reason,
        )
