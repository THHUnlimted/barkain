"""Fee engines for Walmart Marketplace + WFS and eBay.

Pure module. Money is ``Decimal`` end to end — a fee engine that rounds through
``float`` will disagree with the marketplace's own statement by cents per unit,
and cents per unit is exactly the margin being argued about.

## Treat every rate table here as configuration, not as truth

Marketplace fee schedules change on the marketplace's schedule, not ours. Each
table below carries its source and the date it was last verified, and the module
carries ``FEE_SCHEDULE_VERSION``. When a verdict looks wrong the first question
is always "is the rate card current". A stale referral rate is a silent 2-point
margin error across every row of every list.

The values shipped here are the published US rates as of the date noted. They
are **not** account-specific: negotiated rates, promotional fee holidays, and
category exceptions granted to individual sellers are not modelled. Anyone
running real money through this should re-derive the tables from their own
settlement reports.

## What's modelled

Walmart (WFS):
  referral fee (% of sale price, tiered by category and sometimes by price)
  + fulfillment fee (weight/size tier)
  + monthly storage (cubic feet × rate, seasonal)

Walmart (seller-fulfilled):
  referral fee + your own shipping cost

eBay:
  final value fee (% + per-order fixed) + optional ad rate + your shipping cost

## What's not modelled

Returns, chargebacks, WFS inbound freight, prep/labeling, inventory shrink, and
the cost of your own time. A 25% ROI threshold is doing the job of absorbing
those — which is why the threshold is 25% and not 5%.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from m15_sourcing.plans import SellingPlan, effective_fee_rate, get_plan

FEE_SCHEDULE_VERSION = "2026-07-26"

_CENT = Decimal("0.01")
_ZERO = Decimal("0")


def _money(value: Decimal | float | int) -> Decimal:
    """Quantize to cents, half-up — the rounding marketplaces use on statements."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


# MARK: - Walmart referral fees
#
# Source: Walmart Marketplace "Referral Fees by Category", US, verified
# 2026-07-26. Categories with a price break are expressed as an ordered list of
# (price_ceiling, rate) — the first bucket whose ceiling the sale price does not
# exceed wins; a `None` ceiling is the catch-all.

WalmartRateTiers = tuple[tuple[Decimal | None, Decimal], ...]

WALMART_REFERRAL_RATES: dict[str, WalmartRateTiers] = {
    "apparel_accessories": ((None, Decimal("0.15")),),
    "automotive_powersports": ((None, Decimal("0.12")),),
    "baby": ((Decimal("10"), Decimal("0.08")), (None, Decimal("0.15"))),
    "beauty": ((Decimal("10"), Decimal("0.08")), (None, Decimal("0.15"))),
    "books": ((None, Decimal("0.15")),),
    "camera_photo": ((None, Decimal("0.08")),),
    "cell_phones": ((None, Decimal("0.08")),),
    "consumer_electronics": ((None, Decimal("0.08")),),
    "electronics_accessories": (
        (Decimal("100"), Decimal("0.15")),
        (None, Decimal("0.08")),
    ),
    "furniture_decor": ((Decimal("200"), Decimal("0.15")), (None, Decimal("0.10"))),
    "grocery": ((Decimal("10"), Decimal("0.08")), (None, Decimal("0.15"))),
    "health_personal_care": ((Decimal("10"), Decimal("0.08")), (None, Decimal("0.15"))),
    "home_garden": ((None, Decimal("0.15")),),
    "indoor_outdoor_furniture": ((Decimal("200"), Decimal("0.15")), (None, Decimal("0.10"))),
    "industrial_scientific": ((None, Decimal("0.12")),),
    "jewelry": ((None, Decimal("0.20")),),
    "kitchen": ((None, Decimal("0.15")),),
    "music_video_games": ((None, Decimal("0.15")),),
    "office_products": ((None, Decimal("0.15")),),
    "outdoors": ((None, Decimal("0.15")),),
    "pet_supplies": ((None, Decimal("0.15")),),
    "software_computer_games": ((None, Decimal("0.15")),),
    "sporting_goods": ((None, Decimal("0.15")),),
    "tires_wheels": ((None, Decimal("0.10")),),
    "tools_home_improvement": ((None, Decimal("0.15")),),
    "toys_games": ((None, Decimal("0.15")),),
    "video_games_consoles": ((None, Decimal("0.08")),),
    "watches": ((Decimal("1500"), Decimal("0.15")), (None, Decimal("0.03"))),
    # The catch-all. Walmart's own default for uncategorized items is 15%, and
    # 15% is also the modal rate, so an unknown category is priced pessimistically
    # by accident rather than optimistically — the right direction for a
    # go/no-go tool.
    "default": ((None, Decimal("0.15")),),
}

