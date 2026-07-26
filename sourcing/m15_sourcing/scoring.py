"""Verdict scoring — thresholds in, PASS / WATCH / FAIL out.

Pure module. Deterministic, zero LLM: per ``docs/FEATURES.md``'s classification
rule, a profit calculator is Traditional. The same posture as M6 — an answer a
seller is going to spend $4,000 on should be reproducible and auditable, not
resampled.

## Why three outcomes and not two

A binary pass/fail throws away the most interesting rows. Something that clears
every profit threshold but has ``UNKNOWN`` demand isn't a failure — it's a row
where the snapshot database hasn't run long enough yet, and it should come back
next week. ``WATCH`` is where those live, and it's also the queue that tells the
snapshot worker which listings are worth polling.

## Ranking: velocity first

Rows sort by **annualized ROI**, not margin and not raw monthly profit.

The reasoning: for a capital-constrained buyer the scarce resource is cash, and
what matters is how many times a year that cash comes back with a profit
attached. A 60% margin that turns over twice a year is a worse use of a
purchase order than 22% that turns over eleven times — the second one earns
more on the same dollar, and it does it with less shelf risk, less price-war
exposure, and less chance of holding dead stock into Q4 storage rates.

    annualized_roi = roi_pct × 365 ÷ (days_to_sell_through + reorder_lead_time)

``days_to_sell_through`` is how long the minimum order takes to clear at the
estimated rate. That denominator is what makes a fast item beat a fat one, and
it's why a $3/unit item that moves 400 times a month outranks a $40/unit item
that moves six.

The lead time in the denominator is not a detail. Capital doesn't redeploy the
moment the last unit ships — it redeploys when the next case lands. An item
that clears in six days on a three-week reorder cycle turns over about 14 times
a year, not 60, and the version without lead time produces four-figure
percentages that reorder the entire list on an artifact of the formula.

``RankingPolicy`` keeps the alternatives available — ``monthly_profit`` for
buyers optimizing absolute dollars, ``margin`` for anyone who insists — but
``velocity`` is the default and the one the thresholds are tuned for.

Rows whose demand is unknown get ranked on a ``UNKNOWN_DEMAND_UNITS`` placeholder
so they interleave sensibly rather than sinking to the bottom — but they can
never be ``PASS``, so the ranking never promotes them past a measured row.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

from m15_sourcing.demand import DemandEstimate, PriceStability
from m15_sourcing.fees import ChannelEconomics


class Verdict(str, Enum):
    PASS = "pass"
    WATCH = "watch"
    FAIL = "fail"


# Placeholder monthly units for ranking rows with no demand signal. Low enough
# that a measured winner always outranks an unmeasured one, high enough that
# unmeasured rows don't all collapse to a zero-profit tie.
UNKNOWN_DEMAND_UNITS = 10.0

# Ranking policies. `velocity` is the default — see the module docstring.
RANK_BY_VELOCITY = "velocity"
RANK_BY_MONTHLY_PROFIT = "monthly_profit"
RANK_BY_MARGIN = "margin"

# Cap on annualized ROI so a row estimated to clear in half a day doesn't
# produce a five-figure percentage and dominate the sort on what is really
# estimator noise. Anything at the cap is "as fast as we can tell", and the
# tiebreak falls through to projected monthly profit.
_MAX_ANNUALIZED_ROI = Decimal("2000")

# Floor on sell-through days for the same reason: sub-day turnover is below the
# resolution of any signal we have.
_MIN_SELL_THROUGH_DAYS = 1.0


@dataclass(frozen=True)
class Thresholds:
    """The buy box, in the literal sense — what you'll accept.

    Defaults are the numbers a wholesale buyer typically runs. They're
    deliberately strict: the whole point of crunching 3,000 rows is that you
    can afford to be picky.
    """

    min_net_profit: Decimal = Decimal("3.00")
    min_roi_pct: Decimal = Decimal("25.0")
    min_margin_pct: Decimal | None = None
    min_monthly_unit_share: float = 30.0
    max_seller_count: int | None = None
    require_price_stability: bool = True
    require_listing_exists: bool = True
    # Velocity gate. The minimum order has to clear within this many days or
    # the row fails regardless of how good the margin looks — that's the
    # "faster beats fatter" preference expressed as a hard threshold rather
    # than only as a sort order.
    max_days_to_sell_through: float | None = 90.0
    # Minimum annualized ROI. 25% ROI on a 90-day turn is ~101% annualized;
    # the default here (150%) is deliberately above that, so clearing the
    # per-order ROI bar is necessary but not sufficient when the item is slow.
    min_annualized_roi_pct: Decimal | None = Decimal("150.0")
    # Days between placing a reorder and having sellable stock again. Part of
    # the turn cycle, not of sell-through — see `annualized_roi`. Two weeks is
    # a common domestic-distributor default; overseas sourcing is 45-90.
    reorder_lead_time_days: float = 14.0
    ranking_policy: str = "velocity"
    # Cash you're willing to tie up in one SKU's minimum order. A row that
    # passes every ratio but needs a $9,000 pallet is not a candidate for a
    # buyer with a $5,000 budget, and it should say so rather than rank first.
    max_capital_per_sku: Decimal | None = None

    @classmethod
    def from_dict(cls, data: dict | None) -> "Thresholds":
        """Build from a JSONB blob, ignoring unknown keys and bad types."""
        if not data:
            return cls()
        kwargs: dict[str, object] = {}
        for name in (
            "min_net_profit", "min_roi_pct", "min_margin_pct", "max_capital_per_sku",
            "min_annualized_roi_pct",
        ):
            if data.get(name) is not None:
                try:
                    kwargs[name] = Decimal(str(data[name]))
                except (ArithmeticError, ValueError):
                    pass
        for name in (
            "min_monthly_unit_share", "max_days_to_sell_through",
            "reorder_lead_time_days",
        ):
            if data.get(name) is not None:
                try:
                    kwargs[name] = float(data[name])
                except (TypeError, ValueError):
                    pass
        if data.get("ranking_policy") in (
            RANK_BY_VELOCITY, RANK_BY_MONTHLY_PROFIT, RANK_BY_MARGIN
        ):
            kwargs["ranking_policy"] = data["ranking_policy"]
        if data.get("max_seller_count") is not None:
            try:
                kwargs["max_seller_count"] = int(data["max_seller_count"])
            except (TypeError, ValueError):
                pass
        for name in ("require_price_stability", "require_listing_exists"):
            if data.get(name) is not None:
                kwargs[name] = bool(data[name])
        return cls(**kwargs)  # type: ignore[arg-type]

    def as_dict(self) -> dict[str, object]:
        return {
            "min_net_profit": float(self.min_net_profit),
            "min_roi_pct": float(self.min_roi_pct),
            "min_margin_pct": float(self.min_margin_pct)
            if self.min_margin_pct is not None
            else None,
            "min_monthly_unit_share": self.min_monthly_unit_share,
            "max_seller_count": self.max_seller_count,
            "require_price_stability": self.require_price_stability,
            "require_listing_exists": self.require_listing_exists,
            "max_capital_per_sku": float(self.max_capital_per_sku)
            if self.max_capital_per_sku is not None
            else None,
            "max_days_to_sell_through": self.max_days_to_sell_through,
            "reorder_lead_time_days": self.reorder_lead_time_days,
            "min_annualized_roi_pct": float(self.min_annualized_roi_pct)
            if self.min_annualized_roi_pct is not None
            else None,
            "ranking_policy": self.ranking_policy,
        }


# Brand-access states that change the verdict. See docs/SOURCING_SCANNER.md §7 —
# a restricted brand is *demoted, not hidden*: knowing there's a $9/unit spread
# behind a gate is exactly what tells you which gating application to file.
BRAND_AUTHORIZED = "authorized"
BRAND_RESTRICTED = "restricted"
BRAND_PENDING = "pending"
BRAND_UNKNOWN = "unknown"


@dataclass
class ScoredChannel:
    """One channel's verdict for one row."""

    economics: ChannelEconomics
    demand: DemandEstimate
    stability: PriceStability
    seller_count: int | None
    verdict: Verdict
    reasons: list[str] = field(default_factory=list)
    passed: list[str] = field(default_factory=list)
    unit_share: float | None = None
    projected_monthly_profit: float | None = None
    days_to_sell_through: float | None = None
    annualized_roi_pct: float | None = None
    inventory_turns_per_year: float | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "economics": self.economics.as_dict(),
            "demand": self.demand.as_dict(),
            "stability": self.stability.as_dict(),
            "seller_count": self.seller_count,
            "verdict": self.verdict.value,
            "reasons": self.reasons,
            "passed": self.passed,
            "unit_share": self.unit_share,
            "projected_monthly_profit": self.projected_monthly_profit,
            "days_to_sell_through": self.days_to_sell_through,
            "annualized_roi_pct": self.annualized_roi_pct,
            "inventory_turns_per_year": self.inventory_turns_per_year,
        }


