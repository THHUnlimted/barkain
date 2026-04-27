#!/usr/bin/env python3
"""Head-to-head bench against Mike-verified UPCs for bench/vendor-migrate-1.

Prior expansion (bench_synthesis_expansion_grid.py) wiped out 0/250 across
all 5 mini-grid winners. Investigation showed at least 30 % of those UPCs
were wrong in our test catalog (Apple Watch S9 UPC was actually a MacBook
Pro demo unit, etc.). This script tests against a Mike-verified catalog so
we get a clean read on whether E (Serper synthesis) can ever match B
(Gemini grounded) recall.

3 configurations:
  - E_current_budget0     : cheapest mini-grid winner (current prompt, no thinking)
  - E_hardened_budget512  : defensive mini-grid winner (hardened prompt, 512 thinking)
  - B_grounded_low        : current production baseline (grounded + ThinkingLevel.LOW)

3 configs × 9 UPCs × 5 runs = 135 calls. ~$2 (B dominates cost), ~10 min.

Run:
    python3 scripts/bench_synthesis_verified.py
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

from bench_synthesis_grid import (  # noqa: E402
    PROMPT_CURRENT,
    PROMPT_HARDENED,
    SerperClient,
    _percentile,
    format_snippets,
    matches,
    synth_call,
)
from bench_vendor_compare import (  # noqa: E402
    UPC_LOOKUP_PROMPT,
    _gemini_call,
)

RESULTS_DIR = ROOT / "scripts" / "bench_results"
RUNS_PER_COMBO = 5

# 9 Mike-verified UPCs spanning broad categories. Each was checked against
# manufacturer site or Amazon by Mike (who confirmed the UPC actually
# corresponds to the named product).
VERIFIED_CASES = [
    {
        "label": "switch_lite_hyrule",
        "upc": "045496884963",
        "expected_brand": "Nintendo",
        "expected_name_contains": ["Switch Lite"],
        "category": "console",
    },
    {
        "label": "instant_pot_duo",
        "upc": "853084004088",
        "expected_brand": "Instant Pot",
        "expected_name_contains": ["Duo", "Pressure Cooker"],
        "category": "kitchen",
    },
    {
        "label": "dewalt_dcd791d2",
        "upc": "885911425308",
        "expected_brand": "DEWALT",
        "expected_name_contains": ["DCD791", "20V"],
        "category": "tool",
    },
    {
        "label": "ps5_dualsense_white",
        "upc": "711719399506",
        "expected_brand": "Sony",
        "expected_name_contains": ["DualSense"],
        "category": "console",
    },
    {
        "label": "samsung_pro_plus_sonic",
        "upc": "887276911571",
        "expected_brand": "Samsung",
        "expected_name_contains": ["PRO Plus", "microSDXC", "Sonic"],
        "category": "storage",
    },
    {
        "label": "minisforum_um760_slim",
        "upc": "4897118833127",  # 13-digit EAN-13, kept as-is
        "expected_brand": "Minisforum",
        "expected_name_contains": ["UM760"],
        "category": "computer",
    },
    {
        "label": "ipad_air_m4_13in",
        "upc": "195950797817",
        "expected_brand": "Apple",
        "expected_name_contains": ["iPad Air"],
        "expected_chip": "M4",
        "expected_display_size_in": 13,
        "category": "tablet",
    },
    {
        "label": "dell_inspiron_14_7445",
        "upc": "884116490845",
        "expected_brand": "Dell",
        "expected_name_contains": ["Inspiron"],
        "category": "laptop",
    },
    {
        "label": "lenovo_legion_go",
        "upc": "618996774340",
        "expected_brand": "Lenovo",
        "expected_name_contains": ["Legion Go"],
        "category": "handheld",
    },
]


def matches_extended(result: dict, case: dict) -> bool:
    """matches() + Apple Rule 2c/2d (chip/display equality, disagreement-only)."""
    if not matches(result, case):
        return False
    # Apple Rule 2c: chip equality, disagreement-only
    if case.get("expected_chip"):
        rc = (result.get("chip") or "").upper()
        if rc and rc != case["expected_chip"].upper():
            return False
    # Apple Rule 2d: display-size equality, disagreement-only
    if case.get("expected_display_size_in"):
        rs = result.get("display_size_in")
        if rs and rs != case["expected_display_size_in"]:
            return False
    return True


# ── Three config wrappers ───────────────────────────────────────────────────
async def run_e_current_budget0(case, snippets: str):
    prompt = PROMPT_CURRENT.format(upc=case["upc"], snippets=snippets)
    return await synth_call(prompt, thinking_budget=0)


async def run_e_hardened_budget512(case, snippets: str):
    prompt = PROMPT_HARDENED.format(upc=case["upc"], snippets=snippets)
    return await synth_call(prompt, thinking_budget=512)


async def run_b_grounded_low(case, snippets: str):
    """Production baseline — grounded Google search + ThinkingLevel.LOW.
    Doesn't take Serper snippets (B uses its own grounded search)."""
    return await _gemini_call(
        UPC_LOOKUP_PROMPT.format(upc=case["upc"]),
        grounded=True, thinking="low", max_output_tokens=4096,
    )


