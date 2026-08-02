# Loose Ends

> **Audited:** 2026-07-27, against `main` @ `28002c9`.
> **Revised:** 2026-07-30 — `.env.example` drift, the `sourcing/` ruff split,
> and `2i-d-L4` are closed and their entries deleted. The rotating-category
> entry is rewritten: Q3 is seeded, and the impact analysis turned out to be
> materially different from what the first audit assumed.
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

### Rotating card categories — Q3 seeded, Q4 is the real deadline

**Status 2026-07-30:** Q3 2026 is now seeded for both cards and the dev DB is
current (2 rows effective today, previously 0). What remains is Q4.

The original finding stands mechanically: `CardService._recommendations`
filters on `effective_from <= date.today() <= effective_until`, seed data
stopped at `2026-Q2`, and from 2026-07-01 the query matched nothing. But the
**impact assessment was wrong**, and the correction matters for prioritisation.

Q3 2026's actual categories are:

| Card | Q3 2026 categories |
|---|---|
| Chase Freedom Flex | gas stations, EV charging, public transit, select live entertainment, United Way |
| Discover it Cash Back | gas stations, EV charging, public transportation, flights, drugstores |

None of those intersect `_RETAILER_CATEGORY_TAGS`
(`card_service.py:37-75`), whose vocabulary is entirely shopping-oriented —
amazon, best_buy, walmart, target, home_depot, lowes, ebay, sams_club,
online_shopping, electronics_stores, department_stores, wholesale_clubs,
home_improvement, apple, electronics. Barkain does not compare prices on gas,
transit, or flights.

So for Q3 specifically, **a correctly-seeded table and an empty one produce
the same recommendation**: both cards fall to their base rate at every
retailer we shop. The four weeks of "silently wrong" reward math were, by
coincidence, silently right. Q2 *was* genuinely wrong while it was live
(`amazon` and `home_depot` are both categories and Barkain retailers), and
Q4 will be wrong again.

**Q4 2026 is the deadline that costs money.** Secondary sources report
Discover's Q4 categories as **Amazon and Target** — both first-class Barkain
retailers. From 2026-10-01, an unseeded Q4 means every Discover holder
shopping Amazon or Target is told to use a worse card, on the product's
headline feature. A commented-out Q4 block is staged in
`seed_rotating_categories.py` with that reasoning inline.

**What unblocks it:** the Q4 lists confirmed against the issuers' own pages —
not aggregators. Discover publishes officially ~September; Chase announces Q4
separately, also ~September. Uncomment, fill in Chase, reseed.

**Now detectable rather than silent.** Two tripwires were added, because the
root cause was never the stale data — it was that stale data made no sound:

- `scripts/check_catalog_freshness.py` — reads the seed file (not the DB, so
  it needs no Postgres and runs in CI), exits non-zero once the newest quarter
  is inside its final 14 days. Verified against the historical failure: at a
  simulated 2026-07-15 with only Q2 seeded it reports both cards EXPIRED.
- `card_service.py` now partitions rotating rows in Python instead of
  filtering them in SQL — same single round trip — so it can distinguish "no
  rotating categories" from "all rotating categories lapsed" and log
  `rotating_categories_all_expired` for the latter.

Deliberately **not** a pytest case: PR #98 made these fixtures time-invariant
precisely so a date rollover stops turning unrelated PRs red. A check that
fails on its own schedule belongs in cron, not in the blocking suite.

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

**Ruff is pinned to 0.15.9** (`.github/workflows/backend-tests.yml`). Re-measured
2026-07-30 against `ruff 0.16.0` over `backend/ scripts/ sourcing/`: **642
findings, 495 auto-fixable with `--fix`**, 26 more behind `--unsafe-fixes`,
leaving ~121 for manual review. Concentrated in a few rules, so the diff is
mechanical rather than sprawling:

| Count | Rule | Auto? |
|---|---|:-:|
| 163 | `UP045` non-pep604-annotation-optional (`Optional[X]` → `X \| None`) | ✅ |
| 141 | `FURB157` verbose-decimal-constructor | ✅ |
| 78 | `I001` unsorted-imports | ✅ |
| 78 | `RUF100` unused-noqa | ✅ |
| 71 | `B008` function-call-in-default-argument | ❌ FastAPI `Depends()` — expect to suppress |
| 22 | `BLE001` blind-except | ❌ needs per-site judgement |
| 13 | `EXE001` shebang-not-executable | ❌ chmod or drop shebang |