def sell_through_days(order_units: int | None, monthly_unit_share: float | None) -> float | None:
    """How many days the minimum order takes to clear at the estimated rate.

    The denominator of everything velocity-related. ``None`` when either input
    is missing — an unknown turn rate must not silently become a fast one.
    """
    if not order_units or order_units <= 0:
        return None
    if not monthly_unit_share or monthly_unit_share <= 0:
        return None
    days = order_units / (monthly_unit_share / 30.0)
    return round(max(days, _MIN_SELL_THROUGH_DAYS), 1)


def annualized_roi(
    roi_pct: Decimal, days: float | None, reorder_lead_time_days: float = 0.0
) -> float | None:
    """ROI per turn, scaled to how many turns a year buys.

    This is the number that reconciles "high margin" and "sells fast" into one
    comparable figure, and it's why a thin fast mover can legitimately outrank
    a fat slow one instead of the two being incomparable.

    **The cycle is sell-through plus lead time, not sell-through alone.** An
    item that clears its case in six days does not turn over sixty times a
    year — it turns over as fast as you can get the next case, and if the
    supplier takes three weeks that's the real denominator. Ignoring lead time
    produces spectacular four-figure percentages for fast movers on slow
    supply chains, which is both wrong and the kind of wrong that reorders the
    whole list.
    """
    if days is None or days <= 0:
        return None
    cycle = Decimal(str(days)) + Decimal(str(max(reorder_lead_time_days, 0.0)))
    if cycle <= 0:
        return None
    turns = Decimal("365") / cycle
    value = roi_pct * turns
    # Clamped at both ends: an unbounded negative is as distorting to a sort
    # as an unbounded positive, and neither carries information past the cap.
    return float(max(-_MAX_ANNUALIZED_ROI, min(value, _MAX_ANNUALIZED_ROI)))


