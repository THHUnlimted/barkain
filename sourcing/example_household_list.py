#!/usr/bin/env python3
"""Worked example — six household goods from a distributor list, fully scored.

Every number here is produced by the real pipeline: landed cost from
``landed_cost.py``, fees from ``fees.py`` (including the Under-$10 WFS rule),
demand from ``demand.py``, verdicts and ranking from ``scoring.py``.

    python3 sourcing/example_household_list.py

Two things are deliberately made internally consistent, because the last
hand-built scenario wasn't:

1. **BSR is derived from the target volume, not guessed.** For each item the
   rank is back-solved from ``units = a x rank^-b`` using the same
   ``home_kitchen`` curve the estimator uses, so ``rank`` and ``depletion``
   cross-validate instead of contradicting each other by 300x.
2. **Badge windows are correct per channel.** Walmart's badge is per-day,
   Amazon's is per-month. The Walmart badge is set to a plausible daily floor
   just under the measured rate.

The cost profile uses the operator's stated method (freight by weight, 3%
return reserve) with placeholder rates -- see PLACEHOLDERS below.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from m15_sourcing import demand as dm  # noqa: E402
from m15_sourcing import fees as fm  # noqa: E402
from m15_sourcing import landed_cost as lc  # noqa: E402
from m15_sourcing import scoring as sc  # noqa: E402

NOW = datetime(2026, 7, 27, tzinfo=UTC)

# PLACEHOLDERS — replace with the operator's real figures.
COST_PROFILE = lc.CostProfile(
    inbound_freight_per_lb=D("0.42"),   # <- placeholder
    prep_per_unit=D("0.55"),            # <- placeholder
    packaging_per_unit=D("0.18"),       # <- placeholder
    inspection_per_unit=D("0.10"),      # <- placeholder
    return_rate=D("0.03"),              # operator-stated cushion (measured <1%)
)

THRESHOLDS = sc.Thresholds(
    min_net_profit=D("3.00"),
    min_roi_pct=D("25.0"),
    min_monthly_unit_share=30.0,
    max_days_to_sell_through=90.0,
    min_annualized_roi_pct=D("150.0"),
    max_capital_per_sku=D("5000"),
    velocity_bias=0.75,
)


def bsr_for(units_per_month: float, category: str = "Home & Kitchen") -> int:
    """Back-solve a rank from a target volume using the estimator's own curve.

    Keeps `rank` and `depletion` telling the same story, so the worked example
    demonstrates the pipeline rather than an estimator disagreement.
    """
    key = dm.normalize_bsr_category(category)
    a, b = dm._BSR_CURVES[key]
    return int(round((a / units_per_month) ** (1.0 / b)))


@dataclass
class Item:
    name: str
    brand: str
    case_cost: D
    case_pack: int
    moq_units: int
    weight_lb: D
    walmart_price: D
    ebay_price: D | None
    monthly_units: float          # true market rate for this listing
    seller_count: int
    lead_time_days: float
    walmart_listing: bool = True

    @property
    def unit_invoice(self) -> D:
        return self.case_cost / D(self.case_pack)

    @property
    def capital(self) -> D:
        return self.unit_invoice * D(self.moq_units)


ITEMS = [
    # Fast + thin. High turn, small dollars per unit. Wins on pure velocity.
    Item("Silicone Dish Brush Set, 3pc", "Kitchenly",
         case_cost=D("60.00"), case_pack=24, moq_units=48, weight_lb=D("0.4"),
         walmart_price=D("12.97"), ebay_price=D("14.50"),
         monthly_units=150, seller_count=3, lead_time_days=7),

    # The sub-$10 squeeze. Flat $4.45 WFS is 47% of the sale price.
    Item("Microfiber Cleaning Cloths, 24pk", "HomeCrest",
         case_cost=D("36.00"), case_pack=24, moq_units=48, weight_lb=D("0.9"),
         walmart_price=D("9.47"), ebay_price=D("11.99"),
         monthly_units=90, seller_count=6, lead_time_days=14),

    # Middle of the road on both axes.
    Item("Stainless Mixing Bowl Set, 5pc", "Kitchenly",
         case_cost=D("180.00"), case_pack=12, moq_units=24, weight_lb=D("3.2"),
         walmart_price=D("34.99"), ebay_price=D("38.50"),
         monthly_units=40, seller_count=4, lead_time_days=14),

    # Slow + fat. Best dollars per unit on the list, worst turn. Wins on pure margin.
    Item("Cast Iron Dutch Oven, 6qt", "IronHearth",
         case_cost=D("204.00"), case_pack=6, moq_units=12, weight_lb=D("14.0"),
         walmart_price=D("79.99"), ebay_price=D("84.00"),
         monthly_units=18, seller_count=2, lead_time_days=21),

    # Capital-heavy, slow, long lead, crowded. The classic trap.
    Item("Air Fryer 8qt Digital", "Chefwave",
         case_cost=D("288.00"), case_pack=4, moq_units=24, weight_lb=D("12.5"),
         walmart_price=D("119.99"), ebay_price=D("112.00"),
         monthly_units=12, seller_count=8, lead_time_days=45),

    # Dead row — distributor carries it, no marketplace listing exists.
    Item("Ceramic Canister Set, 4pc", "HomeCrest",
         case_cost=D("96.00"), case_pack=8, moq_units=16, weight_lb=D("6.0"),
         walmart_price=D("0"), ebay_price=None,
         monthly_units=0, seller_count=0, lead_time_days=14,
         walmart_listing=False),
]


def snapshots_for(item: Item) -> list[dm.Snapshot]:
    """Five daily observations: stock depletion + a consistent BSR + a daily badge."""
    if not item.walmart_listing:
        return []
    daily = item.monthly_units / 30.0
    start_qty = int(daily * 30)
    rank = bsr_for(item.monthly_units)
    # Walmart badges bucket coarsely; use the largest bucket at or below the rate.
    buckets = [1000, 500, 100, 50, 25, 10]
    badge = next((b for b in buckets if b <= daily), None)
    return [
        dm.Snapshot(
            captured_at=NOW - timedelta(days=5 - i),
            price=item.walmart_price,
            available_quantity=int(start_qty - daily * i),
            sales_rank=rank,
            sales_rank_category="Home & Kitchen",
            bought_badge_min=badge,
            seller_count=item.seller_count,
        )
        for i in range(6)
    ]


def score(item: Item) -> sc.ScoredRow:
    landed = lc.build_landed_cost(
        invoice_cost=item.unit_invoice,
        profile=COST_PROFILE,
        weight_lb=item.weight_lb,
        case_pack=item.case_pack,
    )
    row = sc.ScoredRow(
        row_index=0, gtin14=None, description=item.name, brand=item.brand,
        unit_cost=landed.total, minimum_buy_cost=item.capital,
        brand_status=sc.BRAND_AUTHORIZED
        if item.brand in ("Kitchenly", "IronHearth")
        else sc.BRAND_UNKNOWN,
    )
    row.landed_cost = landed
    snaps = snapshots_for(item)
    demand = dm.estimate_demand(snaps) if snaps else dm.UNKNOWN_DEMAND
    stability = dm.price_stability(snaps)
    dims = fm.ItemDimensions(weight_lb=item.weight_lb)

    if item.walmart_listing:
        row.channels["walmart"] = sc.score_channel(
            economics=fm.walmart_economics(
                sale_price=item.walmart_price, unit_cost=landed.total,
                category="Home & Garden", dims=dims, return_rate=D("0.03"),
            ),
            demand=demand, stability=stability, seller_count=item.seller_count,
            thresholds=THRESHOLDS, minimum_buy_cost=item.capital,
            minimum_buy_units=item.moq_units, lead_time_days=item.lead_time_days,
            brand_status=row.brand_status,
        )
    if item.ebay_price:
        row.channels["ebay"] = sc.score_channel(
            economics=fm.ebay_economics(
                sale_price=item.ebay_price, unit_cost=landed.total, dims=dims,
            ),
            demand=demand, stability=stability, seller_count=item.seller_count,
            thresholds=THRESHOLDS, minimum_buy_cost=item.capital,
            minimum_buy_units=item.moq_units, lead_time_days=item.lead_time_days,
            brand_status=row.brand_status,
        )
    return row


def main() -> int:
    rows = [score(i) for i in ITEMS]
    by_name = {r.description: i for r, i in zip(rows, ITEMS)}

    print("=" * 108)
    print("SOURCING INPUTS")
    print("=" * 108)
    print(f"  {'ITEM':32}{'CASE':>9}{'PACK':>6}{'MOQ':>5}{'INV/u':>8}"
          f"{'LANDED':>8}{'LB':>6}{'CAPITAL':>9}{'LEAD':>6}")
    for r, i in zip(rows, ITEMS):
        lcst = r.landed_cost
        print(f"  {i.name[:30]:32}{float(i.case_cost):>9.2f}{i.case_pack:>6}{i.moq_units:>5}"
              f"{float(i.unit_invoice):>8.2f}{float(lcst.total):>8.2f}{float(i.weight_lb):>6.1f}"
              f"{float(i.capital):>9.0f}{i.lead_time_days:>6.0f}")

    modes = (
        (0.75, "DEFAULT (velocity-weighted)"),
        (0.0, "PURE MARGIN"),
        (1.0, "PURE VELOCITY"),
    )
    for bias, label in modes:
        ranked = sc.rank(rows, velocity_bias=bias)
        print()
        print("=" * 108)
        print(f"RANKED — velocity_bias={bias}  [{label}]")
        print("=" * 108)
        print(f"  {'#':<3}{'ITEM':30}{'CH':<9}{'SELL':>8}{'NET/u':>8}{'ROI':>7}"
              f"{'UNITS/MO':>10}{'DAYS':>6}{'ANN.ROI':>9}{'$/MO':>8}  VERDICT")
        for n, r in enumerate(ranked, 1):
            b = r.best_channel
            if b is None:
                print(f"  {n:<3}{(r.description or '')[:28]:30}{'-':<9}"
                      f"{'':>8}{'':>8}{'':>7}{'':>10}{'':>6}{'':>9}{'':>8}  FAIL (no listing)")
                continue
            e = b.economics
            print(f"  {n:<3}{(r.description or '')[:28]:30}{e.channel:<9}"
                  f"{float(e.sale_price):>8.2f}{float(e.net_profit):>8.2f}{float(e.roi_pct):>6.0f}%"
                  f"{(b.unit_share or 0):>10.0f}{(b.days_to_sell_through or 0):>6.0f}"
                  f"{(f'{b.annualized_roi_pct:.0f}%' if b.annualized_roi_pct else '-'):>9}"
                  f"{(b.projected_monthly_profit or 0):>8.0f}  {r.verdict.value.upper()}")

    print()
    print("=" * 108)
    print("WHY — default ranking")
    print("=" * 108)
    for r in sc.rank(rows, velocity_bias=0.75):
        b = r.best_channel
        print(f"\n  {r.description}  [{r.verdict.value.upper()}]")
        if b is None:
            print("     no listing found on any channel")
            continue
        i = by_name[r.description]
        lcst = r.landed_cost
        f = b.economics.fees
        freight = float(lcst.inbound_freight_per_unit)
        print(f"     invoice ${float(lcst.invoice_cost):.2f} -> "
              f"landed ${float(lcst.total):.2f} (+{float(lcst.uplift_pct):.0f}%; "
              f"freight ${freight:.2f} on {float(i.weight_lb)} lb)")
        print(f"     fees: referral ${f.referral_fee} | fulfil ${f.fulfillment_fee} | "
              f"ship ${f.shipping_cost} | other ${f.other_fees} = ${f.total}")
        print(f"     demand: {b.demand.basis} [{b.demand.confidence.value}]")
        for reason in b.passed:
            print(f"     PASS  {reason}")
        for reason in b.reasons:
            print(f"     FLAG  {reason}")

    print()
    print("=" * 108)
    print("PORTFOLIO")
    print("=" * 108)
    for k, v in sc.summarize(rows).items():
        print(f"  {k:42} {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
