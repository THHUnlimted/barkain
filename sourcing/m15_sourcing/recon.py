"""Reconciliation import — learn real fees from real settlements.

Pure module. Parses Walmart Marketplace/WFS reconciliation reports and eBay
order data into observed fee facts, then exposes them as a ``FeeCalibration``
that the fee engine consults **before** its published rate tables.

## Why this exists

Published rate cards are an approximation of what you actually get charged.
They don't know about your contract category assignments, promotional fee
programs, incentive rates, or the fact that a rate card changed last Tuesday.
Your settlement report knows all of that, because it *is* what happened.

The first real report proved the point immediately. Walmart's published WFS
fulfillment tiers put a 1 lb item at $3.45 and a 1–2 lb item at $4.95. The
actual charge on a 16 oz automotive polish was **$4.45** — neither. Meanwhile
the commission came through at exactly 12.00% on ``Automotive & Powersports``,
matching the published table to the basis point.

So the rule is: **an observed fee always beats a published rate.** Published
tables are the fallback for products you've never sold, and every import
shrinks the set of products that need them.

## Two asymmetries this module encodes

Both are confirmed from real documents and both are easy to get backwards:

1. **eBay charges its percentage on the sales tax it collects. Walmart does
   not.** eBay's fee base was $28.36 on a $26.50 item ($26.50 + $1.86 tax);
   Walmart's commission was 12.00% of $8.99 flat, with the $0.69 tax collected
   and withheld as a pass-through that never enters the base.
2. **Walmart bills WFS fulfillment as a separate adjustment line, not as part
   of the order.** It can post under a different purchase order number and in a
   different settlement period than the sale it belongs to, so matching is by
   ``Purchase Order #``, not by row adjacency.
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import datetime
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

_CENT = Decimal("0.01")
_ZERO = Decimal("0")


def _money(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def _dec(raw: object) -> Decimal | None:
    if raw is None or raw == "":
        return None
    try:
        return Decimal(str(raw).replace("$", "").replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None


# MARK: - Observed facts


@dataclass
class ObservedOrder:
    """One reconciled order, assembled from the settlement lines that touch it."""

    channel: str
    order_key: str
    item_name: str | None = None
    gtin: str | None = None
    sku: str | None = None
    contract_category: str | None = None
    product_type: str | None = None
    fulfillment_type: str | None = None

    product_price: Decimal = _ZERO
    shipping_revenue: Decimal = _ZERO
    sales_tax: Decimal = _ZERO
    tax_withheld: Decimal = _ZERO

    commission: Decimal = _ZERO          # referral / final value fee
    commission_rate_reported: Decimal | None = None
    fulfillment_fee: Decimal = _ZERO
    storage_fee: Decimal = _ZERO
    shipping_label: Decimal = _ZERO
    ad_fee: Decimal = _ZERO
    other_fees: Decimal = _ZERO
    quantity: int = 1

    @property
    def total_fees(self) -> Decimal:
        return _money(
            self.commission
            + self.fulfillment_fee
            + self.storage_fee
            + self.shipping_label
            + self.ad_fee
            + self.other_fees
        )

    @property
    def net_proceeds(self) -> Decimal:
        """What actually landed in your account, before cost of goods.

        Sales tax nets to zero on Walmart (collected then withheld) and is
        never yours on eBay, so it's excluded from proceeds on both — but note
        that on eBay it *is* still in the fee base.
        """
        return _money(self.product_price + self.shipping_revenue - self.total_fees)

    @property
    def effective_commission_rate(self) -> Decimal | None:
        """Commission as a share of product price — the comparable rate."""
        if self.product_price <= 0:
            return None
        return (self.commission / self.product_price).quantize(Decimal("0.0001"))

    def as_dict(self) -> dict[str, object]:
        return {
            "channel": self.channel,
            "order_key": self.order_key,
            "item_name": self.item_name,
            "gtin": self.gtin,
            "contract_category": self.contract_category,
            "product_type": self.product_type,
            "fulfillment_type": self.fulfillment_type,
            "product_price": float(self.product_price),
            "sales_tax": float(self.sales_tax),
            "commission": float(self.commission),
            "commission_rate_reported": float(self.commission_rate_reported)
            if self.commission_rate_reported is not None
            else None,
            "effective_commission_rate": float(self.effective_commission_rate)
            if self.effective_commission_rate is not None
            else None,
            "fulfillment_fee": float(self.fulfillment_fee),
            "storage_fee": float(self.storage_fee),
            "shipping_label": float(self.shipping_label),
            "ad_fee": float(self.ad_fee),
            "total_fees": float(self.total_fees),
            "net_proceeds": float(self.net_proceeds),
            "quantity": self.quantity,
        }


# MARK: - Walmart reconciliation parser
#
# Column names from the Marketplace/WFS reconciliation report v1. The report is
# line-per-transaction: a single sale produces separate rows for product price,
# product tax, tax withheld, and commission, and the WFS fulfillment fee arrives
# as its own `Adjustment` row keyed on the same purchase order.

_WM_AMOUNT_TYPES = {
    "product price": "product_price",
    "product tax": "sales_tax",
    "product tax withheld": "tax_withheld",
    "commission on product": "commission",
    "shipping": "shipping_revenue",
    "shipping tax": None,
}


def parse_walmart_reconciliation(data: bytes | str) -> list[ObservedOrder]:
    """Parse a Walmart MP/WFS reconciliation CSV into per-order observations."""
    text = data.decode("utf-8-sig") if isinstance(data, bytes) else data
    reader = csv.DictReader(io.StringIO(text))

    orders: dict[str, ObservedOrder] = {}
    # Fulfillment and storage adjustments that arrive without a matching sale in
    # this period. Kept separately so they can be reported rather than dropped —
    # a fee with no sale attached still happened and still cost money.
    orphan_fees: dict[str, Decimal] = defaultdict(Decimal)

    for row in reader:
        po = (row.get("Purchase Order #") or "").strip()
        amount = _dec(row.get("Amount"))
        amount_type = (row.get("Amount Type") or "").strip().lower()
        description = (row.get("Transaction Description") or "").strip()

        if amount is None:
            continue

        # ── WFS adjustments: fulfillment and storage ──────────────────
        if "fulfillment fee" in description.lower():
            if po and po in orders:
                orders[po].fulfillment_fee += abs(amount)
            elif po:
                orphan_fees[po] += abs(amount)
            continue
        if "storagefee" in description.lower().replace(" ", ""):
            # Storage posts per-inventory, often with no purchase order at all.
            key = po or "__inventory__"
            if key in orders:
                orders[key].storage_fee += abs(amount)
            else:
                orphan_fees[key] += abs(amount)
            continue

        if not po:
            continue

        order = orders.get(po)
        if order is None:
            order = ObservedOrder(channel="walmart", order_key=po)
            orders[po] = order
            # Adopt any fees that arrived before the sale row.
            if po in orphan_fees:
                order.fulfillment_fee += orphan_fees.pop(po)

        order.item_name = order.item_name or (row.get("Partner Item Name") or "").strip() or None
        order.gtin = order.gtin or (row.get("Partner GTIN") or "").strip() or None
        order.sku = order.sku or (row.get("Partner Item Id") or "").strip() or None
        order.contract_category = (
            order.contract_category or (row.get("Contract Category") or "").strip() or None
        )
        order.product_type = (
            order.product_type or (row.get("Product Type") or "").strip() or None
        )
        order.fulfillment_type = (
            order.fulfillment_type or (row.get("Fulfillment Type") or "").strip() or None
        )
        qty = _dec(row.get("Ship Qty"))
        if qty and qty > 0:
            order.quantity = int(qty)

        field_name = _WM_AMOUNT_TYPES.get(amount_type)
        if field_name == "product_price":
            order.product_price += amount
        elif field_name == "shipping_revenue":
            order.shipping_revenue += amount
        elif field_name == "sales_tax":
            order.sales_tax += amount
        elif field_name == "tax_withheld":
            order.tax_withheld += abs(amount)
        elif field_name == "commission":
            order.commission += abs(amount)
            reported = _dec(row.get("Commission Rate"))
            if reported is not None:
                # The report states the rate in percent (12.00), not as a ratio.
                order.commission_rate_reported = reported / Decimal("100")

    # A second pass to attach fulfillment fees that referenced a purchase order
    # whose sale row appeared later in the file.
    for po, amount in list(orphan_fees.items()):
        if po in orders:
            orders[po].fulfillment_fee += amount
            del orphan_fees[po]

    result = list(orders.values())

    # Anything still unattached gets emitted as a synthetic zero-revenue order
    # rather than dropped. Long-term storage in particular posts against
    # *inventory*, not against any sale — it has no purchase order at all — and
    # it is exactly the fee a sourcing tool most needs to see, because it's the
    # one that quietly punishes slow movers. A parser that silently discards it
    # would make dead stock look free.
    for key, amount in orphan_fees.items():
        if amount <= 0:
            continue
        result.append(
            ObservedOrder(
                channel="walmart",
                order_key=key,
                item_name="(unattached fee — no matching sale in this period)",
                storage_fee=amount if key == "__inventory__" else _ZERO,
                fulfillment_fee=_ZERO if key == "__inventory__" else amount,
            )
        )

    return result


# MARK: - Settlement report parser
#
# A *different* file from the reconciliation report, with a different layout:
# two preamble lines (seller name, then the reporting period) before the header,
# and one row per fee rather than one row per transaction leg.
#
# The column that matters most is ``Billing Method``. See ``WFS_UNDER_10_*`` in
# fees.py — this report is where the Under-$10 schedule was discovered.

# Fee rows whose Net Payable should be *added back* rather than treated as a
# charge. Walmart issues a discount as a reduced fee, then claws it back with a
# separate DiscountAdjustment when the discount was applied in error. A parser
# that counts only the discounted rows learns a fulfillment fee that's too low.
_SETTLEMENT_ADJUSTMENT_TYPES = {"discountadjustment"}


@dataclass
class SettlementFee:
    """One fee line from a settlement report."""

    transaction_type: str
    reason_code: str | None
    billing_method: str | None
    net_payable: Decimal
    original_amount: Decimal
    discount: Decimal
    gtin: str | None
    sku: str | None
    item_name: str | None
    category: str | None
    order_key: str | None
    quantity: int = 1
    seller_partner_id: str | None = None

    @property
    def effective_amount(self) -> Decimal:
        """The fee before any discount, which is what the rate card describes.

        Calibrating on ``net_payable`` would teach the model whatever promotion
        happened to be running. ``original_amount`` is the durable number, and
        the discounts show up separately as savings.
        """
        return self.original_amount if self.original_amount > 0 else self.net_payable


def parse_walmart_settlement(data: bytes | str) -> list[SettlementFee]:
    """Parse a Walmart settlement report into individual fee lines.

    Skips the seller-name and reporting-period preamble by scanning for the row
    that actually looks like a header.
    """
    text = data.decode("utf-8-sig") if isinstance(data, bytes) else data
    lines = text.splitlines()

    header_index = next(
        (i for i, line in enumerate(lines) if "Transaction Type" in line), None
    )
    if header_index is None:
        return []

    reader = csv.DictReader(io.StringIO("\n".join(lines[header_index:])))
    out: list[SettlementFee] = []

    def _clean(value: str | None) -> str | None:
        # Walmart wraps IDs as ="00065791330026" to stop Excel eating the zeros.
        if value is None:
            return None
        v = value.strip().lstrip("=").strip('"').strip()
        return v or None

    for row in reader:
        ttype = (row.get("Transaction Type") or "").strip()
        if not ttype:
            continue
        net = _dec(row.get("Net Payable")) or _ZERO
        original = _dec(row.get("Original Amount")) or _ZERO
        discount = _dec(row.get("Discount Savings")) or _ZERO
        qty = _dec(row.get("Qty"))

        out.append(
            SettlementFee(
                transaction_type=ttype,
                reason_code=_clean(row.get("Reason Code")),
                billing_method=_clean(row.get("Billing Method")) or _clean(row.get("Detail")),
                net_payable=net,
                original_amount=original,
                discount=discount,
                gtin=_clean(row.get("Partner GTIN")),
                # NB: `Partner ID` in this report is the *seller's* partner ID
                # (it matches the number in the filename), not an item SKU.
                # Keying fee observations on it would collapse every SKU in the
                # account into one bucket and produce a meaningless average.
                sku=None,
                seller_partner_id=_clean(row.get("Partner ID")),
                item_name=_clean(row.get("Partner Item Name")),
                category=_clean(row.get("Category")),
                order_key=_clean(row.get("Walmart.com PO #")),
                quantity=int(qty) if qty and qty > 0 else 1,
            )
        )
    return out


def settlement_fee_summary(fees: list[SettlementFee]) -> dict[str, object]:
    """Roll settlement lines up by type, netting the clawback adjustments.

    The netting matters: a $1.50 discount on one order followed by a $1.50
    ``DiscountAdjustment`` recouping it is a wash, and reporting only the first
    half would understate what fulfillment actually costs.
    """
    by_type: dict[str, dict[str, object]] = {}
    adjustments = _ZERO

    for fee in fees:
        key = fee.transaction_type
        if key.strip().lower() in _SETTLEMENT_ADJUSTMENT_TYPES:
            adjustments += fee.net_payable
            continue
        bucket = by_type.setdefault(
            key, {"lines": 0, "net": _ZERO, "original": _ZERO, "discount": _ZERO,
                  "billing_methods": set()}
        )
        bucket["lines"] = int(bucket["lines"]) + 1  # type: ignore[arg-type]
        bucket["net"] = bucket["net"] + fee.net_payable  # type: ignore[operator]
        bucket["original"] = bucket["original"] + fee.effective_amount  # type: ignore[operator]
        bucket["discount"] = bucket["discount"] + fee.discount  # type: ignore[operator]
        if fee.billing_method:
            bucket["billing_methods"].add(fee.billing_method)  # type: ignore[union-attr]

    return {
        "by_type": {
            key: {
                "lines": bucket["lines"],
                "net_payable": float(bucket["net"]),  # type: ignore[arg-type]
                "before_discounts": float(bucket["original"]),  # type: ignore[arg-type]
                "discounts": float(bucket["discount"]),  # type: ignore[arg-type]
                "billing_methods": sorted(bucket["billing_methods"]),  # type: ignore[arg-type]
            }
            for key, bucket in sorted(by_type.items())
        },
        "discount_clawbacks": float(adjustments),
    }


# MARK: - Inventory reconciliation parser
#
# The single best demand signal available, and it needs no scraping at all: for
# SKUs you already own, Walmart reports exactly how many units left the
# fulfillment centre in the period, with Lost / Found / Removed / Transferred
# broken out separately so adjustments never get mistaken for sales.
#
# This is what the cart-quantity depletion estimator in demand.py is
# *approximating* for items you don't own yet. Where this report exists, it wins
# outright — same signal, first-party, no inference.


@dataclass
class InventoryMovement:
    """One SKU's inventory movement at one fulfillment centre over one period."""

    gtin: str | None
    item_id: str | None
    sku: str | None
    product_name: str | None
    fulfillment_center: str | None
    period_start: str
    period_end: str
    starting_quantity: int = 0
    received: int = 0
    sold: int = 0
    lost: int = 0
    found: int = 0
    removed: int = 0
    ending_quantity: int = 0

    @property
    def period_days(self) -> int:
        try:
            start = datetime.fromisoformat(self.period_start)
            end = datetime.fromisoformat(self.period_end)
            return max((end - start).days, 1)
        except (TypeError, ValueError):
            return 30

    @property
    def monthly_units(self) -> float:
        """Sold units normalized to 30 days."""
        return round(self.sold / self.period_days * 30.0, 1)

    @property
    def months_of_cover(self) -> float | None:
        """How long the remaining stock lasts at the observed rate.

        The number that decides whether a reorder is urgent — and the one that
        predicts a long-term storage bill before it arrives.
        """
        rate = self.monthly_units
        if rate <= 0:
            return None
        return round(self.ending_quantity / rate, 1)

    def as_dict(self) -> dict[str, object]:
        return {
            "gtin": self.gtin,
            "sku": self.sku,
            "product_name": self.product_name,
            "fulfillment_center": self.fulfillment_center,
            "period_days": self.period_days,
            "starting_quantity": self.starting_quantity,
            "sold": self.sold,
            "lost": self.lost,
            "removed": self.removed,
            "ending_quantity": self.ending_quantity,
            "monthly_units": self.monthly_units,
            "months_of_cover": self.months_of_cover,
        }


