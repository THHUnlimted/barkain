"""Demand estimation from listing snapshots.

Pure module — takes snapshot dataclasses, returns an estimate. The DB query
that produces the snapshots lives in ``service.py``.

## The problem

Walmart does not publish sales figures. Neither does eBay for active listings.
So every number here is a proxy, and the honest thing to do is rank the proxies
by how much they can be trusted and carry that ranking all the way to the UI.
A verdict built on a direct sold-count and one built on a single review count
should not look the same on screen.

## Signal hierarchy

Ordered by how close each is to actually counting units. Only the top three
should ever move capital; the rest exist to rank and to fill the gap while the
snapshot table accumulates.

1. ``OBSERVED``  — inventory depletion. Poll the purchasable quantity on a
                   listing, sum the day-over-day *decreases*, and reset the
                   baseline on any increase (a restock). That sum is units
                   sold — not modelled, observed. It is the only signal that
                   measures a *specific seller's* movement rather than the
                   whole listing's, which is exactly what unit-share wants.
                   Published accuracy on products with observable stock
                   movement runs around 87% of actual monthly units.
2. ``DIRECT``    — eBay exact sold count over a window. Terapeak / Product
                   Research inside Seller Hub is the practical source; the
                   Marketplace Insights API covers the same ground but is a
                   Limited Release that, as of mid-2026, is effectively closed
                   to anyone who isn't a major partner.
3. ``RANK``      — Amazon Best Sellers Rank run through a per-category curve.
                   Roughly 20–40% of actual under rank 50,000, degrading badly
                   on fresh listings and the long tail. Category-specific by
                   necessity: rank 1,000 in Beauty is not rank 1,000 in Books.
4. ``VELOCITY``  — Δreview_count between two snapshots ≥ ``MIN_VELOCITY_DAYS``
                   apart, divided by the share of buyers who leave a review.
                   Cheap and universal, but it rests entirely on the review-rate
                   constant, which is the softest number in the system.
5. ``BADGE``     — Walmart's "500+ bought since yesterday" flag. Coarse, and a
                   *floor* rather than an estimate, but it's same-day truth.
6. ``HEURISTIC`` — total review count over listing age. Wildly noisy: a listing
                   with 4,000 reviews accumulated over six years tells you
                   almost nothing about this month. Ranks; never decides.
7. ``UNKNOWN``   — no listing, or no signal at all.

## The review-rate constant

``DEFAULT_REVIEW_RATE = 0.02`` — roughly 2% of buyers leave a review. This is
the single most load-bearing assumption in the whole product and it varies by
category by a factor of several (cheap consumables run lower, hobbyist gear
higher). It's a settings knob for that reason, and every estimate derived from
it carries ``review_rate_assumed`` so nobody mistakes it for measurement.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import Enum

DEFAULT_REVIEW_RATE = 0.02
MIN_VELOCITY_DAYS = 7
# Beyond this the two endpoints are describing different market conditions
# (a holiday spike, a competitor stockout) and averaging across them smooths
# away the thing you wanted to see.
MAX_VELOCITY_WINDOW_DAYS = 120


class DemandConfidence(str, Enum):
    OBSERVED = "observed"
    DIRECT = "direct"
    RANK = "rank"
    VELOCITY = "velocity"
    BADGE = "badge"
    HEURISTIC = "heuristic"
    UNKNOWN = "unknown"


# Ordering for "which estimate wins when several are available". Higher is
# better; used by `estimate_demand` to pick among computed candidates.
_CONFIDENCE_RANK: dict[DemandConfidence, int] = {
    DemandConfidence.OBSERVED: 6,
    DemandConfidence.DIRECT: 5,
    DemandConfidence.RANK: 4,
    DemandConfidence.VELOCITY: 3,
    DemandConfidence.BADGE: 2,
    DemandConfidence.HEURISTIC: 1,
    DemandConfidence.UNKNOWN: 0,
}

# Minimum span before depletion data is worth reading. Two consecutive days of
# stock counts on a slow mover is mostly noise; a week is enough for the
# decreases to separate from the restocks.
MIN_DEPLETION_DAYS = 5

# A single-day drop larger than this is treated as a stock correction (a seller
# pulling inventory, a feed error, a listing-level quantity reset) rather than
# a sale. Without the guard, one bad observation of "quantity: 0" turns a
# 40-unit/month item into a 900-unit/month item.
_MAX_PLAUSIBLE_DAILY_DEPLETION = 0.75  # share of the running baseline


@dataclass(frozen=True)
class Snapshot:
    """One observation of a listing at a point in time."""

    captured_at: datetime
    price: Decimal | None = None
    review_count: int | None = None
    rating: float | None = None
    seller_count: int | None = None
    in_stock: bool | None = None
    sold_count_90d: int | None = None
    sold_count_window_days: int | None = None  # window `sold_count_90d` covers
    bought_badge_min: int | None = None  # "500+ bought since yesterday" → 500
    first_available_at: datetime | None = None
    # Purchasable quantity as reported by the channel — the raw material for
    # the depletion estimator. On Walmart and Amazon this is what the cart
    # surfaces when you request an implausibly large quantity; the response
    # names the true remaining stock for the current offer.
    available_quantity: int | None = None
    # Amazon Best Sellers Rank and the top-level category it's ranked in.
    # Both are required together — a rank without its category can't be
    # converted, because the curves differ by an order of magnitude.
    sales_rank: int | None = None
    sales_rank_category: str | None = None


@dataclass(frozen=True)
class DemandEstimate:
    """Estimated monthly unit sales for a listing, plus how much to trust it."""

    estimated_monthly_sales: float | None
    confidence: DemandConfidence
    basis: str
    observation_days: int | None = None
    review_delta: int | None = None
    assumptions: tuple[str, ...] = ()

    @property
    def is_actionable(self) -> bool:
        """True when the estimate is good enough to promote a row, not just rank it.

        ``HEURISTIC`` is deliberately excluded: total-reviews-over-age is fine
        for sorting a list but it should never be the reason you commit capital.
        """
        return (
            self.estimated_monthly_sales is not None
            and self.confidence
            in (
                DemandConfidence.OBSERVED,
                DemandConfidence.DIRECT,
                DemandConfidence.RANK,
                DemandConfidence.VELOCITY,
                DemandConfidence.BADGE,
            )
        )

    @property
    def is_seller_specific(self) -> bool:
        """True when the estimate already measures one offer, not the whole listing.

        Inventory depletion tracks a single seller's stock, so dividing it by
        seller count again would double-count the competition and understate a
        good row by a factor of five.
        """
        return self.confidence == DemandConfidence.OBSERVED

    def unit_share(self, seller_count: int | None) -> float | None:
        """Your slice of monthly demand: ``sales ÷ (sellers + 1)``.

        The ``+1`` is you joining the listing. Five sellers on a 300 unit/month
        item is 50 units each and a real business; five sellers on a 40
        unit/month item is a price war with extra steps.

        Skipped entirely for seller-specific estimates — see
        ``is_seller_specific``.
        """
        if self.estimated_monthly_sales is None:
            return None
        if self.is_seller_specific:
            return round(self.estimated_monthly_sales, 1)
        sellers = seller_count if seller_count and seller_count > 0 else 0
        return round(self.estimated_monthly_sales / (sellers + 1), 1)

    def as_dict(self) -> dict[str, object]:
        return {
            "estimated_monthly_sales": self.estimated_monthly_sales,
            "confidence": self.confidence.value,
            "basis": self.basis,
            "observation_days": self.observation_days,
            "review_delta": self.review_delta,
            "assumptions": list(self.assumptions),
        }


UNKNOWN_DEMAND = DemandEstimate(
    estimated_monthly_sales=None,
    confidence=DemandConfidence.UNKNOWN,
    basis="no signal available",
)


# MARK: - Individual estimators


def _from_inventory_depletion(snapshots: list[Snapshot]) -> DemandEstimate | None:
    """Sum observed stock decreases, resetting the baseline on every restock.

    This is the closest thing to counting units without the retailer's own
    data. The algorithm is deliberately boring:

        walk the observations in time order
        a decrease  → that many units sold
        an increase → a restock; reset the baseline, count nothing
        an implausibly large single-day decrease → a correction, not a sale

    The last guard is what separates this from the naive version. Sellers pull
    inventory, feeds glitch, and a listing that reports 400 units on Monday and
    0 on Tuesday almost certainly went out of stock rather than selling 400
    units in a day. Counting it would put a garbage row at the top of the rank,
    which on a velocity-first ranking is the worst possible failure.

    Note this measures **one offer's** movement, not the listing's. That's a
    feature: it's already the seller-specific number that unit-share is trying
    to approximate, so callers should not divide it by seller count again.
    """
    observed = [s for s in snapshots if s.available_quantity is not None]
    if len(observed) < 2:
        return None
    observed.sort(key=lambda s: s.captured_at)

    span_days = (
        observed[-1].captured_at - observed[0].captured_at
    ).total_seconds() / 86400.0
    if span_days < MIN_DEPLETION_DAYS:
        return None

    units_sold = 0
    restocks = 0
    discarded = 0
    previous = observed[0].available_quantity
    assert previous is not None

    for snapshot in observed[1:]:
        current = snapshot.available_quantity
        assert current is not None
        if current > previous:
            restocks += 1
        elif current < previous:
            drop = previous - current
            if previous > 0 and drop / previous > _MAX_PLAUSIBLE_DAILY_DEPLETION:
                discarded += 1
            else:
                units_sold += drop
        previous = current

    if units_sold <= 0 and restocks == 0:
        # Stock never moved across the whole window. That IS a signal — this
        # offer sells roughly nothing — so report zero rather than falling
        # through to a rosier proxy.
        return DemandEstimate(
            estimated_monthly_sales=0.0,
            confidence=DemandConfidence.OBSERVED,
            basis=f"no stock movement observed over {span_days:.0f} days",
            observation_days=int(round(span_days)),
        )

    monthly = units_sold / span_days * 30.0
    detail = f"{units_sold} units of observed stock depletion over {span_days:.0f} days"
    if restocks:
        detail += f", {restocks} restock(s) excluded"
    if discarded:
        detail += f", {discarded} implausible drop(s) discarded"

    assumptions = ["seller_specific_not_listing_wide"]
    if discarded:
        assumptions.append("depletion_outliers_discarded")

    return DemandEstimate(
        estimated_monthly_sales=round(monthly, 1),
        confidence=DemandConfidence.OBSERVED,
        basis=detail,
        observation_days=int(round(span_days)),
        assumptions=tuple(assumptions),
    )


def _from_sold_count(snapshots: list[Snapshot]) -> DemandEstimate | None:
    """Exact sold count over a stated window → monthly. Measurement, not model.

    ``sold_count_window_days`` defaults to 90 because that's what both eBay
    Terapeak and the Marketplace Insights API report, but it's carried
    explicitly so a 30-day Product Research export doesn't get divided by three.
    """
    latest = next(
        (s for s in reversed(snapshots) if s.sold_count_90d is not None), None
    )
    if latest is None or latest.sold_count_90d is None:
        return None
    window = latest.sold_count_window_days or 90
    if window <= 0:
        return None
    monthly = latest.sold_count_90d / window * 30.0
    return DemandEstimate(
        estimated_monthly_sales=round(monthly, 1),
        confidence=DemandConfidence.DIRECT,
        basis=f"{latest.sold_count_90d} sold in trailing {window} days",
        observation_days=window,
    )


# MARK: - Amazon BSR
#
# Per-category power-law curves: monthly_units ≈ a × rank^(-b). Rank-to-sales is
# category-specific by an order of magnitude — a rank of 1,000 in Books is a
# very different business from a rank of 1,000 in Beauty, because the
# denominators (catalogue size and category velocity) differ enormously.
#
# These coefficients are calibrated to published sales-rank charts as of
# 2026-07 and should be treated exactly like the fee tables: configuration to
# re-verify, not constants. Accuracy is roughly 20–40% of actual under rank
# 50,000 and degrades sharply beyond it and on fresh listings.

_BSR_CURVES: dict[str, tuple[float, float]] = {
    # category → (a, b) for monthly_units = a * rank ** -b
    "books": (95_000.0, 0.72),
    "beauty": (52_000.0, 0.80),
    "health_household": (60_000.0, 0.80),
    "grocery": (38_000.0, 0.79),
    "home_kitchen": (78_000.0, 0.78),
    "tools_home_improvement": (42_000.0, 0.80),
    "toys_games": (46_000.0, 0.79),
    "sports_outdoors": (40_000.0, 0.80),
    "pet_supplies": (36_000.0, 0.79),
    "electronics": (55_000.0, 0.77),
    "office_products": (30_000.0, 0.80),
    "clothing": (48_000.0, 0.81),
    "baby": (28_000.0, 0.79),
    "automotive": (32_000.0, 0.81),
    "default": (45_000.0, 0.79),
}

# Beyond this rank the curve is extrapolating far past where it was calibrated
# and the honest answer is "almost nothing", not a precise small number.
_BSR_TAIL_CUTOFF = 500_000


def normalize_bsr_category(raw: str | None) -> str:
    """Map an Amazon category breadcrumb to a curve key, defaulting safely."""
    if not raw:
        return "default"
    text = raw.strip().lower().replace("&", " ").replace("-", " ")
    text = " ".join(text.split())
    candidates = {
        "books": "books", "beauty": "beauty", "personal care": "beauty",
        "health": "health_household", "household": "health_household",
        "grocery": "grocery", "gourmet": "grocery",
        "home": "home_kitchen", "kitchen": "home_kitchen",
        "tools": "tools_home_improvement", "home improvement": "tools_home_improvement",
        "toys": "toys_games", "games": "toys_games",
        "sports": "sports_outdoors", "outdoors": "sports_outdoors",
        "pet": "pet_supplies",
        "electronics": "electronics", "computers": "electronics",
        "office": "office_products",
        "clothing": "clothing", "shoes": "clothing", "apparel": "clothing",
        "baby": "baby",
        "automotive": "automotive",
    }
    for keyword, key in candidates.items():
        if keyword in text:
            return key
    return "default"


def estimate_units_from_bsr(rank: int, category: str | None = None) -> float | None:
    """Convert a Best Sellers Rank to estimated monthly units."""
    if rank is None or rank <= 0:
        return None
    if rank > _BSR_TAIL_CUTOFF:
        return 0.0
    a, b = _BSR_CURVES.get(
        normalize_bsr_category(category), _BSR_CURVES["default"]
    )
    return round(a * (rank ** -b), 1)


def _from_sales_rank(snapshots: list[Snapshot]) -> DemandEstimate | None:
    """Amazon BSR → monthly units via the category curve."""
    latest = next((s for s in reversed(snapshots) if s.sales_rank), None)
    if latest is None or not latest.sales_rank:
        return None
    monthly = estimate_units_from_bsr(latest.sales_rank, latest.sales_rank_category)
    if monthly is None:
        return None
    category = normalize_bsr_category(latest.sales_rank_category)
    assumptions = ["bsr_curve_estimate"]
    if category == "default":
        assumptions.append("bsr_category_unknown")
    return DemandEstimate(
        estimated_monthly_sales=monthly,
        confidence=DemandConfidence.RANK,
        basis=f"BSR #{latest.sales_rank:,} in {category.replace('_', ' ')}",
        assumptions=tuple(assumptions),
    )


def _from_review_velocity(
    snapshots: list[Snapshot], review_rate: float
) -> DemandEstimate | None:
    """Δreviews between the widest valid snapshot pair → monthly unit sales.

    Picks the earliest and latest snapshots that both carry a review count and
    sit ``MIN_VELOCITY_DAYS`` to ``MAX_VELOCITY_WINDOW_DAYS`` apart. Widest
    valid window wins — more elapsed time means less quantization noise from
    the review counter ticking in ones.
    """
    with_reviews = [s for s in snapshots if s.review_count is not None]
    if len(with_reviews) < 2:
        return None
    with_reviews.sort(key=lambda s: s.captured_at)

    earliest = with_reviews[0]
    latest = with_reviews[-1]
    span_days = (latest.captured_at - earliest.captured_at).total_seconds() / 86400.0

    if span_days > MAX_VELOCITY_WINDOW_DAYS:
        # Walk the start forward until the window is in range, so a listing
        # snapshotted for a year still yields a recent-window estimate.
        cutoff = latest.captured_at - timedelta(days=MAX_VELOCITY_WINDOW_DAYS)
        candidates = [s for s in with_reviews if s.captured_at >= cutoff]
        if len(candidates) < 2:
            return None
        earliest = candidates[0]
        span_days = (latest.captured_at - earliest.captured_at).total_seconds() / 86400.0

    if span_days < MIN_VELOCITY_DAYS:
        return None

    assert earliest.review_count is not None and latest.review_count is not None
    delta = latest.review_count - earliest.review_count
    if delta < 0:
        # Review counts go down when a marketplace purges spam or a variation
        # is split off the listing. Neither is a demand signal.
        return None

    monthly_reviews = delta / span_days * 30.0
    monthly_sales = monthly_reviews / review_rate if review_rate > 0 else 0.0

    return DemandEstimate(
        estimated_monthly_sales=round(monthly_sales, 1),
        confidence=DemandConfidence.VELOCITY,
        basis=(
            f"{delta} new review(s) over {span_days:.0f} days "
            f"÷ {review_rate:.1%} review rate"
        ),
        observation_days=int(round(span_days)),
        review_delta=delta,
        assumptions=("review_rate_assumed",),
    )


def _from_badge(snapshots: list[Snapshot]) -> DemandEstimate | None:
    """Walmart's "N+ bought since yesterday" → a monthly floor."""
    latest = next(
        (s for s in reversed(snapshots) if s.bought_badge_min is not None), None
    )
    if latest is None or not latest.bought_badge_min:
        return None
    # The badge is a daily floor. Extrapolating ×30 would take a floor and
    # present it as a point estimate, so we keep it explicitly conservative
    # and label it a floor in `basis`.
    monthly_floor = latest.bought_badge_min * 30.0
    return DemandEstimate(
        estimated_monthly_sales=round(monthly_floor, 1),
        confidence=DemandConfidence.BADGE,
        basis=f"{latest.bought_badge_min}+ bought/day badge (floor, not a point estimate)",
        assumptions=("badge_is_a_floor",),
    )