# Loose keyword → category resolution for the category strings the item APIs
# actually return (Walmart's `categoryPath` is a "Home/Kitchen/Cookware" style
# breadcrumb, eBay's is a leaf name). Ordered most-specific first; first hit
# wins. This is deliberately conservative — an unmatched category falls to
# `default` at 15% rather than guessing into an 8% bucket and overstating margin.
_CATEGORY_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("video game", "video_games_consoles"),
    ("cell phone", "cell_phones"),
    ("smartphone", "cell_phones"),
    ("camera", "camera_photo"),
    ("electronics accessor", "electronics_accessories"),
    ("computer accessor", "electronics_accessories"),
    ("electronic", "consumer_electronics"),
    ("computer", "consumer_electronics"),
    ("tv & video", "consumer_electronics"),
    ("audio", "consumer_electronics"),
    ("jewelry", "jewelry"),
    ("watch", "watches"),
    ("baby", "baby"),
    ("beauty", "beauty"),
    ("personal care", "health_personal_care"),
    ("health", "health_personal_care"),
    ("grocery", "grocery"),
    ("food", "grocery"),
    ("pet", "pet_supplies"),
    ("tire", "tires_wheels"),
    ("automotive", "automotive_powersports"),
    ("tool", "tools_home_improvement"),
    ("home improvement", "tools_home_improvement"),
    ("hardware", "tools_home_improvement"),
    ("furniture", "furniture_decor"),
    ("kitchen", "kitchen"),
    ("cookware", "kitchen"),
    ("appliance", "home_garden"),
    ("home", "home_garden"),
    ("garden", "home_garden"),
    ("patio", "outdoors"),
    ("outdoor", "outdoors"),
    ("sport", "sporting_goods"),
    ("toy", "toys_games"),
    ("game", "toys_games"),
    ("office", "office_products"),
    ("book", "books"),
    ("music", "music_video_games"),
    ("movie", "music_video_games"),
    ("industrial", "industrial_scientific"),
    ("clothing", "apparel_accessories"),
    ("apparel", "apparel_accessories"),
    ("shoe", "apparel_accessories"),
    ("software", "software_computer_games"),
)


def resolve_category(raw_category: str | None) -> str:
    """Map a retailer category breadcrumb to a referral-fee category key.

    Unmatched input returns ``"default"`` (15%) rather than a guess. Fee
    optimism is the expensive kind of wrong here: it turns a losing row into a
    candidate, and you find out after the pallet arrives.
    """
    if not raw_category:
        return "default"
    text = raw_category.lower()
    for keyword, category in _CATEGORY_KEYWORDS:
        if keyword in text:
            return category
    return "default"


def walmart_referral_rate(category: str | None, sale_price: Decimal) -> Decimal:
    """Return the referral-fee rate for a category at a given sale price."""
    key = category if category in WALMART_REFERRAL_RATES else resolve_category(category)
    for ceiling, rate in WALMART_REFERRAL_RATES.get(key, WALMART_REFERRAL_RATES["default"]):
        if ceiling is None or sale_price <= ceiling:
            return rate
    return WALMART_REFERRAL_RATES["default"][0][1]


