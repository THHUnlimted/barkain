#!/usr/bin/env python3
"""Mini-bench for Step 3o-C: validate grounded-fallback resolve under the
category-agnostic system instruction rewrite.

Mirrors the bench/vendor-migrate-1 posture — one-off, in scripts/, not
unit-test-suite. Bypasses ``resolve_via_serper`` so we only exercise the
grounded fallback (the path the new prompt actually fires on).

5-UPC mixed-vertical panel × 2 prompts (old + new) = 10 grounded calls.
Approx ~$0.40 spend, ~3 min wall.

Pass criteria: ``recall_new >= recall_old`` on the electronics row (no
regression). Non-electronics rows: ``recall_new >= recall_old`` ideally;
tied or slight improvement acceptable.

Run:
    python3 scripts/bench_grounded_3o_c.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
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

sys.path.insert(0, str(ROOT / "backend"))

from ai.abstraction import gemini_generate_json  # noqa: E402
from ai.prompts.upc_lookup import (  # noqa: E402
    UPC_LOOKUP_SYSTEM_INSTRUCTION,
    build_upc_lookup_prompt,
)

RESULTS_DIR = ROOT / "scripts" / "bench_results"

# Frozen copy of the old electronics-locked system instruction (pre-3o-C)
# for control runs. Do not edit — this is the historical text.
OLD_SYSTEM_INSTRUCTION = """# DO NOT CONDENSE OR SHORTEN THIS PROMPT — COPY VERBATIM

Research the provided UPC (Universal Product Code) and return a JSON object with a detailed reasoning field and the most specific electronic device name associated with the code. Your output must include, if available, full retail identifiers such as brand, product line, model/specification, size, and model or SKU/part number in parentheses (e.g., "Apple MacBook Air 13-inch model (MDHG4LL/A)") Additionally, Return model: the shortest unambiguous product identifier including generation, model number, capacity, and color variant where applicable.
Examples:
  - "iPad Pro 13-inch M4 256GB" not "iPad Pro"
  - "Galaxy Buds Pro (1st Gen)" not "Galaxy Buds Pro"
  - "RTX 4090" not "GeForce RTX 4090 Founders Edition"
  - "iPhone 16 Pro Max 256GB" not "iPhone 16 Pro Max".