def _from_review_total(
    snapshots: list[Snapshot], review_rate: float, now: datetime
) -> DemandEstimate | None:
    """Lifetime reviews ÷ listing age. The estimator of last resort."""
    latest = next((s for s in reversed(snapshots) if s.review_count), None)
    if latest is None or not latest.review_count:
        return None
    first_seen = latest.first_available_at or snapshots[0].captured_at
    age_days = max((now - first_seen).total_seconds() / 86400.0, 30.0)
    monthly_reviews = latest.review_count / age_days * 30.0
    monthly_sales = monthly_reviews / review_rate if review_rate > 0 else 0.0
    return DemandEstimate(
        estimated_monthly_sales=round(monthly_sales, 1),
        confidence=DemandConfidence.HEURISTIC,
        basis=(
            f"{latest.review_count} lifetime reviews over ~{age_days / 30:.0f} months "
            f"÷ {review_rate:.1%} review rate"
        ),
        observation_days=int(round(age_days)),
        assumptions=("review_rate_assumed", "listing_age_estimated"),
    )


# MARK: - Entry point


def estimate_demand(
    snapshots: list[Snapshot],
    *,
    review_rate: float = DEFAULT_REVIEW_RATE,
    now: datetime | None = None,
) -> DemandEstimate:
    """Best available demand estimate for a listing, highest-confidence first."""
    if not snapshots:
        return UNKNOWN_DEMAND

    ordered = sorted(snapshots, key=lambda s: s.captured_at)
    now = now or datetime.now(UTC)

    candidates = [
        _from_inventory_depletion(ordered),
        _from_sold_count(ordered),
        _from_sales_rank(ordered),
        _from_review_velocity(ordered, review_rate),
        _from_badge(ordered),
        _from_review_total(ordered, review_rate, now),
    ]
    available = [c for c in candidates if c is not None]
    if not available:
        return UNKNOWN_DEMAND
    return max(available, key=lambda e: _CONFIDENCE_RANK[e.confidence])


