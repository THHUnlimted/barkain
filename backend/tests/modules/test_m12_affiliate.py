"""Tests for M12 Affiliate — URL construction, click logging, stats, webhook.

14 tests:
- 9 pure URL construction (Amazon x3, eBay x2, Walmart x2, passthrough x2)
- 3 click/stats endpoint (click Amazon, click passthrough, stats group by)
- 2 conversion webhook (permissive, bearer required)
"""

from sqlalchemy import text

from app.config import settings
from modules.m12_affiliate.service import (
    AMAZON_NETWORK,
    EBAY_NETWORK,
    PASSTHROUGH_NETWORK,
    WALMART_NETWORK,
    AffiliateService,
)
from tests.conftest import MOCK_USER_ID


# MARK: - Helpers


async def _seed_retailer(db_session, retailer_id: str) -> None:
    """Insert a retailer row to satisfy the affiliate_clicks.retailer_id FK.

    Only the NOT NULL columns are populated — the rest use server defaults.
    """
    await db_session.execute(
        text(
            "INSERT INTO retailers "
            "(id, display_name, base_url, extraction_method) "
            "VALUES (:id, :name, :base, :method) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {
            "id": retailer_id,
            "name": retailer_id.replace("_", " ").title(),
            "base": f"https://www.{retailer_id}.com",
            "method": "container",
        },
    )
    await db_session.flush()


# MARK: - Pure URL construction (no DB)


def test_amazon_tag_appended_no_existing_params(monkeypatch):
    monkeypatch.setattr(settings, "AMAZON_ASSOCIATE_TAG", "barkain-20")

    result = AffiliateService.build_affiliate_url(
        "amazon", "https://www.amazon.com/dp/B0B2FCT81R"
    )

    assert result.is_affiliated is True
    assert result.network == AMAZON_NETWORK
    assert result.affiliate_url == (
        "https://www.amazon.com/dp/B0B2FCT81R?tag=barkain-20"
    )
    assert result.retailer_id == "amazon"


def test_amazon_tag_appended_with_existing_params(monkeypatch):
    monkeypatch.setattr(settings, "AMAZON_ASSOCIATE_TAG", "barkain-20")

    result = AffiliateService.build_affiliate_url(
        "amazon",
        "https://www.amazon.com/Sony-WH-1000XM5/dp/B0B2FCT81R?psc=1",
    )

    assert result.is_affiliated is True
    assert result.affiliate_url.endswith("&tag=barkain-20")
    assert "?psc=1" in result.affiliate_url
    # Make sure we didn't break the existing query string.
    assert result.affiliate_url.count("?") == 1


def test_amazon_untagged_when_env_empty(monkeypatch):
    monkeypatch.setattr(settings, "AMAZON_ASSOCIATE_TAG", "")

    result = AffiliateService.build_affiliate_url(
        "amazon", "https://www.amazon.com/dp/B0B2FCT81R"
    )

    assert result.is_affiliated is False
    assert result.network is None
    assert result.affiliate_url == "https://www.amazon.com/dp/B0B2FCT81R"


def test_ebay_new_appends_epn_query_params(monkeypatch):
    monkeypatch.setattr(settings, "EBAY_CAMPAIGN_ID", "5339148665")

    source_url = "https://www.ebay.com/itm/12345?var=99"
    result = AffiliateService.build_affiliate_url("ebay_new", source_url)

    assert result.is_affiliated is True
    assert result.network == EBAY_NETWORK
    # Modern EPN tagging — query params appended to the item URL itself.
    assert result.affiliate_url.startswith("https://www.ebay.com/itm/12345?var=99&")
    assert "mkcid=1" in result.affiliate_url
    assert "mkrid=711-53200-19255-0" in result.affiliate_url
    assert "campid=5339148665" in result.affiliate_url
    assert "toolid=10001" in result.affiliate_url
    assert "mkevt=1" in result.affiliate_url
    # Must NOT use the legacy rover impression-pixel pattern.
    assert "rover.ebay.com" not in result.affiliate_url


def test_ebay_used_uses_same_network(monkeypatch):
    monkeypatch.setattr(settings, "EBAY_CAMPAIGN_ID", "5339148665")

    result = AffiliateService.build_affiliate_url(
        "ebay_used", "https://www.ebay.com/itm/99999"
    )

    assert result.is_affiliated is True
    assert result.network == EBAY_NETWORK
    assert result.retailer_id == "ebay_used"
    assert "campid=5339148665" in result.affiliate_url


def test_walmart_tagged_when_env_set(monkeypatch):
    monkeypatch.setattr(settings, "WALMART_AFFILIATE_ID", "test-wmt-id")

    result = AffiliateService.build_affiliate_url(
        "walmart", "https://www.walmart.com/ip/12345"
    )

    assert result.is_affiliated is True
    assert result.network == WALMART_NETWORK
    assert result.affiliate_url.startswith(
        "https://goto.walmart.com/c/test-wmt-id/1/4/mp?u="
    )
    # Encoded product URL is present in the `u=` parameter.
    assert "u=https%3A%2F%2Fwww.walmart.com%2Fip%2F12345" in (
        result.affiliate_url
    )


