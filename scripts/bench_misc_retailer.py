#!/usr/bin/env python3
"""Bench harness for the Step 3n misc-retailer slot.

Iterates a 50-SKU pet-vertical panel through `_serper_shopping_fetch`,
filters with `is_known_retailer`, and emits per-SKU + aggregate JSON. Used
to gate the canary flag-flip (≥80 % SKU pass) and the weekly Z-build
threshold alert (<75 % for 2 consecutive weekly runs).

Bypasses Redis cache by calling the helper directly — every run hits
Serper. Cost: 50 SKUs × 2 credits/call = 100 credits per run = $0.10 at
Starter pricing ($50 / 50K credits).

Usage:

  PYTHONPATH=backend python3 scripts/bench_misc_retailer.py \\
      --panel scripts/bench_data/misc_retailer_panel_v1.json \\
      --out scripts/bench_results/misc_retailer_$(date -u +%Y%m%dT%H%M%SZ).json

Pass criteria:
  - SKU passes when ≥3 misc retailers come through the filter.
  - Panel passes when ≥80 % of SKUs pass.
  - Standby alert when <75 % for 2 consecutive weekly runs.

Exit codes:
  - 0  → panel pass (≥80 %)
  - 2  → panel below pass threshold but still above alert threshold
  - 3  → panel below alert threshold (<75 %)
  - 1  → fatal error (no panel, no API key, etc.)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

# Allow running with or without PYTHONPATH=backend.
_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from ai.web_search import _serper_shopping_fetch  # noqa: E402
from modules.m14_misc_retailer.service import is_known_retailer  # noqa: E402
from modules.m14_misc_retailer.adapters.serper_shopping import (  # noqa: E402
    _normalize_source,
)

PASS_THRESHOLD = 0.80
ALERT_THRESHOLD = 0.75
MIN_MISC_PER_SKU = 3


async def _bench_one(query: str) -> dict[str, Any]:
    t0 = time.perf_counter()
    items = await _serper_shopping_fetch(query)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    if items is None:
        return {
            "sku": query,
            "error": "serper_returned_none",
            "items": 0,
            "unique_retailers": 0,
            "misc_retailers": 0,
            "misc_pct": 0.0,
            "latency_ms": round(elapsed_ms, 1),
        }

    sources = [_normalize_source(item.get("source", "")) for item in items]
    sources = [s for s in sources if s]
    unique_retailers = sorted(set(sources))
    misc_sources = [s for s in unique_retailers if not is_known_retailer(s)]

    return {
        "sku": query,
        "items": len(items),
        "unique_retailers": len(unique_retailers),
        "misc_retailers": len(misc_sources),
        "misc_pct": round(
            (len(misc_sources) / len(unique_retailers) * 100) if unique_retailers else 0.0,
            1,
        ),
        "misc_sources_sample": misc_sources[:8],
        "latency_ms": round(elapsed_ms, 1),
    }


async def _bench_panel(panel: dict[str, Any]) -> dict[str, Any]:
    queries: list[str] = panel.get("queries", [])
    if not queries:
        raise SystemExit("Panel has no queries — check the JSON file.")

    rows: list[dict[str, Any]] = []
    for query in queries:
        row = await _bench_one(query)
        rows.append(row)
        # Polite to Serper — they default to 25 req/s but the bench is
        # not a load test. Sleep a beat between calls so back-to-back
        # local runs don't trip the rate limit.
        await asyncio.sleep(0.05)

    pass_count = sum(1 for r in rows if r.get("misc_retailers", 0) >= MIN_MISC_PER_SKU)
    pass_pct = round(pass_count / len(rows) * 100, 1) if rows else 0.0
    latencies = [r["latency_ms"] for r in rows if "latency_ms" in r]
    p50 = round(statistics.median(latencies), 1) if latencies else 0.0
    p95 = (
        round(statistics.quantiles(latencies, n=20)[-1], 1) if len(latencies) >= 20 else None
    )

    aggregate = {
        "panel_id": panel.get("panel_id"),
        "panel_size": len(rows),
        "pass_count": pass_count,
        "pass_pct": pass_pct,
        "min_misc_per_sku": MIN_MISC_PER_SKU,
        "pass_threshold_pct": PASS_THRESHOLD * 100,
        "alert_threshold_pct": ALERT_THRESHOLD * 100,
        "panel_passes": pass_pct >= PASS_THRESHOLD * 100,
        "panel_below_alert": pass_pct < ALERT_THRESHOLD * 100,
        "p50_latency_ms": p50,
        "p95_latency_ms": p95,
        "total_serper_credits_estimate": len(rows) * 2,
    }
    return {"per_sku": rows, "aggregate": aggregate}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--panel",
        default=str(_HERE / "bench_data" / "misc_retailer_panel_v1.json"),
        help="Path to the panel JSON file (default: misc_retailer_panel_v1.json).",
    )
    parser.add_argument(
        "--out",
        default="-",
        help="Where to write the bench JSON (default: stdout).",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Smoke mode — run only the first 3 queries. Used by tests.",
    )
    args = parser.parse_args()

    panel_path = Path(args.panel)
    if not panel_path.exists():
        print(f"error: panel file not found: {panel_path}", file=sys.stderr)
        return 1
    panel = json.loads(panel_path.read_text())

    if args.smoke:
        panel = {**panel, "queries": panel.get("queries", [])[:3]}

    if not os.environ.get("SERPER_API_KEY"):
        print(
            "error: SERPER_API_KEY not set. Export it (see .env) before running the bench.",
            file=sys.stderr,
        )
        return 1

    result = asyncio.run(_bench_panel(panel))
    serialized = json.dumps(result, indent=2)
    if args.out == "-":
        print(serialized)
    else:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(serialized + "\n")
        print(f"Wrote {out_path}", file=sys.stderr)

    aggregate = result["aggregate"]
    if aggregate["panel_below_alert"]:
        return 3
    if not aggregate["panel_passes"]:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
