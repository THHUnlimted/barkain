"""Projected vs. actual — the feedback loop that makes the estimates converge.

Pure module. The companion to ``recon.py``: that one calibrates **fees** from
your settlements, this one calibrates **demand** from your sales.

## Why this is the most valuable table in the system

Every demand number the scanner produces is an estimate with a known error
profile — BSR curves run 20–40% off, review velocity rests on a 2% constant
that varies by category, depletion is good but samples one offer. Right now
those errors are *unmeasured*, which means they're unmanaged.

The fix is boring and powerful: write down every prediction at the moment it's
made, then compare it to what actually happened. Two things fall out:

1. **Per-tier bias.** If the ``rank`` tier consistently predicts 1.6× the units
   you actually sell in Pet Supplies, that's not noise — it's a correction
   factor, and applying it makes every future Pet Supplies BSR estimate better.
2. **Honest confidence.** A tier that's been within 15% across 40 SKUs deserves
   to promote a row to PASS. A tier that's been off by 3× deserves WATCH, no
   matter how good the margin looks.

The scanner can't learn this from anyone else's data because it depends on your
categories, your price points, and your listings. It is the same compounding
asset as the snapshot table, and it starts accumulating the first time you buy
something the tool recommended.

## Where actuals come from

Both marketplaces expose first-party seller APIs — no scraping, no approval
gauntlet, because it's your own data:

- **Walmart**: Orders API for shipped units, the Reports API reconciliation
  feed (the one ``recon.py`` already parses) for realized revenue and fees, and
  the Insights API for listing-level performance.
- **eBay**: Sell Fulfillment ``getOrders`` for units, Sell Finances
  ``getTransactions`` for exact realized fees, and Sell Analytics
  ``getTrafficReport`` for impressions, views and sales-conversion rate.

The traffic report is a genuine bonus: conversion rate is the missing term in
every demand estimate. Knowing a listing got 4,000 impressions and converted at
1.2% explains a miss in a way that a units number alone never does.

## Bias, not accuracy, is what gets applied

``median_ratio`` (actual ÷ predicted) is the correction factor, and it's a
median for the same reason ``recon.py`` uses one: a single viral week shouldn't
permanently reset the model. ``mape`` is reported alongside but never applied —
it measures spread, and correcting for spread is meaningless.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

_CENT = Decimal("0.01")
_ZERO = Decimal("0")

# Below this many paired observations a bias factor is reported but not applied.
# Two data points can produce a 0.4x correction that's pure chance, and a
# correction applied too early is worse than none — it moves every row and
# looks authoritative doing it.
MIN_SAMPLES_TO_APPLY = 5

# Clamp on the applied correction. A learned factor outside this range almost
# always means the pairing is wrong (a forecast matched to the wrong SKU, a
# window mismatch) rather than that demand is genuinely 6x off.
_MIN_BIAS = 0.25
_MAX_BIAS = 4.0


def _money(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


# MARK: - Records


@dataclass(frozen=True)
class Forecast:
    """A prediction, recorded at the moment the verdict was produced.

    Written on every scored row that the buyer actually purchases. Rows that
    were never bought have no actual to compare against, so recording them
    would only add noise — the loop is about SKUs that made it into inventory.
    """

    sku: str
    channel: str
    predicted_at: datetime
    predicted_monthly_units: float
    predicted_net_per_unit: Decimal
    signal_tier: str                      # DemandConfidence value used
    category: str | None = None
    thresholds_version: str | None = None
    fee_schedule_version: str | None = None
    notes: str | None = None

    @property
    def predicted_monthly_profit(self) -> Decimal:
        return _money(self.predicted_net_per_unit * Decimal(str(self.predicted_monthly_units)))


@dataclass(frozen=True)
class Actual:
    """What actually happened over an observation window.

    ``net_proceeds`` is what landed after fees but before cost of goods, which
    is what ``recon.py`` already computes — so a reconciliation import feeds
    this directly with no extra plumbing.
    """

    sku: str
    channel: str
    window_start: datetime
    window_end: datetime
    units_sold: int
    net_proceeds: Decimal
    impressions: int | None = None        # eBay getTrafficReport
    listing_views: int | None = None
    conversion_rate: float | None = None

    @property
    def window_days(self) -> float:
        return max((self.window_end - self.window_start).total_seconds() / 86400.0, 1.0)

    @property
    def actual_monthly_units(self) -> float:
        """Normalize the window to a month so it's comparable to the forecast."""
        return round(self.units_sold / self.window_days * 30.0, 2)

    @property
    def actual_net_per_unit(self) -> Decimal:
        if self.units_sold <= 0:
            return _ZERO
        return _money(self.net_proceeds / Decimal(self.units_sold))