def test_walmart_passthrough_when_env_empty(monkeypatch):
    monkeypatch.setattr(settings, "WALMART_AFFILIATE_ID", "")

    source = "https://www.walmart.com/ip/12345"
    result = AffiliateService.build_affiliate_url("walmart", source)

    assert result.is_affiliated is False
    assert result.network is None
    assert result.affiliate_url == source


def test_best_buy_passthrough():
    source = "https://www.bestbuy.com/site/product/12345.p"
    result = AffiliateService.build_affiliate_url("best_buy", source)

    assert result.is_affiliated is False
    assert result.network is None
    assert result.affiliate_url == source
    assert result.retailer_id == "best_buy"


def test_home_depot_passthrough():
    source = "https://www.homedepot.com/p/some-product/123"
    result = AffiliateService.build_affiliate_url("home_depot", source)

    assert result.is_affiliated is False
    assert result.network is None
    assert result.affiliate_url == source


# MARK: - Click endpoint


async def test_click_endpoint_logs_row_and_returns_tagged_url(
    client, db_session, monkeypatch
):
    monkeypatch.setattr(settings, "AMAZON_ASSOCIATE_TAG", "barkain-20")
    await _seed_retailer(db_session, "amazon")

    resp = await client.post(
        "/api/v1/affiliate/click",
        json={
            "product_id": None,
            "retailer_id": "amazon",
            "product_url": "https://www.amazon.com/dp/B0B2FCT81R",
        },
    )
    assert resp.status_code == 200

    body = resp.json()
    assert body["is_affiliated"] is True
    assert body["network"] == AMAZON_NETWORK
    assert body["affiliate_url"].endswith("?tag=barkain-20")
    assert body["retailer_id"] == "amazon"

    row = (
        await db_session.execute(
            text(
                "SELECT affiliate_network, retailer_id, click_url "
                "FROM affiliate_clicks "
                "WHERE user_id = :uid "
                "ORDER BY clicked_at DESC "
                "LIMIT 1"
            ),
            {"uid": MOCK_USER_ID},
        )
    ).first()
    assert row is not None
    assert row[0] == AMAZON_NETWORK
    assert row[1] == "amazon"
    assert "tag=barkain-20" in row[2]


async def test_click_endpoint_passthrough_logs_sentinel(
    client, db_session
):
    await _seed_retailer(db_session, "best_buy")

    resp = await client.post(
        "/api/v1/affiliate/click",
        json={
            "retailer_id": "best_buy",
            "product_url": "https://www.bestbuy.com/site/product/12345.p",
        },
    )
    assert resp.status_code == 200

    body = resp.json()
    assert body["is_affiliated"] is False
    assert body["network"] is None
    # Original URL comes through untagged.
    assert body["affiliate_url"] == (
        "https://www.bestbuy.com/site/product/12345.p"
    )

    row = (
        await db_session.execute(
            text(
                "SELECT affiliate_network "
                "FROM affiliate_clicks "
                "WHERE user_id = :uid AND retailer_id = 'best_buy'"
            ),
            {"uid": MOCK_USER_ID},
        )
    ).first()
    assert row is not None
    assert row[0] == PASSTHROUGH_NETWORK


# MARK: - Stats endpoint


async def test_stats_endpoint_groups_by_retailer(
    client, db_session, monkeypatch
):
    monkeypatch.setattr(settings, "AMAZON_ASSOCIATE_TAG", "barkain-20")
    await _seed_retailer(db_session, "amazon")
    await _seed_retailer(db_session, "best_buy")

    # 2 Amazon clicks + 1 Best Buy click for the mock user.
    for _ in range(2):
        resp = await client.post(
            "/api/v1/affiliate/click",
            json={
                "retailer_id": "amazon",
                "product_url": "https://www.amazon.com/dp/B0B2FCT81R",
            },
        )
        assert resp.status_code == 200

    resp = await client.post(
        "/api/v1/affiliate/click",
        json={
            "retailer_id": "best_buy",
            "product_url": "https://www.bestbuy.com/site/p/12345.p",
        },
    )
    assert resp.status_code == 200

    stats = await client.get("/api/v1/affiliate/stats")
    assert stats.status_code == 200

    body = stats.json()
    assert body["total_clicks"] == 3
    assert body["clicks_by_retailer"] == {"amazon": 2, "best_buy": 1}


# MARK: - Step 3f — activation_skipped metadata


async def test_click_endpoint_defaults_activation_skipped_false(
    client, db_session
):
    """Omitting activation_skipped persists `{activation_skipped: false}`."""
    await _seed_retailer(db_session, "best_buy")

    resp = await client.post(
        "/api/v1/affiliate/click",
        json={
            "retailer_id": "best_buy",
            "product_url": "https://www.bestbuy.com/site/product/123.p",
        },
    )
    assert resp.status_code == 200

    row = (
        await db_session.execute(
            text(
                "SELECT metadata FROM affiliate_clicks "
                "WHERE user_id = :uid ORDER BY clicked_at DESC LIMIT 1"
            ),
            {"uid": MOCK_USER_ID},
        )
    ).first()
    assert row is not None
    assert row[0] == {"activation_skipped": False}


