# Walmart Adapter Paradigm Shift — Conversation Summary

| Field | Value |
|-------|-------|
| **Date** | 2026-04-10 |
| **Sessions** | 1 (long but single-context) |
| **Agent** | Claude Code (Opus 4.6, 1M context window) |
| **Branch** | main (work landed directly — no feature branch created for this) |
| **PR** | none — direct commit(s) to main |
| **Tests** | 128 backend passed / 0 failed (104 → 128, +24 new) / 0 xfailed / 21 iOS unchanged |
| **Source** | This conversation summary |

---

## What Was Built

**Backend:**
- **New adapters subpackage** — `backend/modules/m2_prices/adapters/`
  - `__init__.py` — subpackage marker with a one-paragraph docstring pointing to the architecture appendices
  - `_walmart_parser.py` (~200 LOC) — shared `<script id="__NEXT_DATA__">` walker + `ContainerListing` mapper. Filters sponsored placements, detects challenge markers, handles both flat `price` and nested `priceInfo.{linePrice,currentPrice,wasPrice}` shapes, resolves relative URLs to absolute, infers used/new condition from product name.
  - `walmart_firecrawl.py` (~155 LOC) — Firecrawl `POST /v1/scrape` adapter with `rawHtml` format + `country: US` geo-targeting. Bearer auth. 45 s timeout. Error surfaces for missing API key, HTTP errors, `success=false`, empty body, challenge-in-response.
  - `walmart_http.py` (~180 LOC) — Decodo residential proxy adapter. Auto-prefixes username with `user-` and suffixes with `-country-us`. URL-encodes password via `quote_plus`. 1-retry on challenge (rotating IP = fresh IP on retry). Per-request `wire_bytes` logging for cost observability. Fails fast with `ADAPTER_NOT_CONFIGURED` if creds are missing.
- **Router** — `backend/modules/m2_prices/container_client.py::_extract_one` — one `if retailer_id == "walmart"` scope that routes to the adapter selected by `WALMART_ADAPTER` env var. All 10 other retailers flow through the unmodified `self.extract()` call. Imports are deferred so unused adapters don't pay startup cost.
- **Config** — `backend/app/config.py` — added `WALMART_ADAPTER: str = "container"` (code default), `FIRECRAWL_API_KEY`, `DECODO_PROXY_USER`, `DECODO_PROXY_PASS`, `DECODO_PROXY_HOST`.
- **No database or migration changes** — the adapter output is a `ContainerResponse` which already maps cleanly into the existing `Price` and `PriceHistory` tables via `PriceAggregationService`. Pipeline, cache, upsert, and history logic all unchanged.
- **No router or endpoint changes** — the existing `GET /api/v1/prices/{product_id}` endpoint transparently routes walmart through the new adapter because the switch is internal to `ContainerClient`. API contract unchanged.

**Frontend:**
- **Nothing changed.** iOS app contract with the backend is untouched. `GET /api/v1/prices/{product_id}` returns the same shape, walmart just arrives via a different backend code path. 21 iOS tests unchanged, unrun in this session.

**Infrastructure:**
- **`.env.example`** — added `WALMART_ADAPTER`, `FIRECRAWL_API_KEY`, `DECODO_PROXY_*` with inline comments.
- **`.gitattributes`** — new file, forces LF on `*.sh`, `*.py`, `*.js`, `*.json`, `*.yml`, `Dockerfile`, `*.swift`. Keeps `*.bat`/`*.cmd`/`*.ps1` as CRLF. Prevents recurrence of the `bash\r` shebang issue that broke walmart container builds.
- **No Docker changes** — all Docker test infrastructure (barkain-db, barkain-db-test, barkain-redis) stayed unchanged. The walmart container (`containers/walmart/`) is preserved in the repo as a fallback for `WALMART_ADAPTER=container` mode even though it's known broken.

**Tests:**
- **24 new tests, all passing.**
  - `test_walmart_http_adapter.py` (15 tests): proxy URL builder (prefix/suffix/encoding/missing-creds, 4 tests), happy path (2), challenge retry semantics (2), HTTP error / parse error / timeout / missing creds (4), parser edge cases (5: sponsored filter, OOS, absolute URL, missing data raise, challenge detector)
  - `test_walmart_firecrawl_adapter.py` (9 tests): happy path (1), request shape with Bearer auth + country in body (1), 7 error surfaces (no API key, HTTP 429, `success=false`, challenge in response, empty body)
  - Updated 2 existing fixtures in `test_container_client.py` and `test_container_retailers.py` to set `walmart_adapter_mode = "container"` so legacy tests continue exercising the legacy path
