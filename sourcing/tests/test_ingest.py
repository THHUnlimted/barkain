"""Spreadsheet ingest tests.

A distributor price list is not a clean CSV. It has letterhead above the header
row, money in four different spellings, a cost column that might be per-unit or
per-case, and null placeholders that aren't empty strings. Every test here is a
shape that showed up in a real list.

The bundled ``sample_price_list.csv`` is the end-to-end fixture — it's also what
``demo_crunch.py`` runs on, so a regression here shows up in the CI smoke step
too.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from m15_sourcing.ingest import (
    IngestError,
    IngestedRow,
    ingest,
    parse_int,
    parse_money,
    read_table,
)

SAMPLE_CSV = Path(__file__).resolve().parent.parent / "sample_price_list.csv"


def _csv(text: str) -> bytes:
    return text.encode("utf-8")


# MARK: - Money parsing


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("$1,234.56", Decimal("1234.56")),
        ("1234.56 USD", Decimal("1234.56")),
        ("12.00", Decimal("12.00")),
        ("  $4.99  ", Decimal("4.99")),
        (12.5, Decimal("12.5")),
        (12, Decimal("12")),
        (Decimal("3.25"), Decimal("3.25")),
    ],
)
def test_parse_money_handles_the_common_spellings(raw, expected):
    assert parse_money(raw) == expected


def test_parse_money_reads_accounting_negatives():
    """`(2.50)` is a credit, not the number 2.50."""
    assert parse_money("(2.50)") == Decimal("-2.50")


@pytest.mark.parametrize("raw", [None, "", "-", "--", "n/a", "N/A", "null", "TBD", "."])
def test_parse_money_returns_none_for_null_placeholders(raw):
    assert parse_money(raw) is None


def test_parse_money_never_raises_on_junk():
    """One junk cell shouldn't fail a 3,000-row upload."""
    assert parse_money("see attached") is None
    assert parse_money("$$$") is None


# MARK: - Integer parsing


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("12 ea", 12),
        ("1,200", 1200),
        ("12.0", 12),
        (12.0, 12),
        (12, 12),
        ("  6  ", 6),
    ],
)
def test_parse_int_handles_the_common_spellings(raw, expected):
    assert parse_int(raw) == expected


def test_parse_int_does_not_turn_a_decimal_into_a_bigger_number():
    """Stripping the dot from '12.0' naively would produce 120."""
    assert parse_int("12.0") == 12


def test_parse_int_rejects_booleans():
    """`True` is an int in Python; a case pack of 1 from a checkbox is nonsense."""
    assert parse_int(True) is None
    assert parse_int(False) is None


@pytest.mark.parametrize("raw", [None, "", "n/a", "-"])
def test_parse_int_returns_none_for_null_placeholders(raw):
    assert parse_int(raw) is None


# MARK: - Header detection


def test_header_is_found_below_letterhead():
    """Real lists open with a company name, a date, and a blank row."""
    csv = _csv(
        "ACME WHOLESALE DISTRIBUTORS\n"
        "Price list effective 2026-07-01\n"
        "\n"
        "UPC,Description,Unit Cost,Case Pack\n"
        "195949036323,Widget,12.00,6\n"
    )
    result = ingest(csv, "list.csv")
    assert result.mapping.header_row_index == 3
    assert len(result.rows) == 1
    assert result.rows[0].description == "Widget"


def test_rows_above_the_header_are_reported_not_silently_eaten():
    csv = _csv(
        "ACME WHOLESALE\n"
        "\n"
        "UPC,Description,Unit Cost\n"
        "195949036323,Widget,12.00\n"
    )
    result = ingest(csv, "list.csv")
    assert any("above the header" in w for w in result.warnings)


def test_a_file_with_no_header_is_an_upload_time_failure():
    """Not a per-row problem — there's nothing to map."""
    with pytest.raises(IngestError):
        ingest(_csv("1,2,3\n4,5,6\n"), "list.csv")


def test_an_empty_file_is_an_upload_time_failure():
    with pytest.raises(IngestError):
        ingest(_csv(""), "list.csv")


# MARK: - Column mapping


