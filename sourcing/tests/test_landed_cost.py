"""Landed-cost tests.

The load-bearing idea in this module is that **reserves divide, they don't add**.
You don't pay shrink and returns per unit — you lose that fraction of units, and
the survivors carry the cost of all of them. Getting that wrong understates cost
by a small amount that compounds exactly where margins are thinnest.

The second idea is that uplift is *uneven*: a heavy item absorbs far more freight
per unit than a light one at the same invoice price, so costing properly doesn't
shift the ranking uniformly — it reorders it.
"""

from __future__ import annotations

from decimal import Decimal

from m15_sourcing.landed_cost import (
    ALLOCATION_BY_WEIGHT,
    CostProfile,
    LandedCost,
    allocate_shipment_cost,
    build_landed_cost,
)


# MARK: - Reserves divide


def test_reserves_divide_rather_than_add():
    """3% shrink + 5% returns costs more than the 8% an additive model implies.

    The reserves *compound*: shrink removes units in transit, and the return
    rate then applies to what actually sold. Survival is 0.97 x 0.95 = 0.9215,
    so 100 / 0.9215 = $108.52 — an 8.52% increase, not 8%.

    NOTE — README drift: `sourcing/README.md` §6b works this same example as
    "92 units carry the cost of 100: an 8.7% cost increase". That reads survival
    additively (100 - 3 - 5 = 92) and yields 100/0.92 = $108.70. The code's
    compounding model is the more defensible of the two and is what ships; the
    README's worked number is stale by 18 cents on a $100 item. Asserted here
    against the implementation so the discrepancy is recorded rather than
    rediscovered.
    """
    cost = LandedCost(
        invoice_cost=Decimal("100.00"),
        shrink_rate=Decimal("0.03"),
        return_rate=Decimal("0.05"),
    )
    assert cost.survival_rate == Decimal("0.9215")
    assert cost.total == Decimal("108.52")
    # The point that actually matters: dividing beats adding. A model that
    # treated reserves as an 8% fee would have produced exactly $108.00.
    assert cost.total > Decimal("108.00")


def test_survival_rate_is_multiplicative_not_additive():
    cost = LandedCost(
        invoice_cost=Decimal("10.00"),
        shrink_rate=Decimal("0.10"),
        return_rate=Decimal("0.10"),
    )
    # 0.9 x 0.9 = 0.81, not 1 - 0.20 = 0.80.
    assert cost.survival_rate == Decimal("0.81")


def test_survival_rate_is_floored_so_total_cost_stays_finite():
    """A nonsense 100% shrink rate must not divide by zero."""
    cost = LandedCost(invoice_cost=Decimal("10.00"), shrink_rate=Decimal("1.0"))
    assert cost.survival_rate == Decimal("0.01")
    assert cost.total == Decimal("1000.00")


def test_no_reserves_means_cost_equals_the_direct_stack():
    cost = LandedCost(invoice_cost=Decimal("10.00"))
    assert cost.total == Decimal("10.00")
    assert cost.uplift_pct == Decimal("0")


# MARK: - The cost stack


def test_per_case_costs_are_divided_down_by_case_pack():
    cost = LandedCost(
        invoice_cost=Decimal("10.00"), per_case_cost=Decimal("24.00"), case_pack=12
    )
    assert cost.case_allocated_per_unit == Decimal("2.00")
    assert cost.total == Decimal("12.00")


def test_per_case_cost_without_a_pack_size_contributes_nothing():
    """Better to leave it out than to divide by a guess."""
    cost = LandedCost(invoice_cost=Decimal("10.00"), per_case_cost=Decimal("24.00"))
    assert cost.case_allocated_per_unit == Decimal("0")


def test_rate_adders_apply_to_the_goods_value():
    cost = LandedCost(
        invoice_cost=Decimal("100.00"),
        duty_rate=Decimal("0.05"),
        payment_fee_rate=Decimal("0.03"),
    )
    assert cost.rate_adders == Decimal("8.00")
    assert cost.total == Decimal("108.00")


def test_direct_adders_sum_every_per_unit_component():
    cost = LandedCost(
        invoice_cost=Decimal("10.00"),
        inbound_freight_per_unit=Decimal("1.00"),
        prep_per_unit=Decimal("0.50"),
        packaging_per_unit=Decimal("0.25"),
        inspection_per_unit=Decimal("0.15"),
        other_per_unit=Decimal("0.10"),
    )
    assert cost.direct_adders == Decimal("2.00")
    assert cost.total == Decimal("12.00")


def test_uplift_is_reported_against_the_invoice_price():
    cost = LandedCost(invoice_cost=Decimal("10.00"), inbound_freight_per_unit=Decimal("2.00"))
    assert cost.uplift_pct == Decimal("20.00")


def test_uplift_on_a_free_item_does_not_divide_by_zero():
    cost = LandedCost(invoice_cost=Decimal("0"), inbound_freight_per_unit=Decimal("2.00"))
    assert cost.uplift_pct == Decimal("0")


# MARK: - Uplift is uneven, which is why it reorders the list


