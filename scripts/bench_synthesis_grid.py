#!/usr/bin/env python3
"""Synthesis-prompt mini-grid for bench/vendor-migrate-1.

Goal: kill the non-deterministic null E_serper_then_D returned 4/4 on Xbox
Series X (UPC 889842640816) in vendor-compare-2 — without regressing the
AirPods cases that already pass.

Knobs:
  - prompt: "current" (vendor-compare-2 wording) vs "hardened" (new wording
    that swaps "if snippets insufficient return null" for "if 3+ snippets
    clearly name the same product, return it")
  - thinking_budget: 0 (no thinking), 256, 512, 1024, -1 (dynamic). All five
    are tested so we get a clean speed × quality curve across the full
    spectrum of internal-reasoning budgets — answers "how much thinking
    does the synthesis call actually need?"
  - max_output_tokens: fixed at 1024 (gives breathing room; observed median
    rarely fills it; varying this added little signal in early probes)

2 prompts × 5 thinking_budgets × 3 UPCs × 5 warm runs = 150 calls (~$0.40,
~7-10 min wall time). Pick cheapest combo achieving 5/5 on Xbox + 5/5 on
both AirPods regression guards.

Run:
    python3 scripts/bench_synthesis_grid.py
"""

from __future__ import annotations

import asyncio
import json
import os
import re
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

sys.path.insert(0, str(ROOT / "scripts"))

from _bench_serper import SerperClient, format_snippets  # noqa: E402

from google import genai  # noqa: E402
from google.genai.types import (  # noqa: E402
    GenerateContentConfig,
    ThinkingConfig,
)

GEMINI_MODEL = "gemini-3.1-flash-lite-preview"
RUNS_PER_COMBO = 5
TIMEOUT_SEC = 30
MAX_OUTPUT_TOKENS = 1024
RESULTS_DIR = ROOT / "scripts" / "bench_results"

# 3 UPCs: Xbox is the failure case we need to fix; two AirPods variants are
# regression guards confirmed-passing in vendor-compare-2.
PROBE_CASES = [
    {
        "label": "xbox_series_x",
        "upc": "889842640816",
        "expected_brand": "Microsoft",
        "expected_name_contains": ["Xbox Series X"],
    },
    {
        "label": "airpods_pro_2_usbc",
        "upc": "195949052484",
        "expected_brand": "Apple",
        "expected_name_contains": ["AirPods Pro"],
    },
    {
        "label": "airpods_pro_2",
        "upc": "194253397168",
        "expected_brand": "Apple",
        "expected_name_contains": ["AirPods Pro"],
    },
]

PROMPT_CURRENT = """You will identify a product from these search results for UPC barcode {upc}.

Use ONLY the snippets below. Do not invent. If the snippets are insufficient
to identify the product, return device_name: null.

Snippets:
{snippets}

Return STRICT JSON with this shape (no markdown, no commentary):
{{
  "device_name": "<full product name with brand>",
  "model": "<model number/identifier or null>",
  "chip": "<Apple silicon chip e.g. M4, M3 Pro, A18 Pro — null if not Apple>",
  "display_size_in": <integer inches for displays/tablets/laptops, null otherwise>
}}"""

PROMPT_HARDENED = """You will identify a product from these search results for UPC barcode {upc}.

Decision rule:
- If 3 or more snippets clearly name the same product, return that product's name.
- Only return device_name: null when snippets contradict each other OR when
  no snippets clearly name a single product.
- Do not invent details that aren't in the snippets.

Snippets:
{snippets}

Return STRICT JSON with this shape (no markdown, no commentary):
{{
  "device_name": "<full product name with brand>",
  "model": "<model number/identifier or null>",
  "chip": "<Apple silicon chip e.g. M4, M3 Pro, A18 Pro — null if not Apple>",
  "display_size_in": <integer inches for displays/tablets/laptops, null otherwise>
}}"""

PROMPTS = {"current": PROMPT_CURRENT, "hardened": PROMPT_HARDENED}

