"""Selling-plan tests.

The rule this module exists to enforce: a monthly subscription is a **fixed**
cost, and amortizing it into per-unit margin is wrong in both directions. If you
already pay it, it's sunk for the next SKU decision; if you don't, it's a
threshold question with a volume answer.

So plans do exactly two things and never mix them — contribute genuinely
marginal rates to the fee engine, and report a breakeven volume separately.
"""

from __future__ import annotations

from decimal import Decimal

from m15_sourcing.plans import (
    AMAZON_PLANS,
    PLAN_SCHEDULE_VERSION,
    SellingPlan,
    effective_fee_rate,
    get_plan,
    per_unit_plan_fee,
    plan_breakeven,
    recommend_plan,
)


# MARK: - Marginal rates


def test_store_discount_subtracts_percentage_points_from_the_base_rate():
    """0.9pp off 13.6% is 12.7% — points, not a multiplier."""
    basic = get_plan("ebay", "basic")
    assert effective_fee_rate(Decimal("0.136"), basic) == Decimal("0.127")


def test_fee_rate_is_floored_at_zero():
    """A discount larger than the base rate would manufacture profit."""
    absurd = SellingPlan(channel="ebay", key="x", display_name="X", fvf_discount=Decimal("0.5"))
    assert effective_fee_rate(Decimal("0.136"), absurd) == Decimal("0")


def test_no_store_means_no_discount():
    assert effective_fee_rate(Decimal("0.136"), get_plan("ebay", "none")) == Decimal("0.136")


def test_amazon_individual_per_item_fee_is_genuinely_marginal():
    """$0.99 per item *sold* belongs in the fee engine; the monthly fee doesn't."""
    individual = get_plan("amazon", "individual")
    assert per_unit_plan_fee(individual) == Decimal("0.99")
    assert individual.monthly_fee == Decimal("0")


def test_amazon_professional_swaps_the_per_item_fee_for_a_fixed_one():
    professional = get_plan("amazon", "professional")
    assert per_unit_plan_fee(professional) == Decimal("0")
    assert professional.monthly_fee == Decimal("39.99")


def test_walmart_has_no_plan_fees_at_all():
    """Modelled explicitly rather than omitted, so the lookup is total."""
    walmart = get_plan("walmart")
    assert walmart.monthly_fee == Decimal("0")
    assert walmart.per_item_fee == Decimal("0")
    assert walmart.fvf_discount == Decimal("0")


# MARK: - Breakeven volume


def test_amazon_crossover_lands_on_the_well_known_forty_units():
    """$39.99 / $0.99 = ~40 units/month.

    The number is famous, but it's *derived* from the two fee structures rather
    than written down — so it moves on its own when Amazon changes either.
    """
    breakeven = plan_breakeven("amazon", "individual", "professional")
    assert breakeven.breakeven_units is not None
    assert round(breakeven.breakeven_units) == 40


def test_crossover_moves_when_the_underlying_fees_move():
    """Proves it's computed, not hardcoded."""
    original = AMAZON_PLANS["professional"]
    try:
        AMAZON_PLANS["professional"] = SellingPlan(
            channel="amazon",
            key="professional",
            display_name="Professional",
            monthly_fee=Decimal("79.98"),  # doubled
        )
        doubled = plan_breakeven("amazon", "individual", "professional")
        assert round(doubled.breakeven_units) == 81  # 79.98 / 0.99
    finally:
        AMAZON_PLANS["professional"] = original


def test_percentage_discount_plans_break_even_on_gmv_not_units():
    """An eBay Store's benefit is a rate cut, so the answer is a sales volume."""
    breakeven = plan_breakeven("ebay", "none", "basic")
    assert breakeven.breakeven_gmv is not None
    # $21.95 monthly / 0.9pp = ~$2,439 of monthly sales.
    assert breakeven.breakeven_gmv == Decimal("2438.89")


def test_gmv_breakeven_can_be_restated_in_units():
    """The form people actually reason in."""
    breakeven = plan_breakeven("ebay", "none", "basic", avg_sale_price=Decimal("25.00"))
    assert "units at $25.00" in breakeven.note


def test_a_free_upgrade_breaks_even_immediately():
    breakeven = plan_breakeven("ebay", "basic", "none")
    assert breakeven.monthly_fee_delta < 0
    assert breakeven.breakeven_units == 0.0
    assert "free or cheaper" in breakeven.note


def test_an_upgrade_with_no_marginal_saving_says_so():
    """Starter buys listings, not a fee cut — there's no volume that repays it."""
    breakeven = plan_breakeven("ebay", "none", "starter")
    assert breakeven.breakeven_units is None
    assert breakeven.breakeven_gmv is None
    assert "listings or features" in breakeven.note


def test_breakeven_is_reported_never_folded_into_a_row():
    """The dataclass carries fixed-cost facts only — no per-unit field."""
    breakeven = plan_breakeven("amazon", "individual", "professional")
    assert not hasattr(breakeven, "per_unit_cost")
    assert breakeven.monthly_fee_delta == Decimal("39.99")


# MARK: - Recommendation


def test_low_volume_seller_stays_on_the_free_plan():
    plan, _ = recommend_plan("amazon", monthly_units=10, avg_sale_price=Decimal("20.00"))
    assert plan.key == "individual"


def test_high_volume_seller_is_moved_to_the_subscription():
    plan, _ = recommend_plan("amazon", monthly_units=500, avg_sale_price=Decimal("20.00"))
    assert plan.key == "professional"


def test_recommendation_flips_at_the_crossover():
    below, _ = recommend_plan("amazon", monthly_units=39, avg_sale_price=Decimal("20.00"))
    above, _ = recommend_plan("amazon", monthly_units=41, avg_sale_price=Decimal("20.00"))
    assert below.key == "individual"
    assert above.key == "professional"


def test_recommendation_returns_the_comparisons_it_used():
    _, comparisons = recommend_plan(
        "ebay", monthly_units=100, avg_sale_price=Decimal("30.00")
    )
    assert comparisons
    assert all(c.from_plan == "none" for c in comparisons)


def test_unknown_channel_degrades_gracefully():
    plan, comparisons = recommend_plan(
        "etsy", monthly_units=100, avg_sale_price=Decimal("30.00")
    )
    assert plan is not None
    assert comparisons == []


# MARK: - Lookup


def test_get_plan_falls_back_to_the_channel_default():
    assert get_plan("ebay").key == "none"
    assert get_plan("amazon").key == "individual"
    assert get_plan("walmart").key == "standard"


def test_get_plan_with_an_unknown_key_does_not_raise():
    assert get_plan("ebay", "platinum-deluxe") is not None


def test_plan_schedule_is_versioned():
    assert PLAN_SCHEDULE_VERSION
