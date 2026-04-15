"""Tests for M11 Billing — webhook + status endpoint + tier-aware rate limiter.

14 tests:
- 8 webhook tests (5 state-changing event types + auth + unknown + dedup)
- 3 status tests (free, pro, expired-pro)
- 2 rate-limit tests (free base, pro 2x multiplier)
- 1 migration 0004 index existence check
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.config import settings
from tests.conftest import MOCK_USER_ID


# MARK: - Helpers


async def _seed_user(db_session, user_id: str = MOCK_USER_ID, **fields) -> None:
    """Insert or update a users row with arbitrary columns.

    `fields` may include `subscription_tier`, `subscription_expires_at`, etc.
    Values passed as None pass through as SQL NULL.
    """
    base = {"id": user_id, **fields}
    columns = ", ".join(base.keys())
    placeholders = ", ".join(f":{k}" for k in base.keys())
    updates = ", ".join(
        f"{k} = EXCLUDED.{k}" for k in base.keys() if k != "id"
    )
    sql = f"INSERT INTO users ({columns}) VALUES ({placeholders})"
    if updates:
        sql += f" ON CONFLICT (id) DO UPDATE SET {updates}"
    else:
        sql += " ON CONFLICT (id) DO NOTHING"
    await db_session.execute(text(sql), base)
    await db_session.flush()


def _build_event(
    event_type: str,
    event_id: str = "evt_test_1",
    app_user_id: str = MOCK_USER_ID,
    expiration_at_ms: int | None = None,
) -> dict:
    """Build a minimal RevenueCat webhook payload."""
    event: dict = {
        "type": event_type,
        "id": event_id,
        "app_user_id": app_user_id,
    }
    if expiration_at_ms is not None:
        event["expiration_at_ms"] = expiration_at_ms
    return {"event": event, "api_version": "1.0"}


def _webhook_headers(secret: str | None = None) -> dict:
    """Return Authorization header matching REVENUECAT_WEBHOOK_SECRET."""
    token = secret if secret is not None else settings.REVENUECAT_WEBHOOK_SECRET
    return {"Authorization": f"Bearer {token}"}


def _future_ms(days: int = 30) -> int:
    return int((datetime.now(UTC) + timedelta(days=days)).timestamp() * 1000)


def _past_ms(days: int = 1) -> int:
    return int((datetime.now(UTC) - timedelta(days=days)).timestamp() * 1000)


# MARK: - Webhook tests


async def test_webhook_initial_purchase_sets_pro(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "REVENUECAT_WEBHOOK_SECRET", "test_secret")

    expiration_ms = _future_ms(30)
    payload = _build_event(
        "INITIAL_PURCHASE",
        event_id="evt_initial_1",
        expiration_at_ms=expiration_ms,
    )
    resp = await client.post(
        "/api/v1/billing/webhook",
        json=payload,
        headers=_webhook_headers("test_secret"),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["action"] == "processed"
    assert data["tier"] == "pro"

    row = (
        await db_session.execute(
            text(
                "SELECT subscription_tier, subscription_expires_at "
                "FROM users WHERE id = :id"
            ),
            {"id": MOCK_USER_ID},
        )
    ).first()
    assert row is not None
    assert row[0] == "pro"
    assert row[1] is not None


async def test_webhook_renewal_sets_new_expiration(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "REVENUECAT_WEBHOOK_SECRET", "test_secret")

    # Seed with an expiration 5 days from now.
    old_expiration = datetime.now(UTC) + timedelta(days=5)
    await _seed_user(
        db_session,
        subscription_tier="pro",
        subscription_expires_at=old_expiration,
    )

    # Renewal event with expiration 35 days from now.
    new_expiration_ms = _future_ms(35)
    resp = await client.post(
        "/api/v1/billing/webhook",
        json=_build_event(
            "RENEWAL",
            event_id="evt_renewal_1",
            expiration_at_ms=new_expiration_ms,
        ),
        headers=_webhook_headers("test_secret"),
    )
    assert resp.status_code == 200

    row = (
        await db_session.execute(
            text(
                "SELECT subscription_tier, subscription_expires_at FROM users WHERE id = :id"
            ),
            {"id": MOCK_USER_ID},
        )
    ).first()
    assert row[0] == "pro"
    # Expiration is SET from the event (not += delta) — should be within a
    # second of new_expiration_ms.
    actual = row[1].replace(tzinfo=UTC) if row[1].tzinfo is None else row[1]
    expected = datetime.fromtimestamp(new_expiration_ms / 1000, tz=UTC)
    assert abs((actual - expected).total_seconds()) < 2


async def test_webhook_non_renewing_lifetime(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "REVENUECAT_WEBHOOK_SECRET", "test_secret")

    resp = await client.post(
        "/api/v1/billing/webhook",
        json=_build_event(
            "NON_RENEWING_PURCHASE",
            event_id="evt_lifetime_1",
        ),
        headers=_webhook_headers("test_secret"),
    )
    assert resp.status_code == 200

    row = (
        await db_session.execute(
            text(
                "SELECT subscription_tier, subscription_expires_at FROM users WHERE id = :id"
            ),
            {"id": MOCK_USER_ID},
        )
    ).first()
    assert row[0] == "pro"
    assert row[1] is None  # lifetime → never expires


async def test_webhook_cancellation_keeps_pro_until_expiration(
    client, db_session, monkeypatch
):
    monkeypatch.setattr(settings, "REVENUECAT_WEBHOOK_SECRET", "test_secret")

    # User is currently pro with 10 days left.
    await _seed_user(
        db_session,
        subscription_tier="pro",
        subscription_expires_at=datetime.now(UTC) + timedelta(days=10),
    )

    # CANCELLATION event carries expiration_at_ms; they keep pro until then.
    future_ms = _future_ms(10)
    resp = await client.post(
        "/api/v1/billing/webhook",
        json=_build_event(
            "CANCELLATION",
            event_id="evt_cancel_1",
            expiration_at_ms=future_ms,
        ),
        headers=_webhook_headers("test_secret"),
    )
    assert resp.status_code == 200

    row = (
        await db_session.execute(
            text(
                "SELECT subscription_tier, subscription_expires_at FROM users WHERE id = :id"
            ),
            {"id": MOCK_USER_ID},
        )
    ).first()
    assert row[0] == "pro"
    assert row[1] is not None


async def test_webhook_expiration_downgrades_to_free(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "REVENUECAT_WEBHOOK_SECRET", "test_secret")

    await _seed_user(
        db_session,
        subscription_tier="pro",
        subscription_expires_at=datetime.now(UTC) + timedelta(days=1),
    )

    resp = await client.post(
        "/api/v1/billing/webhook",
        json=_build_event("EXPIRATION", event_id="evt_expire_1"),
        headers=_webhook_headers("test_secret"),
    )
    assert resp.status_code == 200

    row = (
        await db_session.execute(
            text(
                "SELECT subscription_tier, subscription_expires_at FROM users WHERE id = :id"
            ),
            {"id": MOCK_USER_ID},
        )
    ).first()
    assert row[0] == "free"
    assert row[1] is None


async def test_webhook_invalid_auth_returns_401(client, monkeypatch):
    monkeypatch.setattr(settings, "REVENUECAT_WEBHOOK_SECRET", "test_secret")

    resp = await client.post(
        "/api/v1/billing/webhook",
        json=_build_event("INITIAL_PURCHASE", event_id="evt_unauth"),
        headers={"Authorization": "Bearer wrong_secret"},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"]["error"]["code"] == "WEBHOOK_AUTH_FAILED"


async def test_webhook_unknown_event_acknowledged(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "REVENUECAT_WEBHOOK_SECRET", "test_secret")

    resp = await client.post(
        "/api/v1/billing/webhook",
        json=_build_event("SUBSCRIBER_ALIAS", event_id="evt_alias"),
        headers=_webhook_headers("test_secret"),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "acknowledged"
    # No user row should have been created for a non-state event.
    row = (
        await db_session.execute(
            text("SELECT 1 FROM users WHERE id = :id"),
            {"id": MOCK_USER_ID},
        )
    ).first()
    assert row is None


async def test_webhook_idempotency_same_event_id(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "REVENUECAT_WEBHOOK_SECRET", "test_secret")

    expiration_ms = _future_ms(30)
    payload = _build_event(
        "INITIAL_PURCHASE",
        event_id="evt_dedup_1",
        expiration_at_ms=expiration_ms,
    )

    resp1 = await client.post(
        "/api/v1/billing/webhook",
        json=payload,
        headers=_webhook_headers("test_secret"),
    )
    assert resp1.status_code == 200
    assert resp1.json()["action"] == "processed"

    resp2 = await client.post(
        "/api/v1/billing/webhook",
        json=payload,
        headers=_webhook_headers("test_secret"),
    )
    assert resp2.status_code == 200
    assert resp2.json()["action"] == "duplicate"


# MARK: - Status tests


async def test_status_free_user(client):
    resp = await client.get("/api/v1/billing/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tier"] == "free"
    assert data["is_active"] is False
    assert data["expires_at"] is None


async def test_status_pro_user_with_expiration(client, db_session):
    await _seed_user(
        db_session,
        subscription_tier="pro",
        subscription_expires_at=datetime.now(UTC) + timedelta(days=30),
    )

    resp = await client.get("/api/v1/billing/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tier"] == "pro"
    assert data["is_active"] is True
    assert data["expires_at"] is not None
    assert data["entitlement_id"] == "Barkain Pro"


async def test_status_expired_pro_downgrades_in_response(client, db_session):
    # Row still says pro but expiration is in the past — the read path
    # reports free without mutating the row (webhook will clean up later).
    await _seed_user(
        db_session,
        subscription_tier="pro",
        subscription_expires_at=datetime.now(UTC) - timedelta(days=1),
    )

    resp = await client.get("/api/v1/billing/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tier"] == "free"
    assert data["is_active"] is False

    # DB row unchanged — the endpoint is read-only.
    row = (
        await db_session.execute(
            text("SELECT subscription_tier FROM users WHERE id = :id"),
            {"id": MOCK_USER_ID},
        )
    ).first()
    assert row[0] == "pro"


# MARK: - Rate limiter tests


async def test_rate_limiter_free_user_uses_base_limit(client, monkeypatch):
    """Free users hit RATE_LIMIT_GENERAL, not the doubled pro cap.

    Rapid-fire requests against the existing test endpoint, temporarily lowered
    to 3/min. Without a users row, MOCK_USER_ID resolves to free.
    """
    monkeypatch.setattr(settings, "RATE_LIMIT_GENERAL", 3)
    monkeypatch.setattr(settings, "RATE_LIMIT_PRO_MULTIPLIER", 2)

    # 3 requests succeed (at the limit).
    for _ in range(3):
        r = await client.get("/api/v1/test-rate-limit")
        assert r.status_code == 200

    # 4th request over the free limit → 429.
    r = await client.get("/api/v1/test-rate-limit")
    assert r.status_code == 429


async def test_rate_limiter_pro_user_doubled(
    client, db_session, fake_redis, monkeypatch
):
    """Pro users get 2x the free-tier base limit.

    Seeds MOCK_USER_ID as pro, then does 6 requests against a 3/min cap.
    Tier cache is pre-primed via fake_redis to avoid the in-test DB round trip
    depending on DB fixture ordering. (The service would also resolve via DB
    since we seeded, but priming is explicit about what we're testing.)
    """
    monkeypatch.setattr(settings, "RATE_LIMIT_GENERAL", 3)
    monkeypatch.setattr(settings, "RATE_LIMIT_PRO_MULTIPLIER", 2)

    await _seed_user(
        db_session,
        subscription_tier="pro",
        subscription_expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    await fake_redis.setex(f"tier:{MOCK_USER_ID}", 60, "pro")

    # Effective limit for pro = 3 * 2 = 6.
    for i in range(6):
        r = await client.get("/api/v1/test-rate-limit")
        assert r.status_code == 200, f"request {i} rejected"

    # 7th request over the doubled limit → 429.
    r = await client.get("/api/v1/test-rate-limit")
    assert r.status_code == 429


# MARK: - Migration


async def test_migration_0004_index_exists(db_session):
    """Verify idx_card_reward_programs_product was created with UNIQUE."""
    row = (
        await db_session.execute(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE indexname = 'idx_card_reward_programs_product'"
            )
        )
    ).first()
    assert row is not None, "idx_card_reward_programs_product not found"
    indexdef = row[0]
    assert "UNIQUE" in indexdef
    assert "card_issuer" in indexdef
    assert "card_product" in indexdef


async def test_migration_0006_subscription_tier_constraint(db_session):
    """Verify chk_subscription_tier exists and rejects bogus values."""
    import pytest
    from sqlalchemy.exc import IntegrityError

    row = (
        await db_session.execute(
            text(
                "SELECT conname FROM pg_constraint "
                "WHERE conname = 'chk_subscription_tier'"
            )
        )
    ).first()
    assert row is not None, "chk_subscription_tier constraint not found"

    # Reject a value outside {'free', 'pro'}. Use a SAVEPOINT so the
    # IntegrityError doesn't poison the outer fixture transaction.
    await _seed_user(db_session, subscription_tier="free")
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                text(
                    "UPDATE users SET subscription_tier = 'enterprise' "
                    "WHERE id = :user_id"
                ),
                {"user_id": MOCK_USER_ID},
            )
