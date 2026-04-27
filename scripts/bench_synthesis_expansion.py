#!/usr/bin/env python3
"""Broader-category recall expansion for bench/vendor-migrate-1.

Mini-grid winner (current prompt + thinking_budget=0 + max_output_tokens=1024)
was selected against 3 UPCs (Xbox + 2 AirPods). This expansion validates the
recall claim across 10 broader-category UPCs (3 non-Apple audio, 3 gaming,
1 phone, 1 wearable, 1 kitchen, 1 tool) before swapping production.

10 UPCs × 5 runs = 50 calls. Single config (the winner). ~$0.05, ~5 min.

If recall holds (≥9/10 cases at ≥4/5 runs), proceed with production wire-up
in m1_product/service.py.

Run:
    python3 scripts/bench_synthesis_expansion.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# Reuse helpers from the mini-grid script (env loader, Serper client, Gemini
# call, JSON parser, percentile). All public-ish symbols are stable.
from bench_synthesis_grid import (  # noqa: E402
    PROMPT_CURRENT,
    SerperClient,
    _percentile,
    format_snippets,
    matches,
    synth_call,
)

RESULTS_DIR = ROOT / "scripts" / "bench_results"
RUNS_PER_CASE = 5
WINNING_BUDGET = 0  # no thinking
WINNING_MAX_TOKENS = 1024  # already fixed in synth_call via MAX_OUTPUT_TOKENS

EXPANSION_CASES = [
    # ── Non-Apple audio ────────────────────────────────────────────────
    {
        "label": "jbl_flip_6",
        "upc": "848061073966",
        "expected_brand": "JBL",
        "expected_name_contains": ["Flip 6"],
        "category": "audio",
    },
    {
        "label": "bose_qc45",
        "upc": "017817841634",
        "expected_brand": "Bose",
        "expected_name_contains": ["QuietComfort", "QC45"],
        "category": "audio",
    },
    {
        "label": "sonos_era_100",
        "upc": "878269009993",
        "expected_brand": "Sonos",
        "expected_name_contains": ["Era 100"],
        "category": "audio",
    },
    # ── Gaming consoles + accessories (non-Xbox-Series-X) ──────────────
    {
        "label": "ps5_slim",
        "upc": "711719577331",
        "expected_brand": "Sony",
        "expected_name_contains": ["PS5", "PlayStation 5"],
        "category": "console",
    },
    {
        "label": "switch_oled",
        "upc": "045496883843",
        "expected_brand": "Nintendo",
        "expected_name_contains": ["Switch", "OLED"],
        "category": "console",
    },
    {
        "label": "dualsense_ps5",
        "upc": "711719541073",
        "expected_brand": "Sony",
        "expected_name_contains": ["DualSense"],
        "category": "console",
    },
    # ── Phone ──────────────────────────────────────────────────────────
    {
        "label": "galaxy_s24_ultra",
        "upc": "887276752815",
        "expected_brand": "Samsung",
        "expected_name_contains": ["Galaxy S24"],
        "category": "phone",
    },
    # ── Wearable ───────────────────────────────────────────────────────
    {
        "label": "apple_watch_s9",
        "upc": "195949013690",
        "expected_brand": "Apple",
        "expected_name_contains": ["Apple Watch"],
        "category": "wearable",
    },
    # ── Kitchen ────────────────────────────────────────────────────────
    {
        "label": "kitchenaid_artisan",
        "upc": "883049010113",
        "expected_brand": "KitchenAid",
        "expected_name_contains": ["Artisan", "Stand Mixer"],
        "category": "kitchen",
    },
    # ── Tool ───────────────────────────────────────────────────────────
    {
        "label": "dewalt_dcd800b",
        "upc": "885911685320",
        "expected_brand": "DEWALT",
        "expected_name_contains": ["DCD800", "20V"],
        "category": "tool",
    },
]


async def expansion():
    serper = SerperClient()
    rows = []
    started_at = datetime.now(timezone.utc).isoformat()
    total = len(EXPANSION_CASES) * RUNS_PER_CASE

    print(
        f"\n[expansion] {len(EXPANSION_CASES)} UPCs × {RUNS_PER_CASE} runs = "
        f"{total} calls  (config: current prompt, thinking_budget=0, max=1024)\n",
        file=sys.stderr,
    )

    call_n = 0
    for case in EXPANSION_CASES:
        # 1 Serper call per UPC, reused for all runs
        organic, _kg, serper_ms = await serper.fetch(case["upc"])
        snippets = format_snippets(organic, top=5)
        organic_n = len(organic) if organic else 0
        print(
            f"[serper] {case['label']:>22} ({case['upc']}) "
            f"{serper_ms:.0f}ms organic={organic_n} ({case['category']})",
            file=sys.stderr,
        )

        for run_idx in range(1, RUNS_PER_CASE + 1):
            t_total_start = time.perf_counter()
            prompt = PROMPT_CURRENT.format(upc=case["upc"], snippets=snippets)
            result = await synth_call(prompt, thinking_budget=WINNING_BUDGET)
            total_ms = (time.perf_counter() - t_total_start) * 1000 + serper_ms
            pass_flag = matches(result, case)
            rows.append({
                "case": case["label"],
                "upc": case["upc"],
                "category": case["category"],
                "run": run_idx,
                "device_name": result["device_name"],
                "matches_expected": pass_flag,
                "gemini_latency_ms": result["latency_ms"],
                "serper_latency_ms": serper_ms,
                "total_latency_ms": total_ms,
                "error": result["error"],
                "raw_response": result["raw_response"],
            })
            call_n += 1
            tag = "PASS" if pass_flag else ("ERR" if result["error"] else "fail")
            short = (result["device_name"] or "<null>")[:48]
            print(
                f"  [{call_n:>2}/{total}] {case['label']:>22} run{run_idx}: "
                f"{tag:<4} {result['latency_ms']:>6.0f}ms (+{serper_ms:.0f}) {short}",
                file=sys.stderr,
            )

    completed_at = datetime.now(timezone.utc).isoformat()
    artifact = {
        "started_at": started_at,
        "completed_at": completed_at,
        "config": {
            "prompt": "current",
            "thinking_budget": WINNING_BUDGET,
            "max_output_tokens": WINNING_MAX_TOKENS,
        },
        "runs_per_case": RUNS_PER_CASE,
        "cases": [{"label": c["label"], "upc": c["upc"], "category": c["category"]}
                  for c in EXPANSION_CASES],
        "results": rows,
    }
    safe_ts = completed_at.replace(":", "-").replace("+", "_")
    out_path = RESULTS_DIR / f"synthesis_expansion_{safe_ts}.json"
    out_path.write_text(json.dumps(artifact, indent=2))
    print(f"\n[artifact] {out_path}", file=sys.stderr)

    print_summary(rows)


def print_summary(rows):
    print()
    print("=" * 80)
    print("\n=== PER-CASE RECALL (5 runs each) ===")
    print(
        f"  {'case':>22} {'category':>12}   "
        f"{'pass':>5}   {'gemini_p50':>10} {'total_p50':>10}"
    )

    case_stats = {}
    for r in rows:
        case_stats.setdefault(r["case"], []).append(r)

    perfect = 0
    near_perfect = 0  # ≥4/5
    full_fail = 0
    for case_label, crows in case_stats.items():
        hits = sum(1 for r in crows if r["matches_expected"])
        cat = crows[0]["category"]
        gemini_lat = [r["gemini_latency_ms"] for r in crows if r["error"] is None]
        total_lat = [r["total_latency_ms"] for r in crows if r["error"] is None]
        gp50 = _percentile(gemini_lat, 50) if gemini_lat else 0
        tp50 = _percentile(total_lat, 50) if total_lat else 0
        marker = ""
        if hits == 5:
            perfect += 1
            marker = "  ✓"
        elif hits >= 4:
            near_perfect += 1
            marker = "  ~"
        elif hits == 0:
            full_fail += 1
            marker = "  ✗"
        else:
            marker = "  ?"
        print(
            f"  {case_label:>22} {cat:>12}   "
            f"{hits}/5   {gp50:>9.0f}ms {tp50:>9.0f}ms{marker}"
        )

    # Aggregate latency across the full expansion
    print()
    print("=== AGGREGATE LATENCY (Gemini-only, all successful runs) ===")
    gemini_lat = [r["gemini_latency_ms"] for r in rows if r["error"] is None]
    total_lat = [r["total_latency_ms"] for r in rows if r["error"] is None]
    print(f"  Gemini p50:     {_percentile(gemini_lat, 50):.0f} ms")
    print(f"  Gemini p90:     {_percentile(gemini_lat, 90):.0f} ms")
    print(f"  Gemini p99:     {_percentile(gemini_lat, 99):.0f} ms")
    print()
    print("=== AGGREGATE LATENCY (full E pipeline = Serper + Gemini) ===")
    print(f"  Total p50:      {_percentile(total_lat, 50):.0f} ms")
    print(f"  Total p90:      {_percentile(total_lat, 90):.0f} ms")
    print(f"  Total p99:      {_percentile(total_lat, 99):.0f} ms")

    # Verdict
    print()
    print("=" * 80)
    n_cases = len(case_stats)
    overall_recall = sum(
        sum(1 for r in crows if r["matches_expected"])
        for crows in case_stats.values()
    )
    print(
        f"\n=== EXPANSION VERDICT: "
        f"{perfect}/{n_cases} perfect (5/5)  "
        f"{near_perfect}/{n_cases} near-perfect (≥4/5)  "
        f"{full_fail}/{n_cases} total fail  "
        f"recall {overall_recall}/{n_cases * 5} ({100*overall_recall/(n_cases*5):.1f}%) ==="
    )
    if perfect == n_cases:
        print("  → SHIP. Recall holds at perfect across all categories.")
    elif perfect + near_perfect == n_cases:
        print("  → SHIP with caveat (near-perfect on some). Fallback-to-B catches edge cases.")
    elif full_fail == 0:
        print("  → MIXED. Recall partially holds. Inspect raw_response for failed cases.")
    else:
        print(f"  → INVESTIGATE {full_fail} category fail(s) before shipping.")


if __name__ == "__main__":
    asyncio.run(expansion())
