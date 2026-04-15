"""Portal rate scraping worker.

One-shot: scrapes Rakuten, TopCashBack, and BeFrugal for retailer
cashback rates, normalizes retailer names to Barkain retailer_ids, and
upserts rows into ``portal_bonuses``. The ``is_elevated`` column is a
PostgreSQL GENERATED ALWAYS STORED column — never written; it
auto-computes from ``bonus_value > COALESCE(normal_value, 0) * 1.5``.

Chase Shop Through Chase and Capital One Shopping are listed in the
result dict for observability but log-and-skip: both portals require
auth that isn't wired up here.

Tool choice: ``httpx`` + ``BeautifulSoup``. Portal rate pages are
static-enough HTML tables; ``agent-browser`` would be overkill and
would couple this worker to the scraper container infrastructure,
making local dev painful. This is a deliberate deviation from the
Job 1 pseudocode in ``docs/SCRAPING_AGENT_ARCHITECTURE.md``; see
``docs/CHANGELOG.md`` §Step 2h for the reasoning.

The parsers below were tuned against live HTML probes captured on
2026-04-14 into ``backend/tests/fixtures/portal_rates/``. If any
portal's DOM changes materially, re-probe the live page and refresh
the fixture, not the parser.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Callable

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.m5_identity.models import PortalBonus

logger = logging.getLogger("barkain.workers.portal_rates")

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
    "Cache-Control": "no-cache",
}

# Portal display-name → Barkain retailer_id. Lowercase-only lookup; keep
# common aliases (the and apostrophe variants) so fuzzy matching is not
# needed.
RETAILER_NAME_ALIASES: dict[str, str] = {
    "amazon": "amazon",
    "best buy": "best_buy",
    "bestbuy": "best_buy",
    "walmart": "walmart",
    "target": "target",
    "home depot": "home_depot",
    "the home depot": "home_depot",
    "homedepot": "home_depot",
    "lowe's": "lowes",
    "lowes": "lowes",
    "ebay": "ebay_new",
    "sam's club": "sams_club",
    "sams club": "sams_club",
    "samsclub": "sams_club",
    "backmarket": "backmarket",
    "back market": "backmarket",
}

# Curly apostrophe (&#x27; / U+2019) → straight so alias lookup hits.
_APOSTROPHE_RE = re.compile(r"[\u2018\u2019]|&#x27;")


def _decode_entities(text: str) -> str:
    return _APOSTROPHE_RE.sub("'", text).strip()


def normalize_retailer(name: str) -> str | None:
    if not name:
        return None
    key = _decode_entities(name).lower().strip()
    return RETAILER_NAME_ALIASES.get(key)


def _parse_percent(raw: str) -> Decimal | None:
    """Extract the first ``<num>%`` token from a rate string.

    Handles ``"Up to 5%"``, ``"5% Cash Back"``, ``"5.5%"``, etc. Returns
    ``None`` on any parse failure (never raises).
    """
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", raw)
    if not m:
        return None
    try:
        return Decimal(m.group(1))
    except (InvalidOperation, ValueError):
        return None


@dataclass(frozen=True)
class PortalRate:
    retailer_name: str
    retailer_id: str
    rate_percent: Decimal
    previous_rate_percent: Decimal | None = None  # Rakuten "was X%" baseline


# MARK: - Per-portal parsers (pure functions, trivially unit-testable)


def parse_rakuten(html: str) -> list[PortalRate]:
    """Parse the Rakuten stores listing page.

    Rakuten tiles look like::

        <a aria-label="Find out more at <NAME> - Rakuten coupons and Cash Back" ...>
          ... <span class="css-z47yg2">NAME</span>
          ... <span class="css-xxx">Up to 4% Cash Back</span>
          ... <span class="css-1ynb68i">was 2%</span>
        </a>

    CSS class names are hash-based and will drift, so the parser anchors
    on the stable ``aria-label`` attribute and then pulls the first
    ``X% Cash Back`` and the optional ``was Y%`` from the anchor's text
    body.
    """
    rates: list[PortalRate] = []
    soup = BeautifulSoup(html, "html.parser")
    for anchor in soup.find_all("a", attrs={"aria-label": re.compile(r"Find out more at .+ - Rakuten coupons and Cash Back")}):
        label = anchor.get("aria-label", "")
        m = re.match(r"Find out more at (.+?) - Rakuten coupons and Cash Back", label)
        if not m:
            continue
        name = _decode_entities(m.group(1))
        retailer_id = normalize_retailer(name)
        if not retailer_id:
            continue

        text = anchor.get_text(" ", strip=True)
        current = _parse_percent(text)
        if current is None:
            continue

        was_match = re.search(r"was\s+(\d+(?:\.\d+)?)\s*%", text, re.IGNORECASE)
        previous = None
        if was_match:
            try:
                previous = Decimal(was_match.group(1))
            except (InvalidOperation, ValueError):
                previous = None

        rates.append(
            PortalRate(
                retailer_name=name,
                retailer_id=retailer_id,
                rate_percent=current,
                previous_rate_percent=previous,
            )
        )
    return rates


def parse_topcashback(html: str) -> list[PortalRate]:
    """Parse the TopCashBack category/landing page.

    Each tile is::

        <a href="/<slug>/">
          <img alt="<NAME>">
          <span class="nav-bar-standard-tenancy__value">Up to 6%</span>
        </a>
    """
    rates: list[PortalRate] = []
    soup = BeautifulSoup(html, "html.parser")
    for span in soup.find_all("span", class_="nav-bar-standard-tenancy__value"):
        anchor = span.find_parent("a")
        if anchor is None:
            continue
        img = anchor.find("img")
        if img is None or not img.get("alt"):
            continue
        name = _decode_entities(img["alt"])
        retailer_id = normalize_retailer(name)
        if not retailer_id:
            continue
        rate = _parse_percent(span.get_text(strip=True))
        if rate is None:
            continue
        rates.append(
            PortalRate(
                retailer_name=name,
                retailer_id=retailer_id,
                rate_percent=rate,
            )
        )
    return rates


def parse_befrugal(html: str) -> list[PortalRate]:
    """Parse the BeFrugal store-listing page.

    Each tile::

        <a href="/store/<slug>/?ploc=...">
          <img alt="<NAME>">
          ...
          <span class="... txt-bold txt-under-store">4%</span>
        </a>

    Some tiles lack the bold rate (e.g. Amazon's reward-program-only
    page shows no direct cashback); those are skipped.
    """
    rates: list[PortalRate] = []
    soup = BeautifulSoup(html, "html.parser")
    for anchor in soup.find_all("a", href=re.compile(r"^/store/")):
        img = anchor.find("img")
        if img is None or not img.get("alt"):
            continue
        name = _decode_entities(img["alt"])
        retailer_id = normalize_retailer(name)
        if not retailer_id:
            continue
        # The bold class holds the rate.
        bold_span = anchor.find("span", class_=re.compile(r"\btxt-bold\b"))
        if bold_span is None:
            continue
        rate = _parse_percent(bold_span.get_text(strip=True))
        if rate is None:
            continue
        rates.append(
            PortalRate(
                retailer_name=name,
                retailer_id=retailer_id,
                rate_percent=rate,
            )
        )
    return rates


PortalParser = Callable[[str], list[PortalRate]]

PORTAL_SOURCES: dict[str, tuple[str, PortalParser]] = {
    "rakuten": ("https://www.rakuten.com/stores", parse_rakuten),
    "topcashback": (
        "https://www.topcashback.com/category/big-box-brands/",
        parse_topcashback,
    ),
    "befrugal": ("https://www.befrugal.com/coupons/stores/", parse_befrugal),
}

DEFERRED_PORTALS: tuple[str, ...] = (
    "chase_shop_through_chase",
    "capital_one_shopping",
)


# MARK: - Upsert


async def upsert_portal_bonus(
    db: AsyncSession,
    portal_source: str,
    rate: PortalRate,
) -> None:
    """Insert or update a ``portal_bonuses`` row.

    ``is_elevated`` is GENERATED ALWAYS STORED — never written.

    ``normal_value`` persists across runs so the spike-detection column
    keeps working. On first observation we seed it to the current rate;
    on later runs we leave it alone unless the scrape reports a
    ``previous_rate_percent`` (Rakuten's "was X%" marker), in which case
    we overwrite ``normal_value`` with the scraped baseline so we
    match the portal's own view of what "normal" means.
    """
    now = datetime.now(UTC)

    existing = await db.execute(
        select(PortalBonus).where(
            PortalBonus.portal_source == portal_source,
            PortalBonus.retailer_id == rate.retailer_id,
        )
    )
    row = existing.scalar_one_or_none()

    if row is None:
        # First observation — seed normal_value from the portal's "was"
        # marker if present, otherwise fall back to the current rate so
        # is_elevated stays stable on the very first scrape.
        normal_seed = rate.previous_rate_percent or rate.rate_percent
        db.add(
            PortalBonus(
                portal_source=portal_source,
                retailer_id=rate.retailer_id,
                bonus_type="cashback_percentage",
                bonus_value=rate.rate_percent,
                normal_value=normal_seed,
                effective_from=now,
                last_verified=now,
                verified_by="nightly_batch",
            )
        )
        return

    row.bonus_value = rate.rate_percent
    row.last_verified = now
    row.verified_by = "nightly_batch"
    if rate.previous_rate_percent is not None:
        row.normal_value = rate.previous_rate_percent
    # Otherwise intentionally leave normal_value alone so the
    # baseline-relative spike detector keeps working.


# MARK: - Orchestrator


async def run_portal_scrape(db: AsyncSession) -> dict[str, int]:
    """Scrape all configured portals.

    Returns a dict keyed by portal source with the number of rates
    upserted per portal. Deferred portals always map to ``0``.

    Graceful degradation: a single portal failing (network error, bot
    block, non-2xx status) is logged as a warning and the per-portal
    count goes to ``0``; the other portals still run.
    """
    results: dict[str, int] = {}

    async with httpx.AsyncClient(
        headers=CHROME_HEADERS,
        timeout=30.0,
        follow_redirects=True,
    ) as client:
        for portal_source, (url, parser) in PORTAL_SOURCES.items():
            try:
                resp = await client.get(url)
            except httpx.HTTPError as exc:
                logger.warning(
                    "Portal %s fetch failed: %s", portal_source, exc
                )
                results[portal_source] = 0
                continue

            if resp.status_code in (403, 429, 503):
                logger.warning(
                    "Portal %s bot-blocked: status=%d",
                    portal_source,
                    resp.status_code,
                )
                results[portal_source] = 0
                continue

            if resp.status_code >= 400:
                logger.warning(
                    "Portal %s returned %d, skipping",
                    portal_source,
                    resp.status_code,
                )
                results[portal_source] = 0
                continue

            rates = parser(resp.text)
            for rate in rates:
                await upsert_portal_bonus(db, portal_source, rate)
            results[portal_source] = len(rates)
            logger.info(
                "Portal %s: upserted %d rates", portal_source, len(rates)
            )

    for placeholder in DEFERRED_PORTALS:
        logger.info("Portal %s: deferred (auth required)", placeholder)
        results[placeholder] = 0

    return results
