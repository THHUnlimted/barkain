"""Demand-estimation tests.

Margins are arithmetic; whether the thing *sells* is the real question. The
signals are ranked by how close each one is to counting units, and two
properties carry the most weight:

  * **Inventory depletion** is the only signal that counts units, and it needs
    a guard — a listing reporting 400 units on Monday and 0 on Tuesday went out
    of stock, it did not sell 400 units in a day. Without that guard one bad
    observation produces a phantom top-ranked row, which on a velocity-first
    ranking is the worst failure the system can have.
  * **Confidence tiers must not collapse.** A verdict built on observed stock
    movement and one built on a lifetime review total must not look the same,
    so ``estimate_demand`` always returns the highest-confidence candidate.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from m15_sourcing.demand import (
    MIN_DEPLETION_DAYS,
    DemandConfidence,
    Snapshot,
    estimate_demand,
    estimate_from_inventory_report,
    estimate_from_orders,
    estimate_units_from_bsr,
    normalize_bsr_category,
    price_stability,
)

BASE = datetime(2026, 7, 1, tzinfo=UTC)


def _stock_series(quantities: list[int], *, step_days: int = 1) -> list[Snapshot]:
    """Daily observations of purchasable quantity."""
    return [
        Snapshot(captured_at=BASE + timedelta(days=i * step_days), available_quantity=q)
        for i, q in enumerate(quantities)
    ]


# MARK: - Inventory depletion


def test_depletion_sums_decreases_over_the_window():
    # 10 units gone across 10 days → 30/month.
    snapshots = _stock_series([100, 99, 98, 97, 96, 95, 94, 93, 92, 91, 90])
    estimate = estimate_demand(snapshots)

    assert estimate.confidence is DemandConfidence.OBSERVED
    assert estimate.estimated_monthly_sales == pytest.approx(30.0, abs=0.5)


def test_restock_resets_the_baseline_and_counts_nothing():
    """An increase is a restock, not negative sales."""
    snapshots = _stock_series([50, 45, 40, 100, 95, 90, 85])
    estimate = estimate_demand(snapshots)

    assert estimate.confidence is DemandConfidence.OBSERVED
    # 5+5 before the restock, 5+5+5 after = 25 units over 6 days.
    assert estimate.estimated_monthly_sales == pytest.approx(125.0, abs=1.0)
    assert "restock" in estimate.basis


def test_implausible_single_day_drop_is_discarded_as_a_correction():
    """400 → 0 overnight is a stockout or a feed glitch, not 400 sales.

    This is the guard that separates the estimator from the naive version. The
    phantom row it prevents would rank first on a velocity-first sort.
    """
    snapshots = _stock_series([400, 396, 392, 388, 0, 0, 0])
    estimate = estimate_demand(snapshots)

    assert estimate.confidence is DemandConfidence.OBSERVED
    assert "implausible" in estimate.basis
    assert "depletion_outliers_discarded" in estimate.assumptions
    # Only the 4+4+4 of real movement should have counted, not the 388 cliff.
    assert estimate.estimated_monthly_sales is not None
    assert estimate.estimated_monthly_sales < 100


def test_a_gradual_drawdown_to_zero_is_not_discarded():
    """The guard keys off the *rate* of a single drop, not the destination."""
    snapshots = _stock_series([10, 8, 7, 5, 4, 2, 1])
    estimate = estimate_demand(snapshots)
    assert estimate.confidence is DemandConfidence.OBSERVED
    assert "implausible" not in estimate.basis


def test_stock_that_never_moves_reports_zero_rather_than_a_rosier_proxy():
    """Nothing selling IS a signal — falling through to reviews would hide it."""
    snapshots = [
        Snapshot(captured_at=BASE + timedelta(days=i), available_quantity=25, review_count=4000)
        for i in range(10)
    ]
    estimate = estimate_demand(snapshots)

    assert estimate.confidence is DemandConfidence.OBSERVED
    assert estimate.estimated_monthly_sales == 0.0


def test_depletion_needs_a_long_enough_window():
    """Two observations a day apart can't establish a rate."""
    snapshots = _stock_series([100, 95])
    estimate = estimate_demand(snapshots)
    assert estimate.confidence is not DemandConfidence.OBSERVED


def test_depletion_window_floor_is_enforced():
    short = _stock_series([100, 95, 90], step_days=1)
    span = (short[-1].captured_at - short[0].captured_at).days
    assert span < MIN_DEPLETION_DAYS
    assert estimate_demand(short).confidence is not DemandConfidence.OBSERVED


def test_depletion_is_seller_specific_and_says_so():
    """Callers must not divide this by seller count — it's already per-offer."""
    estimate = estimate_demand(_stock_series([100, 95, 90, 85, 80, 75, 70]))
    assert "seller_specific_not_listing_wide" in estimate.assumptions


