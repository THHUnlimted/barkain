#!/usr/bin/env python3
"""Mini A-vs-B verified bench — confirms B (grounding + ThinkingLevel.LOW)
matches A (grounding + dynamic thinking) on recall over a UPCitemdb-verified
catalog before flipping production.

Why this exists:
    vendor-compare-1 (PR #74) shipped DEFER because 16 of 18 non-invalid
    catalog UPCs didn't resolve to their labeled products on grounded Gemini —
    the catalog labels were synthesized from prefix-block matching without
    UPCitemdb verification. Latency wins were conclusive but recall was
    contaminated. Before flipping the Gemini leg from dynamic thinking to
    LOW thinking in production we need recall confirmation on real ground
    truth.

How it differs from bench_vendor_compare.py:
    - Only A and B configs (no Serper, no priors-only, no KG-only)
    - 10 hand-picked candidate UPCs with UPCitemdb pre-validation
        (each candidate's UPCitemdb response brand must contain the intended
        brand token; otherwise the UPC is dropped before any Gemini calls)
    - 3 runs per config (1 cold + 2 warm); cold excluded from latency stats
    - Per-UPC pass/fail table

Cost: ~10 UPCs × 2 configs × 3 runs ≈ 60 calls, ~$3-4.

Run:
    python3 scripts/bench_mini_a_vs_b.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── .env loader (manual, no python-dotenv dep — mirrors test_upc_lookup.py) ──
ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
if ENV_PATH.exists():
    for raw_line in ENV_PATH.read_text().splitlines():
        s = raw_line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, _, v = s.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

sys.path.insert(0, str(ROOT / "scripts"))

import httpx  # noqa: E402

# Reuse helpers from the full bench so we stay byte-for-byte aligned with
# vendor-compare-1's call shape (same model, same prompt, same parser).
from bench_vendor_compare import (  # noqa: E402
    UPC_LOOKUP_PROMPT,
    _gemini_call,
    _timed_call,
    percentile,
    validate,
)

RESULTS_DIR = ROOT / "scripts" / "bench_results"
RUNS_PER_CONFIG = 3  # 1 cold + 2 warm
UPCITEMDB_TRIAL_URL = "https://api.upcitemdb.com/prod/trial/lookup"

# Cost estimates lifted from vendor-compare-1 final analysis. Order-of-magnitude.
COST_ESTIMATES_USD = {
    "A_grounded_dynamic": 0.064,
    "B_grounded_low": 0.040,
}

# Candidate UPCs. Each entry's UPCitemdb response brand must contain the
# `expected_brand` token (case-insensitive) for the UPC to enter the bench.
# This list is the subset that survived UPCitemdb's trial DB pre-flight; UPCs
# that returned no item (Sony WH-1000XM3/4/5 — not in trial DB) or that
# persistently 429'd (JBL Flip 6, Bose QC45, Switch Pro Controller) were
# dropped to keep the bench run focused on real ground truth. 4 Apple +
# 1 Samsung covers two brands and two product families (TWS earbuds +
# wireless earbuds).
CANDIDATES: list[dict] = [
    # Apple AirPods family — 4 variants
    {
        "upc": "195949052484",
        "expected_brand": "Apple",
        "expected_name_contains": ["AirPods Pro"],
        "label": "AirPods Pro 2 USB-C",
        "category": "audio",
    },
    {
        "upc": "194253397168",
        "expected_brand": "Apple",
        "expected_name_contains": ["AirPods Pro"],
        "label": "AirPods Pro 2nd Gen",
        "category": "audio",
    },
    {
        "upc": "190199246850",
        "expected_brand": "Apple",
        "expected_name_contains": ["AirPods Pro"],
        "label": "AirPods Pro 1st Gen",
        "category": "audio",
    },
    {
        "upc": "190199098428",
        "expected_brand": "Apple",
        "expected_name_contains": ["AirPods"],
        "label": "AirPods 2nd Gen",
        "category": "audio",
    },
    # Samsung — second brand for divergence signal
    {
        "upc": "732554340133",
        "expected_brand": "Samsung",
        "expected_name_contains": ["Galaxy Buds"],
        "label": "Galaxy Buds R170N",
        "category": "audio",
    },
]

CONFIGS = ["A_grounded_dynamic", "B_grounded_low"]


# ── UPCitemdb pre-validation ────────────────────────────────────────────────
async def upcitemdb_lookup(upc: str, *, max_retries: int = 3) -> dict | None:
    """Hit UPCitemdb's trial endpoint. Returns first item or None.

    Retries on 429 with exponential backoff (5s, 15s, 45s) — trial tier has
    a per-minute rate cap on top of the daily 100-call quota.
    """
    delay = 5.0
    for attempt in range(1, max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(UPCITEMDB_TRIAL_URL, params={"upc": upc})
                if resp.status_code == 429:
                    if attempt < max_retries:
                        print(f"  [retry {attempt}/{max_retries}] {upc}: 429 — sleeping {delay:.0f}s")
                        await asyncio.sleep(delay)
                        delay *= 3
                        continue
                    print(f"  [!] {upc}: UPCitemdb rate-limited after {max_retries} retries")
                    return None
                resp.raise_for_status()
                data = resp.json()
            items = data.get("items", [])
            if not items:
                return None
            item = items[0]
            return {
                "name": item.get("title", ""),
                "brand": item.get("brand", ""),
                "category": item.get("category", ""),
            }
        except Exception as exc:
            print(f"  [!] {upc}: UPCitemdb error {type(exc).__name__}: {exc!r}")
            return None
    return None


async def validate_candidates(candidates: list[dict]) -> tuple[list[dict], list[dict]]:
    """Returns (kept, dropped). Each kept entry gains an `upcitemdb_*` block."""
    kept: list[dict] = []
    dropped: list[dict] = []
    print("\n=== UPCitemdb pre-validation ===")
    for cand in candidates:
        ud = await upcitemdb_lookup(cand["upc"])
        if not ud:
            print(f"  [DROP] {cand['upc']} ({cand['label']}): UPCitemdb returned no item")
            dropped.append({**cand, "drop_reason": "no_upcitemdb_item"})
            continue
        brand_ok = cand["expected_brand"].lower() in (ud.get("brand") or "").lower()
        # Some UPCitemdb entries store the brand in the title only (e.g. "JBL Flip 6")
        # so fall back to scanning the title when the brand field is empty.
        if not brand_ok:
            brand_ok = cand["expected_brand"].lower() in (ud.get("name") or "").lower()
        if not brand_ok:
            print(
                f"  [DROP] {cand['upc']} ({cand['label']}): UPCitemdb brand "
                f"'{ud.get('brand')}' / name '{ud.get('name')}' does not contain "
                f"'{cand['expected_brand']}'"
            )
            dropped.append({**cand, "drop_reason": "brand_mismatch", "upcitemdb_brand": ud.get("brand"), "upcitemdb_name": ud.get("name")})
            continue
        print(
            f"  [KEEP] {cand['upc']} ({cand['label']}) → "
            f"UPCitemdb says: {ud.get('brand')} / {ud.get('name')[:60]}"
        )
        kept.append({
            **cand,
            "upcitemdb_brand": ud.get("brand"),
            "upcitemdb_name": ud.get("name"),
            "upcitemdb_category": ud.get("category"),
            "difficulty": "flagship",  # used by validate() — none of these are 'invalid'
        })
    return kept, dropped


# ── Per-config wrappers (only A and B — match bench_vendor_compare.py) ──────
async def run_a(case):
    return await _gemini_call(
        UPC_LOOKUP_PROMPT.format(upc=case["upc"]),
        grounded=True, thinking="dynamic", max_output_tokens=4096,
    )


async def run_b(case):
    return await _gemini_call(
        UPC_LOOKUP_PROMPT.format(upc=case["upc"]),
        grounded=True, thinking="low", max_output_tokens=4096,
    )


CONFIG_FUNCS = {
    "A_grounded_dynamic": run_a,
    "B_grounded_low": run_b,
}


# ── Summary ─────────────────────────────────────────────────────────────────
def print_per_upc_table(rows: list[dict], catalog: list[dict]):
    print("\n=== PER-UPC PASS/FAIL (warm runs only) ===")
    print(f"  {'UPC':<14} {'label':<26} {'A':>10}  {'B':>10}  agree?")
    for case in catalog:
        upc = case["upc"]
        a_warm = [r for r in rows if r["upc"] == upc and r["config"] == "A_grounded_dynamic" and not r["is_cold"]]
        b_warm = [r for r in rows if r["upc"] == upc and r["config"] == "B_grounded_low" and not r["is_cold"]]
        a_pass = sum(1 for r in a_warm if r["matches_expected"])
        b_pass = sum(1 for r in b_warm if r["matches_expected"])
        agree = "yes" if (a_pass > 0) == (b_pass > 0) else "DIVERGE"
        print(
            f"  {upc:<14} {case['label'][:25]:<26} "
            f"{a_pass}/{len(a_warm)}".rjust(10) + "  "
            + f"{b_pass}/{len(b_warm)}".rjust(10) + f"  {agree}"
        )


def print_config_summary(rows: list[dict]):
    print("\n=== PER-CONFIG SUMMARY (warm runs only) ===")
    for cfg in CONFIGS:
        warm = [r for r in rows if r["config"] == cfg and not r["is_cold"]]
        successful = [r for r in warm if r["error"] is None]
        recall_hits = sum(1 for r in warm if r["matches_expected"])
        latencies = [r["total_latency_ms"] for r in warm if r["error"] is None]
        timeouts = sum(1 for r in rows if r["config"] == cfg and r["error"] == "timeout")
        print(f"\n  --- {cfg} ---")
        print(f"  Successful runs: {len(successful)}/{len(warm)} ({100*len(successful)/max(1,len(warm)):.1f}%)")
        print(f"  Recall:          {recall_hits}/{len(warm)} ({100*recall_hits/max(1,len(warm)):.1f}%)")
        if latencies:
            print(f"  Latency p50:     {percentile(latencies, 50):.0f} ms")
            print(f"  Latency p90:     {percentile(latencies, 90):.0f} ms")
        print(f"  Timeouts:        {timeouts}")


def print_head_to_head(rows: list[dict]):
    a_warm = [r for r in rows if r["config"] == "A_grounded_dynamic" and not r["is_cold"] and r["error"] is None]
    b_warm = [r for r in rows if r["config"] == "B_grounded_low" and not r["is_cold"] and r["error"] is None]
    if not (a_warm and b_warm):
        print("\n=== HEAD-TO-HEAD ===\n  (insufficient data)")
        return
    a_lat = [r["total_latency_ms"] for r in a_warm]
    b_lat = [r["total_latency_ms"] for r in b_warm]
    a_p50, b_p50 = percentile(a_lat, 50), percentile(b_lat, 50)
    a_p90, b_p90 = percentile(a_lat, 90), percentile(b_lat, 90)
    a_recall_total = sum(1 for r in rows if r["config"] == "A_grounded_dynamic" and not r["is_cold"])
    b_recall_total = sum(1 for r in rows if r["config"] == "B_grounded_low" and not r["is_cold"])
    a_recall_hits = sum(1 for r in rows if r["config"] == "A_grounded_dynamic" and not r["is_cold"] and r["matches_expected"])
    b_recall_hits = sum(1 for r in rows if r["config"] == "B_grounded_low" and not r["is_cold"] and r["matches_expected"])
    a_pp = 100 * a_recall_hits / max(1, a_recall_total)
    b_pp = 100 * b_recall_hits / max(1, b_recall_total)
    cost_a = COST_ESTIMATES_USD["A_grounded_dynamic"]
    cost_b = COST_ESTIMATES_USD["B_grounded_low"]
    print("\n=== HEAD-TO-HEAD: A_grounded_dynamic vs B_grounded_low ===")
    print(f"  p50 latency: {a_p50:.0f}  →  {b_p50:.0f} ms  ({100*(a_p50-b_p50)/max(1,a_p50):+.1f}%)")
    print(f"  p90 latency: {a_p90:.0f}  →  {b_p90:.0f} ms  ({100*(a_p90-b_p90)/max(1,a_p90):+.1f}%)")
    print(f"  Recall:      {a_recall_hits}/{a_recall_total} ({a_pp:.1f}%)  →  {b_recall_hits}/{b_recall_total} ({b_pp:.1f}%)  ({b_pp-a_pp:+.1f} pp)")
    print(f"  Cost/call:   ${cost_a:.4f}  →  ${cost_b:.4f}  ({100*(cost_a-cost_b)/max(1e-6,cost_a):+.1f}%)")
    diverged = []
    for r in a_warm:
        # Find matching B run; report any UPC where A passed but B failed
        b_match = next((br for br in b_warm if br["upc"] == r["upc"] and br["run"] == r["run"]), None)
        if b_match and r["matches_expected"] and not b_match["matches_expected"]:
            diverged.append((r["upc"], r["device_name"], b_match.get("device_name")))
    if diverged:
        print("\n  [!] UPCs where A passed but B failed (run-paired):")
        for upc, a_name, b_name in diverged:
            print(f"      {upc}: A={a_name!r}  B={b_name!r}")
    else:
        print("\n  ✓ No UPC where A passed but B failed on a paired warm run.")


# ── Main loop ───────────────────────────────────────────────────────────────
async def benchmark():
    catalog, dropped = await validate_candidates(CANDIDATES)
    if not catalog:
        print("\n[ABORT] No UPCs survived UPCitemdb pre-validation.")
        return None

    print(f"\n=== Running A vs B against {len(catalog)} validated UPCs, "
          f"{RUNS_PER_CONFIG} runs each ({len(catalog) * 2 * RUNS_PER_CONFIG} total calls) ===\n")

    rows: list[dict] = []
    started_at = datetime.now(timezone.utc).isoformat()
    call_count = 0

    for case_idx, case in enumerate(catalog, start=1):
        print(f"[{case_idx:>2}/{len(catalog)}] UPC {case['upc']} ({case['label']})", file=sys.stderr)
        for run_idx in range(1, RUNS_PER_CONFIG + 1):
            for config_id in CONFIGS:
                func = CONFIG_FUNCS[config_id]
                result, elapsed_ms, err = await _timed_call(func(case))
                rows.append({
                    "config": config_id,
                    "upc": case["upc"],
                    "label": case["label"],
                    "category": case.get("category"),
                    "run": run_idx,
                    "is_cold": run_idx == 1,
                    "latency_ms": elapsed_ms,
                    "total_latency_ms": elapsed_ms,
                    "device_name": result.get("device_name"),
                    "model": result.get("model"),
                    "chip": result.get("chip"),
                    "display_size_in": result.get("display_size_in"),
                    "matches_expected": validate(result, {**case, "difficulty": "flagship"}),
                    "error": err,
                })
                call_count += 1
                if call_count % 10 == 0:
                    print(f"  [progress] {call_count} calls done", file=sys.stderr)

    completed_at = datetime.now(timezone.utc).isoformat()
    artifact = {
        "started_at": started_at,
        "completed_at": completed_at,
        "catalog": catalog,
        "dropped_candidates": dropped,
        "configs": CONFIGS,
        "runs_per_config": RUNS_PER_CONFIG,
        "cost_estimates_usd": COST_ESTIMATES_USD,
        "results": rows,
        "intent": (
            "Verify B (grounding + ThinkingLevel.LOW) matches A (grounding + dynamic "
            "thinking) on recall over UPCitemdb-verified UPCs before flipping production."
        ),
    }
    safe_ts = completed_at.replace(":", "-").replace("+", "_")
    out_path = RESULTS_DIR / f"bench_mini_a_vs_b_{safe_ts}.json"
    out_path.write_text(json.dumps(artifact, indent=2))
    print(f"\n[artifact] {out_path}", file=sys.stderr)

    print_per_upc_table(rows, catalog)
    print_config_summary(rows)
    print_head_to_head(rows)
    return artifact


if __name__ == "__main__":
    asyncio.run(benchmark())
