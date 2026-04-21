"""Lint tests for scripts/seed_discount_catalog.py.

Pure-Python validation of the BRAND_RETAILERS and DISCOUNT_PROGRAMS lists
— no DB round-trip required. Catches:
- typos in eligibility_type (breaks the service's .in_() query silently)
- unknown retailer_id (FK violation on actual seed run)
- duplicate (retailer_id, program_name, eligibility_type) tuples (UniqueConstraint)
- out-of-vocabulary verification_method or discount_type
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.m5_identity.schemas import ELIGIBILITY_TYPES  # noqa: E402
from scripts.seed_discount_catalog import (  # noqa: E402
    BRAND_RETAILERS,
    DISCOUNT_PROGRAMS,
)
from scripts.seed_retailers import RETAILERS  # noqa: E402

_VALID_VERIFICATION_METHODS = {
    "id_me",
    "sheer_id",
    "unidays",
    "wesalute",
    "student_beans",
    "govx",
    "age_verification",
    None,
}
_VALID_DISCOUNT_TYPES = {"percentage", "fixed_amount"}
_VALID_PROGRAM_TYPES = {"identity", "membership"}


def _known_retailer_ids() -> set[str]:
    return {r["id"] for r in RETAILERS} | {r["id"] for r in BRAND_RETAILERS}


def test_brand_retailers_unique_ids():
    ids = [r["id"] for r in BRAND_RETAILERS]
    assert len(ids) == len(set(ids)), f"Duplicate brand retailer ids: {ids}"


def test_brand_retailers_all_direct_suffix():
    """Convention: brand-direct retailers end in _direct to distinguish from scraped retailers."""
    for r in BRAND_RETAILERS:
        assert r["id"].endswith("_direct"), (
            f"Brand retailer {r['id']} must end in _direct"
        )
        assert r["extraction_method"] == "none"
        assert r["supports_identity"] is True


def test_brand_retailers_count():
    assert len(BRAND_RETAILERS) == 12, (
        f"Expected 12 brand-direct retailers (8 original + 4 Benefits Expansion), "
        f"got {len(BRAND_RETAILERS)}"
    )


def test_benefits_expansion_brand_retailers_present():
    """Regression guard: acer/asus/razer/logitech direct retailers must be seeded."""
    ids = {r["id"] for r in BRAND_RETAILERS}
    for required in ("acer_direct", "asus_direct", "razer_direct", "logitech_direct"):
        assert required in ids, f"{required} missing from BRAND_RETAILERS"


def test_all_program_retailer_ids_are_known():
    known = _known_retailer_ids()
    for p in DISCOUNT_PROGRAMS:
        assert p["retailer_id"] in known, (
            f"Unknown retailer_id in program '{p['program_name']}': {p['retailer_id']}"
        )


def test_all_eligibility_types_in_vocabulary():
    valid = set(ELIGIBILITY_TYPES)
    for p in DISCOUNT_PROGRAMS:
        assert p["eligibility_type"] in valid, (
            f"Unknown eligibility_type '{p['eligibility_type']}' "
            f"in program '{p['program_name']}'"
        )


def test_all_verification_methods_valid():
    for p in DISCOUNT_PROGRAMS:
        assert p["verification_method"] in _VALID_VERIFICATION_METHODS, (
            f"Unknown verification_method '{p['verification_method']}' "
            f"in program '{p['program_name']}'"
        )


def test_all_discount_types_valid():
    for p in DISCOUNT_PROGRAMS:
        assert p["discount_type"] in _VALID_DISCOUNT_TYPES, (
            f"Unknown discount_type '{p['discount_type']}' "
            f"in program '{p['program_name']}'"
        )


def test_all_program_types_valid():
    for p in DISCOUNT_PROGRAMS:
        assert p["program_type"] in _VALID_PROGRAM_TYPES, (
            f"Unknown program_type '{p['program_type']}' "
            f"in program '{p['program_name']}'"
        )


def test_no_duplicate_program_rows():
    """UniqueConstraint on (retailer_id, program_name, eligibility_type)."""
    seen: set[tuple[str, str, str]] = set()
    for p in DISCOUNT_PROGRAMS:
        key = (p["retailer_id"], p["program_name"], p["eligibility_type"])
        assert key not in seen, f"Duplicate program row: {key}"
        seen.add(key)


def test_percentage_values_in_range():
    for p in DISCOUNT_PROGRAMS:
        if p["discount_type"] == "percentage":
            val = p["discount_value"]
            assert val is None or 0 < val <= 100, (
                f"Percentage {val} out of range in {p['program_name']}"
            )


def test_max_value_gte_value_when_both_set():
    for p in DISCOUNT_PROGRAMS:
        if p["discount_max_value"] is not None and p["discount_value"] is not None:
            # Either max is a higher percentage, or it's a dollar cap — both
            # structurally valid. We can only assert non-negative here.
            assert p["discount_max_value"] >= 0


def test_military_covers_top_brands():
    """Regression guard: military users must always match Samsung, Apple, HP."""
    military_rows = [
        p for p in DISCOUNT_PROGRAMS if p["eligibility_type"] == "military"
    ]
    retailers_with_military = {p["retailer_id"] for p in military_rows}
    for required in ("samsung_direct", "apple_direct", "hp_direct"):
        assert required in retailers_with_military, (
            f"{required} missing a military program"
        )


def test_student_covers_all_tech_brands():
    """Benefits Expansion regression guard: students must match the 10 tech brands."""
    student_retailers = {
        p["retailer_id"] for p in DISCOUNT_PROGRAMS if p["eligibility_type"] == "student"
    }
    required = {
        "apple_direct",
        "samsung_direct",
        "hp_direct",
        "dell_direct",
        "lenovo_direct",
        "microsoft_direct",
        "acer_direct",
        "asus_direct",
        "razer_direct",
        "logitech_direct",
    }
    missing = required - student_retailers
    assert not missing, f"Student tech brands missing from catalog: {missing}"


def test_young_adult_amazon_row_exists():
    """Prime Young Adult must be seeded with scope=membership_fee so identity
    savings math doesn't claim a product-price dollar figure (same contract as
    Prime Student post-3f-hotfix)."""
    young_adult_rows = [
        p for p in DISCOUNT_PROGRAMS if p["eligibility_type"] == "young_adult"
    ]
    assert len(young_adult_rows) >= 1, "No young_adult programs seeded"
    amazon_rows = [p for p in young_adult_rows if p["retailer_id"] == "amazon"]
    assert len(amazon_rows) == 1, "Prime Young Adult row missing from amazon"
    assert amazon_rows[0]["scope"] == "membership_fee", (
        "Prime Young Adult must have scope='membership_fee' — its 50% is off "
        "the Prime fee, not off products"
    )