@dataclass(frozen=True)
class Comparison:
    """One forecast paired with one actual."""

    sku: str
    channel: str
    signal_tier: str
    category: str | None
    predicted_units: float
    actual_units: float
    predicted_net: Decimal
    actual_net: Decimal
    window_days: float

    @property
    def units_ratio(self) -> float | None:
        """Actual ÷ predicted. 1.0 is perfect, >1 means we under-predicted."""
        if self.predicted_units <= 0:
            return None
        return round(self.actual_units / self.predicted_units, 4)

    @property
    def units_error_pct(self) -> float | None:
        if self.predicted_units <= 0:
            return None
        return round(
            abs(self.actual_units - self.predicted_units) / self.predicted_units * 100, 1
        )

    @property
    def net_ratio(self) -> float | None:
        """Actual ÷ predicted net per unit.

        Systematically below 1.0 means the fee or landed-cost model is
        optimistic — a different failure from a demand miss, and it points at
        ``recon.py`` rather than at the demand tiers.
        """
        if self.predicted_net <= 0:
            return None
        return round(float(self.actual_net / self.predicted_net), 4)

    def as_dict(self) -> dict[str, object]:
        return {
            "sku": self.sku,
            "channel": self.channel,
            "signal_tier": self.signal_tier,
            "category": self.category,
            "predicted_units": self.predicted_units,
            "actual_units": self.actual_units,
            "units_ratio": self.units_ratio,
            "units_error_pct": self.units_error_pct,
            "predicted_net": float(self.predicted_net),
            "actual_net": float(self.actual_net),
            "net_ratio": self.net_ratio,
        }


def pair(forecasts: list[Forecast], actuals: list[Actual]) -> list[Comparison]:
    """Match forecasts to actuals on ``(sku, channel)``.

    Uses the **latest forecast made before the window opened** — a prediction
    made after the sales it's being judged on isn't a prediction. Forecasts with
    no matching actual are dropped silently; that just means the SKU hasn't sold
    yet, which isn't evidence of anything.
    """
    by_key: dict[tuple[str, str], list[Forecast]] = {}
    for forecast in forecasts:
        by_key.setdefault((forecast.sku, forecast.channel), []).append(forecast)
    for bucket in by_key.values():
        bucket.sort(key=lambda f: f.predicted_at)

    out: list[Comparison] = []
    for actual in actuals:
        bucket = by_key.get((actual.sku, actual.channel))
        if not bucket:
            continue
        eligible = [f for f in bucket if f.predicted_at <= actual.window_start]
        if not eligible:
            continue
        forecast = eligible[-1]
        out.append(
            Comparison(
                sku=actual.sku,
                channel=actual.channel,
                signal_tier=forecast.signal_tier,
                category=forecast.category,
                predicted_units=forecast.predicted_monthly_units,
                actual_units=actual.actual_monthly_units,
                predicted_net=forecast.predicted_net_per_unit,
                actual_net=actual.actual_net_per_unit,
                window_days=actual.window_days,
            )
        )
    return out


# MARK: - Learned corrections


@dataclass
class BiasEstimate:
    ratios: list[float] = field(default_factory=list)
    errors: list[float] = field(default_factory=list)

    def add(self, ratio: float | None, error_pct: float | None) -> None:
        if ratio is not None and ratio > 0:
            self.ratios.append(ratio)
        if error_pct is not None:
            self.errors.append(error_pct)

    @property
    def samples(self) -> int:
        return len(self.ratios)

    @property
    def median_ratio(self) -> float | None:
        """The correction factor. Median so one viral week can't reset the model."""
        if not self.ratios:
            return None
        return round(statistics.median(self.ratios), 4)

    @property
    def mape(self) -> float | None:
        """Mean absolute percentage error — reported, never applied."""
        if not self.errors:
            return None
        return round(statistics.fmean(self.errors), 1)

    @property
    def is_applicable(self) -> bool:
        return self.samples >= MIN_SAMPLES_TO_APPLY and self.median_ratio is not None

    @property
    def correction(self) -> float:
        """Multiplier to apply to a raw estimate. 1.0 until there's evidence."""
        if not self.is_applicable:
            return 1.0
        assert self.median_ratio is not None
        return min(max(self.median_ratio, _MIN_BIAS), _MAX_BIAS)

    def as_dict(self) -> dict[str, object]:
        return {
            "samples": self.samples,
            "median_ratio": self.median_ratio,
            "mape": self.mape,
            "correction_applied": self.correction if self.is_applicable else None,
        }


