"""Tests for workers.queue_client.SQSClient.

Uses ``moto`` 5.x (``mock_aws`` context) so the tests are hermetic —
no running LocalStack container needed in CI.
"""

import json

import pytest
from moto import mock_aws

from workers.queue_client import (
    DLQ_MAX_RECEIVE_COUNT,
    QUEUE_PRICE_INGESTION,
    SQSClient,
    dlq_name,
)


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


# 2h-ops: SQS DLQ wiring


@pytest.mark.asyncio
async def test_create_queue_with_dlq_creates_both_and_wires_redrive():
    """create_queue_with_dlq must create the main queue, the sibling DLQ,
    and apply a RedrivePolicy on the main queue pointing at the DLQ ARN.
    """
    with mock_aws():
        client = SQSClient(endpoint_url=None, region="us-east-1")

        main_url, dlq_url = await client.create_queue_with_dlq(
            QUEUE_PRICE_INGESTION
        )

        assert main_url
        assert dlq_url
        assert main_url != dlq_url
        assert dlq_url.endswith(dlq_name(QUEUE_PRICE_INGESTION))

        # RedrivePolicy must be present on the main queue and reference
        # the DLQ's ARN with the configured maxReceiveCount.
        attrs = client._client.get_queue_attributes(
            QueueUrl=main_url, AttributeNames=["RedrivePolicy"]
        )["Attributes"]
        policy = json.loads(attrs["RedrivePolicy"])
        dlq_arn = await client.get_queue_arn(dlq_name(QUEUE_PRICE_INGESTION))
        assert policy["deadLetterTargetArn"] == dlq_arn
        assert int(policy["maxReceiveCount"]) == DLQ_MAX_RECEIVE_COUNT


@pytest.mark.asyncio
async def test_create_queue_with_dlq_is_idempotent():
    """Re-running setup-queues must not error and must keep the redrive
    policy in place — operators tweak DLQ_MAX_RECEIVE_COUNT and re-run.
    """
    with mock_aws():
        client = SQSClient(endpoint_url=None, region="us-east-1")

        main_url_1, dlq_url_1 = await client.create_queue_with_dlq(
            QUEUE_PRICE_INGESTION
        )
        main_url_2, dlq_url_2 = await client.create_queue_with_dlq(
            QUEUE_PRICE_INGESTION, max_receive_count=5
        )

        assert main_url_1 == main_url_2
        assert dlq_url_1 == dlq_url_2

        attrs = client._client.get_queue_attributes(
            QueueUrl=main_url_2, AttributeNames=["RedrivePolicy"]
        )["Attributes"]
        policy = json.loads(attrs["RedrivePolicy"])
        # Second call's max_receive_count overrides the first.
        assert int(policy["maxReceiveCount"]) == 5


@pytest.mark.asyncio
async def test_get_queue_arn_returns_canonical_arn():
    with mock_aws():
        client = SQSClient(endpoint_url=None, region="us-east-1")
        await client.create_queue(QUEUE_PRICE_INGESTION)

        arn = await client.get_queue_arn(QUEUE_PRICE_INGESTION)

        # moto formats ARNs as `arn:aws:sqs:<region>:<account>:<name>`.
        assert arn.startswith("arn:aws:sqs:us-east-1:")
        assert arn.endswith(f":{QUEUE_PRICE_INGESTION}")
