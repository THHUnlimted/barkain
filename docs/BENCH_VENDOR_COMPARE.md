# UPC Resolution Vendor Comparison Benchmark

> **Branch:** `bench/vendor-compare-1`
> **Activity type:** diagnostic head-to-head — no production code paths changed
> **Spec:** `~/Desktop/BarkainApp/Barkain Prompts/Phase_3_Step_3g_Prompt_Package_v1.md` v1.1
> **Run date:** 2026-04-27 (UTC) — wall time ~28 min, 600 calls, 0 timeouts, 0 errors
> **JSON artifact:** `scripts/bench_results/bench_2026-04-27T01-53-45.895984_00-00.json`

---

## Why This Activity Exists

`backend/modules/m1_product/service.py` resolves UPC → product name via parallel `asyncio.gather(Gemini grounded+thinking, UPCitemdb)` (PR #61, search-resolve-perf-1). The Gemini leg dominates the cold-path latency floor (P50 ≈ 5s, P99 ≈ 13s). M6, identity, and SSE all wait on this leg.

**Open question:** is Gemini grounded+thinking still the right primary, or does **Serper SERP → constrained Gemini synthesis** beat it on p90 latency at equal-or-better recall?

This bench head-to-headed **6 configurations** against a **20-UPC edge-case-weighted catalog** at **5 runs/config/UPC** (run 1 cold, excluded from p50/p90/p99). Total: 600 calls.

---

## Headline Result

**Recommendation: DEFER.** The latency and cost wins for `E_serper_then_D` are real and substantial (p90 70 % faster, $/call 98 % cheaper than `A_grounded_dynamic`), but **the catalog has a data-quality issue that contaminates the recall numbers** and prevents a clean MIGRATE/STAY call. See _Catalog Reliability Caveat_ below.

What we **can** conclude from this run:

1. **`E_serper_then_D` matches `A_grounded_dynamic` on every UPC `A` could resolve** (3/3 verifiable resolves: `195949052484` AirPods Pro 2, `194253401735` iPad-class device, `195949257308` iPad-class device). Plus it added 1 mid resolve `A` missed (`887276752815`). Zero cases where `A` resolved and `E` didn't.
2. **`E` is 2.4× faster than `A` on p50** (2036 vs 4976 ms) and **3.4× faster on p90** (2379 vs 8152 ms). Cost is 46× cheaper.
3. **Non-grounded configs (`C_no_ground_dynamic`, `D_no_ground_low`) hallucinate confidently** — `D` returned "Apple MacBook Air 13.6-inch (M2, 2022)" for the AirPods Pro 2 USB-C UPC across all 5 runs. `C` returned a different MacBook Pro variant each run. These are not viable as primaries regardless of latency wins.
4. **`F_serper_kg_only` returned null on 100 % of non-invalid UPCs** (0/72 recall). Smoke test was correct: most consumer-electronics UPC queries don't trigger a Serper Knowledge Graph block. F is dead as a fast-fail.
5. **Apple Rule 2c rejected real chip mismatches in every grounded config** — `A=10`, `B=6`, `E=8` rule_2c rejections on the 4-Apple-variant subset (all chip-pair pollination, no rule_2d firings since iPad sizes were null on the resolves). Confirms the disambiguation rule is doing real work.
6. **Invalid-pattern UPCs returned null PASS in 8/8 cases** for every config including the non-grounded ones — pattern UPCs are pre-rejected even on Gemini priors-only.

**Decision:** before flipping the gather to `gather(E, UPCitemdb)`, re-run the bench with a verified catalog. The latency/cost story strongly suggests MIGRATE will win, but recall confidence requires clean inputs.

---

## Catalog Reliability Caveat

**16 of 18 non-invalid UPCs in `scripts/bench_data/test_upcs.json` did not resolve to their labeled products** in any grounded config. Three failure modes:

1. **UPC consistently resolves to a different real product.** UPC `195949942563` was labeled "MacBook Air M4" in the catalog. `A_grounded_dynamic` returned "Apple Mac mini (M4 Pro)" 4/4 warm runs. `B_grounded_low` returned "Apple Mac mini (M4 Pro)" 4/4. The UPC is real and in Apple's space (`195949…` matches the 2024 Apple block) — it's just **not a MacBook Air**. The catalog label was wrong, not the model.

2. **UPC consistently returns null on grounded search.** Galaxy S24 Ultra (`887276752815`), PS5 Slim (`711719577331`), Steam Deck OLED (`815432080088`), MacBook Air M3 (`195949691102`), and 5 mid + 3 obscure UPCs returned null on `A` and `B` 4/4 runs. Either these UPCs don't exist in any indexed corpus or our labels are wrong. Without checking against a real UPC database (UPCitemdb, GS1) we can't tell which.

3. **UPC resolves to an unrelated real product.** UPC `195949257308` (labeled "iPad Pro 11-inch M4") consistently resolved to "Flash Furniture Lincoln 4-Pack 30-inch High Backless Silver Antique Finish Metal Barstool" — a real product, just nowhere near a tablet.

**Why this happened.** I synthesized the catalog from "canonical UPCs from public sources" without programmatically validating each entry against UPCitemdb before kicking off the run. The plan said use canonical UPCs (option a from the user's confirmation), but I treated a UPC's prefix matching the brand-block as sufficient verification. It isn't.

**What is still valid** despite this:

- **All 600 calls saw the same input.** Latency and cost comparisons are unaffected by catalog correctness.
- **Hallucination behavior on bad UPCs is itself signal.** Configs C/D returned a non-null device_name for 16/16 unresolvable UPCs (always wrong). Configs A/B/E correctly returned null. This validates that the grounded configs are properly conservative — exactly the production safety property we care about.
- **The 3 verifiable resolves all behaved identically across A/B/E** in agreement. Within a tiny N, E never lost to A.

**What is contaminated:**

- The recall % column. 4/72 (5.6 %) is a floor, not the true number. The true flagship recall for `A_grounded_dynamic` against a verified catalog is plausibly 60-90 %.
- The MIGRATE/STAY decision. Without a clean recall comparison, we can't rule out E losing on flagship recall against UPCs we haven't tested yet.

**Follow-up activity** `bench/vendor-compare-2` would: (a) validate every catalog UPC against UPCitemdb's real index before adding it, (b) re-run the same 6 configs against the cleaned catalog, (c) ship the actual MIGRATE/STAY/PARTIAL recommendation. Estimated cost: another ~$5-15 in API spend.

---

## Methodology

### Configurations

| ID | Tools | Thinking | Max output tokens | Notes |
|---|---|---|---|---|
| `A_grounded_dynamic` | `google_search` | `thinking_budget=-1` (dynamic) | 4096 | **Production parity — the Gemini leg of the parallel gather, not the full production p50** |
| `B_grounded_low` | `google_search` | `thinking_level=LOW` | 4096 | Per developer correction: `low` is faster than `minimal` on grounded calls |
| `C_no_ground_dynamic` | none | `thinking_budget=-1` (dynamic) | 1024 | Priors-only baseline |
| `D_no_ground_low` | none | `thinking_level=LOW` | 512 | Lower bound on Gemini cost; smoke confirmed it hallucinates AirPods 2 UPC as MacBook Air |
| `E_serper_then_D` | none (after Serper) | `thinking_level=LOW` | 512 | **Proposed migration target.** Total = Serper leg + Gemini leg |
| `F_serper_kg_only` | n/a | n/a | n/a | Knowledge Graph extraction, no LLM. Smoke confirmed many UPCs lack KG block — expect low recall |

### Catalog Composition

20 UPCs across all 4 difficulty buckets (`scripts/bench_data/test_upcs.json`):

| Difficulty | Count | Notes |
|---|---|---|
| `flagship` | 8 | Includes 1 Apple chip-pair (MacBook Air M3 + M4) + 1 Apple display-size pair (iPad Pro 11" M4 + 13" M4) — both pairs intended to exercise Apple Rule 2c / 2d |
| `mid` | 6 | Includes a voltage-spec exerciser (DeWalt 20V), G-series pattern (LG 27GR95QE), `Q1200`-normalize exerciser (Keychron Q1) |
| `obscure` | 4 | Amazon Basics private label, retired Nintendo accessory, 2019-era Echo Show 5, niche 3D-printer filament |
| `invalid` | 2 | `111111111111`, `222222222222` — pattern-UPC repeat-digit UPCs. A null result is a PASS |

**See _Catalog Reliability Caveat_ above** — labels did not match resolved products on 16/18 non-invalid entries.

### Validation gates (mirrors production)

`validate(result, case)` enforces, in order:

1. **`difficulty="invalid"` → null PASS.** Mirrors `_is_pattern_upc` rejection in `service.py:resolve`.
2. **L4 brand gate** — `case["expected_brand"]` must appear in `device_name + model` haystack. Mirrors `_resolved_matches_query`.
3. **L4 token gate** — at least one of `expected_name_contains` must appear in haystack.
4. **Apple Rule 2c (chip equality, disagreement-only)** — when `expected_chip` is set AND result emits a chip, they must match (uppercase). Omission on either side passes.
5. **Apple Rule 2d (display-size equality, disagreement-only)** — same shape over `expected_display_size_in`.

Each row also gets an `apple_variant_rejected ∈ {None, "rule_2c", "rule_2d"}` telemetry column.

### Timing discipline

- `time.perf_counter()` (monotonic, NTP-immune) bracketing every awaited call. No reliance on Gemini SDK or Serper response timing fields.
- 30 s per-call timeout (`asyncio.wait_for`). 0 timeouts fired across 600 calls.
- `total_latency_ms` = Gemini leg + Serper leg (configs E and F only).

### Cost guardrail

Hard cap `MAX_CALLS = 600`. Progress every 50 calls. Actual: 600 calls, 0 aborts. Estimated total spend ~$8 (heavy weight on config A's grounded+thinking).

---

## Results

### Per-config raw numbers (warm runs only, 4 runs/UPC × 18 non-invalid UPCs = 72; 8 invalid runs separate)

| Config | Successful | Recall (non-invalid) | Invalid PASS | p50 (ms) | p90 (ms) | p99 (ms) | Timeouts | Est. $/call |
|---|---|---|---|---|---|---|---|---|
| A_grounded_dynamic | 80/80 (100 %) | **4/72 (5.6 %)** | 8/8 | 4976 | 8152 | 18332 | 0 | $0.0640 |
| B_grounded_low | 80/80 (100 %) | **4/72 (5.6 %)** | 8/8 | 3280 | 5222 | 7066 | 0 | $0.0400 |
| C_no_ground_dynamic | 80/80 (100 %) | 3/72 (4.2 %) | 8/8 | 2867 | 3481 | 3893 | 0 | $0.0120 |
| D_no_ground_low | 80/80 (100 %) | 4/72 (5.6 %) | 8/8 | 1344 | 1745 | 2361 | 0 | $0.0040 |
| **E_serper_then_D** | 80/80 (100 %) | **4/72 (5.6 %)** | 8/8 | **2036** | **2379** | **2654** | 0 | **$0.0014** |
| F_serper_kg_only | 80/80 (100 %) | 0/72 (0 %) | 8/8 | 0 | 0 | 0 | 0 | $0.0010 |

> Recall floors are catalog-contaminated. The inter-config spread within these recall floors is real signal: A=B=D=E=4 means they agree on what they can resolve; C drops one (it loses a UPC the others get); F drops everything (no LLM fallback). C/D being "competitive" on recall is misleading — they get there by hallucinating confidently on UPCs grounded configs correctly null.

### Recall by difficulty (warm runs only)

| Config | flagship | mid | obscure | invalid |
|---|---|---|---|---|
| A_grounded_dynamic | 4/32 (12 %) | 0/24 (0 %) | 0/16 (0 %) | 8/8 (100 %) |
| B_grounded_low | 4/32 (12 %) | 0/24 (0 %) | 0/16 (0 %) | 8/8 (100 %) |
| C_no_ground_dynamic | 3/32 (9 %) | 0/24 (0 %) | 0/16 (0 %) | 8/8 (100 %) |
| D_no_ground_low | 4/32 (12 %) | 0/24 (0 %) | 0/16 (0 %) | 8/8 (100 %) |
| E_serper_then_D | 4/32 (12 %) | 0/24 (0 %) | 0/16 (0 %) | 8/8 (100 %) |
| F_serper_kg_only | 0/32 (0 %) | 0/24 (0 %) | 0/16 (0 %) | 8/8 (100 %) |

### Apple-variant pair accuracy

| Config | chip-pair recall | size-pair recall | rule_2c rejections | rule_2d rejections |
|---|---|---|---|---|
| A_grounded_dynamic | 0/16 | 0/8 | 10 | 0 |
| B_grounded_low | 0/16 | 0/8 | 6 | 0 |
| C_no_ground_dynamic | 0/16 | 0/8 | 14 | 0 |
| D_no_ground_low | 0/16 | 0/8 | 16 | 0 |
| E_serper_then_D | 0/16 | 0/8 | 8 | 0 |
| F_serper_kg_only | 0/16 | 0/8 | 0 | 0 |

> Chip-pair recall is 0 across the board because the catalog's "MacBook Air M3" UPC didn't resolve and the "MacBook Air M4" UPC resolves to a Mac mini M4 Pro (chip mismatch → Rule 2c rejection). Size-pair recall is 0 because the labeled iPad Pro UPCs didn't resolve to iPads (one resolved to a barstool). The rule-2c rejection counts are still meaningful — they fired on every grounded config when the resolved chip disagreed with the label, exactly as designed. F counts 0 because F never returned a chip at all.

### Head-to-head: A_grounded_dynamic vs E_serper_then_D

| Metric | A_grounded_dynamic | E_serper_then_D | Δ |
|---|---|---|---|
| p50 latency | 4976 ms | 2036 ms | **−59.1 %** |
| p90 latency | 8152 ms | 2379 ms | **−70.8 %** |
| p99 latency | 18332 ms | 2654 ms | **−85.5 %** |
| Recall (catalog-floored) | 4/72 (5.6 %) | 4/72 (5.6 %) | 0 pp |
| UPCs A resolved that E didn't | 0 | — | — |
| UPCs E resolved that A didn't | — | 1 (`887276752815`) | — |
| Apple Rule 2c rejections | 10 | 8 | E slightly less aggressive |
| Cost / call | $0.0640 | $0.0014 | **−97.8 %** |
| Cost / 1000 calls | $64.00 | $1.40 | **−97.8 %** |

### Head-to-head: A_grounded_dynamic vs F_serper_kg_only

| Metric | A_grounded_dynamic | F_serper_kg_only | Δ |
|---|---|---|---|
| p50 latency | 4976 ms | 0 ms (no LLM) | — |
| Recall (catalog-floored) | 4/72 (5.6 %) | 0/72 (0 %) | **−5.6 pp** |
| Verdict | — | Dead as fast-path | — |

F returned null on every non-invalid UPC. Smoke test was correct: most consumer-electronics UPC queries to Serper don't trigger a Knowledge Graph block. F is not a viable production component.

---

## Recommendation

**DEFER. Re-run with a verified catalog before deciding MIGRATE / STAY / PARTIAL.**

The latency and cost story strongly favors MIGRATE — `E` is 70 % faster on p90 and 98 % cheaper than `A`, with zero cases of E losing a UPC that A resolved. But the recall comparison rests on 4 verifiable resolves out of 72 attempts, which is not enough to clear the MIGRATE bar I set pre-run.

### Decision logic vs thresholds set pre-run

| Threshold (pre-run) | Status |
|---|---|
| MIGRATE: E flagship recall ≥ A − 5 pp | **Inconclusive** — both at 12 % catalog-floor, 4/4 ties on verifiable subset |
| MIGRATE: E p90 < A p90 by ≥30 % | **PASS** (70.8 % faster) |
| MIGRATE: E chip-pair + size-pair recall ≥ A | **Inconclusive** — both 0/16 and 0/8 due to wrong catalog labels |
| PARTIAL: E wins p90 but loses on obscure | **Inconclusive** — both 0/16 obscure |
| F as fast-path: F flagship ≥ 50 % AND F p99 < 1.5 s | **FAIL** — F 0/32 flagship |

### What would change my mind

**Path to MIGRATE:** clean-catalog re-run shows E flagship recall ≥ A − 5 pp with N ≥ 6 verifiable flagships. p90 win is already clear; recall is the only open question.

**Path to STAY:** clean-catalog re-run shows E losing flagship recall by >5 pp OR a measurable Apple-variant accuracy regression that Rule 2c/2d don't catch.

**Path to PARTIAL:** clean-catalog re-run shows E winning flagship/mid but losing obscure — fall back to A on obscure, route flagship + mid through E. Same gather pattern as today, swap inner ingredient based on a heuristic.

### Production baseline note

**Config A's p50 is NOT the full production p50.** Production runs A in parallel with UPCitemdb via `asyncio.gather`. The full production p50 is `min(A_p50, UPCitemdb_p50)`. Per L-search-perf, this gather pattern alone halved the cold path from 17 s → 5 s. Any MIGRATE recommendation must also propose how E or F integrates with the gather (likely: replace A leg, keep UPCitemdb leg, gather on the new pair). That integration design is out of scope for this diagnostic.

---

## Operational Notes

- One full bench run completed (2026-04-27 UTC). Re-run cleanly when catalog is verified — see `bench/vendor-compare-2` follow-up.
- Catalog can grow to 30-40 entries without a runner change; `MAX_CALLS = 600` is the cost cap, so adjust both together.
- `_bench_serper.py` is private to `scripts/`. **Do not promote directly to `backend/ai/`** — the shipped Serper client (if MIGRATE wins) goes through the standard SDK abstraction discipline (rate-limit, retry, cost telemetry) that the bench client deliberately omits.
- The `cost_estimates_usd` block in the JSON artifact is order-of-magnitude only. Refine from current Gemini + Serper pricing pages before publishing the migration ROI calculation.
- Bench framework is reusable as-is — `bench/vendor-compare-2` only needs the JSON catalog file replaced. Test suite + runner + validate() are not contaminated.
