"""demo-prep-1 Item 4 — smoke coverage for scripts/demo_check.py.

Mocks httpx so the control flow can be exercised without a running
backend. Not exhaustive — the script is a thin orchestration layer over
real endpoints, so the value here is catching exit-code regressions and
table-rendering breakage when the script is touched in a pinch.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# scripts/ sits at the repo root, sibling to backend/. Add it explicitly
# so the test can import the module without a package layout.
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts import demo_check  # noqa: E402


def _make_health_response(status_code: int = 200, body: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body or {"status": "healthy", "database": "healthy", "redis": "healthy"}
    return resp


def _make_resolve_response(status_code: int = 200, product_id: str = "abc-123") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = {"id": product_id}
    return resp


class _FakeStream:
    """async context manager that yields ``aiter_lines()`` frames."""

    def __init__(self, status_code: int, lines: list[str]):
        self.status_code = status_code
        self._lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def aiter_lines(self):
        for line in self._lines:
            yield line


def _make_success_stream_lines(retailers: list[str]) -> list[str]:
    """One ``data:`` frame per retailer, marked ``status=success``."""
    return [
        f'data: {{"retailer_id": "{rid}", "status": "success"}}'
        for rid in retailers
    ]


@pytest.mark.asyncio
async def test_run_demo_check_returns_0_when_all_healthy(monkeypatch):
    """Healthy backend + 9 retailers succeed within budget → exit 0."""
    stream_lines = _make_success_stream_lines(demo_check.ACTIVE_RETAILERS)
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.get = AsyncMock(return_value=_make_health_response())
    client.post = AsyncMock(return_value=_make_resolve_response())
    client.stream = MagicMock(return_value=_FakeStream(200, stream_lines))

    with patch.object(demo_check.httpx, "AsyncClient", return_value=client):
        exit_code = await demo_check.run_demo_check(base_url="http://127.0.0.1:8000")

    assert exit_code == 0


@pytest.mark.asyncio
async def test_run_demo_check_returns_1_when_backend_unhealthy(monkeypatch):
    """Backend /health returns non-healthy status → exit 1, never touches resolve."""
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.get = AsyncMock(
        return_value=_make_health_response(body={"status": "degraded", "database": "unhealthy", "redis": "healthy"})
    )
    client.post = AsyncMock()
    client.stream = MagicMock()

    with patch.object(demo_check.httpx, "AsyncClient", return_value=client):
        exit_code = await demo_check.run_demo_check(base_url="http://127.0.0.1:8000")

    assert exit_code == 1
    # resolve never called — short-circuit on health failure.
    assert client.post.call_count == 0


@pytest.mark.asyncio
async def test_run_demo_check_returns_1_when_below_threshold(monkeypatch):
    """Only 4 of 9 retailers respond → below 5-threshold, exit 1."""
    partial = demo_check.ACTIVE_RETAILERS[:4]
    stream_lines = _make_success_stream_lines(partial)
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.get = AsyncMock(return_value=_make_health_response())
    client.post = AsyncMock(return_value=_make_resolve_response())
    client.stream = MagicMock(return_value=_FakeStream(200, stream_lines))

    with patch.object(demo_check.httpx, "AsyncClient", return_value=client):
        exit_code = await demo_check.run_demo_check(base_url="http://127.0.0.1:8000")

    assert exit_code == 1


# --- Pre-Fix C (savings-math-prominence) ---------------------------------
#
# 10× sim runs on 2026-04-24 (`/tmp/barkain-sim-run/summary.log`) showed
# stable `success=4 unavailable=4 no_match=1 exit=2` — Redis replay (run
# 1 5s, runs 2-10 0-1s) and the structural local 4/9 cap (target /
# home_depot / backmarket / fb_marketplace are EC2-only). Pre-Fix C wires
# `--no-cache` and `--remote-containers=ec2` to address both.


@pytest.mark.asyncio
async def test_no_cache_flag_appends_force_refresh_to_sse_url(monkeypatch):
    """`--no-cache` should append `?force_refresh=true` to the SSE call."""
    stream_lines = _make_success_stream_lines(demo_check.ACTIVE_RETAILERS)
    captured_urls: list[str] = []

    def stream_factory(method, url, **_kwargs):
        captured_urls.append(url)
        return _FakeStream(200, stream_lines)

    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.get = AsyncMock(return_value=_make_health_response())
    client.post = AsyncMock(return_value=_make_resolve_response())
    client.stream = MagicMock(side_effect=stream_factory)

    with patch.object(demo_check.httpx, "AsyncClient", return_value=client):
        await demo_check.run_demo_check(
            base_url="http://127.0.0.1:8000", no_cache=True
        )

    assert any("force_refresh=true" in url for url in captured_urls), (
        f"expected ?force_refresh=true in SSE URL, got {captured_urls!r}"
    )


def test_resolve_ec2_container_urls_fails_loudly_when_env_unset(monkeypatch):
    """No EC2 env vars → RuntimeError with operator-friendly guidance.

    Whole point of `--remote-containers=ec2` is to NOT silently fall back
    to localhost — the flag exists because localhost can't see the
    container scrapers (they live on EC2 only).
    """
    for key in ("EC2_CONTAINER_BASE_URL",) + tuple(
        f"{r.upper()}_CONTAINER_URL" for r in demo_check.EC2_ONLY_RETAILERS
    ):
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(RuntimeError) as excinfo:
        demo_check._resolve_ec2_container_urls()

    msg = str(excinfo.value)
    assert "EC2_CONTAINER_BASE_URL" in msg
    # Names of the EC2-only retailers should appear so the operator can
    # see exactly which env vars they need to set.
    for rid in demo_check.EC2_ONLY_RETAILERS:
        assert rid.upper() in msg


def test_resolve_ec2_container_urls_uses_base_url_with_port_mapping(monkeypatch):
    """Single `EC2_CONTAINER_BASE_URL` expands to `{base}:{port}` per retailer."""
    monkeypatch.setenv("EC2_CONTAINER_BASE_URL", "http://54.197.27.219")
    for rid in demo_check.EC2_ONLY_RETAILERS:
        monkeypatch.delenv(f"{rid.upper()}_CONTAINER_URL", raising=False)

    urls = demo_check._resolve_ec2_container_urls()

    assert urls == {
        "target": "http://54.197.27.219:8084",
        "home_depot": "http://54.197.27.219:8085",
        "backmarket": "http://54.197.27.219:8090",
        "fb_marketplace": "http://54.197.27.219:8091",
    }


def test_resolve_ec2_container_urls_per_retailer_override_wins(monkeypatch):
    """`{RETAILER}_CONTAINER_URL` takes precedence over the umbrella base URL."""
    monkeypatch.setenv("EC2_CONTAINER_BASE_URL", "http://54.197.27.219")
    monkeypatch.setenv("TARGET_CONTAINER_URL", "http://overridden:9999")
    for rid in demo_check.EC2_ONLY_RETAILERS:
        if rid != "target":
            monkeypatch.delenv(f"{rid.upper()}_CONTAINER_URL", raising=False)

    urls = demo_check._resolve_ec2_container_urls()

    assert urls["target"] == "http://overridden:9999"
    assert urls["home_depot"] == "http://54.197.27.219:8085"
