"""demo-prep-1 Item 4 + savings-math-prominence Pre-Fix C — pre-demo health sweep.

Runs end-to-end against the dev backend to answer "is this thing ready for
F&F in 2 minutes?" — hits /health, resolves an evergreen UPC, opens the
SSE price stream, tallies which retailers responded within a 15s budget,
prints a table, exits 0 when ≥5 of 9 retailers respond with prices.

NOT for production — the live production backend sits behind Clerk auth
and a Lambda cron writes `retailer_health`. This script is the local pre-
demo sanity check Mike runs from the project root via ``make demo-check``.

Evergreen UPC (module-level constant): MacBook Air M1 was the broadest-
coverage SKU in the 2026-04-25 sim sweep (6/9 success — Best Buy, eBay
new + used, Amazon, Walmart, Facebook Marketplace; Target / Home Depot /
Back Market correctly return ``no_match`` because they do not stock
laptops). Threshold 5 leaves room for fb_marketplace's high-variance
~30s tail latency to occasionally fall outside the 15s budget without
flagging the platform as degraded. Tune in place during demo week if a
better SKU surfaces.

Pre-Fix C (savings-math-prominence) flags
-----------------------------------------
``--no-cache``
    Append ``?force_refresh=true`` to the SSE call so the M2 service
    bypasses Redis. The 10× sim-drive runs (2026-04-24) showed run 1
    elapsed ~5s and runs 2-10 elapsed 0-1s because Redis replayed the
    cache. ``--no-cache`` forces a real fanout every time.
``--remote-containers=ec2``
    Pre-flight ``/health`` against each EC2-only container retailer
    (target, home_depot, backmarket, fb_marketplace — ports 8084 / 8085
    / 8090 / 8091). Reads ``EC2_CONTAINER_BASE_URL`` (or per-retailer
    ``{RETAILER}_CONTAINER_URL`` overrides). Fails loud if env is unset
    — does NOT silently fall back to localhost. Used at T-2 to confirm
    the EC2 scraper stack is alive before kicking the demo off.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Iterable

import httpx

# Module-level constants — tunable without a PR if demo week surfaces a
# better SKU. The threshold of 5/9 is calibrated against catalog reality:
# Home Depot doesn't stock consumer electronics, Back Market only carries
# refurbished phones/laptops, so any single SKU realistically tops out at
# 6-8 of 9. Setting the bar at 5 catches "Decodo creds rotated" or "eBay
# API key expired" without false-flagging the structural catalog gap.
DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"
EVERGREEN_UPC = "194252056639"  # MacBook Air M1 — broadest catalog coverage in 2026-04 sweep
STREAM_BUDGET_S = 15.0
SUCCESS_THRESHOLD_RETAILERS = 5  # of 9 active retailers
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

# Retailers whose price path runs in a per-retailer scraper container on
# EC2. The FastAPI backend dispatches via CONTAINER_URL_PATTERN (config.py)
# so locally these are unreachable unless the developer also runs the
# containers — which nobody does. Pre-flight via --remote-containers=ec2.
EC2_ONLY_RETAILERS = {
    "target": 8084,
    "home_depot": 8085,
    "backmarket": 8090,
    "fb_marketplace": 8091,
}


@dataclass
class RetailerCheckRow:
    retailer_id: str
    status: str  # "success" / "no_match" / "unavailable" / "timeout"
    response_time_ms: int | None
    note: str


def _resolve_ec2_container_urls() -> dict[str, str]:
    """Return ``{retailer_id: base_url}`` for the EC2-only retailers.

    Per-retailer ``{RETAILER}_CONTAINER_URL`` env vars take precedence
    over the umbrella ``EC2_CONTAINER_BASE_URL``. Missing env raises
    ``RuntimeError`` with operator-friendly guidance — do NOT fall back
    to localhost (that defeats the flag's whole purpose).
    """
    base_url = os.environ.get("EC2_CONTAINER_BASE_URL", "").rstrip("/")
    resolved: dict[str, str] = {}
    missing: list[str] = []
    for rid, port in EC2_ONLY_RETAILERS.items():
        env_key = f"{rid.upper()}_CONTAINER_URL"
        per_retailer = os.environ.get(env_key, "").rstrip("/")
        if per_retailer:
            resolved[rid] = per_retailer
        elif base_url:
            resolved[rid] = f"{base_url}:{port}"
        else:
            missing.append(rid)
    if missing:
        raise RuntimeError(
            "--remote-containers=ec2 needs container URLs in env. Set\n"
            "  EC2_CONTAINER_BASE_URL=http://54.197.27.219\n"
            "or per-retailer overrides ("
            + ", ".join(f"{r.upper()}_CONTAINER_URL" for r in missing)
            + "). See CLAUDE.md § Production Infra (EC2)."
        )
    return resolved


async def _preflight_ec2_containers(
    client: httpx.AsyncClient, urls: dict[str, str]
) -> list[tuple[str, bool, str]]:
    """``GET {url}/health`` per EC2 container. Returns ``[(rid, ok, note)]``.

    Doesn't gate the SSE call (the SSE stream is the truth source) — the
    pre-flight just surfaces "EC2 stack is dead" before the developer
    waits 15s for an SSE that was never going to succeed.
    """
    async def _one(rid: str, base: str) -> tuple[str, bool, str]:
        try:
            resp = await client.get(f"{base}/health", timeout=5.0)
        except httpx.RequestError as exc:
            return rid, False, f"connection failed: {exc.__class__.__name__}"
        if resp.status_code != 200:
            return rid, False, f"status {resp.status_code}"
        return rid, True, "OK"

    return await asyncio.gather(*(_one(rid, base) for rid, base in urls.items()))


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
    client: httpx.AsyncClient,
    base_url: str,
    product_id: str,
    budget_s: float,
    no_cache: bool = False,
) -> dict[str, RetailerCheckRow]:
    """Open the SSE price stream for a product and collect per-retailer
    rows until the budget is spent or the stream closes.

    Times out individual retailers against the budget rather than tracking
    per-retailer wall time — "respond within 15s" in the package spec is
    about the ceremony, not scientific accuracy.

    ``no_cache=True`` appends ``?force_refresh=true`` so the M2 service
    bypasses Redis (router.py:39 already wires this query param to
    ``PriceAggregationService.get_prices_streaming(force_refresh=...)``).
    """
    rows: dict[str, RetailerCheckRow] = {}
    started = time.monotonic()
    url = f"{base_url}/api/v1/prices/{product_id}/stream"
    if no_cache:
        url += "?force_refresh=true"

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


async def run_demo_check(
    base_url: str = DEFAULT_BACKEND_URL,
    upc: str = EVERGREEN_UPC,
    no_cache: bool = False,
    remote_containers: str | None = None,
) -> int:
    """Main entry point. Returns the exit code (0 = healthy, 1 = hard-down).

    Exposed as an async function so the +3 backend integration tests can
    exercise the control-flow with mocked endpoints.

    ``remote_containers`` accepts ``"ec2"`` (only supported value today).
    When set, pre-flights each EC2-only container's ``/health`` and aborts
    early with a loud message if any are unreachable — saves the developer
    from waiting 15s for an SSE that was never going to succeed.
    """
    async with httpx.AsyncClient() as client:
        if remote_containers == "ec2":
            try:
                ec2_urls = _resolve_ec2_container_urls()
            except RuntimeError as exc:
                print(f"--remote-containers=ec2: {exc}")
                return 1
            print(f"Pre-flight EC2 containers ({len(ec2_urls)}):")
            results = await _preflight_ec2_containers(client, ec2_urls)
            any_down = False
            for rid, ok, note in results:
                marker = "OK" if ok else "DOWN"
                print(f"  {rid:<16} {marker:<6} {note}")
                if not ok:
                    any_down = True
            if any_down:
                print(
                    "EC2 container preflight failed — check `ssh ... 'docker ps'` per "
                    "CLAUDE.md § Production Infra. Aborting before SSE call."
                )
                return 1
            print()

        healthy, health_note = await _check_backend_health(client, base_url)
        print(f"Backend /health: {'OK' if healthy else 'FAIL'} — {health_note}")
        if not healthy:
            return 1

        product_id = await _resolve_upc(client, base_url, upc)
        if not product_id:
            print(f"Could not resolve evergreen UPC {upc} — backend can't see upstreams.")
            return 1

        rows = await _collect_stream_results(
            client, base_url, product_id, STREAM_BUDGET_S, no_cache=no_cache
        )

    ordered_rows = [rows[rid] for rid in ACTIVE_RETAILERS]
    print()
    print(_render_table(ordered_rows))
    print()

    succeeded = sum(1 for row in ordered_rows if row.status == "success")
    print(f"Summary: {succeeded}/{len(ACTIVE_RETAILERS)} retailers responded with prices.")
    if no_cache:
        print("(--no-cache: SSE issued ?force_refresh=true; cache replay bypassed.)")
    if succeeded >= SUCCESS_THRESHOLD_RETAILERS:
        print("Status: OK — ready for demo.")
        return 0
    print(f"Status: DEGRADED — need ≥{SUCCESS_THRESHOLD_RETAILERS} healthy retailers.")
    return 1


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pre-demo retailer health sweep.")
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Bypass Redis cache by appending ?force_refresh=true to the SSE call.",
    )
    parser.add_argument(
        "--remote-containers",
        choices=("ec2",),
        default=None,
        help="Pre-flight EC2 container /health endpoints. Requires EC2_CONTAINER_BASE_URL "
        "or per-retailer {RETAILER}_CONTAINER_URL env vars.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    return asyncio.run(
        run_demo_check(
            no_cache=args.no_cache,
            remote_containers=args.remote_containers,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
