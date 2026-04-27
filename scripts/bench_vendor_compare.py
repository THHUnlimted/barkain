#!/usr/bin/env python3
"""UPC Resolution Vendor Comparison Benchmark — bench/vendor-compare-1.

Diagnostic head-to-head against ``backend/ai/abstraction.py``'s production
Gemini leg. NOT a feature step. NOT promoted to ``backend/`` even after
the run. See ``Phase_3_Step_3g_Prompt_Package_v1.md`` v1.1 for the full
methodology.

Six configurations × 20-UPC catalog × 5 runs/config = 600 calls (cap).

Configurations:
- A_grounded_dynamic   : current production Gemini leg (the AI half of the
                         parallel ``asyncio.gather(Gemini, UPCitemdb)``).
                         Do NOT advertise A's p50 as full production p50.
- B_grounded_low       : grounding + ThinkingLevel.LOW
- C_no_ground_dynamic  : reasoning only, no web
- D_no_ground_low      : pure JSON synthesis from priors, ThinkingLevel.LOW
- E_serper_then_D      : Serper SERP → constrained Gemini (D's params)
- F_serper_kg_only     : Knowledge Graph extraction, no LLM

Run:
    python3 scripts/bench_vendor_compare.py
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

from _bench_serper import SerperClient, format_snippets  # noqa: E402

from google import genai  # noqa: E402
from google.genai.types import (  # noqa: E402
    GenerateContentConfig,
    GoogleSearch,
    ThinkingConfig,
    ThinkingLevel,
    Tool,
)

# ── Configuration ───────────────────────────────────────────────────────────
# Catalog path can be overridden via CLI: `python3 bench_vendor_compare.py
# --catalog scripts/bench_data/test_upcs_v2.json`. Default keeps the v1
# catalog so prior runs reproduce.
_DEFAULT_CATALOG = ROOT / "scripts" / "bench_data" / "test_upcs.json"
if "--catalog" in sys.argv:
    _idx = sys.argv.index("--catalog")
    CATALOG_PATH = Path(sys.argv[_idx + 1]).resolve()
else:
    CATALOG_PATH = _DEFAULT_CATALOG
RESULTS_DIR = ROOT / "scripts" / "bench_results"
GEMINI_MODEL = "gemini-3.1-flash-lite-preview"
RUNS_PER_CONFIG = 5
TIMEOUT_SEC = 30
MAX_CALLS = 600

CONFIGS = [
    "A_grounded_dynamic",
    "B_grounded_low",
    "C_no_ground_dynamic",
    "D_no_ground_low",
    "E_serper_then_D",
    "F_serper_kg_only",
]

# Rough per-call cost estimates (USD). Order-of-magnitude only — the bench
# does not measure tokens directly; refine these from the JSON artifact +
# current Gemini/Serper pricing pages before publishing the analysis doc.
COST_ESTIMATES_USD = {
    "A_grounded_dynamic": 0.064,
    "B_grounded_low": 0.040,
    "C_no_ground_dynamic": 0.012,
    "D_no_ground_low": 0.004,
    "E_serper_then_D": 0.0014,
    "F_serper_kg_only": 0.001,
}

UPC_LOOKUP_PROMPT = """Identify the consumer product with UPC barcode {upc}.

Return STRICT JSON with this shape (no markdown, no commentary):
{{
  "device_name": "<full product name with brand>",
  "model": "<model number/identifier or null>",
  "chip": "<Apple silicon chip e.g. M4, M3 Pro, A18 Pro — null if not Apple>",
  "display_size_in": <integer inches for displays/tablets/laptops, null otherwise>
}}

If you cannot identify the product, return device_name: null."""

SYNTHESIS_PROMPT = """You will identify a product from these search results for UPC barcode {upc}.

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


# ── Response helpers ────────────────────────────────────────────────────────
_FENCE_OPEN_RE = re.compile(r"^```(?:json)?\s*\n?")
_FENCE_CLOSE_RE = re.compile(r"\n?```\s*$")
_FIRST_OBJ_RE = re.compile(r"\{[\s\S]*\}", re.M)


def _extract_text(response) -> str:
    """Mirror ``backend/ai/abstraction.py``: strip thinking parts, keep text."""
    if not getattr(response, "candidates", None):
        return getattr(response, "text", "") or ""
    parts = response.candidates[0].content.parts
    text_parts = [p.text for p in parts if not getattr(p, "thought", False) and p.text]
    if text_parts:
        return "\n".join(text_parts)
    return getattr(response, "text", "") or ""


