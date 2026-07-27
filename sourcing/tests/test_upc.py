"""UPC normalization tests.

Distributor lists arrive dirty in predictable ways, and every symptom in the
README's §4 table is a real spreadsheet artifact. The through-line of these
tests is that the module is allowed to *repair* what it can prove, and must
refuse to *guess* what it can't — a well-formed-but-wrong UPC is worse than an
obvious failure, because it looks like a clean miss instead of corrupt input.
"""

from __future__ import annotations

import pytest

from m15_sourcing.upc import (
    WARN_AMBIGUOUS_11_DIGIT,
    WARN_CASE_GTIN,
    WARN_CHECK_DIGIT_APPENDED,
    WARN_CHECK_DIGIT_RECOVERED,
    WARN_EMPTY,
    WARN_INVALID_CHECK_DIGIT,
    WARN_PRECISION_LOST,
    WARN_RESTRICTED_PREFIX,
    WARN_SCIENTIFIC_NOTATION,
    WARN_TOO_LONG,
    WARN_TOO_SHORT,
    WARN_UPCE_EXPANDED,
    METHOD_CHECK_DIGIT_APPENDED,
    METHOD_FAILED,
    METHOD_SCIENTIFIC,
    METHOD_UPCE_EXPANDED,
    case_gtin_to_each,
    expand_upce,
    gtin_check_digit,
    is_valid_gtin,
    normalize_upc,
    summarize,
)

# A real, check-digit-valid UPC-A used throughout as the "clean" reference.
CLEAN_UPC = "195949036323"
CLEAN_GTIN14 = "00195949036323"


# MARK: - Check digit


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("19594903632", "3"),   # UPC-A body
        ("81234567890", "1"),
        ("03600029145", "2"),
    ],
)
def test_check_digit_matches_known_good_upcs(body, expected):
    assert gtin_check_digit(body) == expected


def test_check_digit_is_length_agnostic():
    """One implementation covers UPC-A, EAN-13, GTIN-14 and EAN-8 alike."""
    upc_a = CLEAN_UPC
    ean_13 = "0" + upc_a
    gtin_14 = "00" + upc_a
    assert is_valid_gtin(upc_a)
    assert is_valid_gtin(ean_13)
    assert is_valid_gtin(gtin_14)


def test_check_digit_rejects_non_digits():
    with pytest.raises(ValueError):
        gtin_check_digit("12A45")


@pytest.mark.parametrize("bad", ["", "1", "abc", "19594903632X"])
def test_is_valid_gtin_is_false_on_junk(bad):
    assert is_valid_gtin(bad) is False


def test_is_valid_gtin_catches_a_single_transposed_digit():
    assert is_valid_gtin(CLEAN_UPC)
    assert not is_valid_gtin(CLEAN_UPC[:-1] + "4")


# MARK: - Clean input


def test_clean_upc_passes_through_to_canonical_gtin14():
    result = normalize_upc(CLEAN_UPC)
    assert result.is_usable
    assert result.gtin14 == CLEAN_GTIN14
    assert result.warnings == ()


def test_canonical_views_derive_from_gtin14():
    result = normalize_upc(CLEAN_UPC)
    assert result.upc12 == CLEAN_UPC
    assert result.ean13 == "0" + CLEAN_UPC
    assert result.search_value == CLEAN_UPC


def test_human_readable_spacing_is_stripped():
    """A PDF paste arrives as '8 12345 67890 1'."""
    result = normalize_upc("8 12345 67890 1")
    assert result.is_usable
    assert result.upc12 == "812345678901"


@pytest.mark.parametrize("raw", ["195949036323", " 195949036323 ", "195-949-036-323"])
def test_formatting_noise_does_not_change_the_answer(raw):
    assert normalize_upc(raw).gtin14 == CLEAN_GTIN14


# MARK: - Excel numeric coercion


