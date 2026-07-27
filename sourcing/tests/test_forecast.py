"""Projected-vs-actual calibration tests.

Every demand tier has an error profile, and the loop that measures it can very
easily learn the wrong lesson. Three guards keep it honest, and each has a test
here:

  * corrections are **reported below 5 paired samples but not applied**;
  * factors are **clamped to 0.25x-4x** — anything outside that almost always
    means a mis-paired SKU, not a real bias;
  * **medians, not means**, so one viral week can't reset the model.

The fourth idea is separation of blame: ``net_per_unit`` bias is tracked apart
from demand bias, because running below 1.0 there means the *fee and cost* model
is optimistic — a ``recon.py`` problem, not a demand one.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from m15_sourcing.forecast import (
    MIN_SAMPLES_TO_APPLY,
    Actual,
    BiasEstimate,
    DemandCalibration,
    Forecast,
    accuracy_summary,
    pair,
)

T0 = datetime(2026, 6, 1, tzinfo=UTC)


def _forecast(sku: str, units: float, net: str = "5.00", tier: str = "rank", category=None):
    return Forecast(
        sku=sku,
        channel="walmart",
        predicted_at=T0,
        predicted_monthly_units=units,
        predicted_net_per_unit=Decimal(net),
        signal_tier=tier,
        category=category,
    )


def _actual(sku: str, units: int, proceeds: str = "5.00", days: int = 30):
    return Actual(
        sku=sku,
        channel="walmart",
        window_start=T0,
        window_end=T0 + timedelta(days=days),
        units_sold=units,
        net_proceeds=Decimal(proceeds) * units,
    )


# MARK: - Normalizing the window


def test_a_ninety_day_actual_is_normalized_to_a_month():
    """Otherwise a quarterly export looks like a 3x demand beat."""
    quarterly = _actual("A", units=90, days=90)
    assert quarterly.actual_monthly_units == pytest.approx(30.0, abs=0.1)


def test_net_per_unit_divides_proceeds_by_units():
    actual = _actual("A", units=10, proceeds="4.50")
    assert actual.actual_net_per_unit == Decimal("4.50")


def test_net_per_unit_on_zero_sales_does_not_divide_by_zero():
    actual = Actual(
        sku="A",
        channel="walmart",
        window_start=T0,
        window_end=T0 + timedelta(days=30),
        units_sold=0,
        net_proceeds=Decimal("0"),
    )
    assert actual.actual_net_per_unit == Decimal("0")


def test_a_zero_length_window_is_floored_at_a_day():
    actual = Actual(
        sku="A",
        channel="walmart",
        window_start=T0,
        window_end=T0,
        units_sold=5,
        net_proceeds=Decimal("25"),
    )
    assert actual.window_days == 1.0


# MARK: - Pairing


def test_forecasts_pair_to_actuals_on_sku_and_channel():
    comparisons = pair([_forecast("A", 100.0)], [_actual("A", 90)])
    assert len(comparisons) == 1
    assert comparisons[0].sku == "A"


def test_an_unmatched_forecast_produces_no_comparison():
    """Rows that were never bought have no actual — recording them adds noise."""
    assert pair([_forecast("A", 100.0)], [_actual("B", 90)]) == []


def test_ratio_reads_above_one_when_we_under_predicted():
    comparison = pair([_forecast("A", 100.0)], [_actual("A", 150)])[0]
    assert comparison.units_ratio == pytest.approx(1.5, abs=0.01)


def test_error_percentage_is_unsigned():
    over = pair([_forecast("A", 100.0)], [_actual("A", 150)])[0]
    under = pair([_forecast("B", 100.0)], [_actual("B", 50)])[0]
    assert over.units_error_pct == pytest.approx(50.0, abs=0.1)
    assert under.units_error_pct == pytest.approx(50.0, abs=0.1)


def test_a_zero_prediction_yields_no_ratio():
    comparison = pair([_forecast("A", 0.0)], [_actual("A", 50)])[0]
    assert comparison.units_ratio is None
    assert comparison.units_error_pct is None


# MARK: - Guard 1: below the sample floor, report but don't apply


def test_a_correction_is_not_applied_below_the_sample_floor():
    bias = BiasEstimate()
    for _ in range(MIN_SAMPLES_TO_APPLY - 1):
        bias.add(ratio=2.0, error_pct=100.0)

    assert bias.samples < MIN_SAMPLES_TO_APPLY
    assert not bias.is_applicable
    # Reported...
    assert bias.median_ratio == 2.0
    # ...but not applied.
    assert bias.correction == 1.0


def test_a_correction_applies_once_there_are_enough_samples():
    bias = BiasEstimate()
    for _ in range(MIN_SAMPLES_TO_APPLY):
        bias.add(ratio=2.0, error_pct=100.0)

    assert bias.is_applicable
    assert bias.correction == 2.0


def test_an_uncalibrated_tier_is_a_no_op_multiplier():
    calibration = DemandCalibration()
    units, basis = calibration.apply(100.0, "rank")
    assert units == 100.0
    assert basis == "uncalibrated"


# MARK: - Guard 2: clamp


@pytest.mark.parametrize(
    ("ratio", "expected"),
    [
        (10.0, 4.0),    # clamped down
        (0.01, 0.25),   # clamped up
        (2.0, 2.0),     # inside the band, untouched
    ],
)
def test_corrections_are_clamped_to_a_plausible_band(ratio, expected):
    """Outside 0.25x-4x almost always means a mis-paired SKU, not a real bias."""
    bias = BiasEstimate()
    for _ in range(MIN_SAMPLES_TO_APPLY):
        bias.add(ratio=ratio, error_pct=0.0)
    assert bias.correction == expected


# MARK: - Guard 3: median, not mean


def test_one_viral_week_cannot_reset_the_model():
    """A single 100x outlier would drag a mean; the median ignores it."""
    bias = BiasEstimate()
    for _ in range(5):
        bias.add(ratio=1.0, error_pct=0.0)
    bias.add(ratio=100.0, error_pct=9900.0)

    assert bias.median_ratio == pytest.approx(1.0, abs=0.01)
    assert bias.correction == pytest.approx(1.0, abs=0.01)


def test_non_positive_ratios_are_not_recorded():
    bias = BiasEstimate()
    bias.add(ratio=0.0, error_pct=10.0)
    bias.add(ratio=None, error_pct=10.0)
    assert bias.samples == 0


# MARK: - Specificity


def test_the_more_specific_key_wins_when_it_has_enough_samples():
    """BSR bias is genuinely category-dependent — that's why the curves are too."""
    comparisons = [
        pair([_forecast(f"A{i}", 100.0, tier="rank", category="Pet Supplies")],
             [_actual(f"A{i}", 200)])[0]
        for i in range(MIN_SAMPLES_TO_APPLY)
    ] + [
        pair([_forecast(f"B{i}", 100.0, tier="rank", category="Tools")],
             [_actual(f"B{i}", 50)])[0]
        for i in range(MIN_SAMPLES_TO_APPLY)
    ]
    calibration = DemandCalibration().ingest(comparisons)

    pet, pet_basis = calibration.correction_for("rank", "Pet Supplies")
    tools, tools_basis = calibration.correction_for("rank", "Tools")

    assert pet == pytest.approx(2.0, abs=0.01)
    assert tools == pytest.approx(0.5, abs=0.01)
    assert "tier+category" in pet_basis
    assert "tier+category" in tools_basis


