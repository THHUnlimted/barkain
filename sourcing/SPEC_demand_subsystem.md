# Build spec — M15 demand-estimation subsystem

> **Audience:** a coding agent implementing changes to `sourcing/m15_sourcing/demand.py`
> and the collector that feeds it.
> **Status of the code being changed:** merged to `main` (PR #97). `main` is a
> protected branch — work on a feature branch and open a PR.
> **Scope:** demand estimation only. Do not modify `fees.py`, `landed_cost.py`,
> `plans.py`, or `recon.py` except where §7 explicitly says so.

---

## 1. What this subsystem does

It answers one question per listing: **how many units of this will sell per
month, and how much should we trust that number?**

Everything downstream depends on it. `scoring.py` turns the answer into
`unit_share` → `days_to_sell_through` → `annualized_roi`, which is the primary
ranking key for the whole product. An error here does not shift the list
uniformly — it reorders it.

The subsystem is **pure**: no network, no database, no settings reads. It takes
dataclasses in and returns dataclasses out. The DB query that produces the
input lives in `service.py`; the scraper that produces the raw observations
does not exist yet (§6).

---

## 2. Current file layout

```
sourcing/m15_sourcing/demand.py     ← the subsystem. ~610 lines.
sourcing/m15_sourcing/scoring.py    ← the only consumer. Read §5 before touching.
sourcing/m15_sourcing/forecast.py   ← learns per-tier bias from actuals. See §8.
sourcing/m15_sourcing/models.py     ← ListingSnapshot table, mirrors Snapshot.
sourcing/m15_sourcing/service.py    ← _snapshots_for() builds Snapshot lists from DB.
```

Everything is importable as `from m15_sourcing import demand`. There is no test
suite yet — §9 specifies the one to write alongside these changes.

---

## 3. The data model (do not change without updating `models.py`)

`Snapshot` is one observation of one listing at one time. Every field except
`captured_at` is optional, because different channels expose different things.

```python
@dataclass(frozen=True)
class Snapshot:
    captured_at: datetime              # tz-aware, UTC
    price: Decimal | None
    review_count: int | None
    rating: float | None
    seller_count: int | None
    in_stock: bool | None
    sold_count_90d: int | None         # exact sold count over a window
    sold_count_window_days: int | None # the window it covers; defaults to 90
    bought_badge_min: int | None       # "500+ bought since yesterday" → 500
    first_available_at: datetime | None
    available_quantity: int | None     # purchasable qty — the depletion input
    sales_rank: int | None             # Amazon BSR
    sales_rank_category: str | None    # required WITH sales_rank; curves differ 10x
```

`DemandEstimate` is the output:

```python
@dataclass(frozen=True)
class DemandEstimate:
    estimated_monthly_sales: float | None
    confidence: DemandConfidence
    basis: str                         # human-readable, shown in the UI
    observation_days: int | None
    review_delta: int | None
    assumptions: tuple[str, ...]       # e.g. ("review_rate_assumed",)
```

**Invariant:** `estimated_monthly_sales is None` ⟺ `confidence is UNKNOWN`.
Never emit a number with UNKNOWN confidence or vice versa.

---

## 4. The estimators

Six private functions, each `(snapshots) -> DemandEstimate | None`. Returning
`None` means "this estimator cannot fire on this data" — it is not an error and
must not be logged as one.

### 4.1 `_from_inventory_depletion` → `OBSERVED`

Walks stock counts in time order, sums the **decreases**, resets baseline on
increases (restocks).

```
for each consecutive pair:
    current > previous  → restock; reset baseline, count nothing
    current < previous  → drop = previous - current
                          if drop / previous > 0.75: discard as a correction
                          else: units_sold += drop
```

Guards, all load-bearing:
- Requires ≥2 observations spanning ≥ `MIN_DEPLETION_DAYS` (5).
- `_MAX_PLAUSIBLE_DAILY_DEPLETION = 0.75`. A listing showing 400 units Monday
  and 0 Tuesday went out of stock; it did not sell 400 units. Without this
  guard one bad reading produces a phantom top-ranked row, which on a
  velocity-first ranking is the worst failure the system can have.
- Zero movement across the whole window returns `0.0`, **not** `None` — "this
  sells nothing" is a real answer and must not fall through to a rosier proxy.

Carries `assumptions=("seller_specific_not_listing_wide",)`. See §5.2.

### 4.2 `_from_sold_count` → `DIRECT`

`sold_count_90d ÷ sold_count_window_days × 30`. Exact measurement.

`sold_count_window_days` defaults to 90 but **must** be respected when present —
a 30-day Terapeak export divided by three is a 3× under-read.

### 4.3 `_from_sales_rank` → `RANK`

`monthly_units = a × rank^-b`, coefficients per category in `_BSR_CURVES`
(14 categories + `default`). `normalize_bsr_category()` maps a breadcrumb to a
curve key; unmatched → `default`.

`_BSR_TAIL_CUTOFF = 500_000`; beyond it return `0.0`, because the curve is
extrapolating far past calibration and the honest answer is "almost nothing".

### 4.4 `_from_review_velocity` → `VELOCITY`

`Δreviews ÷ span_days × 30 ÷ review_rate`.

- Picks the widest valid pair; window must be ≥ `MIN_VELOCITY_DAYS` (7) and
  ≤ `MAX_VELOCITY_WINDOW_DAYS` (120), walking the start forward if too wide.
- Negative delta returns `None` — review counts drop when a marketplace purges
  spam or splits a variation, neither of which is a demand signal.
- `review_rate` defaults to 0.02 and is the softest number in the system.

### 4.5 `_from_badge` → `BADGE`

`bought_badge_min × 30`. A **floor**, not a point estimate.

### 4.6 `_from_review_total` → `HEURISTIC`

`lifetime_reviews ÷ listing_age_months ÷ review_rate`. Estimator of last resort.

---

## 5. Selection, and what downstream consumes

### 5.1 `estimate_demand()` — the selector

Runs all six, discards `None`, returns the one with the highest
`_CONFIDENCE_RANK`. **This is where change #1 and #2 land.**

### 5.2 `unit_share(seller_count)`

```
unit_share = estimated_monthly_sales ÷ (seller_count + 1)
```

The `+1` is you joining the listing. **Exception:** when
`is_seller_specific` is True (currently: `OBSERVED` only), the division is
skipped — depletion already measures one seller's movement, and dividing again
understates a good row by ~5×.

### 5.3 The contract with `scoring.py`

`score_channel()` reads exactly three things off the estimate. Do not break these:

| Read | Used for |
|---|---|
| `demand.unit_share(seller_count)` | the `min_monthly_unit_share` gate, and the denominator of `sell_through_days()` |
| `demand.is_actionable` | if False, the row gets a **soft flag** → `WATCH`, never `PASS` |
| `demand.confidence.value` | displayed in the reason string |

Changing `is_actionable` for a tier is therefore a **verdict-level** change, not
cosmetic. It moves rows from PASS to WATCH.

---

## 6. CHANGES TO IMPLEMENT

These come from the operator's field experience, which overrides my
first-principles ordering. Implement all four.

### Change 1 — reorder the confidence hierarchy

The badge is a better estimator in practice than its rank suggests; review
velocity is worse. Rationale: the badge is same-day, channel-native, and has no
conversion constant to guess. Review velocity guesses twice — whether reviews
tracked sales, and what fraction of buyers review.

```python
_CONFIDENCE_RANK: dict[DemandConfidence, int] = {
    DemandConfidence.OBSERVED:  6,   # unchanged — exact count
    DemandConfidence.DIRECT:    5,   # unchanged — exact count
    DemandConfidence.BADGE:     4,   # was 2  ↑
    DemandConfidence.RANK:      3,   # was 4  ↓
    DemandConfidence.VELOCITY:  2,   # was 3  ↓
    DemandConfidence.HEURISTIC: 1,   # unchanged
    DemandConfidence.UNKNOWN:   0,
}
```

Update the module docstring's signal-hierarchy list to match. It currently
documents the old order and would otherwise become a lie.

### Change 2 — `VELOCITY` loses `is_actionable`

```python
@property
def is_actionable(self) -> bool:
    return (
        self.estimated_monthly_sales is not None
        and self.confidence in (
            DemandConfidence.OBSERVED,
            DemandConfidence.DIRECT,
            DemandConfidence.BADGE,
            DemandConfidence.RANK,
        )
    )
```

`VELOCITY` moves to ranking-only, alongside `HEURISTIC`. A row whose only
signal is review velocity now lands in `WATCH` rather than `PASS`.

**Expect this to move rows.** That is the intent: the estimate rests entirely
on an unvalidated constant, so "we don't know yet" is the honest verdict.

### Change 3 — combine badge and rank instead of letting one win

They are complementary, not redundant: the badge is a high-confidence *floor*,
rank is a moderate-confidence *point estimate*. Currently the higher tier wins
and the other is discarded.

In `estimate_demand()`, after selecting the best candidate:

```python
best = max(available, key=lambda e: _CONFIDENCE_RANK[e.confidence])

# Badge and rank measure the same thing from different angles. Take the
# larger — the badge is a floor, so a rank estimate below it is knowably
# too low, and a rank estimate above it is new information the floor can't
# contradict.
badge = next((c for c in available if c.confidence is DemandConfidence.BADGE), None)
rank = next((c for c in available if c.confidence is DemandConfidence.RANK), None)
if badge and rank and best.confidence in (DemandConfidence.BADGE, DemandConfidence.RANK):
    winner = max(badge, rank, key=lambda e: e.estimated_monthly_sales or 0.0)
    return replace(
        winner,
        basis=f"{winner.basis}; cross-checked against "
              f"{(rank if winner is badge else badge).basis}",
        assumptions=tuple(dict.fromkeys(winner.assumptions + ("badge_rank_combined",))),
    )
return best
```

Only combine when **both** fired and the winner is one of those two. Never let
this override `OBSERVED` or `DIRECT`.

### Change 4 — record the disagreement

When two or more estimators fire and the highest and lowest differ by more than
**3×**, append `"estimator_disagreement"` to `assumptions` on the returned
estimate, and include the spread in `basis`.

This is diagnostic, not corrective — do not adjust the number. A 3× spread
between `rank` and `velocity` almost always means the review-rate constant is
wrong for that category, and surfacing it is how that gets found. It also feeds
§8.

---

## 7. Files you may touch

| File | Permitted change |
|---|---|
| `demand.py` | all of §6 |
| `scoring.py` | **none required.** The contract in §5.3 is unchanged. If you find yourself editing it, stop and re-read §5.3. |
| `sourcing/README.md` | update §5's tier table to match the new ordering |
| `sourcing/BUILD_PRINT.html` | update the Sheet S-07 tier table (same content, HTML) |

Do not touch `fees.py`, `landed_cost.py`, `plans.py`, `recon.py`, `models.py`,
`service.py`, or the migration.

---

## 8. Not in scope, but design for it

Two things are coming; don't make them harder.

**The depletion collector.** `_from_inventory_depletion` reads
`Snapshot.available_quantity`; nothing writes it yet. The collector will poll a
listing's purchasable quantity daily and write one `ListingSnapshot` row per
SKU per day. It should run against the **shortlist** (rows that already cleared
the fee gates), not all 3,000 rows — roughly 50–200 SKUs/day. Keep the
estimator agnostic about where the numbers came from.

**Bias calibration.** `forecast.py` learns a per-tier and per-(tier, category)
correction factor from actuals and exposes
`DemandCalibration.apply(monthly_units, signal_tier, category) -> (units, basis)`.
It is **not** wired into `estimate_demand()` and should not be wired in by this
task — the correction belongs at the scoring layer where the category is known.
Just make sure `confidence.value` stays a stable string, since that's the key
the calibration is stored under.

---

## 9. Tests to write

No test suite exists for this module yet. Create
`sourcing/tests/test_demand.py` (add `sourcing/tests/__init__.py`). Pure module,
so no fixtures, no DB, no network.

Required cases:

**Hierarchy**
- badge + velocity both fire → badge wins
- rank + velocity both fire → rank wins
- observed + everything → observed wins
- direct + badge → direct wins

**`is_actionable`**
- velocity-only estimate → `is_actionable is False`
- badge-only → `is_actionable is True`
- rank-only → `is_actionable is True`

**Badge/rank combine**
- badge 1500, rank 68 → returns 1500, `"badge_rank_combined"` in assumptions
- badge 40, rank 300 → returns 300, same flag
- badge alone (no rank) → no combine flag
- observed 120 + badge 1500 → returns **120**; combine must not override

**Depletion guards** (regression-critical)
- `[240, 180]` over 15 days → 60 units → 120.0/mo
- `[180, 60, 140]` → restock excluded, not counted as negative
- `[400, 0]` → drop discarded as correction, `"depletion_outliers_discarded"` set
- flat `[50, 50, 50]` over 15 days → returns `0.0`, not `None`
- 2 observations 2 days apart → `None` (below `MIN_DEPLETION_DAYS`)

**Disagreement**
- rank 68 + velocity 1200 → `"estimator_disagreement"` in assumptions
- rank 68 + velocity 90 → flag absent

**Invariant**
- for every estimator, `estimated_monthly_sales is None` ⟺ `confidence is UNKNOWN`

**Unit share**
- observed 120, seller_count 5 → 120 (not divided)
- rank 120, seller_count 5 → 20.0 (divided)

---

## 10. Acceptance

- `cd backend && python3 -m ruff check --config pyproject.toml --select E,F,E741 ../sourcing/` passes
- `python3 sourcing/demo_crunch.py` runs clean
- new tests pass
- module docstring hierarchy matches `_CONFIDENCE_RANK`
- README and BUILD_PRINT tier tables match

Branch from `main`, open a PR. Do not push to `main` directly — it is protected.

---

## 11. Open question for the operator

**How coarse are the Walmart badge buckets?** If they are `50+ / 100+ / 500+`,
treating the badge as a floor and extrapolating ×30 is fair, and Change 1 is
correctly sized. If Walmart ever surfaces an *exact* daily count, the badge stops
being a floor and becomes closer to `DIRECT` — it should then rank at 5, and
Change 3's `max()` combine becomes wrong (an exact number should not be floored
upward by a curve estimate).

Confirm before treating Change 1 as final.
