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

1. ``DIRECT``    — eBay sold-count over 90 days. Not an estimate; it's the
                   number. Requires Marketplace Insights API approval (Terapeak
                   in Seller Hub is the free manual equivalent).
2. ``VELOCITY``  — Δreview_count between two snapshots ≥ ``MIN_VELOCITY_DAYS``
                   apart, divided by the share of buyers who leave a review.
                   This is the good one, and it's why the snapshot table has to
                   start filling before the feature is useful.
3. ``BADGE``     — Walmart's "500+ bought since yesterday" flag. Coarse, and a
                   *floor* rather than an estimate, but it's same-day truth.
4. ``HEURISTIC`` — total review count over listing age. Wildly noisy: a listing
                   with 4,000 reviews accumulated over six years tells you
                   almost nothing about this month. Ranks; never decides.
5. ``UNKNOWN``   — no listing, or no signal at all.

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
    DIRECT = "direct"
    VELOCITY = "velocity"
    BADGE = "badge"
    HEURISTIC = "heuristic"
    UNKNOWN = "unknown"


# Ordering for "which estimate wins when several are available". Higher is
# better; used by `estimate_demand` to pick among computed candidates.
_CONFIDENCE_RANK: dict[DemandConfidence, int] = {
    DemandConfidence.DIRECT: 4,
    DemandConfidence.VELOCITY: 3,
    DemandConfidence.BADGE: 2,
    DemandConfidence.HEURISTIC: 1,
    DemandConfidence.UNKNOWN: 0,
}


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
    bought_badge_min: int | None = None  # "500+ bought since yesterday" → 500
    first_available_at: datetime | None = None


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
            in (DemandConfidence.DIRECT, DemandConfidence.VELOCITY, DemandConfidence.BADGE)
        )

    def unit_share(self, seller_count: int | None) -> float | None:
        """Your slice of monthly demand: ``sales ÷ (sellers + 1)``.

        The ``+1`` is you joining the listing. Five sellers on a 300 unit/month
        item is 50 units each and a real business; five sellers on a 40
        unit/month item is a price war with extra steps.
        """
        if self.estimated_monthly_sales is None:
            return None
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


def _from_sold_count(snapshots: list[Snapshot]) -> DemandEstimate | None:
    """eBay 90-day sold count → monthly. Direct measurement, no assumptions."""
    latest = next(
        (s for s in reversed(snapshots) if s.sold_count_90d is not None), None
    )
    if latest is None or latest.sold_count_90d is None:
        return None
    monthly = latest.sold_count_90d / 3.0
    return DemandEstimate(
        estimated_monthly_sales=round(monthly, 1),
        confidence=DemandConfidence.DIRECT,
        basis=f"{latest.sold_count_90d} sold in trailing 90 days",
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
        _from_sold_count(ordered),
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