def score_channel(
    *,
    economics: ChannelEconomics,
    demand: DemandEstimate,
    stability: PriceStability,
    seller_count: int | None,
    thresholds: Thresholds,
    listing_exists: bool = True,
    minimum_buy_cost: Decimal | None = None,
    minimum_buy_units: int | None = None,
    brand_status: str = BRAND_UNKNOWN,
) -> ScoredChannel:
    """Apply thresholds to one channel's economics and return a verdict.

    The distinction that matters: a **failed** check is a reason the row is bad
    (it loses money, nobody buys it, twelve sellers are already fighting over
    it). A **soft** check is a reason we can't tell yet (no demand data, no
    price history) — those produce ``WATCH``, which means "re-crunch after the
    snapshot worker has run", not "no".
    """
    hard_fails: list[str] = []
    soft_flags: list[str] = []
    passed: list[str] = []

    if not listing_exists:
        return ScoredChannel(
            economics=economics,
            demand=demand,
            stability=stability,
            seller_count=seller_count,
            verdict=Verdict.FAIL if thresholds.require_listing_exists else Verdict.WATCH,
            reasons=["no active listing found on this channel"],
            unit_share=None,
            projected_monthly_profit=None,
        )

    # ── Profitability ────────────────────────────────────────────────
    net = economics.net_profit
    if net < thresholds.min_net_profit:
        hard_fails.append(
            f"net profit ${net} below ${thresholds.min_net_profit} minimum"
        )
    else:
        passed.append(f"net profit ${net}/unit")

    roi = economics.roi_pct
    if roi < thresholds.min_roi_pct:
        hard_fails.append(f"ROI {roi}% below {thresholds.min_roi_pct}% minimum")
    else:
        passed.append(f"ROI {roi}%")

    if thresholds.min_margin_pct is not None:
        if economics.margin_pct < thresholds.min_margin_pct:
            hard_fails.append(
                f"margin {economics.margin_pct}% below {thresholds.min_margin_pct}% minimum"
            )
        else:
            passed.append(f"margin {economics.margin_pct}%")

    # ── Capital commitment ───────────────────────────────────────────
    if thresholds.max_capital_per_sku is not None and minimum_buy_cost is not None:
        if minimum_buy_cost > thresholds.max_capital_per_sku:
            hard_fails.append(
                f"minimum order ${minimum_buy_cost:.2f} exceeds "
                f"${thresholds.max_capital_per_sku} per-SKU capital limit"
            )
        else:
            passed.append(f"minimum order ${minimum_buy_cost:.2f}")

    # ── Competition ──────────────────────────────────────────────────
    if thresholds.max_seller_count is not None and seller_count is not None:
        if seller_count > thresholds.max_seller_count:
            hard_fails.append(
                f"{seller_count} sellers already on the listing "
                f"(limit {thresholds.max_seller_count})"
            )
        else:
            passed.append(f"{seller_count} competing seller(s)")

    # ── Demand ───────────────────────────────────────────────────────
    unit_share = demand.unit_share(seller_count)
    if unit_share is None:
        soft_flags.append("no demand signal yet — needs snapshot history")
    elif not demand.is_actionable:
        soft_flags.append(
            f"demand is a {demand.confidence.value} estimate "
            f"(~{unit_share}/mo share) — not strong enough to commit on"
        )
    elif unit_share < thresholds.min_monthly_unit_share:
        hard_fails.append(
            f"estimated {unit_share} units/month share below "
            f"{thresholds.min_monthly_unit_share} minimum"
        )
    else:
        passed.append(f"~{unit_share} units/month share")

    # ── Velocity ─────────────────────────────────────────────────────
    # The preference the whole tool is tuned for: how fast the money comes
    # back, not how much of it comes back per unit.
    days_to_clear = sell_through_days(minimum_buy_units, unit_share)
    annualized = annualized_roi(roi, days_to_clear, thresholds.reorder_lead_time_days)
    cycle_days = (
        days_to_clear + thresholds.reorder_lead_time_days if days_to_clear else None
    )
    turns = round(365.0 / cycle_days, 1) if cycle_days else None

    if days_to_clear is None:
        soft_flags.append("can't estimate sell-through — no order size or no demand rate")
    else:
        if thresholds.max_days_to_sell_through is not None:
            if days_to_clear > thresholds.max_days_to_sell_through:
                hard_fails.append(
                    f"minimum order takes ~{days_to_clear:.0f} days to clear "
                    f"(limit {thresholds.max_days_to_sell_through:.0f})"
                )
            else:
                passed.append(
                    f"clears in ~{days_to_clear:.0f} days "
                    f"({turns} turns/yr incl. {thresholds.reorder_lead_time_days:.0f}d lead time)"
                )

        if thresholds.min_annualized_roi_pct is not None and annualized is not None:
            if Decimal(str(annualized)) < thresholds.min_annualized_roi_pct:
                hard_fails.append(
                    f"annualized ROI {annualized:.0f}% below "
                    f"{thresholds.min_annualized_roi_pct}% — the margin is fine, "
                    f"the money just turns over too slowly"
                )
            else:
                passed.append(f"annualized ROI {annualized:.0f}%")

    # ── Price stability ──────────────────────────────────────────────
    if thresholds.require_price_stability:
        if stability.observations < 3:
            soft_flags.append("price history too short to judge stability")
        elif not stability.is_stable:
            hard_fails.append(
                f"buy-box price is volatile "
                f"(CV {stability.coefficient_of_variation}, "
                f"${stability.min_price}–${stability.max_price})"
            )
        else:
            passed.append("price stable")

    # ── Brand access ─────────────────────────────────────────────────
    if brand_status == BRAND_RESTRICTED:
        soft_flags.append("brand is gated or restricted — sourcing approval required")
    elif brand_status == BRAND_PENDING:
        soft_flags.append("distributor inquiry sent, awaiting response")
    elif brand_status == BRAND_UNKNOWN:
        soft_flags.append("no confirmed distributor for this brand yet")
    else:
        passed.append("authorized distributor on file")

    # ── Assumptions ride along as soft flags ─────────────────────────
    for assumption in economics.assumptions:
        if assumption in ("assumed_weight", "assumed_cubic_feet"):
            soft_flags.append(f"fee estimate rests on {assumption.replace('_', ' ')}")

    if hard_fails:
        verdict = Verdict.FAIL
    elif soft_flags:
        verdict = Verdict.WATCH
    else:
        verdict = Verdict.PASS

    ranking_units = unit_share if unit_share is not None else UNKNOWN_DEMAND_UNITS
    projected = round(float(net) * ranking_units, 2) if net > 0 else round(float(net), 2)

    return ScoredChannel(
        economics=economics,
        demand=demand,
        stability=stability,
        seller_count=seller_count,
        verdict=verdict,
        reasons=hard_fails + soft_flags,
        passed=passed,
        unit_share=unit_share,
        projected_monthly_profit=projected,
        days_to_sell_through=days_to_clear,
        annualized_roi_pct=annualized,
        inventory_turns_per_year=turns,
    )