@dataclass
class DemandCalibration:
    """Learned per-tier and per-(tier, category) corrections for demand estimates.

    Consulted by the scoring layer the same way ``FeeCalibration`` is consulted
    by the fee engine. The more specific key wins when it has enough samples,
    because BSR bias is genuinely category-dependent — that's the whole reason
    the curves are per-category in the first place.
    """

    by_tier: dict[str, BiasEstimate] = field(default_factory=dict)
    by_tier_category: dict[tuple[str, str], BiasEstimate] = field(default_factory=dict)
    net_bias: BiasEstimate = field(default_factory=BiasEstimate)
    comparisons_seen: int = 0

    @staticmethod
    def _key(value: str | None) -> str:
        return " ".join((value or "").strip().lower().split())

    def ingest(self, comparisons: list[Comparison]) -> "DemandCalibration":
        for c in comparisons:
            self.comparisons_seen += 1
            tier = c.signal_tier
            self.by_tier.setdefault(tier, BiasEstimate()).add(c.units_ratio, c.units_error_pct)
            category = self._key(c.category)
            if category:
                self.by_tier_category.setdefault(
                    (tier, category), BiasEstimate()
                ).add(c.units_ratio, c.units_error_pct)
            self.net_bias.add(c.net_ratio, None)
        return self

    def correction_for(
        self, signal_tier: str, category: str | None = None
    ) -> tuple[float, str]:
        """Multiplier for a raw demand estimate, plus the basis that produced it."""
        key = (signal_tier, self._key(category))
        specific = self.by_tier_category.get(key)
        if specific and specific.is_applicable:
            return specific.correction, f"tier+category_n{specific.samples}"
        general = self.by_tier.get(signal_tier)
        if general and general.is_applicable:
            return general.correction, f"tier_n{general.samples}"
        return 1.0, "uncalibrated"

    def apply(
        self, monthly_units: float | None, signal_tier: str, category: str | None = None
    ) -> tuple[float | None, str]:
        """Correct one estimate. Returns ``(units, basis)``."""
        if monthly_units is None:
            return None, "uncalibrated"
        factor, basis = self.correction_for(signal_tier, category)
        return round(monthly_units * factor, 1), basis

    def report(self) -> dict[str, object]:
        return {
            "comparisons_seen": self.comparisons_seen,
            "by_tier": {
                tier: obs.as_dict() for tier, obs in sorted(self.by_tier.items())
            },
            "by_tier_category": {
                f"{tier} / {category}": obs.as_dict()
                for (tier, category), obs in sorted(self.by_tier_category.items())
            },
            # A net_bias well below 1.0 points at the fee/cost model, not the
            # demand model — that's a recon.py problem, and saying so saves an
            # afternoon of tuning the wrong thing.
            "net_per_unit_bias": self.net_bias.as_dict(),
        }


def accuracy_summary(comparisons: list[Comparison]) -> dict[str, object]:
    """Headline scoreboard: how well is the scanner actually predicting?

    ``within_25_pct`` is the honest headline metric. A tool that's within a
    quarter on units is genuinely useful for sourcing decisions; MAPE alone
    hides whether the misses are a few disasters or uniform drift.
    """
    if not comparisons:
        return {"comparisons": 0}

    ratios = [c.units_ratio for c in comparisons if c.units_ratio is not None]
    errors = [c.units_error_pct for c in comparisons if c.units_error_pct is not None]
    within_25 = sum(1 for e in errors if e <= 25)
    over = sum(1 for r in ratios if r < 1.0)

    return {
        "comparisons": len(comparisons),
        "median_ratio": round(statistics.median(ratios), 3) if ratios else None,
        "mape": round(statistics.fmean(errors), 1) if errors else None,
        "within_25_pct": round(100.0 * within_25 / len(errors), 1) if errors else None,
        # Which direction the tool is wrong in matters more than how much.
        # Over-predicting demand buys dead stock; under-predicting only means
        # missed upside, and those are not equally bad outcomes.
        "over_predicted_pct": round(100.0 * over / len(ratios), 1) if ratios else None,
    }