def _parse_json(raw: str) -> dict:
    """Mirror ``gemini_generate_json`` markdown stripping + fallback regex."""
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


def _coerce_int(v):
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _empty_result(error: str | None = None) -> dict:
    return {
        "device_name": None,
        "model": None,
        "chip": None,
        "display_size_in": None,
        "raw_response": "",
        "error": error,
    }


# ── Per-config Gemini wrapper ───────────────────────────────────────────────
async def _gemini_call(
    prompt: str,
    *,
    grounded: bool,
    thinking: str,  # "dynamic" | "low" | "off"
    max_output_tokens: int,
) -> dict:
    client = _get_gemini()
    tools = [Tool(google_search=GoogleSearch())] if grounded else None
    if thinking == "dynamic":
        tc = ThinkingConfig(thinking_budget=-1)
    elif thinking == "low":
        tc = ThinkingConfig(thinking_level=ThinkingLevel.LOW)
    else:
        tc = ThinkingConfig(thinking_budget=0)
    config = GenerateContentConfig(
        temperature=0.1,
        max_output_tokens=max_output_tokens,
        thinking_config=tc,
        tools=tools,
    )
    response = await client.aio.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=config,
    )
    text = _extract_text(response)
    parsed = _parse_json(text)
    return {
        "device_name": parsed.get("device_name"),
        "model": parsed.get("model"),
        "chip": parsed.get("chip"),
        "display_size_in": _coerce_int(parsed.get("display_size_in")),
        "raw_response": text[:2000],
        "error": None,
    }


# ── 6 config implementations ────────────────────────────────────────────────
async def run_a(case, organic, kg):
    return await _gemini_call(
        UPC_LOOKUP_PROMPT.format(upc=case["upc"]),
        grounded=True, thinking="dynamic", max_output_tokens=4096,
    )


async def run_b(case, organic, kg):
    return await _gemini_call(
        UPC_LOOKUP_PROMPT.format(upc=case["upc"]),
        grounded=True, thinking="low", max_output_tokens=4096,
    )


async def run_c(case, organic, kg):
    return await _gemini_call(
        UPC_LOOKUP_PROMPT.format(upc=case["upc"]),
        grounded=False, thinking="dynamic", max_output_tokens=1024,
    )


async def run_d(case, organic, kg):
    return await _gemini_call(
        UPC_LOOKUP_PROMPT.format(upc=case["upc"]),
        grounded=False, thinking="low", max_output_tokens=512,
    )


async def run_e(case, organic, kg):
    if not organic:
        return _empty_result("no_serper_organic")
    snip_text = format_snippets(organic, top=5)
    return await _gemini_call(
        SYNTHESIS_PROMPT.format(upc=case["upc"], snippets=snip_text),
        grounded=False, thinking="low", max_output_tokens=512,
    )


_KG_CHIP_RE = re.compile(r"\b(M[1-4](?:\s+(?:Pro|Max|Ultra))?)\b", re.I)
_KG_SIZE_RE = re.compile(r"\b(11|13|14|15|16)\s*-?\s*inch", re.I)


async def run_f(case, organic, kg):
    """KG extraction, no LLM. Returns empty when no KG block (expected; smoke
    test confirmed many UPCs have none)."""
    if not kg:
        return _empty_result()
    name = kg.get("title")
    if not name:
        return _empty_result()
    chip = None
    size = None
    attrs = kg.get("attributes") or {}
    haystack_blob = " ".join(str(v) for v in attrs.values()) + " " + (kg.get("description") or "")
    m = _KG_CHIP_RE.search(haystack_blob)
    if m:
        chip = m.group(1).upper().replace(" ", " ")
    m = _KG_SIZE_RE.search(haystack_blob)
    if m:
        size = int(m.group(1))
    return {
        "device_name": name,
        "model": kg.get("type"),
        "chip": chip,
        "display_size_in": size,
        "raw_response": json.dumps(kg)[:2000],
        "error": None,
    }