# MARK: - Row-level roll-up


@dataclass
class ScoredRow:
    """A distributor row scored across every channel we could price it on."""

    row_index: int
    gtin14: str | None
    description: str | None
    brand: str | None
    unit_cost: Decimal | None
    minimum_buy_cost: Decimal | None
    channels: dict[str, ScoredChannel] = field(default_factory=dict)
    brand_status: str = BRAND_UNKNOWN
    errors: list[str] = field(default_factory=list)
    # The full cost stack behind `unit_cost`. Carried so the UI can show why
    # a $12.00 invoice price scores as $13.61 landed, which is the difference
    # between a row passing and failing more often than any other single input.
    landed_cost: object | None = None

    ranking_policy: str = RANK_BY_VELOCITY

    @property
    def best_channel(self) -> ScoredChannel | None:
        """The channel to actually sell on.

        Ranked by verdict tier first, then by the active ranking policy.
        Verdict first matters: a PASS on eBay clearing in 20 days beats a WATCH
        on Walmart projecting more, because the WATCH's projection is precisely
        the part we aren't sure about.
        """
        if not self.channels:
            return None
        tier = {Verdict.PASS: 2, Verdict.WATCH: 1, Verdict.FAIL: 0}
        return max(
            self.channels.values(),
            key=lambda c: (tier[c.verdict], *_sort_key(c, self.ranking_policy)),
        )

    @property
    def days_to_sell_through(self) -> float | None:
        best = self.best_channel
        return best.days_to_sell_through if best else None

    @property
    def annualized_roi_pct(self) -> float | None:
        best = self.best_channel
        return best.annualized_roi_pct if best else None

    @property
    def verdict(self) -> Verdict:
        best = self.best_channel
        return best.verdict if best else Verdict.FAIL

    @property
    def projected_monthly_profit(self) -> float:
        best = self.best_channel
        return best.projected_monthly_profit or 0.0 if best else 0.0

    def as_dict(self) -> dict[str, object]:
        best = self.best_channel
        return {
            "row_index": self.row_index,
            "gtin14": self.gtin14,
            "description": self.description,
            "brand": self.brand,
            "brand_status": self.brand_status,
            "unit_cost": float(self.unit_cost) if self.unit_cost is not None else None,
            "landed_cost": self.landed_cost.as_dict()
            if self.landed_cost is not None and hasattr(self.landed_cost, "as_dict")
            else None,
            "minimum_buy_cost": float(self.minimum_buy_cost)
            if self.minimum_buy_cost is not None
            else None,
            "verdict": self.verdict.value,
            "best_channel": best.economics.channel if best else None,
            "projected_monthly_profit": self.projected_monthly_profit,
            "days_to_sell_through": self.days_to_sell_through,
            "annualized_roi_pct": self.annualized_roi_pct,
            "channels": {name: ch.as_dict() for name, ch in self.channels.items()},
            "errors": self.errors,
        }