# Explicit thinking_budget integer values. -1 = dynamic (model decides);
# 0 = no thinking; positive = exact token budget cap.
THINKING_BUDGETS = [0, 256, 512, 1024, -1]


def _budget_label(budget: int) -> str:
    return "dynamic" if budget == -1 else str(budget)


# ── Cost estimate (USD per Gemini synthesis call). Order-of-magnitude. ──────
# Gemini 3 Flash Lite Preview ~$0.10/1M input, ~$0.40/1M output. Synthesis
# input is ~600 tokens (prompt + 5 snippets). Output is ~80 tokens (compact
# JSON). Thinking tokens are billed at the output rate. For thinking_budget=N
# the model burns somewhere between 0 and N thinking tokens internally;
# dynamic (-1) typically lands ~600-1500 on UPC tasks per the SDK telemetry.
def cost_per_call(thinking_budget: int) -> float:
    input_cost = 600 * 0.10 / 1_000_000
    visible_output_cost = 80 * 0.40 / 1_000_000
    if thinking_budget == 0:
        thinking_cost = 0.0
    elif thinking_budget == -1:
        thinking_cost = 1000 * 0.40 / 1_000_000  # dynamic: typical ~1k tokens
    else:
        thinking_cost = thinking_budget * 0.40 / 1_000_000  # cap = upper bound
    return input_cost + visible_output_cost + thinking_cost


# ── Gemini client (lazy singleton) ──────────────────────────────────────────
_gemini: genai.Client | None = None


def _get_gemini() -> genai.Client:
    global _gemini
    if _gemini is None:
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY not set in environment")
        _gemini = genai.Client(api_key=api_key)
    return _gemini


# ── Response helpers (mirror bench_vendor_compare.py) ───────────────────────
_FENCE_OPEN_RE = re.compile(r"^```(?:json)?\s*\n?")
_FENCE_CLOSE_RE = re.compile(r"\n?```\s*$")
_FIRST_OBJ_RE = re.compile(r"\{[\s\S]*\}", re.M)


def _extract_text(response) -> str:
    if not getattr(response, "candidates", None):
        return getattr(response, "text", "") or ""
    parts = response.candidates[0].content.parts
    text_parts = [p.text for p in parts if not getattr(p, "thought", False) and p.text]
    if text_parts:
        return "\n".join(text_parts)
    return getattr(response, "text", "") or ""


