"""Selling-plan and subscription modelling.

Pure module. Verified against published US rate cards, July 2026 — see
``PLAN_SCHEDULE_VERSION`` and the per-plan ``source`` note.

## The costing decision that matters

A monthly subscription is a **fixed** cost. The instinct is to amortize it into
per-unit margin — take Amazon's $39.99, divide by expected monthly units, add
it to every row. That is a real and expensive mistake, and it's expensive in
both directions:

- If you already pay the fee, it is **sunk** for the next SKU decision. Loading
  a share of it onto every candidate makes marginal-but-real winners look like
  losers, and you decline orders that would have made money.
- If you don't yet pay it, the fee isn't per-unit at all — it's a threshold
  question. "Does this plan pay for itself?" has a volume answer, not a
  per-unit one.

So this module does two separate things and never mixes them:

1. **Marginal rates.** The plan changes your variable fee — an eBay Store cuts
   the final value fee, Amazon Individual adds $0.99 per item sold. Those *are*
   per-unit and flow straight into the fee engine.
2. **Breakeven volume.** The fixed monthly fee is reported on its own, as the
   number of units (or the amount of fee-savings) at which the plan pays for
   itself. That's a plan-selection answer, surfaced once per channel, not
   smeared across three thousand rows.

``effective_fee_rate()`` is what the fee engine calls. ``plan_breakeven()`` is
what the summary view calls. Nothing amortizes.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

PLAN_SCHEDULE_VERSION = "2026-07-26"

_CENT = Decimal("0.01")
_ZERO = Decimal("0")


def _money(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class SellingPlan:
    """One channel's selling plan and what it changes.

    ``fvf_discount`` is expressed in *percentage points* off the base referral
    or final-value rate (0.009 = 0.9pp), because that's how the marketplaces
    publish it and converting it to a multiplier early is how sign errors get in.
    """

    channel: str
    key: str
    display_name: str
    monthly_fee: Decimal = _ZERO
    per_item_fee: Decimal = _ZERO
    fvf_discount: Decimal = _ZERO
    included_listings: int = 0
    per_listing_fee_over_allowance: Decimal = _ZERO
    source: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "channel": self.channel,
            "key": self.key,
            "display_name": self.display_name,
            "monthly_fee": float(self.monthly_fee),
            "per_item_fee": float(self.per_item_fee),
            "fvf_discount_pp": float(self.fvf_discount * 100),
            "included_listings": self.included_listings,
        }


# ── eBay Store subscriptions ─────────────────────────────────────────
# Monthly fees are the annual-prepay price; month-to-month runs roughly 25%
# higher. FVF discounts are category-dependent and published as a range
# (~0.4–0.9pp for Basic and above); the midpoint is used and flagged as an
# estimate wherever it materially moves a verdict.
# Source: eBay "Store subscription fees" + "Selling fees", US, July 2026.

EBAY_PLANS: dict[str, SellingPlan] = {
    "none": SellingPlan(
        channel="ebay", key="none", display_name="No Store",
        source="eBay selling fees, US, 2026-07",
    ),
    "starter": SellingPlan(
        channel="ebay", key="starter", display_name="Starter Store",
        monthly_fee=Decimal("4.95"), included_listings=250,
        per_listing_fee_over_allowance=Decimal("0.30"),
        source="eBay store subscription fees, US, 2026-07",
    ),
    "basic": SellingPlan(
        channel="ebay", key="basic", display_name="Basic Store",
        monthly_fee=Decimal("21.95"), fvf_discount=Decimal("0.009"),
        included_listings=1000, per_listing_fee_over_allowance=Decimal("0.25"),
        source="eBay store subscription fees, US, 2026-07",
    ),
    "premium": SellingPlan(
        channel="ebay", key="premium", display_name="Premium Store",
        monthly_fee=Decimal("74.95"), fvf_discount=Decimal("0.009"),
        included_listings=10000, per_listing_fee_over_allowance=Decimal("0.10"),
        source="eBay store subscription fees, US, 2026-07",
    ),
    "anchor": SellingPlan(
        channel="ebay", key="anchor", display_name="Anchor Store",
        monthly_fee=Decimal("299.95"), fvf_discount=Decimal("0.009"),
        included_listings=25000, per_listing_fee_over_allowance=Decimal("0.05"),
        source="eBay store subscription fees, US, 2026-07",
    ),
}

# ── Amazon selling plans ─────────────────────────────────────────────
# Individual has no monthly fee but charges $0.99 per item *sold* — a genuinely
# per-unit cost, so it belongs in the fee engine. Professional replaces it with
# a flat monthly fee. Crossover is ~40 units/month, which `plan_breakeven`
# computes rather than hardcoding.
# Source: Amazon Seller Central "Selling plan comparison", US, July 2026.

AMAZON_PLANS: dict[str, SellingPlan] = {
    "individual": SellingPlan(
        channel="amazon", key="individual", display_name="Individual",
        per_item_fee=Decimal("0.99"),
        source="Amazon selling plans, US, 2026-07",
    ),
    "professional": SellingPlan(
        channel="amazon", key="professional", display_name="Professional",
        monthly_fee=Decimal("39.99"),
        source="Amazon selling plans, US, 2026-07",
    ),
}

# ── Walmart ──────────────────────────────────────────────────────────
# No monthly subscription or per-item plan fee — Walmart Marketplace monetizes
# entirely through referral fees and, if you use it, WFS. Modelled explicitly
# rather than omitted so the plan lookup is total across channels.

WALMART_PLANS: dict[str, SellingPlan] = {
    "standard": SellingPlan(
        channel="walmart", key="standard", display_name="Marketplace (no monthly fee)",
        source="Walmart Marketplace fee structure, US, 2026-07",
    ),
}

ALL_PLANS: dict[str, dict[str, SellingPlan]] = {
    "ebay": EBAY_PLANS,
    "amazon": AMAZON_PLANS,
    "walmart": WALMART_PLANS,
}

DEFAULT_PLAN_KEYS: dict[str, str] = {
    "ebay": "none",
    "amazon": "individual",
    "walmart": "standard",
}


def get_plan(channel: str, key: str | None = None) -> SellingPlan:
    """Look up a plan, falling back to the channel's no-subscription default."""
    plans = ALL_PLANS.get(channel, {})
    if not plans:
        return SellingPlan(channel=channel, key="unknown", display_name="Unknown")
    resolved = key or DEFAULT_PLAN_KEYS.get(channel, "")
    return plans.get(resolved) or plans[DEFAULT_PLAN_KEYS.get(channel, next(iter(plans)))]


