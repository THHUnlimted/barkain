#!/usr/bin/env python3
"""Dual-filter catalog pre-validation for bench/vendor-compare-2.

The vendor-compare-1 catalog (PR #74) was synthesized from UPC prefix-block
matching without UPCitemdb verification — 16 of 18 non-invalid UPCs did not
resolve to their labeled products on grounded Gemini, contaminating the
recall comparison.

The mini-bench (PR #75) added a UPCitemdb pre-validation gate but discovered
that UPCitemdb-validated does not imply Gemini-resolvable — Galaxy Buds R170N
(UPC 732554340133) is in UPCitemdb but Gemini's grounded search returns
"Goodcook 20434 Can Opener" because UPCs aren't globally unique cross-brand.

This script applies BOTH filters before vendor-compare-2 burns its $5-15
budget on contaminated inputs:

  Filter 1 — UPCitemdb has a record, response brand/title contains the
             expected brand token.
  Filter 2 — Gemini A-config (grounded + dynamic thinking) resolution agrees
             with the expected brand AND name token.

Survivors are written to scripts/bench_data/test_upcs_v2.json in the same
schema as vendor-compare-1's catalog. Drops are logged to
scripts/bench_results/prevalidate_v2_drops_<UTC>.json so we can audit.

Run:
    python3 scripts/bench_prevalidate_v2.py
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

# Reuse the production-aligned Gemini call shape from the bench harness so
# Filter 2's verdict matches what config A would return during the bench itself.
from bench_vendor_compare import UPC_LOOKUP_PROMPT, _gemini_call  # noqa: E402

OUT_CATALOG = ROOT / "scripts" / "bench_data" / "test_upcs_v2.json"
OUT_DROPS = ROOT / "scripts" / "bench_results"
UPCITEMDB_TRIAL_URL = "https://api.upcitemdb.com/prod/trial/lookup"

# ── Candidate pool ───────────────────────────────────────────────────────────
# Sourcing strategy:
#   - Apple AirPods family (4 UPCs already UPCitemdb-validated in mini-bench)
#   - Apple iPad/MacBook (from v1 catalog — UPCitemdb has them; Step 2 will
#     surface the Galaxy-Buds-class collisions)
#   - High-indexing consumer electronics from scripts/test_upc_lookup.py CATALOG
#   - Mid-difficulty real-world products from v1 catalog
#   - 1 known-canary (Galaxy Buds R170N) to verify Filter 2 catches the Goodcook
#     collision
#   - 2 invalid pattern UPCs (skip both filters; null is a PASS at bench time)
#
# Each non-invalid entry MUST have expected_brand + expected_name_contains
# for the validate() gate at bench time. Apple variants get expected_chip /
# expected_display_size_in for Rule 2c/2d coverage.
CANDIDATES: list[dict] = [
    # ── Apple AirPods family (mini-bench-validated) ─────────────────────
    {
        "upc": "194253397168",
        "expected_brand": "Apple",
        "expected_name_contains": ["AirPods Pro"],
        "label": "AirPods Pro 2nd Gen",
        "category": "audio",
        "difficulty": "flagship",
    },
    {
        "upc": "190199246850",
        "expected_brand": "Apple",
        "expected_name_contains": ["AirPods Pro"],
        "label": "AirPods Pro 1st Gen",
        "category": "audio",
        "difficulty": "flagship",
    },
    {
        "upc": "190199098428",
        "expected_brand": "Apple",
        "expected_name_contains": ["AirPods"],
        "label": "AirPods 2nd Gen",
        "category": "audio",
        "difficulty": "flagship",
    },
    {
        "upc": "195949052484",
        "expected_brand": "Apple",
        "expected_name_contains": ["AirPods Pro"],
        "label": "AirPods Pro 2 USB-C",
        "category": "audio",
        "difficulty": "flagship",
    },
    {
        "upc": "194252721247",
        "expected_brand": "Apple",
        "expected_name_contains": ["AirPods Pro"],
        "label": "AirPods Pro 1st Gen MagSafe",
        "category": "audio",
        "difficulty": "flagship",
    },
    # ── Apple iPad / MacBook (Apple Rule 2c/2d coverage) ────────────────
    # Note: 194253401735 / 195949691102 / 194252056639 dropped — not in
    # UPCitemdb trial DB. UPC 195949257308 is iPad Air M2 13" per UPCitemdb,
    # NOT iPad Pro M4 11" as v1 catalog claimed; we use UPCitemdb's record
    # as the ground-truth label.
    {
        "upc": "195949257308",
        "expected_brand": "Apple",
        "expected_name_contains": ["iPad Air"],
        "expected_chip": "M2",
        "expected_display_size_in": 13,
        "label": "iPad Air 13-inch M2 (2024)",
        "category": "tablet",
        "difficulty": "flagship",
    },
    # ── Consumer electronics (high-indexing) ────────────────────────────
    {
        "upc": "848061073966",
        "expected_brand": "JBL",
        "expected_name_contains": ["Flip 6"],
        "label": "JBL Flip 6 speaker",
        "category": "audio",
        "difficulty": "flagship",
    },
    {
        "upc": "017817841634",
        "expected_brand": "Bose",
        "expected_name_contains": ["QuietComfort", "QC45"],
        "label": "Bose QuietComfort 45",
        "category": "audio",
        "difficulty": "flagship",
    },
    {
        "upc": "097855171191",
        "expected_brand": "Nintendo",
        "expected_name_contains": ["Pro Controller"],
        "label": "Switch Pro Controller",
        "category": "console",
        "difficulty": "flagship",
    },
    {
        "upc": "711719577331",
        "expected_brand": "Sony",
        "expected_name_contains": ["PS5", "PlayStation 5"],
        "label": "PS5 Slim",
        "category": "console",
        "difficulty": "flagship",
    },
    # ── Samsung canary (UPCitemdb says Galaxy Buds; Gemini grounded says
    #    Goodcook can opener — Filter 2 should drop this) ────────────────
    {
        "upc": "732554340133",
        "expected_brand": "Samsung",
        "expected_name_contains": ["Galaxy Buds"],
        "label": "Galaxy Buds R170N (canary — Gemini collision expected)",
        "category": "audio",
        "difficulty": "flagship",
    },
    {
        "upc": "887276752815",
        "expected_brand": "Samsung",
        "expected_name_contains": ["Galaxy S24"],
        "label": "Galaxy S24 Ultra",
        "category": "phone",
        "difficulty": "flagship",
    },
    # ── Mid-difficulty appliances / tools / peripherals ─────────────────
    {
        "upc": "883049010113",
        "expected_brand": "KitchenAid",
        "expected_name_contains": ["Artisan", "Stand Mixer"],
        "label": "KitchenAid Artisan stand mixer",
        "category": "kitchen",
        "difficulty": "mid",
    },
    {
        "upc": "885911685320",
        "expected_brand": "DEWALT",
        "expected_name_contains": ["DCD800", "20V"],
        "label": "DeWalt DCD800B 20V drill",
        "category": "tools",
        "difficulty": "mid",
    },
    {
        "upc": "878269009993",
        "expected_brand": "Sonos",
        "expected_name_contains": ["Era 100"],
        "label": "Sonos Era 100",
        "category": "audio",
        "difficulty": "mid",
    },
    # UPC 885609020013 is Dyson V11 Torque Drive per UPCitemdb, NOT V15
    # Detect as v1 catalog claimed; we use UPCitemdb's record as ground truth.
    {
        "upc": "885609020013",
        "expected_brand": "Dyson",
        "expected_name_contains": ["V11"],
        "label": "Dyson V11 Torque Drive",
        "category": "appliance",
        "difficulty": "mid",
    },
    {
        "upc": "195174037102",
        "expected_brand": "LG",
        "expected_name_contains": ["27GR95QE", "UltraGear"],
        "label": "LG 27GR95QE UltraGear monitor",
        "category": "monitor",
        "difficulty": "mid",
    },
    {
        "upc": "840148735408",
        "expected_brand": "Keychron",
        "expected_name_contains": ["Q1"],
        "label": "Keychron Q1 keyboard",
        "category": "peripherals",
        "difficulty": "mid",
    },
    # ── Additional well-indexed candidates (sourcing for v2 expansion) ──
    {
        "upc": "190199706101",
        "expected_brand": "Apple",
        "expected_name_contains": ["AirPods Max"],
        "label": "AirPods Max Silver",
        "category": "audio",
        "difficulty": "flagship",
    },
    {
        "upc": "194253829430",
        "expected_brand": "Apple",
        "expected_name_contains": ["Apple Watch Ultra"],
        "label": "Apple Watch Ultra 2 49mm",
        "category": "wearable",
        "difficulty": "flagship",
    },
    {
        "upc": "190199233492",
        "expected_brand": "Apple",
        "expected_name_contains": ["Pencil"],
        "label": "Apple Pencil 2nd gen",
        "category": "accessory",
        "difficulty": "flagship",
    },
    {
        "upc": "194252582510",
        "expected_brand": "Apple",
        "expected_name_contains": ["AirTag"],
        "label": "AirTag 4-pack",
        "category": "accessory",
        "difficulty": "flagship",
    },
    {
        "upc": "889842640816",
        "expected_brand": "Microsoft",
        "expected_name_contains": ["Xbox Series X"],
        "label": "Xbox Series X console",
        "category": "console",
        "difficulty": "flagship",
    },
    {
        "upc": "889842611564",
        "expected_brand": "Microsoft",
        "expected_name_contains": ["Xbox Wireless Controller"],
        "label": "Xbox Wireless Controller Carbon Black",
        "category": "console",
        "difficulty": "flagship",
    },
    {
        "upc": "097855179807",
        "expected_brand": "Logitech",
        "expected_name_contains": ["MX Master"],
        "label": "Logitech MX Master 3S",
        "category": "peripherals",
        "difficulty": "flagship",
    },
    {
        "upc": "097855170095",
        "expected_brand": "Logitech",
        "expected_name_contains": ["G502"],
        "label": "Logitech G502 X Plus",
        "category": "peripherals",
        "difficulty": "flagship",
    },
    {
        "upc": "045496883843",
        "expected_brand": "Nintendo",
        "expected_name_contains": ["Switch", "OLED"],
        "label": "Nintendo Switch OLED White",
        "category": "console",
        "difficulty": "flagship",
    },
    {
        "upc": "711719541073",
        "expected_brand": "Sony",
        "expected_name_contains": ["DualSense"],
        "label": "DualSense PS5 Controller",
        "category": "console",
        "difficulty": "flagship",
    },
    {
        "upc": "197223999166",
        "expected_brand": "Beats",
        "expected_name_contains": ["Studio Buds"],
        "label": "Beats Studio Buds Plus Black",
        "category": "audio",
        "difficulty": "flagship",
    },
    {
        "upc": "190199233614",
        "expected_brand": "Apple",
        "expected_name_contains": ["Magic Keyboard"],
        "label": "Apple Magic Keyboard",
        "category": "peripherals",
        "difficulty": "flagship",
    },
    {
        "upc": "195949013690",
        "expected_brand": "Apple",
        "expected_name_contains": ["Apple Watch"],
        "label": "Apple Watch Series 9 41mm",
        "category": "wearable",
        "difficulty": "flagship",
    },
    {
        "upc": "194253437970",
        "expected_brand": "Apple",
        "expected_name_contains": ["MagSafe"],
        "label": "Apple MagSafe Charger",
        "category": "accessory",
        "difficulty": "mid",
    },
    # ── Invalid pattern UPCs (skip both filters; null is a PASS) ────────
    {
        "upc": "111111111111",
        "expected_brand": "(invalid)",
        "expected_name_contains": [],
        "label": "pattern UPC 111…",
        "category": "invalid",
        "difficulty": "invalid",
    },
    {
        "upc": "222222222222",
        "expected_brand": "(invalid)",
        "expected_name_contains": [],
        "label": "pattern UPC 222…",
        "category": "invalid",
        "difficulty": "invalid",
    },
]


# ── Filter 1: UPCitemdb ─────────────────────────────────────────────────────
class RateLimitExhausted(Exception):
    """Raised when UPCitemdb returns 429 after all retries."""


async def upcitemdb_lookup(upc: str, *, max_retries: int = 4) -> dict | None:
    """Hit UPCitemdb's trial endpoint. Retry on 429 with 5/15/45/90s backoff.

    Returns:
      dict with name/brand/category on success
      None for genuine "no item" responses
      Raises RateLimitExhausted when 429 persists past all retries (caller
        treats this differently from a true empty result so it can retry later).
    """
    delay = 5.0
    for attempt in range(1, max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(UPCITEMDB_TRIAL_URL, params={"upc": upc})
                if resp.status_code == 429:
                    if attempt < max_retries:
                        print(f"    [retry {attempt}/{max_retries}] {upc}: 429 — sleep {delay:.0f}s")
                        await asyncio.sleep(delay)
                        delay *= 3
                        continue
                    raise RateLimitExhausted(f"{upc}: rate-limited after {max_retries} retries")
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
        except RateLimitExhausted:
            raise
        except Exception as exc:
            print(f"    [!] {upc}: UPCitemdb error {type(exc).__name__}: {exc!r}")
            return None
    return None


# Inter-call throttle: keeps us under UPCitemdb's per-minute cap on the trial
# tier. Empirically ~1 req/sec is the sustainable rate. 1.5s is conservative.
INTER_CALL_SLEEP_SEC = 1.5


async def filter_upcitemdb(candidates: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """Filter 1: brand-match against UPCitemdb's response.

    Returns (kept, dropped_no_item, rate_limited). The rate_limited bucket is
    inconclusive (couldn't verify either way) — caller can retry these later.
    """
    print("\n=== Filter 1: UPCitemdb brand-match ===")
    kept: list[dict] = []
    dropped: list[dict] = []
    rate_limited: list[dict] = []
    for idx, cand in enumerate(candidates):
        if cand["difficulty"] == "invalid":
            kept.append(cand)
            continue
        if idx > 0:
            await asyncio.sleep(INTER_CALL_SLEEP_SEC)
        try:
            ud = await upcitemdb_lookup(cand["upc"])
        except RateLimitExhausted as exc:
            print(f"  [RATE_LIMITED] {cand['upc']} ({cand['label']}): {exc}")
            rate_limited.append({**cand, "filter1_outcome": "rate_limited"})
            continue
        if not ud:
            print(f"  [DROP] {cand['upc']} ({cand['label']}): genuinely no UPCitemdb item")
            dropped.append({**cand, "filter1_drop_reason": "no_upcitemdb_item"})
            continue
        brand_lower = (ud.get("brand") or "").lower()
        name_lower = (ud.get("name") or "").lower()
        expected = cand["expected_brand"].lower()
        if expected not in brand_lower and expected not in name_lower:
            print(
                f"  [DROP] {cand['upc']} ({cand['label']}): brand "
                f"'{ud.get('brand')}' / name '{(ud.get('name') or '')[:60]}' "
                f"missing '{cand['expected_brand']}'"
            )
            dropped.append({
                **cand,
                "filter1_drop_reason": "brand_mismatch",
                "upcitemdb_brand": ud.get("brand"),
                "upcitemdb_name": ud.get("name"),
            })
            continue
        print(f"  [KEEP] {cand['upc']} ({cand['label']}) → {ud.get('brand')} / {(ud.get('name') or '')[:55]}")
        kept.append({
            **cand,
            "upcitemdb_brand": ud.get("brand"),
            "upcitemdb_name": ud.get("name"),
            "upcitemdb_category": ud.get("category"),
        })
    return kept, dropped, rate_limited


# ── Filter 2: Gemini grounded agreement ─────────────────────────────────────
def _gemini_agrees(result: dict, cand: dict) -> tuple[bool, str]:
    """Returns (agrees, reason). Mirrors validate() but as a filter, not a bench gate."""
    if not result.get("device_name"):
        return False, "device_name=null"
    name = (result.get("device_name") or "").lower()
    model = (result.get("model") or "").lower()
    haystack = f"{name} {model}"
    if cand["expected_brand"].lower() not in haystack:
        return False, f"brand '{cand['expected_brand']}' missing from '{name}'"
    if not any(tok.lower() in haystack for tok in cand["expected_name_contains"]):
        return False, f"name tokens {cand['expected_name_contains']} missing from '{name}'"
    if cand.get("expected_chip"):
        result_chip = (result.get("chip") or "").upper()
        if result_chip and result_chip != cand["expected_chip"].upper():
            return False, f"chip {result_chip} ≠ expected {cand['expected_chip']}"
    if cand.get("expected_display_size_in"):
        result_size = result.get("display_size_in")
        if result_size and result_size != cand["expected_display_size_in"]:
            return False, f"display_size {result_size} ≠ expected {cand['expected_display_size_in']}"
    return True, "ok"


async def filter_gemini(candidates: list[dict]) -> tuple[list[dict], list[dict]]:
    """Filter 2: A-config probe; require name+brand+chip+size agreement."""
    print("\n=== Filter 2: Gemini grounded-agreement (A-config probe) ===")
    kept: list[dict] = []
    dropped: list[dict] = []
    for cand in candidates:
        if cand["difficulty"] == "invalid":
            kept.append(cand)
            continue
        try:
            result = await _gemini_call(
                UPC_LOOKUP_PROMPT.format(upc=cand["upc"]),
                grounded=True,
                thinking="dynamic",
                max_output_tokens=4096,
            )
        except Exception as exc:
            print(f"  [DROP] {cand['upc']} ({cand['label']}): Gemini error {type(exc).__name__}")
            dropped.append({**cand, "filter2_drop_reason": f"gemini_error_{type(exc).__name__}"})
            continue
        agrees, reason = _gemini_agrees(result, cand)
        if not agrees:
            print(
                f"  [DROP] {cand['upc']} ({cand['label']}): Gemini "
                f"returned {result.get('device_name')!r} chip={result.get('chip')} "
                f"size={result.get('display_size_in')} — {reason}"
            )
            dropped.append({
                **cand,
                "filter2_drop_reason": reason,
                "gemini_device_name": result.get("device_name"),
                "gemini_model": result.get("model"),
                "gemini_chip": result.get("chip"),
                "gemini_display_size_in": result.get("display_size_in"),
            })
            continue
        print(
            f"  [KEEP] {cand['upc']} ({cand['label']}) → Gemini agrees: "
            f"{result.get('device_name')!r}"
        )
        kept.append({
            **cand,
            "gemini_device_name": result.get("device_name"),
            "gemini_model": result.get("model"),
            "gemini_chip": result.get("chip"),
            "gemini_display_size_in": result.get("display_size_in"),
        })
    return kept, dropped


# ── Output writers ──────────────────────────────────────────────────────────
def write_catalog(survivors: list[dict]) -> None:
    """Strip the prevalidation metadata, write the bench-runner schema."""
    bench_entries = []
    for s in survivors:
        entry = {
            "upc": s["upc"],
            "expected_brand": s["expected_brand"],
            "expected_name_contains": s["expected_name_contains"],
            "category": s.get("category"),
            "difficulty": s["difficulty"],
        }
        if "expected_chip" in s:
            entry["expected_chip"] = s["expected_chip"]
        if "expected_display_size_in" in s:
            entry["expected_display_size_in"] = s["expected_display_size_in"]
        bench_entries.append(entry)
    OUT_CATALOG.parent.mkdir(parents=True, exist_ok=True)
    OUT_CATALOG.write_text(json.dumps(bench_entries, indent=2))
    print(f"\n[catalog] wrote {len(bench_entries)} entries → {OUT_CATALOG}")


def write_drops(filter1_drops: list[dict], filter2_drops: list[dict]) -> Path:
    completed_at = datetime.now(timezone.utc).isoformat()
    safe_ts = completed_at.replace(":", "-").replace("+", "_")
    out_path = OUT_DROPS / f"prevalidate_v2_drops_{safe_ts}.json"
    out_path.write_text(json.dumps({
        "completed_at": completed_at,
        "filter1_upcitemdb_drops": filter1_drops,
        "filter2_gemini_drops": filter2_drops,
    }, indent=2))
    return out_path


# ── Main ────────────────────────────────────────────────────────────────────
INTERMEDIATE_PATH = ROOT / "scripts" / "bench_results" / "prevalidate_v2_after_f1.json"


async def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "both"
    if mode not in {"both", "f1", "f2"}:
        print(f"Usage: {sys.argv[0]} [both|f1|f2]")
        sys.exit(2)

    if mode in {"both", "f1"}:
        # If a prior intermediate has rate-limited UPCs we can re-probe them
        # without re-running already-classified candidates.
        if INTERMEDIATE_PATH.exists() and "--retry-rate-limited" in sys.argv:
            snap = json.loads(INTERMEDIATE_PATH.read_text())
            prior_kept = snap.get("kept", [])
            prior_dropped = snap.get("dropped", [])
            to_retry = snap.get("rate_limited", [])
            print(f"=== Retrying {len(to_retry)} rate-limited UPCs from {INTERMEDIATE_PATH.name} ===")
            retry_kept, retry_dropped, still_limited = await filter_upcitemdb(to_retry)
            after_f1 = prior_kept + [k for k in retry_kept if k not in prior_kept]
            f1_drops = prior_dropped + retry_dropped
            f1_rate_limited = still_limited
        else:
            print(f"=== Pre-validating {len(CANDIDATES)} candidates "
                  f"({sum(1 for c in CANDIDATES if c['difficulty'] != 'invalid')} non-invalid) ===")
            after_f1, f1_drops, f1_rate_limited = await filter_upcitemdb(CANDIDATES)
        INTERMEDIATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        INTERMEDIATE_PATH.write_text(json.dumps({
            "kept": after_f1,
            "dropped": f1_drops,
            "rate_limited": f1_rate_limited,
        }, indent=2))
        print(f"\n[f1-intermediate] wrote {INTERMEDIATE_PATH}")
        print(f"  kept:         {len(after_f1)}")
        print(f"  dropped:      {len(f1_drops)}")
        print(f"  rate_limited: {len(f1_rate_limited)} (inconclusive — re-run with --retry-rate-limited)")
    else:
        if not INTERMEDIATE_PATH.exists():
            print(f"[!] {INTERMEDIATE_PATH} missing — run with 'f1' or 'both' first")
            sys.exit(2)
        snap = json.loads(INTERMEDIATE_PATH.read_text())
        after_f1, f1_drops = snap["kept"], snap["dropped"]

    if mode == "f1":
        return

    after_f2, f2_drops = await filter_gemini(after_f1)

    print("\n=== Summary ===")
    print(f"  Candidates: {len(CANDIDATES)}")
    print(f"  After Filter 1 (UPCitemdb): {len(after_f1)} (-{len(f1_drops)})")
    print(f"  After Filter 2 (Gemini):    {len(after_f2)} (-{len(f2_drops)})")
    print(f"  Final catalog:              {len(after_f2)}")

    write_catalog(after_f2)
    drops_path = write_drops(f1_drops, f2_drops)
    print(f"[drops]   wrote {drops_path}")


if __name__ == "__main__":
    asyncio.run(main())
