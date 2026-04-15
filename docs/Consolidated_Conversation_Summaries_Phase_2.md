# Consolidated Conversation Summaries — Phase 2

> Date range: 2026-04-10 → 2026-04-15
> Source: `docs/CHANGELOG.md`. Per-step session summaries live in `Barkain Prompts/`.
> Purpose: a single timeline view of Phase 2 + methodology observations to feed Phase 3 planning.

---

## Timeline

| Step | Date | Tests added | Key deliverable | PR |
|---|---|---|---|---|
| 2a | 04-10 | +20 backend | Watchdog supervisor, health monitoring, shared base image | #3 |
| Walmart adapter routing | 04-10 | +24 backend | `WALMART_ADAPTER` env routing (container / firecrawl / decodo_http) | — |
| Scan-to-prices live demo | 04-10 | — | First end-to-end EC2 deploy: 11 retailers wired, fd-3 stdout pattern, 3 retailers validated live | — |
| 2b | 04-11 | +24 backend | UPCitemdb cross-validation + relevance scoring + integration markers | #5 |
| 2b-val | 04-12 | — | Live validation pass — 3 latent regressions caught and fixed inline | — |
| 2b-final | 04-13 | +35 backend | Gemini `model` field, GitHub Actions CI workflow, 35 hardening tests | #7 |
| 2c | 04-13 | +11 backend, +11 iOS | SSE streaming endpoint, `asyncio.as_completed` pattern, manual byte-level iOS parser | #8 |
| 2c-val | 04-13 | — | Live SSE smoke test — exposed L6 (consumer never streamed) and L7 (IPv6 happy-eyeballs) | — |
| 2c-fix | 04-13 | +4 iOS | Manual byte splitter, `127.0.0.1`, permanent `os_log` instrumentation under `com.barkain.app/SSE` | #10 |
| 2d | 04-14 | +30 backend, +7 iOS | M5 Identity Profile, 52-program discount catalog, migration 0003 | #11 |
| 2e | 04-14 | +30 backend, +10 iOS | M5 Card Portfolio, 30-card catalog, rotating categories, reward matching | #12 |
| 2e-val | 04-14 | — | 6-phase live smoke test — 0 bugs, 5 UX observations | #13 |
| 2f | 04-14 | +14 backend, +10 iOS | M11 Billing — RevenueCat SDK, feature gating, migration 0004 | #14 |
| 2g | 04-14 | +14 backend, +6 iOS | M12 Affiliate Router (Amazon/eBay/Walmart) + `SFSafariViewController` in-app browser | #15 |
| 2h | 04-14 | +21 backend | Background workers — SQS + price ingestion + portal rates + discount verification, migration 0005 | #16 |
| 2i-a | 04-15 | — | CLAUDE.md compaction to v5.0 + guiding-doc sweep | #17 |
| 2i-b | 04-15 | +1 backend | Code quality: `DEMO_MODE` rename, dead branches, `_classify_retailer_result` extraction, migration 0006 | #18 |
| 2i-c | 04-15 | — | Operational validation (LocalStack workers end-to-end), conftest drift detection, CI ruff step, Phase 2 consolidation, tag prep | (this PR) |

**Phase 2 totals:** 14 working steps, 0 hot-fixes after merge, **+121 backend tests** (181 → 302) and **+45 iOS tests** (21 → 66). All HIGH-severity issues found during the phase were resolved within the phase.

---

## Architecture Evolution

Phase 1 left Barkain with a barcode-scan-to-price-comparison foundation: 11 retailer scrapers behind a FastAPI dispatcher, Gemini UPC resolution, a SwiftUI scanner, and a single `GET /prices/{id}` endpoint that fanned out and waited for the slowest retailer. Phase 2 wrapped that core in **five overlapping intelligence layers**, each one zero-LLM at query time:

1. **Streaming UX (2c, 2c-fix)** — `asyncio.as_completed` + SSE so users see Walmart in 0.8s instead of waiting 91s for Best Buy.
2. **Identity discounts (2d)** — pure SQL join against a 52-program catalog; sub-150ms.
3. **Card rewards (2e)** — pure SQL join against a 30-card catalog with rotating-category resolution; in-memory `max()` per retailer.
4. **Billing + tier (2f)** — RevenueCat SDK on iOS for instant gating, backend `users.subscription_tier` as the rate-limit authority, RC webhook with idempotent SETNX dedup converging the two within 60s.
5. **Affiliate routing (2g)** — backend-only URL construction, `SFSafariViewController` for cookie persistence, fail-open resolver.

