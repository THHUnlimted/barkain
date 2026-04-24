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
    """Only 5 of 9 retailers respond → below 7-threshold, exit 1."""
    partial = demo_check.ACTIVE_RETAILERS[:5]
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
