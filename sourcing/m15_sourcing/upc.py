"""UPC / GTIN normalization for distributor price lists.

Pure module — no I/O, no settings, no imports outside the stdlib. Every
function here is deterministic and unit-tested.

## Why this needs to exist

A barcode scanner hands you a clean 12-digit UPC-A. A distributor spreadsheet
hands you whatever survived a round-trip through Excel, a PDF, and three
different ERP exports. The failure modes are predictable and each one silently
produces a *lookup miss* rather than an error, which is the worst kind of bug
in a pipeline whose entire job is "did we find this item":

    195949036323          clean UPC-A                       → fine
    1.9594903632E+11      Excel coerced it to a float       → expand
    195949036323.0        same, fewer significant digits    → strip tail
    0195949036323         EAN-13 with US "0" prefix         → strip to 12
    00195949036323        GTIN-14 case code                 → strip padding
    12345678901           11 digits — genuinely ambiguous   → see below
    04963406              UPC-E compressed                  → expand to UPC-A
    "8 12345 67890 1"     human-readable spacing            → strip non-digits

## The 11-digit ambiguity

An 11-digit string is either:

  (a) a 12-digit UPC-A whose leading zero Excel ate, or
  (b) a UPC-A *body* with the check digit never included.

Both are common; you cannot tell them apart from length alone. We resolve by
computing the check digit for each interpretation and preferring the one that
validates. When *both* validate the value is genuinely ambiguous and we keep
the zero-padded reading (empirically the more common corruption) while
attaching an ``AMBIGUOUS_11_DIGIT`` warning so the UI can surface it.

## Canonical form

We store **GTIN-14** (left-zero-padded). It is the only representation that
round-trips every input without loss: UPC-E, UPC-A, EAN-13 and GTIN-14 all
embed cleanly. ``upc12`` and ``ean13`` are derived views that return ``None``
when the value genuinely doesn't fit that form (e.g. a real case code with a
non-zero indicator digit).

## What we never do

Silently "fix" a bad check digit. A UPC whose check digit fails is a typo or a
truncation, and guessing which digit was wrong turns one bad row into one
*confidently* bad row. We keep the digits, flag ``INVALID_CHECK_DIGIT``, and
let the match step decide whether to try it anyway.

The one exception is scientific notation, where we know *exactly* which digit
is untrustworthy: float rounding eats the least significant digit, which is the
check digit. There, recomputing is a repair rather than a guess — see
``_recover_scientific_check_digit``. When the mantissa lost more than that one
digit the row is failed outright (``PRECISION_LOST``) rather than emitted as a
well-formed wrong answer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

# MARK: - Warning codes

WARN_EMPTY = "EMPTY"
WARN_NO_DIGITS = "NO_DIGITS"
WARN_TOO_SHORT = "TOO_SHORT"
WARN_TOO_LONG = "TOO_LONG"
WARN_INVALID_CHECK_DIGIT = "INVALID_CHECK_DIGIT"
WARN_AMBIGUOUS_11_DIGIT = "AMBIGUOUS_11_DIGIT"
WARN_CHECK_DIGIT_APPENDED = "CHECK_DIGIT_APPENDED"
WARN_CHECK_DIGIT_RECOVERED = "CHECK_DIGIT_RECOVERED"
WARN_ZERO_PADDED = "ZERO_PADDED"
WARN_SCIENTIFIC_NOTATION = "SCIENTIFIC_NOTATION"
WARN_CASE_GTIN = "CASE_GTIN"
WARN_UPCE_EXPANDED = "UPCE_EXPANDED"
WARN_RESTRICTED_PREFIX = "RESTRICTED_PREFIX"
WARN_PRECISION_LOST = "PRECISION_LOST"

# MARK: - Normalization methods (how we got from input to canonical)

METHOD_CLEAN = "clean"
METHOD_STRIPPED_FORMATTING = "stripped_formatting"
METHOD_SCIENTIFIC = "scientific_notation"
METHOD_ZERO_PADDED = "zero_padded"
METHOD_CHECK_DIGIT_APPENDED = "check_digit_appended"
METHOD_UPCE_EXPANDED = "upce_expanded"
METHOD_GTIN14_UNWRAPPED = "gtin14_unwrapped"
METHOD_FAILED = "failed"

_SCIENTIFIC_RE = re.compile(r"^\s*[+-]?\d+(?:\.\d+)?[eE][+-]?\d+\s*$")
_NON_DIGIT_RE = re.compile(r"\D")

# GS1 prefixes that never identify a retail trade item. 2xxxxx is the
# variable-measure / in-store range (a deli scale prints these), 4xxxxx is
# reserved for retailer internal use. Both appear in distributor exports when
# someone pasted a shelf label instead of the manufacturer UPC — they will
# never match a Walmart or eBay listing, so flagging them up front saves an
# API call per occurrence.
_RESTRICTED_UPC_PREFIXES = ("2", "4")


# MARK: - Check digit


def gtin_check_digit(body: str) -> str:
    """Return the GS1 mod-10 check digit for ``body`` (all digits, no check).

    Weighting runs right-to-left over the body: the rightmost body digit gets
    weight 3, then 1, alternating. Works for UPC-A (11-digit body), EAN-13
    (12), GTIN-14 (13) and EAN-8 (7) alike — the algorithm is length-agnostic,
    which is why we don't need four of these.
    """
    if not body or not body.isdigit():
        raise ValueError(f"body must be non-empty digits, got {body!r}")
    total = 0
    for i, ch in enumerate(reversed(body)):
        weight = 3 if i % 2 == 0 else 1
        total += int(ch) * weight
    return str((10 - (total % 10)) % 10)


def is_valid_gtin(value: str) -> bool:
    """True iff ``value`` is all digits and its last digit is a valid check digit."""
    if not value or not value.isdigit() or len(value) < 2:
        return False
    return gtin_check_digit(value[:-1]) == value[-1]


# MARK: - UPC-E expansion


def _upce_body(number_system: str, payload: str) -> str | None:
    """Apply the GS1 UPC-E → UPC-A expansion table. Returns the 11-digit body."""
    last = payload[5]
    first5 = payload[:5]

    if last in "012":
        # mfr = first two payload digits + last + "00", item = "00" + digits 3-5
        body = f"{number_system}{first5[:2]}{last}0000{first5[2:5]}"
    elif last == "3":
        body = f"{number_system}{first5[:3]}00000{first5[3:5]}"
    elif last == "4":
        body = f"{number_system}{first5[:4]}00000{first5[4]}"
    else:  # 5-9
        body = f"{number_system}{first5}0000{last}"

    return body if len(body) == 11 else None


def expand_upce(upce: str) -> str | None:
    """Expand a UPC-E to its 12-digit UPC-A form, or ``None``.

    The 8-digit form is ``[number system][6 payload digits][check]``. The
    payload's last digit selects one of six expansion rules — a fixed table
    from the GS1 spec, not a heuristic.

    **We only expand forms that carry a verifiable check digit.** A bare
    6-digit payload expands to a UPC-A whose check digit we would be
    *inventing*, which means any 6-digit SKU in a distributor list — and ERP
    exports are full of them — would come out the far side looking like a
    perfectly valid UPC. That's worse than dropping the row: it burns an API
    call and can false-match a real product. So 6-digit input returns ``None``
    and 7-digit input is only accepted when read as ``[payload][check]``.
    """
    if not upce or not upce.isdigit():
        return None

    candidates: list[tuple[str, str, str]] = []  # (number_system, payload, check)
    if len(upce) == 7:
        # Read as [6 payload][check] with implied number system 0. The other
        # reading — [ns][6 payload] — has no check digit to verify, so we
        # don't take it.
        candidates.append(("0", upce[:6], upce[6]))
    elif len(upce) == 8:
        if upce[0] not in "01":
            return None
        candidates.append((upce[0], upce[1:7], upce[7]))
    else:
        return None

    for number_system, payload, check in candidates:
        body = _upce_body(number_system, payload)
        if body and gtin_check_digit(body) == check:
            return body + check
    return None


# MARK: - Case codes


def case_gtin_to_each(gtin14: str) -> str | None:
    """Derive the *each* GTIN-14 from a case/inner-pack GTIN-14.

    A GTIN-14 is ``[indicator][13-digit body][check]`` where the body after the
    indicator is the each's GTIN-13 payload. Indicator ``0`` already *is* the
    each. Indicators ``1``–``8`` are packaging levels (inner pack, case,
    pallet); ``9`` is variable-measure and has no fixed each.

    Distributor lists are full of case codes — the distributor sells you a case
    and prints the case barcode, but the *listing* you're pricing against on
    Walmart or eBay is the each. Without this derivation those rows come back
    as clean misses with no explanation.

    Returns ``None`` when ``gtin14`` isn't a case code we can unwrap.
    """
    if not gtin14 or len(gtin14) != 14 or not gtin14.isdigit():
        return None
    indicator = gtin14[0]
    if indicator == "0" or indicator == "9":
        return None
    body = gtin14[1:13]  # 12 digits: the each's payload, minus its check digit
    each13 = body + gtin_check_digit(body)
    return each13.zfill(14)


# MARK: - Result


@dataclass(frozen=True)
class NormalizedUpc:
    """The outcome of normalizing one spreadsheet cell.

    ``gtin14`` is the canonical, storage-and-lookup key. ``is_usable`` is the
    single flag the pipeline branches on — everything else is provenance for
    the UI and for debugging a list that came back with 400 misses.
    """

    raw: str
    gtin14: str | None
    method: str
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_usable(self) -> bool:
        """True when we produced a check-digit-valid GTIN worth spending an API call on."""
        return self.gtin14 is not None and WARN_INVALID_CHECK_DIGIT not in self.warnings

    @property
    def upc12(self) -> str | None:
        """The 12-digit UPC-A view, or ``None`` if the value doesn't fit one.

        A GTIN-14 with a non-zero indicator digit is a *case* code and has no
        UPC-A form — returning a truncated 12 digits there would silently turn
        a case into an each.
        """
        if not self.gtin14:
            return None
        if self.gtin14[:2] != "00":
            return None
        return self.gtin14[2:]

    @property
    def ean13(self) -> str | None:
        """The 13-digit EAN view, or ``None`` for true case codes."""
        if not self.gtin14:
            return None
        if self.gtin14[0] != "0":
            return None
        return self.gtin14[1:]

    @property
    def each_gtin14(self) -> str | None:
        """The each-level GTIN when this value is a case code, else ``None``."""
        if not self.gtin14:
            return None
        return case_gtin_to_each(self.gtin14)

    @property
    def search_value(self) -> str | None:
        """The form to hand an external API: UPC-A when available, else EAN-13.

        Walmart and eBay both index the 12-digit UPC for US goods; passing a
        zero-padded GTIN-14 to either returns nothing. When the row is a case
        code we search the *each* — the case barcode is what the distributor
        prints, but the listing you're pricing against is the single unit.
        """
        each = self.each_gtin14
        if each:
            if each[:2] == "00":
                return each[2:]
            if each[0] == "0":
                return each[1:]
        return self.upc12 or self.ean13 or self.gtin14


def _recover_scientific_check_digit(value: str, method: str) -> tuple[str, bool]:
    """Repair the trailing digit of a value that came through float coercion.

    Normally we refuse to "fix" a bad check digit — guessing which digit was
    wrong turns one bad row into one *confidently* bad row. Scientific notation
    is the documented exception: ``1.9594903632E+11`` expands to
    ``195949036320``, where the trailing ``0`` is float padding and the real
    check digit (``3``) was rounded away. We know exactly which digit is
    untrustworthy, so recomputing it is a repair, not a guess.

    Only fires for ``METHOD_SCIENTIFIC`` input. Returns ``(value, recovered)``.
    """
    if method != METHOD_SCIENTIFIC or len(value) < 2:
        return value, False
    repaired = value[:-1] + gtin_check_digit(value[:-1])
    return repaired, True


def _fail(raw: str, *warnings: str) -> NormalizedUpc:
    return NormalizedUpc(raw=raw, gtin14=None, method=METHOD_FAILED, warnings=tuple(warnings))


def _pad14(value: str) -> str:
    return value.zfill(14)


# MARK: - Entry point


def normalize_upc(raw: object) -> NormalizedUpc:  # noqa: C901 — a dispatch table, read top to bottom
    """Normalize one raw cell value into a canonical GTIN-14.

    Never raises. A value we can't make sense of comes back with
    ``gtin14=None`` and a warning explaining which stage gave up.
    """
    if raw is None:
        return _fail("", WARN_EMPTY)

    text = str(raw).strip()
    if not text:
        return _fail(text, WARN_EMPTY)

    warnings: list[str] = []
    method = METHOD_CLEAN

    # Stage 1 — undo Excel's numeric coercion. `1.9594903632E+11` has already
    # lost digits to float rounding in the *general* case, but Excel emits it
    # for values that still fit a double exactly, so expansion is lossless far
    # more often than not. Worst case we produce a wrong-but-well-formed UPC
    # that misses on lookup, same as if we'd dropped the row.
    if _SCIENTIFIC_RE.match(text):
        try:
            dec = Decimal(text)
            significant = len(dec.as_tuple().digits)
            text = format(dec, "f")
            warnings.append(WARN_SCIENTIFIC_NOTATION)
            method = METHOD_SCIENTIFIC
            # How many digits did the mantissa actually carry? `1.9594903632E+11`
            # carries 11 of the 12 a UPC-A needs — exactly the check digit was
            # rounded away, and `_recover_scientific_check_digit` puts it back.
            # `1.95949E+11` carries 6, so seven digits of the manufacturer and
            # item code are simply gone. No amount of arithmetic recovers those,
            # and a well-formed-but-wrong UPC is worse than an obvious failure:
            # it looks like a clean miss instead of a corrupt input.
            if significant < len(format(dec, "f").lstrip("0")) - 1:
                return _fail(str(raw), WARN_SCIENTIFIC_NOTATION, WARN_PRECISION_LOST)
        except (InvalidOperation, ValueError):
            return _fail(str(raw), WARN_NO_DIGITS)

    # Stage 2 — drop a trailing ".0" (and anything after a decimal point; UPCs
    # have no fractional part, so digits there are float noise, not data).
    if "." in text:
        head, _, tail = text.partition(".")
        if set(tail) <= {"0"} or not head:
            text = head or text
            if method == METHOD_CLEAN:
                method = METHOD_STRIPPED_FORMATTING

    # Stage 3 — strip spacing, dashes, quotes, currency junk.
    digits = _NON_DIGIT_RE.sub("", text)
    if not digits:
        return _fail(str(raw), WARN_NO_DIGITS)
    if digits != str(raw).strip() and method == METHOD_CLEAN:
        method = METHOD_STRIPPED_FORMATTING

    # Leading zeros beyond 14 are padding somebody else added; drop them
    # before we branch on length.
    stripped = digits.lstrip("0")
    if len(digits) > 14 and len(stripped) <= 14:
        digits = stripped.zfill(14)

    n = len(digits)

    # Stage 4 — length dispatch.
    if n > 14:
        return _fail(str(raw), WARN_TOO_LONG)

    if n == 14:
        gtin = digits
        if not is_valid_gtin(gtin):
            gtin, recovered = _recover_scientific_check_digit(gtin, method)
            if recovered:
                warnings.append(WARN_CHECK_DIGIT_RECOVERED)
            else:
                warnings.append(WARN_INVALID_CHECK_DIGIT)
        if gtin[0] != "0":
            # Non-zero indicator digit — this is a case/pallet code, not an each.
            warnings.append(WARN_CASE_GTIN)
        result_method = METHOD_GTIN14_UNWRAPPED if method == METHOD_CLEAN else method
        return _finish(str(raw), gtin, result_method, warnings)

    if n in (12, 13):
        value = digits
        if not is_valid_gtin(value):
            value, recovered = _recover_scientific_check_digit(value, method)
            warnings.append(
                WARN_CHECK_DIGIT_RECOVERED if recovered else WARN_INVALID_CHECK_DIGIT
            )
        return _finish(str(raw), _pad14(value), method, warnings)

    if n == 11:
        # The ambiguous case. Interpretation (a): a stripped leading zero.
        padded = digits.zfill(12)
        padded_ok = is_valid_gtin(padded)
        # Interpretation (b): a body missing its check digit.
        appended = digits + gtin_check_digit(digits)
        # `appended` validates by construction, so "both valid" reduces to
        # "padded also validates".
        if padded_ok:
            warnings.append(WARN_ZERO_PADDED)
            warnings.append(WARN_AMBIGUOUS_11_DIGIT)
            return _finish(str(raw), _pad14(padded), METHOD_ZERO_PADDED, warnings)
        warnings.append(WARN_CHECK_DIGIT_APPENDED)
        return _finish(str(raw), _pad14(appended), METHOD_CHECK_DIGIT_APPENDED, warnings)

    if n in (6, 7, 8):
        expanded = expand_upce(digits)
        if expanded:
            warnings.append(WARN_UPCE_EXPANDED)
            return _finish(str(raw), _pad14(expanded), METHOD_UPCE_EXPANDED, warnings)
        # An 8-digit value that isn't a valid UPC-E may still be an EAN-8.
        if n == 8 and is_valid_gtin(digits):
            return _finish(str(raw), _pad14(digits), method, warnings)
        # Otherwise fall through to the short-numeric handling below.

    if 6 <= n <= 11:
        # Short numerics are usually a UPC that lost more than one leading
        # zero (SKUs like "0001234" are common in ERP exports). Try padding
        # to 12 and validating; only accept when the check digit agrees,
        # because a coincidental match is far less likely than a real one.
        padded = digits.zfill(12)
        if is_valid_gtin(padded):
            warnings.append(WARN_ZERO_PADDED)
            return _finish(str(raw), _pad14(padded), METHOD_ZERO_PADDED, warnings)
        return _fail(str(raw), WARN_TOO_SHORT)

    return _fail(str(raw), WARN_TOO_SHORT)


def _finish(
    raw: str, gtin14: str, method: str, warnings: list[str]
) -> NormalizedUpc:
    """Attach prefix-level warnings and freeze the result."""
    upc_body = gtin14[2:] if gtin14[:2] == "00" else None
    if upc_body and upc_body[0] in _RESTRICTED_UPC_PREFIXES:
        warnings.append(WARN_RESTRICTED_PREFIX)
    # Preserve first-seen order while de-duplicating.
    seen: dict[str, None] = {}
    for w in warnings:
        seen.setdefault(w, None)
    return NormalizedUpc(raw=raw, gtin14=gtin14, method=method, warnings=tuple(seen))


# MARK: - Batch helper


@dataclass(frozen=True)
class NormalizationStats:
    """Aggregate normalization outcome for a whole list.

    Surfaced by ``POST /lists`` *before* any API spend, so a list that arrives
    with 2,900 unusable UPCs gets rejected at upload instead of after twenty
    minutes of crunching.
    """

    total: int
    usable: int
    unusable: int
    duplicates: int
    by_method: dict[str, int]
    by_warning: dict[str, int]

    @property
    def usable_pct(self) -> float:
        return round(100.0 * self.usable / self.total, 1) if self.total else 0.0


def summarize(results: list[NormalizedUpc]) -> NormalizationStats:
    """Roll a batch of normalization results into upload-time stats."""
    by_method: dict[str, int] = {}
    by_warning: dict[str, int] = {}
    seen: set[str] = set()
    duplicates = 0
    usable = 0

    for r in results:
        by_method[r.method] = by_method.get(r.method, 0) + 1
        for w in r.warnings:
            by_warning[w] = by_warning.get(w, 0) + 1
        if r.is_usable:
            usable += 1
            assert r.gtin14 is not None  # is_usable implies non-None
            if r.gtin14 in seen:
                duplicates += 1
            seen.add(r.gtin14)

    return NormalizationStats(
        total=len(results),
        usable=usable,
        unusable=len(results) - usable,
        duplicates=duplicates,
        by_method=dict(sorted(by_method.items())),
        by_warning=dict(sorted(by_warning.items())),
    )
