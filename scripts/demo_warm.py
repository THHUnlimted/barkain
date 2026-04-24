"""demo-prep-1 Item 5 — pre-warm the caches before F&F arrives.

Runs a configurable UPC list through the full scan flow
(resolve → prices stream → identity → cards → recommend) so by the time
F&F tap the app:
  * Redis has products, prices, identity, card-recs, and portal-CTAs
    cached for every warmup UPC.
  * The PG connection pool is warm (no cold-start latency tax on the
    first live scan).
  * Gemini's prompt cache has been touched for the repeated system
    instruction — subsequent UPC lookups against the same prompt
    land on a cache hit.

The UPC list lives in ``scripts/demo_warm_upcs.txt`` (operational —
.gitignored so Mike can tune in-situ without a PR). One UPC per line;
blank lines + `#`-prefixed comments ignored. If the file is missing we
fall back to the same evergreen UPC demo_check uses, keeping the
command idempotent on a fresh checkout.
"""

from __future__ import annotations

import asyncio
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"
DEFAULT_WARM_UPCS_PATH = Path(__file__).resolve().parent / "demo_warm_upcs.txt"
FALLBACK_UPCS = ["190198451736"]  # AirPods — same as demo_check
PER_UPC_BUDGET_S = 30.0


@dataclass
class WarmRow:
    upc: str
    ok: bool
    elapsed_s: float
    note: str


def load_warm_upcs(path: Path = DEFAULT_WARM_UPCS_PATH) -> list[str]:
    """Read a UPC list from disk. Returns the fallback when the file
    doesn't exist — demo-warm should never hard-fail just because Mike
    hasn't curated the list yet."""
    if not path.exists():
        return list(FALLBACK_UPCS)
    upcs: list[str] = []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        upcs.append(line)
    return upcs or list(FALLBACK_UPCS)


async def _warm_one(
    client: httpx.AsyncClient,
    base_url: str,
    upc: str,
    budget_s: float = PER_UPC_BUDGET_S,
) -> WarmRow:
    started = time.monotonic()
    try:
        resolve = await client.post(
            f"{base_url}/api/v1/products/resolve",
            json={"upc": upc},
            timeout=budget_s,
        )
    except httpx.RequestError as exc:
        return WarmRow(upc=upc, ok=False, elapsed_s=time.monotonic() - started, note=f"resolve error: {exc}")
    if resolve.status_code != 200:
        return WarmRow(
            upc=upc,
            ok=False,
            elapsed_s=time.monotonic() - started,
            note=f"resolve {resolve.status_code}",
        )
    product_id = resolve.json().get("id")
    if not product_id:
        return WarmRow(upc=upc, ok=False, elapsed_s=time.monotonic() - started, note="no product_id")

    # Open + drain the stream to warm the per-retailer caches. We don't
    # care about individual retailer outcomes — just that the endpoints
    # touched their upstream caches.
    try:
        async with client.stream(
            "GET",
            f"{base_url}/api/v1/prices/{product_id}/stream",
            timeout=budget_s,
        ) as resp:
            async for _ in resp.aiter_lines():
                pass
    except httpx.RequestError as exc:
        return WarmRow(upc=upc, ok=False, elapsed_s=time.monotonic() - started, note=f"stream error: {exc}")

    # Fire identity + cards + recommend in parallel; their caches are
    # keyed off the product, so settling all three is cheap once the
    # prices payload is warm.
    try:
        await asyncio.gather(
            client.get(f"{base_url}/api/v1/identity/discounts", params={"product_id": product_id}, timeout=budget_s),
            client.get(f"{base_url}/api/v1/cards/recommendations", params={"product_id": product_id}, timeout=budget_s),
            client.post(f"{base_url}/api/v1/recommend", json={"product_id": product_id, "force_refresh": False}, timeout=budget_s),
            return_exceptions=True,
        )
    except httpx.RequestError as exc:
        return WarmRow(upc=upc, ok=False, elapsed_s=time.monotonic() - started, note=f"gather error: {exc}")

    return WarmRow(upc=upc, ok=True, elapsed_s=time.monotonic() - started, note="warmed")


async def run_demo_warm(
    base_url: str = DEFAULT_BACKEND_URL,
    upcs: list[str] | None = None,
) -> int:
    """Main entry point. Returns exit code (0 clean, 1 any hard-fail)."""
    upcs = upcs or load_warm_upcs()
    print(f"Warming {len(upcs)} UPCs against {base_url}...")
    async with httpx.AsyncClient() as client:
        rows = await asyncio.gather(*[_warm_one(client, base_url, upc) for upc in upcs])

    total_elapsed = sum(row.elapsed_s for row in rows)
    succeeded = sum(1 for row in rows if row.ok)
    avg_elapsed = total_elapsed / max(len(rows), 1)

    print()
    for row in rows:
        status = "OK" if row.ok else "FAIL"
        print(f"  {status:<4}  {row.upc:<14}  {row.elapsed_s:>5.1f}s  {row.note}")
    print()
    print(f"Summary: {succeeded}/{len(rows)} warmed, avg {avg_elapsed:.1f}s.")
    return 0 if succeeded == len(rows) else 1


def main() -> int:
    return asyncio.run(run_demo_warm())


if __name__ == "__main__":
    sys.exit(main())
