"""Tests for workers.queue_client.SQSClient.

Uses ``moto`` 5.x (``mock_aws`` context) so the tests are hermetic —
no running LocalStack container needed in CI.
"""

import pytest
from moto import mock_aws

from workers.queue_client import QUEUE_PRICE_INGESTION, SQSClient


@pytest.mark.asyncio
async def test_send_message_round_trip():
    with mock_aws():
        client = SQSClient(endpoint_url=None, region="us-east-1")
        await client.create_queue(QUEUE_PRICE_INGESTION)

        msg_id = await client.send_message(
            QUEUE_PRICE_INGESTION, {"x": 1, "y": "hello"}
        )
        assert msg_id

        received = await client.receive_messages(
            QUEUE_PRICE_INGESTION, wait_seconds=0
        )
        assert len(received) == 1
        assert received[0]["body"] == {"x": 1, "y": "hello"}
        assert received[0]["receipt_handle"]


@pytest.mark.asyncio
async def test_receive_messages_empty_queue_returns_empty_list():
    with mock_aws():
        client = SQSClient(endpoint_url=None, region="us-east-1")
        await client.create_queue(QUEUE_PRICE_INGESTION)

        received = await client.receive_messages(
            QUEUE_PRICE_INGESTION, wait_seconds=0
        )
        assert received == []


@pytest.mark.asyncio
async def test_delete_message_removes_from_queue():
    with mock_aws():
        client = SQSClient(endpoint_url=None, region="us-east-1")
        await client.create_queue(QUEUE_PRICE_INGESTION)

        await client.send_message(QUEUE_PRICE_INGESTION, {"hello": "world"})

        received = await client.receive_messages(
            QUEUE_PRICE_INGESTION, wait_seconds=0
        )
        assert len(received) == 1

        await client.delete_message(
            QUEUE_PRICE_INGESTION, received[0]["receipt_handle"]
        )

        # Fresh receive after visibility timeout — moto honors the
        # delete immediately.
        again = await client.receive_messages(
            QUEUE_PRICE_INGESTION, wait_seconds=0
        )
        assert again == []


@pytest.mark.asyncio
async def test_get_queue_url_caches_after_first_resolution():
    with mock_aws():
        client = SQSClient(endpoint_url=None, region="us-east-1")
        await client.create_queue(QUEUE_PRICE_INGESTION)

        # Patch the underlying boto3 method so we can count calls.
        call_count = 0
        original = client._client.get_queue_url

        def _counting(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return original(*args, **kwargs)

        # Wipe the cache populated by create_queue so we can actually
        # observe the first lookup.
        client._url_cache.clear()
        client._client.get_queue_url = _counting

        url1 = client.get_queue_url(QUEUE_PRICE_INGESTION)
        url2 = client.get_queue_url(QUEUE_PRICE_INGESTION)

        assert url1 == url2
        assert call_count == 1  # cache hit on the second call
