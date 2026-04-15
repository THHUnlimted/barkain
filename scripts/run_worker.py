"""Barkain background worker CLI runner.

Mirrors ``scripts/run_watchdog.py``: argparse + ``asyncio.run`` +
``async with AsyncSessionLocal()`` outside the FastAPI DI container.

Usage::

    python3 scripts/run_worker.py setup-queues      # Create SQS queues (idempotent)
    python3 scripts/run_worker.py price-enqueue     # Enqueue stale products
    python3 scripts/run_worker.py price-process     # Long-poll ingestion queue
    python3 scripts/run_worker.py portal-rates      # Scrape portal rates (one-shot)
    python3 scripts/run_worker.py discount-verify   # Verify discount URLs (one-shot)

Cron schedule (production, UTC)::

    # Price refresh enqueue — every 6 hours
    0 */6 * * *   cd /path/to/barkain && python3 scripts/run_worker.py price-enqueue

    # Portal rate scrape — offset 30m so it doesn't race price enqueue
    30 */6 * * *  cd /path/to/barkain && python3 scripts/run_worker.py portal-rates

    # Discount program verification — Sunday 04:00
    0 4 * * 0     cd /path/to/barkain && python3 scripts/run_worker.py discount-verify

    # Watchdog health check — nightly 03:00
    0 3 * * *     cd /path/to/barkain && python3 scripts/run_worker.py --check-all

(The last line still points at ``run_watchdog.py``; worker runner is
intentionally separate to keep each CLI's surface small.)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

import redis.asyncio as aioredis  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import AsyncSessionLocal  # noqa: E402
from workers.queue_client import ALL_QUEUES, SQSClient  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("barkain.run_worker")


async def _price_enqueue() -> None:
    from workers.price_ingestion import enqueue_stale_products

    sqs = SQSClient()
    async with AsyncSessionLocal() as db:
        count = await enqueue_stale_products(db, sqs)
    logger.info("price-enqueue done: %d messages", count)


async def _price_process() -> None:
    from modules.m2_prices.container_client import ContainerClient
    from workers.price_ingestion import process_queue

    sqs = SQSClient()
    redis = aioredis.from_url(settings.REDIS_URL)
    container_client = ContainerClient()
    try:
        async with AsyncSessionLocal() as db:
            try:
                processed = await process_queue(
                    db, redis, sqs, container_client
                )
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        logger.info("price-process done: %d messages processed", processed)
    finally:
        await redis.aclose()


async def _portal_rates() -> None:
    from workers.portal_rates import run_portal_scrape

    async with AsyncSessionLocal() as db:
        try:
            summary = await run_portal_scrape(db)
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    logger.info("portal-rates done: %s", json.dumps(summary))


async def _discount_verify() -> None:
    from workers.discount_verification import run_discount_verification

    async with AsyncSessionLocal() as db:
        try:
            summary = await run_discount_verification(db)
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    logger.info("discount-verify done: %s", json.dumps(summary))


async def _setup_queues() -> None:
    client = SQSClient()
    for queue in ALL_QUEUES:
        url = await client.create_queue(queue)
        logger.info("queue ready: %s -> %s", queue, url)


COMMANDS = {
    "price-enqueue": _price_enqueue,
    "price-process": _price_process,
    "portal-rates": _portal_rates,
    "discount-verify": _discount_verify,
    "setup-queues": _setup_queues,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Barkain worker runner")
    parser.add_argument(
        "command",
        choices=sorted(COMMANDS.keys()),
        help="Which worker task to run.",
    )
    args = parser.parse_args()
    asyncio.run(COMMANDS[args.command]())


if __name__ == "__main__":
    main()