def _parse_json(raw: str) -> dict:
    if not raw:
        return {}
    cleaned = _FENCE_OPEN_RE.sub("", raw.strip())
    cleaned = _FENCE_CLOSE_RE.sub("", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        m = _FIRST_OBJ_RE.search(cleaned)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass
    return {}


async def synth_call(prompt: str, *, thinking_budget: int) -> dict:
    """Single non-grounded synthesis call with explicit thinking_budget."""
    client = _get_gemini()
    config = GenerateContentConfig(
        temperature=0.1,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        thinking_config=ThinkingConfig(thinking_budget=thinking_budget),
        tools=None,
    )
    t0 = time.perf_counter()
    try:
        response = await asyncio.wait_for(
            client.aio.models.generate_content(
                model=GEMINI_MODEL, contents=prompt, config=config,
            ),
            timeout=TIMEOUT_SEC,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000
        text = _extract_text(response)
        parsed = _parse_json(text)
        return {
            "device_name": parsed.get("device_name"),
            "raw_response": text[:1500],
            "latency_ms": elapsed_ms,
            "error": None,
        }
    except asyncio.TimeoutError:
        return {
            "device_name": None,
            "raw_response": "",
            "latency_ms": TIMEOUT_SEC * 1000,
            "error": "timeout",
        }
    except Exception as exc:
        return {
            "device_name": None,
            "raw_response": "",
            "latency_ms": (time.perf_counter() - t0) * 1000,
            "error": f"{type(exc).__name__}: {exc!r}",
        }


def matches(result: dict, case: dict) -> bool:
    name = (result.get("device_name") or "").lower()
    if not name:
        return False
    if case["expected_brand"].lower() not in name:
        return False
    return any(tok.lower() in name for tok in case["expected_name_contains"])


# ── Probe loop ──────────────────────────────────────────────────────────────
async def probe():
    serper = SerperClient()
    rows = []
    started_at = datetime.now(timezone.utc).isoformat()

    # 1 Serper call per UPC; reused across all combos × 5 runs.
    case_snippets: dict[str, str] = {}
    for case in PROBE_CASES:
        organic, _kg, serper_ms = await serper.fetch(case["upc"])
        snippets = format_snippets(organic, top=5)
        case_snippets[case["upc"]] = snippets
        print(
            f"[serper] {case['label']:>22} ({case['upc']}) "
            f"{serper_ms:.0f}ms organic={len(organic) if organic else 0}",
            file=sys.stderr,
        )

    combos = [
        (prompt_id, budget)
        for prompt_id in PROMPTS.keys()
        for budget in THINKING_BUDGETS
    ]
    total_calls = len(combos) * len(PROBE_CASES) * RUNS_PER_COMBO
    print(
        f"\n[probe] {len(combos)} combos × {len(PROBE_CASES)} cases × "
        f"{RUNS_PER_COMBO} runs = {total_calls} calls",
        file=sys.stderr,
    )

    call_n = 0
    for case in PROBE_CASES:
        snippets = case_snippets[case["upc"]]
        for prompt_id, budget in combos:
            template = PROMPTS[prompt_id]
            for run_idx in range(1, RUNS_PER_COMBO + 1):
                prompt = template.format(upc=case["upc"], snippets=snippets)
                result = await synth_call(prompt, thinking_budget=budget)
                pass_flag = matches(result, case)
                rows.append({
                    "case": case["label"],
                    "upc": case["upc"],
                    "prompt_id": prompt_id,
                    "thinking_budget": budget,
                    "run": run_idx,
                    "device_name": result["device_name"],
                    "matches_expected": pass_flag,
                    "latency_ms": result["latency_ms"],
                    "error": result["error"],
                    "raw_response": result["raw_response"],
                })
                call_n += 1
                tag = "PASS" if pass_flag else ("ERR" if result["error"] else "fail")
                if call_n % 10 == 0 or not pass_flag:
                    short = (result["device_name"] or "<null>")[:48]
                    print(
                        f"  [{call_n:>3}/{total_calls}] {case['label']:>22} "
                        f"{prompt_id:>9} budget={_budget_label(budget):>7} "
                        f"run{run_idx}: {tag:<4} {short}",
                        file=sys.stderr,
                    )

    completed_at = datetime.now(timezone.utc).isoformat()
    artifact = {
        "started_at": started_at,
        "completed_at": completed_at,
        "model": GEMINI_MODEL,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "runs_per_combo": RUNS_PER_COMBO,
        "cases": [c["label"] for c in PROBE_CASES],
        "combos": [
            {"prompt_id": p, "thinking_budget": b}
            for p, b in combos
        ],
        "results": rows,
    }
    safe_ts = completed_at.replace(":", "-").replace("+", "_")
    out_path = RESULTS_DIR / f"synthesis_grid_{safe_ts}.json"
    out_path.write_text(json.dumps(artifact, indent=2))
    print(f"\n[artifact] {out_path}", file=sys.stderr)

    print_summary(rows)
    return artifact


def _percentile(vals, p):
    if not vals:
        return 0.0
    s = sorted(vals)
    k = int(round(len(s) * p / 100)) - 1
    return s[max(0, min(k, len(s) - 1))]


def print_summary(rows):
    print()
    print("=" * 100)
    print("\n=== PER-COMBO PASS RATE (across all 3 cases) ===")
    print(
        f"  {'prompt':>9} {'budget':>8}   "
        f"{'xbox':>10} {'aprr_usbc':>10} {'aprr_2nd':>10}   "
        f"{'p50_ms':>7} {'p90_ms':>7} {'cost':>9}"
    )

    by_combo: dict[tuple, list] = {}
    for r in rows:
        key = (r["prompt_id"], r["thinking_budget"])
        by_combo.setdefault(key, []).append(r)

    winners = []
    for key in sorted(by_combo.keys(), key=lambda k: (k[0], k[1] if k[1] >= 0 else 9999)):
        prompt_id, budget = key
        combo_rows = by_combo[key]
        case_stats = {}
        for case_label in [c["label"] for c in PROBE_CASES]:
            crows = [r for r in combo_rows if r["case"] == case_label]
            case_stats[case_label] = (
                sum(1 for r in crows if r["matches_expected"]),
                len(crows),
            )
        latencies = [r["latency_ms"] for r in combo_rows if r["error"] is None]
        p50 = _percentile(latencies, 50)
        p90 = _percentile(latencies, 90)
        cost = cost_per_call(budget)
        xbox_h, xbox_t = case_stats["xbox_series_x"]
        ap1_h, ap1_t = case_stats["airpods_pro_2_usbc"]
        ap2_h, ap2_t = case_stats["airpods_pro_2"]
        all_pass = (xbox_h == xbox_t and ap1_h == ap1_t and ap2_h == ap2_t)
        marker = "  WINNER" if all_pass else ""
        print(
            f"  {prompt_id:>9} {_budget_label(budget):>8}   "
            f"{xbox_h}/{xbox_t:<8} {ap1_h}/{ap1_t:<8} {ap2_h}/{ap2_t:<8}   "
            f"{p50:>7.0f} {p90:>7.0f} ${cost:>7.5f}{marker}"
        )
        if all_pass:
            winners.append((cost, p50, key))

    # Speed comparison across all 5 thinking_budget values, averaged across
    # both prompt variants and all cases — answers "how much does each
    # thinking_budget actually cost in latency?"
    print()
    print("=== SPEED PER thinking_budget (all combos, all cases, all runs) ===")
    print(
        f"  {'budget':>8}   {'p50_ms':>7} {'p90_ms':>7} {'p99_ms':>7}   "
        f"{'mean_ms':>8}   {'n_calls':>8}"
    )
    for budget in THINKING_BUDGETS:
        b_rows = [r for r in rows if r["thinking_budget"] == budget and r["error"] is None]
        latencies = [r["latency_ms"] for r in b_rows]
        p50 = _percentile(latencies, 50)
        p90 = _percentile(latencies, 90)
        p99 = _percentile(latencies, 99)
        mean = sum(latencies) / len(latencies) if latencies else 0
        print(
            f"  {_budget_label(budget):>8}   "
            f"{p50:>7.0f} {p90:>7.0f} {p99:>7.0f}   "
            f"{mean:>8.0f}   {len(latencies):>8}"
        )

    # Per-case × per-budget recall — useful for spotting "Xbox needs ≥X budget"
    # vs "AirPods works at any budget."
    print()
    print("=== RECALL PER CASE × thinking_budget (hardened prompt only) ===")
    header = f"  {'budget':>8}"
    for case in PROBE_CASES:
        header += f"   {case['label']:>22}"
    print(header)
    for budget in THINKING_BUDGETS:
        line = f"  {_budget_label(budget):>8}"
        for case in PROBE_CASES:
            crows = [
                r for r in rows
                if r["prompt_id"] == "hardened"
                and r["thinking_budget"] == budget
                and r["case"] == case["label"]
            ]
            hits = sum(1 for r in crows if r["matches_expected"])
            line += f"   {hits:>2}/{len(crows):<2} ({100*hits/max(1,len(crows)):>3.0f}%)".rjust(25)
        print(line)

    print()
    if winners:
        winners.sort()
        cheapest_cost, _p50, (p, b) = winners[0]
        print(
            f"=== CHEAPEST WINNER: prompt={p} thinking_budget={_budget_label(b)} "
            f"(cost=${cheapest_cost:.5f}/call) ==="
        )
        print(f"  ({len(winners)} of {len(by_combo)} combos achieved 5/5 across all 3 cases)")
    else:
        print("=== NO WINNER — no combo achieved 5/5 across all 3 cases ===")
        print("  Inspect raw_response in the artifact JSON to diagnose.")


if __name__ == "__main__":
    asyncio.run(probe())