def test_weight_based_freight_penalizes_the_heavy_item_at_equal_invoice_cost():
    """The air purifier and the phone case do not absorb the same freight.

    This is the whole reason landed cost changes the *order* of a ranked list
    rather than shifting every row by a constant.
    """
    profile = CostProfile(inbound_freight_per_lb=Decimal("0.45"))
    heavy = build_landed_cost(
        invoice_cost=Decimal("40.00"), profile=profile, weight_lb=Decimal("14")
    )
    light = build_landed_cost(
        invoice_cost=Decimal("40.00"), profile=profile, weight_lb=Decimal("0.25")
    )
    assert heavy.total > light.total
    assert heavy.uplift_pct > light.uplift_pct


# MARK: - Assumptions are recorded, never invented


def test_unspecified_components_are_flagged_not_guessed():
    cost = build_landed_cost(invoice_cost=Decimal("10.00"), profile=CostProfile())
    assert "no_inbound_freight" in cost.assumptions
    assert "no_prep_or_packaging" in cost.assumptions
    assert not cost.is_fully_specified


def test_a_fully_specified_profile_carries_no_assumptions():
    profile = CostProfile(
        inbound_freight_per_unit=Decimal("1.00"),
        prep_per_unit=Decimal("0.50"),
        packaging_per_unit=Decimal("0.25"),
    )
    cost = build_landed_cost(
        invoice_cost=Decimal("10.00"), profile=profile, weight_lb=Decimal("2")
    )
    assert cost.is_fully_specified
    assert cost.assumptions == ()


def test_zero_return_reserve_is_itself_flagged():
    """Choosing not to reserve is a decision, and it shows up as one."""
    profile = CostProfile(
        inbound_freight_per_unit=Decimal("1.00"),
        prep_per_unit=Decimal("0.50"),
        return_rate=Decimal("0"),
    )
    cost = build_landed_cost(
        invoice_cost=Decimal("10.00"), profile=profile, weight_lb=Decimal("1")
    )
    assert "no_return_reserve" in cost.assumptions


def test_default_profile_reserves_returns_at_three_percent():
    """Deliberately above the measured rate — cheap insurance in a go/no-go tool."""
    assert CostProfile().return_rate == Decimal("0.03")


# MARK: - Freight resolution order


def test_explicit_override_beats_the_profile():
    profile = CostProfile(inbound_freight_per_lb=Decimal("1.00"))
    cost = build_landed_cost(
        invoice_cost=Decimal("10.00"),
        profile=profile,
        weight_lb=Decimal("5"),
        overrides={"inbound_freight_per_unit": "0.25"},
    )
    assert cost.inbound_freight_per_unit == Decimal("0.25")


def test_weight_based_freight_beats_the_flat_rate_when_a_weight_exists():
    profile = CostProfile(
        inbound_freight_per_lb=Decimal("0.50"), inbound_freight_per_unit=Decimal("9.99")
    )
    cost = build_landed_cost(
        invoice_cost=Decimal("10.00"), profile=profile, weight_lb=Decimal("4")
    )
    assert cost.inbound_freight_per_unit == Decimal("2.00")


def test_flat_rate_without_a_weight_is_flagged():
    profile = CostProfile(inbound_freight_per_unit=Decimal("1.50"))
    cost = build_landed_cost(invoice_cost=Decimal("10.00"), profile=profile)
    assert cost.inbound_freight_per_unit == Decimal("1.50")
    assert "freight_flat_rate_no_weight" in cost.assumptions


# MARK: - Shipment allocation


def test_per_unit_allocation_splits_evenly():
    assert allocate_shipment_cost(Decimal("120.00"), units=60) == Decimal("2.00")


def test_weight_allocation_matches_how_the_carrier_billed_it():
    """A 14 lb portion of a 700 lb shipment absorbs 2% of the freight."""
    per_unit = allocate_shipment_cost(
        Decimal("1000.00"),
        units=10,
        basis=ALLOCATION_BY_WEIGHT,
        this_measure=Decimal("14"),
        total_measure=Decimal("700"),
    )
    assert per_unit == Decimal("2.00")  # 1000 x (14/700) = 20, over 10 units


def test_weight_allocation_falls_back_to_even_split_without_measures():
    """A rough allocation beats leaving freight out entirely."""
    per_unit = allocate_shipment_cost(
        Decimal("100.00"), units=10, basis=ALLOCATION_BY_WEIGHT
    )
    assert per_unit == Decimal("10.00")


def test_allocation_over_zero_units_is_zero_not_an_error():
    assert allocate_shipment_cost(Decimal("100.00"), units=0) == Decimal("0")


# MARK: - Profile round-tripping


def test_profile_from_dict_ignores_junk_values():
    profile = CostProfile.from_dict(
        {"shrink_rate": "0.02", "duty_rate": "not-a-number", "prep_per_unit": None}
    )
    assert profile.shrink_rate == Decimal("0.02")
    assert profile.duty_rate == Decimal("0")
    assert profile.prep_per_unit == Decimal("0")


def test_profile_from_empty_dict_is_the_default():
    assert CostProfile.from_dict(None) == CostProfile()
    assert CostProfile.from_dict({}) == CostProfile()
