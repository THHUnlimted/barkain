"""Private Serper SERP client for the vendor-comparison bench.

Used only by ``scripts/bench_vendor_compare.py``. Leading underscore
signals: do not import from ``backend/``. If the bench's MIGRATE
recommendation lands, the SHIPPED version goes in
``backend/ai/web_search.py`` — don't promote this file directly.

One method: ``fetch(upc)`` returns a tuple of
``(organic_snippets | None, kg_block | None, latency_ms)``. Soft-fails
to ``(None, None, latency_ms)`` on any HTTP / network error so the
bench loop never crashes on a single bad call.
"""

from __future__ import annotations

import os
import time

import httpx

SERPER_URL = "https://google.serper.dev/search"
DEFAULT_TIMEOUT_SEC = 10
DEFAULT_NUM_RESULTS = 10


class SerperClient:
    """Thin async wrapper around the Serper /search endpoint."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        timeout_sec: float = DEFAULT_TIMEOUT_SEC,
    ):
        self.api_key = api_key or os.environ.get("SERPER_API_KEY", "")
        if not self.api_key:
            raise RuntimeError(
                "SERPER_API_KEY not set in environment. "
                "Add it to .env (see .env.example)."
            )
        self.timeout_sec = timeout_sec

    async def fetch(
        self, upc: str, *, num: int = DEFAULT_NUM_RESULTS
    ) -> tuple[list[dict] | None, dict | None, float]:
        """Issue one Serper /search call. Returns (organic, kg, latency_ms).

        Soft-fails to (None, None, latency_ms) on any error. The bench
        is responsible for logging the failure envelope — we only
        return what we got.
        """
        body = {"q": f"UPC {upc}", "num": num}
        headers = {"X-API-KEY": self.api_key, "Content-Type": "application/json"}
        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.timeout_sec) as client:
                resp = await client.post(SERPER_URL, json=body, headers=headers)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            if resp.status_code != 200:
                return None, None, elapsed_ms
            data = resp.json()
            return (
                data.get("organic"),
                data.get("knowledgeGraph"),
                elapsed_ms,
            )
        except (httpx.HTTPError, ValueError, KeyError):
            elapsed_ms = (time.perf_counter() - t0) * 1000
            return None, None, elapsed_ms


def format_snippets(organic: list[dict] | None, *, top: int = 5) -> str:
    """Render the top-N organic results as a compact text block.

    Used by ``E_serper_then_D`` to feed Gemini a constrained context.
    Title + snippet only — link is dropped to keep the prompt short.
    """
    if not organic:
        return "(no results)"
    lines = []
    for i, hit in enumerate(organic[:top], start=1):
        title = (hit.get("title") or "").strip()
        snippet = (hit.get("snippet") or "").strip()
        lines.append(f"{i}. {title}\n   {snippet}")
    return "\n".join(lines)