CONFIG_FUNCS = {
    "A_grounded_dynamic": run_a,
    "B_grounded_low": run_b,
    "C_no_ground_dynamic": run_c,
    "D_no_ground_low": run_d,
    "E_serper_then_D": run_e,
    "F_serper_kg_only": run_f,
}


# ── Timer wrapper (perf_counter, monotonic) ─────────────────────────────────
async def _timed_call(coro):
    """Run an awaitable with a timeout. Returns (result_dict, elapsed_ms, error)."""
    t0 = time.perf_counter()
    try:
        result = await asyncio.wait_for(coro, timeout=TIMEOUT_SEC)
        return result, (time.perf_counter() - t0) * 1000, None
    except asyncio.TimeoutError:
        return _empty_result("timeout"), TIMEOUT_SEC * 1000, "timeout"
    except Exception as exc:
        envelope = f"{type(exc).__name__}: {exc!r}"
        return _empty_result(envelope), (time.perf_counter() - t0) * 1000, envelope


# ── Validation (Group E) ────────────────────────────────────────────────────
def validate(result: dict, case: dict) -> bool:
    """Recall + L4 brand/spec + Apple Rule 2c (chip) + Rule 2d (size).

    Mirrors production gates (``backend/modules/m1_product/service.py:_resolved_matches_query``
    and ``_apple_variant`` rules). Disagreement-only — chip omission on either side is
    allowed; chip mismatch is rejected.
    """
    if case["difficulty"] == "invalid":
        return result.get("device_name") is None
    if not result.get("device_name"):
        return False
    name_lower = result["device_name"].lower()
    haystack = f"{name_lower} {(result.get('model') or '').lower()}"
    # L-cat-rel-1 brand check
    if case["expected_brand"].lower() not in haystack:
        return False
    # L-cat-rel-1 token check (any-of)
    expected_tokens = case.get("expected_name_contains") or []
    if expected_tokens and not any(tok.lower() in haystack for tok in expected_tokens):
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


def apple_variant_check(result: dict, case: dict) -> str | None:
    """Telemetry: which Apple-variant rule (if any) would have fired.

    Disagreement-only — returns None when either side omits the value.
    Used purely for the ``apple_variant_rejected`` column on each row.
    """
    if case.get("expected_chip"):
        rc = (result.get("chip") or "").upper()
        if rc and rc != case["expected_chip"].upper():
            return "rule_2c"
    if case.get("expected_display_size_in"):
        rs = result.get("display_size_in")
        if rs and rs != case["expected_display_size_in"]:
            return "rule_2d"
    return None


# ── Summary helpers (Group F) ───────────────────────────────────────────────
def percentile(vals, p):
    """Inclusive nearest-rank percentile. Empty input → 0.0."""
    if not vals:
        return 0.0
    s = sorted(vals)
    k = int(round(len(s) * p / 100)) - 1
    if k < 0:
        k = 0
    if k >= len(s):
        k = len(s) - 1
    return s[k]


def warm_rows(rows, config_id):
    """Filter to non-cold rows for a config (cold runs excluded from p50/p90/p99)."""
    return [r for r in rows if r["config"] == config_id and not r["is_cold"]]


def recall_stats(warm, *, exclude_invalid=True):
    """Returns (hits, total) on the recall-eligible rows."""
    pool = warm if not exclude_invalid else [r for r in warm if r["difficulty"] != "invalid"]
    hits = sum(1 for r in pool if r["matches_expected"])
    return hits, len(pool)


