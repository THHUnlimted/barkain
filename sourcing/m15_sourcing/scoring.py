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

## Ranking

Rows sort by **projected monthly profit** = ``net_profit × unit_share``, not by
margin or ROI. A 60% margin on something that sells twice a month is a worse
use of a purchase order than 22% on something that moves 400 times, and sorting
by margin is how sourcing spreadsheets talk people into slow-moving inventory.

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
        ):
            if data.get(name) is not None:
                try:
                    kwargs[name] = Decimal(str(data[name]))
                except (ArithmeticError, ValueError):
                    pass
        if data.get("min_monthly_unit_share") is not None:
            try:
                kwargs["min_monthly_unit_share"] = float(data["min_monthly_unit_share"])
            except (TypeError, ValueError):
                pass
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
        }


def score_channel(
    *,
    economics: ChannelEconomics,
    demand: DemandEstimate,
    stability: PriceStability,
    seller_count: int | None,
    thresholds: Thresholds,
    listing_exists: bool = True,
    minimum_buy_cost: Decimal | None = None,
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

    @property
    def best_channel(self) -> ScoredChannel | None:
        """The channel to actually sell on.

        Ranked by verdict tier first, then projected monthly profit. Verdict
        first matters: a PASS on eBay at $180/mo beats a WATCH on Walmart
        projecting $400/mo, because the WATCH's projection is the part we
        aren't sure about.
        """
        if not self.channels:
            return None
        tier = {Verdict.PASS: 2, Verdict.WATCH: 1, Verdict.FAIL: 0}
        return max(
            self.channels.values(),
            key=lambda c: (tier[c.verdict], c.projected_monthly_profit or 0.0),
        )

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
            "minimum_buy_cost": float(self.minimum_buy_cost)
            if self.minimum_buy_cost is not None
            else None,
            "verdict": self.verdict.value,
            "best_channel": best.economics.channel if best else None,
            "projected_monthly_profit": self.projected_monthly_profit,
            "channels": {name: ch.as_dict() for name, ch in self.channels.items()},
            "errors": self.errors,
        }


def rank(rows: list[ScoredRow]) -> list[ScoredRow]:
    """Sort rows the way a buyer works a list: winners first, by dollars.

    Verdict tier is the primary key so no amount of projected profit floats a
    FAIL above a PASS — the ranking's job is to put the rows you can act on at
    the top, not to be a leaderboard of theoretical maxima.
    """
    tier = {Verdict.PASS: 2, Verdict.WATCH: 1, Verdict.FAIL: 0}
    return sorted(
        rows,
        key=lambda r: (tier[r.verdict], r.projected_monthly_profit),
        reverse=True,
    )


def summarize(rows: list[ScoredRow]) -> dict[str, object]:
    """Headline counts for the list view."""
    counts = {v.value: 0 for v in Verdict}
    total_projected = 0.0
    for row in rows:
        counts[row.verdict.value] += 1
        if row.verdict == Verdict.PASS:
            total_projected += row.projected_monthly_profit
    return {
        "total_rows": len(rows),
        "pass": counts[Verdict.PASS.value],
        "watch": counts[Verdict.WATCH.value],
        "fail": counts[Verdict.FAIL.value],
        "projected_monthly_profit_of_passing": round(total_projected, 2),
    }