# MARK: - First-party reports


def test_inventory_report_is_depletion_without_the_inference():
    estimate = estimate_from_inventory_report(units_sold=60, period_days=30)
    assert estimate.confidence is DemandConfidence.OBSERVED
    assert estimate.estimated_monthly_sales == pytest.approx(60.0, abs=0.1)


def test_orders_api_gives_a_direct_count():
    estimate = estimate_from_orders(order_units=45, window_days=30)
    assert estimate.estimated_monthly_sales == pytest.approx(45.0, abs=0.1)


def test_a_ninety_day_window_is_not_read_as_a_month():
    """The window has to divide, or a 90-day export triples the estimate."""
    monthly = estimate_from_orders(order_units=90, window_days=30)
    quarterly = estimate_from_orders(order_units=90, window_days=90)
    assert monthly.estimated_monthly_sales == pytest.approx(90.0, abs=0.1)
    assert quarterly.estimated_monthly_sales == pytest.approx(30.0, abs=0.1)


# MARK: - BSR


def test_bsr_converts_within_the_modelled_range():
    units = estimate_units_from_bsr(5_000, "home_garden")
    assert units is not None
    assert units > 0


def test_better_rank_means_more_units():
    strong = estimate_units_from_bsr(1_000, "home_garden")
    weak = estimate_units_from_bsr(100_000, "home_garden")
    assert strong is not None and weak is not None
    assert strong > weak


def test_bsr_past_the_tail_cutoff_reads_as_almost_nothing():
    """Past 500k the curve is extrapolating far outside its calibration.

    The answer there is a deliberate ``0.0`` — "almost nothing" — rather than a
    precise-looking small number the curve hasn't earned. It's not ``None``:
    a rank that far down is genuine evidence of no demand, and zero carries
    that, where ``None`` would read as "no data" and fall through to a rosier
    proxy signal.
    """
    assert estimate_units_from_bsr(900_000, "home_garden") == 0.0
    # Contrast: a missing or nonsensical rank is genuinely no-data.
    assert estimate_units_from_bsr(0, "home_garden") is None
    assert estimate_units_from_bsr(-5, "home_garden") is None


def test_bsr_category_normalization_is_forgiving():
    assert normalize_bsr_category("Home & Garden") == normalize_bsr_category("home_garden")


def test_unknown_bsr_category_still_resolves_to_something():
    assert normalize_bsr_category("Blorptech") is not None


# MARK: - Tier precedence


def test_observed_depletion_outranks_a_large_review_total():
    """4,000 lifetime reviews says nothing about this month."""
    snapshots = [
        Snapshot(
            captured_at=BASE + timedelta(days=i),
            available_quantity=100 - i,
            review_count=4000,
            first_available_at=BASE - timedelta(days=2000),
        )
        for i in range(8)
    ]
    estimate = estimate_demand(snapshots)
    assert estimate.confidence is DemandConfidence.OBSERVED


def test_no_snapshots_is_unknown_not_zero():
    """Unknown can never be a PASS; zero would be a claim we haven't earned."""
    estimate = estimate_demand([])
    assert estimate.confidence is DemandConfidence.UNKNOWN
    assert estimate.estimated_monthly_sales is None


def test_snapshots_with_no_usable_signal_are_unknown():
    snapshots = [Snapshot(captured_at=BASE + timedelta(days=i)) for i in range(10)]
    assert estimate_demand(snapshots).confidence is DemandConfidence.UNKNOWN


def test_snapshots_are_sorted_before_estimating():
    """Callers shouldn't have to pre-sort; out-of-order input is common."""
    ordered = _stock_series([100, 95, 90, 85, 80, 75, 70])
    shuffled = [ordered[3], ordered[0], ordered[6], ordered[1], ordered[4], ordered[2], ordered[5]]
    assert (
        estimate_demand(shuffled).estimated_monthly_sales
        == estimate_demand(ordered).estimated_monthly_sales
    )


# MARK: - Price stability


def test_a_stable_price_series_reads_as_stable():
    from decimal import Decimal

    snapshots = [
        Snapshot(captured_at=BASE + timedelta(days=i), price=Decimal("24.99")) for i in range(10)
    ]
    assert price_stability(snapshots).is_stable


def test_a_swinging_buy_box_reads_as_unstable():
    """A price war you're about to walk into."""
    from decimal import Decimal

    prices = ["30.00", "21.00", "33.00", "19.00", "31.00", "18.00", "34.00", "20.00"]
    snapshots = [
        Snapshot(captured_at=BASE + timedelta(days=i), price=Decimal(p))
        for i, p in enumerate(prices)
    ]
    assert not price_stability(snapshots).is_stable


def test_stability_of_nothing_is_not_a_claim_of_stability():
    assert price_stability([]).coefficient_of_variation is None