# MARK: - WFS fulfillment
#
# Source: Walmart Fulfillment Services rate card, US standard-size, verified
# 2026-07-26. Tiers are (weight_ceiling_lb, base_fee, per_lb_over_base_weight,
# base_weight). Anything past the last tier uses the last tier's formula.

_WFS_TIERS: tuple[tuple[Decimal, Decimal, Decimal, Decimal], ...] = (
    (Decimal("1"), Decimal("3.45"), _ZERO, _ZERO),
    (Decimal("2"), Decimal("4.95"), _ZERO, _ZERO),
    (Decimal("3"), Decimal("5.45"), _ZERO, _ZERO),
    (Decimal("20"), Decimal("5.75"), Decimal("0.40"), Decimal("3")),
    (Decimal("30"), Decimal("12.55"), Decimal("0.40"), Decimal("20")),
    (Decimal("150"), Decimal("16.55"), Decimal("0.40"), Decimal("30")),
)

# Oversize surcharge applied when the item exceeds standard-size limits.
_WFS_OVERSIZE_SURCHARGE = Decimal("30.00")
_WFS_BULKY_SURCHARGE = Decimal("70.00")
_STANDARD_MAX_LONGEST_IN = Decimal("48")
_STANDARD_MAX_GIRTH_IN = Decimal("105")
_STANDARD_MAX_WEIGHT_LB = Decimal("30")
_BULKY_MIN_WEIGHT_LB = Decimal("150")

# Monthly storage per cubic foot. Q4 (Oct–Dec) is roughly double, which is the
# whole reason slow movers are dangerous — a 90-day sell-through that's fine in
# March quietly eats the margin in November.
_STORAGE_RATE_STANDARD = Decimal("0.75")
_STORAGE_RATE_Q4 = Decimal("1.50")

# WFS bills dimensional weight above this threshold; below it, actual weight
# governs. Divisor is the standard 139 cubic inches per pound.
_DIM_WEIGHT_DIVISOR = Decimal("139")


@dataclass(frozen=True)
class ItemDimensions:
    """Shipping dimensions. Any field may be unknown."""

    weight_lb: Decimal | None = None
    length_in: Decimal | None = None
    width_in: Decimal | None = None
    height_in: Decimal | None = None

    @property
    def is_complete(self) -> bool:
        return all(
            v is not None and v > 0
            for v in (self.weight_lb, self.length_in, self.width_in, self.height_in)
        )

    @property
    def cubic_feet(self) -> Decimal | None:
        if None in (self.length_in, self.width_in, self.height_in):
            return None
        assert self.length_in and self.width_in and self.height_in
        cubic_inches = self.length_in * self.width_in * self.height_in
        return cubic_inches / Decimal("1728")

    @property
    def dimensional_weight_lb(self) -> Decimal | None:
        if None in (self.length_in, self.width_in, self.height_in):
            return None
        assert self.length_in and self.width_in and self.height_in
        return (self.length_in * self.width_in * self.height_in) / _DIM_WEIGHT_DIVISOR

    @property
    def billable_weight_lb(self) -> Decimal | None:
        """The greater of actual and dimensional weight — what carriers bill on."""
        dim = self.dimensional_weight_lb
        if self.weight_lb is None:
            return dim
        if dim is None:
            return self.weight_lb
        return max(self.weight_lb, dim)

    @property
    def size_tier(self) -> str:
        """``standard`` | ``oversize`` | ``bulky`` | ``unknown``."""
        weight = self.billable_weight_lb
        if weight is None:
            return "unknown"
        if weight >= _BULKY_MIN_WEIGHT_LB:
            return "bulky"
        dims = sorted(
            (d for d in (self.length_in, self.width_in, self.height_in) if d is not None),
            reverse=True,
        )
        if len(dims) == 3:
            longest = dims[0]
            girth = longest + 2 * (dims[1] + dims[2])
            if longest > _STANDARD_MAX_LONGEST_IN or girth > _STANDARD_MAX_GIRTH_IN:
                return "oversize"
        if weight > _STANDARD_MAX_WEIGHT_LB:
            return "oversize"
        return "standard"


