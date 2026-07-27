"""Fee-engine tests, anchored on the real settlement figures that calibrated it.

The tests that matter most here are the ones reproducing an actual order to the
cent. Every one of those numbers is cited in ``fees.py``'s comments, and each
represents an error the published rate cards would have caused:

  * eBay charges its percentage on a **tax-inclusive** base.
  * eBay's per-order fixed fee is tiered on **order total**, not item price.
  * Walmart's commission **excludes** tax — the opposite asymmetry.
  * WFS prices sub-$10 items on a flat schedule, not by weight.

A rate table drifting is expected and fine; these tests exist so that the
*shape* of the calculation can't silently change underneath it.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from m15_sourcing.fees import (
    EBAY_ASSUMED_SALES_TAX_RATE,
    EBAY_PER_ORDER_FEE,
    EBAY_PER_ORDER_FEE_LOW,
    FEE_SCHEDULE_VERSION,
    WALMART_REFERRAL_RATES,
    ItemDimensions,
    ebay_economics,
    ebay_final_value_fee,
    ebay_per_order_fee,
    ebay_shipping_estimate,
    resolve_category,
    walmart_economics,
    walmart_referral_rate,
    wfs_fulfillment_fee,
    wfs_storage_fee,
)

# ── The settlement sample ────────────────────────────────────────────
# One real eBay order, quoted from the fee-detail screen:
#     item $26.50 + shipping $0.00 + sales tax $1.86 = $28.36 base
#     $28.36 x 13.6% = $3.86 variable, + $0.40 fixed  = $4.26 total
#     promoted-listings ad fee $2.55 = exactly 9.0% of the same $28.36
SAMPLE_ITEM = Decimal("26.50")
SAMPLE_TAX = Decimal("1.86")
SAMPLE_BASE = Decimal("28.36")


# MARK: - eBay: the tax-inclusive base


def test_ebay_fvf_reproduces_the_real_order_to_the_cent():
    fee = ebay_final_value_fee(SAMPLE_ITEM, Decimal("0"), None, sales_tax=SAMPLE_TAX)
    assert fee == Decimal("4.26")


def test_ebay_fvf_is_charged_on_tax_not_item_price():
    """The specific error the settlement caught: a ~7%-of-fee understatement."""
    with_tax = ebay_final_value_fee(SAMPLE_ITEM, Decimal("0"), None, sales_tax=SAMPLE_TAX)
    without_tax = ebay_final_value_fee(SAMPLE_ITEM, Decimal("0"), None, sales_tax=Decimal("0"))
    assert with_tax == Decimal("4.26")
    assert without_tax == Decimal("4.00")
    # Getting this wrong doesn't just shift the fee, it shifts it in the
    # optimistic direction — which is the direction that promotes a bad row.
    assert with_tax > without_tax


def test_assumed_tax_rate_reproduces_the_observed_tax():
    """7.0% is not a round guess — it matched the sample order to the cent."""
    assert EBAY_ASSUMED_SALES_TAX_RATE == Decimal("0.07")
    implied = (SAMPLE_ITEM * EBAY_ASSUMED_SALES_TAX_RATE).quantize(Decimal("0.01"))
    assert implied == SAMPLE_TAX


def test_ebay_fvf_defaults_to_estimated_tax_when_none_supplied():
    """Scoring happens before a buyer exists, so the tax leg must self-supply."""
    supplied = ebay_final_value_fee(SAMPLE_ITEM, Decimal("0"), None, sales_tax=SAMPLE_TAX)
    estimated = ebay_final_value_fee(SAMPLE_ITEM, Decimal("0"), None)
    assert estimated == supplied


def test_buyer_paid_shipping_is_in_the_fee_base():
    """Free shipping doesn't dodge the fee — it just moves where the money sits."""
    no_ship = ebay_final_value_fee(Decimal("20.00"), Decimal("0"), sales_tax=Decimal("0"))
    with_ship = ebay_final_value_fee(Decimal("20.00"), Decimal("6.00"), sales_tax=Decimal("0"))
    assert with_ship - no_ship == (Decimal("6.00") * Decimal("0.136")).quantize(Decimal("0.01"))


# MARK: - eBay: the tiered per-order fee


@pytest.mark.parametrize(
    ("order_total", "expected"),
    [
        (Decimal("5.00"), EBAY_PER_ORDER_FEE_LOW),
        (Decimal("9.99"), EBAY_PER_ORDER_FEE_LOW),
        # The threshold is exclusive: the fee screen reads "Order total $10.01+".
        (Decimal("10.00"), EBAY_PER_ORDER_FEE_LOW),
        (Decimal("10.01"), EBAY_PER_ORDER_FEE),
        (Decimal("500.00"), EBAY_PER_ORDER_FEE),
    ],
)
def test_per_order_fee_tiers_on_order_total(order_total, expected):
    assert ebay_per_order_fee(order_total) == expected


