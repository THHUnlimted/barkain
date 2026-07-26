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
    storage_fee_by_sku: dict[str, FeeObservation] = field(default_factory=dict)
    orders_seen: int = 0

    @staticmethod
    def _key(value: str | None) -> str | None:
        if not value:
            return None
        return " ".join(value.strip().lower().split()) or None

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
