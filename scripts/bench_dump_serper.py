#!/usr/bin/env python3
"""Dump raw Serper output for the failing UPCs so a human can inspect what
the SERP looks like and decide whether the failure is (a) UPC reuse, (b)
top-5 truncation, (c) genuine non-coverage, or (d) something fixable.

10 calls (~$0.01). Output: stdout + JSON artifact at
``scripts/bench_results/serper_inspection_<UTC>.json``.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
if ENV_PATH.exists():
    for raw_line in ENV_PATH.read_text().splitlines():
        s = raw_line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, _, v = s.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

sys.path.insert(0, str(ROOT / "scripts"))

from _bench_serper import SerperClient  # noqa: E402

RESULTS_DIR = ROOT / "scripts" / "bench_results"

CASES = [
    {"label": "jbl_flip_6",         "upc": "848061073966", "expected": "JBL Flip 6"},
    {"label": "bose_qc45",          "upc": "017817841634", "expected": "Bose QuietComfort 45"},
    {"label": "sonos_era_100",      "upc": "878269009993", "expected": "Sonos Era 100"},
    {"label": "ps5_slim",           "upc": "711719577331", "expected": "Sony PS5 Slim"},
    {"label": "switch_oled",        "upc": "045496883843", "expected": "Nintendo Switch OLED"},
    {"label": "dualsense_ps5",      "upc": "711719541073", "expected": "Sony DualSense PS5 Controller"},
    {"label": "galaxy_s24_ultra",   "upc": "887276752815", "expected": "Samsung Galaxy S24 Ultra"},
    {"label": "apple_watch_s9",     "upc": "195949013690", "expected": "Apple Watch Series 9 41mm"},
    {"label": "kitchenaid_artisan", "upc": "883049010113", "expected": "KitchenAid Artisan stand mixer"},
    {"label": "dewalt_dcd800b",     "upc": "885911685320", "expected": "DeWalt DCD800B 20V drill"},
]


async def main():
    serper = SerperClient()
    dump = []
    for case in CASES:
        organic, kg, latency_ms = await serper.fetch(case["upc"], num=10)
        dump.append({
            "label": case["label"],
            "upc": case["upc"],
            "expected": case["expected"],
            "latency_ms": latency_ms,
            "organic_count": len(organic) if organic else 0,
            "knowledgeGraph": kg,
            "organic_top5": [
                {
                    "title": (h.get("title") or "").strip(),
                    "snippet": (h.get("snippet") or "").strip(),
                    "link": (h.get("link") or "").strip(),
                }
                for h in (organic or [])[:5]
            ],
        })

    print()
    print("=" * 110)
    for d in dump:
        kg_present = "YES" if d["knowledgeGraph"] else "no"
        kg_title = (d["knowledgeGraph"] or {}).get("title", "")
        print(f"\n=== {d['label']} (UPC {d['upc']}) — expected: {d['expected']} ===")
        print(f"  organic_count={d['organic_count']}  KG={kg_present}  kg_title={kg_title!r}")
        for i, hit in enumerate(d["organic_top5"], 1):
            print(f"\n  [{i}] {hit['title']}")
            snippet = hit["snippet"][:200]
            print(f"      {snippet}")
            print(f"      → {hit['link']}")

    completed = datetime.now(timezone.utc).isoformat()
    safe_ts = completed.replace(":", "-").replace("+", "_")
    out_path = RESULTS_DIR / f"serper_inspection_{safe_ts}.json"
    out_path.write_text(json.dumps({"completed_at": completed, "cases": dump}, indent=2))
    print(f"\n[artifact] {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