def test_per_order_threshold_keys_off_total_not_item_price():
    """A $9.50 item whose tax pushes the order over $10 still pays the high fee.

    This is why the threshold takes ``order_total`` rather than ``sale_price``
    — an item priced just under the line can land either side of it depending
    on the buyer's tax rate.
    """
    item = Decimal("9.50")
    tax = Decimal("0.67")  # ~7%, pushes the total to $10.17
    assert item < Decimal("10.00")
    assert ebay_per_order_fee(item + tax) == EBAY_PER_ORDER_FEE


# MARK: - eBay: promoted listings share the FVF base


def test_ad_fee_uses_the_same_tax_inclusive_base_as_the_fvf():
    """$2.55 / $28.36 = exactly the 9.0% ad rate the seller set.

    Computing it on the item price alone would imply a nonsense 9.62%, which is
    how the base was identified as tax-inclusive in the first place.
    """
    econ = ebay_economics(
        sale_price=SAMPLE_ITEM,
        unit_cost=Decimal("12.00"),
        ad_rate=Decimal("0.09"),
        seller_shipping_cost=Decimal("0"),
    )
    assert econ.fees.ad_fee == Decimal("2.55")
    # Same $2.55 read back as a rate on each candidate base.
    assert (econ.fees.ad_fee / SAMPLE_BASE).quantize(Decimal("0.0001")) == Decimal("0.0899")
    assert (econ.fees.ad_fee / SAMPLE_ITEM).quantize(Decimal("0.0001")) == Decimal("0.0962")


def test_no_ad_fee_when_ad_rate_is_zero():
    econ = ebay_economics(
        sale_price=SAMPLE_ITEM, unit_cost=Decimal("12.00"), seller_shipping_cost=Decimal("0")
    )
    assert econ.fees.ad_fee == Decimal("0")


# MARK: - eBay economics wiring


def test_ebay_economics_splits_fixed_and_variable_the_way_a_statement_reads():
    econ = ebay_economics(
        sale_price=SAMPLE_ITEM, unit_cost=Decimal("12.00"), seller_shipping_cost=Decimal("0")
    )
    assert econ.fees.per_order_fee == EBAY_PER_ORDER_FEE
    assert econ.fees.referral_fee == Decimal("3.86")
    assert econ.fees.referral_fee + econ.fees.per_order_fee == Decimal("4.26")


def test_ebay_revenue_includes_buyer_paid_shipping():
    """A $10 item with $6 shipping is the same trade as a $16 item shipped free."""
    econ = ebay_economics(
        sale_price=Decimal("10.00"),
        unit_cost=Decimal("4.00"),
        shipping_charged=Decimal("6.00"),
        seller_shipping_cost=Decimal("5.00"),
    )
    assert econ.sale_price == Decimal("16.00")


def test_ebay_flags_that_the_tax_leg_was_estimated():
    econ = ebay_economics(
        sale_price=SAMPLE_ITEM, unit_cost=Decimal("12.00"), seller_shipping_cost=Decimal("0")
    )
    assert "fvf_charged_on_estimated_sales_tax" in econ.assumptions


# MARK: - Walmart: commission EXCLUDES tax


def test_walmart_commission_excludes_sales_tax():
    """The mirror image of eBay, from a reconciliation report.

    $8.99 item in Automotive & Powersports charged $1.08 = 12.00% of $8.99
    exactly. The $0.69 tax was collected and withheld as a pass-through and
    never entered the base.
    """
    econ = walmart_economics(
        sale_price=Decimal("8.99"),
        unit_cost=Decimal("4.00"),
        category="automotive_powersports",
        use_wfs=False,
        seller_shipping_cost=Decimal("0"),
    )
    assert econ.fees.referral_fee == Decimal("1.08")
    # Had tax been folded in the way eBay does it, the fee would be higher.
    tax_inclusive = ((Decimal("8.99") + Decimal("0.69")) * Decimal("0.12")).quantize(
        Decimal("0.01")
    )
    assert tax_inclusive == Decimal("1.16")
    assert econ.fees.referral_fee < tax_inclusive


@pytest.mark.parametrize(
    ("raw_category", "expected_key"),
    [
        # Walmart's own two reports spell this differently for the same item.
        ("Automotive & Powersports", "automotive_powersports"),
        ("Vehicles, Parts & Accessories", "automotive_powersports"),
        ("Home & Garden", "home_garden"),
        ("Tools & Home Improvement", "tools_home_improvement"),
    ],
)
def test_category_resolution_matches_the_validated_samples(raw_category, expected_key):
    assert resolve_category(raw_category) == expected_key