# Fallback weight when the item APIs and UPC databases all come up empty. 1.5 lb
# is around the median for the small-parcel consumer goods that dominate
# wholesale lists. It is a *guess* and every estimate built on it is flagged
# `assumed_weight` so a candidate never gets promoted on invented data.
DEFAULT_ASSUMED_WEIGHT_LB = Decimal("1.5")


def wfs_fulfillment_fee(dims: ItemDimensions) -> tuple[Decimal, list[str]]:
    """WFS fulfillment fee for one unit, plus any assumptions made.

    Returns ``(fee, notes)``. ``notes`` is non-empty whenever the number rests
    on an assumption — that flag rides all the way to the verdict so a PASS
    built on a guessed weight is visibly different from one built on measured
    dimensions.
    """
    notes: list[str] = []
    weight = dims.billable_weight_lb
    if weight is None:
        weight = DEFAULT_ASSUMED_WEIGHT_LB
        notes.append("assumed_weight")

    tier = dims.size_tier
    if tier == "bulky":
        notes.append("bulky_surcharge")
        return _money(_WFS_TIERS[-1][1] + _WFS_BULKY_SURCHARGE), notes

    fee = None
    for ceiling, base, per_lb, base_weight in _WFS_TIERS:
        if weight <= ceiling:
            fee = base + per_lb * max(_ZERO, weight - base_weight)
            break
    if fee is None:
        ceiling, base, per_lb, base_weight = _WFS_TIERS[-1]
        fee = base + per_lb * max(_ZERO, weight - base_weight)

    if tier == "oversize":
        fee += _WFS_OVERSIZE_SURCHARGE
        notes.append("oversize_surcharge")

    return _money(fee), notes


def wfs_storage_fee(
    dims: ItemDimensions, days_on_hand: int = 60, q4: bool = False
) -> tuple[Decimal, list[str]]:
    """Estimated storage cost for one unit over ``days_on_hand``."""
    notes: list[str] = []
    cubic_feet = dims.cubic_feet
    if cubic_feet is None or cubic_feet <= 0:
        # ~0.05 cu ft is a shoebox-ish small parcel; the fee it produces is
        # cents, which is the right order of magnitude for an unknown.
        cubic_feet = Decimal("0.05")
        notes.append("assumed_cubic_feet")
    rate = _STORAGE_RATE_Q4 if q4 else _STORAGE_RATE_STANDARD
    months = Decimal(days_on_hand) / Decimal("30")
    return _money(cubic_feet * rate * months), notes


# MARK: - eBay fees
#
# Source: eBay US "Selling fees" (final value fees), verified 2026-07-26.
# Most categories: 13.6% of the total amount of the sale + $0.40 per order,
# with the percentage dropping above a portion threshold in some categories.

EBAY_DEFAULT_FVF_RATE = Decimal("0.136")

# The per-order fixed fee is tiered on ORDER TOTAL, not item price. Confirmed
# from a real fee-detail screen: "Per order fixed amount · Order total $10.01+"
# charged $0.40. Below that threshold it's $0.30. On a $9 item that difference
# is 1.1% of revenue, which is the kind of thing that decides a marginal row.
EBAY_PER_ORDER_FEE = Decimal("0.40")
EBAY_PER_ORDER_FEE_LOW = Decimal("0.30")
EBAY_PER_ORDER_FEE_THRESHOLD = Decimal("10.00")