def test_an_uncategorized_estimate_falls_back_to_the_tier_level():
    comparisons = [
        pair([_forecast(f"A{i}", 100.0, tier="velocity", category="Pet Supplies")],
             [_actual(f"A{i}", 200)])[0]
        for i in range(MIN_SAMPLES_TO_APPLY)
    ]
    calibration = DemandCalibration().ingest(comparisons)
    _, basis = calibration.correction_for("velocity", "A Category Never Seen")
    assert basis.startswith("tier_n")


def test_category_keys_are_normalized():
    comparisons = [
        pair([_forecast(f"A{i}", 100.0, tier="rank", category="  Pet   Supplies ")],
             [_actual(f"A{i}", 200)])[0]
        for i in range(MIN_SAMPLES_TO_APPLY)
    ]
    calibration = DemandCalibration().ingest(comparisons)
    factor, basis = calibration.correction_for("rank", "pet supplies")
    assert "tier+category" in basis
    assert factor == pytest.approx(2.0, abs=0.01)


# MARK: - Separation of blame


def test_net_bias_is_tracked_apart_from_demand_bias():
    """Below 1.0 here means the fee/cost model is optimistic, not the demand one."""
    comparisons = [
        pair([_forecast(f"A{i}", 100.0, net="5.00")], [_actual(f"A{i}", 100, proceeds="4.00")])[0]
        for i in range(MIN_SAMPLES_TO_APPLY)
    ]
    calibration = DemandCalibration().ingest(comparisons)
    report = calibration.report()

    assert report["net_per_unit_bias"]["median_ratio"] == pytest.approx(0.8, abs=0.01)
    # Demand was predicted perfectly; only the money was wrong.
    assert calibration.by_tier["rank"].median_ratio == pytest.approx(1.0, abs=0.01)


# MARK: - Scoreboard


def test_accuracy_summary_reports_the_honest_headline():
    comparisons = [
        pair([_forecast(f"A{i}", 100.0)], [_actual(f"A{i}", units)])[0]
        for i, units in enumerate([100, 110, 90, 200, 40])
    ]
    summary = accuracy_summary(comparisons)
    assert summary["comparisons"] == 5
    assert "within_25_pct" in summary


def test_accuracy_summary_of_nothing_does_not_divide_by_zero():
    summary = accuracy_summary([])
    assert summary["comparisons"] == 0