@pytest.mark.parametrize(
    ("category", "expected_rate"),
    [
        # Validated across 28 samples in three categories.
        ("home_garden", Decimal("0.15")),
        ("tools_home_improvement", Decimal("0.15")),
        ("automotive_powersports", Decimal("0.12")),
    ],
)
def test_referral_rates_match_published_to_the_basis_point(category, expected_rate):
    assert walmart_referral_rate(category, Decimal("25.00")) == expected_rate


def test_both_automotive_spellings_resolve_to_one_rate():
    """If the spellings split, each half of the calibration looks under-sampled."""
    a = walmart_referral_rate(resolve_category("Automotive & Powersports"), Decimal("8.99"))
    b = walmart_referral_rate(resolve_category("Vehicles, Parts & Accessories"), Decimal("8.99"))
    assert a == b == Decimal("0.12")


def test_unknown_category_falls_to_the_pessimistic_default():
    """15% by default — fee optimism is the expensive kind of wrong."""
    assert resolve_category("Blorptech Widgets") == "default"
    assert resolve_category(None) == "default"
    assert walmart_referral_rate("Blorptech Widgets", Decimal("25.00")) == Decimal("0.15")


def test_unknown_category_is_flagged_in_assumptions():
    econ = walmart_economics(
        sale_price=Decimal("25.00"),
        unit_cost=Decimal("10.00"),
        category="Blorptech Widgets",
        use_wfs=False,
        seller_shipping_cost=Decimal("0"),
    )
    assert "default_referral_rate" in econ.assumptions


def test_price_break_categories_pick_the_bucket_by_sale_price():
    """Beauty is 8% at or below $10 and 15% above — the break must be honoured."""
    assert walmart_referral_rate("beauty", Decimal("9.99")) == Decimal("0.08")
    assert walmart_referral_rate("beauty", Decimal("10.00")) == Decimal("0.08")
    assert walmart_referral_rate("beauty", Decimal("10.01")) == Decimal("0.15")


# MARK: - WFS: the Under-$10 flat schedule


@pytest.mark.parametrize("sale_price", [Decimal("5.93"), Decimal("8.99"), Decimal("9.99")])
def test_wfs_under_10_is_flat_not_weight_tiered(sale_price):
    """Confirmed at two price points across 12 orders / three weeks.

    The observed $4.45 matched neither the published 0-1 lb ($3.45) nor the
    1-2 lb ($4.95) band, because sub-$10 items aren't priced by weight at all.
    """
    light = ItemDimensions(weight_lb=Decimal("0.5"))
    heavy = ItemDimensions(weight_lb=Decimal("1.8"))
    light_fee, light_notes = wfs_fulfillment_fee(light, sale_price)
    heavy_fee, _ = wfs_fulfillment_fee(heavy, sale_price)

    assert light_fee == Decimal("4.45")
    # Flat means flat: weight must not move it inside the band.
    assert heavy_fee == light_fee
    assert "wfs_under_10_schedule" in light_notes


def test_wfs_under_10_sits_between_the_published_weight_tiers():
    """The tell that identified the separate schedule in the first place."""
    dims = ItemDimensions(weight_lb=Decimal("1.0"))
    tier_0_1, _ = wfs_fulfillment_fee(dims, Decimal("25.00"))
    flat, _ = wfs_fulfillment_fee(dims, Decimal("8.99"))
    tier_1_2, _ = wfs_fulfillment_fee(ItemDimensions(weight_lb=Decimal("1.5")), Decimal("25.00"))

    assert tier_0_1 == Decimal("3.45")
    assert tier_1_2 == Decimal("4.95")
    assert tier_0_1 < flat < tier_1_2


def test_wfs_at_and_above_10_uses_the_weight_tiers():
    """The threshold is exclusive — $10.00 is already on the published table."""
    dims = ItemDimensions(weight_lb=Decimal("0.5"))
    at_ten, notes = wfs_fulfillment_fee(dims, Decimal("10.00"))
    assert at_ten == Decimal("3.45")
    assert "wfs_under_10_schedule" not in notes


def test_wfs_without_a_sale_price_uses_weight_tiers():
    """No price supplied means the Under-$10 rule can't be evaluated at all."""
    fee, _ = wfs_fulfillment_fee(ItemDimensions(weight_lb=Decimal("0.5")))
    assert fee == Decimal("3.45")


# MARK: - WFS: weight tiers and assumptions


@pytest.mark.parametrize(
    ("weight", "expected"),
    [
        (Decimal("0.5"), Decimal("3.45")),
        (Decimal("1"), Decimal("3.45")),
        (Decimal("1.5"), Decimal("4.95")),
        (Decimal("2"), Decimal("4.95")),
        (Decimal("3"), Decimal("5.45")),
        # 3-20 lb band: $5.75 base + $0.40/lb over 3 lb.
        (Decimal("5"), Decimal("6.55")),
    ],
)
def test_wfs_weight_tiers(weight, expected):
    fee, _ = wfs_fulfillment_fee(ItemDimensions(weight_lb=weight), Decimal("25.00"))
    assert fee == expected