Two notes for whoever takes it. `B008` at 71 is almost entirely FastAPI's
`Depends()`/`Query()` idiom and should be suppressed wholesale rather than
"fixed". And `DTZ011 call-date-today` (4 hits) is worth reading rather than
autofixing — `date.today()` is exactly the call at the centre of the
rotating-category expiry above.

Still a standalone PR, not collateral on whatever unrelated branch runs first
after a release.

**The two `test` workflows are not mutually exclusive** (found 2026-08-01, on
PR #100). `backend-tests-docs-skip.yml` carries a comment asserting that
mirroring its `paths-ignore` against `backend-tests.yml`'s `paths` keeps
"exactly one `test` check reporting". It does not, because of how GitHub
evaluates the two filters:

- `paths-ignore` skips a workflow only when **every** changed file matches.
  One non-backend file — a doc, a script, anything under `Barkain/` — is
  enough to make the no-op run.
- `paths` runs a workflow when **any** changed file matches.

So a PR touching backend code *and* anything else fires both, and both emit a
check context named `test`. That is most PRs. Verified on `6ac8f41`: the no-op
reported success in ~3 seconds while the real suite was still running, and
`gh run list` shows both genuinely executed on the same SHA. The sweep commit
`1283fd4` did it too.

Nothing has actually merged unverified since #97 — the real suite ran and
passed on both of those commits. But the guard is not doing what it claims,
and the failure it was written to prevent is the one that let #97 through on a
3-second green. Mirroring the path lists more carefully cannot fix this; the
premise that PRs touch one directory is what is wrong.

Three shapes, differing mainly in what they cost:

1. Give the no-op a distinct job name and require **both** contexts in branch
   protection. Cleanest, but needs a repo-settings change, not just a commit.
2. Have the no-op check out the diff and exit early if any backend path is
   present. Keeps one context, no settings change, but the no-op now has logic
   that can itself be wrong.
3. Collapse to one workflow that decides internally whether to run pytest.
   Most robust, largest rewrite, and the required context stops depending on
   which workflow won a race.

Worth doing before the next large merge. **The general shape is that a check's
trustworthiness is a property of its trigger, not its script** — this one and
the freshness checker below both passed review with correct-looking bodies and
wrong assumptions about when they run.

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

- **Local Postgres shadows the Docker one** (found 2026-07-30). A host-installed
  Postgres holds `127.0.0.1:5432` and `[::1]:5432`; the `barkain-db` container
  binds `*:5432`. The loopback-specific bind wins, so anything resolving
  `localhost:5432` — every seed script, via `scripts/_db_url.py`'s
  `DEFAULT_DEV_DB_URL` — talks to the host Postgres and fails with
  `role "app" does not exist`. The backend suite is unaffected because it uses
  port **5433** (`barkain-db-test`), which is why this stayed invisible.
  Workaround used to reseed: `DATABASE_URL=postgresql+asyncpg://app:localdev@$(ipconfig getifaddr en0):5432/barkain`.
  Real fixes: stop the host Postgres, or move the container to a free port and
  update `DEFAULT_DEV_DB_URL`. Worth doing — the failure mode is a seed script
  that appears to run against the app DB and does not.
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

The converse showed up immediately, on the very PR that added the tripwires.
`catalog-freshness` went red on PR #100 — not because the catalog was stale
(Q3 has until 2026-09-30) but because `check_catalog_freshness.py` imports
`seed_rotating_categories.py`, which imported SQLAlchemy at module level, in a
job that deliberately runs no `pip install`. A red check nobody can act on
mutes a tripwire just as thoroughly as a green one nobody can trace, and it
does it faster. Fixed by deferring the SQLAlchemy imports into the seeding
functions and pinning both scripts' module-level import surface to the standard
library with `ast`, the way `check_env_example.py` already reads `config.py`.
**A checker that parses its source has no dependency surface to break; one that
imports its source inherits every dependency that source ever grows.**