# MARK: - Price stability


@dataclass(frozen=True)
class PriceStability:
    """How much the buy-box price has moved over the observed window.

    A listing whose price swings 30% is a price war you'd be joining mid-fight;
    the current price is not the price you'll get. Coefficient of variation
    (σ/μ) is the right measure because it's scale-free — 5% movement means the
    same thing on a $12 item and a $400 one.
    """

    coefficient_of_variation: float | None
    min_price: Decimal | None
    max_price: Decimal | None
    latest_price: Decimal | None
    observations: int
    trend_pct: float | None  # % change first → last, signed

    @property
    def is_stable(self) -> bool:
        """Stable enough to underwrite a purchase decision.

        Fewer than three observations returns ``True`` — "we haven't watched
        long enough" must not read as "this is volatile", or every new list
        would fail the stability gate on its first crunch.
        """
        if self.coefficient_of_variation is None:
            return True
        return self.coefficient_of_variation <= 0.15

    def as_dict(self) -> dict[str, object]:
        return {
            "coefficient_of_variation": self.coefficient_of_variation,
            "min_price": float(self.min_price) if self.min_price is not None else None,
            "max_price": float(self.max_price) if self.max_price is not None else None,
            "latest_price": float(self.latest_price)
            if self.latest_price is not None
            else None,
            "observations": self.observations,
            "trend_pct": self.trend_pct,
            "is_stable": self.is_stable,
        }


