#!/usr/bin/env python3
"""Offline end-to-end demo of the sourcing pipeline — no network, no database.

Runs the pure half of the pipeline (ingest → normalize → fee → demand → verdict)
against ``sample_price_list.csv`` using canned match data in place of the
Walmart and eBay adapters. That's the point: everything computational is pure,
so the whole decision path is reproducible without a single API call.

    python3 sourcing/demo_crunch.py

The canned matches live in ``_FAKE_MATCHES`` keyed by GTIN-14. Swap in
``SourcingService.match_row`` and the same code runs against live APIs.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from m15_sourcing import demand as demand_mod  # noqa: E402
from m15_sourcing import fees as fees_mod  # noqa: E402
from m15_sourcing import landed_cost as landed_mod  # noqa: E402
from m15_sourcing import plans as plans_mod  # noqa: E402
from m15_sourcing import scoring as scoring_mod  # noqa: E402
from m15_sourcing.ingest import ingest  # noqa: E402
from m15_sourcing.inquiry import SellerProfile, build_inquiry  # noqa: E402
from m15_sourcing.upc import summarize as summarize_upcs  # noqa: E402

NOW = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)

# Canned channel responses, keyed by GTIN-14, standing in for the adapters.
_FAKE_MATCHES: dict[str, dict] = {
    "00195949036323": {  # French press — the clear winner
        "walmart": {
            "found": True, "item_id": "551234567", "price": 39.98,
            "category_path": "Home/Kitchen/Coffee", "weight_lb": 2.1,
            "review_count": 412, "seller_count": 2, "in_stock": True,
        },
        "ebay": {"found": True, "reference_price": 42.50, "total_active_listings": 7},
    },
    "00812345678901": {  # Fry pan — thin on Walmart, better on eBay
        "walmart": {
            "found": True, "item_id": "551234568", "price": 54.00,
            "category_path": "Home/Kitchen/Cookware", "weight_lb": 3.4,
            "review_count": 88, "seller_count": 9, "in_stock": True,
        },
        "ebay": {"found": True, "reference_price": 61.99, "total_active_listings": 3},
    },
    "00777681000055": {  # Desk lamp — margin fails
        "walmart": {
            "found": True, "item_id": "551234569", "price": 26.94,
            "category_path": "Home/Lighting", "weight_lb": 2.8,
            "review_count": 51, "seller_count": 6, "in_stock": True,
        },
        "ebay": {"found": False},
    },
    "00883816756817": {  # Earbuds — electronics 8% referral, decent
        "walmart": {
            "found": True, "item_id": "551234570", "price": 69.99,
            "category_path": "Electronics/Audio/Headphones", "weight_lb": 0.6,
            "review_count": 1204, "seller_count": 4, "in_stock": True,
        },
        "ebay": {"found": True, "reference_price": 64.95, "total_active_listings": 22},
    },
    "00049000006346": {  # Dog toys — no Walmart listing at all
        "walmart": {"found": False},
        "ebay": {"found": True, "reference_price": 21.99, "total_active_listings": 2},
    },
    "10195949036320": {  # Drill — case code, unwrapped to the each
        "walmart": {
            "found": True, "item_id": "551234571", "price": 379.00,
            "category_path": "Tools/Power Tools", "weight_lb": 11.2,
            "review_count": 340, "seller_count": 3, "in_stock": True,
        },
        "ebay": {"found": True, "reference_price": 355.00, "total_active_listings": 11},
    },
    "00036000291452": {  # Air purifier — passes ratios, capital-heavy
        "walmart": {
            "found": True, "item_id": "551234572", "price": 249.99,
            "category_path": "Home/Air Quality", "weight_lb": 14.0,
            "review_count": 156, "seller_count": 5, "in_stock": True,
        },
        "ebay": {"found": True, "reference_price": 239.00, "total_active_listings": 6},
    },
}

# Canned snapshot history — three observations 15 days apart, so the velocity
# estimator has a real window to work with on the items we've been watching.
_FAKE_REVIEW_HISTORY: dict[str, list[int]] = {
    "00195949036323": [380, 396, 412],
    "00812345678901": [82, 85, 88],
    "00777681000055": [44, 48, 51],
    "00883816756817": [1100, 1150, 1204],
    "00049000006346": [12, 13, 14],
    "10195949036320": [318, 330, 340],
    "00036000291452": [140, 148, 156],
}
# Observed purchasable-quantity history — the depletion signal. Note the
# restock in the earbuds series (60 -> 140): the estimator resets its baseline
# there rather than counting it as negative sales.
_FAKE_STOCK_HISTORY: dict[str, list[int]] = {
    "00195949036323": [220, 148, 96],
    "00883816756817": [180, 60, 140],
    "00036000291452": [40, 38, 36],
}
# Amazon Best Sellers Rank, where we have it.
_FAKE_BSR: dict[str, tuple[int, str]] = {
    "00812345678901": (18_400, "Home & Kitchen"),
    "00049000006346": (52_000, "Pet Supplies"),
}
_FAKE_PRICE_HISTORY: dict[str, list[float]] = {
    "00195949036323": [39.98, 39.98, 39.98],
    "00812345678901": [58.00, 49.00, 54.00],  # volatile — a price war
    "00777681000055": [27.94, 27.44, 26.94],
    "00883816756817": [72.99, 71.00, 69.99],
    "00049000006346": [21.99, 21.99, 21.99],
    "10195949036320": [379.00, 379.00, 379.00],
    "00036000291452": [249.99, 249.99, 249.99],
}


def _snapshots(gtin14: str) -> list[demand_mod.Snapshot]:
    reviews = _FAKE_REVIEW_HISTORY.get(gtin14)
    prices = _FAKE_PRICE_HISTORY.get(gtin14)
    stock = _FAKE_STOCK_HISTORY.get(gtin14)
    bsr = _FAKE_BSR.get(gtin14)
    if not reviews:
        return []
    out = []
    for i, review_count in enumerate(reviews):
        out.append(
            demand_mod.Snapshot(
                captured_at=NOW - timedelta(days=30 - i * 15),
                price=Decimal(str(prices[i])) if prices else None,
                review_count=review_count,
                available_quantity=stock[i] if stock else None,
                sales_rank=bsr[0] if bsr else None,
                sales_rank_category=bsr[1] if bsr else None,
            )
        )
    return out


def main() -> int:
    path = Path(__file__).resolve().parent / "sample_price_list.csv"
    result = ingest(path.read_bytes(), path.name)
    stats = summarize_upcs([r.upc for r in result.rows])
    thresholds = scoring_mod.Thresholds(
        min_net_profit=Decimal("3.00"),
        min_roi_pct=Decimal("25.0"),
        min_monthly_unit_share=30.0,
        max_capital_per_sku=Decimal("5000"),
        max_days_to_sell_through=90.0,
        min_annualized_roi_pct=Decimal("150.0"),
        ranking_policy=scoring_mod.RANK_BY_VELOCITY,
    )
    # A realistic small-seller cost profile: freight billed by weight into a
    # prep centre, a polybag and a label on every unit, a 3% damage reserve and
    # a 5% return reserve.
    cost_profile = landed_mod.CostProfile(
        inbound_freight_per_lb=Decimal("0.42"),
        prep_per_unit=Decimal("0.55"),
        packaging_per_unit=Decimal("0.18"),
        inspection_per_unit=Decimal("0.10"),
        shrink_rate=Decimal("0.03"),
        return_rate=Decimal("0.05"),
    )
    plan_selection = plans_mod.PlanSelection(
        ebay="basic", amazon="professional", walmart="standard",
        already_subscribed=True,
    )

    print("=" * 78)
    print("INGEST")
    print("=" * 78)
    print(f"  header row       : {result.mapping.header_row_index}")
    print(f"  columns mapped   : {result.mapping.columns}")
    print(f"  rows             : {len(result.rows)} ({result.skipped_rows} skipped)")
    print(f"  UPCs usable      : {stats.usable}/{stats.total} ({stats.usable_pct}%)")
    print(f"  by method        : {stats.by_method}")
    print(f"  by warning       : {stats.by_warning}")
    for warning in result.warnings:
        print(f"  ! {warning}")

    print()
    print("=" * 78)
    print("NORMALIZE")
    print("=" * 78)
    for row in result.rows:
        flag = "ok " if row.upc.is_usable else "DROP"
        print(
            f"  [{flag}] {str(row.upc.raw)[:22]:24} -> "
            f"{str(row.upc.gtin14 or '-'):15} search={str(row.upc.search_value or '-'):14} "
            f"{row.upc.method:22} {','.join(row.upc.warnings) or '-'}"
        )

    scored_rows: list[scoring_mod.ScoredRow] = []
    for row in result.rows:
        gtin14 = row.upc.gtin14
        unit_cost = row.effective_unit_cost
        scored = scoring_mod.ScoredRow(
            row_index=row.row_index,
            gtin14=gtin14,
            description=row.description,
            brand=row.brand,
            unit_cost=unit_cost,
            minimum_buy_cost=row.minimum_buy_cost,
            brand_status=scoring_mod.BRAND_AUTHORIZED
            if (row.brand or "").lower() == "kitchenly"
            else scoring_mod.BRAND_UNKNOWN,
        )
        if not gtin14 or unit_cost is None or unit_cost <= 0:
            scored.errors.append("no usable UPC or cost")
            scored_rows.append(scored)
            continue

        match = _FAKE_MATCHES.get(gtin14, {"walmart": {"found": False}, "ebay": {"found": False}})
        snaps = _snapshots(gtin14)
        walmart = match.get("walmart") or {}
        ebay = match.get("ebay") or {}
        weight = Decimal(str(walmart["weight_lb"])) if walmart.get("weight_lb") else None
        dims = fees_mod.ItemDimensions(weight_lb=weight)

        landed = landed_mod.build_landed_cost(
            invoice_cost=unit_cost,
            profile=cost_profile,
            weight_lb=weight,
            case_pack=row.case_pack,
        )
        scored.landed_cost = landed
        unit_cost = landed.total

        if walmart.get("found"):
            scored.channels["walmart"] = scoring_mod.score_channel(
                economics=fees_mod.walmart_economics(
                    sale_price=Decimal(str(walmart["price"])),
                    unit_cost=unit_cost,
                    category=walmart.get("category_path"),
                    dims=dims,
                ),
                demand=demand_mod.estimate_demand(snaps),
                stability=demand_mod.price_stability(snaps),
                seller_count=walmart.get("seller_count"),
                thresholds=thresholds,
                minimum_buy_cost=row.minimum_buy_cost,
                minimum_buy_units=row.minimum_buy_units,
                brand_status=scored.brand_status,
            )
        if ebay.get("found"):
            scored.channels["ebay"] = scoring_mod.score_channel(
                economics=fees_mod.ebay_economics(
                    sale_price=Decimal(str(ebay["reference_price"])),
                    unit_cost=unit_cost,
                    dims=dims,
                ),
                demand=demand_mod.estimate_demand(snaps),
                stability=demand_mod.price_stability(snaps),
                seller_count=ebay.get("total_active_listings"),
                thresholds=thresholds,
                minimum_buy_cost=row.minimum_buy_cost,
                minimum_buy_units=row.minimum_buy_units,
                brand_status=scored.brand_status,
            )
        scored_rows.append(scored)

    ranked = scoring_mod.rank(scored_rows, thresholds.ranking_policy)

    print()
    print("=" * 78)
    print("VERDICT  (ranked by projected monthly profit)")
    print("=" * 78)
    header = (
        f"  {'#':<3}{'ITEM':27}{'CH':<8}{'INV':>7}{'LAND':>8}{'SELL':>8}"
        f"{'NET':>7}{'ROI':>6}{'/MO':>6}{'DAYS':>6}{'ANN':>7}  SIGNAL     VERDICT"
    )
    print(header)
    print("  " + "-" * (len(header) - 2))
    for i, row in enumerate(ranked, 1):
        best = row.best_channel
        if best is None:
            blanks = f"{'':>7}{'':>8}{'':>8}{'':>7}{'':>6}{'':>6}{'':>6}{'':>7}"
            print(
                f"  {i:<3}{(row.description or '?')[:25]:27}{'-':<8}{blanks}  "
                "unknown    FAIL"
            )
            continue
        eco = best.economics
        invoice = float(row.landed_cost.invoice_cost) if row.landed_cost else 0.0
        days, ann = best.days_to_sell_through, best.annualized_roi_pct
        print(
            f"  {i:<3}{(row.description or '?')[:25]:27}{eco.channel:<8}"
            f"{invoice:>7.2f}{float(eco.unit_cost):>8.2f}{float(eco.sale_price):>8.2f}"
            f"{float(eco.net_profit):>7.2f}{float(eco.roi_pct):>5.0f}%"
            f"{(best.unit_share or 0):>6.0f}"
            f"{(f'{days:.0f}' if days else '-'):>6}"
            f"{(f'{ann:.0f}%' if ann else '-'):>7}  "
            f"{best.demand.confidence.value:<10} {row.verdict.value.upper()}"
        )

    print()
    print("=" * 78)
    print("WHY  (top 4)")
    print("=" * 78)
    for row in ranked[:4]:
        best = row.best_channel
        if best is None:
            continue
        print(
            f"  {row.description} -> {best.economics.channel} "
            f"[{row.verdict.value.upper()}]"
        )
        f = best.economics.fees
        print(
            f"     fees: referral ${f.referral_fee} | fulfil ${f.fulfillment_fee} | "
            f"storage ${f.storage_fee} | ship ${f.shipping_cost} | per-order ${f.per_order_fee} "
            f"= ${f.total}"
        )
        print(f"     demand: {best.demand.basis} ({best.demand.confidence.value})")
        print(f"     breakeven sale price: ${best.economics.breakeven_sale_price}")
        for reason in best.passed:
            print(f"     PASS  {reason}")
        for reason in best.reasons:
            print(f"     FLAG  {reason}")
        print()

    print("=" * 78)
    print("LANDED COST  (the invoice price is not what a unit costs you)")
    print("=" * 78)
    for row in ranked[:4]:
        lc = row.landed_cost
        if lc is None:
            continue
        print(
            f"  {(row.description or '?')[:32]:34} "
            f"invoice ${float(lc.invoice_cost):>7.2f} -> landed ${float(lc.total):>7.2f} "
            f"(+{float(lc.uplift_pct):.1f}%)"
        )
        print(
            f"     freight ${float(lc.inbound_freight_per_unit):.2f} | "
            f"prep ${float(lc.prep_per_unit):.2f} | pack ${float(lc.packaging_per_unit):.2f} | "
            f"QC ${float(lc.inspection_per_unit):.2f} | "
            f"survives {float(lc.survival_rate) * 100:.0f}%"
        )

    print()
    print("=" * 78)
    print("SELLING PLANS  (fixed fees are never amortized into unit margin)")
    print("=" * 78)
    passing = [r for r in ranked if r.verdict == scoring_mod.Verdict.PASS]
    avg_price = (
        sum((r.best_channel.economics.sale_price for r in passing), Decimal("0"))
        / len(passing)
        if passing
        else Decimal("30")
    )
    monthly_units = sum((r.best_channel.unit_share or 0) for r in passing)
    for channel in ("ebay", "amazon"):
        current = getattr(plan_selection, channel)
        best_plan, comparisons = plans_mod.recommend_plan(
            channel, monthly_units=monthly_units, avg_sale_price=avg_price
        )
        print(
            f"  {channel}: holding '{current}' | at {monthly_units:.0f} units/mo "
            f"the cheapest plan is '{best_plan.key}'"
        )
        for comparison in comparisons:
            print(f"     {comparison.from_plan} -> {comparison.to_plan}: {comparison.note}")

    print()
    print("=" * 78)
    print("SUMMARY")
    print("=" * 78)
    summary = scoring_mod.summarize(scored_rows)
    for key, value in summary.items():
        print(f"  {key:40} {value}")

    winner = next((r for r in ranked if r.verdict == scoring_mod.Verdict.PASS), None)
    if winner:
        print()
        print("=" * 78)
        print("DISTRIBUTOR INQUIRY DRAFT  (top candidate)")
        print("=" * 78)
        source_row = next(r for r in result.rows if r.upc.gtin14 == winner.gtin14)
        draft = build_inquiry(
            seller=SellerProfile(
                business_name="Northwind Retail Group",
                contact_name="Mike O.",
                email="buying@northwind.example",
                resale_certificate_state="TX",
                years_in_business=3,
            ),
            product_name=winner.description or "",
            brand=winner.brand,
            upc=source_row.upc.search_value,
            case_pack=source_row.case_pack,
            moq=source_row.moq,
            quoted_unit_cost=winner.unit_cost,
            distributor_name="Meridian Wholesale Supply",
            distributor_email="sales@meridianwholesale.example",
        )
        print(f"  To: {draft.to}")
        print(f"  Subject: {draft.subject}")
        print()
        for line in draft.body.splitlines():
            print(f"  | {line}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
