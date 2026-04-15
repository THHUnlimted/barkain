"""SQS client abstraction for Barkain background workers.

Uses LocalStack in dev (endpoint from ``settings.SQS_ENDPOINT_URL``) and
real AWS SQS in production (empty endpoint → boto3 default credential
chain resolution).

boto3 is synchronous; the public methods below are async and wrap every
blocking SDK call with ``asyncio.to_thread`` so they can be awaited from
worker event loops without blocking the reactor. A thread-pool hop per
SQS operation is acceptable at our current cadence (tens to hundreds of
messages/hour); if throughput ever exceeds ~10k messages/hour, swap to
``aioboto3``/``aiobotocore`` for a single-loop implementation.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import boto3
from botocore.config import Config as BotoConfig

from app.config import settings

logger = logging.getLogger("barkain.workers.sqs")


QUEUE_PRICE_INGESTION = "barkain-price-ingestion"
QUEUE_PORTAL_SCRAPING = "barkain-portal-scraping"
QUEUE_DISCOUNT_VERIFICATION = "barkain-discount-verification"

ALL_QUEUES: tuple[str, ...] = (
    QUEUE_PRICE_INGESTION,
    QUEUE_PORTAL_SCRAPING,
    QUEUE_DISCOUNT_VERIFICATION,
)


_UNSET = object()


class SQSClient:
    def __init__(
        self,
        endpoint_url: str | None = _UNSET,  # type: ignore[assignment]
        region: str | None = None,
    ) -> None:
        # Use a sentinel so callers can pass ``None`` to mean "no endpoint
        # override — resolve via the default boto3 credential chain"
        # (important for tests backed by ``moto.mock_aws``, which is
        # incompatible with LocalStack endpoint overrides). Passing no
        # argument at all falls back to ``settings.SQS_ENDPOINT_URL``,
        # which may be empty in prod and set to the LocalStack URL in
        # dev via ``.env``.
        if endpoint_url is _UNSET:
            endpoint_url = settings.SQS_ENDPOINT_URL or None
        # Empty string and None both mean "no override" for boto3.
        self._endpoint_url = endpoint_url or None
        self._region = region or settings.SQS_REGION
        self._client = boto3.client(
            "sqs",
            endpoint_url=self._endpoint_url,
            region_name=self._region,
            config=BotoConfig(retries={"max_attempts": 3, "mode": "standard"}),
        )
        self._url_cache: dict[str, str] = {}

    def get_queue_url(self, queue_name: str) -> str:
        if queue_name in self._url_cache:
            return self._url_cache[queue_name]
        resp = self._client.get_queue_url(QueueName=queue_name)
        url = resp["QueueUrl"]
        self._url_cache[queue_name] = url
        return url

    async def send_message(self, queue_name: str, body: dict[str, Any]) -> str:
        def _send() -> str:
            resp = self._client.send_message(
                QueueUrl=self.get_queue_url(queue_name),
                MessageBody=json.dumps(body),
            )
            return resp["MessageId"]

        return await asyncio.to_thread(_send)

    async def receive_messages(
        self,
        queue_name: str,
        max_messages: int = 10,
        wait_seconds: int = 20,
    ) -> list[dict[str, Any]]:
        def _receive() -> list[dict[str, Any]]:
            # boto3 SDK call is singular (`receive_message`) even though it
            # returns many — easy typo trap, noted in the Step 2h plan.
            resp = self._client.receive_message(
                QueueUrl=self.get_queue_url(queue_name),
                MaxNumberOfMessages=max_messages,
                WaitTimeSeconds=wait_seconds,
            )
            return [
                {
                    "body": json.loads(m["Body"]),
                    "receipt_handle": m["ReceiptHandle"],
                }
                for m in resp.get("Messages", [])
            ]

        return await asyncio.to_thread(_receive)

    async def delete_message(self, queue_name: str, receipt_handle: str) -> None:
        def _delete() -> None:
            self._client.delete_message(
                QueueUrl=self.get_queue_url(queue_name),
                ReceiptHandle=receipt_handle,
            )

        await asyncio.to_thread(_delete)

    async def create_queue(self, queue_name: str) -> str:
        """Idempotent — SQS returns the existing URL when the queue exists."""

        def _create() -> str:
            resp = self._client.create_queue(QueueName=queue_name)
            return resp["QueueUrl"]

        url = await asyncio.to_thread(_create)
        self._url_cache[queue_name] = url
        return url
