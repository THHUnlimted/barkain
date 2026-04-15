"""Price ingestion worker.

Two modes:

1. ``enqueue_stale_products(db, sqs)`` — scheduled every 6h. Finds all
   products whose newest ``prices.last_checked`` is older than the stale
   cutoff and sends one SQS message per product. Products with zero
   prices are ignored: they need a real user scan first to seed the
   retailer set.

2. ``process_queue(db, redis, sqs)`` — long-poll consumer. Reuses the
   existing :class:`PriceAggregationService.get_prices` with
   ``force_refresh=True`` so container dispatch, Redis + DB caching, and
   the ``price_history`` append are handled in one place. The worker
   adds no normalization of its own.

Message shape (wire)::

    {
        "product_id": "<uuid>",
        "product_name": "Sony WH-1000XM5",
        "retailers": ["amazon", "best_buy", "walmart"],
        "enqueued_at": "2026-04-14T12:00:00Z"
    }

``retailers`` is informational only — the service refreshes every active
retailer for the product. The field is carried for forensic logging and
future "refresh only these retailers" routing.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

import redis.asyncio as aioredis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from modules.m1_product.models import Product
from modules.m2_prices.container_client import ContainerClient
from modules.m2_prices.service import PriceAggregationService
from workers.queue_client import QUEUE_PRICE_INGESTION, SQSClient

logger = logging.getLogger("barkain.workers.price_ingestion")


async def enqueue_stale_products(
    db: AsyncSession,
    sqs: SQSClient,
    stale_hours: int | None = None,
) -> int:
    """Enqueue one SQS message per product with stale prices.

    A product is stale when the newest ``prices.last_checked`` row is
    older than ``NOW() - stale_hours``. Products without any ``prices``
    rows at all are skipped — there is no retailer set to refresh until
    a user scans them for the first time.

    Returns the number of messages successfully enqueued.
    """
    cutoff_hours = (
        stale_hours
        if stale_hours is not None
        else settings.PRICE_INGESTION_STALE_HOURS
    )
    cutoff = datetime.now(UTC) - timedelta(hours=cutoff_hours)

    rows = (
        await db.execute(
            text(
                """
                SELECT p.id, p.name, array_agg(DISTINCT pr.retailer_id) AS retailers
                FROM products p
                JOIN prices pr ON pr.product_id = p.id
                GROUP BY p.id, p.name
                HAVING MAX(pr.last_checked) < :cutoff
                """
            ),
            {"cutoff": cutoff},
        )
    ).all()

    enqueued = 0
    for row in rows:
        body = {
            "product_id": str(row.id),
            "product_name": row.name,
            "retailers": list(row.retailers or []),
            "enqueued_at": datetime.now(UTC).isoformat(),
        }
        await sqs.send_message(QUEUE_PRICE_INGESTION, body)
        enqueued += 1

    logger.info(
        "Enqueued %d stale products (cutoff=%dh)", enqueued, cutoff_hours
    )
    return enqueued


async def process_queue(
    db: AsyncSession,
    redis: aioredis.Redis,
    sqs: SQSClient,
    container_client: ContainerClient | None = None,
    max_iterations: int | None = None,
) -> int:
    """Drain the price ingestion queue.

    Reuses :class:`PriceAggregationService.get_prices` with
    ``force_refresh=True`` — the same pipeline a user scan triggers,
    just initiated from SQS instead of an HTTP request. All container
    dispatch, caching, and ``price_history`` bookkeeping lives in the
    service layer.

    Error handling:
        * Malformed bodies (missing or non-UUID ``product_id``) are
          ack+skipped — retrying bad data just retries the same crash.
        * Missing products (UUID that doesn't exist in ``products``) are
          ack+skipped for the same reason.
        * Any ``PriceAggregationService`` exception is logged and the
          message is **not** deleted. SQS visibility timeout handles
          retry naturally.

    Returns the number of messages successfully processed.
    """
    service = PriceAggregationService(db, redis, container_client)
    processed = 0
    iterations = 0

    while True:
        if max_iterations is not None and iterations >= max_iterations:
            break
        iterations += 1

        messages = await sqs.receive_messages(
            QUEUE_PRICE_INGESTION,
            # In the bounded-test path, skip the 20s SQS long-poll so
            # tests drain immediately when the queue is empty.
            wait_seconds=0 if max_iterations is not None else 20,
        )
        if not messages:
            if max_iterations is not None:
                break
            continue

        for msg in messages:
            body = msg["body"]
            try:
                product_id = uuid.UUID(body["product_id"])
            except (KeyError, ValueError, TypeError) as exc:
                logger.warning("Malformed message body=%s err=%s", body, exc)
                await sqs.delete_message(
                    QUEUE_PRICE_INGESTION, msg["receipt_handle"]
                )
                continue

            exists = await db.execute(
                select(Product).where(Product.id == product_id)
            )
            if not exists.scalar_one_or_none():
                logger.warning("Product %s not found, ack+skip", product_id)
                await sqs.delete_message(
                    QUEUE_PRICE_INGESTION, msg["receipt_handle"]
                )
                continue

            try:
                await service.get_prices(product_id, force_refresh=True)
                await sqs.delete_message(
                    QUEUE_PRICE_INGESTION, msg["receipt_handle"]
                )
                processed += 1
            except Exception as exc:  # noqa: BLE001
                # Don't delete — SQS visibility timeout handles retry.
                logger.exception(
                    "Price refresh failed for %s: %s", product_id, exc
                )

    return processed
