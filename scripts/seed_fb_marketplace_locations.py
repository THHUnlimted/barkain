#!/usr/bin/env python3
"""Seed fb_marketplace_locations from a list of US cities.

This warms the L2 Postgres cache so that real iOS users in common metros
never pay the live-resolver latency (~1 s + search-engine token bucket)
on their first save. After the seed runs, resolver hits L1/L2 for any
city in the seed list; the live path only fires for the long tail.

Uses the production ``FbLocationResolver`` end-to-end — same token
bucket, same engine fallback, same singleflight — but with a single
caller (this script). That keeps the bootstrap honest: if the rate
limits aren't sustainable in reality, we find out here, not in prod.

Idempotent: rows that already exist are skipped via the resolver's L1/L2
short-circuit, so re-running after a partial failure is safe.

Usage
-----
    python scripts/seed_fb_marketplace_locations.py                    # top-50 baked-in
    python scripts/seed_fb_marketplace_locations.py --cities-csv <path>
    python scripts/seed_fb_marketplace_locations.py --dry-run          # print plan only
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import sys
from pathlib import Path

# Prepend the backend dir so `from app.*` / `from modules.*` resolve when
# running this script directly without setting PYTHONPATH.
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "backend"))

import redis.asyncio as aioredis  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.config import settings  # noqa: E402
from app import models  # noqa: F401, E402 — side-effect: register FbMarketplaceLocation
from modules.m2_prices.adapters.fb_marketplace_location_resolver import (  # noqa: E402
    FbLocationResolver,
)

logger = logging.getLogger("barkain.seed.fb_locations")


# MARK: - Baked-in top-50 US metros
#
# Picked by population + user-likelihood. Covers the NYC boroughs / LA
# metro / SF Bay / Atlanta / Chicago / Boston clusters that the old
# slug-alias map had to special-case. Source: Census 2020 + common-sense
# rounding to single entries per metro (we don't need Staten Island AND
# Brooklyn — FB resolves both to the NYC Page). The seed is a starting
# point, not an authoritative list; rerun with --cities-csv for full
# coverage.
_TOP_50_US: list[tuple[str, str]] = [
    ("New York", "NY"),
    ("Brooklyn", "NY"),
    ("Manhattan", "NY"),
    ("Queens", "NY"),
    ("Los Angeles", "CA"),
    ("Long Beach", "CA"),
    ("Santa Monica", "CA"),
    ("San Diego", "CA"),
    ("San Francisco", "CA"),
    ("Oakland", "CA"),
    ("San Jose", "CA"),
    ("Chicago", "IL"),
    ("Houston", "TX"),
    ("Austin", "TX"),
    ("Dallas", "TX"),
    ("Fort Worth", "TX"),
    ("San Antonio", "TX"),
    ("El Paso", "TX"),
    ("Philadelphia", "PA"),
    ("Pittsburgh", "PA"),
    ("Phoenix", "AZ"),
    ("Tucson", "AZ"),
    ("Jacksonville", "FL"),
    ("Miami", "FL"),
    ("Orlando", "FL"),
    ("Tampa", "FL"),
    ("Atlanta", "GA"),
    ("Mableton", "GA"),
    ("Marietta", "GA"),
    ("Boston", "MA"),
    ("Cambridge", "MA"),
    ("Seattle", "WA"),
    ("Denver", "CO"),
    ("Washington", "DC"),
    ("Las Vegas", "NV"),
    ("Portland", "OR"),
    ("Nashville", "TN"),
    ("Memphis", "TN"),
    ("Detroit", "MI"),
    ("Indianapolis", "IN"),
    ("Columbus", "OH"),
    ("Cleveland", "OH"),
    ("Charlotte", "NC"),
    ("Raleigh", "NC"),
    ("Minneapolis", "MN"),
    ("Milwaukee", "WI"),
    ("Kansas City", "MO"),
    ("St. Louis", "MO"),
    ("Baltimore", "MD"),
    ("Sacramento", "CA"),
]


# MARK: - CSV loader


def _cities_from_csv(path: Path, min_population: int) -> list[tuple[str, str]]:
    """Read a SimpleMaps-style ``uscities.csv`` → [(city, state_id), …].

    Expected columns: ``city``, ``state_id``, ``population``. Unknown /
    non-numeric population rows are skipped, not fatal.
    """
    out: list[tuple[str, str]] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                pop = int(float(row.get("population", "0") or "0"))
            except ValueError:
                continue
            if pop < min_population:
                continue
            city = (row.get("city") or "").strip()
            state = (row.get("state_id") or "").strip().upper()
            if city and len(state) == 2:
                out.append((city, state))
    return out


# MARK: - Seed runner


async def _seed(
    cities: list[tuple[str, str]], dry_run: bool, country: str
) -> None:
    if dry_run:
        for city, state in cities:
            logger.info("[dry-run] would resolve: %s, %s", city, state)
        logger.info("[dry-run] %d cities", len(cities))
        return

    engine = create_async_engine(settings.DATABASE_URL)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    redis = aioredis.from_url(settings.REDIS_URL)

    stats = {"resolved": 0, "tombstoned": 0, "throttled": 0, "errors": 0}

    try:
        for i, (city, state) in enumerate(cities, start=1):
            async with session_factory() as db:
                resolver = FbLocationResolver(db=db, redis=redis)
                try:
                    resolved = await resolver.resolve(city, state, country=country)
                finally:
                    await resolver.aclose()

            if resolved.source == "throttled":
                stats["throttled"] += 1
                logger.warning(
                    "[%d/%d] %s, %s — THROTTLED (will retry next run)",
                    i,
                    len(cities),
                    city,
                    state,
                )
                # Back off when the resolver starts throttling — the
                # bucket needs time to refill. 3s is enough to drain the
                # Startpage queue head without being wasteful.
                await asyncio.sleep(3.0)
                continue

            if resolved.location_id is None:
                stats["tombstoned"] += 1
                logger.info(
                    "[%d/%d] %s, %s — tombstoned (no FB Marketplace here)",
                    i,
                    len(cities),
                    city,
                    state,
                )
            else:
                stats["resolved"] += 1
                logger.info(
                    "[%d/%d] %s, %s → %s (canonical=%s, source=%s)",
                    i,
                    len(cities),
                    city,
                    state,
                    resolved.location_id,
                    resolved.canonical_name,
                    resolved.source,
                )

        logger.info(
            "Seed complete: resolved=%d tombstoned=%d throttled=%d errors=%d",
            stats["resolved"],
            stats["tombstoned"],
            stats["throttled"],
            stats["errors"],
        )
    finally:
        await redis.aclose()
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed fb_marketplace_locations.")
    parser.add_argument(
        "--cities-csv",
        type=Path,
        default=None,
        help="Path to SimpleMaps uscities.csv. If omitted, uses the baked-in top-50.",
    )
    parser.add_argument(
        "--min-population",
        type=int,
        default=50_000,
        help="Skip CSV rows below this population (ignored for --cities-csv-less runs).",
    )
    parser.add_argument(
        "--country",
        type=str,
        default="US",
        help="Two-letter country code stored on each row.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the plan without contacting the resolver.",
    )
    parser.add_argument(
        "--log-level", type=str, default="INFO", help="Python logging level."
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.cities_csv:
        cities = _cities_from_csv(args.cities_csv, args.min_population)
        logger.info(
            "Loaded %d cities from %s (min_population=%d)",
            len(cities),
            args.cities_csv,
            args.min_population,
        )
    else:
        cities = list(_TOP_50_US)
        logger.info("Using baked-in top-%d US metros", len(cities))

    asyncio.run(_seed(cities, dry_run=args.dry_run, country=args.country.upper()))


if __name__ == "__main__":
    main()
