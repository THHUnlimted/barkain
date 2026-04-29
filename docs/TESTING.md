# Barkain — Testing Reference

> Source: Architecture sessions, March–April 2026
> Scope: Backend (pytest) + iOS (XCTest) test conventions, CI configuration, coverage targets
> Last updated: 2026-04-29 (v2.33 — Step 3o-C Gemini UPC system-instruction rewrite: **781 backend passed (+8 from 773)** / 207 iOS unit / 6 iOS UI. 8 skipped network-gated tests (pre-existing); 789 collected. New file `backend/tests/ai/test_upc_lookup_prompt.py` with 8 anti-condensation regression tests pinning structural integrity of `UPC_LOOKUP_SYSTEM_INSTRUCTION` after the category-agnostic rewrite: `test_upc_lookup_system_instruction_has_do_not_condense_marker` (asserts `# DO NOT CONDENSE OR SHORTEN` in the constant), `test_upc_lookup_system_instruction_min_length` (`len(...) >= 3000` — current 4,310 chars), `test_upc_lookup_system_instruction_has_all_nine_steps` (loops 1–9 and asserts `Step N:` markers found AND in monotonic order), `test_upc_lookup_system_instruction_has_six_examples` (`iPad Pro 13-inch M4` / `KitchenAid Artisan 5-Quart` / `Royal Canin Adult Indoor 7lb` / `DeWalt 20V MAX Brushless Drill/Driver Kit` / `Greenworks 80V 21-inch Self-Propelled` / `iPhone 16 Pro Max 256GB`), `test_upc_lookup_system_instruction_has_json_contract` (`"device_name":` / `"model":` / `"reasoning":` JSON contract fields), `test_upc_lookup_system_instruction_no_electronics_only_qualifier` (negative regression — asserts `electronics-only` / `electronics device` / `electronics-focused` / `electronics relevance` ABSENT), `test_build_upc_retry_prompt_is_category_agnostic` (asserts `non-electronics sources` / `grocery, household, apparel` ABSENT, `all retail categories` PRESENT, `{upc}` template substitution preserved), `test_build_upc_lookup_prompt_unchanged` (byte-equal regression for `012345678905`). All 8 pass in 0.01s. Phase 1 L13 (agent shortening Gemini system instructions during implementation) is the load-bearing failure mode this catches — verbatim text in Locked Decisions §53 + character-count floor + `# DO NOT CONDENSE` markers (one inside the string, one as a leading comment) are layered defenses. **Mini-bench `scripts/bench_grounded_3o_c.py`** is one-off diagnostic tooling (NOT covered by unit tests — same posture as `bench_synthesis_verified.py`, `bench_mini_a_vs_b.py`, `bench_vendor_compare.py`); 5-UPC mixed-vertical panel × old + new prompts = 10 grounded `gemini_generate_json` calls with the frozen old prompt text inlined verbatim for control. Output JSON saved to `scripts/bench_results/bench_3o_c_<timestamp>.json`. Pass criterion `no_electronics_regression=True` met. **iOS untouched** (207 / 6 unchanged). UI 6 unchanged. 8 skipped unchanged. `pytest -q` reports `781 passed, 8 skipped`. `ruff check backend/ scripts/` clean. `xcodebuild` not required for this step but should remain clean. Surfaced bug `3o-C-L1-fabricated-upc-tap` (pre-existing since 3c — Tier 3 Gemini search ships fabricated `primary_upc` values, iOS `SearchViewModel.resolveTappedResult:399` calls `/resolve` on them and grounded resolve hallucinates an unrelated product; concrete repro: rustoleum search → tap row #2 → Tide Pods); deferred to follow-up. v2.32 — Step 3o-B Tier-2 noise filter narrowing: **773 backend passed (+19 from 754)** / 207 iOS unit / 6 iOS UI. 8 skipped network-gated tests (pre-existing); 781 collected. Backend +19 split: 6 case soft-pool tests (drop, opt-out singular, opt-out plural), 3 charger soft-pool tests (drop, opt-out, charging-token), 5 accessor-context tests (gaming-controller drop, phone drop, litter keep, mixer keep, vacuum keep), 4 regression tests (thumbstick title, pixel-10 monitor hard-pool, applecare warranty hard-pool, screen-protector hard-pool), 4 telemetry tests (`_classify_tier2_noise` returns hard_category / soft_category / accessor_context / None). All 24 prior tier2/noise tests in `test_product_search.py` continue to pass without changes — the existing `test_is_tier2_noise_filters_controller_accessories` thumbstick + case rows still drop via the new accessor-context rule because their parent tokens are in `_ACCESSOR_CONTEXT_TOKENS`. iOS code untouched. `pytest -q` reports `773 passed, 8 skipped`. `ruff check backend/` clean. v2.31 — Step 3o-A autocomplete vocab expansion: **754 backend** / 207 iOS unit / 6 iOS UI. The pre-3o-A baseline coming into this step was 757 backend (per CLAUDE.md v5.41); the −3 collected delta is `−9 from collapsing the 9-case `test_electronics_filter` parametrize block when `is_electronics()` was retired, +6 added`. The 6 added are: `test_non_electronics_terms_pass_through` (single test replacing the 9 dropped REJECT cases — asserts `cat food` / `baby diapers` / `dog treats` survive `assemble_terms`), `test_default_sources_includes_six_categories` (CLI default expands to the 6 Step 3o-A scopes + `--max-terms` is 15000), `test_scope_probe_gates_extras` (yield ≥ 5 admits the scope, yield < 5 skips it; uses fake fetcher patched into `SOURCE_FETCHERS` to control yields per scope), `test_sweep_runs_sources_in_parallel` (per-source start times cluster within 100 ms; sequential would have spaced them by per-source-runtime), `test_sweep_soft_fails_on_one_source_error` (mid-gather `RuntimeError` on one source leaves the others' contributions intact and emits a warning log), `test_output_schema_v2` (asserts `version=2`, `stats.scope_probes` + `stats.scope_probes_admitted` present, `after_electronics_filter` absent). One smoke companion `test_real_amazon_endpoint_returns_results_for_pet_supplies_scope` is gated on `BARKAIN_RUN_NETWORK_TESTS=1` and counts as `skipped` not `passed` in the headline number. Two existing tests `test_dry_run_does_not_write_output` and `test_run_end_to_end_writes_valid_json` thread `--skip-probes` so the production probe-gating path stays out of respx-stubbed harnesses. iOS code untouched — `BarkainTests/Fixtures/autocomplete_vocab_test.json` is the hand-curated 50-term fixture and is intentionally NOT regenerated when the production bundle is. `pytest -q` reports `754 passed, 8 skipped`. `ruff check scripts/ backend/` clean. `xcodebuild build` clean (only pre-existing Swift 6 warnings unrelated to this step).)

> Previous: 2026-04-27 (v2.30 — bench/vendor-migrate-1 [PR pending]: **711 backend** / 203 iOS unit / 6 iOS UI — backend **+17** vs vendor-compare-2's 694. Production AI-resolve leg switched from grounded-Gemini-only (B) to Serper-then-grounded (E-then-B) via new `backend/ai/web_search.py`. The +17 land in 3 files: **11 in new `tests/test_ai_web_search.py`** covering `resolve_via_serper` happy path (Serper organic + synthesis JSON returns the expected shape), API-key-missing soft-fail (returns None when `settings.SERPER_API_KEY` empty), httpx.HTTPError soft-fail, Serper non-200 soft-fail, zero-organic soft-fail, synthesis-null-device-name soft-fail, gemini_generate-raises soft-fail, bench-winning config pinning (asserts `thinking_budget=0`, `grounded=False`, `max_output_tokens=1024` in the call kwargs — tied to vendor-migrate-1's mini-grid finding), `_parse_synthesis_json` markdown-fence stripping, `_parse_synthesis_json` parse-failure returns `{}`, and `_format_snippets` top-N truncation. **3 in `tests/test_ai_abstraction.py`**: `test_gemini_generate_grounded_false_omits_tool` (pins `grounded=False` removes the `Tool(google_search=GoogleSearch())` from `GenerateContentConfig.tools` — synthesis must use only Serper snippets, not run its own grounded search), `test_gemini_generate_thinking_budget_zero_disables_thinking` (pins `thinking_budget=0` wires `ThinkingConfig(thinking_budget=0)` with `thinking_level=None` — passing both at once is undefined SDK behavior), `test_gemini_generate_respects_temperature_parameter` (pins the temperature parameter now propagates to `GenerateContentConfig` — fixes a long-standing hardcoded `temperature=1.0` bug where prod ran at 1.0 despite asking for 0.1; bench was at 0.1 via its own client). **3 in `tests/modules/test_m1_product.py`**: `test_resolve_uses_serper_when_serper_returns_value` (asserts grounded `gemini_generate_json` is NOT called when `resolve_via_serper` returns a result — load-bearing latency win), `test_resolve_falls_back_to_grounded_when_serper_returns_none` (asserts grounded IS called when Serper returns None — coverage-gap UPCs still resolve), `test_resolve_falls_back_to_grounded_when_serper_raises` (defensive: future bug in web_search.py must not propagate to the user). **New autouse fixture in `tests/conftest.py`**: `_serper_synthesis_disabled` patches `modules.m1_product.service.resolve_via_serper → AsyncMock(return_value=None)` for every test by default — without it, existing tests that mock `gemini_generate_json` would have `resolve_via_serper` fire against live Serper (developers keep the key in `.env` for the bench scripts) and either return surprising real results or fail intermittently. Tests that exercise the Serper path patch the same target with their own value. The 3 new wire-up tests in `test_m1_product.py` use this override pattern. **5 new bench scripts** at `scripts/bench_synthesis_*.py` and `scripts/bench_dump_serper.py` — these are one-off diagnostic tooling, NOT covered by unit tests (same posture as `bench_mini_a_vs_b.py` from feat/grounded-low-thinking). The 9 unit tests in `tests/scripts/test_bench_vendor_compare.py` cover the shared helpers (validate / percentile / warm_rows / recall_stats) which are imported and reused by the new `bench_synthesis_verified.py`. **iOS untouched** (203 / 6 unchanged). UI 6 unchanged. 7 skipped unchanged. `pytest -q` reports `711 passed, 7 skipped`. `ruff check backend/ scripts/` clean. `xcodebuild build` clean (iOS untouched).)

> Previous: 2026-04-27 (v2.29 — bench/vendor-compare-2 [PR pending]: **694 backend** / 203 iOS unit / 6 iOS UI — **counts unchanged.** This is a diagnostic-only branch (clean-catalog re-run of vendor-compare-1's 6-config head-to-head); no production code paths changed and no new unit tests added. The existing 9 unit tests in `tests/scripts/test_bench_vendor_compare.py` from vendor-compare-1 still cover validate / percentile / warm_rows / recall_stats / apple_variant_check helpers, which are the math the v2 run depends on. Verified after adding the `--catalog` CLI flag to `scripts/bench_vendor_compare.py` (`pytest -q tests/scripts/test_bench_vendor_compare.py` → `9 passed in 0.01s`). Run-time-only artifacts: `scripts/bench_prevalidate_v2.py` (~410 LoC dual-filter pre-validation: UPCitemdb retry-on-429 + Gemini A-config probe), `scripts/bench_data/test_upcs_v2.json` (9-entry catalog), `scripts/bench_results/bench_2026-04-27T04-04-02.577574_00-00.json` (270-call run output), `scripts/bench_results/prevalidate_v2_drops_2026-04-27T03-44-44.228980_00-00.json` (drops audit). The pre-validation script is one-shot tooling and is NOT covered by unit tests — same posture as `bench_mini_a_vs_b.py` from feat/grounded-low-thinking. `pytest -q` reports `694 passed, 7 skipped` unchanged. `ruff check backend/ scripts/` clean. iOS untouched (203 / 6). UI 6 unchanged. 7 skipped unchanged. `xcodebuild build` clean (iOS untouched).)

> Previous: 2026-04-27 (v2.28 — feat/grounded-low-thinking [PR pending]: **694 backend** / 203 iOS unit / 6 iOS UI. Backend **+2** in `tests/test_ai_abstraction.py` pinning the new `gemini_generate` config shape after the production switch from `ThinkingConfig(thinking_budget=-1)` to `ThinkingConfig(thinking_level=ThinkingLevel.LOW)`. Tests: `test_gemini_generate_uses_thinking_level_low` (mocks `_get_gemini_client`, calls `gemini_generate` with `max_retries=0`, introspects the `config` arg passed to `client.aio.models.generate_content`, asserts `config.thinking_config.thinking_level == ThinkingLevel.LOW` AND `config.thinking_config.thinking_budget is None` — passing both at once is undefined SDK behavior so both are pinned); `test_gemini_generate_keeps_grounding_enabled` (asserts `config.tools` contains exactly one `Tool(google_search=GoogleSearch())` — bench established equivalent recall *only when grounding stays on*; stripping the tool would silently regress to non-grounded synthesis, which vendor-compare-1's config C/D proved hallucinates MacBooks for AirPods UPCs). The two tests are deliberately tight on the regression surface — they pin the two config knobs that `feat/grounded-low-thinking` is changing or relying on, nothing else. Both pass alongside the existing 4 Claude tests; test_ai_abstraction.py runs in 0.02s. **iOS untouched** (203 / 6 unchanged). UI 6 unchanged. 7 skipped unchanged. `pytest -q` reports `694 passed, 7 skipped`. `ruff check backend/ scripts/` clean. `xcodebuild build` clean (iOS untouched). The mini-bench artifact `scripts/bench_results/bench_mini_a_vs_b_<UTC>.json` and `scripts/bench_mini_a_vs_b.py` (~370 LoC, reuses `bench_vendor_compare.py` helpers — UPC_LOOKUP_PROMPT, _gemini_call, _timed_call, percentile, validate) are NOT covered by unit tests — they're one-off diagnostic tooling that ran once to verify the production change. The 9 unit tests in `tests/scripts/test_bench_vendor_compare.py` from vendor-compare-1 cover the shared helpers (validate / percentile / warm_rows / recall_stats) so the mini-bench's recall judgments can't silently regress.)

> Previous: 2026-04-26 (v2.27 — bench/vendor-compare-1 [PR pending]: **692 backend** / 203 iOS unit / 6 iOS UI. Backend **+9** in `tests/scripts/test_bench_vendor_compare.py` covering the runner's helpers — diagnostic activity, NO live Gemini/Serper in unit tests, NO production code paths changed. Tests: `test_validate_matches_expected_brand_and_token` (happy path); `test_validate_null_device_name_returns_false_for_non_invalid` (null guard); `test_validate_invalid_difficulty_treats_null_as_pass` (pattern-UPC bucket); `test_validate_apple_rule_2c_rejects_chip_disagreement` (M3 result for M4 case → reject); `test_validate_apple_rule_2d_rejects_display_size_disagreement` (11" for 13" case → reject); `test_validate_apple_rule_2c_allows_chip_omission` (disagreement-only — null on either side passes); `test_apple_variant_check_returns_rule_id_on_disagreement` (telemetry column 2c/2d); `test_summary_excludes_cold_runs_from_percentiles` (run==1 excluded from p50/p90/p99); `test_summary_excludes_invalid_upcs_from_recall` (invalid bucket separation). Tests load the `scripts/bench_vendor_compare.py` module via `importlib.util.spec_from_file_location` (mirrors `test_generate_autocomplete_vocab.py` pattern); stubs `SERPER_API_KEY=test-key-for-imports` so `_bench_serper` import doesn't crash; never instantiates `SerperClient` so no live Serper hit. **The bench itself is the integration test for vendors** — these unit tests exclusively cover validate/percentile/warm_rows/recall_stats math so a regression in helper logic doesn't silently corrupt a head-to-head decision. **iOS untouched** (203 / 6 unchanged). UI 6 unchanged. 7 skipped unchanged. `pytest -q` reports `692 passed, 7 skipped`. `ruff check backend/ scripts/` clean. `xcodebuild build` clean (iOS untouched). Output of bench run: `scripts/bench_results/bench_<UTC>.json` + `docs/BENCH_VENDOR_COMPARE.md` analysis with MIGRATE / STAY / PARTIAL recommendation. Run command: `python3 scripts/bench_vendor_compare.py` (loads SERPER_API_KEY + GEMINI_API_KEY from `.env`, ~600 calls cap, ~30-45 min wall time).)

> v2.26 — fix/apple-variant-disambiguation [PR pending, stacked on cat-rel-1-followups]: **666 backend** / **203 iOS unit** / 6 iOS UI. Backend +14 in `tests/modules/test_m2_prices.py` covering Rule 2c (Apple chip equality, disagreement-only) + Rule 2d (display size equality, disagreement-only) + structured telemetry on every rejection. **Helper unit (5):** `test_extract_apple_chip_tokens_finds_bare_chip` (M1/M2/M4 with no suffix → `{m1}`/`{m2}`/`{m4}`); `..._finds_pro_max_ultra_suffix` (M3 Pro → `{m3 pro}`, M3 Max → `{m3 max}`, M2 Ultra → `{m2 ultra}`); `..._skips_non_apple_collisions` — the load-bearing safety check, asserts empty set on Logitech M310 (digit-digit boundary blocks `M3` match), M16 carbine (same boundary), Belkin MS220 cable (leading `MS` not `M[1-4]`), Yamaha M1234 receiver (digit-digit boundary), Sony WH-1000XM5 (no `M[1-4]\b` shape); `test_extract_apple_display_size_tokens_finds_inch_variants` (`14-inch` / `13 inch` / `11inch` / `16 inches` all normalize to digit string); `..._skips_out_of_range` (Wusthof 8-inch chef knife, Dell UltraSharp 27-inch monitor, Samsung 55-inch QLED TV all return empty). **Score-level (6):** `test_relevance_chip_disagreement_rejects_m3_listing_for_m4_product` reproduces the user's exact bug — product `name="Apple iPad Pro 11-inch (2024)" gemini_model="iPad Pro 11-inch M4"` against listing `"Apple iPad Pro M3 11-inch 256GB Space Gray Wi-Fi"` → score 0.0; `..._chip_match_passes_when_both_sides_emit_same_chip` (M4 product + M4 listing → `score >= 0.4`); `..._chip_omitted_in_listing_still_passes` is the load-bearing coverage safeguard — product has chip via gemini_model, listing has no chip token (typical used-eBay shape "Apple MacBook Air 13-inch 2022 8GB 256GB Midnight Excellent Condition") → must still score `>= 0.4`; `..._chip_pro_max_distinguished_from_base` (M3 Max product + M3 Pro listing → 0.0, multi-token chip equality); `..._size_disagreement_rejects_15_listing_for_13_product` (M2 13-inch product + M2 15-inch listing → 0.0, same chip + different size); `..._size_omitted_in_listing_still_passes` (size in product gemini_model only, listing has no inch token → still passes). **Telemetry (2):** `..._chip_rejection_emits_telemetry_log` and `..._size_rejection_emits_telemetry_log` — both use `caplog.at_level(logging.INFO, logger="barkain.m2")` and assert `any("apple_variant_gate_rejected" in r.getMessage() and "rule=2{c|d}" in r.getMessage() for r in caplog.records)`. The chip telemetry test was the harder one to write: my first attempt used a listing where the chip identifier (M4) was the only product identifier, so Rule 1 hard-rejected before Rule 2c ran and the log line never fired. Realized Rule 2c only becomes the load-bearing rejection when Rule 1 PASSES via a non-chip identifier (e.g. "Pro 11" adjacent in listing) and chips disagree. Reshaped both tests to use `product.name="Apple iPad Pro 11"` + `gemini_model="iPad Pro 11 M4"` and listing `"Apple iPad Pro 11 M3 256GB Space Gray Wi-Fi"` so "Pro 11" matches as identifier (Rule 1 passes) and chip mismatch is the actual rejection (Rule 2c fires + telemetry logs). Realistic eBay shape too. **Demo-check evergreen guard (1):** `..._demo_check_evergreen_macbook_air_m1_still_passes` — uses the actual demo-check UPC's MBA M1 product shape (`name="Apple MacBook Air M1 13-inch (2020)" gemini_model="MacBook Air M1 13-inch"`) against typical eBay listing `"Apple MacBook Air 13.3-inch M1 8GB 256GB Space Gray (2020)"` and asserts `score >= 0.4`. Critical regression guard: per CLAUDE.md `make demo-check` requires 5/9 retailers, so if this PR accidentally tightened chip/size enforcement to break MBA M1 listings, demo would fail at F&F. Test fails loudly here BEFORE the demo. iOS test count unchanged at 203 (backend-only pack). UI 6 unchanged. 7 skipped unchanged. `make verify-counts` reports `666 passed, 7 skipped` (run from `cd backend` per `L-pytest-cwd-flake`). **Caplog gotcha lesson for future agents:** `record.message` is only populated after a `Formatter.format()` call runs, which caplog does not by default. Use `record.getMessage()` for substring assertions on log content. Spent ~5 minutes debugging "log line didn't fire" before realizing it had fired but `record.message` was an unformatted template. **Sweep plan documented but not executed:** `Barkain Prompts/Apple_Variant_Disambiguation_Sweep_v1.md` defines a 15-SKU validation harness across MacBook Air chip rev / MacBook Pro tier+same-year-chip-swap / iPad gen+Air/Pro chip+display. Not a prerequisite for this targeted fix because the bug was concrete and the disagreement-only semantic mirrors Rule 2/2b which have shipped and stayed stable. Sweep is filed for future expansion if telemetry surfaces silent-zero-results clusters.)

> v2.25 — fix/cat-rel-1-followups [PR pending]: **652 backend** / **203 iOS unit** / 6 iOS UI. Backend +22 across three files. **`tests/modules/test_product_resolve_from_search.py` (+11)** covers L4 + L2 logging. L4 unit (7): `test_resolved_matches_query_passes_when_specs_and_brand_align` (Vitamix 5200 happy path), `..._rejects_pure_digit_drift` (5200 query → E310 result rejected), `..._rejects_voltage_drift` (40V → 80V), `..._rejects_brand_mismatch` (Toro → Greenworks), `..._falls_back_to_query_leading_token_when_brand_absent` (no `query_brand` param → leading meaningful alpha token used), `..._passes_with_no_strict_specs` (iPhone 16 — 2-digit number below the 4-digit floor stays unaffected), `..._passes_when_brand_in_resolved_name_only` (substring haystack covers `resolved_brand=None` case). L4 endpoint integration (3): `test_resolve_from_search_404_when_resolved_drifts_on_voltage` / `..._on_pure_digit_model` / `..._invalidates_bad_cache_entry` (the last one pre-populates `fake_redis` with a Vitamix-5200 → 703113640681 mapping pointing at an E310 Product row → asserts 404 AND `await fake_redis.get(cache_key) is None`). L2 logging (1): `test_gemini_null_logs_reasoning_for_obscure_sku_diagnosis` patches `gemini_generate_json` to return `{"upc": None, "reasoning": "Major US retailers do not currently stock the Husqvarna 130BT..."}`; uses `caplog.at_level(logging.INFO, logger="barkain.m1")` to assert the retry-null log line includes both the device name AND the reasoning substring. One pre-existing fixture realigned: `test_resolve_from_search_devupc_cache_short_circuits_gemini` had bogus product data (`name="Cached Product", brand="Steam"` for a `"Steam Deck OLED"` query, brand `"Valve"`) that the new L4 gate correctly rejected — updated to `name="Valve Steam Deck OLED 1TB", brand="Valve"`; cache-short-circuit intent preserved. **`tests/modules/test_amazon_scraper_api.py` (+8)** covers L1. Helper unit (5): `test_extract_brand_from_url_finds_leading_alpha_segment` (`/Weber-…` → "Weber"; `/Breville-BES870XL-…` → "Breville"), `..._handles_absolute_urls`, `..._rejects_dp_direct` (`/dp/B0...` → None via denylist), `..._rejects_digit_led_slug`, `..._returns_none_for_empty`. Adapter via `respx.mock` (3): `test_fetch_amazon_reinjects_brand_from_url_slug_when_title_stripped` (live Weber Q1200 fixture: `manufacturer=""`, `title="Q1200 Liquid Propane Portable Gas Grill, Red"`, `url="/Weber-51040001-Q1200-Liquid-Propane/dp/B010ILB4KU/..."` → asserts adapter output title startsWith "Weber Q1200"), `..._does_not_double_prefix_when_title_already_has_brand` (Sony WH-1000XM5 + slug-brand "Sony" + title already contains "Sony" → no double prefix), `..._skips_prefix_when_manufacturer_present` (organic with `manufacturer="Apple"` → title untouched). **`tests/modules/test_m2_prices.py` (+3)** covers L3. `test_extract_model_identifiers_catches_digit_led_appliance_sku` (Hamilton Beach 49981A/49963A/49988, Bissell 15999, Greenworks 24252). `test_extract_model_identifiers_skips_capacity_units` (`12000 BTU` / `12000 Btu` / `10000 mAh` skipped via case-insensitive negative lookahead). `test_extract_model_identifiers_does_not_collide_with_capacity_specs` (5-digit anchor cleanly rejects 1080p / 4090Ti). iOS test count unchanged at 203 (backend-only pack). UI 6 unchanged. 7 skipped unchanged. `make verify-counts` reports `652 passed, 7 skipped` (run from `cd backend` per `L-pytest-cwd-flake`). **L1 live verification:** SSH-curled real Decodo response from EC2 into `/tmp/breville_resp.json` and ran `_map_organic_to_listing` against each organic item — 5/5 listings prefixed correctly. End-to-end (Weber Q1200 query on `/api/v1/prices/{id}/stream` returning the Amazon row at retail $279 instead of `no_match`) requires EC2 deploy to verify in-stream. **L2 live verification:** ran `gemini_generate_json` directly against the existing `device_to_upc` prompt for the 3 known-fail SKUs from `backend/` cwd with `dotenv` loading the `.env`. Confirmed Ryobi P1817 already returns a UPC, ASUS CX1 + Husqvarna 130BT correctly null with reasons that justify the refusal — used to motivate REJECTING the originally-proposed prompt-tightening fix path. **Tooling lesson:** when introducing a new gate that runs against existing test fixtures (like L4's brand+spec check), audit fixture data first — `name="Cached Product", brand="Steam"` is exactly the kind of placeholder that passes a permissive pre-fix gate but trips a tighter post-fix one. Adjusting the fixture to realistic data (rather than weakening the gate) preserves both the test's original intent AND the new behavior.)

> v2.24 — fix/category-relevance-1 [PR #67]: **630 backend** / **203 iOS unit** / 6 iOS UI. Backend +13 across two files. **`tests/modules/test_m2_prices.py` (+8)** — 4 cover the FB Marketplace strict-overlap floor: `test_fb_soft_gate_rejects_drip_tray_when_model_missing` (Breville drip tray, overlap 0.5 < 0.6 floor → 0.0), `test_fb_soft_gate_keeps_legit_listing_when_model_missing` (real Breville listing, overlap 0.83 ≥ 0.6 → returns capped 0.5), `test_fb_soft_gate_rejects_grill_cover` (Weber Q1200 grill cover via Q1200 model gate), `test_fb_soft_gate_unchanged_for_non_fb_retailer` (eBay path is hard-gate, no soft fallback). 1 covers the appliance/tool model regex pre-pass: `test_extract_model_normalizes_single_letter_space_digits` (Q1200 extracted from "Weber Q 1200" with negative control on "Use Q 12 of these"). 2 cover the Conair → Cuisinart brand fallback: `test_brand_match_falls_back_to_product_name_first_word` (single-token Cuisinart product name to isolate Rule 3) + `test_brand_match_fallback_does_not_open_unrelated_brands` (Whirlpool listing for a Cuisinart product still rejected). 1 covers Rule 3b "for-template" reject: `test_third_party_for_brand_template_rejected` — 4 listing titles (Uniflasy alphabetic-led, "304 Stainless Steel" digit-led, "6FT for Weber Adapter Hose", "Burner for Weber Q100") all rejected; positive control on real Weber-prefixed listing. **`tests/modules/test_product_search.py` (+5)** covering m1 `_is_tier2_noise` brand-gate + `_query_strict_specs`: `test_is_tier2_noise_rejects_cross_brand_drift` (Toro Recycler → Greenworks/WORX rejected; positive control on real Toro), `test_is_tier2_noise_rejects_voltage_drift` (40V query → 80V row rejected), `test_is_tier2_noise_rejects_pure_digit_sub_sku_drift` (Vitamix 5200 → E310 rejected; positive control on real 5200), `test_is_tier2_noise_preserves_brand_subsidiary_match` (Anker → Soundcore subsidiary still passes via "by Anker" in title), `test_query_strict_specs_extracts_voltage_and_pure_digits` (extraction unit tests + iPhone 16 / WH-1000XM5 negative controls). iOS test count unchanged at 203 (this pack is backend-only). UI 6 unchanged. 7 skipped unchanged. `make verify-counts` reports `630 passed, 7 skipped` for backend (run from `cd backend` per `L-pytest-cwd-flake` — running from repo root spuriously reports 148 failures unrelated to changes). **Sim-driven UI verification was NOT done per-SKU** for the 14 non-Anker SKUs in the audit; the harness probed `/products/resolve` + `/products/search` + `/prices/{id}/stream` directly. Future agents driving sim verification of search-by-name flows should note: **XcodeBuildMCP `type_text` drops all-but-first character on SwiftUI `.searchable` field** — workaround is `printf "query" | xcrun simctl pbcopy <udid>` then tap the field and trigger paste. **Tooling lesson:** an SSE harness using Python `urllib.request` line-iteration silently dropped events when chunked encoding wrapped event boundaries — the v1 harness reported Logitech 0/9 in 14ms while direct `curl` showed 3/9. v2 harness uses `subprocess.run(["curl", "-sN", ...])` and parses `data:` lines from captured stdout. When an SSE harness shows a too-fast empty result, suspect the parser before the backend.)

> v2.23 — fix/interstitial-parity-1 [PR pending]: **617 backend** / **203 iOS unit** / 6 iOS UI. Backend +1 in `tests/modules/test_m6_recommend.py`: `test_recommendation_skips_portal_savings_for_inactive_membership` asserts `portal_savings == 0.0` and `portal_source is None` for both `user_memberships={"rakuten": False}` and `user_memberships={}` — pins the F#1b membership-gate so a future regression that re-introduces aspirational portal stacking would fail loudly. Existing `test_recommendation_stacks_all_three_layers_end_to_end` updated to pass `user_memberships={"rakuten": True}` so the seeded portal stays active under the new gate. **iOS +3** Swift Testing tests in `BarkainTests/Features/Purchase/PurchaseInterstitialViewModelTests.swift`: `receiptRendersWithoutCardWhenPortalSavingsExist` (the canonical demo-path repro: portal-only winner without a card portfolio produces `receipt.hasAnyDiscount == true`, `portalSavings == 4.20`, `portalSource == "befrugal"`, `yourPrice ≈ 205.79`); `receiptRendersWithoutCardWhenIdentitySavingsExist` (same shape for identity-only stacks — confirms F#1 covers the identity branch too); `directPurchaseWhenNothingToStack` (no-card-no-stack genuinely falls through to direct-purchase copy — confirms the directPurchaseBlock path is preserved as the no-discount fallback). The `yourPrice` assertion uses `abs(receipt.yourPrice - 205.79) < 0.005` because `209.99 - 4.20 = 205.79000000000002` in Double arithmetic and exact equality fails. **Test fixture rebase:** `tests/test_demo_check.py:103` `partial = ACTIVE_RETAILERS[:5]` → `[:4]`. F#2 lowered `SUCCESS_THRESHOLD_RETAILERS` from 7 to 5; the existing "below-threshold" test was using exactly 5 retailers, which is now AT the threshold not BELOW it. Bumping to 4 keeps the test meaningful. **XCTest count unchanged at 154**; the +3 from this pack are Swift Testing `@Suite` tests so the Swift Testing count moved 46 → 49. `make verify-counts` reports `203` total iOS unit tests (154 + 49). UI 6 unchanged. 7 skipped unchanged. **Snapshot baseline drift carry-forward:** the iOS 26.3 sim drift documented in v2.22 still applies; this pack added zero new snapshot baselines so no new drift introduced. Pin canonical totals via `make verify-counts` before any guiding-doc edit. **Runner flag unchanged:** `-parallel-testing-enabled NO` still required on iOS. **Sim-contention learning:** running `xcodebuild test` and UI-driving the same sim concurrently kills the test process with `signal kill`. Don't parallelize sim verification with the test suite — finish one before starting the other.)

> v2.22 — fix/sim-edge-case-fixes-v1 [PR #65]: **616 backend** / **200 iOS unit** / 6 iOS UI. Backend +3 in `tests/modules/test_m1_product.py`: `test_validation_422_uses_wrapped_envelope` (asserts the new global `RequestValidationError` handler returns the canonical `{detail:{error:{code:"VALIDATION_ERROR", message, details:{errors:[…]}}}}` envelope, not FastAPI's default 422 shape); `test_resolve_rejects_pattern_upc_all_zeros_without_calling_gemini` (asserts both `gemini_generate_json` AND `upcitemdb_lookup` mocks were `assert_not_called` for `000000000000`); `test_resolve_rejects_pattern_upc_all_ones_without_calling_gemini` (same for `111111111111`). **Test fixture rebase:** sed-replaced 6 placeholder pattern UPCs (`111111111111`, `222222222222`, `333333333333`, `444444444444`, `555555555555`, `666666666666`, `888888888888`) in `tests/test_integration.py` and `tests/modules/test_product_resolve_from_search.py` by bumping the trailing digit so they don't trip the new pattern-UPC reject in `service.py:resolve` (semantics-preserving since both files mock external calls regardless of input value). iOS test count unchanged at 200 — no new tests added in this pack. **iOS snapshot baseline drift (NOT a regression):** 20 snapshot tests fail on the currently-booted iOS 26.3 sim (`ProfileViewSnapshotTests`, `RecommendationHeroSnapshotTests`, `StackingReceiptViewSnapshotTests`, `ConfirmationPromptViewSnapshotTests`, `UnresolvedProductViewSnapshotTests`). Confirmed pre-existing by stashing the 4 iOS files in this pack (`ScannerView`, `SearchView`, `SearchViewModel`, `RecentSearches`) and re-running `RecommendationHeroSnapshotTests` at HEAD: failed identically with the same baselines. Root cause likely sim subpixel/font drift between sim OS versions (the savings-math pack's snapshots were recorded on a slightly different sim state). CLAUDE.md L#2 ("snapshot record-mode workflow is broken") covers the underlying recording issue; a baseline re-record pass is on the Pack 3 candidate list. Reviewers should NOT block on these. Trunk-default `SEARCH_TIER2_USE_EBAY=false` → **616 passing / 0 failing / 7 skipped**. **Runner flag unchanged:** `-parallel-testing-enabled NO` still required on iOS. Pin canonical totals via `make verify-counts` before any guiding-doc edit.)

> v2.21 — feat/savings-math-prominence [PR #64]: 613 backend / 200 iOS unit / 6 iOS UI. Backend +4 from `test_demo_check.py` Pre-Fix C coverage. iOS +10 across `APIClientErrorEnvelopeTests` (Pre-Fix B, +4), `RecommendationHeroSnapshotTests` (Item 1, +3), `StackingReceiptViewSnapshotTests` (Item 2, +3). One re-recorded baseline: `ProfileViewSnapshotTests/test_errorBranch_rendersEmptyState.error.png` picks up softened `APIError.errorDescription` copy.

> v2.20 — fix/demo-prep-1 [PR #63]: **609 backend** / **190 iOS unit** / 6 iOS UI. Backend +12 across three files: `test_product_resolve_from_search.py` gains 5 new tests covering the Item 3 low-confidence 409 gate on `/resolve-from-search` and the new `/resolve-from-search/confirm` endpoint (both `user_confirmed=true` + `user_confirmed=false` paths, plus backcompat for clients that omit `confidence`); new `test_demo_check.py` (+3) + `test_demo_warm.py` (+4) cover the Makefile CLI scripts via mocked httpx. iOS +11: `RecommendationViewModelTests` gains Item 1 insufficient-data state coverage (+3); `ScannerViewModelTests` gains Item 2 notFound-preservation (+1); `SearchViewModelTests` gains Item 2 inline-unresolved state (+2 — one rewritten from alert-toast) and Item 3 confirmation flow (+3); new `UnresolvedProductViewSnapshotTests` (+2, scanner + search contexts) and `ConfirmationPromptViewSnapshotTests` (+2, primary-only + three-candidates). Snapshot baselines under `BarkainTests/Features/{Shared,Search}/__Snapshots__/`. Trunk-default `SEARCH_TIER2_USE_EBAY=false` → **609 passing / 0 failing / 7 skipped**. **Runner flag unchanged:** `-parallel-testing-enabled NO` still required on iOS.)

> Previous: 2026-04-24 (v2.19 — fix/search-relevance-pack-1: 589→597. +8 backend covering relevance pack — price-outlier + FB soft gate + model-family prefix + G-series SKU + upcitemdb.model + partial-listing regex + Tier-2 accessory noise.)

---

## Test Strategy Overview

| Platform | Framework | DB | Key Patterns |
|----------|-----------|----|----|
| Backend (Python) | pytest + pytest-asyncio | Docker PostgreSQL+TimescaleDB (**NOT SQLite**) | Async tests, fakeredis, mocked API adapters, fixture files |
| iOS (Swift) | XCTest | In-memory (no persistence in Phase 1) | Protocol-based mocks, @MainActor test methods, Given/When/Then |

**Target:** Backend tests run in <30s. iOS tests in <60s. Full suite <5min. CI must pass before merge.

---

## Backend Testing

### File Organization

```
backend/tests/
├── conftest.py                    # Shared fixtures: test DB, auth bypass, fakeredis
├── test_health.py                 # Health endpoint
├── test_auth.py                   # Clerk JWT validation
├── test_rate_limit.py             # Rate limiting
├── test_migrations.py             # All tables created successfully
├── modules/
│   ├── test_m1_product.py         # Product resolution
│   ├── test_m2_prices.py          # Price aggregation
│   ├── test_m5_identity.py        # Identity profile + card matching
│   ├── test_m6_recommend.py       # Deterministic stacking (Step 3e)
│   └── ...
└── fixtures/
    ├── bestbuy_response.json      # Canned Best Buy API response
    ├── ebay_response.json         # Canned eBay Browse API response
    ├── keepa_response.json        # Canned Keepa API response
    ├── gemini_upc_response.json       # Canned Gemini UPC lookup response
    ├── upcitemdb_response.json        # Canned UPCitemdb backup response
    ├── container_extract_response.json # Canned container extraction response
    ├── amazon_extract_response.json   # Canned Amazon container response
    ├── walmart_extract_response.json  # Canned Walmart container response
    ├── target_extract_response.json   # Canned Target container response
    ├── sams_club_extract_response.json    # Canned Sam's Club container response
    ├── fb_marketplace_extract_response.json # Canned Facebook Marketplace response
    ├── best_buy_extract_response.json     # Canned Best Buy container response
    ├── home_depot_extract_response.json   # Canned Home Depot container response
    ├── lowes_extract_response.json        # Canned Lowe's container response
    ├── ebay_new_extract_response.json     # Canned eBay (new) container response
    ├── ebay_used_extract_response.json    # Canned eBay (used/refurb) container response
    └── backmarket_extract_response.json   # Canned BackMarket container response
```

### conftest.py Pattern

```python
import pytest
import asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from fakeredis import aioredis as fakeredis

from app.main import app
from app.dependencies import get_db, get_redis, get_current_user

# ── Test Database (Docker PostgreSQL+TimescaleDB) ─────────────
TEST_DATABASE_URL = "postgresql+asyncpg://app:test@localhost:5433/barkain_test"

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="session")
async def test_engine():
    engine = create_async_engine(TEST_DATABASE_URL)
    # Create all tables (or run alembic migrations)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()

@pytest.fixture
async def db_session(test_engine):
    async_session = sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
        await session.rollback()  # Clean up after each test

# ── Fake Redis ────────────────────────────────────────────────
@pytest.fixture
async def fake_redis():
    redis = fakeredis.FakeRedis()
    yield redis
    await redis.flushall()

# ── Auth Bypass ───────────────────────────────────────────────
@pytest.fixture
def mock_user_id():
    return "user_test_123"

@pytest.fixture
async def client(db_session, fake_redis, mock_user_id):
    """Async test client with dependency overrides."""
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_redis] = lambda: fake_redis
    app.dependency_overrides[get_current_user] = lambda: {"user_id": mock_user_id}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()

# ── Auth-Required Client (no user override) ───────────────────
@pytest.fixture
async def unauthed_client(db_session, fake_redis):
    """Client without auth — for testing 401 responses."""
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_redis] = lambda: fake_redis
    # No get_current_user override — auth middleware will reject

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
```

### Schema Drift Auto-Recreate (Step 2i-c)

`backend/tests/conftest.py:_ensure_schema` probes for a known constraint from the most recent migration (`chk_subscription_tier` from migration 0006) before running `Base.metadata.create_all`. If the marker is missing, the test schema is stale — `DROP SCHEMA public CASCADE` + recreate. This catches the common case where a migration adds a column or constraint to an existing table and `create_all` (a no-op for existing tables) silently leaves the test DB in a stale state.

**When adding a new migration that touches existing tables:** update the marker query in `_ensure_schema` to point at the new constraint or column so the drift detection keeps catching the latest state.

**Manual fallback:** `docker compose restart postgres-test` (the container uses tmpfs, so a restart wipes the data cleanly).

### Constraint Violation Tests (SAVEPOINT pattern, Step 2i-b)

When a test deliberately triggers an `IntegrityError` to verify a constraint, wrap the offending statement in a savepoint so the rollback is scoped:

```python
async def test_chk_subscription_tier_rejects_bogus_value(db_session):
    await _seed_user(db_session, subscription_tier="free")
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE users SET subscription_tier = 'enterprise' WHERE id = :id"),
                {"id": user_id},
            )
```

Without `begin_nested()`, the `IntegrityError` rollback poisons the outer fixture transaction with `SAWarning: transaction already deassociated from connection` and breaks teardown.

### Pinning canonical test counts

Before editing any test count in CLAUDE.md / TESTING.md / CHANGELOG.md, run `make verify-counts` (`scripts/verify_test_counts.sh`) and paste the output. demo-prep-1-3 carry-forward: a miscounted total made it into 4 guiding docs before the catch — type a count from memory and it'll happen again.

The script `cd backend`s before pytest (per `L-pytest-cwd-flake`), uses `-parallel-testing-enabled NO` (per `L-parallel-runner`), and sets `SEARCH_TIER2_USE_EBAY=false` (per `L-Experiment-flags-default-off`).

### Backend Test Conventions

**Naming:** `test_[function]_[scenario]_[expected]`
```python
async def test_resolve_product_valid_upc_returns_product(client):
async def test_resolve_product_unknown_upc_returns_404(client):
async def test_get_prices_cached_skips_api_calls(client, fake_redis):
```

**Structure:** Given / When / Then (comments for clarity)
```python
async def test_get_prices_returns_all_retailers(client):
    # Given: a product exists in the DB
    product = await create_test_product(db_session)

    # When: prices are requested
    response = await client.get(f"/api/v1/prices/{product.id}")

    # Then: all retailers are returned, sorted by price
    assert response.status_code == 200
    data = response.json()
    assert len(data["prices"]) == 3
    prices = [p["price"] for p in data["prices"]]
    assert prices == sorted(prices)
```

**Mocking retailer APIs:** Use `pytest-httpx` or `respx` to mock HTTP calls. Canned responses in `tests/fixtures/`:
```python
@pytest.fixture
def mock_bestbuy_response():
    with open("tests/fixtures/bestbuy_response.json") as f:
        return json.load(f)

async def test_bestbuy_adapter_parses_response(mock_bestbuy_response, respx_mock):
    respx_mock.get("https://api.bestbuy.com/v1/products(upc=...)")
        .respond(json=mock_bestbuy_response)

    adapter = BestBuyAdapter(api_key="test")
    result = await adapter.get_price(upc="012345678901")

    assert result.price == 499.99
    assert result.retailer_id == "best_buy"
```

### Backend Test Requirements

- **Docker PostgreSQL+TimescaleDB required** — NEVER use SQLite (TimescaleDB features, generated columns, and array types require PostgreSQL)
- Every step includes tests — not a separate step
- All existing tests must pass after every step
- `ruff check` must pass (lint)
- Mock all external dependencies (retailer APIs, Clerk, etc.)
- One logical assertion per test (but multiple `assert` checking one outcome is fine)

---

## iOS Testing

### File Organization

```
BarkainTests/
├── Features/
│   ├── Scanner/
│   │   └── ScannerViewModelTests.swift
│   ├── Search/
│   │   └── SearchViewModelTests.swift
│   ├── Profile/
│   │   ├── CardSelectionViewModelTests.swift
│   │   ├── IdentityOnboardingViewModelTests.swift
│   │   ├── LocationPickerViewModelTests.swift
│   │   ├── ProfileViewSnapshotTests.swift       # chore/profileview-snapshot-infra
│   │   └── __Snapshots__/                       # Baseline PNGs, tracked in git
│   │       └── ProfileViewSnapshotTests/
│   └── Recommendation/
│       └── RecommendationViewModelTests.swift
├── Services/
│   ├── APIClientTests.swift
│   └── AuthServiceTests.swift
└── Helpers/
    ├── TestFixtures.swift         # Shared mock data
    ├── MockAPIClient.swift        # Protocol-based mock
    ├── SnapshotTestHelper.swift   # UIHostingController host + accessibility sweep + RECORD_SNAPSHOTS gate
    └── XCTestCase+Extensions.swift

BarkainUITests/
├── Screens/                       # Page object pattern
│   ├── ScannerScreen.swift
│   └── SearchScreen.swift
└── Flows/
    └── ScanFlowTests.swift
```

### ViewModel Test Pattern

```swift
final class ScannerViewModelTests: XCTestCase {
    var sut: ScannerViewModel!
    var mockAPIClient: MockAPIClient!

    @MainActor
    override func setUp() {
        mockAPIClient = MockAPIClient()
        sut = ScannerViewModel(apiClient: mockAPIClient)
    }

    override func tearDown() {
        sut = nil
        mockAPIClient = nil
    }

    @MainActor
    func test_onBarcodeScan_resolvesProduct() async {
        // Given
        mockAPIClient.resolveProductResult = .success(TestFixtures.sampleProduct)

        // When
        await sut.handleBarcodeScan(upc: "012345678901")

        // Then
        XCTAssertNotNil(sut.product)
        XCTAssertEqual(sut.product?.name, "Sony WH-1000XM5")
        XCTAssertFalse(sut.isLoading)
    }

    @MainActor
    func test_onBarcodeScan_networkError_showsError() async {
        // Given
        mockAPIClient.resolveProductResult = .failure(.network(.noConnection))

        // When
        await sut.handleBarcodeScan(upc: "012345678901")

        // Then
        XCTAssertNil(sut.product)
        XCTAssertNotNil(sut.error)
    }
}
```

### Mock Pattern

```swift
protocol APIClientProtocol {
    func resolveProduct(upc: String) async throws -> Product
    func getPrices(productId: UUID) async throws -> PriceComparison
}

final class MockAPIClient: APIClientProtocol {
    var resolveProductResult: Result<Product, AppError> = .success(TestFixtures.sampleProduct)
    var getPricesResult: Result<PriceComparison, AppError> = .success(TestFixtures.samplePrices)

    func resolveProduct(upc: String) async throws -> Product {
        try resolveProductResult.get()
    }

    func getPrices(productId: UUID) async throws -> PriceComparison {
        try getPricesResult.get()
    }
}
```

### iOS Test Conventions

- **Naming:** `test_[methodName]_[expectedBehavior]`
- **Structure:** Given / When / Then with comments
- **@MainActor** required on all ViewModel test methods
- **Protocol-first:** Every service has a protocol; mock via conformance
- **Accessibility identifiers:** `enum AccessibilityID { static let scanButton = "scan_button" }`
- **No force unwraps** except in test setup
- **Per-test UserDefaults isolation (Step 2f learning):** any test that touches a service persisting to `UserDefaults` (e.g. `FeatureGateService`'s daily scan counter) must inject a fresh `UserDefaults(suiteName:)` keyed by a UUID in `setUp`. Without isolation, tests share `UserDefaults.standard`, accumulate persisted state across the suite, and eventually trip gates that were never meant to fire in unrelated tests (the 2f tests break `test_reset_clearsPriceState` once cumulative scans hit the daily cap). The `makeDefaults()` helper in `FeatureGateServiceTests.swift` and `ScannerViewModelTests.swift` is the reference implementation.

### Snapshot Testing (chore/profileview-snapshot-infra + smoke followup)

SwiftUI views with branched render paths (the motivating example: `ProfileView`'s 4-way `content` switch — loading, error, empty-profile `ScrollView`, `profileSummary` `ScrollView` — see CLAUDE.md KDL `3g-B-fix-1`) are protected by image-based snapshot tests. The committed baseline PNG is the regression signal: if any shared section disappears from a branch, the branch's baseline diff surfaces the omission on the next snapshot run. Every branch of the render switch has its own test; state permutations that materially change the inner layout (e.g. a profile with flags in all 3 chip-row categories vs only one) also get their own test when the layout delta is non-trivial.

- **Dependency:** `pointfreeco/swift-snapshot-testing` at 1.19.2, SPM-scoped to the `BarkainTests` target only (never the app target).
- **Helper:** `BarkainTests/Helpers/SnapshotTestHelper.swift` owns the hosting-controller setup, pinned snapshot surface (402×2800 @3x — wider-than-device height so scrollable views don't clip), and the record-mode gate. A `UIWindow`-mount is needed in `host(_:)` so SwiftUI's `.task` modifier treats the view as "on-screen" and the view's async profile load fires.
- **Capturing in-flight UI states:** `MockAPIClient.getIdentityProfileDelay` holds the identity load open so the `isLoading == true && profile == nil` branch can be captured before it transitions. The snapshot test passes a small `flushTaskIterations` count (3) to stop yielding before the delay expires. Post-capture the sleeping Task is harmless — swift-testing cancels on suite exit.
- **No accessibility-grep assertion.** Four walker variants were tried across the original chore and the smoke followup — full `UIAccessibilityContainer` recursion (original), UIView-subview-only, `accessibilityElements` array read, and bounded-bridge probe with wall-clock budget. All failed: the original wedged for 60+ seconds on iOS 26.4; the subview-only variants returned 0 identifiers because SwiftUI's `.accessibilityIdentifier` modifier doesn't propagate to `UIView.accessibilityIdentifier` nor to the `accessibilityElements` array on the rendered hosting-controller tree (only through the informal `UIAccessibilityContainer` protocol whose recursion is the original slow path). The `accessibilityIdentifiers(in:)` helper was deleted in the cleanup PR (#59) since it had no callers and no plausible path back to viability — the comment in `SnapshotTestHelper.swift` points back here. Identifiers on the 6 shared `ProfileView` sections (`kennelHeader`/`scentTrailsCard`/`subscriptionSection`/`marketplaceLocationSection`/`cardsSection`/`portalMembershipsSection`) are still added in view code — they're useful for XCUITest queries and serve as a self-documenting contract for "this section lives in both `ScrollView` branches."
- **Other views don't need this treatment (audit: L-smoke-7).** `ContentView`, `SearchView`, `ScannerView`, `PriceComparisonView`, `HomeView`, `SavingsPlaceholderView`, `Billing/*`, and `Recommendation/*` were all scanned for the 3g-B pattern ("each branch owns its own top-level container with 2+ duplicated sections"). None match — every other branched view uses the single-shared-container-with-subview-switch shape. Don't default-audit the codebase on future snapshot work; check the specific suspect view first.
- **Record workflow:**
  1. Add `RECORD_SNAPSHOTS=1` to the `Barkain` scheme's **Test** action → Environment Variables.
  2. Run the affected snapshot test(s) once. New PNGs land under `BarkainTests/Features/<feature>/__Snapshots__/<SuiteName>/`.
  3. Visually review the generated PNGs. Commit them alongside the test code.
  4. Remove the env var and re-run to confirm assertions pass against the committed baselines.
- **CI:** Do NOT set `RECORD_SNAPSHOTS` in CI — a missing baseline should fail the build. This forces developers to own baseline generation + review locally.
- **Runner flag:** still `-parallel-testing-enabled NO` (from 3g-A) — snapshot tests share the same simulator-process fragility as other swift-testing `@Test` functions.
- **Size note:** PNGs are ~1–1.3 MB each at 402×2800 @3x. If a new snapshot comes in noticeably larger, confirm the surface isn't being rendered at higher-than-@3x scale before committing.

---

## UI Tests (Phase 2+)

### Page Object Pattern

```swift
struct ScannerScreen {
    let app: XCUIApplication

    var scanButton: XCUIElement { app.buttons["scan_button"] }
    var resultLabel: XCUIElement { app.staticTexts["product_name"] }

    func tapScan() -> RecommendationScreen {
        scanButton.tap()
        return RecommendationScreen(app: app)
    }
}
```

---

## CI Test Configuration

### Backend (GitHub Actions)

```yaml
services:
  postgres:
    image: timescale/timescaledb:latest-pg16
    env:
      POSTGRES_DB: barkain_test
      POSTGRES_USER: app
      POSTGRES_PASSWORD: test
    ports:
      - 5432:5432
    options: >-
      --health-cmd "pg_isready -U app"
      --health-interval 5s
      --health-timeout 3s
      --health-retries 5
  redis:
    image: redis:7-alpine
    ports:
      - 6379:6379

steps:
  - uses: actions/setup-python@v5
    with: { python-version: "3.12" }
  - run: pip install -r requirements.txt -r requirements-test.txt
  - run: alembic upgrade head
    env:
      DATABASE_URL: postgresql+asyncpg://app:test@localhost:5432/barkain_test
  - run: pytest --tb=short -q --cov=app
  - run: ruff check .
```

### iOS (GitHub Actions)

```yaml
steps:
  - uses: actions/checkout@v4
  - run: sudo xcode-select -s /Applications/Xcode_16.app
  - run: |
      xcodebuild test \
        -scheme Barkain \
        -destination 'platform=iOS Simulator,name=iPhone 16,OS=18.0' \
        -resultBundlePath TestResults.xcresult \
        -enableCodeCoverage YES
  - run: swiftlint
```

---

## Test Inventory

Update this table after every step:

| Phase/Step | Backend | iOS Unit | iOS UI | Snapshot | New This Step |
|-----------|---------|----------|--------|----------|---------------|
| Step 1a | 14 | 0 | 0 | 0 | 14 (health×4, auth×3, rate_limit×3, migrations×2, seed×2) |
| Step 1b | 26 | 0 | 0 | 0 | 12 (validation×3, auth×1, redis_cache×1, postgres×1, gemini×1, upcitemdb×1, 404×1, response_shape×1, ean13×1, idempotency×1) |
| Step 1c | 40 | 0 | 0 | 0 | 14 (url_resolution×2, extract_success×1, extract_timeout×1, extract_conn_error×1, extract_http500×1, extract_retry×1, extract_all_succeed×1, extract_all_partial×1, extract_all_fail×1, extract_all_specific×1, health_healthy×1, health_timeout×1, response_normalization×1) |
| Step 1d | 50 | 0 | 0 | 0 | 10 (parse_amazon×1, parse_walmart×1, parse_target_sale×1, parse_sams_club×1, parse_fb_used×1, extract_all_5×1, mixed_success_failure×1, correct_retailer_ids×1, amazon_metadata×1, fb_sellers×1) |
| Step 1e | 59 | 0 | 0 | 0 | 9 (parse_best_buy×1, parse_home_depot×1, parse_lowes×1, parse_ebay_new_condition×1, parse_ebay_used_conditions×1, parse_backmarket_refurb×1, extract_all_6_batch2×1, batch2_partial_failure×1, ebay_new_sellers×1) |
| Step 1f | 72 | 0 | 0 | 0 | 13 (cache_miss×1, redis_hit×1, db_hit×1, force_refresh×1, sorted×1, partial_fail×1, all_fail×1, history×1, upsert×1, is_on_sale×1, 404×1, 422×1, auth×1) |
| Step 1g | 72 | 9 | 0 | 0 | 9 iOS (scan_resolve×1, scan_network_error×1, scan_loading×1, scan_clear_old×1, scan_reset×1, api_decode_product×1, api_404×1, api_decode_prices×1, placeholder×1) |
| Step 1h | 72 | 21 | 0 | 0 | 9 iOS (resolve_and_prices×1, loading_states×1, price_error×1, force_refresh×1, partial_results×1, savings_calc×1, best_price×1, reset_price_state×1, resolve_fail_skips_prices×1) + existing test updated |
| Step 1i | 84 | 21 | 0 | 0 | 12 backend integration (full_flow×7, error_format×5) |
| Step 2a | 104 | 21 | 0 | 0 | 20 (ai_abstraction×4, health_monitor×5, watchdog×8, pre_fix_verifications×3) |
| Walmart adapter routing (post-2a) | 128 | 21 | 0 | 0 | 24 (walmart_http×15: proxy URL builder×4, happy path×2, challenge retry×2, http/parse/timeout/missing-creds errors×4, parser edge cases×3 + walmart_firecrawl×9: happy path×1, request shape×1, 6 error surfaces, + 2 existing fixture updates) |
| Scan-to-Prices Live Demo (2026-04-10) | 128 | 21 | 0 | 0 | **0 new** — live validation session, not a code-gen step. 7 live-run bugs fixed but no tests added; test gap documented below and deferred to Step 2b |
| Step 2b | 152 | 21 | 0 | 0 | 24 (cross_validation×6: gemini→upcitemdb second-opinion, confidence scoring, category mismatch detection, fallback trigger, cache invalidation on correction, wrong-product rejection + relevance_scoring×8: model_number_hard_gate×2, brand_match×2, token_overlap×2, threshold_filter×1, pick_best_with_scoring×1 + walmart_first_party×4: first_party_filter×2, sponsored_exclusion×1, seller_name_extraction×1) + 6 integration tests with skip guard |
| Step 2b-val Live Validation (2026-04-12) | 152 | 21 | 0 | 0 | **0 new** — live validation session, 3 extract.js + regex fixes landed without new tests. See `Barkain Prompts/Step_2b_val_Results.md`. Same gap as Scan-to-Prices Live Demo; real-API smoke tests deferred to a dedicated CI step |
| Post-2b-val Hardening (2026-04-12) | 152 | 21 | 0 | 0 | **0 new**, 1 existing test updated (`test_walmart_http_adapter::test_fetch_walmart_success_returns_listings` now asserts `Restored → refurbished` instead of `used`). Session added: per-retailer status system, sub-variant hard gate, Amazon refurb + installment fixes, supplier-code cleanup, accessory filter, manual UPC entry — all live-validated against real Amazon/Walmart/Best Buy but not unit-tested. Test-debt paid down in Step 2b-final. See CLAUDE.md § "Post-2b-val hardening COMPLETE" |
| Step 2b-final (2026-04-13) | 181 | 21 | 0 | 0 | 35 new: M1 model-field×2 (resolve_exposes_gemini_model + resolve_handles_null_gemini_model), M2 gemini_model relevance×5 (generation_marker×2, gpu_model×2, backward_compat×1), hardening×24 (clean_product_name×4, is_accessory×4, ident_to_regex×3, variant_equality×2, classify_error×2 + 8-code parametrize, retailer_results_e2e×1), carrier-listing×4. Paid down the "most load-bearing test-debt item" from post-2b-val. `_MODEL_PATTERNS[5]` + `_ORDINAL_TOKENS` added for GPU + generation-marker scoring. |
| Step 2c (2026-04-13) | 192 | 32 | 0 | 0 | 22 new: backend stream×11 (`test_m2_prices_stream.py` — as_completed completion order, success/no_match/unavailable event payloads, Redis cache short-circuit, DB cache short-circuit, force_refresh bypass, SSE content-type, 404-before-stream-opens, end-to-end wire parsing, unknown product raises) + iOS SSE parser×5 (`SSEParserTests.swift` — single event, multiple events, multi-line data, trailing flush, comment/unknown lines ignored) + iOS scanner stream×6 (`ScannerViewModelTests.swift` — incremental retailerResults mutation, sortedPrices re-sorts as events arrive, `.error` event clears comparison, thrown-error falls back to batch, closed-without-done falls back, bestPrice tracks cheaper retailer). PF-2 eliminated 33 pytest warnings by removing redundant `pytestmark = pytest.mark.asyncio` (asyncio_mode=auto is set in pyproject.toml). Streaming tests drive the generator directly via an injected `_FakeContainerClient` for the service-level assertions, and use `httpx.AsyncClient.stream()` + an `_collect_sse()` line parser for the endpoint-level assertions. |
| Step 2c-fix (2026-04-13) | 192 | 36 | 0 | 0 | 4 new byte-level SSE parser tests (`SSEParserTests.swift` — `test_byte_level_splits_on_LF`, `test_byte_level_handles_CRLF_line_endings`, `test_byte_level_flushes_partial_trailing_event_without_final_blank_line`, `test_byte_level_no_spurious_events_from_partial_lines`). Driven through a new test-visible `SSEParser.parse(bytes:)` entry point that accepts any `AsyncSequence<UInt8>`, over a hand-rolled `ByteStream` fixture that yields bytes one at a time with `Task.yield()` between each — simulating wire-level delivery. **These tests would not have caught 2c-val-L6** (the root cause was `URLSession.AsyncBytes.lines` buffering, which is specific to the real URLSession pipeline and impossible to reproduce in a unit test without a real TCP connection). They guard against regressions in the manual byte splitter — the buffering bug itself is guarded by the os_log instrumentation which makes any future regression observable in a single sim run. Live-backend XCUITest deferred to Step 2g. |
| Step 2d (2026-04-14) | 222 | 43 | 0 | 0 | 37 new: **backend 30** — `test_m5_identity.py`×18 (profile CRUD×4: get-default-if-none, get-existing, create-via-post, update-full-replace; matching×5: no-flags-empty, military-union, multi-group union, Samsung-9-row dedup, inactive-excluded; savings math×5: percentage $1500×30%=$450, cap $10000×10% → $400, fixed_amount, no-product-id null, no-prices null; endpoints×3: /discounts empty-for-new-user, /discounts end-to-end-after-POST, /discounts/all excludes-inactive; performance×1: seed 66 programs, median of 5 runs < 150ms) + `test_discount_catalog_seed.py`×12 (pure-Python lint: unique ids, _direct suffix, count==8, known retailers, eligibility vocabulary matches `ELIGIBILITY_TYPES`, verification_method whitelist, discount_type whitelist, program_type whitelist, no duplicate tuples, percentage values in (0,100], non-negative max_value, military covers samsung/apple/hp regression guard). **iOS 7** — `IdentityOnboardingViewModelTests.swift`×4 (save_callsAPI_withCorrectFlags, skip_callsAPI_withAllFalse, saveFailure_setsError, editFlow_preservesInitialProfile) + `ScannerViewModelTests.swift`×3 (fetchIdentityDiscounts_firesAfterStreamDone, fetchIdentityDiscounts_emptyOnFailure_doesNotSetPriceError, fetchIdentityDiscounts_clearedOnNewScan). Both backend test files use helper functions `_seed_user/_seed_retailer/_seed_program/_seed_product_with_price` for consistency with `test_m2_prices.py` style. The performance gate runs 5 queries with `time.perf_counter()`, takes the median to smooth CI variance, and asserts < 150ms (50ms local-dev target; 150ms upper bound for GitHub Actions cold-Postgres). |
| Step 2e (2026-04-14) | 252 | 53 | 0 | 0 | 40 new: **backend 30** — `test_m5_cards.py`×22 (catalog×3: empty, active-only filter, 30-active; portfolio CRUD×6: add + list, add unknown → 404, re-activate soft-deleted, set preferred unsets others, user categories upsert, reject unknown user-picked category; matching×8: rotating 5x > CSP 1x at Amazon + dollar math, static bonus wins at online_shopping, user-selected Cash+ 5x at best_buy, no-cards → `user_has_cards: false`, expired rotating ignored, activation flag propagates, one-rec-per-retailer for 3-retailer product, ≤150ms perf gate with 5 cards; infra×2: users-row upsert on first add_card, `_quarter_to_dates` helper unit test; error surfaces×3: INVALID_CATEGORY_SELECTION 400, CARD_NOT_FOUND 404). `test_card_catalog_seed.py`×8 (pure-Python lint: card_count==30, issuers match vocab, currencies match vocab, no-duplicate-tuples, display names unique, category_bonuses shape + user_selected requires non-empty allowed, all 8 Tier 1 issuers represented, base rates positive, points cards carry conservative cpp, rotating references valid cards, rotating categories non-empty, Q2 2026 dates, Cash+/Customized Cash excluded from rotating). **iOS 10** — `CardSelectionViewModelTests.swift`×7 (load populates catalog + user cards, filteredGroups alphabetical with `US Bank` special-case, addCard calls API and updates portfolio, addCard user_selected card opens category sheet, removeCard soft-deletes locally, togglePreferred unsets others, setCategories calls API with quarter + clears pending sheet) + `ScannerViewModelTests.swift`×3 (fetchCardRecommendations_firesAfterIdentityDiscounts, emptyOnFailure_doesNotSetPriceError, clearedOnNewScan). TestFixtures + MockAPIClient extended with `sampleCardProgram`/`sampleUserCardSummary`/`sampleCardRecommendationsResponse` + 7 call-tracking properties. Removed `test_recommendations_lowest_price_per_retailer` — the composite UNIQUE constraint on `(product_id, retailer_id, condition)` prevents seeding multiple prices at the same retailer, making the dedup branch unreachable from tests. |
| Step 2f (2026-04-14) | 266 | 63 | 0 | 0 | 24 new: **backend 14** — `test_m11_billing.py`×14 (webhook×8: initial_purchase_sets_pro, renewal_sets_new_expiration with SET-not-delta assertion, non_renewing_lifetime → expires_at NULL, cancellation_keeps_pro_until_expiration, expiration_downgrades_to_free, invalid_auth_returns_401 with WEBHOOK_AUTH_FAILED code, unknown_event_acknowledged with no-DB-write assertion, idempotency_same_event_id → action=duplicate; status×3: free_user, pro_user_with_expiration, expired_pro_downgrades_in_response with DB-row-unchanged assertion; rate limiter×2: free_user_uses_base_limit (3/min cap → 4th 429), pro_user_doubled (6 succeed, 7th 429); migration×1: migration_0004_index_exists queries pg_indexes for indexdef containing UNIQUE/card_issuer/card_product). Helpers `_seed_user(...arbitrary fields)`, `_build_event`, `_webhook_headers(secret)`, `_future_ms/_past_ms` for expiration math. Webhook tests use `monkeypatch.setattr(settings, "REVENUECAT_WEBHOOK_SECRET", "test_secret")`. **iOS 10** — `FeatureGateServiceTests.swift`×8 (free_hits_limit_at_10, pro_unlimited, daily_rollover_with_mutable_clock_closure, canAccess_fullIdentityDiscounts_false_for_free, canAccess_cardRecommendations_false_for_free, canAccess_all_features_true_for_pro_iterates_ProFeature_allCases, remainingScans_nil_for_pro, hydrate_restores_persisted_count). Each test uses a fresh UUID-suffixed `UserDefaults(suiteName:)` via `makeDefaults()` helper to prevent quota leakage. `ScannerViewModelTests.swift`×2 (scanLimit_triggersPaywall_blocksFetchPrices: gate pre-loaded to limit, scan resolves product but skips prices, showPaywall flipped, getPricesCallCount stays 0; scanQuota_consumedOnlyOnSuccessfulResolve: failing resolve does NOT increment dailyScanCount, subsequent successful resolve does). `setUp` updated to inject a per-test UUID-suffixed UserDefaults suite + FeatureGateService — without this, all ScannerViewModelTests share UserDefaults.standard and accumulate scans, causing `test_reset_clearsPriceState` to silently break mid-suite once cumulative scans hit the 10/day cap. |
| Step 2h (2026-04-14) | 301 | 66 | 0 | 0 | 21 new backend — **`backend/tests/workers/`** new package. `test_queue_client.py`×4 (send_message_round_trip, receive_empty_queue, delete_message_removes, get_queue_url_caches) — all wrapped in `with mock_aws():` from `moto[sqs]` 5.x so the tests run hermetic with no LocalStack container. `test_price_ingestion.py`×4 (enqueue_stale_products_sends_one_per_stale_product: seeds 3 products with stale/fresh `last_checked`, asserts SQS receives exactly the 2 stale IDs; enqueue_skips_products_without_prices: 0-price product → 0 messages; process_queue_calls_price_service_with_force_refresh: monkeypatches `PriceAggregationService.get_prices` to count `force_refresh=True` calls, confirms message is ack+deleted after success; process_queue_skips_unknown_product: random UUID in body → ack+delete without calling the service). `test_portal_rates.py`×6 (parse_rakuten_extracts_phase1_retailers + parse_topcashback_... + parse_befrugal_at_least_two: load `backend/tests/fixtures/portal_rates/{rakuten,topcashback,befrugal}.html` captured from live probes on 2026-04-14, parser returns `PortalRate` list, assert ≥3/≥3/≥2 Phase-1 retailers + Decimal rates; normalize_retailer_aliases: `"Best Buy"`/`"Lowe's"`/curly `U+2019` apostrophe/`"The Home Depot"` all resolve, `"Unknown Store"`→None; upsert_portal_bonus_seeds_baseline_on_first_write: normal_value == bonus_value on first observation, `is_elevated` reads back False; upsert_portal_bonus_detects_spike_via_generated_column: second scrape at 10 with preserved baseline 5 → `bonus_value=10`, `normal_value=5` preserved, `is_elevated=True` from the Postgres GENERATED column). `test_discount_verification.py`×7 (verify_active_program_updates_last_verified: 200 + program name in body → `consecutive_failures=0`, `last_verified` set; flagged_missing_mention_does_not_increment: 200 but body missing name → `flagged` counter +1, `consecutive_failures` stays 0, `is_active=True`; 404_increments_failure_counter; network_error_increments_failure_counter (respx `side_effect=httpx.ConnectError`); three_consecutive_failures_deactivates: seed `consecutive_failures=2`, 500 response → 3, `is_active=False`; successful_verification_resets_failure_counter: seed 2 → 200+mention → 0; skips_programs_without_verification_url). All discount verification tests use `respx.mock` to intercept `httpx.AsyncClient.get`. **Test isolation bug fix:** initially used `await db_session.refresh(program)` after the worker mutated in-memory state — `refresh()` does not autoflush, so it re-read the stale pre-mutation row and caused 6 false failures. Removed all `refresh()` calls; the in-memory instance is mutated in place so direct attribute inspection works. Documented in 2h learnings. **SQSClient endpoint sentinel fix:** initial constructor `endpoint_url or settings.SQS_ENDPOINT_URL or None` couldn't distinguish "explicit None override" from "use settings fallback" — `None or "http://localhost:4566" or None` → `"http://localhost:4566"`. Replaced with a `_UNSET = object()` sentinel so tests can pass `endpoint_url=None` to force default boto3 resolution (compatible with `moto.mock_aws`). iOS untouched — 0 new iOS tests. |
| Step 2i-b (2026-04-15) | 302 | 66 | 0 | 0 | **+1 backend** — `test_m11_billing.py::test_migration_0006_subscription_tier_constraint` verifies `chk_subscription_tier` exists in `pg_constraint` and rejects a subscription_tier outside `{'free','pro'}`. The bad-value UPDATE is wrapped in `db_session.begin_nested()` (a SAVEPOINT) so the IntegrityError rolls back only the savepoint and leaves the outer fixture transaction intact for teardown — this fixed a `SAWarning: transaction already deassociated from connection` that the first cut produced when it called `db_session.rollback()` directly. iOS untouched. **Refactor coverage:** `_classify_retailer_result` extraction in `m2_prices/service.py` is exercised end-to-end by the existing 11 stream tests + 12 batch tests + 12 integration tests, all unchanged. |
| Step 2i-c (2026-04-15) | 302 | 66 | 0 | 0 | **0 new tests** — operational validation step. `_ensure_schema` in `backend/tests/conftest.py` gained drift detection (probes `pg_constraint` for `chk_subscription_tier`; if missing, drops + recreates the public schema) — verified by restarting `barkain-db-test` (wipes tmpfs) and re-running the suite, which exercises the drop+recreate branch and still passes 302/6. CI workflow now runs `ruff check backend/ scripts/` after pytest. |
| Step 2i-d (2026-04-15) | 302 | 66 | **2 UI** | 0 | **+1 iOS UI test** — `BarkainUITests/BarkainUITests.swift::testManualUPCEntryToAffiliateSheet` replaces Xcode boilerplate (`testExample` + `testLaunchPerformance` deleted; `BarkainUITestsLaunchTests.testLaunch` kept). E2E flow: launch → tap `manualEntryButton` → type UPC `194252818381` → tap `resolveButton` → wait up to 90 s for any of `retailerRow_amazon`/`_best_buy`/`_walmart` via an `expectation(for:evaluatedWith:)` OR → tap the one that appears → assert affiliate sheet presents via OR of 3 signals (`app.webViews.firstMatch` exists, `app.buttons["Done"]` exists, or original row `!isHittable`). iOS 26's SFSafariViewController chrome is not in the host app's accessibility tree, which is why the assertion is OR'd across weak signals — the **authoritative proof** is the backend-side `affiliate_clicks` row with `click_url LIKE '%tag=barkain-20%'` and `affiliate_network='amazon_associates'`. **Preconditions** for running: (1) `DEMO_MODE=1` on the uvicorn backend (without it `/products/resolve` 401s); (2) 11-port SSH tunnel forwarding 8081–8091 so the SSE stream reaches real retailer containers; (3) AirPods 3 UPC already cached in `products` table so resolve short-circuits Gemini. Watchdog side: caught latent `CONTAINERS_ROOT = parents[1] / "containers"` bug on the first live `--check-all` — every `selector_drift` heal failed with "extract.js not found" before reaching Opus. One-line fix (`parents[2]`), validated via `--heal ebay_new`. No backend test was added for the path fix because every 2h watchdog test stubs the filesystem — the real protection is operational, not unit-level. |
| Step 2g (2026-04-14) | 280 | 66 | 0 | 0 | 20 new: **backend 14** — `test_m12_affiliate.py`×14 (pure URL construction×9: amazon_tag_appended_no_existing_params (asserts `?tag=barkain-20` suffix), amazon_tag_appended_with_existing_params (asserts `&tag=` branch + `?psc=1` preserved + single `?`), amazon_untagged_when_env_empty (passthrough with `is_affiliated=false`, `network=None`), ebay_new_rover_redirect_encodes_url (asserts rover skeleton + `campid=5339148665` + `toolid=10001` + percent-encoded `mpre=https%3A%2F%2Fwww.ebay.com%2Fitm%2F12345%3Fvar%3D99`), ebay_used_uses_same_network (same rover shape via `EBAY_RETAILERS` frozenset), walmart_tagged_when_env_set (monkeypatches `WALMART_AFFILIATE_ID=test-wmt-id`, asserts `goto.walmart.com/c/test-wmt-id/1/4/mp?u=<encoded>`), walmart_passthrough_when_env_empty, best_buy_passthrough (denied network), home_depot_passthrough (unaffiliated); click endpoint×3: click_endpoint_logs_row_and_returns_tagged_url (asserts `SELECT affiliate_network, click_url FROM affiliate_clicks WHERE user_id=...` returns `amazon_associates` + `tag=barkain-20`), click_endpoint_passthrough_logs_sentinel (asserts `affiliate_network='passthrough'` NOT NULL sentinel for Best Buy), stats_endpoint_groups_by_retailer (logs 2 amazon + 1 best_buy, asserts `{clicks_by_retailer: {amazon: 2, best_buy: 1}, total_clicks: 3}`); conversion webhook×2: conversion_webhook_permissive_without_secret (empty env → 200 no-auth), conversion_webhook_bearer_required_when_secret_set (401 for missing + wrong bearer, 200 for correct)). New `_seed_retailer(db_session, retailer_id)` helper inserts a minimal retailers row (only NOT NULL columns) so `affiliate_clicks.retailer_id` FK lands. 9 of 14 are pure-function tests — no DB fixture required — using `monkeypatch.setattr(settings, "AMAZON_ASSOCIATE_TAG", "barkain-20")` against the `@staticmethod AffiliateService.build_affiliate_url`. **iOS 6** — `ScannerViewModelTests.swift`×3 (`test_resolveAffiliateURL_returnsTaggedURLOnSuccess`: stubs `MockAPIClient.getAffiliateURLResult` with Amazon-tagged URL, calls helper after `handleBarcodeScan`, asserts tagged URL + call count; `test_resolveAffiliateURL_fallsBackOnAPIError`: stubs `.failure(.network(URLError(.notConnectedToInternet)))`, asserts original `retailerPrice.url` comes back wrapped in a URL, NOT nil, and that the helper tried the API before falling back; `test_resolveAffiliateURL_passesCorrectArguments`: validates `getAffiliateURLLastRetailerId == "best_buy"`, `...LastProductURL == "https://bestbuy.com/site/123"`, `...LastProductId == samplePriceComparison.productId`). `IdentityDiscountCardTests.swift`×3 (`test_resolvedURL_prefersVerificationURL` when both fields set, `test_resolvedURL_fallsBackToURLWhenVerificationMissing` when only `url` set, `test_resolvedURL_returnsNilWhenBothMissing`). `IdentityDiscountCard.resolvedURL` is exposed as a new testable computed property (prefers `verificationUrl`, falls back to `url`, nil when both missing). `makeDiscount(verificationUrl:url:)` factory avoids boilerplate per test. |
| Step 3a (2026-04-16) | 312 | 72 | **3 UI** | 0 | **+17** — **backend 10** — `test_product_search.py`×10 (rejects_short_query, rejects_empty_query, pagination_cap>20, normalizes_query (casing+whitespace collapse → same cache key, ≤1 Gemini call across two requests), db_fuzzy_match (seed 3 iPhones, search "iPhone 16" → all returned with source=db), cache_hit (second identical query returns cached=true, zero additional Gemini calls), gemini_fallback (empty DB → mocked Gemini returns 3 → response has 3 source=gemini rows), gemini_dedup (DB=2 + Gemini=3-with-1-dup by lowercased (brand,name) → final 4), rate_limit (monkeypatched `RATE_LIMIT_GENERAL=3` → 4th call 429), pg_trgm_index_exists (queries pg_indexes for `idx_products_name_trgm`)). Gemini mocked at `modules.m1_product.search_service.gemini_generate_json` boundary — same pattern as `test_m1_product.py`. **iOS 6 unit** — `SearchViewModelTests.swift`×6 (debounce cancels 5 rapid queries and only fires the last one via an AsyncStream-gated clock; populatesResults_onSuccess; setsError_onAPIFailure; recentSearches persist across fresh VM + cap at 10 FIFO; handleResultTap_dbSource navigates immediately (no `/resolve` call); handleResultTap_geminiSource calls `/resolve` with the primary_upc). Each test uses a per-UUID `UserDefaults(suiteName:)` so recent-search state doesn't leak. **iOS 1 UI** — `SearchFlowUITests.swift::testTextSearchToAffiliateSheet` — tap Search tab → type "AirPods 3rd Generation" → wait for `searchResultRow_*` → tap → wait 90s for any `retailerRow_*` via OR-of-3 expectations → tap retailer → OR-of-3-signal affiliate sheet assertion (same pattern as 2i-d `testManualUPCEntryToAffiliateSheet`). Requires live backend + retailer tunnels; same preconditions as 2i-d. **Preview stubs** — added `searchProducts` stub to `PreviewAPIClient` (PriceComparisonView), `PreviewCardAPIClient`, `PreviewOnboardingAPIClient`, `PreviewProfileAPIClient`, and `MockAPIClient`. **Swift 6:** `SearchViewModel.defaultDebounceNanos` had to be marked `nonisolated` because the class is `@MainActor` and the constant is used as a default argument expression. |
| Step 3b (2026-04-17) | 335 | 72 | **3 UI** | 0 | **+13 backend** — `test_ebay_webhook.py`×5 (GET handshake returns SHA-256(challenge + token + endpoint) as hex, 503 when EBAY_VERIFICATION_TOKEN unset, 503 when EBAY_ACCOUNT_DELETION_ENDPOINT unset, POST logs + 204 on well-formed deletion payload, POST still 204 on invalid JSON body — the 204-on-bad-JSON is deliberate so eBay doesn't retry garbage). `test_ebay_browse_api.py`×8 (is_configured requires both App ID + Cert ID; OAuth token mint caches + reuses across calls; happy path maps itemSummaries → ContainerListing with extraction_method=ebay_browse_api and script_version=ebay_browse_api/1.0; conditionIds filter uses `\|` separator not comma — eBay silently no-ops on comma; invalid retailer_id returns INVALID_RETAILER error; 401 from Browse API clears the in-process token cache so next call refreshes; 5xx returns HTTP_ERROR with status_code + first 500 bytes in details; malformed items — no price OR no title — are silently dropped instead of raising). All 8 tests use `respx.mock` to intercept both `POST /identity/v1/oauth2/token` and `GET /buy/browse/v1/item_summary/search`. Autouse `_reset_token_cache` fixture clears the module-level cache before + after each test. **Fixture patch** for `test_container_retailers_batch2.py::_setup_client`: added `client.walmart_adapter_mode = "container"` and `client._cfg = Settings(EBAY_APP_ID="", EBAY_CERT_ID="")` so batch-dispatch tests that use `ContainerClient.__new__(...)` keep routing eBay through the container path (fall-through when creds absent). iOS untouched. |
| Step 3e (2026-04-22) | ~516 | 108 | **5 UI** | 0 | **+14 backend** — `tests/modules/test_m6_recommend.py`×18 covering pure-function stacking (three layers compose correctly with card/portal computed on post-identity price; identity-only, card-only, portal-only stacks; new>refurbished tiebreak; brand-direct callout fires only at `*_direct` retailers with ≥15 % percentage programs; headline builds retailer + portal + card phrases; empty-stack why copy falls back to "Lowest available price"), service-level DB+fakeredis integration (3-layer stacks end-to-end with Samsung product so `IdentityService.BRAND_SPECIFIC_RETAILERS` relevance gate admits samsung_direct; `InsufficientPriceDataError` on <2 usable prices; inactive + drift-flagged retailers excluded from input pack; cache hit on repeat call flips `cached=true`), and endpoint-level tests (404 `PRODUCT_NOT_FOUND`, 422 `RECOMMEND_INSUFFICIENT_DATA`, subprocess-invoked `scripts/seed_portal_bonuses_demo.py` idempotent across two runs via `TEST_DATABASE_URL` env override). **Zero Anthropic / Gemini mocks** — 3e is fully deterministic. **+8 iOS unit** — `RecommendationViewModelTests.swift`×5 covers the three-settle-flag gate on `ScannerViewModel`: fetch fires exactly once after SSE done + identity + cards all settle; failure leaves `recommendation == nil` and NEVER sets `priceError`; 422 `.success(nil)` path leaves hero hidden silently; `reset()` clears recommendation + flags; `fetchPrices(forceRefresh:)` re-fires the hero fetch exactly once. Uses test-only `_awaitRecommendationTaskForTesting()` hook on the VM to deterministically await the fire-and-forget `Task`. `RecommendationDecodingTests.swift`×3 locks snake→camel mapping (full JSON, brand-direct callout + stack, spot-check for `.convertFromSnakeCase`). **+1 UI** — `RecommendationHeroUITests.swift::testScanToRecommendationHeroToAffiliateSheet` drives scan → 120 s wait for first retailer row → assert `recommendationHero` is NOT present during streaming → wait 60 s for hero to materialize post-settle → tap `recommendationActionButton` → OR-of-3 affiliate-sheet signal. `XCTSkip` on missing manual-entry button OR insufficient-data fallthrough so the test is environment-robust. `MockAPIClient` extended with `fetchRecommendationResult/CallCount/LastProductId/LastForceRefresh/Delay`. `TestFixtures` gained `successfulStreamEvents`, `sampleStackedPathAmazon/BestBuy`, `sampleRecommendation`, `recommendationJSON`, `recommendationWithCalloutJSON`. Preview stubs in `PriceComparisonView.PreviewAPIClient`, `PreviewCardAPIClient`, `PreviewOnboardingAPIClient`, `PreviewProfileAPIClient` gained `fetchRecommendation(...)` returning nil. 6 pre-existing auth failures (`test_auth.py`/`test_m1_product.py`/`test_m2_prices.py`/`test_integration.py`/`test_container_client.py`×2) remain unchanged — pre-date this step. |
| Step 3o-A (2026-04-28) | 754 | 207 | 6 UI | 0 | **−3 collected backend** (757→754) — `tests/scripts/test_generate_autocomplete_vocab.py` collapses the 9-case `test_electronics_filter` parametrize block when `is_electronics()` retires (−9) and adds 6 new tests covering the Step 3o-A code paths: `test_non_electronics_terms_pass_through` replaces the dropped REJECT cases; `test_default_sources_includes_six_categories` pins the CLI defaults; `test_scope_probe_gates_extras` exercises `probe_extra_scopes` against synthetic yield sequences (10/10/10 admit, 3/4/2 skip, 6/5/4 admit at boundary); `test_sweep_runs_sources_in_parallel` patches `sweep_source` with a 0.5 s sleep and asserts per-source start-time spread < 100 ms; `test_sweep_soft_fails_on_one_source_error` raises `RuntimeError` from one source and asserts the others' contributions survive plus a warning log fires; `test_output_schema_v2` asserts `version=2`, `stats.scope_probes` + `stats.scope_probes_admitted` present, `after_electronics_filter` removed. One smoke companion `test_real_amazon_endpoint_returns_results_for_pet_supplies_scope` is gated on `BARKAIN_RUN_NETWORK_TESTS=1` (counts as skipped not passed). Two pre-existing end-to-end tests thread `--skip-probes` so the production probe path stays out of respx-stubbed harnesses. iOS untouched. |
| Step 3o-B (2026-04-28) | 773 | 207 | 6 UI | 0 | **+19 backend** (754→773 passed; 8 skipped → 781 collected) — `tests/modules/test_product_search.py` gains 19 tests covering the three-pool noise filter restructure: 3 case soft-pool (`test_case_soft_noise_drops_when_query_lacks_case_token`, `test_case_soft_noise_keeps_when_query_mentions_case`, `test_case_soft_noise_keeps_on_plural_cases_query` — uses plural row title to clear the soft-majority gate downstream of opt-out), 3 charger soft-pool (`test_charger_soft_noise_drops_when_query_lacks_charger_token`, `test_charger_soft_noise_keeps_when_query_mentions_charger`, `test_charger_soft_noise_keeps_on_charging_token`), 5 accessor-context (`test_accessor_drops_gaming_controller_accessories`, `test_accessor_drops_phone_accessories`, `test_accessor_keeps_litter_boxes_accessories` — Discovery v1 §B3 false-negative regression test, `test_accessor_keeps_mixer_accessories`, `test_accessor_keeps_vacuum_accessories`), 4 regression-preservation (`test_existing_thumbstick_title_still_drops` — title gate intact; `test_existing_pixel_10_mobile_pixels_still_drops` — `monitor` hard-pool; `test_existing_warranty_still_drops_unconditionally` — query-agnostic hard-pool; `test_existing_screen_protector_still_drops` — `screen protector` hard-pool), 4 telemetry on `_classify_tier2_noise` (returns `hard_category` for warranty, `soft_category` for case-no-match, `accessor_context` for gaming-accessories, `None` for legitimate Sony WH-1000XM5). All 24 prior tier2/noise tests in the file continue to pass without changes — the existing `test_is_tier2_noise_filters_controller_accessories` rows have categories `Gaming Controller Accessories` (gaming+controller in `_ACCESSOR_CONTEXT_TOKENS`) and `Video Game Accessories` (video game in `_ACCESSOR_CONTEXT_TOKENS`), both still drop via the new accessor-context rule. iOS untouched. `pytest -q` reports `773 passed, 8 skipped`. `ruff check backend/` clean. iOS sim smoke (cat litter unscented / iphone 17 pro max case / anker portable charger / ps5 controller) passed end-to-end. |
| Step 3d (2026-04-19) | ~482 | 100 | **4 UI** | 0 | **+23 backend** — `tests/scripts/test_generate_autocomplete_vocab.py`×23 (Amazon `/api/2017/` JSON-shape parse via fixture `amazon_suggestions_ipho.json`; normalize round-trip + idempotency; TermAccumulator dedup-counts distinct (source,prefix) tuples; electronics filter parametrized — `iphone 17`/`apple watch`/`rtx 4090`/`sony wh-1000xm5`/`western digital ssd`/`hard drive 2tb` pass; `cat food`/`baby diapers` reject; `phone charger lotion` passes only because `amazon_electronics` source-scopes; `--max-terms` cap; throttle invokes monkeypatched sleep ≥2× per-3-prefix sweep; 429 → 429 → 200 retry succeeds; `--resume` loads cached prefix and never hits respx; output schema (version/git_commit/sources/stats/terms{t,s} sort-by-score-desc); `--dry-run` writes nothing; Best Buy + eBay graceful skip on shape drift; end-to-end `run()` writes a valid file with title-cased terms; display_case preserves short uppercase tokens like `PS5`). Plus 1 opt-in real-API smoke gated by `BARKAIN_RUN_NETWORK_TESTS=1` (asserts live Amazon `iph` returns `iphone`-prefixed). All HTTP mocking via `respx.mock` mirrors `test_walmart_http_adapter.py` template. Six pre-existing auth tests in `test_auth.py`/`test_integration.py`/`test_m1_product.py`/`test_m2_prices.py`/`test_container_client.py` fail in clean envs without DEMO_MODE setup — unrelated to 3d. **iOS +34 unit (net)** — `BarkainTests/Services/Autocomplete/AutocompleteServiceTests.swift`×10 (isReady true after first call when bundle present, false+empty when bundle missing, false+empty when JSON malformed; `iph` returns iPhone-only; case-insensitive equivalence across `iph`/`IPH`/`IpH`; ranking: score desc then shorter-first tie-break; limit respected; empty + whitespace-only + unmatched prefixes return []). `BarkainTests/Services/Autocomplete/RecentSearchesTests.swift`×7 (add prepends + dedupes case-insensitive; cap at 10 FIFO; ignores whitespace-only; clear empties storage; persists across instances on same UserDefaults; **legacy-key migration** from pre-3d `recentSearches` → `barkain.recentSearches` on first instantiation; doesn't migrate when new key already populated). `SearchViewModelTests.swift`×17 (rewrite — net +6 vs 3a's 11): empty query → suggestions == recents; non-empty → calls autocompleteService with prefix + limit=8; service unavailable returns empty; suggestion-tap sets query+searches+records recent; submit adds to recents; submit <3 chars no-op; performSearch success/failure paths; deep-search hint thresholds; deepSearch forces gemini; recents cap+persist across VM instances; DB/Gemini/Gemini-no-UPC/404 result-tap branches; clearRecentSearches empties mirror+storage. `MockAutocompleteService` added to `BarkainTests/Helpers/`. Test-bundle fixture `BarkainTests/Fixtures/autocomplete_vocab_test.json` (50 hand-curated terms with predictable prefix groupings). **iOS UI +1** — `SearchFlowUITests.swift::testTypeSuggestionTapToAffiliateSheet`: tap Search tab → tap searchField → type "iph" → wait ≤5s for any `suggestionRow_*` (3-signal OR across `descendants(matching:.any)`/`buttons`/`staticTexts`) → tap → assert results land within 15s OR query-field text was replaced. The existing `testTextSearchToAffiliateSheet` was updated to use `app.searchFields.firstMatch` (was `app.textFields["searchTextField"]`) and to press return after typing (since 3d removes auto-debounce-search). |
| **Total** | **~482** | **100** | **4 UI** | **0** | (Phase 3 open at Step 3d) |

---

## Integration Tests (Step 2b+)

### Pattern: `@pytest.mark.integration` with skip guard

Integration tests live in `backend/tests/integration/test_real_api_contracts.py` and hit real external APIs (Firecrawl, Decodo, Gemini, UPCitemdb, retailer containers). They are **not** run on every push — they require explicit opt-in via environment variable:

```bash
# Run integration tests manually
BARKAIN_RUN_INTEGRATION_TESTS=1 pytest -m integration --tb=short -q

# Run only unit tests (default CI behavior)
pytest --tb=short -q
```

Every integration test is decorated with:
```python
@pytest.mark.integration
```

The marker is registered in `backend/pyproject.toml` via `[tool.pytest.ini_options]` → `markers`. The individual skip guard lives on `test_real_api_contracts.py` itself as a module-level `pytestmark` check for `BARKAIN_RUN_INTEGRATION_TESTS`.

`backend/tests/integration/conftest.py` (added in Step 2b-final) auto-loads `.env` into `os.environ` when `BARKAIN_RUN_INTEGRATION_TESTS=1`, so developers no longer need `set -a && source ../.env && set +a` before every run:

```python
def pytest_configure(config):
    if os.environ.get("BARKAIN_RUN_INTEGRATION_TESTS") != "1":
        return
    env_path = Path(__file__).resolve().parents[3] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
```

### Why separate from unit tests

- **Cost:** Each integration test makes real API calls (Firecrawl credits, proxy bandwidth, Gemini tokens).
- **Rate limits:** Vendors throttle aggressive testing.
- **Flakiness:** Real endpoints have transient failures that would break CI if run on every push.
- **Speed:** Integration tests take 10-60s each vs <100ms for mocked unit tests.

Integration tests complement the respx-mocked unit tests by catching the schema drift and environmental regressions that mocks cannot see (see "Real-API smoke tests" section below for the full rationale from the 2026-04-10 live run).

---

## Testing Principles

1. **Every step includes tests** — tests are part of the step, not a separate step
2. **Test behavior, not implementation** — assert outcomes, not internal calls
3. **Fast tests** — mock all external dependencies (APIs, auth, Redis)
4. **Deterministic** — no flaky tests, no time-dependent assertions without control
5. **Docker PostgreSQL for backend** — never SQLite. TimescaleDB features require real PostgreSQL
6. **Preview providers count as tests** — if it compiles in Preview, the view renders
7. **Fixture files for canned API responses** — `tests/fixtures/*.json`, not inline strings
8. **Mocks are not contracts** — respx + MockAPIClient catch logic bugs but do not validate vendor API schema drift or real subprocess boundaries. Every vendor adapter and every scraper container must ALSO have a real-API smoke test (see next principle).

---

## Real-API smoke tests (added 2026-04-10 after first live run exposed the gap)

> The first-ever live 3-retailer run on 2026-04-10 surfaced 7 bugs that all 128 respx-mocked backend tests and 21 MockAPIClient-backed iOS tests were blind to. The root cause is the same in every case: the unit tests mock the boundary between our code and the outside world, so schema drift / subprocess / stdout / Chromium issues are invisible until something real runs through. Full postmortem: `Barkain Prompts/Error_Report_Scan_to_Prices_Deployment.md` (SP-1 through SP-9).

### Required coverage (Step 2b pre-fix block)

Every adapter and every retailer container must have a companion real-API smoke test:

| Component | Current test coverage | Real-API smoke test required |
|-----------|----------------------|------------------------------|
| `walmart_firecrawl.py` adapter | 7 respx-mocked tests (schema drift invisible) | Nightly GET against real Firecrawl v2 `/scrape` endpoint with a known Walmart URL; assert non-zero listings with non-zero prices |
| `walmart_http.py` (Decodo) adapter | 15 respx-mocked tests | Nightly GET against Walmart via real Decodo proxy; assert non-zero listings |
| `containers/{amazon,best_buy,…}/extract.sh` | 10-14 respx-mocked tests per retailer | Nightly real `POST /extract` against each retailer container; assert `success=true`, `listings|length > 0`, first listing `price > 0`. Reuses `scripts/ec2_test_extractions.sh` as the reference implementation |
| Future Keepa adapter | n/a | Nightly GET against real Keepa API |
| Future UPCitemdb fallback | n/a | Nightly GET against real UPCitemdb API |

**Step 2b-final partial paydown (2026-04-13):** `_clean_product_name`, `_is_accessory_listing`, `_ident_to_regex`, `_classify_error_status`, `retailer_results` construction, `_is_carrier_listing`, and the new `gemini_model` relevance path all now have dedicated unit coverage in `test_m2_prices.py` and `test_walmart_firecrawl_adapter.py`. The real-API smoke tests in `test_real_api_contracts.py` remain the definitive check against schema drift and real subprocess boundaries.

### Cadence and enforcement

- **Every PR** touching `backend/**` or `containers/**` runs unit tests via `.github/workflows/backend-tests.yml` (added Step 2b-final). TimescaleDB + Redis service containers, fake API keys. Note: `DEMO_MODE` is intentionally **not** set in CI — the test client overrides `get_current_user` directly. (Renamed from `BARKAIN_DEMO_MODE` in 2i-b.)
- **Nightly** in CI against the real endpoints, not every push (cost + rate limits). Still to wire up.
- Alert on failure via Slack / email / PagerDuty.
- A smoke test failure is **not a build break** but creates a P1 issue for the next morning.
- These tests do **not** replace the respx unit tests — unit tests stay fast and run on every push. Smoke tests catch schema drift and environmental regressions the unit tests can't see.

### Counter-examples: bugs that respx + MockAPIClient missed on 2026-04-10

- **SP-1** — `agent-browser` writes progress lines to stdout, polluting `json.loads`. Invisible because the container client tests (`test_container_client.py`) mock HTTP responses and never invoke the real subprocess.
- **SP-4** — Firecrawl v2 renamed `country` → `location.country`. Invisible because `test_walmart_firecrawl_adapter.py` uses respx and doesn't validate request body shape.
- **SP-2, SP-3** — `EXTRACT_TIMEOUT=60s` too short and `/tmp/.X99-lock` blocks Xvfb on restart. Invisible because tests never actually run Chromium.
- **SP-5, SP-6** — `.env` overrides for `CONTAINER_URL_PATTERN` and `CONTAINER_TIMEOUT_SECONDS` silently rotted. Invisible because tests don't read `.env`.
- **SP-7** — Zero-price listings dominated `_pick_best_listing`. Invisible because respx fixtures don't mirror real-world extract.js parse failures.
- **SP-8** — iOS URLSession 60 s default timed out before 90 s backend round trip. Invisible because `MockAPIClient` returns synchronously.

All seven of these were one-line or small fixes once discovered. The lesson isn't "write more unit tests" — it's "the mocking boundary is a blind spot, and the blind spot must have its own test discipline."

**Step 2c-val added one more to this list:**

- **2c-val-L6** — `URLSession.AsyncBytes.lines` buffers aggressively for small SSE payloads. The iOS SSE parser's 5 unit tests + ScannerViewModel's 6 stream tests all passed because they inject an `AsyncThrowingStream<RetailerStreamEvent, Error>` above the `URLSession.bytes(for:)` layer, never exercising the real `AsyncBytes.lines` iterator. The bug only surfaced when a real TCP connection delivered events seconds apart — at which point `lines` held them back until stream close, `sawDone` never flipped, and `fallbackToBatch()` fired on every call. Fix: replace `bytes.lines` with a manual byte-level splitter (Step 2c-fix). Same lesson: the mocking boundary was above the actual buffering layer. See also the SSE debugging section below.

---

## SSE debugging (Step 2c-fix)

The iOS SSE consumer emits structured os_log events on the `com.barkain.app` subsystem, category `SSE`. These cover the full pipeline: stream connection opened / HTTP status, each raw line received from the byte splitter, each parsed `SSEEvent`, each decoded `RetailerStreamEvent`, `sawDone` transitions, fallback triggers, stream end / error. os_log is lazy-evaluated and costs nothing in Release builds.

**Watch a live session from the host:**

```bash
xcrun simctl spawn booted log stream \
  --level debug \
  --predicate 'subsystem == "com.barkain.app" AND category == "SSE"' \
  --style compact
```

**Expected happy-path signature:**

```
SSE stream opening for product <uuid> forceRefresh=false
SSE stream opened HTTP 200
SSE raw line: event: retailer_result
SSE raw line: data: {"retailer_id": "amazon", ...}
SSE raw line:
SSE parsed event: retailer_result dataLen=882
SSE decoded: retailerResult(...)
fetchPrices: received event retailerResult(...)
… (repeat for each retailer)
SSE parsed event: done dataLen=292
fetchPrices: sawDone=true succeeded=N failed=M cached=X
SSE stream ended normally
fetchPrices: stream completed successfully
```

**Failure-mode fingerprinting matrix** — read the log, not the stack trace:

| Observation | Root cause |
|---|---|
| `raw line` entries arrive all at once at stream close | Byte splitter regression (buffering returned) |
| `raw line` arrives incrementally but no `parsed event` | Parser state-machine regression |
| `parsed event` fires but no `decoded` | Swift JSON decode mismatch — check the error log line for the field name, inspect the `payload=...` attachment |
| `decoded` fires but no `received event` in ScannerViewModel | VM-level routing regression |
| `sawDone=true` never logs even though `done` arrives | `apply(_:for:)` or `sawDone` state-machine bug |
| `falling back to batch` fires on a healthy backend | Upstream error in one of the above; read the `warning` log line for `sawDone=...` state |

**Live-backend XCUITest:** deferred to Step 2g. The repo has zero UI tests today, and standing up a BarkainUITests target + uvicorn lifecycle + launch-argument plumbing exceeded the Step 2c-fix time budget. The os_log category above is the interim substitute — any regression is observable in one session by running the predicate above during a manual scan flow. When Step 2g adds the UITest, it should:

1. Launch the app with a `BARKAIN_E2E_BASE_URL=http://127.0.0.1:8000` launch argument that overrides `AppConfig.apiBaseURL`.
2. Require `DEMO_MODE=1 uvicorn app.main:app` to be running on `127.0.0.1:8000` (document as a pre-test precondition; fail fast if `/api/v1/health` isn't reachable).
3. Drive the manual UPC entry sheet → type `027242923232` → tap Resolve.
4. Assert within 30s that ≥1 `PriceRow` is visible (proves the stream rendered something before batch would have returned).
5. Assert that NO `XCUIElement` matching "Sniffing out deals..." is visible while prices are rendering (proves stream-driven transition, not batch-driven).
6. Wait for final state, assert ≥1 retailer with a non-nil price when `cached=true`.