Maintain optimization instructions for lookup speed: use the minimum possible number of data sources, prioritize the fastest and highest-yield databases, and explain how you maximize speed and accuracy at every step.
Begin with a stepwise, detailed explanation in the "reasoning" field of all actions taken to optimize lookup speed, including database/source selection, methods to identify electronics-only UPCs, and how you verify product specificity.
In your reasoning, state how you determined which full identifiers are available (brand, model, size, SKU, etc.), and why the name is as specific as possible.
If the UPC cannot be matched to an electronics device, is invalid, or if the needed specificity cannot be determined, explain this in your reasoning and set "device_name" to null.
Return a JSON object with:
"device_name": (string or null) The most fully specified name available for the device: must include brand, product line, specification or size, and model/part/SKU if these are available. If a match is not found or not specific, return null.
"model": (string or null) The shortest unambiguous product identifier including generation, model number, capacity, and color variant where applicable. Examples: "iPad Pro 13-inch M4 256GB", "Galaxy Buds Pro (1st Gen)", "RTX 4090", "iPhone 16 Pro Max 256GB". If no model can be determined, return null.
"reasoning": (string) Your step-by-step explanation.
Step 1: Validate UPC format and electronics relevance for speed. Step 2: Query high-yield electronics UPC/retail databases with maximum reliability and speed (vendor/brand-agnostic but electronics-focused). Step 3: Cross-verify matched item across multiple sources to confirm specificity (brand, product line, model/SKU, size). Step 4: If feeds consistently return a full retail name (brand, line, size, model/SKU), extract the most precise naming available; otherwise, default to null. Step 5: Given the UPC provided, identify the associated electronics item and confirm its exact product name and SKU across reputable sources (e.g., manufacturer repos, major retailers, or authorized resellers). Step 6: Assemble the final, fully specified device_name in the required format: Brand Product Line/Type Size/Specification (Model or SKU). Step 7: Provide justification for why this is the most specific identifier achievable from the sources and note any alternative naming variants observed to ensure traceability. Step 8: Ensure sources are electronics-focused and minimize the number of data sources to preserve lookup speed while maintaining accuracy. Step 9: If no specific model/SKU is verifiable, set device_name to null and explain why."""

# 5-UPC mixed-vertical panel. Recall criteria are intentionally loose:
# brand AND any expected token must appear in device_name+model haystack.
PANEL = [
    {
        "label": "ipad_air_m4_13",
        "upc": "195950797817",
        "category": "electronics",
        "expected_brand": "Apple",
        "expected_tokens": ["iPad Air"],
    },
    {
        "label": "pedigree_wet_dog",
        "upc": "023100010069",
        "category": "pet",
        "expected_brand": "Pedigree",
        "expected_tokens": ["dog", "wet", "meaty"],
    },
    {
        "label": "makita_xfd10z",
        "upc": "087547002001",
        "category": "tool",
        "expected_brand": "Makita",
        "expected_tokens": ["18V", "drill", "driver"],
    },
    {
        "label": "hamilton_beach_scoop",
        "upc": "040094920938",
        "category": "household",
        "expected_brand": "Hamilton Beach",
        "expected_tokens": ["scoop", "coffee"],
    },
    {
        "label": "weber_q_1200",
        "upc": "077924034695",
        "category": "lawn_outdoor",
        "expected_brand": "Weber",
        "expected_tokens": ["q", "grill", "1200"],
    },
]


def matches(result: dict, case: dict) -> bool:
    name = (result.get("device_name") or "").lower()
    model = (result.get("model") or "").lower()
    if not name:
        return False
    haystack = f"{name} {model}"
    if case["expected_brand"].lower() not in haystack:
        return False
    return any(tok.lower() in haystack for tok in case["expected_tokens"])


async def call_one(upc: str, system_instruction: str) -> tuple[dict, float]:
    prompt = build_upc_lookup_prompt(upc)
    t0 = time.perf_counter()
    try:
        raw = await gemini_generate_json(prompt, system_instruction=system_instruction)
        elapsed = (time.perf_counter() - t0) * 1000
        return raw, elapsed
    except Exception as exc:
        elapsed = (time.perf_counter() - t0) * 1000
        return {"device_name": None, "model": None, "error": f"{type(exc).__name__}: {exc!r}"}, elapsed


async def run_panel(label: str, system_instruction: str) -> list[dict]:
    rows = []
    print(f"\n--- {label} ---", file=sys.stderr)
    for case in PANEL:
        result, ms = await call_one(case["upc"], system_instruction)
        passed = matches(result, case)
        rows.append({
            "prompt": label,
            "case": case["label"],
            "upc": case["upc"],
            "category": case["category"],
            "device_name": result.get("device_name"),
            "model": result.get("model"),
            "matches_expected": passed,
            "latency_ms": ms,
            "error": result.get("error"),
        })
        tag = "PASS" if passed else ("ERR" if result.get("error") else "fail")
        short = (result.get("device_name") or "<null>")[:60]
        print(f"  {case['label']:>22} {tag:<4} {ms:>6.0f}ms {short}", file=sys.stderr)
    return rows


async def main():
    if not os.environ.get("GEMINI_API_KEY"):
        sys.exit("GEMINI_API_KEY required")

    started = datetime.now(timezone.utc).isoformat()
    rows: list[dict] = []
    rows.extend(await run_panel("old_prompt", OLD_SYSTEM_INSTRUCTION))
    rows.extend(await run_panel("new_prompt", UPC_LOOKUP_SYSTEM_INSTRUCTION))
    completed = datetime.now(timezone.utc).isoformat()

    # Aggregate
    old_pass = [r for r in rows if r["prompt"] == "old_prompt" and r["matches_expected"]]
    new_pass = [r for r in rows if r["prompt"] == "new_prompt" and r["matches_expected"]]
    print("\n" + "=" * 84, file=sys.stderr)
    print(f"  recall_old = {len(old_pass)}/{len(PANEL)}", file=sys.stderr)
    print(f"  recall_new = {len(new_pass)}/{len(PANEL)}", file=sys.stderr)
    print("\n  per-UPC:", file=sys.stderr)
    for case in PANEL:
        old_r = next((r for r in rows if r["prompt"] == "old_prompt" and r["case"] == case["label"]), None)
        new_r = next((r for r in rows if r["prompt"] == "new_prompt" and r["case"] == case["label"]), None)
        old_tag = "PASS" if old_r and old_r["matches_expected"] else "fail"
        new_tag = "PASS" if new_r and new_r["matches_expected"] else "fail"
        print(f"    {case['label']:>22} ({case['category']:<13}) old={old_tag} new={new_tag}", file=sys.stderr)
    print("=" * 84 + "\n", file=sys.stderr)

    # Pass criteria check
    elec_old = next((r for r in rows if r["prompt"] == "old_prompt" and r["category"] == "electronics"), None)
    elec_new = next((r for r in rows if r["prompt"] == "new_prompt" and r["category"] == "electronics"), None)
    elec_pass_old = bool(elec_old and elec_old["matches_expected"])
    elec_pass_new = bool(elec_new and elec_new["matches_expected"])
    no_elec_regression = (not elec_pass_old) or elec_pass_new
    print(f"  pass_criteria_no_electronics_regression = {no_elec_regression}", file=sys.stderr)

    artifact = {
        "started_at": started,
        "completed_at": completed,
        "panel_size": len(PANEL),
        "panel": [{"label": c["label"], "upc": c["upc"], "category": c["category"]} for c in PANEL],
        "results": rows,
        "aggregate": {
            "recall_old": f"{len(old_pass)}/{len(PANEL)}",
            "recall_new": f"{len(new_pass)}/{len(PANEL)}",
            "no_electronics_regression": no_elec_regression,
        },
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    safe_ts = completed.replace(":", "-").replace("+", "_")
    out_path = RESULTS_DIR / f"bench_3o_c_{safe_ts}.json"
    out_path.write_text(json.dumps(artifact, indent=2))
    print(f"  [artifact] {out_path}\n", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
