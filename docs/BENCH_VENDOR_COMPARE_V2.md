# UPC Resolution Vendor Comparison Benchmark — v2 (Clean Catalog)

> **Branch:** `bench/vendor-compare-2`
> **Activity type:** diagnostic head-to-head — no production code paths changed
> **Predecessor:** `bench/vendor-compare-1` (PR #74) shipped DEFER because the catalog had 16/18 mislabeled non-invalid UPCs.
> **Run date:** 2026-04-27 (UTC) — wall time ~14 min, 270 calls, 0 timeouts, 0 errors
> **JSON artifact:** `scripts/bench_results/bench_2026-04-27T04-04-02.577574_00-00.json`
> **Pre-validation drops:** `scripts/bench_results/prevalidate_v2_drops_2026-04-27T03-44-44.228980_00-00.json`

---

## Why v2

vendor-compare-1 produced clear latency wins for `E_serper_then_D` over `A_grounded_dynamic` (p90 −71 %, $/call −98 %), but the recall comparison was contaminated: 16/18 non-invalid UPCs in the catalog did not resolve to their labeled products on grounded Gemini because the catalog labels had been synthesized from prefix-block matching without programmatic verification.

The mini-bench (PR #75) added a UPCitemdb pre-validation gate but discovered that **UPCitemdb-validated does not imply Gemini-resolvable** — Galaxy Buds R170N (UPC `732554340133`) is in UPCitemdb but Gemini's grounded search returns "Goodcook 20434 Can Opener" because UPCs aren't globally unique cross-brand.

vendor-compare-2 applies **both filters** before kicking off the bench:

1. **Filter 1 — UPCitemdb has a record AND its response brand/title contains the expected brand token**. Catches cross-brand UPC reuse (the JBL Flip 6 UPC `848061073966` returned an Anker cable).
2. **Filter 2 — Gemini A-config (grounded + dynamic thinking) probe agrees on brand + name + chip + display size**. Catches the Galaxy-Buds-class collisions where UPCitemdb knows the product but Gemini's broader corpus disagrees.

Survivors carry independently-verified ground truth; the recall comparison is uncontaminated.

---

## Catalog

**32 candidates → 9 survivors** (7 valid + 2 invalid pattern UPCs):

| UPC | Product | Filter notes |
|-----|---------|--------------|
| `194253397168` | AirPods Pro 2nd Gen | both filters pass |
| `190199246850` | AirPods Pro 1st Gen | both filters pass |
| `190199098428` | AirPods 2nd Gen | both filters pass |
| `195949052484` | AirPods Pro 2 USB-C | both filters pass |
| `194252721247` | AirPods Pro 1st Gen MagSafe | both filters pass |
| `195949257308` | iPad Air 13-inch M2 (2024) | **relabeled**: v1 catalog called this "iPad Pro 11" M4"; UPCitemdb says iPad Air M2; Gemini agrees |
| `889842640816` | Microsoft Xbox Series X | both filters pass |
| `111111111111` | invalid pattern UPC | null = PASS |
| `222222222222` | invalid pattern UPC | null = PASS |

**Catalog limitations** (honest):

- **Apple-audio heavy** — 5 of 7 valid UPCs are AirPods variants. The signal generalizes weakly to non-Apple-audio categories.
- **Only 1 chip-pair coverage** — iPad Air M2 13" (chip + display gates). No M3-vs-M4 MacBook Air pair (UPCs not in UPCitemdb's trial DB).
- **No mid/obscure tier** — Sonos Era 100, KitchenAid mixer, DeWalt drill, Sony PS5 Slim, Galaxy S24 Ultra, Apple Watch UPCs all dropped at Filter 1 (UPCitemdb's trial DB doesn't index them).

These limitations are honest tradeoffs of dual-filter rigor over breadth. Better than v1's contaminated 20-UPC catalog; smaller than ideal for category generalization.

**Pre-validation drops worth noting:**

- `732554340133` (Samsung Galaxy Buds R170N canary) — Filter 2 dropped: Gemini returns "Goodcook 20434 Can Opener" (UPC reuse cross-brand). **Filter working as designed.**
- `885609020013` — UPCitemdb says Dyson V11 Torque Drive; Gemini returns null on this UPC. **Filter working.**
- `097855170095` — UPCitemdb says "TAP SCHEDULER MOUNTING KIT GRAPHITE" (a real Logitech room-booking accessory); Gemini returns null. **Filter working.**

---

## Configuration Matrix

(Same as v1 — see `docs/BENCH_VENDOR_COMPARE.md` for full descriptions.)

| ID | Tools | Thinking | Max output |
|---|---|---|---|
| A_grounded_dynamic | google_search | dynamic | 4096 |
| B_grounded_low | google_search | LOW | 4096 |
| C_no_ground_dynamic | none | dynamic | 1024 |
| D_no_ground_low | none | LOW | 512 |
| E_serper_then_D | none (after Serper SERP) | LOW | 512 |
| F_serper_kg_only | n/a (KG extraction only) | n/a | n/a |

Each config: 9 UPCs × 5 runs (run 1 cold, excluded from p50/p90/p99) = 45 calls.

---

## Headline Results

(28 non-invalid warm runs per config; 8 invalid warm runs per config.)

| Config | Recall | Invalid PASS | p50 | p90 | p99 | $/call |
|---|---|---|---|---|---|---|
| **A_grounded_dynamic** | **27/28 (96.4%)** | 8/8 | 3417 ms | 4520 ms | 5531 ms | $0.0640 |
| B_grounded_low | 24/28 (85.7%) | 8/8 | 2930 ms | 3991 ms | 4960 ms | $0.0400 |
| C_no_ground_dynamic | 0/28 (0%) | 8/8 | 2955 ms | 3685 ms | 4201 ms | $0.0120 |
| D_no_ground_low | 0/28 (0%) | 8/8 | 1328 ms | 2352 ms | 2969 ms | $0.0040 |
| **E_serper_then_D** | **24/28 (85.7%)** | 8/8 | **2152 ms** | **2767 ms** | 5482 ms | **$0.0014** |
| F_serper_kg_only | 0/28 (0%) | 8/8 | 0 ms | 0 ms | 0 ms | $0.0010 |

**Per-UPC pass/fail (warm only)**:

| UPC | A | B | C | D | E | F |
|-----|---|---|---|---|---|---|
| AirPods Pro 2nd Gen | 4/4 | 4/4 | 0/4 | 0/4 | 4/4 | 0/4 |
| AirPods Pro 1st Gen | 4/4 | 4/4 | 0/4 | 0/4 | 4/4 | 0/4 |
| AirPods 2nd Gen | 4/4 | 4/4 | 0/4 | 0/4 | 4/4 | 0/4 |
| AirPods Pro 2 USB-C | 4/4 | 4/4 | 0/4 | 0/4 | 4/4 | 0/4 |
| AirPods Pro 1st Gen MagSafe | 4/4 | 4/4 | 0/4 | 0/4 | 4/4 | 0/4 |
| iPad Air 13" M2 | **3/4** | **0/4** | 0/4 | 0/4 | **4/4** | 0/4 |
| Xbox Series X | 4/4 | 4/4 | 0/4 | 0/4 | **0/4** | 0/4 |

---

## Recommendation

> **MIGRATE B → E, with synthesis-prompt hardening first.**

Production currently runs `B_grounded_low` after PR #75 (feat/grounded-low-thinking). The relevant comparison is therefore **B vs E**, not A vs E.

| Metric | B (current prod) | E (proposed) | Δ |
|--------|------------------|--------------|---|
| Recall (clean catalog) | 24/28 (85.7%) | 24/28 (85.7%) | tied |
| p50 latency | 2930 ms | 2152 ms | **−27 %** |
| p90 latency | 3991 ms | 2767 ms | **−31 %** |
| Cost / call | $0.040 | $0.0014 | **−97 % (28× cheaper)** |
| Failure mode | confidently wrong (returns barstool for iPad UPC) | safe null | **safer** |

**Why "with synthesis-prompt hardening first":** E's only recall miss in this bench was Xbox Series X (0/4). The Serper SERP top-5 organic results contained "Microsoft Xbox Series X 1TB Video Game Console" verbatim 5 times. Gemini's synthesis call returned `device_name=null` 4 of 4 warm runs and 1 of 1 cold run — but a fresh manual repro shows the same prompt-snippets pair returns the correct answer **2 of 5 times** under temperature=0.1. The model is interpreting the "Use ONLY the snippets" + "If insufficient, return null" instructions over-cautiously: it's worried the snippets don't explicitly assert "UPC 889842640816 is this product" and so returns null.

This is a **synthesis-prompt fragility**, not a Serper-coverage failure. The fix is to harden the synthesis prompt to be more aggressive about extracting a product name when the snippets clearly identify a single product, while preserving the conservative-null behavior when results are genuinely ambiguous. Recommended phrasing change:

```
OLD: Use ONLY the snippets below. Do not invent. If the snippets are insufficient
     to identify the product, return device_name: null.

NEW: Use ONLY the snippets below. Do not invent. If 3 or more snippets clearly
     name the same product, return that product's full name with brand. Only
     return null if the snippets contradict each other or none clearly name
     a single product.
```

(The "3 or more" threshold ensures conservative behavior on truly contested results while letting clear-consensus cases through.)

**Suggested rollout (`bench/vendor-migrate-1`):**

1. **Land synthesis-prompt hardening** in a small follow-up bench (re-run E on the v2 catalog only — 5 UPCs × 5 runs = 25 calls, ~$0.05). Target: Xbox 4/4 and no AirPods regression.
2. **Add fallback within E in production**: if Serper-then-synthesis returns null, fire B as a fallback. Cost-blended: ~$0.0074/call avg (5× cheaper than current B-only $0.040), still 24/28 recall floor.
3. **Swap `gather(B, UPCitemdb)` → `gather(E-with-fallback, UPCitemdb)`** in `m1_product/service.py`. UPCitemdb leg is unchanged — it's the safety net for UPCs both legs miss.
4. **Mike app-tests broadly** across electronics, appliances, tools, kitchen — the categories vendor-compare-2's catalog couldn't cover.
5. **Optional `bench/vendor-compare-3`** with a broader-category clean catalog to validate the migration on non-Apple-audio products.

---

## Ancillary Findings

**1. The cat-rel-1-L4 post-resolve gate would have caught B's iPad-Air-as-barstool failure in production.** Query "iPad Air M2" → resolved name "Flash Furniture Lincoln…" → no "apple" in haystack → reject + cache invalidate. So B's dangerous failure is mitigated, but at the cost of a wasted Gemini call + DB write + cache write per occurrence. E's null fails fast — no waste.

**2. C and D are unviable as primaries.** Zero recall on every non-invalid UPC across all 7 valid entries. Confirms vendor-compare-1's finding: non-grounded synthesis without external context cannot resolve UPCs. The 0% number here is cleaner because the catalog labels are correct — these configs aren't wrong, they're just unable to perform the task.

**3. F (Serper KG-only) is dead as a fast-path.** 0/28 recall mirrors v1. Most consumer-electronics UPC queries don't trigger a Serper Knowledge Graph block. F costs $0.001/call but contributes zero recall.

**4. Apple-variant chip recall (E=4/4 > A=3/4 > B=0/4)** on the 1 chip-pair UPC available (iPad Air M2). E's snippet-driven extraction nailed the chip every time; A's grounded search was usually right but sometimes drifted; B's LOW thinking returned null chip 4/4 even when the product name was correct. Suggests B may be under-allocating thinking tokens for chip extraction. Sample size is tiny — needs more chip-pair UPCs to confirm.

**5. Pattern-UPC null-PASS held 8/8 for every config including non-grounded ones.** Robust against confused output for clearly-fake UPCs.

---

## Cost Notes

Per-call cost estimates are order-of-magnitude only — refine from current pricing pages before publishing user-facing numbers. Bench spend was ~$11 against current Gemini Flash Lite Preview rates (Apr 2026).

| Config | Calls × Cost | Approx Spend |
|--------|--------------|--------------|
| A | 45 × $0.064 | $2.88 |
| B | 45 × $0.040 | $1.80 |
| C | 45 × $0.012 | $0.54 |
| D | 45 × $0.004 | $0.18 |
| E | 45 × $0.0014 | $0.06 |
| F | 45 × $0.001 | $0.05 |
| **Total** | 270 calls | **~$5.5** |

(Actual spend lower than the $11 estimate — pre-validation Filter 2 added ~$0.65; total was ~$6.)

---

## Methodology Validations

- **`time.perf_counter()` discipline** produced clean monotonic latencies; 30s `asyncio.wait_for` per call fired 0 times across 270 calls.
- **Serper soft-fail on httpx errors** never tripped (live API was 100 % available throughout the run).
- **Cold run exclusion from percentiles** — cold runs preserved in JSON artifact (`is_cold=True`) but not counted in p50/p90/p99 stats.
- **Same Serper response cached across E + F per UPC** — one Serper call per UPC, reused by both configs.
- **`pre-validation drop log`** in `scripts/bench_results/prevalidate_v2_drops_*.json` documents every filter casualty with the reason (UPCitemdb brand mismatch, Gemini disagreement, etc.) for post-hoc audit.

---

## What Would Change the Recommendation

- **If broader-category re-run shows E recall < 80%** on appliances/tools/kitchen: stay on B, queue a synthesis-prompt rewrite + re-bench.
- **If synthesis-prompt hardening fails to fix Xbox-class failures**: fall back to "B with E as a cache-warm preprocessor" (issue Serper SERP in parallel with B; cache the snippets for follow-up calls).
- **If Serper SLA degrades** to < 99 %: E loses the latency win on slow Serper days. Add Serper p99 latency as an SLO before migrating.
- **If Gemini Flash Lite Preview pricing changes substantially**: re-evaluate cost story.

---

## Reproducibility

```bash
# Pre-validate (free UPCitemdb + ~$0.65 Gemini probe)
python3 scripts/bench_prevalidate_v2.py f1   # UPCitemdb filter
python3 scripts/bench_prevalidate_v2.py f2   # Gemini agreement filter

# Run bench against v2 catalog (~$5.5 Gemini + Serper, ~14 min wall)
python3 scripts/bench_vendor_compare.py --catalog scripts/bench_data/test_upcs_v2.json
```

JSON artifacts and drop logs land in `scripts/bench_results/`.