def test_column_synonyms_map_to_logical_fields():
    csv = _csv(
        "Item Barcode,Product Name,Mfr,Your Cost,Pack,Min Order,Retail\n"
        "195949036323,Widget,Acme,12.00,6,24,29.99\n"
    )
    result = ingest(csv, "list.csv")
    cols = result.mapping.columns
    assert "upc" in cols
    assert "description" in cols
    assert "brand" in cols
    assert result.mapping.has_required


def test_a_list_without_a_upc_column_cannot_be_crunched():
    with pytest.raises(IngestError):
        ingest(_csv("Description,Unit Cost\nWidget,12.00\n"), "list.csv")


def test_unmapped_headers_are_preserved_for_the_ui():
    csv = _csv(
        "UPC,Unit Cost,Warehouse Bin,Season Code\n195949036323,12.00,A-14,SS26\n"
    )
    result = ingest(csv, "list.csv")
    assert "Warehouse Bin" in result.mapping.unmapped_headers
    assert "Season Code" in result.mapping.unmapped_headers


# MARK: - Cost semantics


def test_explicit_unit_cost_wins_over_derived():
    row = IngestedRow(
        row_index=0,
        raw={},
        upc=None,  # type: ignore[arg-type]
        unit_cost=Decimal("2.00"),
        case_cost=Decimal("60.00"),
        case_pack=12,
    )
    assert row.effective_unit_cost == Decimal("2.00")


def test_case_cost_divides_down_when_no_unit_cost_is_given():
    """The single most common source of 'everything looks unprofitable'."""
    row = IngestedRow(
        row_index=0,
        raw={},
        upc=None,  # type: ignore[arg-type]
        case_cost=Decimal("60.00"),
        case_pack=12,
    )
    assert row.effective_unit_cost == Decimal("5.00")


def test_case_cost_without_a_pack_size_yields_no_unit_cost():
    row = IngestedRow(
        row_index=0, raw={}, upc=None, case_cost=Decimal("60.00")  # type: ignore[arg-type]
    )
    assert row.effective_unit_cost is None


def test_cost_is_case_cost_override_reinterprets_an_ambiguous_column():
    """Lists whose only cost column is per-unit-looking but billed per case."""
    csv = _csv("UPC,Description,Cost,Case Pack\n195949036323,Widget,60.00,12\n")
    result = ingest(csv, "list.csv", cost_is_case_cost=True)
    assert result.rows[0].effective_unit_cost == Decimal("5.00")


def test_a_bare_price_column_is_read_as_the_wholesale_cost():
    """On a distributor list, "Price" is what you pay — retail is spelled otherwise.

    This is the exact case ``ingest(cost_is_case_cost=...)`` cites in its own
    docstring ("labelled ambiguously ('Price')"), so the override has to be
    able to fire on it.
    """
    csv = _csv("UPC,Description,Price,Case Pack\n195949036323,Widget,60.00,12\n")
    result = ingest(csv, "list.csv", cost_is_case_cost=True)
    assert result.rows[0].effective_unit_cost == Decimal("5.00")


def test_a_bare_price_column_without_the_override_is_a_unit_cost():
    csv = _csv("UPC,Description,Price\n195949036323,Widget,12.00\n")
    result = ingest(csv, "list.csv")
    assert result.rows[0].unit_cost == Decimal("12.00")


# MARK: - Price-column collisions
#
# A bare "price" synonym on `unit_cost` substring-matches every retail column
# heading too, so these pin that `msrp` still wins its own columns. Regressing
# any of them maps the retail price in as cost, which reads as "everything is
# unprofitable" rather than as an error.


@pytest.mark.parametrize(
    "retail_header",
    ["MSRP", "Retail Price", "List Price", "Retail", "SRP", "Suggested Retail"],
)
def test_retail_columns_are_not_stolen_by_the_bare_price_synonym(retail_header):
    csv = _csv(
        f"UPC,Description,Price,{retail_header}\n195949036323,Widget,12.00,29.99\n"
    )
    result = ingest(csv, "list.csv")
    cols = result.mapping.columns

    assert cols["unit_cost"] == 2, f"'Price' should be the cost column, got {cols}"
    assert cols["msrp"] == 3, f"'{retail_header}' should be MSRP, got {cols}"
    assert result.rows[0].unit_cost == Decimal("12.00")
    assert result.rows[0].msrp == Decimal("29.99")