def print_summary(rows):
    print()
    print("=" * 70)
    for cfg in CONFIGS:
        warm = warm_rows(rows, cfg)
        all_cfg = [r for r in rows if r["config"] == cfg]
        successful = [r for r in warm if r["error"] is None]
        recall_hits, recall_total = recall_stats(warm)
        invalid = [r for r in warm if r["difficulty"] == "invalid"]
        invalid_pass = sum(1 for r in invalid if r["matches_expected"])
        latencies = [r["total_latency_ms"] for r in warm if r["error"] is None]
        timeouts = sum(1 for r in all_cfg if r["error"] == "timeout")
        rule_2c = sum(1 for r in warm if r["apple_variant_rejected"] == "rule_2c")
        rule_2d = sum(1 for r in warm if r["apple_variant_rejected"] == "rule_2d")
        print(f"\n=== {cfg} ===")
        print(f"  Successful runs:      {len(successful)}/{len(warm)} ({100*len(successful)/max(1,len(warm)):.1f}%)")
        print(f"  Recall (non-invalid): {recall_hits}/{recall_total} ({100*recall_hits/max(1,recall_total):.1f}%)")
        print(f"  Invalid-pattern PASS: {invalid_pass}/{len(invalid)}")
        print(f"  Apple variant rejects: rule_2c={rule_2c}  rule_2d={rule_2d}")
        if latencies:
            print(f"  Latency p50:          {percentile(latencies, 50):.0f} ms")
            print(f"  Latency p90:          {percentile(latencies, 90):.0f} ms")
            print(f"  Latency p99:          {percentile(latencies, 99):.0f} ms")
        print(f"  Timeouts:             {timeouts}")
        print(f"  Est. cost / call:     ${COST_ESTIMATES_USD[cfg]:.4f}")

    # Head-to-head
    print()
    print("=" * 70)
    _head_to_head(rows, "A_grounded_dynamic", "E_serper_then_D")
    _head_to_head(rows, "A_grounded_dynamic", "F_serper_kg_only")

    # Per-difficulty breakdown
    print()
    print("=" * 70)
    print("\n=== RECALL BY DIFFICULTY (warm runs only) ===")
    print(f"  {'config':<25} {'flagship':>13} {'mid':>13} {'obscure':>13} {'invalid':>13}")
    for cfg in CONFIGS:
        warm = warm_rows(rows, cfg)
        cells = [f"  {cfg:<25}"]
        for diff in ["flagship", "mid", "obscure", "invalid"]:
            d_rows = [r for r in warm if r["difficulty"] == diff]
            hits = sum(1 for r in d_rows if r["matches_expected"])
            total = len(d_rows)
            cells.append(f"{hits}/{total} ({100*hits/max(1,total):.0f}%)".rjust(13))
        print(" ".join(cells))

    # Per-Apple-pair breakdown — load catalog to know which UPCs have chip / size tags
    catalog = json.loads(CATALOG_PATH.read_text())
    chip_upcs = {c["upc"] for c in catalog if c.get("expected_chip")}
    size_upcs = {c["upc"] for c in catalog if c.get("expected_display_size_in")}
    print()
    print("=== APPLE-VARIANT PAIR ACCURACY (warm runs only) ===")
    print(f"  {'config':<25} {'chip_recall':>14} {'size_recall':>14} {'2c_rej':>10} {'2d_rej':>10}")
    for cfg in CONFIGS:
        warm = warm_rows(rows, cfg)
        chip_pool = [r for r in warm if r["upc"] in chip_upcs]
        size_pool = [r for r in warm if r["upc"] in size_upcs]
        chip_hits = sum(1 for r in chip_pool if r["matches_expected"])
        size_hits = sum(1 for r in size_pool if r["matches_expected"])
        rule_2c_n = sum(1 for r in warm if r["apple_variant_rejected"] == "rule_2c")
        rule_2d_n = sum(1 for r in warm if r["apple_variant_rejected"] == "rule_2d")
        cells = [
            f"  {cfg:<25}",
            f"{chip_hits}/{len(chip_pool)}".rjust(14),
            f"{size_hits}/{len(size_pool)}".rjust(14),
            str(rule_2c_n).rjust(10),
            str(rule_2d_n).rjust(10),
        ]
        print(" ".join(cells))