def parse_walmart_inventory_reconciliation(data: bytes | str) -> list[InventoryMovement]:
    """Parse a WFS inventory reconciliation export.

    Row 2 of the file is a column-description legend, not data — it's skipped by
    requiring the start date to parse as a date.
    """
    text = data.decode("utf-8-sig") if isinstance(data, bytes) else data
    reader = csv.DictReader(io.StringIO(text))
    out: list[InventoryMovement] = []

    def _clean(value: str | None) -> str | None:
        if value is None:
            return None
        v = value.strip().lstrip("=").strip('"').strip()
        return v or None

    def _int(value: str | None) -> int:
        parsed = _dec(_clean(value))
        return int(parsed) if parsed is not None else 0

    for row in reader:
        start = _clean(row.get("Start Date"))
        if not start:
            continue
        try:
            datetime.fromisoformat(start)
        except ValueError:
            continue  # the legend row

        out.append(
            InventoryMovement(
                gtin=_clean(row.get("GTIN")),
                item_id=_clean(row.get("Item ID")),
                sku=_clean(row.get("Vendor (Seller) SKU")),
                product_name=_clean(row.get("Product Name")),
                fulfillment_center=_clean(row.get("Fulfillment Center")),
                period_start=start,
                period_end=_clean(row.get("End Date")) or start,
                starting_quantity=_int(row.get("Starting Quantity")),
                received=_int(row.get("Received")),
                # `Sold` is reported as a negative (it depletes stock).
                sold=abs(_int(row.get("Sold"))),
                lost=abs(_int(row.get("Lost"))),
                found=_int(row.get("Found")),
                removed=abs(_int(row.get("Removed"))),
                ending_quantity=_int(row.get("Ending Quantity")),
            )
        )
    return out


