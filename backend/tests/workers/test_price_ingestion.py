"""Tests for workers.price_ingestion."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from moto import mock_aws
from sqlalchemy import text

from app.core_models import Retailer
from modules.m1_product.models import Product
from modules.m2_prices.models import Price
from workers.price_ingestion import enqueue_stale_products, process_queue
from workers.queue_client import QUEUE_PRICE_INGESTION, SQSClient


async def _seed_retailer(db, retailer_id: str) -> None:
    if (
        await db.execute(text("SELECT 1 FROM retailers WHERE id = :id"), {"id": retailer_id})
    ).scalar_one_or_none() is None:
        db.add(
            Retailer(
                id=retailer_id,
                display_name=retailer_id.replace("_", " ").title(),
                base_url=f"https://www.{retailer_id}.com",
                extraction_method="agent_browser",
            )
        )
        await db.flush()


async def _seed_product(db, name: str) -> Product:
    product = Product(
        upc=f"upc-{uuid.uuid4().hex[:10]}",
        name=name,
        brand="test",
        source="test",
    )
    db.add(product)
    await db.flush()
    return product


async def _seed_price(
    db, product_id: uuid.UUID, retailer_id: str, last_checked: datetime
) -> None:
    price = Price(
        product_id=product_id,
        retailer_id=retailer_id,
        price=Decimal("100.00"),
        url=f"https://www.{retailer_id}.com/p/{product_id}",
        last_checked=last_checked,
    )
    db.add(price)
    await db.flush()


@pytest.mark.asyncio
async def test_enqueue_stale_products_sends_one_per_stale_product(db_session):
    await _seed_retailer(db_session, "amazon")
    await _seed_retailer(db_session, "best_buy")

    now = datetime.now(UTC)
    stale_a = await _seed_product(db_session, "Stale Product A")
    stale_b = await _seed_product(db_session, "Stale Product B")
    fresh = await _seed_product(db_session, "Fresh Product")

    old = now - timedelta(hours=10)
    recent = now - timedelta(minutes=30)

    await _seed_price(db_session, stale_a.id, "amazon", old)
    await _seed_price(db_session, stale_a.id, "best_buy", old)
    await _seed_price(db_session, stale_b.id, "amazon", old)
    await _seed_price(db_session, fresh.id, "amazon", recent)

    with mock_aws():
        sqs = SQSClient(endpoint_url=None, region="us-east-1")
        await sqs.create_queue(QUEUE_PRICE_INGESTION)

        count = await enqueue_stale_products(db_session, sqs, stale_hours=6)
        assert count == 2

        received_bodies = []
        for _ in range(2):
            msgs = await sqs.receive_messages(
                QUEUE_PRICE_INGESTION, wait_seconds=0
            )
            for m in msgs:
                received_bodies.append(m["body"])

        product_ids = {b["product_id"] for b in received_bodies}
        assert product_ids == {str(stale_a.id), str(stale_b.id)}


@pytest.mark.asyncio
async def test_enqueue_stale_products_skips_products_without_prices(db_session):
    await _seed_retailer(db_session, "amazon")
    await _seed_product(db_session, "Orphan product with no prices")

    with mock_aws():
        sqs = SQSClient(endpoint_url=None, region="us-east-1")
        await sqs.create_queue(QUEUE_PRICE_INGESTION)

        count = await enqueue_stale_products(db_session, sqs, stale_hours=6)
        assert count == 0


@pytest.mark.asyncio
async def test_process_queue_calls_price_service_with_force_refresh(
    db_session, fake_redis, monkeypatch
):
    await _seed_retailer(db_session, "amazon")
    product = await _seed_product(db_session, "Scan Me")

    calls = []

    async def _fake_get_prices(self, product_id, force_refresh=False):
        calls.append((product_id, force_refresh))
        return {
            "product_id": str(product_id),
            "prices": [],
            "retailer_results": {},
        }

    import modules.m2_prices.service as price_service

    monkeypatch.setattr(
        price_service.PriceAggregationService, "get_prices", _fake_get_prices
    )

    with mock_aws():
        sqs = SQSClient(endpoint_url=None, region="us-east-1")
        await sqs.create_queue(QUEUE_PRICE_INGESTION)
        await sqs.send_message(
            QUEUE_PRICE_INGESTION,
            {
                "product_id": str(product.id),
                "product_name": "Scan Me",
                "retailers": ["amazon"],
                "enqueued_at": datetime.now(UTC).isoformat(),
            },
        )

        processed = await process_queue(
            db_session, fake_redis, sqs, container_client=None, max_iterations=1
        )
        assert processed == 1
        assert len(calls) == 1
        assert calls[0][0] == product.id
        assert calls[0][1] is True

        leftover = await sqs.receive_messages(
            QUEUE_PRICE_INGESTION, wait_seconds=0
        )
        assert leftover == []


@pytest.mark.asyncio
async def test_process_queue_skips_unknown_product(
    db_session, fake_redis, monkeypatch
):
    calls = []

    async def _fake_get_prices(self, product_id, force_refresh=False):
        calls.append(product_id)
        return {}

    import modules.m2_prices.service as price_service

    monkeypatch.setattr(
        price_service.PriceAggregationService, "get_prices", _fake_get_prices
    )

    with mock_aws():
        sqs = SQSClient(endpoint_url=None, region="us-east-1")
        await sqs.create_queue(QUEUE_PRICE_INGESTION)
        random_id = uuid.uuid4()
        await sqs.send_message(
            QUEUE_PRICE_INGESTION,
            {
                "product_id": str(random_id),
                "product_name": "Ghost",
                "retailers": ["amazon"],
                "enqueued_at": datetime.now(UTC).isoformat(),
            },
        )

        processed = await process_queue(
            db_session, fake_redis, sqs, container_client=None, max_iterations=1
        )
        assert processed == 0
        assert calls == []

        leftover = await sqs.receive_messages(
            QUEUE_PRICE_INGESTION, wait_seconds=0
        )
        assert leftover == []  # ack+delete on missing product