- **2 new HTML fixtures** in `backend/tests/fixtures/`:
  - `walmart_next_data_sample.html` — realistic `__NEXT_DATA__` shape with 4 real products + 1 sponsored placement (for the filter test)
  - `walmart_challenge_sample.html` — minimal "Robot or human?" PerimeterX challenge page

---

## Key Decisions Made

| Decision | Rationale | Alternative Considered |
|----------|-----------|----------------------|
| Route walmart through an adapter, not rewrite the container | Single retailer has a known fingerprinting problem; surgical fix with zero impact on the other 10 retailers is safer than a broader migration | Migrate all 11 retailers to HTTP adapters (deferred — see Appendix B.7). Or write a fingerprint-hardened walmart container (deep rabbit hole with no guaranteed fix) |
| Use Firecrawl for demo + Decodo for production, not one or the other | Firecrawl = zero setup friction, generous free credits, proven 10/10 working in probe. Decodo = 2.7× cheaper per scrape, no concurrency cap, better at scale but requires proxy account. Each tool for its phase | Commit to Firecrawl only (simpler but 2.7× more expensive at scale), or Decodo only (blocks demo on proxy account setup) |
| Feature-flag via `WALMART_ADAPTER` env var, not hard-coded switch | Zero-risk deployment flip, instant rollback, both paths tested in CI independently. Matches existing `ENVIRONMENT` / `LOG_LEVEL` config patterns | Hard-code one path (no rollback), use Python runtime config (more complex), route at the nginx layer (out of scope) |
| Code default = `container`, demo `.env.example` default = `firecrawl` | Zero behavior change for devs without env file. Devs following `.env.example` get the working demo path. Opt-in over opt-out | Default to `firecrawl` everywhere (breaks tests that don't set env), default to `decodo_http` (requires creds to run at all) |
| Shared parser in `_walmart_parser.py`, not duplicated per adapter | Both adapters hit the same URL and get the same HTML; parsing logic should only exist once. `_` prefix signals "private to this package" | Duplicate the parser in each adapter (DRY violation), put the parser in a top-level `backend/shared/` directory (over-abstraction for one retailer) |
| Username auto-prefix in the adapter, not in config | User pastes the bare dashboard username and it Just Works. Removes a class of "I forgot to add user-..." config errors | Require fully-qualified username in the env var (more brittle), document the prefix in a comment only (easy to miss) |
| curl_cffi was tried and rejected | Probe showed curl_cffi with Chrome TLS impersonation actually FAILED where vanilla curl + Chrome headers succeeded on AWS IPs. IP reputation dominated over TLS fingerprint for walmart/PX. More Chrome-like ≠ better for this target | Use curl_cffi unconditionally (counter-productive here), or investigate further to determine which specific impersonation signal triggered the block (low ROI — vanilla httpx already works) |
| Decodo country-targeting is mandatory, not optional | Base pool landed in Peru on first sanity check. Without `country-us` the adapter is non-deterministic and will fail periodically on non-US residential IPs | Leave targeting to operator config (brittle), or offer a "random country" mode (out of scope for walmart specifically) |
| 1 retry on challenge, no retry on empty results | Rotating IPs means the retry lands on a fresh IP, which is the point of the residential pool. Empty results on a clean 200 are a legitimate niche-query signal, not a bot block — don't waste bandwidth retrying them | Retry aggressively on everything (wastes bandwidth), retry only on HTTP 5xx (misses challenges), no retry (single-IP failures become hard errors) |
| Test the full stack with respx mocks, not a real proxy | Deterministic, fast, CI-friendly. Proxy credentials are secrets that don't belong in CI anyway | Real proxy in an env-gated live test (future enhancement — `BARKAIN_RUN_LIVE_PROXY_TESTS=1` convention) |
| Don't migrate the other 10 retailers now | Scope discipline. Walmart is the only known-broken container on the user's residential IP. The other 10 work today. Extending the adapter pattern is deferred to a future "paradigm shift round 2" | Migrate all 11 now (unnecessary work, delays walmart fix), migrate lazily as each container breaks (leaves the code split) |

---

## Files Created

| File | Purpose |
|------|---------|
| `.gitattributes` | Force LF line endings on all Linux-executed files; prevents `bash\r` shebang breakage on Windows clones |
| `backend/modules/m2_prices/adapters/__init__.py` | Subpackage marker with architectural pointer to appendices |
| `backend/modules/m2_prices/adapters/_walmart_parser.py` | Shared `__NEXT_DATA__` → `ContainerResponse` logic for both walmart adapters |
| `backend/modules/m2_prices/adapters/walmart_firecrawl.py` | Firecrawl managed API adapter — demo default for walmart |
| `backend/modules/m2_prices/adapters/walmart_http.py` | Decodo residential proxy adapter — production path for walmart |
| `backend/tests/fixtures/walmart_next_data_sample.html` | Realistic `__NEXT_DATA__` fixture with 4 products + 1 sponsored placement |
| `backend/tests/fixtures/walmart_challenge_sample.html` | Minimal "Robot or human?" challenge page fixture |
| `backend/tests/modules/test_walmart_http_adapter.py` | 15 tests for the Decodo adapter + parser edge cases |
| `backend/tests/modules/test_walmart_firecrawl_adapter.py` | 9 tests for the Firecrawl adapter |
| `Error_Report_Walmart_Adapter_Paradigm_Shift.md` | This paradigm shift's structured error report (per `05-ERROR-REPORT-TEMPLATE.md`) |
| `Conversation_Summary_Walmart_Adapter_Paradigm_Shift.md` | This file (per `06-CONVERSATION-SUMMARY-TEMPLATE (1).md`) |

## Files Modified

| File | Changes |
|------|---------|
| `CLAUDE.md` | Added 3 Key Decisions Log rows (Decodo verdict, walmart_http dormant pattern, Firecrawl+Decodo collapse plan). Added "Key Files Created/Modified (Walmart Adapter Routing, post-Step-2a)" section. Updated test count 104 → 128. Bumped footer v3.5 → v3.6. Updated "What's Next" to mention the dormant adapter. |
| `docs/SCRAPING_AGENT_ARCHITECTURE.md` | Appended Appendix A (AWS EC2 5-instance 10-retailer probe), Appendix B (Firecrawl 10-retailer probe), Appendix C (Decodo 5-scrape probe + implementation details). ~750 new lines total. |
| `docs/ARCHITECTURE.md` | Updated Walmart row in Batch 1 table to mark as superseded. Added "Walmart Adapter Routing (post-Step-2a paradigm shift)" subsection between container architecture and background workers. |
| `docs/DEPLOYMENT.md` | Added `WALMART_ADAPTER`, `FIRECRAWL_API_KEY`, `DECODO_PROXY_*` to the `.env.example` block with comments. Added paradigm-shift note explaining the scope ("walmart only"). |
| `docs/COMPONENT_MAP.md` | Split "All 11 Demo Retailers" row into "10 non-walmart" + "Walmart demo (Firecrawl)" + "Walmart production (Decodo)" rows. |
| `docs/PHASES.md` | Added "Walmart HTTP Adapter + Firecrawl/Decodo Routing — COMPLETE (2026-04-10)" milestone between Step 2a and tagged releases. |
| `docs/TESTING.md` | Added "Walmart adapter routing (post-2a)" row to per-step test count table. Updated Total 104 → 128. |
| `docs/FEATURES.md` | Split the price-comparison row into 10-non-walmart and walmart-adapter rows. Added dedicated walmart HTTP adapter feature row. |
| `docs/agent-browser-scraping-guide.md` | Added boxed "⚠️ WALMART EXCEPTION" callout at the top noting walmart is no longer agent-browser scraped; rest of guide still applies to the other 10. |
| `.env.example` | Added 3 new env var blocks (WALMART_ADAPTER, FIRECRAWL_API_KEY, DECODO_PROXY_*) with inline comments on when each is required and how to obtain. |
| `backend/app/config.py` | Added `WALMART_ADAPTER: str = "container"` (code default), `FIRECRAWL_API_KEY`, `DECODO_PROXY_USER`, `DECODO_PROXY_PASS`, `DECODO_PROXY_HOST`. |
| `backend/modules/m2_prices/container_client.py` | Added `_extract_one` router method, `_resolve_walmart_adapter` helper with deferred imports, `walmart_adapter_mode` + `_cfg` attrs in `__init__`. `extract_all` now calls `_extract_one` instead of `extract` directly for routing. |
| `backend/tests/modules/test_container_client.py` | Updated `_setup_client` autouse fixture to set `walmart_adapter_mode = "container"` and `_cfg = None` so legacy tests exercise the legacy path. |
| `backend/tests/modules/test_container_retailers.py` | Same fixture update — this was the test file that surfaced the missing-attribute failure in the first full test run. |
| `containers/base/entrypoint.sh` | `sed -i 's/\r$//'` — stripped CRLF line endings. Needed to unblock the mid-session walmart container build diagnostic. |
| `containers/walmart/extract.sh` | Same CR-stripping. |

---

## Learnings

These should be promoted to pre-fixes or pre-flags in any future scraping-related prompt packages.

- **L1 — IP reputation dominates over TLS fingerprint for top-tier anti-bot vendors.** curl_cffi with Chrome TLS impersonation did *worse* than vanilla curl + Chrome headers on AWS IPs for walmart. Don't reach for impersonation libraries as a first move; measure the plain path first.
- **L2 — Server-rendered React/Next.js sites leak their full state into `<script id="__NEXT_DATA__">`.** You often don't need a browser at all. Check for this before spinning up Chromium. Walmart, Target, Sam's Club all use `__NEXT_DATA__`. Home Depot and Lowe's use `__APOLLO_STATE__` (discovered in Appendix B). Amazon, Best Buy, eBay, BackMarket have their data in direct HTML without a JSON blob but still work with plain HTTP + selectolax.
- **L3 — A single clean IP probe ≠ reliable IP pool.** First AWS single-instance walmart scrape passed. Stability probe 12 minutes later on 5 different IPs in the same region all failed. **Always run the stability probe before committing to an IP-based architecture.** The "lucky single IP" anti-pattern will mislead architecture decisions.
- **L4 — Geo-target residential proxy pools.** Decodo's default pool resolved to Peru on the first sanity check. `country-us` suffix is mandatory for US retail sites, not optional. Any adapter pointing at a residential pool should default to the appropriate country for the retailer, not trust the pool default.
- **L5 — Password URL-embedding is fragile.** `=`, `@`, `:` characters in credentials break standard `user:pass@host` URL parsing. Use `--proxy-user` / `--proxy-auth` flags or URL-encode via `quote_plus`. Document this in the adapter comments so operators don't fight it in config.
- **L6 — `__new__`-based test fixtures bypass the constructor contract.** Any new field added to `ContainerClient.__init__` must also be set in the two autouse fixtures. Alternative: refactor fixtures to use the real constructor with a test `Settings` object. Non-urgent but good hygiene.
- **L7 — Python f-strings with backslash-escaped quotes in expression parts are a Python 3.12+ feature.** AL2023 runs Python 3.9 — f-string backslash errors crash any user-data script that uses them. Prefer `%`-style formatting or a pre-stored string variable for cross-version Python compatibility, especially in shell heredocs that ship to EC2 instances.
- **L8 — EC2 auto-terminate races console output capture.** Quick-terminate instances don't flush `/dev/console` reliably. Either wait ~2 minutes before terminating, or ship results to S3, or use SSM Run Command. Budget an extra minute if you're using console output for diagnostics.
- **L9 — GitHub API tokens need `workflow` scope to touch `.github/workflows/*`.** `repo` scope alone returns 404. Check with `gh auth status | grep scope` before attempting workflow file modifications, and refresh with `gh auth refresh -s workflow` if missing.
- **L10 — AWS temporary session tokens can expire mid-session.** Budget a `sts get-caller-identity` check before every EC2 operation during long debugging sessions, and have the refresh flow documented so you can re-auth without losing context.
- **L11 — Challenge page detection by keyword is fragile.** The 10-retailer survey classifier missed eBay's "Pardon Our Interruption" phrase. Every new retailer adds a potential false-positive. Long-term: replace keyword matching with multi-criteria rules (`page_size < 20 KB AND no structured data markers`).
- **L12 — Docker Desktop on Windows has recurring WSL2 reliability issues.** Budget a Docker health check at session start when builds are in scope, and proactively restart Docker Desktop if operations feel slow. Don't sink time diagnosing builds until you've ruled out a wedged daemon.
- **L13 — `git core.autocrlf=true` + no `.gitattributes` silently breaks Linux shell scripts on Windows clones.** This is the third "surprise CRLF" incident I've seen in this codebase. The `.gitattributes` file added this session prevents it permanently. **Recommend: in any future shell script edit, verify LF line endings via `file <path>` before committing.**
- **L14 — Always test residential-proxy US targeting explicitly.** Don't assume the bare username gives you US IPs. Document the required `country-us` suffix in every adapter that uses a residential pool, and verify with a sanity check against `ip.decodo.com/json` (or equivalent) as the first step of every probe.

---

## Guiding Doc Updates

| Doc | Changes |
|---|---|
| `CLAUDE.md` | 3 new Decisions Log rows; new Key Files section; test count 104→128; footer v3.5→v3.6; What's Next clarifies dormant adapter |
| `docs/SCRAPING_AGENT_ARCHITECTURE.md` | Appendices A (AWS EC2 probe), B (Firecrawl probe), C (Decodo probe + implementation) — ~750 new lines |
| `docs/ARCHITECTURE.md` | Walmart row superseded in Batch 1 table; new "Walmart Adapter Routing" subsection with architecture diagram, file layout, cost table, demo→prod flip mechanics |
| `docs/DEPLOYMENT.md` | New env vars in `.env.example` block + paradigm-shift explanatory note |
| `docs/COMPONENT_MAP.md` | Split 11-retailers row into 10-non-walmart + walmart-demo + walmart-prod rows |
| `docs/PHASES.md` | New "Walmart HTTP Adapter + Firecrawl/Decodo Routing" milestone entry |
| `docs/TESTING.md` | New per-step row with 24 new tests breakdown; total count updated |
| `docs/FEATURES.md` | Split price-comparison row; new dedicated walmart-adapter feature row |
| `docs/agent-browser-scraping-guide.md` | "⚠️ WALMART EXCEPTION" callout at the top, rest of guide preserved for the other 10 retailers |

---

## Open Items

- [ ] **Run `git add --renormalize .`** to fix CRLF line endings in the 9 other `containers/*/extract.sh` files (WMRT-L1). Not urgent because those containers haven't been rebuilt. Should be done before the next container rebuild cycle.
- [ ] **Add `.tmp/` to `.gitignore`** (WMRT-L9). ~17 MB of probe artifacts live there, referenced in appendix footnotes. Prevents accidental `git add .` from dragging them in.
- [ ] **Create a dedicated Firecrawl account for Barkain** before beta launch (WMRT-L2). Currently running on Mike's personal credits (101K). Move the API key when the migration is ready.
- [ ] **Wire `walmart_http_wire_bytes_total` to Prometheus/OTel** (WMRT-L4). Per-request logging exists but isn't exported. Phase 2 observability enhancement.
- [ ] **Add a Walmart canary test** — scrape a known UPC daily, assert `len(listings) >= 1` (WMRT-L5). Catches `__NEXT_DATA__` schema drift before it takes down production.
- [ ] **Add `FIRECRAWL_API_URL` env var** for endpoint override (WMRT-L6). Low priority, trivial when needed.
- [ ] **Load-test 50+ Decodo scrapes in 60s** (WMRT-L7) before broad beta to measure rate-limit behavior and effective retry cost under concurrency.
- [ ] **Add `WALMART_ADAPTER=decodo_http_with_firecrawl_fallback` mode** (WMRT-L3). On terminal Decodo failure, fall back to Firecrawl for the rest of that request. Reliability enhancement for production.
- [ ] **Move `05-ERROR-REPORT-TEMPLATE.md` and `06-CONVERSATION-SUMMARY-TEMPLATE (1).md` out of the project root** into something like `prompts/templates/`. The root directory is getting cluttered. Optional cleanup.
- [ ] **Rerun the 10-retailer AWS EC2 probe with URL-format corrections** for home_depot and lowes (Appendix A). Inconclusive in the original probe — Firecrawl later confirmed they have `__APOLLO_STATE__` server-rendered data, suggesting direct HTTP might work with a different URL template. Could enable 2 more HTTP adapters.
- [ ] **Phase 2 Step 2b (M5 Identity Profile)** — the original next step per CLAUDE.md. Unblocked by this paradigm shift; no dependency changes.