@dataclass(frozen=True)
class PlanSelection:
    """Which plan the seller holds on each channel.

    ``already_subscribed`` is the switch that makes the sunk-cost treatment
    correct. When True, the monthly fee is out of scope for a per-SKU decision
    entirely and only the marginal rate applies — which is the whole point.
    """

    ebay: str = "none"
    amazon: str = "individual"
    walmart: str = "standard"
    already_subscribed: bool = True

    def for_channel(self, channel: str) -> SellingPlan:
        return get_plan(channel, getattr(self, channel, None))

    @classmethod
    def from_dict(cls, data: dict | None) -> "PlanSelection":
        if not data:
            return cls()
        return cls(
            ebay=str(data.get("ebay") or "none"),
            amazon=str(data.get("amazon") or "individual"),
            walmart=str(data.get("walmart") or "standard"),
            already_subscribed=bool(data.get("already_subscribed", True)),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "ebay": self.ebay,
            "amazon": self.amazon,
            "walmart": self.walmart,
            "already_subscribed": self.already_subscribed,
        }


def effective_fee_rate(base_rate: Decimal, plan: SellingPlan) -> Decimal:
    """Apply a plan's discount to a base referral / final-value rate.

    Floored at zero — a discount larger than the base rate is a data error, and
    a negative fee would silently manufacture profit.
    """
    return max(_ZERO, base_rate - plan.fvf_discount)


def per_unit_plan_fee(plan: SellingPlan) -> Decimal:
    """The plan's genuinely per-unit charge. Not the monthly fee."""
    return plan.per_item_fee