def _sort_key(channel: ScoredChannel, policy: str) -> tuple[float, float]:
    """Sort key for one channel under a ranking policy.

    Always a pair, so every policy has a defined tiebreak. Under ``velocity``
    the tiebreak is projected monthly profit, which is what separates two rows
    that both turn over quickly but move very different amounts of money.
    """
    projected = channel.projected_monthly_profit or 0.0
    if policy == RANK_BY_MONTHLY_PROFIT:
        return (projected, channel.annualized_roi_pct or 0.0)
    if policy == RANK_BY_MARGIN:
        return (float(channel.economics.margin_pct), projected)
    # Default: velocity. Rows with no sell-through estimate sort to the bottom
    # of their verdict tier rather than to the top — an unknown turn rate is
    # not a fast one.
    return (channel.annualized_roi_pct or -1.0, projected)


def rank(rows: list[ScoredRow], policy: str = RANK_BY_VELOCITY) -> list[ScoredRow]:
    """Sort rows the way a capital-constrained buyer works a list.

    Verdict tier is the primary key so no amount of projected profit floats a
    FAIL above a PASS — the ranking's job is to put the rows you can act on at
    the top, not to be a leaderboard of theoretical maxima. Within a tier the
    policy decides, and the default is velocity: annualized ROI, tiebroken by
    absolute monthly dollars.
    """
    tier = {Verdict.PASS: 2, Verdict.WATCH: 1, Verdict.FAIL: 0}

    def key(row: ScoredRow) -> tuple[float, float, float]:
        row.ranking_policy = policy
        best = row.best_channel
        if best is None:
            return (float(tier[row.verdict]), -1.0, 0.0)
        primary, secondary = _sort_key(best, policy)
        return (float(tier[row.verdict]), primary, secondary)

    return sorted(rows, key=key, reverse=True)


def summarize(rows: list[ScoredRow]) -> dict[str, object]:
    """Headline counts for the list view."""
    counts = {v.value: 0 for v in Verdict}
    total_projected = 0.0
    total_capital = Decimal("0")
    clear_days: list[float] = []
    for row in rows:
        counts[row.verdict.value] += 1
        if row.verdict == Verdict.PASS:
            total_projected += row.projected_monthly_profit
            if row.minimum_buy_cost is not None:
                total_capital += row.minimum_buy_cost
            if row.days_to_sell_through is not None:
                clear_days.append(row.days_to_sell_through)
    return {
        "total_rows": len(rows),
        "pass": counts[Verdict.PASS.value],
        "watch": counts[Verdict.WATCH.value],
        "fail": counts[Verdict.FAIL.value],
        "projected_monthly_profit_of_passing": round(total_projected, 2),
        # What buying every passing row would actually cost, and how long it
        # would sit. A list of twelve winners that needs $40k and four months
        # to clear is a different proposition from one that needs $6k and three
        # weeks, and the verdict counts alone don't show that.
        "capital_required_for_passing": float(total_capital),
        "median_days_to_clear": (
            round(sorted(clear_days)[len(clear_days) // 2], 1) if clear_days else None
        ),
    }
