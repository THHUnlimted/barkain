"""Tests for the Serper Shopping helper (Step 3n / M14 misc-retailer).

Pins `_serper_shopping_fetch` posture: thumbnail stripping, soft-fail to
None on missing key / non-200 / network error / malformed JSON, and
empty-`shopping`-list returning `[]` (distinct from None — the caller
treats `[]` as "Serper answered, no results" while None means "we
couldn't talk to Serper at all").
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


def _mock_async_client(response: MagicMock | None, *, raises: Exception | None = None):
    """Build an httpx.AsyncClient context-manager mock."""
    mock_client = MagicMock()
    if raises is not None:
        mock_client.post = AsyncMock(side_effect=raises)
    else:
        mock_client.post = AsyncMock(return_value=response)
    mock_async_ctx = MagicMock()
    mock_async_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_async_ctx.__aexit__ = AsyncMock(return_value=None)
    return mock_async_ctx


# MARK: - Happy path


@pytest.mark.asyncio
async def test_serper_shopping_strips_image_url():
    """Every item returned must have `imageUrl` removed before hitting the
    Redis cache. Sidesteps the SerpApi-DMCA copyrighted-image angle and
    keeps the cache payload small (~800 KB → ~18 KB observed in v3 bench).
    """
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json = MagicMock(return_value={
        "shopping": [
            {
                "title": "Royal Canin Adult Maintenance",
                "source": "Chewy",
                "link": "https://www.google.com/shopping/product/x",
                "price": "$84.99",
                "imageUrl": "https://thumbnail.serper.dev/abc==",
                "position": 1,
            },
            {
                "title": "Royal Canin",
                "source": "Petco",
                "link": "https://www.google.com/shopping/product/y",
                "price": "$92.49",
                "imageUrl": "data:image/jpeg;base64,/9j/...",
                "position": 2,
            },
        ]
    })

    with patch(
        "ai.web_search.httpx.AsyncClient",
        return_value=_mock_async_client(fake_resp),
    ), patch("ai.web_search.settings") as mock_settings:
        mock_settings.SERPER_API_KEY = "test-key"
        from ai.web_search import _serper_shopping_fetch

        items = await _serper_shopping_fetch("royal canin")

    assert items is not None
    assert len(items) == 2
    for item in items:
        assert "imageUrl" not in item
    assert items[0]["title"] == "Royal Canin Adult Maintenance"
    assert items[0]["source"] == "Chewy"


# MARK: - Soft-fail paths


@pytest.mark.asyncio
async def test_serper_shopping_returns_none_when_api_key_missing(caplog):
    """No SERPER_API_KEY → soft-fail to None + warn-once."""
    import ai.web_search as ws

    # Reset the warn-once flag so the test sees the log line.
    ws._SERPER_SHOPPING_KEY_WARNED = False

    with patch("ai.web_search.settings") as mock_settings:
        mock_settings.SERPER_API_KEY = ""
        with caplog.at_level("WARNING"):
            result = await ws._serper_shopping_fetch("anything")

    assert result is None
    assert any(
        "SERPER_API_KEY not configured" in record.message
        for record in caplog.records
    )

    # Second call with key still missing should NOT re-emit the warning.
    caplog.clear()
    with patch("ai.web_search.settings") as mock_settings:
        mock_settings.SERPER_API_KEY = ""
        with caplog.at_level("WARNING"):
            second = await ws._serper_shopping_fetch("anything-else")
    assert second is None
    assert not any(
        "SERPER_API_KEY not configured" in record.message
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_serper_shopping_returns_none_on_5xx():
    fake_resp = MagicMock()
    fake_resp.status_code = 503
    fake_resp.json = MagicMock(return_value={})

    with patch(
        "ai.web_search.httpx.AsyncClient",
        return_value=_mock_async_client(fake_resp),
    ), patch("ai.web_search.settings") as mock_settings:
        mock_settings.SERPER_API_KEY = "test-key"
        from ai.web_search import _serper_shopping_fetch

        result = await _serper_shopping_fetch("anything")

    assert result is None


@pytest.mark.asyncio
async def test_serper_shopping_returns_none_on_network_error():
    with patch(
        "ai.web_search.httpx.AsyncClient",
        return_value=_mock_async_client(None, raises=httpx.ConnectError("boom")),
    ), patch("ai.web_search.settings") as mock_settings:
        mock_settings.SERPER_API_KEY = "test-key"
        from ai.web_search import _serper_shopping_fetch

        result = await _serper_shopping_fetch("anything")

    assert result is None


@pytest.mark.asyncio
async def test_serper_shopping_returns_none_on_malformed_json():
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json = MagicMock(side_effect=ValueError("not json"))

    with patch(
        "ai.web_search.httpx.AsyncClient",
        return_value=_mock_async_client(fake_resp),
    ), patch("ai.web_search.settings") as mock_settings:
        mock_settings.SERPER_API_KEY = "test-key"
        from ai.web_search import _serper_shopping_fetch

        result = await _serper_shopping_fetch("anything")

    assert result is None


@pytest.mark.asyncio
async def test_serper_shopping_returns_empty_list_when_no_shopping_field():
    """Serper answered but the response has no `shopping` key — distinct
    from a network failure. We return [] so the caller doesn't fall back."""
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json = MagicMock(return_value={"some_other_field": []})

    with patch(
        "ai.web_search.httpx.AsyncClient",
        return_value=_mock_async_client(fake_resp),
    ), patch("ai.web_search.settings") as mock_settings:
        mock_settings.SERPER_API_KEY = "test-key"
        from ai.web_search import _serper_shopping_fetch

        result = await _serper_shopping_fetch("anything")

    assert result == []


@pytest.mark.asyncio
async def test_serper_shopping_drops_non_dict_items():
    """Defensive: if Serper ever returns garbage in the list, we filter it
    out rather than letting it propagate to the adapter."""
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json = MagicMock(return_value={
        "shopping": [
            None,
            "stringy-not-a-dict",
            {"title": "Real one", "source": "Petflow", "link": "https://x", "price": "$1"},
        ]
    })

    with patch(
        "ai.web_search.httpx.AsyncClient",
        return_value=_mock_async_client(fake_resp),
    ), patch("ai.web_search.settings") as mock_settings:
        mock_settings.SERPER_API_KEY = "test-key"
        from ai.web_search import _serper_shopping_fetch

        items = await _serper_shopping_fetch("anything")

    assert items == [
        {"title": "Real one", "source": "Petflow", "link": "https://x", "price": "$1"}
    ]