**Step 2h** added the operational backbone: four background workers (price ingestion, portal rates, discount verification, watchdog) backed by SQS, hermetic `moto[sqs]` for tests, LocalStack for dev. **Steps 2i-a/b/c** are the hardening sweep — doc compaction, code quality, and operational validation — that closes the phase.

The architecture stays a **modular monolith** throughout. Modules import each other directly; LLM calls always go through `backend/ai/abstraction.py`; per-retailer scrapers live in independent Docker containers. Phase 3's recommendation synthesis layer (Claude Sonnet) is the first piece designed to sit AT the seam these layers leave open.

---

## Methodology Observations

**What worked:**

- **Plan-mode parallel Explore agents.** The single highest-leverage tool of Phase 2 was launching 2-3 Explore agents in parallel during plan mode to verify the prompt against disk reality. Step 2i-b caught ~30% prompt staleness this way before any code was written; Step 2i-c added an explicit `## State Verification` section as a permanent part of every cleanup-step prompt. Recommendation: keep.
- **Two-tier loop (Planner Opus → Executor Code).** Tight, repeatable, and the prompt-package format (header → context → groups → out-of-scope → DoD) survived 14 steps without significant revision.
- **Per-step error reports + conversation summaries.** Two short documents per step (`Error_Report_*.md` + `Conversation_Summary_*.md` in `Barkain Prompts/`) were small enough to be cheap and dense enough to feed the Planner's next prompt. The format converged after ~3 steps and stayed stable.
- **Behavior-preserving extractions are safe.** Step 2i-b extracted ~80 duplicated lines from `m2_prices/service.py` into `_classify_retailer_result` with zero new tests required and zero behavior change. Pre/post diff against the 11 stream + 23 m2 + 12 integration tests was the only verification needed.
- **Migration parity convention.** Every constraint added via Alembic must also be mirrored in the model's `__table_args__` so `Base.metadata.create_all` (test DB) matches `alembic upgrade head` (dev/prod). Steps 2f, 2h, 2i-b all relied on this; step 2i-c's drift detection in conftest.py finally automated the catch.

**What to change for Phase 3:**

- **Mock-only tests are not enough.** 2c-val-L6 (the iOS SSE consumer never streamed in production) and 2i-c's `app/models` import bug (workers passed for 14 days under `moto`) were both hidden by mock-only tests. Add at least one **real-pipeline smoke test** to every step's DoD: real `URLSession.bytes` for iOS, real LocalStack for workers, real Postgres for migrations.
- **State Verification before planning.** 2i-b's prompt staleness was ~30%; 2i-c's State Verification section caught the same shape pre-emptively. Make this a permanent prompt-template section.
- **CI must include `ruff check`.** Caught in 2i-c Group B — workflow ran pytest only. Added a `Lint` step.
- **Branch protection should require status checks.** GitHub branch protection on `main` exists but does NOT require the `Backend Tests / test` workflow to pass before merge. Mike task tracked as 2i-c-L3.
- **Disable Vercel plugin auto-injection.** Permanent FastAPI false positives across 2g, 2h, 2i-b. `~/.claude/settings.json` task for Mike (2i-b-L3).
- **Track the "drift marker" pattern in test bootstraps.** When a step adds a column or constraint, update the `chk_subscription_tier` marker in `conftest.py:_ensure_schema` to point at the new artifact. The drift detection only catches what it's looking for.

---

## Phase 3 Hand-off Notes

The natural next layer is **AI synthesis via Claude Sonnet** — taking the (price + identity + card + portal + coupon) tuple from the existing modules and producing a single recommendation paragraph. The contract for that layer is already mostly fixed: every input it needs is already a SQL-resolvable Phase 2 artifact. The work is the prompt + the streaming integration into the existing SSE channel.

The four operational risks Phase 3 inherits from Phase 2:

1. EC2 containers are running hot-patched code (2b-val-L1) — redeploy from `main` post-tag.
2. Best Buy ~91s tail dominates total runtime (2b-val-L2 / 2c-val-L1) — `domcontentloaded` wait or alternative selector strategy.
3. SQS queues lack DLQ wiring (2h-ops) — operational add for production.
4. Rakuten `normal_value` baseline drifts permanently upward (2h key decision #9) — TimescaleDB continuous aggregate over 30-day windows.

None of these block `v0.2.0`. All are documented in `CLAUDE.md` Known Issues.
