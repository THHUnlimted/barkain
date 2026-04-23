"""M13 Portal worker alerting (Step 3g).

Wraps the existing portal_rates worker so a portal returning zero rows
for three consecutive runs triggers a Resend email to the configured
operator. Counters live on ``portal_configs`` (per-portal scope, no
extra table) and reset on the next successful (≥1 row) run.

The 24h throttle on ``last_alerted_at`` keeps a stuck portal from spam-
emailing every 6 hours indefinitely. After the first alert, the operator
investigates; subsequent firings within 24h are squelched.

Resend dependency: empty ``RESEND_API_KEY`` → log a WARNING and return
without sending. Mirrors the ``AFFILIATE_WEBHOOK_SECRET`` permissive-
placeholder convention from Step 2g — a partly-configured environment
still runs the worker, it just can't notify anyone.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from modules.m13_portal.models import PortalConfig

logger = logging.getLogger("barkain.m13.alerting")


# MARK: - Tunables

_FAILURE_ALERT_THRESHOLD = 3  # consecutive empty runs that trigger an alert
_ALERT_THROTTLE = timedelta(hours=24)  # don't re-alert within this window


# MARK: - Public entry point


async def send_failure_alert_if_warranted(
    db: AsyncSession,
    run_result: Mapping[str, int],
) -> None:
    """Update per-portal counters and fire alerts when warranted.

    ``run_result`` is the dict returned by ``run_portal_scrape`` —
    keys are portal_source names, values are the number of rows
    upserted on this run. Anything not in ``portal_configs`` (e.g. the
    DEFERRED_PORTALS placeholder rows) is ignored.
    """
    configs = await _load_configs_by_source(db, list(run_result.keys()))

    now = datetime.now(UTC)
    for portal_source, row_count in run_result.items():
        config = configs.get(portal_source)
        if config is None:
            # Worker emitted a portal we don't know about — ignore. Avoid
            # noisy WARNINGs for known DEFERRED_PORTALS placeholders.
            continue

        if row_count > 0:
            # Successful run — reset the counter. Don't touch
            # last_alerted_at; that lives across success/fail cycles.
            if config.consecutive_failures != 0:
                logger.info(
                    "m13: portal %s recovered after %d failures",
                    portal_source,
                    config.consecutive_failures,
                )
                config.consecutive_failures = 0
            continue

        config.consecutive_failures += 1
        logger.warning(
            "m13: portal %s returned 0 rows (consecutive failures: %d)",
            portal_source,
            config.consecutive_failures,
        )

        if config.consecutive_failures < _FAILURE_ALERT_THRESHOLD:
            continue

        if _within_throttle(config.last_alerted_at, now):
            logger.info(
                "m13: alert for %s squelched (last alerted %s)",
                portal_source,
                config.last_alerted_at,
            )
            continue

        sent = _send_failure_email(config)
        if sent:
            config.last_alerted_at = now


# MARK: - Helpers


async def _load_configs_by_source(
    db: AsyncSession,
    portal_sources: list[str],
) -> dict[str, PortalConfig]:
    if not portal_sources:
        return {}
    stmt = select(PortalConfig).where(
        PortalConfig.portal_source.in_(portal_sources)
    )
    result = await db.execute(stmt)
    return {row.portal_source: row for row in result.scalars().all()}


def _within_throttle(last_alerted_at: datetime | None, now: datetime) -> bool:
    if last_alerted_at is None:
        return False
    if last_alerted_at.tzinfo is None:
        last_alerted_at = last_alerted_at.replace(tzinfo=UTC)
    return now - last_alerted_at < _ALERT_THROTTLE


def _send_failure_email(config: PortalConfig) -> bool:
    """Fire the Resend email. Returns True on a successful send.

    Empty API key → WARNING + return False (caller does not record an
    alert timestamp, so the next run will retry as soon as creds land).
    """
    if not settings.RESEND_API_KEY:
        logger.warning(
            "m13: would alert on portal %s but RESEND_API_KEY is unset",
            config.portal_source,
        )
        return False
    if not (settings.RESEND_ALERT_FROM and settings.RESEND_ALERT_TO):
        logger.warning(
            "m13: would alert on portal %s but RESEND_ALERT_{FROM,TO} unset",
            config.portal_source,
        )
        return False

    try:
        import resend
    except ImportError:
        logger.warning(
            "m13: resend package not installed — skipping alert for %s",
            config.portal_source,
        )
        return False

    resend.api_key = settings.RESEND_API_KEY
    subject = f"[Barkain] Portal scrape failing: {config.portal_source}"
    body = (
        f"Portal: {config.display_name} ({config.portal_source})\n"
        f"Consecutive empty runs: {config.consecutive_failures}\n"
        f"Last alerted: {config.last_alerted_at}\n\n"
        f"The portal_rates worker has returned zero rows for "
        f"{config.consecutive_failures} consecutive runs. The DOM may have "
        f"shifted — refresh the fixture under "
        f"backend/tests/fixtures/portal_rates/ after confirming the live "
        f"page changed shape (see docs/CHANGELOG.md §Step 2h decision #8)."
    )
    try:
        resend.Emails.send(
            {
                "from": settings.RESEND_ALERT_FROM,
                "to": [settings.RESEND_ALERT_TO],
                "subject": subject,
                "text": body,
            }
        )
        logger.info(
            "m13: alert sent for portal %s (consecutive_failures=%d)",
            config.portal_source,
            config.consecutive_failures,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "m13: resend.Emails.send failed for %s: %s",
            config.portal_source,
            exc,
        )
        return False