def test_a_retail_only_list_does_not_borrow_msrp_as_a_cost():
    """No cost column is an upload failure, not a silent 0% margin."""
    csv = _csv("UPC,Description,Retail Price\n195949036323,Widget,29.99\n")
    with pytest.raises(IngestError, match="No cost column found"):
        ingest(csv, "list.csv")


def test_specific_cost_headers_still_beat_the_bare_price_synonym():
    """'Unit Price' and 'Retail Price' must not swap."""
    csv = _csv(
        "UPC,Description,Unit Price,Retail Price\n195949036323,Widget,12.00,29.99\n"
    )
    result = ingest(csv, "list.csv")
    assert result.rows[0].unit_cost == Decimal("12.00")
    assert result.rows[0].msrp == Decimal("29.99")


def test_case_cost_still_outranks_a_bare_price_column():
    """The 12x cost error the resolution order exists to prevent."""
    csv = _csv(
        "UPC,Description,Case Cost,Case Pack\n195949036323,Widget,60.00,12\n"
    )
    result = ingest(csv, "list.csv")
    assert result.rows[0].case_cost == Decimal("60.00")
    assert result.rows[0].effective_unit_cost == Decimal("5.00")


def test_default_case_pack_fills_lists_that_state_it_in_prose():
    csv = _csv("UPC,Description,Case Cost\n195949036323,Widget,60.00\n")
    result = ingest(csv, "list.csv", default_case_pack=12)
    assert result.rows[0].case_pack == 12
    assert result.rows[0].effective_unit_cost == Decimal("5.00")


# MARK: - Minimum commitment


def test_minimum_buy_prefers_moq_then_falls_back_to_one_case():
    with_moq = IngestedRow(row_index=0, raw={}, upc=None, moq=24, case_pack=6)  # type: ignore[arg-type]
    case_only = IngestedRow(row_index=0, raw={}, upc=None, case_pack=6)  # type: ignore[arg-type]
    neither = IngestedRow(row_index=0, raw={}, upc=None)  # type: ignore[arg-type]

    assert with_moq.minimum_buy_units == 24
    assert case_only.minimum_buy_units == 6
    assert neither.minimum_buy_units is None


def test_minimum_buy_cost_is_the_capital_at_risk():
    row = IngestedRow(
        row_index=0,
        raw={},
        upc=None,  # type: ignore[arg-type]
        unit_cost=Decimal("12.00"),
        moq=24,
    )
    assert row.minimum_buy_cost == Decimal("288.00")


def test_minimum_buy_cost_is_none_without_a_cost():
    row = IngestedRow(row_index=0, raw={}, upc=None, moq=24)  # type: ignore[arg-type]
    assert row.minimum_buy_cost is None


# MARK: - Delimiters and formats


def test_tab_separated_is_detected():
    tsv = _csv("UPC\tDescription\tUnit Cost\n195949036323\tWidget\t12.00\n")
    result = ingest(tsv, "list.tsv")
    assert len(result.rows) == 1
    assert result.rows[0].unit_cost == Decimal("12.00")


def test_read_table_returns_rows_of_cells():
    table = read_table(_csv("a,b\n1,2\n"), "x.csv")
    assert table[0][:2] == ["a", "b"]


# MARK: - The bundled sample


def test_sample_price_list_ingests_the_way_the_demo_reports():
    """Pins the fixture the CI smoke step runs on.

    9 data rows, 4 letterhead rows above the header, and a header on row 4 —
    the numbers ``demo_crunch.py`` prints.
    """
    result = ingest(SAMPLE_CSV.read_bytes(), SAMPLE_CSV.name)
    assert result.mapping.header_row_index == 4
    assert len(result.rows) == 9
    assert result.skipped_rows == 0
    assert result.mapping.has_required


def test_sample_price_list_yields_seven_usable_upcs():
    """The other two are the deliberately unrecoverable ones."""
    result = ingest(SAMPLE_CSV.read_bytes(), SAMPLE_CSV.name)
    usable = [r for r in result.rows if r.upc.is_usable]
    assert len(usable) == 7


def test_max_rows_bounds_a_runaway_list():
    body = "\n".join(f"19594903632{i % 10},Widget {i},12.00" for i in range(50))
    csv = _csv("UPC,Description,Unit Cost\n" + body + "\n")
    result = ingest(csv, "list.csv", max_rows=10)
    assert len(result.rows) <= 10