async def test_click_endpoint_persists_activation_skipped_true(
    client, db_session
):
    """Interstitial's Continue-without-activating path persists skipped=true."""
    await _seed_retailer(db_session, "amazon")

    resp = await client.post(
        "/api/v1/affiliate/click",
        json={
            "retailer_id": "amazon",
            "product_url": "https://www.amazon.com/dp/B0B2FCT81R",
            "activation_skipped": True,
        },
    )
    assert resp.status_code == 200

    row = (
        await db_session.execute(
            text(
                "SELECT metadata FROM affiliate_clicks "
                "WHERE user_id = :uid ORDER BY clicked_at DESC LIMIT 1"
            ),
            {"uid": MOCK_USER_ID},
        )
    ).first()
    assert row is not None
    assert row[0] == {"activation_skipped": True}


async def test_click_endpoint_persists_portal_event_type_and_source(
    client, db_session
):
    """Step 3g-B — portal CTA taps flow `portal_event_type` + `portal_source`
    into `affiliate_clicks.metadata` so funnel analytics can split member
    deeplinks, signup conversions, and guided-only handoffs."""
    await _seed_retailer(db_session, "amazon")

    resp = await client.post(
        "/api/v1/affiliate/click",
        json={
            "retailer_id": "amazon",
            "product_url": "https://www.rakuten.com/amazon.com.htm",
            "portal_event_type": "member_deeplink",
            "portal_source": "rakuten",
        },
    )
    assert resp.status_code == 200

    row = (
        await db_session.execute(
            text(
                "SELECT metadata FROM affiliate_clicks "
                "WHERE user_id = :uid ORDER BY clicked_at DESC LIMIT 1"
            ),
            {"uid": MOCK_USER_ID},
        )
    ).first()
    assert row is not None
    metadata = row[0]
    assert metadata["activation_skipped"] is False
    assert metadata["portal_event_type"] == "member_deeplink"
    assert metadata["portal_source"] == "rakuten"


async def test_click_endpoint_rejects_unknown_portal_event_type(
    client, db_session
):
    """Step 3g-B — bad `portal_event_type` returns 422 instead of silently
    polluting analytics with junk values. iOS string enum mirrors the
    backend `_VALID_PORTAL_EVENT_TYPES` set."""
    await _seed_retailer(db_session, "amazon")

    resp = await client.post(
        "/api/v1/affiliate/click",
        json={
            "retailer_id": "amazon",
            "product_url": "https://www.amazon.com/dp/X",
            "portal_event_type": "definitely_not_a_real_mode",
            "portal_source": "rakuten",
        },
    )
    assert resp.status_code == 422
    assert (
        resp.json()["detail"]["error"]["code"]
        == "AFFILIATE_INVALID_PORTAL_EVENT_TYPE"
    )


async def test_stats_endpoint_unchanged_by_metadata_field(
    client, db_session
):
    """Existing /stats shape doesn't regress when metadata rows exist."""
    await _seed_retailer(db_session, "amazon")
    # Log one click with activation_skipped=true, one with it omitted.
    for body in (
        {
            "retailer_id": "amazon",
            "product_url": "https://www.amazon.com/dp/A1",
            "activation_skipped": True,
        },
        {"retailer_id": "amazon", "product_url": "https://www.amazon.com/dp/A2"},
    ):
        await client.post("/api/v1/affiliate/click", json=body)

    resp = await client.get("/api/v1/affiliate/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_clicks"] == 2
    assert body["clicks_by_retailer"] == {"amazon": 2}


# MARK: - Conversion webhook (placeholder)


async def test_conversion_webhook_permissive_without_secret(
    client, monkeypatch
):
    monkeypatch.setattr(settings, "AFFILIATE_WEBHOOK_SECRET", "")

    resp = await client.post(
        "/api/v1/affiliate/conversion",
        json={"event": "test", "order_id": "abc-123"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "action": "acknowledged"}


async def test_conversion_webhook_bearer_required_when_secret_set(
    client, monkeypatch
):
    monkeypatch.setattr(
        settings, "AFFILIATE_WEBHOOK_SECRET", "test_secret_value"
    )

    # Missing header → 401
    resp = await client.post(
        "/api/v1/affiliate/conversion",
        json={"event": "test"},
    )
    assert resp.status_code == 401
    assert (
        resp.json()["detail"]["error"]["code"]
        == "AFFILIATE_WEBHOOK_AUTH_FAILED"
    )

    # Wrong token → 401
    resp = await client.post(
        "/api/v1/affiliate/conversion",
        json={"event": "test"},
        headers={"Authorization": "Bearer wrong"},
    )
    assert resp.status_code == 401

    # Correct token → 200
    resp = await client.post(
        "/api/v1/affiliate/conversion",
        json={"event": "test", "commission_cents": 1234},
        headers={"Authorization": "Bearer test_secret_value"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "action": "acknowledged"}
