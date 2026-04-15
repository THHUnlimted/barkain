"""Watchdog CLI — run from project root.

Usage:
    python scripts/run_watchdog.py --check-all
    python scripts/run_watchdog.py --heal amazon
    python scripts/run_watchdog.py --status
    python scripts/run_watchdog.py --check-all --dry-run

Cron setup (nightly at 3 AM):
    0 3 * * * cd /path/to/barkain && python scripts/run_watchdog.py --check-all
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Add backend to sys.path so we can import modules
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app import models as _models  # noqa: E402, F401  # registers all ORM classes with Base.metadata so cross-module FKs resolve at flush time
from app.config import settings  # noqa: E402
from app.database import AsyncSessionLocal  # noqa: E402


async def main() -> None:
    import redis.asyncio as aioredis

    from workers.watchdog import WatchdogSupervisor
    from modules.m2_prices.health_monitor import HealthMonitorService

    parser = argparse.ArgumentParser(description="Barkain Watchdog CLI")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check-all", action="store_true", help="Check all retailers")
    group.add_argument("--heal", type=str, metavar="RETAILER_ID", help="Force heal for a retailer")
    group.add_argument("--status", action="store_true", help="Show current health status")
    parser.add_argument("--dry-run", action="store_true", help="Classify only, no healing or DB writes")
    args = parser.parse_args()

    redis = aioredis.from_url(settings.REDIS_URL)

    async with AsyncSessionLocal() as db:
        if args.status:
            monitor = HealthMonitorService(db=db)
            health = await monitor.get_all_health()
            print(json.dumps(health, indent=2))
        else:
            watchdog = WatchdogSupervisor(db=db, redis=redis, dry_run=args.dry_run)

            if args.check_all:
                results = await watchdog.check_all_retailers()
                print(json.dumps(results, indent=2, default=str))
            elif args.heal:
                result = await watchdog.check_retailer(args.heal)
                print(json.dumps(result, indent=2, default=str))

            if not args.dry_run:
                await db.commit()

    await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
