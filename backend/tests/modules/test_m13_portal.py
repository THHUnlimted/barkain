"""Tests for M13 Portal Monetization (Step 3g).

Service-level tests fixture-up portal_configs + portal_bonuses rows
directly. Endpoint tests use the existing `client` fixture from
conftest, which already wires Clerk auth + DB + Redis overrides.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.core_models import Retailer
from modules.m5_identity.models import PortalBonus
from modules.m13_portal.models import PortalConfig
from modules.m13_portal.schemas import PortalCTAMode
from modules.m13_portal.service import PortalMonetizationService


# MARK: - Fixtures


@pytest.fixture
def portal_approved(monkeypatch):
    """All portal referral creds populated. Demo flag on."""
    from app.config import settings

    monkeypatch.setattr(settings, "PORTAL_MONETIZATION_ENABLED", True)
    monkeypatch.setattr(settings, "RAKUTEN_REFERRAL_URL", "https://www.rakuten.com/r/TEST123")
    monkeypatch.setattr(settings, "BEFRUGAL_REFERRAL_URL", "https://www.befrugal.com/rs/TEST/")
    monkeypatch.setattr(settings, "TOPCASHBACK_FLEXOFFERS_PUB_ID", "TESTPUB")
    monkeypatch.setattr(
        settings,
        "TOPCASHBACK_FLEXOFFERS_LINK_TEMPLATE",
        "https://flexoffers.com/?pub={pub}&dest=topcashback",
    )


@pytest.fixture
def portal_pending(monkeypatch):
    """No referral creds populated. Demo flag on (so we exercise the
    no-referral-credential fallthrough, not the feature-flag short-circuit)."""
    from app.config import settings

    monkeypatch.setattr(settings, "PORTAL_MONETIZATION_ENABLED", True)
    monkeypatch.setattr(settings, "RAKUTEN_REFERRAL_URL", "")
    monkeypatch.setattr(settings, "BEFRUGAL_REFERRAL_URL", "")
    monkeypatch.setattr(settings, "TOPCASHBACK_FLEXOFFERS_PUB_ID", "")
    monkeypatch.setattr(settings, "TOPCASHBACK_FLEXOFFERS_LINK_TEMPLATE", "")


# MARK: - Setup helpers


async def _ensure_retailer(db_session, retailer_id: str) -> None:
    existing = await db_session.get(Retailer, retailer_id)
    if existing is not None:
        return
    db_session.add(
        Retailer(
            id=retailer_id,
            display_name=retailer_id.replace("_", " ").title(),
            base_url=f"https://www.{retailer_id}.com/",
            extraction_method="container",
            supports_coupons=False,
            supports_identity=False,
            is_active=True,
        )
    )
    await db_session.flush()


async def _seed_portal_config(
    db_session,
    portal_source: str,
    *,
    is_active: bool = True,
    signup_promo_amount: float | None = None,
    signup_promo_copy: str | None = None,
) -> PortalConfig:
    config = PortalConfig(
        portal_source=portal_source,
        display_name=portal_source.title(),
        homepage_url=f"https://www.{portal_source}.com/",
        signup_promo_amount=Decimal(str(signup_promo_amount)) if signup_promo_amount else None,
        signup_promo_copy=signup_promo_copy,
        is_active=is_active,
    )
    db_session.add(config)
    await db_session.flush()
    return config


async def _seed_portal_bonus(
    db_session,
    portal_source: str,
    retailer_id: str,
    rate: float,
    *,
    last_verified: datetime | None = None,
) -> PortalBonus:
    if last_verified is None:
        last_verified = datetime.now(UTC)
    bonus = PortalBonus(
        portal_source=portal_source,
        retailer_id=retailer_id,
        bonus_type="cashback",
        bonus_value=Decimal(str(rate)),
        effective_from=datetime.now(UTC),
        last_verified=last_verified,
    )
    db_session.add(bonus)
    await db_session.flush()
    return bonus


# MARK: - Service tests


@pytest.mark.asyncio
async def test_resolve_cta_member_returns_deeplink(db_session, portal_approved):
    await _ensure_retailer(db_session, "amazon")
    await _seed_portal_config(db_session, "rakuten")
    await _seed_portal_bonus(db_session, "rakuten", "amazon", 3.0)

    service = PortalMonetizationService(db_session)
    ctas = await service.resolve_cta_list(
        retailer_id="amazon",
        user_memberships={"rakuten": True},
    )
    assert len(ctas) == 1
    assert ctas[0].mode is PortalCTAMode.MEMBER_DEEPLINK
    assert "rakuten.com/amazon.com" in ctas[0].cta_url
    assert ctas[0].disclosure_required is False


@pytest.mark.asyncio
async def test_resolve_cta_nonmember_with_referral_returns_signup(
    db_session, portal_approved
):
    await _ensure_retailer(db_session, "amazon")
    await _seed_portal_config(
        db_session,
        "rakuten",
        signup_promo_amount=50.00,
        signup_promo_copy="Get $50 when you spend $30",
    )
    await _seed_portal_bonus(db_session, "rakuten", "amazon", 3.0)

    service = PortalMonetizationService(db_session)
    ctas = await service.resolve_cta_list(
        retailer_id="amazon",
        user_memberships={"rakuten": False},
    )
    assert len(ctas) == 1
    cta = ctas[0]
    assert cta.mode is PortalCTAMode.SIGNUP_REFERRAL
    assert cta.cta_url == "https://www.rakuten.com/r/TEST123"
    assert cta.disclosure_required is True
    assert cta.signup_promo_copy == "Get $50 when you spend $30"
    assert "$50 bonus" in cta.cta_label


@pytest.mark.asyncio
async def test_resolve_cta_nonmember_without_referral_returns_guided(
    db_session, portal_pending
):
    await _ensure_retailer(db_session, "amazon")
    await _seed_portal_config(db_session, "rakuten")
    await _seed_portal_bonus(db_session, "rakuten", "amazon", 3.0)

    service = PortalMonetizationService(db_session)
    ctas = await service.resolve_cta_list(retailer_id="amazon")
    assert len(ctas) == 1
    cta = ctas[0]
    assert cta.mode is PortalCTAMode.GUIDED_ONLY
    assert cta.cta_url == "https://www.rakuten.com/"
    assert cta.disclosure_required is False


@pytest.mark.asyncio
async def test_resolve_cta_stale_bonus_is_skipped(db_session, portal_approved):
    await _ensure_retailer(db_session, "amazon")
    await _seed_portal_config(db_session, "rakuten")
    await _seed_portal_bonus(
        db_session,
        "rakuten",
        "amazon",
        3.0,
        last_verified=datetime.now(UTC) - timedelta(hours=48),
    )

    service = PortalMonetizationService(db_session)
    ctas = await service.resolve_cta_list(
        retailer_id="amazon",
        user_memberships={"rakuten": True},
    )
    assert ctas == []


@pytest.mark.asyncio
async def test_feature_flag_off_forces_guided_only(db_session, monkeypatch):
    """Even for a member with a populated deeplink mapping, the flag-off
    path collapses to GUIDED_ONLY so demo / test never leak attribution."""
    from app.config import settings

    monkeypatch.setattr(settings, "PORTAL_MONETIZATION_ENABLED", False)
    monkeypatch.setattr(settings, "RAKUTEN_REFERRAL_URL", "https://www.rakuten.com/r/X")

    await _ensure_retailer(db_session, "amazon")
    await _seed_portal_config(db_session, "rakuten")
    await _seed_portal_bonus(db_session, "rakuten", "amazon", 3.0)

    service = PortalMonetizationService(db_session)
    ctas = await service.resolve_cta_list(
        retailer_id="amazon",
        user_memberships={"rakuten": True},
    )
    assert len(ctas) == 1
    assert ctas[0].mode is PortalCTAMode.GUIDED_ONLY


@pytest.mark.asyncio
async def test_member_fallthrough_to_signup_when_slug_missing(
    db_session, portal_approved
):
    """Retailer not in _RETAILER_TO_PORTAL_SLUG → fall through to
    SIGNUP_REFERRAL rather than dropping the row entirely."""
    await _ensure_retailer(db_session, "newegg")
    await _seed_portal_config(db_session, "rakuten")
    await _seed_portal_bonus(db_session, "rakuten", "newegg", 3.0)

    service = PortalMonetizationService(db_session)
    ctas = await service.resolve_cta_list(
        retailer_id="newegg",
        user_memberships={"rakuten": True},
    )
    assert len(ctas) == 1
    assert ctas[0].mode is PortalCTAMode.SIGNUP_REFERRAL


@pytest.mark.asyncio
async def test_inactive_portal_config_is_skipped(db_session, portal_approved):
    await _ensure_retailer(db_session, "amazon")
    await _seed_portal_config(db_session, "chase_shop", is_active=False)
    await _seed_portal_bonus(db_session, "chase_shop", "amazon", 3.0)

    service = PortalMonetizationService(db_session)
    ctas = await service.resolve_cta_list(retailer_id="amazon")
    assert ctas == []


@pytest.mark.asyncio
async def test_multiple_portals_sorted_by_rate_desc(db_session, portal_approved):
    await _ensure_retailer(db_session, "best_buy")
    await _seed_portal_config(db_session, "rakuten")
    await _seed_portal_config(db_session, "topcashback")
    await _seed_portal_config(db_session, "befrugal")
    await _seed_portal_bonus(db_session, "rakuten", "best_buy", 1.0)
    await _seed_portal_bonus(db_session, "topcashback", "best_buy", 4.0)
    await _seed_portal_bonus(db_session, "befrugal", "best_buy", 2.5)

    service = PortalMonetizationService(db_session)
    ctas = await service.resolve_cta_list(retailer_id="best_buy")
    assert [c.portal_source for c in ctas] == ["topcashback", "befrugal", "rakuten"]
    assert [c.bonus_rate_percent for c in ctas] == [4.0, 2.5, 1.0]


@pytest.mark.asyncio
async def test_topcashback_signup_requires_both_pub_and_template(
    db_session, monkeypatch
):
    from app.config import settings

    monkeypatch.setattr(settings, "PORTAL_MONETIZATION_ENABLED", True)
    monkeypatch.setattr(settings, "TOPCASHBACK_FLEXOFFERS_PUB_ID", "PUB")
    monkeypatch.setattr(settings, "TOPCASHBACK_FLEXOFFERS_LINK_TEMPLATE", "")

    await _ensure_retailer(db_session, "amazon")
    await _seed_portal_config(db_session, "topcashback")
    await _seed_portal_bonus(db_session, "topcashback", "amazon", 1.5)

    service = PortalMonetizationService(db_session)
    ctas = await service.resolve_cta_list(retailer_id="amazon")
    assert ctas[0].mode is PortalCTAMode.GUIDED_ONLY


# MARK: - Endpoint tests


@pytest.mark.asyncio
async def test_endpoint_returns_sorted_ctas(client, db_session, portal_approved):
    await _ensure_retailer(db_session, "amazon")
    await _seed_portal_config(db_session, "rakuten")
    await _seed_portal_config(db_session, "topcashback")
    await _seed_portal_bonus(db_session, "rakuten", "amazon", 2.0)
    await _seed_portal_bonus(db_session, "topcashback", "amazon", 3.5)
    await db_session.commit()

    resp = await client.post(
        "/api/v1/portal/cta",
        json={"retailer_id": "amazon", "user_memberships": {}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["retailer_id"] == "amazon"
    assert [cta["portal_source"] for cta in body["ctas"]] == ["topcashback", "rakuten"]


@pytest.mark.asyncio
async def test_endpoint_skips_portal_with_no_bonus(client, db_session, portal_approved):
    await _ensure_retailer(db_session, "amazon")
    await _seed_portal_config(db_session, "rakuten")
    await _seed_portal_config(db_session, "topcashback")  # no bonus row
    await _seed_portal_bonus(db_session, "rakuten", "amazon", 2.0)
    await db_session.commit()

    resp = await client.post(
        "/api/v1/portal/cta",
        json={"retailer_id": "amazon", "user_memberships": {}},
    )
    assert resp.status_code == 200
    sources = [cta["portal_source"] for cta in resp.json()["ctas"]]
    assert sources == ["rakuten"]