# MARK: - Orders parser


@dataclass
class OrderLine:
    """One order line from the Walmart orders export."""

    order_date: str
    gtin: str | None
    sku: str | None
    item_id: str | None
    item_name: str | None
    quantity: int
    gmv: Decimal
    status: str | None
    ship_to_state: str | None = None


def parse_walmart_orders(rows: list[dict]) -> list[OrderLine]:
    """Normalize rows from the orders export (XLSX read elsewhere, dicts here).

    Kept dict-in so this module stays free of openpyxl — ``ingest.read_table``
    already handles the workbook, and the pure modules shouldn't grow an
    optional binary dependency.
    """
    out: list[OrderLine] = []
    for row in rows:
        qty = _dec(row.get("QUANTITY")) or _ZERO
        if qty <= 0:
            continue
        out.append(
            OrderLine(
                order_date=str(row.get("ORDER_PLACED_DT") or "")[:10],
                gtin=str(row.get("GTIN") or "").strip() or None,
                sku=str(row.get("VENDOR_SKU") or "").strip() or None,
                item_id=str(row.get("WMT_ITEM_ID") or "").strip() or None,
                item_name=str(row.get("ITEM_NAME") or "").strip() or None,
                quantity=int(qty),
                gmv=_dec(row.get("GMV_AMT")) or _ZERO,
                status=str(row.get("ORDER_STATUS") or "").strip() or None,
                ship_to_state=str(row.get("SHIP_TO_ST") or "").strip() or None,
            )
        )
    return out