def test_scientific_notation_expands_and_recovers_the_check_digit():
    """`7.7768100005E+11` lost exactly its check digit to float rounding.

    We know *which* digit is untrustworthy, so recomputing it is a repair rather
    than a guess — the one documented exception to never fixing a check digit.
    """
    result = normalize_upc("7.7768100005E+11")
    assert result.is_usable
    assert result.method == METHOD_SCIENTIFIC
    assert WARN_SCIENTIFIC_NOTATION in result.warnings
    assert WARN_CHECK_DIGIT_RECOVERED in result.warnings
    assert is_valid_gtin(result.upc12)


def test_scientific_notation_that_lost_real_digits_is_dropped():
    """`1.95949E+11` carries 6 significant digits; seven are simply gone.

    No arithmetic recovers those, so this must fail loudly instead of producing
    a plausible-looking UPC that burns an API call and can false-match.
    """
    result = normalize_upc("1.95949E+11")
    assert not result.is_usable
    assert result.gtin14 is None
    assert result.method == METHOD_FAILED
    assert WARN_PRECISION_LOST in result.warnings


def test_trailing_dot_zero_is_stripped():
    """`195949036323.0` — same coercion, under 15 significant digits."""
    result = normalize_upc("195949036323.0")
    assert result.is_usable
    assert result.upc12 == CLEAN_UPC


def test_float_input_is_accepted():
    """openpyxl hands back a float for any unformatted numeric cell."""
    result = normalize_upc(195949036323.0)
    assert result.is_usable
    assert result.upc12 == CLEAN_UPC


# MARK: - The ambiguous 11-digit case


def test_eleven_digits_appends_a_check_digit_when_padding_fails():
    """`88381675681` is a Makita body missing its check digit."""
    result = normalize_upc("88381675681")
    assert result.is_usable
    assert result.method == METHOD_CHECK_DIGIT_APPENDED
    assert WARN_CHECK_DIGIT_APPENDED in result.warnings
    assert result.upc12 == "883816756817"
    assert is_valid_gtin(result.upc12)


def test_eleven_digits_that_validate_when_zero_padded_are_flagged_ambiguous():
    """Both readings are legal here, so the row is flagged rather than silently picked.

    A leading zero that Excel ate and a body missing its check digit are
    genuinely indistinguishable from 11 digits alone.
    """
    # Construct a valid 12-digit UPC-A that starts with '0', then drop that
    # leading zero — exactly what Excel does to it. Built rather than
    # hardcoded so the fixture can't drift out of check-digit validity.
    body = "01234567890"
    full_upc_a = body + gtin_check_digit(body)
    assert len(full_upc_a) == 12
    assert full_upc_a[0] == "0"
    assert is_valid_gtin(full_upc_a)

    eleven_digits = full_upc_a[1:]
    assert len(eleven_digits) == 11

    result = normalize_upc(eleven_digits)
    assert result.is_usable
    # Reading (a) — restore the eaten zero — validates, so it wins...
    assert result.upc12 == full_upc_a
    # ...but reading (b) is equally legal, and the row says so rather than
    # presenting a coin-flip as a fact.
    assert WARN_AMBIGUOUS_11_DIGIT in result.warnings


# MARK: - UPC-E


def test_upce_expands_to_upc_a():
    """`04963406` is a real UPC-E; the expansion table is from the GS1 spec."""
    result = normalize_upc("04963406")
    assert result.is_usable
    assert result.method == METHOD_UPCE_EXPANDED
    assert WARN_UPCE_EXPANDED in result.warnings
    assert result.upc12 == "049000006346"
    assert is_valid_gtin(result.upc12)


def test_upce_expansion_round_trips_the_check_digit():
    expanded = expand_upce("04963406")
    assert expanded is not None
    assert is_valid_gtin(expanded)


def test_bare_six_digit_payload_is_refused():
    """Expanding six digits would *invent* a check digit.

    ERP exports are full of 6-digit SKUs; accepting them would turn every one
    into a perfectly valid-looking UPC.
    """
    assert expand_upce("123456") is None


def test_upce_rejects_number_systems_other_than_0_and_1():
    assert expand_upce("54963406") is None


def test_invalid_upce_check_digit_is_not_expanded():
    assert expand_upce("04963400") is None


# MARK: - Case codes