CONFIGS = [
    ("E_current_budget0",    run_e_current_budget0,    True),   # uses Serper
    ("E_hardened_budget512", run_e_hardened_budget512, True),   # uses Serper
    ("B_grounded_low",       run_b_grounded_low,       False),  # no Serper
]


async def verified_bench():
    serper = SerperClient()
    rows = []
    started_at = datetime.now(timezone.utc).isoformat()
    total = len(CONFIGS) * len(VERIFIED_CASES) * RUNS_PER_COMBO

    print(
        f"\n[verified] {len(CONFIGS)} configs × {len(VERIFIED_CASES)} UPCs × "
        f"{RUNS_PER_COMBO} runs = {total} calls\n",
        file=sys.stderr,
    )
    for cfg_id, _fn, uses_serper in CONFIGS:
        srp = "Serper+Gemini" if uses_serper else "Gemini grounded only"
        print(f"  - {cfg_id}: {srp}", file=sys.stderr)

    # Fetch Serper once per UPC; reused for both Serper-based configs.
    case_snippets: dict[str, tuple[str, float, int]] = {}
    print("\n[serper fetches]", file=sys.stderr)
    for case in VERIFIED_CASES:
        organic, _kg, serper_ms = await serper.fetch(case["upc"])
        snippets = format_snippets(organic, top=5)
        organic_n = len(organic) if organic else 0
        case_snippets[case["upc"]] = (snippets, serper_ms, organic_n)
        print(
            f"  {case['label']:>22} ({case['upc']}) "
            f"{serper_ms:.0f}ms organic={organic_n}",
            file=sys.stderr,
        )

    print("", file=sys.stderr)
    call_n = 0
    for cfg_id, fn, uses_serper in CONFIGS:
        print(f"\n--- {cfg_id} ---", file=sys.stderr)
        for case in VERIFIED_CASES:
            snippets, serper_ms, _organic_n = case_snippets[case["upc"]]
            for run_idx in range(1, RUNS_PER_COMBO + 1):
                t_total_start = time.perf_counter()
                result = await fn(case, snippets)
                gemini_ms = result["latency_ms"] if "latency_ms" in result else 0
                total_ms = (time.perf_counter() - t_total_start) * 1000
                if uses_serper:
                    total_ms += serper_ms
                pass_flag = matches_extended(result, case)
                rows.append({
                    "config": cfg_id,
                    "case": case["label"],
                    "upc": case["upc"],
                    "category": case["category"],
                    "run": run_idx,
                    "device_name": result.get("device_name"),
                    "model": result.get("model"),
                    "chip": result.get("chip"),
                    "display_size_in": result.get("display_size_in"),
                    "matches_expected": pass_flag,
                    "gemini_latency_ms": gemini_ms,
                    "serper_latency_ms": serper_ms if uses_serper else None,
                    "total_latency_ms": total_ms,
                    "error": result.get("error"),
                    "raw_response": result.get("raw_response", "")[:1500],
                })
                call_n += 1
                tag = "PASS" if pass_flag else ("ERR" if result.get("error") else "fail")
                short = (result.get("device_name") or "<null>")[:48]
                if not pass_flag or run_idx == 1:
                    print(
                        f"  [{call_n:>3}/{total}] {case['label']:>22} run{run_idx}: "
                        f"{tag:<4} {gemini_ms:>5.0f}ms {short}",
                        file=sys.stderr,
                    )

    completed_at = datetime.now(timezone.utc).isoformat()
    artifact = {
        "started_at": started_at,
        "completed_at": completed_at,
        "runs_per_combo": RUNS_PER_COMBO,
        "configs": [c[0] for c in CONFIGS],
        "cases": [
            {"label": c["label"], "upc": c["upc"], "category": c["category"]}
            for c in VERIFIED_CASES
        ],
        "results": rows,
    }
    safe_ts = completed_at.replace(":", "-").replace("+", "_")
    out_path = RESULTS_DIR / f"synthesis_verified_{safe_ts}.json"
    out_path.write_text(json.dumps(artifact, indent=2))
    print(f"\n[artifact] {out_path}", file=sys.stderr)

    print_summary(rows)