# MARK: - Cross-check
#
# Three reports describe the same SKU over overlapping windows and they do not
# agree, because each answers a different question:
#
#   orders            what customers asked for      -> the DEMAND rate
#   inventory `Sold`  what left the warehouse       -> the FULFILLED rate
#   fulfillment fees  what Walmart billed you for   -> the BILLED rate
#
# Ordered > shipped whenever anything is still in flight. Using the billed count
# as a demand estimate systematically under-reads demand by however much is
# sitting in ACKNOWLEDGED, which on a fast mover is days of sales.


def cross_check(
    *,
    orders: list[OrderLine] | None = None,
    movements: list[InventoryMovement] | None = None,
    fees: list[SettlementFee] | None = None,
    gtin: str | None = None,
) -> dict[str, object]:
    """Reconcile order / shipment / billing counts for one SKU.

    Divergence beyond the in-flight backlog is worth surfacing: it usually means
    a lost unit, a cancelled order, or a fee that hasn't posted yet.
    """
    def _match(value: str | None) -> bool:
        if gtin is None or value is None:
            return True
        return value.lstrip("0") == gtin.lstrip("0")

    ordered_units = 0
    delivered = 0
    in_flight = 0
    order_days = 0
    gmv = _ZERO
    if orders:
        selected = [o for o in orders if _match(o.gtin)]
        ordered_units = sum(o.quantity for o in selected)
        gmv = sum((o.gmv for o in selected), _ZERO)
        delivered = sum(
            o.quantity for o in selected if (o.status or "").upper() == "DELIVERED"
        )
        in_flight = ordered_units - delivered
        dates = sorted(o.order_date for o in selected if o.order_date)
        if len(dates) >= 2:
            try:
                order_days = max(
                    (datetime.fromisoformat(dates[-1]) - datetime.fromisoformat(dates[0])).days,
                    1,
                )
            except ValueError:
                order_days = 0

    sold_units = 0
    on_hand = 0
    cover = None
    if movements:
        selected_moves = [m for m in movements if _match(m.gtin)]
        sold_units = sum(m.sold for m in selected_moves)
        on_hand = sum(m.ending_quantity for m in selected_moves)
        covers = [m.months_of_cover for m in selected_moves if m.months_of_cover]
        cover = round(sum(covers) / len(covers), 1) if covers else None

    billed_units = 0
    if fees:
        billed_units = sum(
            f.quantity
            for f in fees
            if f.transaction_type.lower() == "fulfillmentfee" and _match(f.gtin)
        )

    demand_rate = (
        round(ordered_units / order_days * 30.0, 1) if order_days else None
    )

    return {
        "gtin": gtin,
        "ordered_units": ordered_units,
        "delivered_units": delivered,
        "in_flight_units": in_flight,
        "sold_units": sold_units,
        "billed_units": billed_units,
        "order_window_days": order_days,
        "gmv": float(gmv),
        "demand_rate_monthly": demand_rate,
        "units_on_hand": on_hand,
        "months_of_cover": cover,
        # Shipped-but-unbilled, or billed-but-not-shipped. Small numbers are
        # normal timing; a persistent gap is a real discrepancy to chase.
        "shipped_vs_billed_gap": sold_units - billed_units,
        "note": (
            "ordered > shipped by the in-flight backlog; use ordered for demand, "
            "billed for cash"
        ),
    }