# eBay charges its percentage on the **total amount of the sale, including the
# sales tax it collects and remits on your behalf**. This is counter-intuitive
# and it is not how Walmart works — see `walmart_economics`. Verified against a
# real order:
#
#     item $26.50 + shipping $0.00 + sales tax $1.86 = $28.36
#     $28.36 x 13.6% = $3.86   <- eBay's own arithmetic, from the fee detail
#
# Computing the fee on the item price alone understates it by ~7% of the fee.
# Since we're scoring before a sale exists, the buyer's tax rate is unknown, so
# we estimate it. 7.0% is close to the US average and matched the sample order
# to the cent (1.86 / 26.50 = 7.02%).
EBAY_ASSUMED_SALES_TAX_RATE = Decimal("0.07")


def ebay_per_order_fee(order_total: Decimal) -> Decimal:
    """The tiered per-order fixed fee. Threshold is on order total, not item price."""
    return (
        EBAY_PER_ORDER_FEE
        if order_total > EBAY_PER_ORDER_FEE_THRESHOLD
        else EBAY_PER_ORDER_FEE_LOW
    )

EBAY_FVF_RATES: dict[str, Decimal] = {
    "default": Decimal("0.136"),
    # Confirmed 13.6% against a real order in this category (fee detail read
    # "Variable percentage · Business & Industrial category").
    "business_industrial": Decimal("0.136"),
    "books_movies_music": Decimal("0.1535"),
    "clothing_shoes_accessories": Decimal("0.135"),
    "coins_paper_money": Decimal("0.09"),
    "jewelry_watches": Decimal("0.15"),
    "musical_instruments": Decimal("0.061"),
    "athletic_shoes": Decimal("0.08"),
    "heavy_equipment": Decimal("0.03"),
    "consumer_electronics": Decimal("0.136"),
}

# Above this portion of the sale price, most categories drop to 2.35%.
_EBAY_HIGH_VALUE_THRESHOLD = Decimal("7500")
_EBAY_HIGH_VALUE_RATE = Decimal("0.0235")

# USPS Ground Advantage-ish retail-adjacent estimate by weight, for when the
# seller ships. Deliberately a little pessimistic; under-costing shipping is the
# classic way an eBay row looks profitable and isn't.
_EBAY_SHIPPING_TIERS: tuple[tuple[Decimal, Decimal], ...] = (
    (Decimal("0.5"), Decimal("4.50")),
    (Decimal("1"), Decimal("5.75")),
    (Decimal("2"), Decimal("7.50")),
    (Decimal("3"), Decimal("9.25")),
    (Decimal("5"), Decimal("12.00")),
    (Decimal("10"), Decimal("17.50")),
    (Decimal("20"), Decimal("26.00")),
    (Decimal("50"), Decimal("48.00")),
)
_EBAY_SHIPPING_OVER_50_PER_LB = Decimal("1.10")


def ebay_shipping_estimate(dims: ItemDimensions) -> tuple[Decimal, list[str]]:
    """Estimated outbound shipping cost for a seller-fulfilled eBay order."""
    notes: list[str] = []
    weight = dims.billable_weight_lb
    if weight is None:
        weight = DEFAULT_ASSUMED_WEIGHT_LB
        notes.append("assumed_weight")
    for ceiling, cost in _EBAY_SHIPPING_TIERS:
        if weight <= ceiling:
            return _money(cost), notes
    last_ceiling, last_cost = _EBAY_SHIPPING_TIERS[-1]
    return _money(last_cost + (weight - last_ceiling) * _EBAY_SHIPPING_OVER_50_PER_LB), notes