def test_missing_weight_is_flagged_never_silently_defaulted():
    """A PASS built on a guessed weight must look different from a measured one."""
    fee, notes = wfs_fulfillment_fee(ItemDimensions(), Decimal("25.00"))
    assert "assumed_weight" in notes
    assert fee > Decimal("0")


def test_dimensional_weight_governs_when_it_exceeds_actual():
    """A big light box bills on volume — carriers do, so the estimate must too."""
    bulky_but_light = ItemDimensions(
        weight_lb=Decimal("1"),
        length_in=Decimal("20"),
        width_in=Decimal("15"),
        height_in=Decimal("10"),
    )
    # 20x15x10 / 139 = ~21.6 lb dimensional, well above the 1 lb actual.
    assert bulky_but_light.billable_weight_lb > Decimal("21")
    fee, _ = wfs_fulfillment_fee(bulky_but_light, Decimal("50.00"))
    assert fee > Decimal("5.75")


def test_storage_flags_an_assumed_cube():
    fee, notes = wfs_storage_fee(ItemDimensions(), days_on_hand=60)
    assert "assumed_cubic_feet" in notes
    assert fee > Decimal("0")


def test_q4_storage_is_double():
    dims = ItemDimensions(length_in=Decimal("12"), width_in=Decimal("12"), height_in=Decimal("12"))
    standard, _ = wfs_storage_fee(dims, days_on_hand=30, q4=False)
    q4, _ = wfs_storage_fee(dims, days_on_hand=30, q4=True)
    assert q4 == standard * 2


# MARK: - Shipping estimate


def test_ebay_shipping_flags_assumed_weight():
    cost, notes = ebay_shipping_estimate(ItemDimensions())
    assert "assumed_weight" in notes
    assert cost > Decimal("0")


def test_ebay_shipping_is_monotonic_in_weight():
    weights = [Decimal("0.4"), Decimal("0.9"), Decimal("1.5"), Decimal("4"), Decimal("9")]
    costs = [ebay_shipping_estimate(ItemDimensions(weight_lb=w))[0] for w in weights]
    assert costs == sorted(costs)


# MARK: - Derived economics


def test_net_margin_and_roi_are_consistent():
    econ = walmart_economics(
        sale_price=Decimal("50.00"),
        unit_cost=Decimal("20.00"),
        category="home_garden",
        dims=ItemDimensions(weight_lb=Decimal("1")),
    )
    assert econ.net_profit == econ.sale_price - econ.unit_cost - econ.fees.total
    assert econ.margin_pct == (econ.net_profit / econ.sale_price * 100).quantize(Decimal("0.01"))
    assert econ.roi_pct == (econ.net_profit / econ.unit_cost * 100).quantize(Decimal("0.01"))


def test_breakeven_price_clears_exactly_zero():
    """The 'how far can this price war go' line has to actually be the line."""
    econ = walmart_economics(
        sale_price=Decimal("50.00"),
        unit_cost=Decimal("20.00"),
        category="home_garden",
        dims=ItemDimensions(weight_lb=Decimal("1")),
    )
    breakeven = econ.breakeven_sale_price
    recomputed = walmart_economics(
        sale_price=breakeven,
        unit_cost=Decimal("20.00"),
        category="home_garden",
        dims=ItemDimensions(weight_lb=Decimal("1")),
    )
    # Within a cent — the referral fee re-rounds at the new price.
    assert abs(recomputed.net_profit) <= Decimal("0.02")


def test_zero_cost_row_does_not_divide_by_zero():
    econ = walmart_economics(
        sale_price=Decimal("10.00"), unit_cost=Decimal("0"), category="home_garden"
    )
    assert econ.roi_pct == Decimal("0")


def test_fee_breakdown_total_is_the_sum_of_its_parts():
    econ = ebay_economics(
        sale_price=Decimal("40.00"),
        unit_cost=Decimal("15.00"),
        ad_rate=Decimal("0.05"),
        seller_shipping_cost=Decimal("6.00"),
    )
    parts = econ.fees.as_dict()
    assert parts["total"] == pytest.approx(
        parts["referral_fee"]
        + parts["fulfillment_fee"]
        + parts["storage_fee"]
        + parts["per_order_fee"]
        + parts["shipping_cost"]
        + parts["ad_fee"]
        + parts["other_fees"]
    )


def test_fee_schedule_is_versioned():
    """Rate tables are configuration to re-verify quarterly, not constants."""
    assert FEE_SCHEDULE_VERSION
    assert "default" in WALMART_REFERRAL_RATES
