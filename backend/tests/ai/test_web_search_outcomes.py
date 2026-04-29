"""Tests for vendor-migrate-1-L1 — Serper resolve outcome telemetry.

These cover the four-bucket counter that ``resolve_via_serper`` writes
to Redis on every code path. Ops uses the counter to answer "what % of
resolves fall back to grounded?" without grepping logs — see
``ai/web_search.py:_SERPER_OUTCOME_KEY``.

We mock both ``_serper_fetch`` and ``gemini_generate`` to drive each
arm of the function, plus ``aioredis.from_url`` so we can assert the
exact bucket name without spinning up a real Redis. Each test bypasses
the autouse ``_serper_synthesis_disabled`` fixture by calling
``resolve_via_serper`` directly (the autouse only patches the import
site in ``m1_product.service``).
"""

from unittest.mock import AsyncMock, patch

import pytest


pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_redis_client():
    """Patch ``aioredis.from_url`` in web_search to return a mock client.

    We only assert which bucket got incremented — moto/fakeredis would
    work but adds setup overhead without changing what's being tested.
    Returns the mock client so the test can interrogate ``hincrby``.
    """
    client = AsyncMock()
    client.aclose = AsyncMock()
    with patch("ai.web_search.aioredis.from_url", return_value=client):
        yield client


async def test_resolve_via_serper_records_success_bucket_on_happy_path(
    mock_redis_client,
):
    from ai.web_search import resolve_via_serper

    organic = [{"title": "Apple iPad Air", "snippet": "M4 chip"}]
    synthesis_json = (
        '{"device_name": "Apple iPad Air 13-inch (M4) Wi-Fi 128GB", '
        '"model": "MV2C3LL/A", "chip": "M4", "display_size_in": 13}'
    )
    with (
        patch(
            "ai.web_search._serper_fetch",
            new_callable=AsyncMock,
            return_value=organic,
        ),
        patch(
            "ai.web_search.gemini_generate",
            new_callable=AsyncMock,
            return_value=synthesis_json,
        ),
    ):
        result = await resolve_via_serper("195950797817")

    assert result is not None
    assert result["name"] == "Apple iPad Air 13-inch (M4) Wi-Fi 128GB"
    mock_redis_client.hincrby.assert_awaited_once_with(
        "metrics:serper_resolve:outcomes", "success", 1
    )


async def test_resolve_via_serper_records_serper_miss_bucket_on_zero_results(
    mock_redis_client,
):
    """When Serper returns no organic results, the function bails before
    Gemini synthesis and increments ``serper_miss``. Caller falls back
    to grounded Gemini.
    """
    from ai.web_search import resolve_via_serper

    with patch(
        "ai.web_search._serper_fetch",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await resolve_via_serper("000000000000")

    assert result is None
    mock_redis_client.hincrby.assert_awaited_once_with(
        "metrics:serper_resolve:outcomes", "serper_miss", 1
    )


async def test_resolve_via_serper_records_synthesis_null_when_gemini_returns_null(
    mock_redis_client,
):
    """When Gemini synthesis runs but can't identify the product (null
    device_name), the bucket is ``synthesis_null`` — distinct from
    ``serper_miss`` because Serper DID return snippets, the model just
    couldn't make sense of them. Useful for ops to distinguish "Serper
    coverage gap" from "obscure SKU".
    """
    from ai.web_search import resolve_via_serper

    organic = [{"title": "ambiguous SERP hit", "snippet": "vague"}]
    null_synthesis = '{"device_name": null, "model": null}'
    with (
        patch(
            "ai.web_search._serper_fetch",
            new_callable=AsyncMock,
            return_value=organic,
        ),
        patch(
            "ai.web_search.gemini_generate",
            new_callable=AsyncMock,
            return_value=null_synthesis,
        ),
    ):
        result = await resolve_via_serper("123456789012")

    assert result is None
    mock_redis_client.hincrby.assert_awaited_once_with(
        "metrics:serper_resolve:outcomes", "synthesis_null", 1
    )


async def test_resolve_via_serper_records_synthesis_error_when_gemini_raises(
    mock_redis_client,
):
    """When Gemini synthesis raises (network, quota, etc.), the bucket
    is ``synthesis_error``. Caller still falls back to grounded Gemini.
    """
    from ai.web_search import resolve_via_serper

    organic = [{"title": "real product", "snippet": "real snippet"}]
    with (
        patch(
            "ai.web_search._serper_fetch",
            new_callable=AsyncMock,
            return_value=organic,
        ),
        patch(
            "ai.web_search.gemini_generate",
            new_callable=AsyncMock,
            side_effect=Exception("network glitch"),
        ),
    ):
        result = await resolve_via_serper("123456789012")

    assert result is None
    mock_redis_client.hincrby.assert_awaited_once_with(
        "metrics:serper_resolve:outcomes", "synthesis_error", 1
    )


async def test_resolve_via_serper_soft_fails_when_redis_write_raises():
    """The counter write must never block the resolve hot path. If
    Redis is unreachable / OOM / bombs out, the function still returns
    its normal result (or None) without propagating the error.
    """
    from ai.web_search import resolve_via_serper

    organic = [{"title": "real product", "snippet": "snippet"}]
    synthesis = '{"device_name": "Real Product", "model": null}'

    busted = AsyncMock()
    busted.hincrby.side_effect = Exception("redis down")
    busted.aclose = AsyncMock()

    with (
        patch("ai.web_search.aioredis.from_url", return_value=busted),
        patch(
            "ai.web_search._serper_fetch",
            new_callable=AsyncMock,
            return_value=organic,
        ),
        patch(
            "ai.web_search.gemini_generate",
            new_callable=AsyncMock,
            return_value=synthesis,
        ),
    ):
        result = await resolve_via_serper("123456789012")

    # The whole point: Redis blew up but we still got the product.
    assert result is not None
    assert result["name"] == "Real Product"
