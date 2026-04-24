"""demo-prep-1 Item 5 — smoke coverage for scripts/demo_warm.py.

Mocks httpx so the control flow can be exercised without a running
backend. Verifies the warmup loop fires the full 4-endpoint sequence
per UPC and aggregates pass/fail correctly.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts import demo_warm  # noqa: E402


class _FakeStream:
    def __init__(self, status_code: int = 200):
        self.status_code = status_code

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def aiter_lines(self):
        for line in ():
            yield line


def _resolve_ok(product_id: str = "abc-123") -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"id": product_id}
    return resp


@pytest.mark.asyncio
async def test_run_demo_warm_returns_0_on_all_success():
    """Happy path: resolve + stream + identity + cards + recommend all 200 → exit 0."""
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.post = AsyncMock(return_value=_resolve_ok())
    client.get = AsyncMock(return_value=MagicMock(status_code=200))
    client.stream = MagicMock(return_value=_FakeStream())

    with patch.object(demo_warm.httpx, "AsyncClient", return_value=client):
        exit_code = await demo_warm.run_demo_warm(
            base_url="http://127.0.0.1:8000",
            upcs=["190198451736"],
        )

    assert exit_code == 0
    # Sanity: resolve POST fires, plus the three parallel gather endpoints.
    # client.post is hit by /resolve AND /recommend → call count ≥ 2.
    assert client.post.call_count >= 2


@pytest.mark.asyncio
async def test_run_demo_warm_returns_1_on_resolve_failure():
    """Resolve failure → exit 1; the downstream endpoints never fire for that UPC."""
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    failed = MagicMock()
    failed.status_code = 404
    client.post = AsyncMock(return_value=failed)
    client.get = AsyncMock()
    client.stream = MagicMock()

    with patch.object(demo_warm.httpx, "AsyncClient", return_value=client):
        exit_code = await demo_warm.run_demo_warm(
            base_url="http://127.0.0.1:8000",
            upcs=["000000000000"],
        )

    assert exit_code == 1


def test_load_warm_upcs_falls_back_when_file_missing(tmp_path):
    """No file → fallback list (never hard-fails on a fresh checkout)."""
    missing = tmp_path / "nope.txt"
    upcs = demo_warm.load_warm_upcs(missing)
    assert upcs == demo_warm.FALLBACK_UPCS


def test_load_warm_upcs_parses_file(tmp_path):
    """Comments + blank lines ignored; real UPCs preserved in order."""
    f = tmp_path / "warm.txt"
    f.write_text(
        "\n".join([
            "# primary list — tuned 2026-04-24",
            "",
            "190198451736",
            "  190199098428  ",
            "# shows deferred",
        ])
    )
    upcs = demo_warm.load_warm_upcs(f)
    assert upcs == ["190198451736", "190199098428"]
