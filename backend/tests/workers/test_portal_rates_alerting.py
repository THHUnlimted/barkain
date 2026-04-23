"""Tests for the m13 portal_rates alerting layer (Step 3g)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from modules.m13_portal.alerting import send_failure_alert_if_warranted
from modules.m13_portal.models import PortalConfig


# MARK: - Helpers


async def _seed_config(
    db_session,
    portal_source: str,
    *,
    consecutive_failures: int = 0,
    last_alerted_at: datetime | None = None,
) -> PortalConfig:
    config = PortalConfig(
        portal_source=portal_source,
        display_name=portal_source.title(),
        homepage_url=f"https://www.{portal_source}.com/",
        consecutive_failures=consecutive_failures,
        last_alerted_at=last_alerted_at,
    )
    db_session.add(config)
    await db_session.flush()
    return config


@pytest.fixture
def resend_configured(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "RESEND_API_KEY", "re_test_key")
    monkeypatch.setattr(settings, "RESEND_ALERT_FROM", "alerts@barkain.test")
    monkeypatch.setattr(settings, "RESEND_ALERT_TO", "ops@barkain.test")


@pytest.fixture
def fake_resend(monkeypatch):
    """Stub the resend.Emails.send call so tests don't hit the network."""
    import sys
    import types

    sent: list[dict] = []

    fake_module = types.ModuleType("resend")
    fake_module.api_key = ""

    class _FakeEmails:
        @staticmethod
        def send(payload):
            sent.append(payload)
            return {"id": "fake_email_id"}

    fake_module.Emails = _FakeEmails  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "resend", fake_module)
    return sent


# MARK: - Tests


@pytest.mark.asyncio
async def test_zero_rows_increments_failure_counter(db_session):
    config = await _seed_config(db_session, "rakuten", consecutive_failures=0)
    await send_failure_alert_if_warranted(db_session, {"rakuten": 0})
    assert config.consecutive_failures == 1


@pytest.mark.asyncio
async def test_three_consecutive_failures_triggers_alert(
    db_session, resend_configured, fake_resend
):
    config = await _seed_config(db_session, "rakuten", consecutive_failures=2)
    await send_failure_alert_if_warranted(db_session, {"rakuten": 0})

    assert config.consecutive_failures == 3
    assert len(fake_resend) == 1
    payload = fake_resend[0]
    assert payload["from"] == "alerts@barkain.test"
    assert payload["to"] == ["ops@barkain.test"]
    assert "rakuten" in payload["subject"].lower()
    assert config.last_alerted_at is not None


@pytest.mark.asyncio
async def test_successful_run_resets_counter(db_session):
    config = await _seed_config(db_session, "rakuten", consecutive_failures=2)
    await send_failure_alert_if_warranted(db_session, {"rakuten": 5})
    assert config.consecutive_failures == 0


@pytest.mark.asyncio
async def test_empty_resend_api_key_logs_and_skips_send(
    db_session, monkeypatch, fake_resend
):
    from app.config import settings

    monkeypatch.setattr(settings, "RESEND_API_KEY", "")
    monkeypatch.setattr(settings, "RESEND_ALERT_FROM", "alerts@barkain.test")
    monkeypatch.setattr(settings, "RESEND_ALERT_TO", "ops@barkain.test")

    config = await _seed_config(db_session, "rakuten", consecutive_failures=2)
    await send_failure_alert_if_warranted(db_session, {"rakuten": 0})

    # Counter still increments (we know there's a failure) but no alert
    # was attempted, and last_alerted_at stays None so the next run with
    # creds populated can still fire.
    assert config.consecutive_failures == 3
    assert config.last_alerted_at is None
    assert fake_resend == []


@pytest.mark.asyncio
async def test_last_alerted_at_throttles_repeat_sends(
    db_session, resend_configured, fake_resend
):
    recently = datetime.now(UTC) - timedelta(minutes=30)
    config = await _seed_config(
        db_session,
        "rakuten",
        consecutive_failures=3,
        last_alerted_at=recently,
    )
    await send_failure_alert_if_warranted(db_session, {"rakuten": 0})

    assert config.consecutive_failures == 4
    assert fake_resend == []
    # last_alerted_at unchanged — throttle is intact.
    assert config.last_alerted_at == recently