UNKNOWN_STABILITY = PriceStability(
    coefficient_of_variation=None,
    min_price=None,
    max_price=None,
    latest_price=None,
    observations=0,
    trend_pct=None,
)


def price_stability(snapshots: list[Snapshot]) -> PriceStability:
    """Compute price dispersion + trend over the snapshot window."""
    prices = [
        (s.captured_at, s.price) for s in snapshots if s.price is not None and s.price > 0
    ]
    if not prices:
        return UNKNOWN_STABILITY
    prices.sort(key=lambda p: p[0])
    values = [float(p[1]) for p in prices if p[1] is not None]

    latest = prices[-1][1]
    lowest = min(p[1] for p in prices if p[1] is not None)
    highest = max(p[1] for p in prices if p[1] is not None)

    if len(values) < 3:
        return PriceStability(
            coefficient_of_variation=None,
            min_price=lowest,
            max_price=highest,
            latest_price=latest,
            observations=len(values),
            trend_pct=None,
        )

    mean = statistics.fmean(values)
    stdev = statistics.pstdev(values)
    cv = round(stdev / mean, 4) if mean else None
    trend = round((values[-1] - values[0]) / values[0] * 100, 1) if values[0] else None

    return PriceStability(
        coefficient_of_variation=cv,
        min_price=lowest,
        max_price=highest,
        latest_price=latest,
        observations=len(values),
        trend_pct=trend,
    )