# MARK: - Calibration


@dataclass
class FeeObservation:
    """Aggregated actuals for one calibration key."""

    samples: int = 0
    values: list[Decimal] = field(default_factory=list)

    def add(self, value: Decimal) -> None:
        self.samples += 1
        self.values.append(value)

    @property
    def median(self) -> Decimal | None:
        """Median, not mean — one promotional order shouldn't move the estimate."""
        if not self.values:
            return None
        ordered = sorted(self.values)
        mid = len(ordered) // 2
        if len(ordered) % 2 == 1:
            return ordered[mid]
        return (ordered[mid - 1] + ordered[mid]) / Decimal("2")

    @property
    def spread(self) -> Decimal | None:
        """Max − min. A wide spread means the key isn't capturing what varies."""
        if len(self.values) < 2:
            return None
        return max(self.values) - min(self.values)


@dataclass
class FeeCalibration:
    """Observed fees, keyed for lookup by the fee engine.

    Consulted before the published rate tables. An entry backed by a single
    observation is still better than a published rate that demonstrably
    disagrees with your statements — but ``samples`` rides along so the UI can
    distinguish "measured 40 times" from "measured once".
    """

    commission_rate_by_category: dict[str, FeeObservation] = field(default_factory=dict)
    fulfillment_fee_by_sku: dict[str, FeeObservation] = field(default_factory=dict)
    fulfillment_fee_by_product_type: dict[str, FeeObservation] = field(default_factory=dict)
    # Keyed on Walmart's own `Billing Method` — "Under$10" and friends. The most
    # reliable key of the three, because it names the schedule being applied
    # rather than a proxy for it.
    fulfillment_fee_by_billing_method: dict[str, FeeObservation] = field(default_factory=dict)
    storage_fee_by_sku: dict[str, FeeObservation] = field(default_factory=dict)
    orders_seen: int = 0

    @staticmethod
    def _key(value: str | None) -> str | None:
        if not value:
            return None
        return " ".join(value.strip().lower().split()) or None

    def ingest_settlement(self, fees: list[SettlementFee]) -> "FeeCalibration":
        """Learn fulfillment and storage fees from settlement lines.

        Uses ``effective_amount`` (pre-discount) rather than net payable, so a
        promotional week doesn't teach a fee that won't be there next month.
        Keys on ``billing_method`` when present — that's how the Under-$10
        schedule surfaced, and lumping it in with weight-tiered charges would
        have averaged two unrelated fee structures into one wrong number.
        """
        for fee in fees:
            ttype = fee.transaction_type.strip().lower()
            key = fee.sku or fee.gtin
            per_unit = fee.effective_amount / Decimal(max(fee.quantity, 1))
            if ttype == "fulfillmentfee":
                if key:
                    self.fulfillment_fee_by_sku.setdefault(key, FeeObservation()).add(per_unit)
                method = self._key(fee.billing_method)
                if method:
                    self.fulfillment_fee_by_billing_method.setdefault(
                        method, FeeObservation()
                    ).add(per_unit)
            elif "storagefee" in ttype and key and per_unit > 0:
                self.storage_fee_by_sku.setdefault(key, FeeObservation()).add(per_unit)
        return self

    def ingest(self, orders: list[ObservedOrder]) -> "FeeCalibration":
        for order in orders:
            self.orders_seen += 1
            category = self._key(order.contract_category)
            product_type = self._key(order.product_type)
            sku = order.sku or order.gtin

            rate = order.commission_rate_reported or order.effective_commission_rate
            if category and rate is not None and rate > 0:
                self.commission_rate_by_category.setdefault(
                    category, FeeObservation()
                ).add(rate)

            if order.fulfillment_fee > 0:
                per_unit = order.fulfillment_fee / Decimal(max(order.quantity, 1))
                if sku:
                    self.fulfillment_fee_by_sku.setdefault(sku, FeeObservation()).add(per_unit)
                if product_type:
                    self.fulfillment_fee_by_product_type.setdefault(
                        product_type, FeeObservation()
                    ).add(per_unit)

            if order.storage_fee > 0 and sku:
                self.storage_fee_by_sku.setdefault(sku, FeeObservation()).add(
                    order.storage_fee / Decimal(max(order.quantity, 1))
                )
        return self

    # ── Lookups used by the fee engine ────────────────────────────────

    def commission_rate(self, contract_category: str | None) -> Decimal | None:
        obs = self.commission_rate_by_category.get(self._key(contract_category) or "")
        return obs.median if obs else None

    def fulfillment_fee(
        self, sku: str | None = None, product_type: str | None = None
    ) -> tuple[Decimal | None, str]:
        """Observed WFS fulfillment fee. SKU-level beats product-type level.

        Returns ``(fee, basis)`` where basis names which key matched, so a
        verdict can say "fulfillment $4.45 (your actual)" rather than implying
        it came from a rate card.
        """
        if sku:
            obs = self.fulfillment_fee_by_sku.get(sku)
            if obs and obs.median is not None:
                return _money(obs.median), f"observed_sku_n{obs.samples}"
        key = self._key(product_type)
        if key:
            obs = self.fulfillment_fee_by_product_type.get(key)
            if obs and obs.median is not None:
                return _money(obs.median), f"observed_product_type_n{obs.samples}"
        return None, "published_rate_card"

    def storage_fee(self, sku: str | None) -> Decimal | None:
        if not sku:
            return None
        obs = self.storage_fee_by_sku.get(sku)
        return _money(obs.median) if obs and obs.median is not None else None

    def report(self) -> dict[str, object]:
        """Human-readable summary of what the imports actually taught us."""
        return {
            "orders_seen": self.orders_seen,
            "commission_rates": {
                key: {
                    "rate_pct": float(obs.median * 100) if obs.median else None,
                    "samples": obs.samples,
                }
                for key, obs in sorted(self.commission_rate_by_category.items())
            },
            "fulfillment_by_billing_method": {
                key: {"fee": float(obs.median) if obs.median else None, "samples": obs.samples}
                for key, obs in sorted(self.fulfillment_fee_by_billing_method.items())
            },
            "fulfillment_by_product_type": {
                key: {
                    "fee": float(obs.median) if obs.median else None,
                    "samples": obs.samples,
                    "spread": float(obs.spread) if obs.spread is not None else None,
                }
                for key, obs in sorted(self.fulfillment_fee_by_product_type.items())
            },
            "storage_by_sku": {
                key: {"fee": float(obs.median) if obs.median else None, "samples": obs.samples}
                for key, obs in sorted(self.storage_fee_by_sku.items())
            },
        }


def compare_to_published(
    calibration: FeeCalibration,
    published_lookup,
) -> list[dict[str, object]]:
    """Diff observed commission rates against the published table.

    The output is a to-do list for the rate tables: every row is either a
    category where the published number is wrong, or a category where it's
    confirmed. Both are worth knowing — a confirmed rate is the reason to trust
    the table for products you haven't sold yet.

    ``published_lookup`` is a callable taking a category key and returning a
    rate, so this module doesn't have to import the fee tables and create a
    cycle.
    """
    out: list[dict[str, object]] = []
    for category, obs in sorted(calibration.commission_rate_by_category.items()):
        observed = obs.median
        if observed is None:
            continue
        published = published_lookup(category)
        delta = None if published is None else observed - published
        out.append(
            {
                "category": category,
                "observed_pct": float(observed * 100),
                "published_pct": float(published * 100) if published is not None else None,
                "delta_pp": float(delta * 100) if delta is not None else None,
                "samples": obs.samples,
                "agrees": delta is not None and abs(delta) < Decimal("0.0005"),
            }
        )
    return out