@dataclass(frozen=True)
class PlanBreakeven:
    """At what volume a paid plan beats the free one.

    Two numbers, because there are two ways a plan pays off and sellers care
    about different ones: ``breakeven_units`` for plans whose benefit is
    replacing a per-item fee (Amazon), ``breakeven_gmv`` for plans whose benefit
    is a percentage discount (eBay Stores).
    """

    channel: str
    from_plan: str
    to_plan: str
    monthly_fee_delta: Decimal
    breakeven_units: float | None
    breakeven_gmv: Decimal | None
    note: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "channel": self.channel,
            "from_plan": self.from_plan,
            "to_plan": self.to_plan,
            "monthly_fee_delta": float(self.monthly_fee_delta),
            "breakeven_units": self.breakeven_units,
            "breakeven_gmv": float(self.breakeven_gmv)
            if self.breakeven_gmv is not None
            else None,
            "note": self.note,
        }


def plan_breakeven(
    channel: str, from_key: str, to_key: str, *, avg_sale_price: Decimal | None = None
) -> PlanBreakeven:
    """Volume at which upgrading from ``from_key`` to ``to_key`` pays for itself.

    Reported once per channel on the list summary, never folded into a row's
    margin. ``avg_sale_price`` lets the GMV answer be restated in units, which
    is the form people actually reason in.
    """
    a, b = get_plan(channel, from_key), get_plan(channel, to_key)
    fee_delta = b.monthly_fee - a.monthly_fee
    per_item_saving = a.per_item_fee - b.per_item_fee
    rate_saving = b.fvf_discount - a.fvf_discount

    breakeven_units: float | None = None
    breakeven_gmv: Decimal | None = None
    note = ""

    if fee_delta <= 0:
        note = "No additional monthly cost — the upgrade is free or cheaper."
        return PlanBreakeven(channel, a.key, b.key, fee_delta, 0.0, _ZERO, note)

    if per_item_saving > 0:
        breakeven_units = float(fee_delta / per_item_saving)
        note = (
            f"Pays off above ~{breakeven_units:.0f} units/month "
            f"(saves ${per_item_saving}/item)."
        )

    if rate_saving > 0:
        breakeven_gmv = _money(fee_delta / rate_saving)
        if avg_sale_price and avg_sale_price > 0:
            units = float(breakeven_gmv / avg_sale_price)
            note = (
                f"Pays off above ~${breakeven_gmv} monthly sales "
                f"(~{units:.0f} units at ${avg_sale_price}), "
                f"from a {rate_saving * 100:.1f}pp fee cut."
            )
        else:
            note = (
                f"Pays off above ~${breakeven_gmv} monthly sales "
                f"from a {rate_saving * 100:.1f}pp fee cut."
            )

    if breakeven_units is None and breakeven_gmv is None:
        note = "No marginal saving — the upgrade buys listings or features, not fees."

    return PlanBreakeven(channel, a.key, b.key, fee_delta, breakeven_units, breakeven_gmv, note)


def recommend_plan(
    channel: str, *, monthly_units: float, avg_sale_price: Decimal
) -> tuple[SellingPlan, list[PlanBreakeven]]:
    """Cheapest total-cost plan at a given monthly volume, plus the comparisons.

    Total monthly cost = fixed fee + per-item fees + the variable-rate
    difference. Evaluated at the *account* level, which is the only level where
    a subscription decision makes sense.
    """
    plans = ALL_PLANS.get(channel, {})
    if not plans:
        return get_plan(channel), []

    units = Decimal(str(max(monthly_units, 0)))
    gmv = units * avg_sale_price

    def total_cost(plan: SellingPlan) -> Decimal:
        listing_overage = _ZERO
        if plan.included_listings and units > plan.included_listings:
            listing_overage = (
                Decimal(int(units) - plan.included_listings)
                * plan.per_listing_fee_over_allowance
            )
        # `fvf_discount` is a saving, so it subtracts from total cost.
        return (
            plan.monthly_fee
            + plan.per_item_fee * units
            + listing_overage
            - plan.fvf_discount * gmv
        )

    best = min(plans.values(), key=total_cost)
    baseline = DEFAULT_PLAN_KEYS.get(channel, best.key)
    comparisons = [
        plan_breakeven(channel, baseline, plan.key, avg_sale_price=avg_sale_price)
        for plan in plans.values()
        if plan.key != baseline
    ]
    return best, comparisons
