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
    if not reviews:
        return []
    out = []
    for i, review_count in enumerate(reviews):
        out.append(
            demand_mod.Snapshot(
                captured_at=NOW - timedelta(days=30 - i * 15),
                price=Decimal(str(prices[i])) if prices else None,
                review_count=review_count,
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
        dims = fees_mod.ItemDimensions(
            weight_lb=Decimal(str(walmart["weight_lb"])) if walmart.get("weight_lb") else None
        )

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
                brand_status=scored.brand_status,
            )
        scored_rows.append(scored)

    ranked = scoring_mod.rank(scored_rows)

    print()
    print("=" * 78)
    print("VERDICT  (ranked by projected monthly profit)")
    print("=" * 78)
    header = (
        f"  {'#':<3}{'ITEM':30}{'CH':<9}{'COST':>8}{'SELL':>9}"
        f"{'NET':>8}{'ROI':>8}{'SHARE':>8}{'PROJ/MO':>10}  VERDICT"
    )
    print(header)
    print("  " + "-" * (len(header) - 2))
    for i, row in enumerate(ranked, 1):
        best = row.best_channel
        if best is None:
            blanks = f"{'':>8}{'':>9}{'':>8}{'':>8}{'':>8}{'':>10}"
            print(
                f"  {i:<3}{(row.description or '?')[:28]:30}{'-':<9}{blanks}  "
                "FAIL (no match)"
            )
            continue
        eco = best.economics
        print(
            f"  {i:<3}{(row.description or '?')[:28]:30}{eco.channel:<9}"
            f"{float(eco.unit_cost):>8.2f}{float(eco.sale_price):>9.2f}"
            f"{float(eco.net_profit):>8.2f}{float(eco.roi_pct):>7.1f}%"
            f"{(best.unit_share or 0):>8.0f}{best.projected_monthly_profit or 0:>10.0f}  "
            f"{row.verdict.value.upper()}"
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
