"""demo-prep-1 Item 4 — pre-demo retailer health sweep.

Runs end-to-end against the dev backend to answer "is this thing ready for
F&F in 2 minutes?" — hits /health, resolves an evergreen UPC, opens the
SSE price stream, tallies which retailers responded within a 15s budget,
prints a table, exits 0 when ≥7 of 9 retailers succeed.

NOT for production — the live production backend sits behind Clerk auth
and a Lambda cron writes `retailer_health`. This script is the local pre-
demo sanity check Mike runs from the project root via ``make demo-check``.

Evergreen UPCs (module-level constant): pick items every retailer carries
to minimize per-retailer noise. Tune the list in place during demo week
if any one UPC stops being useful.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from dataclasses import dataclass
from typing import Iterable

import httpx

# Module-level constants — tunable without a PR if demo week surfaces a
# better UPC. Picked for breadth of retailer coverage (Amazon, Walmart,
# Target, Best Buy, Home Depot all stock AirPods / printer cartridges /
# command strips).
DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"
EVERGREEN_UPC = "190198451736"  # AirPods — stocked at all demo-critical retailers
STREAM_BUDGET_S = 15.0
SUCCESS_THRESHOLD_RETAILERS = 7  # of 9 active retailers
ACTIVE_RETAILERS = [
    "amazon",
    "best_buy",
    "walmart",
    "target",
    "home_depot",
    "ebay_new",
    "ebay_used",
    "backmarket",
    "fb_marketplace",
]


@dataclass
class RetailerCheckRow:
    retailer_id: str
    status: str  # "success" / "no_match" / "unavailable" / "timeout"
    response_time_ms: int | None
    note: str


async def _check_backend_health(client: httpx.AsyncClient, base_url: str) -> tuple[bool, str]:
    """Hit /api/v1/health. Returns ``(ok, message)``."""
    try:
        resp = await client.get(f"{base_url}/api/v1/health", timeout=5.0)
    except httpx.RequestError as exc:
        return False, f"connection failed: {exc}"
    if resp.status_code != 200:
        return False, f"status {resp.status_code}"
    body = resp.json()
    status = body.get("status", "unknown")
    return status == "healthy", f"status={status} db={body.get('database')} redis={body.get('redis')}"


async def _resolve_upc(client: httpx.AsyncClient, base_url: str, upc: str) -> str | None:
    """Resolve a UPC to a product_id. Returns ``None`` on failure (caller
    surfaces the reason in the printed table)."""
    try:
        resp = await client.post(
            f"{base_url}/api/v1/products/resolve",
            json={"upc": upc},
            timeout=30.0,
        )
    except httpx.RequestError:
        return None
    if resp.status_code != 200:
        return None
    return resp.json().get("id")


async def _collect_stream_results(
    client: httpx.AsyncClient, base_url: str, product_id: str, budget_s: float
) -> dict[str, RetailerCheckRow]:
    """Open the SSE price stream for a product and collect per-retailer
    rows until the budget is spent or the stream closes.

    Times out individual retailers against the budget rather than tracking
    per-retailer wall time — "respond within 15s" in the package spec is
    about the ceremony, not scientific accuracy.
    """
    rows: dict[str, RetailerCheckRow] = {}
    started = time.monotonic()
    url = f"{base_url}/api/v1/prices/{product_id}/stream"

    try:
        async with client.stream("GET", url, timeout=budget_s + 2) as resp:
            if resp.status_code != 200:
                for rid in ACTIVE_RETAILERS:
                    rows[rid] = RetailerCheckRow(
                        retailer_id=rid,
                        status="unavailable",
                        response_time_ms=None,
                        note=f"stream returned {resp.status_code}",
                    )
                return rows

            async for line in resp.aiter_lines():
                if time.monotonic() - started > budget_s:
                    break
                if not line.startswith("data:"):
                    continue
                try:
                    payload = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                rid = payload.get("retailer_id")
                if not rid:
                    continue
                elapsed_ms = int((time.monotonic() - started) * 1000)
                rows[rid] = RetailerCheckRow(
                    retailer_id=rid,
                    status=payload.get("status", "unknown"),
                    response_time_ms=elapsed_ms,
                    note=payload.get("note") or "",
                )
    except httpx.RequestError as exc:
        for rid in ACTIVE_RETAILERS:
            rows.setdefault(
                rid,
                RetailerCheckRow(
                    retailer_id=rid,
                    status="unavailable",
                    response_time_ms=None,
                    note=f"stream error: {exc}",
                ),
            )

    # Any retailer that didn't emit within the budget → timeout.
    for rid in ACTIVE_RETAILERS:
        rows.setdefault(
            rid,
            RetailerCheckRow(
                retailer_id=rid,
                status="timeout",
                response_time_ms=None,
                note=f"no event within {int(budget_s)}s",
            ),
        )
    return rows


def _render_table(rows: Iterable[RetailerCheckRow]) -> str:
    header = f"{'retailer':<16}  {'status':<12}  {'time':>8}  note"
    sep = "-" * 60
    lines = [header, sep]
    for row in rows:
        time_str = f"{row.response_time_ms}ms" if row.response_time_ms is not None else "—"
        note = row.note[:40] if row.note else ""
        lines.append(f"{row.retailer_id:<16}  {row.status:<12}  {time_str:>8}  {note}")
    return "\n".join(lines)


async def run_demo_check(base_url: str = DEFAULT_BACKEND_URL, upc: str = EVERGREEN_UPC) -> int:
    """Main entry point. Returns the exit code (0 = healthy, 1 = hard-down).

    Exposed as an async function so the +1 backend integration test can
    exercise the control-flow with mocked endpoints.
    """
    async with httpx.AsyncClient() as client:
        healthy, health_note = await _check_backend_health(client, base_url)
        print(f"Backend /health: {'OK' if healthy else 'FAIL'} — {health_note}")
        if not healthy:
            return 1

        product_id = await _resolve_upc(client, base_url, upc)
        if not product_id:
            print(f"Could not resolve evergreen UPC {upc} — backend can't see upstreams.")
            return 1

        rows = await _collect_stream_results(client, base_url, product_id, STREAM_BUDGET_S)

    ordered_rows = [rows[rid] for rid in ACTIVE_RETAILERS]
    print()
    print(_render_table(ordered_rows))
    print()

    succeeded = sum(1 for row in ordered_rows if row.status == "success")
    print(f"Summary: {succeeded}/{len(ACTIVE_RETAILERS)} retailers responded with prices.")
    if succeeded >= SUCCESS_THRESHOLD_RETAILERS:
        print("Status: OK — ready for demo.")
        return 0
    print(f"Status: DEGRADED — need ≥{SUCCESS_THRESHOLD_RETAILERS} healthy retailers.")
    return 1


def main() -> int:
    return asyncio.run(run_demo_check())


if __name__ == "__main__":
    sys.exit(main())
