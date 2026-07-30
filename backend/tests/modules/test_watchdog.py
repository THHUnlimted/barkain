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


# MARK: - Heal-path page HTML (2i-d-L4)


def _fake_httpx_client(
    *,
    html: str = "",
    raises: Exception | None = None,
    captured: dict | None = None,
):
    """Stand-in for httpx.AsyncClient that records how it was called."""

    class _Response:
        def __init__(self, text: str) -> None:
            self.text = text

        def raise_for_status(self) -> None:
            return None

    class _Client:
        def __init__(self, **kwargs) -> None:
            if captured is not None:
                captured.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def get(self, url, headers=None):
            if captured is not None:
                captured["url"] = url
                captured["headers"] = headers
            if raises is not None:
                raise raises
            return _Response(html)

    return _Client


@pytest.mark.asyncio
async def test_fetch_page_html_returns_live_markup(db_session, fake_redis, monkeypatch):
    """The heal path fetches the retailer's real search page."""
    from workers import watchdog as watchdog_module

    captured: dict = {}
    monkeypatch.setattr(
        watchdog_module.httpx,
        "AsyncClient",
        _fake_httpx_client(html="<html><div data-test='x'>hi</div></html>", captured=captured),
    )

    supervisor = WatchdogSupervisor(db=db_session, redis=fake_redis)
    html = await supervisor._fetch_page_html(
        "target", '{"search_url_template": "https://www.target.com/s?searchTerm="}'
    )

    assert "data-test='x'" in html
    # Query is appended and URL-encoded — the default WATCHDOG_TEST_QUERY has a space.
    assert captured["url"].startswith("https://www.target.com/s?searchTerm=")
    assert " " not in captured["url"]
    assert "User-Agent" in captured["headers"]


@pytest.mark.asyncio
async def test_fetch_page_html_supports_placeholder_template(
    db_session, fake_redis, monkeypatch
):
    """A `{query}` placeholder is substituted rather than appended."""
    from workers import watchdog as watchdog_module

    captured: dict = {}
    monkeypatch.setattr(
        watchdog_module.httpx, "AsyncClient", _fake_httpx_client(html="<html/>", captured=captured)
    )
    monkeypatch.setattr(watchdog_module.settings, "WATCHDOG_TEST_QUERY", "widget")

    supervisor = WatchdogSupervisor(db=db_session, redis=fake_redis)
    await supervisor._fetch_page_html(
        "acme", '{"search_url_template": "https://acme.test/{query}/results"}'
    )

    assert captured["url"] == "https://acme.test/widget/results"


@pytest.mark.asyncio
async def test_fetch_page_html_marker_when_template_missing(db_session, fake_redis):
    """No search_url_template yields an explicit marker, not a crash."""
    supervisor = WatchdogSupervisor(db=db_session, redis=fake_redis)
    html = await supervisor._fetch_page_html("acme", "{}")

    assert "PAGE HTML UNAVAILABLE" in html
    assert "no search_url_template" in html


@pytest.mark.asyncio
async def test_fetch_page_html_marker_on_fetch_failure(db_session, fake_redis, monkeypatch):
    """A network failure degrades to the marker — heal must never crash on it."""
    from workers import watchdog as watchdog_module

    monkeypatch.setattr(
        watchdog_module.httpx,
        "AsyncClient",
        _fake_httpx_client(raises=RuntimeError("connection reset")),
    )

    supervisor = WatchdogSupervisor(db=db_session, redis=fake_redis)
    html = await supervisor._fetch_page_html(
        "target", '{"search_url_template": "https://www.target.com/s?searchTerm="}'
    )

    assert "PAGE HTML UNAVAILABLE" in html
    assert "connection reset" in html
    assert "Do NOT invent" in html


@pytest.mark.asyncio
async def test_fetch_page_html_tolerates_malformed_config(db_session, fake_redis):
    """Unparseable config.json degrades to the marker rather than raising."""
    supervisor = WatchdogSupervisor(db=db_session, redis=fake_redis)
    html = await supervisor._fetch_page_html("acme", "{not json")

    assert "PAGE HTML UNAVAILABLE" in html


@pytest.mark.asyncio
async def test_heal_prompt_gets_page_html_not_error_details(
    db_session, fake_redis, monkeypatch, tmp_path
):
    """Regression for 2i-d-L4.

    The heal prompt used to receive `page_html=error_details`, so Opus was asked
    to rewrite CSS selectors with no page markup at all. Pin that the two slots
    now carry different content and that page_html holds real markup.
    """
    from workers import watchdog as watchdog_module

    container_dir = tmp_path / "target"
    container_dir.mkdir()
    (container_dir / "extract.js").write_text("// stale selectors")
    (container_dir / "config.json").write_text(
        '{"search_url_template": "https://www.target.com/s?searchTerm="}'
    )
    monkeypatch.setattr(watchdog_module, "CONTAINERS_ROOT", tmp_path)

    monkeypatch.setattr(
        watchdog_module.httpx,
        "AsyncClient",
        _fake_httpx_client(html="<html><div class='new-selector'>Sony</div></html>"),
    )

    prompt_kwargs: dict = {}

    def _capture_prompt(**kwargs):
        prompt_kwargs.update(kwargs)
        return "PROMPT"

    monkeypatch.setattr(watchdog_module, "build_watchdog_heal_prompt", _capture_prompt)

    async def _fake_generate(*args, **kwargs):
        return {"extract_js": "// healed", "changes": ["x"], "confidence": 0.9}, 100

    monkeypatch.setattr(watchdog_module, "claude_generate_json_with_usage", _fake_generate)

    async def _noop(self, *args, **kwargs):
        return None

    monkeypatch.setattr(WatchdogSupervisor, "_get_health_record", _noop)
    monkeypatch.setattr(WatchdogSupervisor, "_update_health_status", _noop)
    monkeypatch.setattr(WatchdogSupervisor, "_increment_heal_attempts", _noop)

    supervisor = WatchdogSupervisor(db=db_session, redis=fake_redis)
    result = await supervisor._handle_selector_drift(
        "target", _make_error_response("target", error_code="PARSE_ERROR")
    )

    assert result["action"] == "heal_staged"
    assert "new-selector" in prompt_kwargs["page_html"]
    # The exact shape of the original bug: the two slots were the same string.
    assert prompt_kwargs["page_html"] != prompt_kwargs["error_details"]
    assert "PARSE_ERROR" in prompt_kwargs["error_details"]
