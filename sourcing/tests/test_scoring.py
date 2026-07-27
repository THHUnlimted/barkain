"""Verdict and ranking tests.

Two ideas carry this module:

  * **Velocity beats margin.** Rows sort by annualized ROI, and the cycle in the
    denominator is sell-through *plus reorder lead time*. Capital redeploys when
    the next case lands, not when the last unit ships. Omitting lead time
    produced four-figure percentages on every fast mover in testing and
    reordered the whole list on an artifact of the formula.
  * **A failed check and an unknown are different things.** "It loses money" is
    a reason to reject; "we have no demand data yet" is a reason to WATCH and
    re-crunch after the snapshot worker runs. Collapsing the two either buries
    good rows or promotes unknowable ones.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from m15_sourcing.demand import (
    UNKNOWN_DEMAND,
    UNKNOWN_STABILITY,
    DemandConfidence,
    DemandEstimate,
    PriceStability,
)
from m15_sourcing.fees import ItemDimensions, walmart_economics
from m15_sourcing.scoring import (
    BRAND_AUTHORIZED,
    BRAND_RESTRICTED,
    BRAND_UNKNOWN,
    Thresholds,
    Verdict,
    annualized_roi,
    blend_score,
    score_channel,
    sell_through_days,
)

# `is_stable` is a derived property (CV <= 0.15), not a field — a stable
# fixture is built by giving it a tight CV and enough observations to judge.
STABLE = PriceStability(
    coefficient_of_variation=0.02,
    min_price=Decimal("24.50"),
    max_price=Decimal("25.50"),
    latest_price=Decimal("24.99"),
    observations=10,
    trend_pct=0.5,
)

VOLATILE = PriceStability(
    coefficient_of_variation=0.35,
    min_price=Decimal("18.00"),
    max_price=Decimal("34.00"),
    latest_price=Decimal("31.00"),
    observations=10,
    trend_pct=-4.0,
)


def _demand(units: float, confidence: DemandConfidence = DemandConfidence.OBSERVED):
    return DemandEstimate(
        estimated_monthly_sales=units, confidence=confidence, basis="test fixture"
    )


# Complete dimensions on purpose. An incomplete `ItemDimensions` makes the fee
# engine flag `assumed_weight` / `assumed_cubic_feet`, and `score_channel`
# promotes those assumptions to soft flags — which caps the verdict at WATCH.
# That behaviour is correct (a PASS built on guessed dimensions shouldn't look
# like a measured one), so a fixture testing the PASS path has to be measured.
FULL_DIMS = ItemDimensions(
    weight_lb=Decimal("1"),
    length_in=Decimal("8"),
    width_in=Decimal("6"),
    height_in=Decimal("4"),
)


def _economics(sale: str, cost: str):
    return walmart_economics(
        sale_price=Decimal(sale),
        unit_cost=Decimal(cost),
        category="home_garden",
        dims=FULL_DIMS,
    )


# MARK: - Sell-through


def test_sell_through_converts_an_order_to_days_at_the_estimated_rate():
    # 60 units at 30/month = 2 months = 60 days.
    assert sell_through_days(60, 30.0) == pytest.approx(60.0, abs=0.5)


def test_sell_through_is_none_when_either_input_is_missing():
    """An unknown turn rate must not silently become a fast one."""
    assert sell_through_days(None, 30.0) is None
    assert sell_through_days(60, None) is None
    assert sell_through_days(60, 0.0) is None
    assert sell_through_days(0, 30.0) is None


def test_sell_through_has_a_floor_of_one_day():
    """Guards the downstream division; nothing clears in zero days."""
    assert sell_through_days(1, 100_000.0) >= 1.0


# MARK: - Annualized ROI


def test_lead_time_is_part_of_the_cycle():
    """An item clearing in 6 days on a 3-week reorder turns ~14x/yr, not 60x."""
    without_lead = annualized_roi(Decimal("50"), 6.0, reorder_lead_time_days=0.0)
    with_lead = annualized_roi(Decimal("50"), 6.0, reorder_lead_time_days=21.0)

    assert without_lead is not None and with_lead is not None
    assert with_lead < without_lead
    # 365 / (6 + 21) = 13.5 turns; 50% ROI x 13.5 = ~676%.
    assert with_lead == pytest.approx(676.0, abs=5.0)


def test_ignoring_lead_time_is_what_produced_four_figure_percentages():
    """The bug this guard exists for: a fast mover on a slow supply chain."""
    naive = annualized_roi(Decimal("50"), 3.0, reorder_lead_time_days=0.0)
    realistic = annualized_roi(Decimal("50"), 3.0, reorder_lead_time_days=21.0)
    assert naive is not None and realistic is not None
    assert naive > 4_000 or naive == 2000.0  # clamped, but enormous either way
    assert realistic < 1_000


def test_annualized_roi_is_clamped_at_both_ends():
    """An unbounded negative distorts a sort exactly as much as a positive."""
    huge = annualized_roi(Decimal("500"), 1.0, reorder_lead_time_days=0.0)
    awful = annualized_roi(Decimal("-500"), 1.0, reorder_lead_time_days=0.0)
    assert huge == 2000.0
    assert awful == -2000.0


def test_annualized_roi_is_none_without_a_sell_through():
    assert annualized_roi(Decimal("50"), None) is None
    assert annualized_roi(Decimal("50"), 0.0) is None


def test_a_thin_fast_mover_can_outrank_a_fat_slow_one():
    """The whole point of the metric — 22% x 11 turns beats 60% x 2."""
    fat_slow = annualized_roi(Decimal("60"), 180.0, reorder_lead_time_days=14.0)
    thin_fast = annualized_roi(Decimal("22"), 18.0, reorder_lead_time_days=14.0)
    assert thin_fast > fat_slow


# MARK: - Verdicts


def test_a_healthy_row_passes():
    scored = score_channel(
        economics=_economics("50.00", "15.00"),
        demand=_demand(120.0),
        stability=STABLE,
        seller_count=3,
        thresholds=Thresholds(),
        minimum_buy_units=24,
        minimum_buy_cost=Decimal("360.00"),
        brand_status=BRAND_AUTHORIZED,
    )
    assert scored.verdict is Verdict.PASS


def test_a_money_losing_row_fails():
    scored = score_channel(
        economics=_economics("20.00", "19.00"),
        demand=_demand(200.0),
        stability=STABLE,
        seller_count=2,
        thresholds=Thresholds(),
        minimum_buy_units=24,
        brand_status=BRAND_AUTHORIZED,
    )
    assert scored.verdict is Verdict.FAIL
    assert scored.reasons


def test_unknown_demand_can_never_pass():
    """No signal is not a small signal."""
    scored = score_channel(
        economics=_economics("50.00", "15.00"),
        demand=UNKNOWN_DEMAND,
        stability=STABLE,
        seller_count=2,
        thresholds=Thresholds(),
        minimum_buy_units=24,
        brand_status=BRAND_AUTHORIZED,
    )
    assert scored.verdict is not Verdict.PASS


def test_missing_data_produces_watch_not_fail():
    """WATCH means 're-crunch after the snapshot worker runs', not 'no'."""
    scored = score_channel(
        economics=_economics("50.00", "15.00"),
        demand=_demand(120.0),
        stability=UNKNOWN_STABILITY,
        seller_count=None,
        thresholds=Thresholds(),
        minimum_buy_units=24,
        brand_status=BRAND_AUTHORIZED,
    )
    assert scored.verdict is Verdict.WATCH


def test_a_missing_listing_fails_immediately():
    scored = score_channel(
        economics=_economics("50.00", "15.00"),
        demand=_demand(120.0),
        stability=STABLE,
        seller_count=2,
        thresholds=Thresholds(),
        listing_exists=False,
    )
    assert scored.verdict is Verdict.FAIL


def test_a_slow_row_fails_the_velocity_gate_despite_a_fat_margin():
    """'Faster beats fatter' expressed as a hard threshold, not just a sort."""
    scored = score_channel(
        economics=_economics("50.00", "12.00"),
        demand=_demand(2.0),  # 2 units/month against a 24-unit case
        stability=STABLE,
        seller_count=2,
        thresholds=Thresholds(),
        minimum_buy_units=24,
        brand_status=BRAND_AUTHORIZED,
    )
    assert scored.verdict is Verdict.FAIL
    assert scored.days_to_sell_through is not None
    assert scored.days_to_sell_through > 90


def test_capital_ceiling_rejects_a_row_the_buyer_cannot_fund():
    """A $9,000 pallet is not a candidate for a buyer with a $5,000 budget."""
    scored = score_channel(
        economics=_economics("50.00", "15.00"),
        demand=_demand(300.0),
        stability=STABLE,
        seller_count=2,
        thresholds=Thresholds(max_capital_per_sku=Decimal("5000")),
        minimum_buy_units=600,
        minimum_buy_cost=Decimal("9000.00"),
        brand_status=BRAND_AUTHORIZED,
    )
    assert scored.verdict is not Verdict.PASS


# MARK: - Brand access


def test_a_restricted_brand_is_demoted_not_hidden():
    """Worth knowing about when deciding which gating application to file."""
    scored = score_channel(
        economics=_economics("50.00", "15.00"),
        demand=_demand(150.0),
        stability=STABLE,
        seller_count=2,
        thresholds=Thresholds(),
        minimum_buy_units=24,
        brand_status=BRAND_RESTRICTED,
    )
    assert scored.verdict is not Verdict.PASS
    # Still scored — the economics are computed and carried, not discarded.
    assert scored.economics.net_profit > 0


def test_an_unknown_brand_is_flagged_but_still_scoreable():
    scored = score_channel(
        economics=_economics("50.00", "15.00"),
        demand=_demand(150.0),
        stability=STABLE,
        seller_count=2,
        thresholds=Thresholds(),
        minimum_buy_units=24,
        brand_status=BRAND_UNKNOWN,
    )
    assert scored.verdict in (Verdict.PASS, Verdict.WATCH)


# MARK: - Unit share


def test_listing_wide_demand_is_divided_among_sellers():
    """Five sellers on a 300/month item is 50 each; the `+1` is you."""
    scored = score_channel(
        economics=_economics("50.00", "15.00"),
        demand=_demand(300.0, DemandConfidence.RANK),
        stability=STABLE,
        seller_count=5,
        thresholds=Thresholds(),
        minimum_buy_units=24,
        brand_status=BRAND_AUTHORIZED,
    )
    assert scored.unit_share == pytest.approx(50.0, abs=0.1)


def test_observed_depletion_is_not_divided_again():
    """It's already the per-offer number — dividing understates by ~5x."""
    scored = score_channel(
        economics=_economics("50.00", "15.00"),
        demand=_demand(300.0, DemandConfidence.OBSERVED),
        stability=STABLE,
        seller_count=5,
        thresholds=Thresholds(),
        minimum_buy_units=24,
        brand_status=BRAND_AUTHORIZED,
    )
    assert scored.unit_share == pytest.approx(300.0, abs=0.1)


# MARK: - The velocity/margin slider


def test_blend_score_endpoints_are_pure_margin_and_pure_velocity():
    assert blend_score(velocity_norm=1.0, margin_norm=0.0, velocity_bias=1.0) == pytest.approx(1.0)
    assert blend_score(velocity_norm=0.0, margin_norm=1.0, velocity_bias=0.0) == pytest.approx(1.0)


def test_blend_score_is_continuous_between_the_endpoints():
    """A slider, not a mode switch."""
    mid = blend_score(velocity_norm=1.0, margin_norm=0.0, velocity_bias=0.5)
    assert 0.0 < mid < 1.0


def test_blend_score_moves_monotonically_with_the_bias():
    scores = [
        blend_score(velocity_norm=1.0, margin_norm=0.0, velocity_bias=b)
        for b in (0.0, 0.25, 0.5, 0.75, 1.0)
    ]
    assert scores == sorted(scores)
