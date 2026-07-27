# Loose Ends

> **Audited:** 2026-07-27, against `main` @ `28002c9`.
> **Scope:** things that are wired but not working, or not wired at all. Distinct
> from `CLAUDE.md`'s Known Issues table, which tracks *code defects*. Most of
> what's below is not a bug — it's a credential nobody has obtained, a flag
> nobody has flipped, or catalog data that has aged out.
>
> Every claim here cites a file so it can be re-checked rather than believed.
> When you close one, delete the entry — a stale loose-ends doc is worse than no
> loose-ends doc.

---

## P0 — Live, user-facing, silently wrong

### Rotating card categories expired 2026-06-30

`scripts/seed_rotating_categories.py:39-64` seeds exactly two rows, both
`quarter="2026-Q2"` (lines 43, 55) with `effective_until=date(2026, 6, 30)`
(lines 50, 62):

| Card | Categories | Rate |
|---|---|---|
| Chase Freedom Flex | amazon, chase_travel, feeding_america | 5.0 |
| Discover it Cash Back | restaurants, home_depot, lowes, home_improvement | 5.0 |

`CardService._recommendations` (`backend/modules/m5_identity/card_service.py:331-339`)
filters on `effective_from <= date.today() <= effective_until`. Since
2026-07-01 neither row matches, so **every rotating 5x bonus in the app has
been silently returning the card's base rate for four weeks.** No error, no
log line — the query just returns nothing and a lesser card wins the
recommendation.

This is the single highest-value item on this page: it's live reward math
giving users wrong answers, on the feature the product is named for.

**What unblocks it:** the Q3 2026 category lists from Chase and Discover.
That's catalog data from the issuers, not something a helper can derive — which
is why the fix wasn't attempted when the expiry was found.

