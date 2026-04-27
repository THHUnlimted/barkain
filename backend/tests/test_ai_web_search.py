"""Tests for the Serper-then-synthesis web search path.

Pins the bench/vendor-migrate-1 production wire-up: Serper SERP top-5 →
Gemini synthesis (no grounding, thinking_budget=0). Soft-fail behavior
on Serper missing/error/timeout/zero-results is critical because the
caller (m1_product/service.py:_get_gemini_data) uses None as the "fall
back to grounded" signal.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


# MARK: - resolve_via_serper happy path


@pytest.mark.asyncio
async def test_resolve_via_serper_returns_name_and_model_on_success():
    """Happy path: Serper returns organic, synthesis returns valid JSON,
    function returns ``{"name": ..., "gemini_model": ...}`` matching the
    shape ``_get_gemini_data`` callers expect."""
    organic_payload = [
        {"title": "Sonos Era 100 - Best Buy", "snippet": "Sonos Era 100 wireless smart speaker..."},
        {"title": "Sonos Era 100 - Walmart", "snippet": "Sonos Era 100 voice-controlled..."},
    ]

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json = MagicMock(return_value={"organic": organic_payload})

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=fake_resp)
    mock_async_ctx = MagicMock()
    mock_async_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_async_ctx.__aexit__ = AsyncMock(return_value=None)

    synthesis_response = (
        '{"device_name": "Sonos Era 100", "model": "E10G1US1BLK", '
        '"chip": null, "display_size_in": null}'
    )

    with patch("ai.web_search.httpx.AsyncClient", return_value=mock_async_ctx), \
         patch("ai.web_search.gemini_generate", new=AsyncMock(return_value=synthesis_response)), \
         patch("ai.web_search.settings") as mock_settings:
        mock_settings.SERPER_API_KEY = "test-key"
        from ai.web_search import resolve_via_serper

        result = await resolve_via_serper("878269009993")

    assert result == {"name": "Sonos Era 100", "gemini_model": "E10G1US1BLK"}


# MARK: - resolve_via_serper soft-fail paths


@pytest.mark.asyncio
async def test_resolve_via_serper_returns_none_when_api_key_missing():
    """No API key configured → soft-fail to None so the caller falls back.

    A misconfigured environment must not crash the request — production
    has rolled out without SERPER_API_KEY before vendor-migrate-1 and
    will roll back to that state if Mike unsets the var.
    """
    with patch("ai.web_search.settings") as mock_settings:
        mock_settings.SERPER_API_KEY = ""
        from ai.web_search import resolve_via_serper

        result = await resolve_via_serper("123456789012")

    assert result is None


@pytest.mark.asyncio
async def test_resolve_via_serper_returns_none_on_serper_http_error():
    """httpx.HTTPError during Serper fetch → soft-fail to None."""
    mock_client = MagicMock()
    mock_client.post = AsyncMock(side_effect=httpx.HTTPError("boom"))
    mock_async_ctx = MagicMock()
    mock_async_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_async_ctx.__aexit__ = AsyncMock(return_value=None)

    with patch("ai.web_search.httpx.AsyncClient", return_value=mock_async_ctx), \
         patch("ai.web_search.settings") as mock_settings:
        mock_settings.SERPER_API_KEY = "test-key"
        from ai.web_search import resolve_via_serper

        result = await resolve_via_serper("123456789012")

    assert result is None


@pytest.mark.asyncio
async def test_resolve_via_serper_returns_none_on_serper_non_200():
    """Serper returns 5xx / 429 → soft-fail to None."""
    fake_resp = MagicMock()
    fake_resp.status_code = 429

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=fake_resp)
    mock_async_ctx = MagicMock()
    mock_async_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_async_ctx.__aexit__ = AsyncMock(return_value=None)

    with patch("ai.web_search.httpx.AsyncClient", return_value=mock_async_ctx), \
         patch("ai.web_search.settings") as mock_settings:
        mock_settings.SERPER_API_KEY = "test-key"
        from ai.web_search import resolve_via_serper

        result = await resolve_via_serper("123456789012")

    assert result is None


@pytest.mark.asyncio
async def test_resolve_via_serper_returns_none_on_zero_organic():
    """Serper returns 200 but empty organic list → soft-fail to None."""
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json = MagicMock(return_value={"organic": []})

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=fake_resp)
    mock_async_ctx = MagicMock()
    mock_async_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_async_ctx.__aexit__ = AsyncMock(return_value=None)

    with patch("ai.web_search.httpx.AsyncClient", return_value=mock_async_ctx), \
         patch("ai.web_search.settings") as mock_settings:
        mock_settings.SERPER_API_KEY = "test-key"
        from ai.web_search import resolve_via_serper

        result = await resolve_via_serper("123456789012")

    assert result is None


@pytest.mark.asyncio
async def test_resolve_via_serper_returns_none_when_synthesis_returns_null():
    """Synthesis returned null device_name (model couldn't identify) →
    soft-fail to None so the caller falls back to grounded."""
    organic_payload = [
        {"title": "irrelevant", "snippet": "junk"},
    ]
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json = MagicMock(return_value={"organic": organic_payload})

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=fake_resp)
    mock_async_ctx = MagicMock()
    mock_async_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_async_ctx.__aexit__ = AsyncMock(return_value=None)

    null_response = '{"device_name": null, "model": null, "chip": null, "display_size_in": null}'

    with patch("ai.web_search.httpx.AsyncClient", return_value=mock_async_ctx), \
         patch("ai.web_search.gemini_generate", new=AsyncMock(return_value=null_response)), \
         patch("ai.web_search.settings") as mock_settings:
        mock_settings.SERPER_API_KEY = "test-key"
        from ai.web_search import resolve_via_serper

        result = await resolve_via_serper("123456789012")

    assert result is None


@pytest.mark.asyncio
async def test_resolve_via_serper_returns_none_when_gemini_raises():
    """Synthesis call raises an unexpected exception → soft-fail to None,
    caller falls back to grounded path."""
    organic_payload = [{"title": "x", "snippet": "y"}]
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json = MagicMock(return_value={"organic": organic_payload})

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=fake_resp)
    mock_async_ctx = MagicMock()
    mock_async_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_async_ctx.__aexit__ = AsyncMock(return_value=None)

    with patch("ai.web_search.httpx.AsyncClient", return_value=mock_async_ctx), \
         patch("ai.web_search.gemini_generate", new=AsyncMock(side_effect=RuntimeError("rate limited"))), \
         patch("ai.web_search.settings") as mock_settings:
        mock_settings.SERPER_API_KEY = "test-key"
        from ai.web_search import resolve_via_serper

        result = await resolve_via_serper("123456789012")

    assert result is None


# MARK: - synthesis call configuration (vendor-migrate-1 pinning)


@pytest.mark.asyncio
async def test_resolve_via_serper_calls_gemini_with_budget_zero_no_grounding():
    """Pin: synthesis call uses thinking_budget=0 + grounded=False + max=1024.

    These are the bench-winning values from vendor-migrate-1's mini-grid:
      - budget=0 (no thinking) — tighter recall than budget=256/512 on clean SERP
      - grounded=False — must use ONLY Serper snippets, not run its own search
      - max_output_tokens=1024 — gives breathing room for the JSON envelope

    Changing these requires a re-bench. The function is the load-bearing
    point — if a future PR changes the config, this test fails before any
    user notices a regression.
    """
    organic_payload = [{"title": "x", "snippet": "y"}]
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json = MagicMock(return_value={"organic": organic_payload})

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=fake_resp)
    mock_async_ctx = MagicMock()
    mock_async_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_async_ctx.__aexit__ = AsyncMock(return_value=None)

    mock_gemini = AsyncMock(return_value='{"device_name": "Test", "model": null}')
    with patch("ai.web_search.httpx.AsyncClient", return_value=mock_async_ctx), \
         patch("ai.web_search.gemini_generate", new=mock_gemini), \
         patch("ai.web_search.settings") as mock_settings:
        mock_settings.SERPER_API_KEY = "test-key"
        from ai.web_search import resolve_via_serper

        await resolve_via_serper("123456789012")

    mock_gemini.assert_called_once()
    kwargs = mock_gemini.call_args.kwargs
    assert kwargs["thinking_budget"] == 0
    assert kwargs["grounded"] is False
    assert kwargs["max_output_tokens"] == 1024


# MARK: - parse helpers


def test_parse_synthesis_json_strips_markdown_fences():
    """``_parse_synthesis_json`` strips ```json fences before parsing.

    Some Gemini responses come back wrapped in markdown code fences
    despite the "no markdown" instruction — must not crash.
    """
    from ai.web_search import _parse_synthesis_json

    raw = '```json\n{"device_name": "Apple iPad Air", "model": "M4"}\n```'
    parsed = _parse_synthesis_json(raw)
    assert parsed == {"device_name": "Apple iPad Air", "model": "M4"}


def test_parse_synthesis_json_returns_empty_dict_on_unparseable():
    """Unrecoverable garbage → return {} (no exception). The caller
    treats {} the same as null device_name and falls back."""
    from ai.web_search import _parse_synthesis_json

    assert _parse_synthesis_json("garbage } {{") == {}


def test_format_snippets_renders_top_n():
    """``_format_snippets`` produces title + snippet lines, top-N only."""
    from ai.web_search import _format_snippets

    organic = [
        {"title": "First", "snippet": "snip-1"},
        {"title": "Second", "snippet": "snip-2"},
        {"title": "Third", "snippet": "snip-3"},
    ]
    out = _format_snippets(organic, top=2)
    assert "First" in out and "snip-1" in out
    assert "Second" in out and "snip-2" in out
    assert "Third" not in out
    assert "snip-3" not in out