def print_summary(rows):
    print()
    print("=" * 110)
    print("\n=== PER-CONFIG PER-CASE PASS COUNT (out of 5 runs each) ===\n")

    case_labels = [c["label"] for c in VERIFIED_CASES]
    config_ids = [c[0] for c in CONFIGS]

    # Header row
    header = f"  {'config':>22}"
    for case_label in case_labels:
        header += f"  {case_label[:14]:>14}"
    header += f"  {'recall':>9}"
    print(header)

    config_stats = []
    for cfg_id in config_ids:
        cfg_rows = [r for r in rows if r["config"] == cfg_id]
        line = f"  {cfg_id:>22}"
        case_passes = []
        for case_label in case_labels:
            crows = [r for r in cfg_rows if r["case"] == case_label]
            hits = sum(1 for r in crows if r["matches_expected"])
            case_passes.append((case_label, hits))
            mark = "✓" if hits == 5 else ("~" if hits >= 4 else ("." if hits > 0 else "✗"))
            line += f"  {hits}/5 {mark}".rjust(15)
        total_hits = sum(h for _, h in case_passes)
        total_runs = len(case_labels) * 5
        line += f"  {total_hits}/{total_runs}".rjust(11)
        print(line)

        latencies_total = [r["total_latency_ms"] for r in cfg_rows if r["error"] is None]
        latencies_gemini = [r["gemini_latency_ms"] for r in cfg_rows if r["error"] is None]
        config_stats.append({
            "config": cfg_id,
            "n_perfect": sum(1 for _, h in case_passes if h == 5),
            "n_above_4": sum(1 for _, h in case_passes if h >= 4),
            "n_at_least_one": sum(1 for _, h in case_passes if h > 0),
            "total_hits": total_hits,
            "total_runs": total_runs,
            "p50_total": _percentile(latencies_total, 50),
            "p90_total": _percentile(latencies_total, 90),
            "p99_total": _percentile(latencies_total, 99),
            "p50_gemini": _percentile(latencies_gemini, 50),
            "p90_gemini": _percentile(latencies_gemini, 90),
        })

    print("\nMarker legend:  ✓ = 5/5  ~ = ≥4/5  . = 1-3/5  ✗ = 0/5")

    # Latency + recall summary
    print()
    print("=== PER-CONFIG SUMMARY ===")
    print(
        f"  {'config':>22}  {'5/5 ✓':>6}  {'≥4/5 ~':>6}  {'≥1/5 .':>6}  "
        f"{'recall':>10}  {'gemini_p50':>10}  {'total_p50':>10}  {'total_p90':>10}"
    )
    for s in config_stats:
        print(
            f"  {s['config']:>22}  {s['n_perfect']:>4}/{len(case_labels)}  "
            f"{s['n_above_4']:>4}/{len(case_labels)}  "
            f"{s['n_at_least_one']:>4}/{len(case_labels)}  "
            f"{s['total_hits']}/{s['total_runs']} "
            f"({100*s['total_hits']/max(1,s['total_runs']):.0f}%)".rjust(13) +
            f"  {s['p50_gemini']:>9.0f}ms  {s['p50_total']:>9.0f}ms  {s['p90_total']:>9.0f}ms"
        )

    # Head-to-head against B
    print()
    print("=" * 110)
    print("\n=== HEAD-TO-HEAD vs B (production baseline) ===")
    b_stats = next((s for s in config_stats if s["config"] == "B_grounded_low"), None)
    if not b_stats:
        return
    for s in config_stats:
        if s["config"] == "B_grounded_low":
            continue
        d_recall_pp = (
            100*s["total_hits"]/s["total_runs"] -
            100*b_stats["total_hits"]/b_stats["total_runs"]
        )
        d_lat_pct = 100 * (s["p50_total"] - b_stats["p50_total"]) / max(1, b_stats["p50_total"])
        print(f"\n  {s['config']} vs B:")
        print(f"    recall: {s['total_hits']}/{s['total_runs']} vs {b_stats['total_hits']}/{b_stats['total_runs']}  ({d_recall_pp:+.1f} pp)")
        print(f"    latency p50: {s['p50_total']:.0f}ms vs {b_stats['p50_total']:.0f}ms  ({d_lat_pct:+.1f}%)")
        print(f"    latency p90: {s['p90_total']:.0f}ms vs {b_stats['p90_total']:.0f}ms")


if __name__ == "__main__":
    asyncio.run(verified_bench())