**How it was found:** it broke `test_recommendations_rotating_bonus_wins` and
`test_recommendations_user_selected_wins`, which had been red since 2026-07-01
and went unnoticed because no backend-touching PR ran CI between 2026-05-01 and
2026-07-27. Those fixtures are now time-invariant (PR #98) — the *tests* are
fixed, the *seed data* is not.

### `.env.example` is missing 26 of 63 settings

`backend/app/config.py` declares 63 settings; `.env.example` documents 37. The
consequential omissions:

| Missing key | Consequence of not knowing about it |
|---|---|
| `DECODO_SCRAPER_API_AUTH` | **Amazon pricing silently absent.** This is the Decodo Scraper API adapter — a new environment built from `.env.example` loses Amazon entirely with no error |
| `MISC_RETAILER_ADAPTER` | M14 misc-retailer slot invisible |
| `PROVISIONAL_RESOLVE_ENABLED` | Provisional-resolve path undiscoverable |
| `SEARCH_THUMBNAIL_FALLBACK` | Thumbnail cascade undiscoverable |
| `WALMART_AFFILIATE_ID` | Affiliate attribution silently off |
| `WATCHDOG_SLACK_WEBHOOK` | Watchdog alerts silently discarded |
| `DEMO_MODE` | Auth-bypass switch undocumented |

The remaining 19 are infra tunables with sane defaults (`RATE_LIMIT_*`,
`CONTAINER_*`, `LOG_LEVEL`, …) — worth adding for completeness, but they don't
break anything by being absent.

**What unblocks it:** an hour appending the keys with comments. No external
dependency.

---

## P1 — Built, verified, never switched on

Each of these shipped behind a flag, was live-verified, and then left off.

| Flag | Default | State |
|---|---|---|
| `PROVISIONAL_RESOLVE_ENABLED` | `False` | Dark-launched. Live-verified on Festool 577419 → provisional row → real $700 FB Marketplace listing. Never flipped |
| `MISC_RETAILER_ADAPTER` | `'disabled'` | M14 slot built + iOS card shipped (#80, #81). The canary plan — $50 Starter Serper → bench → 5% → 50% → 100% — never started |
| `PORTAL_MONETIZATION_ENABLED` | `False` | Whole M13 portal CTA tree dark. Also needs `RAKUTEN_REFERRAL_URL`, `BEFRUGAL_REFERRAL_URL`, `TOPCASHBACK_FLEXOFFERS_PUB_ID`, `TOPCASHBACK_FLEXOFFERS_LINK_TEMPLATE` |
| `SEARCH_TIER2_USE_EBAY` | `False` | Plus `SEARCH_TIER2_EBAY_USE_GTIN`, `SEARCH_TIER2_EBAY_SKIP_UPC`, `M2_EBAY_DROP_PARTIAL_LISTINGS`. The eBay-Tier-2 graduation decision was never made |

A flag that is never flipped is indistinguishable from code that was never
written, except that it costs review and carries risk. Each of these deserves
either a rollout or a deletion.

---

## P2 — Credentials never obtained

| Key | Blocks | Blocked on |
|---|---|---|
| `UPCITEMDB_API_KEY` | **Unset — running the unauthenticated free tier.** This is why UPCitemdb rate-limited mid-diagnosis during the Apple Watch Ultra 2 investigation, forcing the provisional path | Paid plan |
| `WALMART_AFFILIATE_ID` | Walmart clicks earn nothing | Impact Radius approval |
| `AFFILIATE_WEBHOOK_SECRET` | `/conversion` is a placeholder — no conversion attribution on any channel | Own decision |
| `REVENUECAT_WEBHOOK_SECRET` | Subscription webhook unverified outside prod | RC dashboard |
| `WATCHDOG_SLACK_WEBHOOK` | Watchdog runs and reports into the void | Slack app |
| `WALMART_IO_CONSUMER_ID` / `WALMART_IO_PRIVATE_KEY` | M15 sourcing Walmart leg | developer.walmart.com approval |
| `EBAY_MARKETPLACE_INSIGHTS_ENABLED` | M15 exact sold-counts | eBay approval — **effectively closed**; Terapeak/Product Research is the real path (see `sourcing/README.md` §5.2) |

---

## P3 — Degraded but functional

**Walmart / Firecrawl.** `WALMART_ADAPTER=decodo_http` carries production and
works (~3.3s). The `firecrawl` option is 100% CHALLENGE'd and kept only as a
selectable value — so the documented fallback is not actually a fallback. Either
fix it or drop the option so the config doesn't imply resilience it lacks.

**`sourcing/` lints against ruff defaults, not the repo's config.**
`backend/pyproject.toml` only governs `backend/`, so `sourcing/` gets
line-length 88 instead of the repo's 99, and a different rule set. Harmless
under the current pin; a `sourcing/pyproject.toml` would hold the tree to one
standard.

**Ruff is pinned to 0.15.9** (`.github/workflows/backend-tests.yml`). 0.16.0
widened the default rule set to 642 findings repo-wide — 313 in `backend/`, 94
in `scripts/`. Bumping the pin is a standalone PR with the resulting fixes, not
collateral on whatever unrelated PR runs first after a release.

---

## P4 — M15 sourcing (merged dark, PR #97)

The module is deliberately inert: nothing imports it, no router is registered,
and migration `0013` is staged under `sourcing/migrations/` rather than
`infrastructure/migrations/versions/`. That's the safety property, not an
oversight. What's genuinely outstanding:

- **No `router.py` / `schemas.py`.** The API surface in `sourcing/README.md` §8
  is a design, not shipped code.
- **Migration 0013 unapplied.** `down_revision = "0012"` is correct; it just
  isn't in Alembic's path, so the six tables don't exist anywhere.
- **Both channel adapters unrun against live credentials.** `walmart_io.py` and
  `ebay_sourcing.py` are written against documented request shapes only.
- **`workers/sourcing_snapshots.py` doesn't exist.** The snapshot cron that
  feeds the demand engine — and that §6 calls "the moat" — is unwritten. Worth
  noting that the snapshot table is the one thing you cannot backfill later.
- **Adapter default mismatch:** `sourcing/README.md:420` documents
  `WALMART_SOURCING_ADAPTER="walmart_io"`; `config.py:52` defaults to
  `"walmart_http"`.
- **Affiliate-terms concern unaddressed.** §9 notes a 3,000-row crunch driving
  zero clicks isn't what the Walmart affiliate program is for. The `walmart_http`
  default sidesteps the API but not the underlying question.

Covered by 291 tests as of PR #98 — pure modules only (`upc`, `ingest`, `fees`,
`landed_cost`, `plans`, `demand`, `scoring`, `forecast`, `inquiry`). `service.py`,
`recon.py`, `models.py` and both adapters have **no** test coverage.

---

## P5 — Carried forward

- **`2i-d-L4`** (MEDIUM, the only entry in CLAUDE.md's Known Issues table) —
  watchdog heal at `workers/watchdog.py:251` passes `page_html=error_details`;
  needs a real browser fetch in the heal path.
- **Physical-iPhone p50** ~3s, target ~1.5s.
- **iOS snapshot baselines** need re-recording — `StackingReceiptViewSnapshotTests`,
  `UnresolvedProductViewSnapshotTests`, `ConfirmationPromptViewSnapshotTests`,
  `ProfileViewSnapshotTests` and 2 `AutocompleteServiceTests` cases flake on
  `main`, independent of any PR. See the iOS 26.4 environmental hang note in
  `SnapshotTestHelper.swift`.
- **AppIcon PNGs** absent.
- **Production FB Marketplace seed** not run.
- **Weekly bench cron** never scheduled.

---

## Process note

Two of the items above — the rotating-category expiry and the ruff drift — were
invisible for weeks because CI wasn't running on the paths that would have
caught them. The backend suite went **2026-05-01 → 2026-07-27** without
executing. `backend-tests.yml` is now path-filtered to include `sourcing/**`
and pins its linter, and the two workflows self-check that exactly one `test`
status reports.

The general lesson is worth keeping: **a green check is only evidence if you
know which job produced it.** PR #97 merged 9,851 lines on a 3-second green
that came from a no-op job.