def ebay_final_value_fee(
    sale_price: Decimal,
    shipping_charged: Decimal = _ZERO,
    category: str | None = None,
    plan: SellingPlan | None = None,
    sales_tax: Decimal | None = None,
) -> Decimal:
    """eBay final value fee on the **total amount of the sale**.

    "Total amount of the sale" means item price **plus buyer-paid shipping plus
    the sales tax eBay collects**. Free shipping doesn't dodge the fee, it just
    moves the money — and neither does tax, even though the tax is remitted to a
    state and never touches your account.

    Verified end to end against a real order: $26.50 item + $0.00 shipping +
    $1.86 tax = $28.36 base, x 13.6% = $3.86, + $0.40 = $4.26 total fees.
    """
    base_rate = EBAY_FVF_RATES.get(category or "default", EBAY_DEFAULT_FVF_RATE)
    rate = effective_fee_rate(base_rate, plan) if plan else base_rate

    tax = sales_tax if sales_tax is not None else (
        sale_price * EBAY_ASSUMED_SALES_TAX_RATE
    )
    total = sale_price + shipping_charged + tax

    if total <= _EBAY_HIGH_VALUE_THRESHOLD:
        variable = total * rate
    else:
        variable = (
            _EBAY_HIGH_VALUE_THRESHOLD * rate
            + (total - _EBAY_HIGH_VALUE_THRESHOLD) * _EBAY_HIGH_VALUE_RATE
        )
    return _money(variable + ebay_per_order_fee(total))


# MARK: - Unified breakdown


@dataclass(frozen=True)
class FeeBreakdown:
    """Per-unit cost stack for one channel. Every field is a positive cost."""

    referral_fee: Decimal = _ZERO
    fulfillment_fee: Decimal = _ZERO
    storage_fee: Decimal = _ZERO
    per_order_fee: Decimal = _ZERO
    shipping_cost: Decimal = _ZERO
    ad_fee: Decimal = _ZERO
    other_fees: Decimal = _ZERO

    @property
    def total(self) -> Decimal:
        return _money(
            self.referral_fee
            + self.fulfillment_fee
            + self.storage_fee
            + self.per_order_fee
            + self.shipping_cost
            + self.ad_fee
            + self.other_fees
        )

    def as_dict(self) -> dict[str, float]:
        return {
            "referral_fee": float(self.referral_fee),
            "fulfillment_fee": float(self.fulfillment_fee),
            "storage_fee": float(self.storage_fee),
            "per_order_fee": float(self.per_order_fee),
            "shipping_cost": float(self.shipping_cost),
            "ad_fee": float(self.ad_fee),
            "other_fees": float(self.other_fees),
            "total": float(self.total),
        }


@dataclass(frozen=True)
class ChannelEconomics:
    """The answer to "what do I actually make on one of these".

    ``roi_pct`` is the number that matters for a capital-constrained buyer:
    margin tells you how much of the sale you keep, ROI tells you how hard your
    money is working. A 40% margin on a $200 item you can only sell twice a
    month is worse than a 20% margin on a $12 item that moves 300 times.
    """

    channel: str
    sale_price: Decimal
    unit_cost: Decimal
    fees: FeeBreakdown
    fulfillment_model: str  # "wfs" | "seller_fulfilled" | "n/a"
    assumptions: tuple[str, ...] = ()

    @property
    def net_profit(self) -> Decimal:
        return _money(self.sale_price - self.unit_cost - self.fees.total)

    @property
    def margin_pct(self) -> Decimal:
        if self.sale_price <= 0:
            return _ZERO
        return _money(self.net_profit / self.sale_price * Decimal("100"))

    @property
    def roi_pct(self) -> Decimal:
        if self.unit_cost <= 0:
            return _ZERO
        return _money(self.net_profit / self.unit_cost * Decimal("100"))

    @property
    def breakeven_sale_price(self) -> Decimal:
        """Lowest sale price that still clears zero, holding fixed fees constant.

        Solves ``p - cost - (p × rate) - fixed = 0`` for ``p``. Useful as the
        "how far can this price war go before I'm out" line, which is a more
        actionable number than the current price when five sellers are racing.
        """
        variable_rate = (
            self.fees.referral_fee / self.sale_price if self.sale_price > 0 else _ZERO
        )
        fixed = (
            self.fees.fulfillment_fee
            + self.fees.storage_fee
            + self.fees.per_order_fee
            + self.fees.shipping_cost
            + self.fees.ad_fee
            + self.fees.other_fees
        )
        denominator = Decimal("1") - variable_rate
        if denominator <= 0:
            return _money(self.sale_price)
        return _money((self.unit_cost + fixed) / denominator)

    def as_dict(self) -> dict[str, object]:
        return {
            "channel": self.channel,
            "sale_price": float(self.sale_price),
            "unit_cost": float(self.unit_cost),
            "fulfillment_model": self.fulfillment_model,
            "fees": self.fees.as_dict(),
            "net_profit": float(self.net_profit),
            "margin_pct": float(self.margin_pct),
            "roi_pct": float(self.roi_pct),
            "breakeven_sale_price": float(self.breakeven_sale_price),
            "assumptions": list(self.assumptions),
        }


