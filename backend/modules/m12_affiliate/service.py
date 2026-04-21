"""M12 Affiliate service — URL tagging + click tracking + stats.

Zero-LLM, deterministic. URL construction lives in a pure static method
(`build_affiliate_url`) so tests can validate it without a DB fixture.
"""

import json
import logging
import urllib.parse

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from modules.m12_affiliate.schemas import (
    AffiliateClickRequest,
    AffiliateStatsResponse,
    AffiliateURLResponse,
)

logger = logging.getLogger("barkain.m12")


# Network identifiers stored in `affiliate_clicks.affiliate_network`. The
# column is NOT NULL in the schema, so untagged clicks fall back to the
# `PASSTHROUGH_NETWORK` sentinel rather than violating the constraint.
AMAZON_NETWORK = "amazon_associates"
EBAY_NETWORK = "ebay_partner"
WALMART_NETWORK = "walmart_impact"
PASSTHROUGH_NETWORK = "passthrough"

EBAY_RETAILERS: frozenset[str] = frozenset({"ebay_new", "ebay_used"})


class AffiliateService:
    """Tag retailer URLs + log clicks + compute per-user stats."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # MARK: - URL construction (pure static method)

    @staticmethod
    def build_affiliate_url(
        retailer_id: str, product_url: str
    ) -> AffiliateURLResponse:
        """Return a tagged URL + metadata for the given retailer.

        Deterministic and side-effect-free. Unknown retailers and retailers
        without a configured tag pass through with `is_affiliated=false`
        and `network=None`. Never raises.
        """
        if not product_url:
            return AffiliateURLResponse(
                affiliate_url="",
                is_affiliated=False,
                network=None,
                retailer_id=retailer_id,
            )

        # Amazon — append ?tag=<store> (or &tag= if query params already exist).
        if retailer_id == "amazon" and settings.AMAZON_ASSOCIATE_TAG:
            separator = "&" if "?" in product_url else "?"
            tagged = (
                f"{product_url}{separator}tag={settings.AMAZON_ASSOCIATE_TAG}"
            )
            return AffiliateURLResponse(
                affiliate_url=tagged,
                is_affiliated=True,
                network=AMAZON_NETWORK,
                retailer_id=retailer_id,
            )

        # eBay — modern EPN tracking via query params on the item URL itself.
        # The legacy `rover/1/<rotation>/1?mpre=` pattern returns a 1x1 GIF
        # impression pixel (content-type: image/gif), not a redirect — so
        # tapping it lands users on a blank page. The current EPN spec is
        # to append `mkcid=1&mkrid=<rotation>&campid=<id>&toolid=10001
        # &mkevt=1` directly to the item URL.
        if retailer_id in EBAY_RETAILERS and settings.EBAY_CAMPAIGN_ID:
            tracking = {
                "mkcid": "1",
                "mkrid": "711-53200-19255-0",  # US rotation id
                "siteid": "0",
                "campid": settings.EBAY_CAMPAIGN_ID,
                "toolid": "10001",
                "mkevt": "1",
            }
            separator = "&" if "?" in product_url else "?"
            tagged = product_url + separator + urllib.parse.urlencode(tracking)
            return AffiliateURLResponse(
                affiliate_url=tagged,
                is_affiliated=True,
                network=EBAY_NETWORK,
                retailer_id=retailer_id,
            )

        # Walmart — Impact Radius redirect, placeholder until approved.
        if retailer_id == "walmart" and settings.WALMART_AFFILIATE_ID:
            encoded = urllib.parse.quote(product_url, safe="")
            redirect = (
                f"https://goto.walmart.com/c/{settings.WALMART_AFFILIATE_ID}"
                f"/1/4/mp?u={encoded}"
            )
            return AffiliateURLResponse(
                affiliate_url=redirect,
                is_affiliated=True,
                network=WALMART_NETWORK,
                retailer_id=retailer_id,
            )

        # Passthrough — Best Buy (denied), any retailer with unset env vars.
        logger.debug(
            "Affiliate passthrough: retailer_id=%s (no configured tag)",
            retailer_id,
        )
        return AffiliateURLResponse(
            affiliate_url=product_url,
            is_affiliated=False,
            network=None,
            retailer_id=retailer_id,
        )

    # MARK: - Click logging

    async def log_click(
        self, user_id: str, request: AffiliateClickRequest
    ) -> AffiliateURLResponse:
        """Tag the URL, insert an `affiliate_clicks` row, return the tagged URL.

        Upserts the users row first for FK safety — matches the
        `m5_identity.get_or_create_profile` pattern so demo mode (where
        Clerk never wrote the user row) works end-to-end.
        """
        tagged = self.build_affiliate_url(request.retailer_id, request.product_url)

        # `affiliate_network` column is NOT NULL — use a sentinel for untagged.
        network_for_db = tagged.network or PASSTHROUGH_NETWORK

        await self.db.execute(
            text(
                "INSERT INTO users (id) VALUES (:id) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"id": user_id},
        )

        metadata_payload = json.dumps(
            {"activation_skipped": request.activation_skipped}
        )

        await self.db.execute(
            text(
                "INSERT INTO affiliate_clicks "
                "(user_id, product_id, retailer_id, affiliate_network, click_url, metadata) "
                "VALUES (:user_id, :product_id, :retailer_id, :network, :url, "
                "CAST(:metadata AS jsonb))"
            ),
            {
                "user_id": user_id,
                "product_id": request.product_id,
                "retailer_id": request.retailer_id,
                "network": network_for_db,
                "url": tagged.affiliate_url,
                "metadata": metadata_payload,
            },
        )
        await self.db.flush()

        logger.info(
            "Affiliate click logged: user=%s retailer=%s network=%s",
            user_id,
            request.retailer_id,
            network_for_db,
        )
        return tagged

    # MARK: - Stats

    async def get_user_stats(self, user_id: str) -> AffiliateStatsResponse:
        """Return click counts grouped by retailer for the current user."""
        rows = await self.db.execute(
            text(
                "SELECT retailer_id, COUNT(*) AS c "
                "FROM affiliate_clicks "
                "WHERE user_id = :user_id "
                "GROUP BY retailer_id"
            ),
            {"user_id": user_id},
        )
        by_retailer: dict[str, int] = {row[0]: int(row[1]) for row in rows}
        total = sum(by_retailer.values())
        return AffiliateStatsResponse(
            clicks_by_retailer=by_retailer, total_clicks=total
        )
