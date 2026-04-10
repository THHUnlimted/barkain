"""Tests for Watchdog supervisor agent."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.m2_prices.schemas import (
    ContainerError,
    ContainerListing,
    ContainerMetadata,
    ContainerResponse,
)
from workers.watchdog import WatchdogSupervisor


def _make_success_response(retailer_id: str = "amazon") -> ContainerResponse:
    return ContainerResponse(
        retailer_id=retailer_id,
        query="Sony WH-1000XM5",
        extraction_time_ms=1500,
        listings=[
            ContainerListing(
                title="Sony WH-1000XM5",
                price=299.99,
                url="https://example.com/product",
            )
        ],
        metadata=ContainerMetadata(
            url="https://example.com",
            extracted_at="2026-04-09T00:00:00Z",
        ),
    )


def _make_error_response(
    retailer_id: str = "amazon",
    error_code: str = "TIMEOUT",
    error_message: str = "Timed out",
    bot_detected: bool = False,
) -> ContainerResponse:
    return ContainerResponse(
        retailer_id=retailer_id,
        query="Sony WH-1000XM5",
        extraction_time_ms=60000,
        listings=[],
        metadata=ContainerMetadata(
            url="",
            extracted_at="2026-04-09T00:00:00Z",
            bot_detected=bot_detected,
        ),
        error=ContainerError(code=error_code, message=error_message),
    )


# MARK: - Classification


@pytest.mark.asyncio
async def test_classify_success(db_session, fake_redis):
    """Given valid listings, classify as success."""
    watchdog = WatchdogSupervisor(db=db_session, redis=fake_redis, dry_run=True)
    response = _make_success_response()
    assert watchdog._classify(response) == "success"


@pytest.mark.asyncio
async def test_classify_transient_timeout(db_session, fake_redis):
    """Given a TIMEOUT error, classify as transient."""
    watchdog = WatchdogSupervisor(db=db_session, redis=fake_redis, dry_run=True)
    response = _make_error_response(error_code="TIMEOUT")
    assert watchdog._classify(response) == "transient"


@pytest.mark.asyncio
async def test_classify_transient_connection_failed(db_session, fake_redis):
    """Given a CONNECTION_FAILED error, classify as transient."""
    watchdog = WatchdogSupervisor(db=db_session, redis=fake_redis, dry_run=True)
    response = _make_error_response(error_code="CONNECTION_FAILED")
    assert watchdog._classify(response) == "transient"


@pytest.mark.asyncio
async def test_classify_selector_drift(db_session, fake_redis):
    """Given a PARSE_ERROR, classify as selector_drift."""
    watchdog = WatchdogSupervisor(db=db_session, redis=fake_redis, dry_run=True)
    response = _make_error_response(error_code="PARSE_ERROR")
    assert watchdog._classify(response) == "selector_drift"


@pytest.mark.asyncio
async def test_classify_blocked(db_session, fake_redis):
    """Given bot_detected=True, classify as blocked."""
    watchdog = WatchdogSupervisor(db=db_session, redis=fake_redis, dry_run=True)
    response = _make_error_response(bot_detected=True)
    assert watchdog._classify(response) == "blocked"


@pytest.mark.asyncio
async def test_classify_empty_listings_no_error(db_session, fake_redis):
    """Given empty listings with no error, classify as selector_drift."""
    watchdog = WatchdogSupervisor(db=db_session, redis=fake_redis, dry_run=True)
    response = ContainerResponse(
        retailer_id="amazon",
        query="test",
        extraction_time_ms=1000,
        listings=[],
        metadata=ContainerMetadata(url="", extracted_at="2026-04-09T00:00:00Z"),
    )
    assert watchdog._classify(response) == "selector_drift"


# MARK: - Actions


@pytest.mark.asyncio
async def test_check_retailer_success_dry_run(db_session, fake_redis):
    """Given a successful extraction in dry_run, return success without DB writes."""
    mock_client = MagicMock()
    mock_client.extract = AsyncMock(return_value=_make_success_response())

    watchdog = WatchdogSupervisor(
        db=db_session, redis=fake_redis, container_client=mock_client, dry_run=True,
    )
    result = await watchdog.check_retailer("amazon")
    assert result["diagnosis"] == "success"
    assert result["action"] == "none"
    assert result["success"] is True


@pytest.mark.asyncio
async def test_selector_drift_dry_run_would_heal(db_session, fake_redis):
    """Given selector_drift in dry_run, report would_heal without actually healing."""
    mock_client = MagicMock()
    mock_client.extract = AsyncMock(
        return_value=_make_error_response(error_code="PARSE_ERROR"),
    )

    watchdog = WatchdogSupervisor(
        db=db_session, redis=fake_redis, container_client=mock_client, dry_run=True,
    )
    result = await watchdog.check_retailer("amazon")
    assert result["diagnosis"] == "selector_drift"
    assert result["action"] == "would_heal"
