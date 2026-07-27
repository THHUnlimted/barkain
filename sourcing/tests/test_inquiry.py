"""Distributor inquiry draft tests.

Turning 12 candidates into 12 sent emails should be one click, not an afternoon.
The draft is plain text with several optional blocks, and the failure mode worth
guarding is a template that half-renders — a draft arriving with a dangling
"Brand:" label or a run of blank lines reads as machine-generated and gets
deleted, which defeats the entire feature.
"""

from __future__ import annotations

from decimal import Decimal

from m15_sourcing.inquiry import SellerProfile, build_inquiry

SELLER = SellerProfile(
    business_name="Northbound Trading Co.",
    contact_name="Mike",
    email="mike@northbound.example",
    phone="555-0101",
    resale_certificate_state="NY",
    years_in_business=3,
)

MINIMAL_SELLER = SellerProfile(business_name="Solo Reseller LLC", ein_on_file=False)


# MARK: - Subject


def test_subject_names_the_brand_and_product():
    draft = build_inquiry(seller=SELLER, product_name="Cordless Drill 20V Kit", brand="DeWalt")
    assert draft.subject == "Wholesale inquiry — DeWalt Cordless Drill 20V Kit"


def test_subject_without_a_brand_has_no_dangling_space():
    draft = build_inquiry(seller=SELLER, product_name="Cordless Drill 20V Kit")
    assert draft.subject == "Wholesale inquiry — Cordless Drill 20V Kit"
    assert "  " not in draft.subject


def test_a_very_long_product_name_is_truncated():
    draft = build_inquiry(seller=SELLER, product_name="X" * 300, brand="Acme")
    assert len(draft.subject) <= 120
    assert draft.subject.endswith("...")


# MARK: - Quantity phrasing


def test_moq_is_expressed_in_the_distributor_s_own_units():
    draft = build_inquiry(
        seller=SELLER, product_name="Widget", case_pack=12, moq=24
    )
    assert "24 units (2 cases of 12)" in draft.body


def test_a_single_case_is_not_pluralized():
    draft = build_inquiry(seller=SELLER, product_name="Widget", case_pack=12, moq=12)
    assert "1 case of 12" in draft.body
    assert "1 cases" not in draft.body


def test_moq_without_a_case_pack_reads_as_bare_units():
    draft = build_inquiry(seller=SELLER, product_name="Widget", moq=50)
    assert "50 units" in draft.body


def test_case_pack_without_an_moq_offers_one_case():
    draft = build_inquiry(seller=SELLER, product_name="Widget", case_pack=6)
    assert "one case of 6 units" in draft.body


def test_neither_falls_back_to_a_generic_opening_order():
    draft = build_inquiry(seller=SELLER, product_name="Widget")
    assert "an opening order" in draft.body


# MARK: - Optional blocks


def test_identifiers_are_listed_when_present():
    draft = build_inquiry(
        seller=SELLER,
        product_name="Widget",
        brand="Acme",
        upc="195949036323",
        sku="ACM-1234",
    )
    assert "Brand: Acme" in draft.body
    assert "UPC: 195949036323" in draft.body
    assert "SKU: ACM-1234" in draft.body


def test_absent_identifiers_leave_no_dangling_labels():
    """A draft with an empty 'UPC:' line reads as a half-rendered template."""
    draft = build_inquiry(seller=SELLER, product_name="Widget")
    assert "Brand:" not in draft.body
    assert "UPC:" not in draft.body
    assert "SKU:" not in draft.body


def test_quoted_cost_invites_a_better_number():
    draft = build_inquiry(
        seller=SELLER, product_name="Widget", quoted_unit_cost=Decimal("12.50")
    )
    assert "$12.50/unit" in draft.body
    assert "if you can do better at volume" in draft.body


def test_no_cost_line_when_no_quote_is_known():
    draft = build_inquiry(seller=SELLER, product_name="Widget")
    assert "/unit" not in draft.body


def test_named_distributor_gets_a_personal_greeting():
    draft = build_inquiry(
        seller=SELLER, product_name="Widget", distributor_name="Pat"
    )
    assert draft.body.startswith("Hi Pat,")


def test_an_unnamed_distributor_gets_a_neutral_greeting():
    draft = build_inquiry(seller=SELLER, product_name="Widget")
    assert draft.body.startswith("Hello,")


def test_tenure_is_mentioned_only_when_known():
    with_tenure = build_inquiry(seller=SELLER, product_name="Widget")
    without = build_inquiry(seller=MINIMAL_SELLER, product_name="Widget")
    assert "3 years" in with_tenure.body
    assert "years" not in without.body


# MARK: - Paperwork


def test_paperwork_lists_what_the_seller_actually_has():
    draft = build_inquiry(seller=SELLER, product_name="Widget")
    assert "NY resale certificate" in draft.body
    assert "EIN" in draft.body


def test_a_seller_with_no_documents_still_offers_something():
    draft = build_inquiry(seller=MINIMAL_SELLER, product_name="Widget")
    assert "reseller documentation on request" in draft.body


# MARK: - Formatting


def test_optional_blocks_do_not_leave_runs_of_blank_lines():
    """Every combination of omitted blocks must still read as hand-written."""
    for kwargs in (
        {},
        {"brand": "Acme"},
        {"upc": "195949036323"},
        {"quoted_unit_cost": Decimal("9.99")},
        {"case_pack": 12, "moq": 24},
        {"brand": "Acme", "upc": "195949036323", "sku": "A-1", "moq": 24, "case_pack": 12},
    ):
        draft = build_inquiry(seller=MINIMAL_SELLER, product_name="Widget", **kwargs)
        assert "\n\n\n" not in draft.body, kwargs


def test_signature_omits_missing_contact_lines():
    draft = build_inquiry(seller=MINIMAL_SELLER, product_name="Widget")
    assert "Solo Reseller LLC" in draft.body
    # No blank signature lines where the email/phone would have been.
    assert not draft.body.rstrip().endswith("\n\n")


def test_body_ends_with_exactly_one_newline():
    draft = build_inquiry(seller=SELLER, product_name="Widget")
    assert draft.body.endswith("\n")
    assert not draft.body.endswith("\n\n")


def test_recipient_is_carried_when_known():
    draft = build_inquiry(
        seller=SELLER, product_name="Widget", distributor_email="sales@dist.example"
    )
    assert draft.to == "sales@dist.example"
    assert draft.as_dict()["to"] == "sales@dist.example"


def test_recipient_is_none_when_unknown():
    assert build_inquiry(seller=SELLER, product_name="Widget").to is None
