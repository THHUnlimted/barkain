"""Discount program verification worker.

Weekly batch (cron ``0 4 * * 0``): for each ``discount_programs`` row
with a ``verification_url``, hit the page with a Chrome UA, and check
whether the program name appears in the response body.

Decision tree per program:

* HTTP 200 + program_name in body → ``verified``, reset
  ``consecutive_failures`` to 0.
* HTTP 200 + program_name **not** in body → ``flagged_missing_mention``.
  We treat this as a soft signal (operator should review — maybe the
  program was renamed) and do **not** increment the failure counter.
* HTTP 4xx / 5xx / network error → ``failed``, increment the counter.
* Counter reaches ``DISCOUNT_VERIFICATION_FAILURE_THRESHOLD`` (default 3)
  → flip ``is_active=False``. A single CDN blip cannot remove an
  otherwise valid program; three consecutive weekly failures can.

``last_verified`` updates on every run regardless of outcome so the
same stale program doesn't re-surface in the next stale query within
the same week.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from modules.m5_identity.models import DiscountProgram

logger = logging.getLogger("barkain.workers.discount_verification")

CHROME_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


async def get_stale_programs(
    db: AsyncSession, stale_days: int
) -> list[DiscountProgram]:
    """Return active programs whose verification is older than the cutoff.

    Programs with no ``verification_url`` at all are excluded — we have
    nothing to hit. Programs with ``last_verified is None`` are
    considered stale by definition.
    """
    cutoff = datetime.now(UTC) - timedelta(days=stale_days)
    result = await db.execute(
        select(DiscountProgram)
        .where(DiscountProgram.is_active.is_(True))
        .where(DiscountProgram.verification_url.is_not(None))
        .where(
            or_(
                DiscountProgram.last_verified.is_(None),
                DiscountProgram.last_verified < cutoff,
            )
        )
    )
    return list(result.scalars().all())


async def check_url(
    client: httpx.AsyncClient,
    url: str,
    program_name: str,
) -> tuple[bool, str]:
    """Return ``(is_verified, status)``.

    ``is_verified`` is True only when the response is HTTP 200 AND the
    program name is found in the body. ``status`` is one of
    ``"verified"``, ``"flagged_missing_mention"``, ``"http:<code>"``,
    or ``"network:<exc_class>"``.
    """
    try:
        resp = await client.get(url)
    except httpx.HTTPError as exc:
        return (False, f"network:{exc.__class__.__name__}")

    if resp.status_code != 200:
        return (False, f"http:{resp.status_code}")

    if program_name.lower() in resp.text.lower():
        return (True, "verified")

    return (False, "flagged_missing_mention")


async def run_discount_verification(
    db: AsyncSession,
    stale_days: int | None = None,
    failure_threshold: int | None = None,
) -> dict[str, int]:
    """One-shot verification pass.

    Returns a summary dict::

        {"checked": int, "verified": int, "flagged": int,
         "failed": int, "deactivated": int}
    """
    stale = (
        stale_days
        if stale_days is not None
        else settings.DISCOUNT_VERIFICATION_STALE_DAYS
    )
    threshold = (
        failure_threshold
        if failure_threshold is not None
        else settings.DISCOUNT_VERIFICATION_FAILURE_THRESHOLD
    )

    programs = await get_stale_programs(db, stale)
    summary = {
        "checked": 0,
        "verified": 0,
        "flagged": 0,
        "failed": 0,
        "deactivated": 0,
    }
    if not programs:
        return summary

    async with httpx.AsyncClient(
        headers=CHROME_HEADERS,
        timeout=20.0,
        follow_redirects=True,
    ) as client:
        for program in programs:
            summary["checked"] += 1
            is_verified, status = await check_url(
                client, program.verification_url, program.program_name
            )

            program.last_verified = datetime.now(UTC)
            program.last_verified_by = "weekly_batch"

            if is_verified:
                program.consecutive_failures = 0
                summary["verified"] += 1
                continue

            if status == "flagged_missing_mention":
                summary["flagged"] += 1
                logger.warning(
                    "Discount program %s flagged: %s (url=%s)",
                    program.id,
                    status,
                    program.verification_url,
                )
                continue

            program.consecutive_failures = (program.consecutive_failures or 0) + 1
            summary["failed"] += 1

            if program.consecutive_failures >= threshold:
                program.is_active = False
                summary["deactivated"] += 1
                logger.warning(
                    "Discount program %s deactivated after %d failures "
                    "(url=%s status=%s)",
                    program.id,
                    program.consecutive_failures,
                    program.verification_url,
                    status,
                )
            else:
                logger.info(
                    "Discount program %s failure %d/%d (url=%s status=%s)",
                    program.id,
                    program.consecutive_failures,
                    threshold,
                    program.verification_url,
                    status,
                )

    return summary