def test_case_gtin_is_flagged_not_silently_unwrapped():
    """A non-zero indicator digit means a case, and a case is not an each."""
    result = normalize_upc("10195949036320")
    assert result.is_usable
    assert WARN_CASE_GTIN in result.warnings
    # The case code has no UPC-A form — truncating would turn it into an each.
    assert result.upc12 is None


def test_case_gtin_searches_the_each():
    """The distributor prints the case barcode; the listing you price is the each."""
    result = normalize_upc("10195949036320")
    assert result.each_gtin14 == CLEAN_GTIN14
    assert result.search_value == CLEAN_UPC


def test_indicator_zero_is_already_an_each():
    assert case_gtin_to_each(CLEAN_GTIN14) is None


def test_indicator_nine_is_variable_measure_with_no_fixed_each():
    assert case_gtin_to_each("9" + CLEAN_GTIN14[1:]) is None


def test_ean13_with_us_zero_prefix_reduces_to_upc_a():
    result = normalize_upc("0" + CLEAN_UPC)
    assert result.is_usable
    assert result.upc12 == CLEAN_UPC


# MARK: - Failure modes


@pytest.mark.parametrize(
    ("raw", "warning"),
    [
        (None, WARN_EMPTY),
        ("", WARN_EMPTY),
        ("   ", WARN_EMPTY),
        ("999", WARN_TOO_SHORT),
        ("123456789012345678", WARN_TOO_LONG),
    ],
)
def test_unusable_input_fails_with_an_explanatory_warning(raw, warning):
    result = normalize_upc(raw)
    assert not result.is_usable
    assert result.gtin14 is None
    assert warning in result.warnings


def test_normalize_never_raises_on_arbitrary_junk():
    """One junk cell must not fail a 3,000-row upload."""
    for junk in ["N/A", "see notes", "—", "$4.99", "TBD", object()]:
        result = normalize_upc(junk)
        assert result.method == METHOD_FAILED or result.gtin14 is not None


def test_bad_check_digit_is_kept_but_marked_unusable():
    """Never silently 'corrected' — a guessed repair makes one bad row confident."""
    bad = CLEAN_UPC[:-1] + "4"
    result = normalize_upc(bad)
    assert WARN_INVALID_CHECK_DIGIT in result.warnings
    assert not result.is_usable
    # Still carried, so the UI can show what arrived.
    assert result.gtin14 is not None


def test_restricted_prefix_is_flagged():
    """Prefixes 2 and 4 are in-store / variable-weight codes with no global listing."""
    body = "20123456789"
    value = body + gtin_check_digit(body)
    result = normalize_upc(value)
    assert WARN_RESTRICTED_PREFIX in result.warnings


def test_warnings_are_deduplicated_but_keep_first_seen_order():
    result = normalize_upc("7.7768100005E+11")
    assert len(result.warnings) == len(set(result.warnings))
    assert result.warnings[0] == WARN_SCIENTIFIC_NOTATION


# MARK: - Batch summary


def test_summarize_counts_usable_and_buckets_by_method():
    raws = [CLEAN_UPC, "88381675681", "04963406", "999", "1.95949E+11"]
    stats = summarize([normalize_upc(r) for r in raws])

    assert stats.total == 5
    assert stats.usable == 3
    assert stats.unusable == 2
    assert stats.usable_pct == 60.0
    assert stats.by_method[METHOD_FAILED] == 2
    assert stats.by_method[METHOD_CHECK_DIGIT_APPENDED] == 1


def test_summarize_counts_duplicates_by_canonical_gtin():
    """The same product reached by three different dirty spellings is one item."""
    results = [
        normalize_upc(CLEAN_UPC),
        normalize_upc("0" + CLEAN_UPC),        # EAN-13 spelling
        normalize_upc(CLEAN_UPC + ".0"),        # Excel float spelling
    ]
    stats = summarize(results)
    assert stats.usable == 3
    assert stats.duplicates == 2


def test_summarize_of_nothing_does_not_divide_by_zero():
    stats = summarize([])
    assert stats.total == 0
    assert stats.usable_pct == 0.0