# MARK: - Channel calculators


def walmart_economics(
    *,
    sale_price: Decimal,
    unit_cost: Decimal,
    category: str | None = None,
    dims: ItemDimensions | None = None,
    use_wfs: bool = True,
    days_on_hand: int = 60,
    q4_storage: bool = False,
    seller_shipping_cost: Decimal | None = None,
    plan: SellingPlan | None = None,
    calibration: object | None = None,
    sku: str | None = None,
    product_type: str | None = None,
) -> ChannelEconomics:
    """Per-unit economics for a Walmart Marketplace listing.

    **Walmart's commission base excludes sales tax** — the opposite of eBay.
    Verified from a reconciliation report: an $8.99 item in Automotive &
    Powersports was charged $1.08 commission (12.00% of $8.99 exactly), while
    the $0.69 tax was collected and withheld as a pass-through that never
    entered the base. Passing a tax-inclusive price here would overstate the
    fee on every row.

    ``calibration`` is a ``recon.FeeCalibration``. When supplied, an *observed*
    commission rate or fulfillment fee from your own settlements overrides the
    published tables — see recon.py for why that ordering is the right one.

    ``plan`` exists for symmetry with the other channels — Walmart charges no
    subscription and no per-item plan fee, so it currently only affects the
    breakdown's ``other_fees`` if a future plan introduces one.
    """
    dims = dims or ItemDimensions()
    assumptions: list[str] = []
    plan = plan or get_plan("walmart")

    observed_rate = None
    if calibration is not None and hasattr(calibration, "commission_rate"):
        observed_rate = calibration.commission_rate(category)
    if observed_rate is not None:
        rate = effective_fee_rate(observed_rate, plan)
        assumptions.append("commission_rate_from_your_settlements")
    else:
        rate = effective_fee_rate(walmart_referral_rate(category, sale_price), plan)
    referral = _money(sale_price * rate)
    if resolve_category(category) == "default" and category not in WALMART_REFERRAL_RATES:
        assumptions.append("default_referral_rate")

    if use_wfs:
        observed_fee, basis = (None, "published_rate_card")
        if calibration is not None and hasattr(calibration, "fulfillment_fee"):
            observed_fee, basis = calibration.fulfillment_fee(
                sku=sku, product_type=product_type
            )
        if observed_fee is not None:
            # Your actual WFS charge beats the published tier table, which has
            # already been shown to disagree: a 16 oz item billed at $4.45 sits
            # between the published 0-1 lb ($3.45) and 1-2 lb ($4.95) tiers.
            fulfillment = observed_fee
            assumptions.append(f"wfs_fee_{basis}")
        else:
            fulfillment, notes = wfs_fulfillment_fee(dims)
            assumptions.extend(notes)

        observed_storage = None
        if calibration is not None and hasattr(calibration, "storage_fee"):
            observed_storage = calibration.storage_fee(sku)
        if observed_storage is not None:
            storage = observed_storage
            assumptions.append("storage_fee_from_your_settlements")
        else:
            storage, storage_notes = wfs_storage_fee(dims, days_on_hand, q4_storage)
            assumptions.extend(storage_notes)
        shipping = _ZERO
        model = "wfs"
    else:
        fulfillment = _ZERO
        storage = _ZERO
        if seller_shipping_cost is None:
            shipping, notes = ebay_shipping_estimate(dims)
            assumptions.extend(notes)
            assumptions.append("estimated_shipping")
        else:
            shipping = _money(seller_shipping_cost)
        model = "seller_fulfilled"

    return ChannelEconomics(
        channel="walmart",
        sale_price=_money(sale_price),
        unit_cost=_money(unit_cost),
        fees=FeeBreakdown(
            referral_fee=referral,
            fulfillment_fee=fulfillment,
            storage_fee=storage,
            shipping_cost=shipping,
            other_fees=plan.per_item_fee,
        ),
        fulfillment_model=model,
        assumptions=tuple(dict.fromkeys(assumptions)),
    )


