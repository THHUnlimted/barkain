#!/usr/bin/env python3
"""5-combo wider-field validation for bench/vendor-migrate-1.

The 3-UPC mini-grid produced 6 'winners' all hitting 5/5 on Xbox + 2 AirPods.
The 1-config 10-UPC broader expansion (winner = current/budget=0) wiped out
0/50 across categories. Apple Watch returning MacBook Pro and Galaxy S24
returning cabinet hardware show the snippets are noisier in the real world
and the model needs some thinking budget to disambiguate.

This script re-tests the 5 OTHER mini-grid winners against the same 10-UPC
broader catalog × 5 runs each. Picks the cheapest combo with ≥9/10 cases at
≥4/5 runs.

5 combos × 10 UPCs × 5 runs = 250 calls (~$0.20, ~15 min).

Run:
    python3 scripts/bench_synthesis_expansion_grid.py
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
    _budget_label,
    _percentile,
    cost_per_call,
    format_snippets,
    matches,
    synth_call,
)
from bench_synthesis_expansion import EXPANSION_CASES  # noqa: E402

RESULTS_DIR = ROOT / "scripts" / "bench_results"
RUNS_PER_COMBO = 5

# 5 combos that hit 5/5 on the 3-UPC mini-grid (excluding budget=0 already
# disqualified by the 0/50 expansion result, and hardened/dynamic which
# regressed on AirPods).
COMBOS = [
    ("current", 1024),
    ("current", -1),     # dynamic
    ("hardened", 256),
    ("hardened", 512),
    ("hardened", 1024),
]

PROMPTS = {"current": PROMPT_CURRENT, "hardened": PROMPT_HARDENED}


async def expansion_grid():
    serper = SerperClient()
    rows = []
    started_at = datetime.now(timezone.utc).isoformat()
    total = len(COMBOS) * len(EXPANSION_CASES) * RUNS_PER_COMBO

    print(
        f"\n[wider-field] {len(COMBOS)} combos × {len(EXPANSION_CASES)} UPCs × "
        f"{RUNS_PER_COMBO} runs = {total} calls\n",
        file=sys.stderr,
    )
    print("Combos under test:", file=sys.stderr)
    for prompt_id, budget in COMBOS:
        print(f"  - {prompt_id}/{_budget_label(budget)}", file=sys.stderr)
    print("", file=sys.stderr)

    # 1 Serper call per UPC; reused across all 5 combos × 5 runs.
    case_snippets: dict[str, tuple[str, float]] = {}
    for case in EXPANSION_CASES:
        organic, _kg, serper_ms = await serper.fetch(case["upc"])
        snippets = format_snippets(organic, top=5)
        case_snippets[case["upc"]] = (snippets, serper_ms)
        organic_n = len(organic) if organic else 0
        print(
            f"[serper] {case['label']:>22} ({case['upc']}) "
            f"{serper_ms:.0f}ms organic={organic_n}",
            file=sys.stderr,
        )

    print("", file=sys.stderr)

    call_n = 0
    for prompt_id, budget in COMBOS:
        template = PROMPTS[prompt_id]
        print(f"\n--- {prompt_id}/{_budget_label(budget)} ---", file=sys.stderr)
        for case in EXPANSION_CASES:
            snippets, serper_ms = case_snippets[case["upc"]]
            for run_idx in range(1, RUNS_PER_COMBO + 1):
                t_total_start = time.perf_counter()
                prompt = template.format(upc=case["upc"], snippets=snippets)
                result = await synth_call(prompt, thinking_budget=budget)
                total_ms = (time.perf_counter() - t_total_start) * 1000 + serper_ms
                pass_flag = matches(result, case)
                rows.append({
                    "case": case["label"],
                    "upc": case["upc"],
                    "category": case["category"],
                    "prompt_id": prompt_id,
                    "thinking_budget": budget,
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
                if not pass_flag or run_idx == 1:
                    short = (result["device_name"] or "<null>")[:40]
                    print(
                        f"  [{call_n:>3}/{total}] {case['label']:>22} run{run_idx}: "
                        f"{tag:<4} {result['latency_ms']:>5.0f}ms {short}",
                        file=sys.stderr,
                    )

    completed_at = datetime.now(timezone.utc).isoformat()
    artifact = {
        "started_at": started_at,
        "completed_at": completed_at,
        "runs_per_combo": RUNS_PER_COMBO,
        "combos": [
            {"prompt_id": p, "thinking_budget": b}
            for p, b in COMBOS
        ],
        "cases": [
            {"label": c["label"], "upc": c["upc"], "category": c["category"]}
            for c in EXPANSION_CASES
        ],
        "results": rows,
    }
    safe_ts = completed_at.replace(":", "-").replace("+", "_")
    out_path = RESULTS_DIR / f"synthesis_expansion_grid_{safe_ts}.json"
    out_path.write_text(json.dumps(artifact, indent=2))
    print(f"\n[artifact] {out_path}", file=sys.stderr)

    print_summary(rows)


def print_summary(rows):
    print()
    print("=" * 110)
    print("\n=== PER-COMBO PER-CASE PASS COUNT (out of 5 runs each) ===")
    print()

    by_combo: dict[tuple, list] = {}
    for r in rows:
        key = (r["prompt_id"], r["thinking_budget"])
        by_combo.setdefault(key, []).append(r)

    case_labels = [c["label"] for c in EXPANSION_CASES]
    # Header
    header = f"  {'combo':>22}"
    for case_label in case_labels:
        header += f"  {case_label[:14]:>14}"
    header += f"  {'overall':>9}"
    print(header)

    # Stats container for the verdict block
    combo_stats = []

    for key in sorted(by_combo.keys(), key=lambda k: (k[0], k[1] if k[1] >= 0 else 9999)):
        prompt_id, budget = key
        combo_label = f"{prompt_id}/{_budget_label(budget)}"
        crows = by_combo[key]
        line = f"  {combo_label:>22}"
        case_passes = []
        for case_label in case_labels:
            case_rows = [r for r in crows if r["case"] == case_label]
            hits = sum(1 for r in case_rows if r["matches_expected"])
            case_passes.append((case_label, hits))
            mark = "✓" if hits == 5 else ("~" if hits >= 4 else ("." if hits > 0 else "✗"))
            line += f"  {hits}/5 {mark:<10}".rjust(15)
        total_hits = sum(h for _, h in case_passes)
        total_runs = len(case_labels) * 5
        line += f"  {total_hits}/{total_runs}".rjust(11)
        print(line)

        n_cases_above_4 = sum(1 for _, h in case_passes if h >= 4)
        n_cases_perfect = sum(1 for _, h in case_passes if h == 5)
        latencies = [r["total_latency_ms"] for r in crows if r["error"] is None]
        gemini_lats = [r["gemini_latency_ms"] for r in crows if r["error"] is None]
        cost = cost_per_call(budget)
        combo_stats.append({
            "combo": combo_label,
            "prompt_id": prompt_id,
            "budget": budget,
            "n_cases_perfect": n_cases_perfect,
            "n_cases_above_4": n_cases_above_4,
            "total_hits": total_hits,
            "total_runs": total_runs,
            "p50_total": _percentile(latencies, 50),
            "p90_total": _percentile(latencies, 90),
            "p50_gemini": _percentile(gemini_lats, 50),
            "p90_gemini": _percentile(gemini_lats, 90),
            "cost_per_call": cost,
        })

    print()
    print("Marker legend:  ✓ = 5/5  ~ = ≥4/5  . = 1-3/5  ✗ = 0/5")

    # Latency + recall summary table
    print()
    print("=== PER-COMBO SUMMARY (sorted by overall recall, then cost) ===")
    print(
        f"  {'combo':>22}  {'5/5 ✓':>6}  {'≥4/5 ~':>6}  "
        f"{'recall':>10}  {'gemini_p50':>10}  {'total_p50':>10}  {'cost':>9}"
    )
    combo_stats.sort(key=lambda s: (-s["total_hits"], s["cost_per_call"]))
    for s in combo_stats:
        print(
            f"  {s['combo']:>22}  {s['n_cases_perfect']:>4}/10  "
            f"{s['n_cases_above_4']:>4}/10  "
            f"{s['total_hits']}/{s['total_runs']} "
            f"({100*s['total_hits']/max(1,s['total_runs']):.0f}%)".rjust(13) +
            f"  {s['p50_gemini']:>9.0f}ms  {s['p50_total']:>9.0f}ms  "
            f"${s['cost_per_call']:>7.5f}"
        )

    # Verdict
    print()
    print("=" * 110)
    eligible = [s for s in combo_stats if s["n_cases_above_4"] >= 9]
    print()
    if eligible:
        eligible.sort(key=lambda s: s["cost_per_call"])
        winner = eligible[0]
        print(
            f"=== CHEAPEST WIDER-FIELD WINNER: {winner['combo']} "
            f"({winner['n_cases_perfect']}/10 perfect, "
            f"{winner['n_cases_above_4']}/10 near-perfect) ==="
        )
        print(
            f"  Gemini p50={winner['p50_gemini']:.0f}ms  "
            f"total p50={winner['p50_total']:.0f}ms  "
            f"cost=${winner['cost_per_call']:.5f}/call"
        )
        print("  → SHIP this combo into production with B as null-fallback.")
    else:
        best = max(combo_stats, key=lambda s: s["n_cases_above_4"])
        print(
            f"=== NO COMBO HIT ≥9/10 NEAR-PERFECT — best is {best['combo']} "
            f"with {best['n_cases_above_4']}/10 cases at ≥4/5 ==="
        )
        print(
            "  → DO NOT MIGRATE. Ship-readiness threshold not met. "
            "Investigate which categories systematically fail."
        )


if __name__ == "__main__":
    asyncio.run(expansion_grid())