def _head_to_head(rows, a_id, b_id):
    a_warm = [r for r in warm_rows(rows, a_id) if r["error"] is None]
    b_warm = [r for r in warm_rows(rows, b_id) if r["error"] is None]
    if not (a_warm and b_warm):
        print(f"\n=== HEAD-TO-HEAD: {a_id} vs {b_id} ===")
        print("  (insufficient data — one or both configs had all errors)")
        return
    a_lat = [r["total_latency_ms"] for r in a_warm]
    b_lat = [r["total_latency_ms"] for r in b_warm]
    a_p50, b_p50 = percentile(a_lat, 50), percentile(b_lat, 50)
    a_p90, b_p90 = percentile(a_lat, 90), percentile(b_lat, 90)
    a_recall_hits, a_recall_total = recall_stats(warm_rows(rows, a_id))
    b_recall_hits, b_recall_total = recall_stats(warm_rows(rows, b_id))
    a_pp = 100 * a_recall_hits / max(1, a_recall_total)
    b_pp = 100 * b_recall_hits / max(1, b_recall_total)
    cost_a = COST_ESTIMATES_USD[a_id]
    cost_b = COST_ESTIMATES_USD[b_id]
    print(f"\n=== HEAD-TO-HEAD: {a_id} vs {b_id} ===")
    print(f"  p50 latency: {a_p50:.0f}  → {b_p50:.0f} ms  ({100*(a_p50-b_p50)/max(1,a_p50):+.1f}%)")
    print(f"  p90 latency: {a_p90:.0f}  → {b_p90:.0f} ms  ({100*(a_p90-b_p90)/max(1,a_p90):+.1f}%)")
    print(f"  Recall:      {a_recall_hits}/{a_recall_total} ({a_pp:.1f}%)  →  {b_recall_hits}/{b_recall_total} ({b_pp:.1f}%)  ({b_pp-a_pp:+.1f} pp)")
    print(f"  Cost/call:   ${cost_a:.4f}  →  ${cost_b:.4f}  ({100*(cost_a-cost_b)/max(1e-6,cost_a):+.1f}%)")


# ── Main loop ───────────────────────────────────────────────────────────────
async def benchmark():
    catalog = json.loads(CATALOG_PATH.read_text())
    serper = SerperClient()
    rows = []
    call_count = 0
    started_at = datetime.now(timezone.utc).isoformat()
    aborted = False

    for case_idx, case in enumerate(catalog, start=1):
        # One Serper call per UPC, cached across E + F
        organic, kg, serper_ms = await serper.fetch(case["upc"])
        print(
            f"[{case_idx:>2}/{len(catalog)}] UPC {case['upc']} ({case['difficulty']:<8}) "
            f"serper={serper_ms:.0f}ms organic={len(organic) if organic else 0} kg={bool(kg)}",
            file=sys.stderr,
        )

        for run_idx in range(1, RUNS_PER_CONFIG + 1):
            for config_id in CONFIGS:
                if call_count >= MAX_CALLS:
                    print(f"[ABORT] hit MAX_CALLS={MAX_CALLS}", file=sys.stderr)
                    aborted = True
                    break
                func = CONFIG_FUNCS[config_id]
                result, elapsed_ms, err = await _timed_call(func(case, organic, kg))
                total_ms = elapsed_ms + (
                    serper_ms if config_id == "E_serper_then_D" else 0
                )
                rows.append({
                    "config": config_id,
                    "upc": case["upc"],
                    "difficulty": case["difficulty"],
                    "category": case.get("category"),
                    "run": run_idx,
                    "is_cold": run_idx == 1,
                    "latency_ms": elapsed_ms,
                    "total_latency_ms": total_ms,
                    "serper_latency_ms": (
                        serper_ms
                        if config_id in {"E_serper_then_D", "F_serper_kg_only"}
                        else None
                    ),
                    "device_name": result.get("device_name"),
                    "model": result.get("model"),
                    "chip": result.get("chip"),
                    "display_size_in": result.get("display_size_in"),
                    "matches_expected": validate(result, case),
                    "apple_variant_rejected": apple_variant_check(result, case),
                    "error": err,
                })
                call_count += 1
                if call_count % 50 == 0:
                    print(f"  [progress] {call_count} calls done", file=sys.stderr)
            if aborted:
                break
        if aborted:
            break

    completed_at = datetime.now(timezone.utc).isoformat()
    artifact = {
        "started_at": started_at,
        "completed_at": completed_at,
        "catalog_size": len(catalog),
        "configs": CONFIGS,
        "runs_per_config": RUNS_PER_CONFIG,
        "production_baseline_note": (
            "Config A is the Gemini leg of asyncio.gather(Gemini, UPCitemdb). "
            "Production p50 is min(A_p50, UPCitemdb_p50). See L-search-perf."
        ),
        "cost_estimates_usd": COST_ESTIMATES_USD,
        "results": rows,
    }
    safe_ts = completed_at.replace(":", "-").replace("+", "_")
    out_path = RESULTS_DIR / f"bench_{safe_ts}.json"
    out_path.write_text(json.dumps(artifact, indent=2))
    print(f"\n[artifact] {out_path}", file=sys.stderr)

    print_summary(rows)
    return artifact


if __name__ == "__main__":
    asyncio.run(benchmark())