def ebay_economics(
    *,
    sale_price: Decimal,
    unit_cost: Decimal,
    category: str | None = None,
    dims: ItemDimensions | None = None,
    shipping_charged: Decimal = _ZERO,
    seller_shipping_cost: Decimal | None = None,
    ad_rate: Decimal = _ZERO,
    plan: SellingPlan | None = None,
    sales_tax_rate: Decimal | None = None,
) -> ChannelEconomics:
    """Per-unit economics for an eBay listing.

    ``shipping_charged`` is what the buyer pays (and what eBay takes its cut of);
    ``seller_shipping_cost`` is what the label actually costs you. Free shipping
    is ``shipping_charged=0`` with a real ``seller_shipping_cost`` — the common
    case, and the one where the fee math surprises people.
    """
    dims = dims or ItemDimensions()
    assumptions: list[str] = []
    plan = plan or get_plan("ebay")

    if seller_shipping_cost is None:
        ship_cost, notes = ebay_shipping_estimate(dims)
        assumptions.extend(notes)
        assumptions.append("estimated_shipping")
    else:
        ship_cost = _money(seller_shipping_cost)

    tax_rate = (
        sales_tax_rate if sales_tax_rate is not None else EBAY_ASSUMED_SALES_TAX_RATE
    )
    sales_tax = _money(sale_price * tax_rate)
    fee_base = sale_price + shipping_charged + sales_tax

    fvf_total = ebay_final_value_fee(
        sale_price, shipping_charged, category, plan=plan, sales_tax=sales_tax
    )
    if tax_rate > 0:
        assumptions.append("fvf_charged_on_estimated_sales_tax")
    if plan.fvf_discount > 0:
        assumptions.append(f"{plan.key}_store_fvf_discount")
    # Split the fixed per-order component back out so the breakdown reads the
    # way a seller's statement does.
    fixed = ebay_per_order_fee(fee_base)
    variable = _money(fvf_total - fixed)
    # Promoted Listings General is charged on the same base as the FVF —
    # confirmed against a real order: $2.55 ad fee / $28.36 base = 9.0%, the
    # seller's set ad rate. Computing it on the item price alone would imply a
    # nonsense 9.62%.
    ad_fee = _money(fee_base * ad_rate) if ad_rate else _ZERO

    return ChannelEconomics(
        channel="ebay",
        # Revenue includes what the buyer paid for shipping — otherwise a
        # $10 item with $6 shipping looks like a loser next to a $16 item
        # with free shipping, when they're the same trade.
        sale_price=_money(sale_price + shipping_charged),
        unit_cost=_money(unit_cost),
        fees=FeeBreakdown(
            referral_fee=variable,
            per_order_fee=fixed,
            shipping_cost=ship_cost,
            ad_fee=ad_fee,
            other_fees=plan.per_item_fee,
        ),
        fulfillment_model="seller_fulfilled",
        assumptions=tuple(dict.fromkeys(assumptions)),
    )
