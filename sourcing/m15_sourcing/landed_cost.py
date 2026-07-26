"""Landed cost — what a unit actually costs you, standing in your warehouse.

Pure module. ``Decimal`` throughout.

## Why the distributor's price is the wrong number

The number on the price list is the *invoice* cost. By the time a unit is
sellable it has also absorbed freight, prep, packaging, duty, payment fees, and
a share of the units that arrived broken or came back. Scoring on invoice cost
systematically overstates margin — and it overstates it *unevenly*, because a
14 lb air purifier absorbs far more freight per unit than a 4 oz phone case at
the same invoice price. That unevenness is what makes it dangerous: it doesn't
shift every row by the same amount, it reorders them.

Every component here is optional. Supply what you know; the rest stays zero and
the row is flagged so an under-specified cost never masquerades as a precise
one. A ``LandedCost`` with nothing but ``invoice_cost`` behaves exactly like the
old raw-cost path, which is what makes this a drop-in.

## Allocation

Costs arrive at three different grains and have to be pushed down to the unit:

- **Per shipment** — LTL freight, one pallet, one customs entry. Allocated
  across the units in the shipment. Allocation basis matters: freight is
  usually billed by weight or cube, so a shipment carrying one heavy SKU and
  one light one should not split it evenly. ``allocate_shipment_cost`` supports
  ``per_unit`` / ``by_weight`` / ``by_cube``.
- **Per case** — a master carton's inbound handling, a case-level label.
  Divided by case pack.
- **Per unit** — polybag, label, inspection, the unit's own box.

## Rates vs. reserves

``duty_rate`` and ``payment_fee_rate`` are applied to the goods value — they're
real cash. ``shrink_rate`` and ``return_rate`` are *reserves*: you don't pay
them per unit, you lose that fraction of units. The correct treatment is to
inflate the cost of the surviving units, not to add a fee — which is why they
divide rather than multiply. Getting this backwards understates the hit at
exactly the rates that matter (a 6% return rate is a 6.4% cost increase, not
6%).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

_CENT = Decimal("0.01")
_ZERO = Decimal("0")
_ONE = Decimal("1")


def _money(value: Decimal | float | int) -> Decimal:
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def _dec(value: Decimal | float | int | None) -> Decimal:
    if value is None:
        return _ZERO
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


# MARK: - Shipment allocation

ALLOCATION_PER_UNIT = "per_unit"
ALLOCATION_BY_WEIGHT = "by_weight"
ALLOCATION_BY_CUBE = "by_cube"


def allocate_shipment_cost(
    total_cost: Decimal,
    *,
    units: int,
    basis: str = ALLOCATION_PER_UNIT,
    this_measure: Decimal | None = None,
    total_measure: Decimal | None = None,
) -> Decimal:
    """Push a shipment-level cost down to one unit.

    ``this_measure`` / ``total_measure`` are the weight or cube of this SKU's
    portion and of the whole shipment. With ``by_weight``, a 14 lb item in a
    shipment totalling 700 lb absorbs 2% of the freight regardless of how many
    units of it there are — which is how the carrier actually billed it.

    Falls back to even per-unit allocation when the measures aren't supplied,
    because a rough allocation beats leaving freight out entirely.
    """
    if units <= 0:
        return _ZERO
    total = _dec(total_cost)
    if basis in (ALLOCATION_BY_WEIGHT, ALLOCATION_BY_CUBE):
        this_m, total_m = _dec(this_measure), _dec(total_measure)
        if this_m > 0 and total_m > 0:
            return total * (this_m / total_m) / Decimal(units)
    return total / Decimal(units)


# MARK: - Landed cost


@dataclass(frozen=True)
class LandedCost:
    """The full cost stack for one sellable unit.

    Only ``invoice_cost`` is required. Everything else defaults to zero, and
    ``assumptions`` records which components were left unspecified so a verdict
    can say "this margin assumes zero freight" instead of quietly implying the
    freight was measured and happened to be nothing.
    """

    invoice_cost: Decimal

    # ── Per-unit direct costs ────────────────────────────────────────
    inbound_freight_per_unit: Decimal = _ZERO
    prep_per_unit: Decimal = _ZERO           # labeling, bundling, polybagging labor
    packaging_per_unit: Decimal = _ZERO      # the box/bag itself
    inspection_per_unit: Decimal = _ZERO     # QC on receipt
    other_per_unit: Decimal = _ZERO

    # ── Per-case costs, divided down by case_pack ────────────────────
    per_case_cost: Decimal = _ZERO
    case_pack: int | None = None

    # ── Rates on goods value (real cash out) ─────────────────────────
    duty_rate: Decimal = _ZERO               # tariff / customs, share of invoice
    payment_fee_rate: Decimal = _ZERO        # card or FX fee paying the supplier

    # ── Reserves (units lost, not fees paid) ─────────────────────────
    shrink_rate: Decimal = _ZERO             # damaged / lost in transit
    return_rate: Decimal = _ZERO             # sold then returned unsellable

    assumptions: tuple[str, ...] = field(default_factory=tuple)

    # ── Derived ──────────────────────────────────────────────────────

    @property
    def case_allocated_per_unit(self) -> Decimal:
        if not self.case_pack or self.case_pack <= 0:
            return _ZERO
        return _dec(self.per_case_cost) / Decimal(self.case_pack)

    @property
    def direct_adders(self) -> Decimal:
        """Everything billed per unit or pushed down to the unit."""
        return (
            _dec(self.inbound_freight_per_unit)
            + _dec(self.prep_per_unit)
            + _dec(self.packaging_per_unit)
            + _dec(self.inspection_per_unit)
            + _dec(self.other_per_unit)
            + self.case_allocated_per_unit
        )

    @property
    def rate_adders(self) -> Decimal:
        """Duty and payment fees, applied to the goods value."""
        return _dec(self.invoice_cost) * (_dec(self.duty_rate) + _dec(self.payment_fee_rate))

    @property
    def cost_before_reserves(self) -> Decimal:
        return _dec(self.invoice_cost) + self.direct_adders + self.rate_adders

    @property
    def survival_rate(self) -> Decimal:
        """Fraction of purchased units that end up sold and kept.

        Clamped to a floor so a nonsense 100% shrink rate can't divide by zero
        and produce an infinite cost.
        """
        survival = (_ONE - _dec(self.shrink_rate)) * (_ONE - _dec(self.return_rate))
        return max(survival, Decimal("0.01"))

    @property
    def total(self) -> Decimal:
        """Landed cost of one *sellable* unit.

        Reserves divide rather than add: if 6% of units come back unsellable,
        the 94 that sell have to carry the cost of all 100.
        """
        return _money(self.cost_before_reserves / self.survival_rate)

    @property
    def uplift_pct(self) -> Decimal:
        """How much the true cost exceeds the invoice price, as a percentage.

        Worth surfacing on its own: a buyer who has never costed freight is
        usually shocked by this number on heavy items, and it explains why two
        rows with identical invoice cost score differently.
        """
        invoice = _dec(self.invoice_cost)
        if invoice <= 0:
            return _ZERO
        return _money((self.total - invoice) / invoice * Decimal("100"))

    @property
    def is_fully_specified(self) -> bool:
        """True when no cost component was left to default."""
        return not self.assumptions

    def as_dict(self) -> dict[str, object]:
        return {
            "invoice_cost": float(_dec(self.invoice_cost)),
            "inbound_freight_per_unit": float(_dec(self.inbound_freight_per_unit)),
            "prep_per_unit": float(_dec(self.prep_per_unit)),
            "packaging_per_unit": float(_dec(self.packaging_per_unit)),
            "inspection_per_unit": float(_dec(self.inspection_per_unit)),
            "per_case_allocated": float(self.case_allocated_per_unit),
            "other_per_unit": float(_dec(self.other_per_unit)),
            "duty_rate": float(_dec(self.duty_rate)),
            "payment_fee_rate": float(_dec(self.payment_fee_rate)),
            "shrink_rate": float(_dec(self.shrink_rate)),
            "return_rate": float(_dec(self.return_rate)),
            "cost_before_reserves": float(_money(self.cost_before_reserves)),
            "survival_rate": float(self.survival_rate),
            "total": float(self.total),
            "uplift_pct": float(self.uplift_pct),
            "assumptions": list(self.assumptions),
        }


# MARK: - Defaults profile


@dataclass(frozen=True)
class CostProfile:
    """A buyer's standing cost assumptions, applied to every row of every list.

    Set once in settings, overridden per list when a particular supplier has
    different terms. The defaults are deliberately zero rather than "typical" —
    an invented freight number that happens to be wrong is worse than a visible
    gap, because it looks like it was measured.
    """

    inbound_freight_per_lb: Decimal = _ZERO
    inbound_freight_per_unit: Decimal = _ZERO
    prep_per_unit: Decimal = _ZERO
    packaging_per_unit: Decimal = _ZERO
    inspection_per_unit: Decimal = _ZERO
    per_case_cost: Decimal = _ZERO
    duty_rate: Decimal = _ZERO
    payment_fee_rate: Decimal = _ZERO
    shrink_rate: Decimal = _ZERO
    return_rate: Decimal = _ZERO

    @classmethod
    def from_dict(cls, data: dict | None) -> "CostProfile":
        if not data:
            return cls()
        kwargs: dict[str, Decimal] = {}
        for name in cls.__dataclass_fields__:
            if data.get(name) is not None:
                try:
                    kwargs[name] = Decimal(str(data[name]))
                except (ArithmeticError, ValueError):
                    pass
        return cls(**kwargs)

    def as_dict(self) -> dict[str, float]:
        return {
            name: float(getattr(self, name)) for name in self.__dataclass_fields__
        }


def build_landed_cost(
    *,
    invoice_cost: Decimal,
    profile: CostProfile | None = None,
    weight_lb: Decimal | None = None,
    case_pack: int | None = None,
    overrides: dict | None = None,
) -> LandedCost:
    """Compose a ``LandedCost`` from a profile, the item's weight, and overrides.

    Freight resolves in priority order: an explicit per-unit override, then
    ``inbound_freight_per_lb × weight``, then the profile's flat per-unit rate.
    Weight-based is preferred wherever a weight exists because it's the only
    version that distinguishes the air purifier from the phone case.
    """
    profile = profile or CostProfile()
    overrides = overrides or {}
    assumptions: list[str] = []

    def _override(name: str) -> Decimal | None:
        raw = overrides.get(name)
        if raw is None:
            return None
        try:
            return Decimal(str(raw))
        except (ArithmeticError, ValueError):
            return None

    freight = _override("inbound_freight_per_unit")
    if freight is None:
        if profile.inbound_freight_per_lb > 0 and weight_lb and weight_lb > 0:
            freight = profile.inbound_freight_per_lb * weight_lb
        elif profile.inbound_freight_per_unit > 0:
            freight = profile.inbound_freight_per_unit
            if weight_lb is None:
                assumptions.append("freight_flat_rate_no_weight")
        else:
            freight = _ZERO
            assumptions.append("no_inbound_freight")

    prep = _override("prep_per_unit") or profile.prep_per_unit
    packaging = _override("packaging_per_unit") or profile.packaging_per_unit
    inspection = _override("inspection_per_unit") or profile.inspection_per_unit
    per_case = _override("per_case_cost") or profile.per_case_cost

    if prep == 0 and packaging == 0:
        assumptions.append("no_prep_or_packaging")
    if profile.return_rate == 0 and not _override("return_rate"):
        assumptions.append("no_return_reserve")

    return LandedCost(
        invoice_cost=invoice_cost,
        inbound_freight_per_unit=freight,
        prep_per_unit=prep,
        packaging_per_unit=packaging,
        inspection_per_unit=inspection,
        per_case_cost=per_case,
        case_pack=case_pack,
        duty_rate=_override("duty_rate") or profile.duty_rate,
        payment_fee_rate=_override("payment_fee_rate") or profile.payment_fee_rate,
        shrink_rate=_override("shrink_rate") or profile.shrink_rate,
        return_rate=_override("return_rate") or profile.return_rate,
        assumptions=tuple(dict.fromkeys(assumptions)),
    )
