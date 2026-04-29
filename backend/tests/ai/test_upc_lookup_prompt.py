"""Anti-condensation regression tests for the 3o-C UPC lookup prompt rewrite.

The Phase 1 L13 lesson — agent shortened the Gemini system instruction
during implementation — is the load-bearing failure these tests catch.
Pin every structural element of the rewrite so any future condensation
trips a bright-red unit test.

The tests assert structural integrity, not Gemini behavior. The mini-bench
in scripts/bench_grounded_3o_c.py covers real-API behavior.
"""

from ai.prompts.upc_lookup import (
    UPC_LOOKUP_SYSTEM_INSTRUCTION,
    build_upc_lookup_prompt,
    build_upc_retry_prompt,
)


def test_upc_lookup_system_instruction_has_do_not_condense_marker():
    assert "# DO NOT CONDENSE OR SHORTEN" in UPC_LOOKUP_SYSTEM_INSTRUCTION


def test_upc_lookup_system_instruction_min_length():
    # Floor of 3000 chars is the regression boundary; current prompt ~4310.
    # Character count beats word count: punctuation + JSON sigils count.
    assert len(UPC_LOOKUP_SYSTEM_INSTRUCTION) >= 3000


def test_upc_lookup_system_instruction_has_all_nine_steps():
    last_idx = -1
    for i in range(1, 10):
        marker = f"Step {i}:"
        idx = UPC_LOOKUP_SYSTEM_INSTRUCTION.find(marker)
        assert idx != -1, f"missing {marker}"
        assert idx > last_idx, f"{marker} appears out of order"
        last_idx = idx


def test_upc_lookup_system_instruction_has_six_examples():
    examples = [
        "iPad Pro 13-inch M4",
        "KitchenAid Artisan 5-Quart",
        "Royal Canin Adult Indoor 7lb",
        "DeWalt 20V MAX Brushless Drill/Driver Kit",
        "Greenworks 80V 21-inch Self-Propelled",
        "iPhone 16 Pro Max 256GB",
    ]
    for example in examples:
        assert example in UPC_LOOKUP_SYSTEM_INSTRUCTION, f"missing example: {example}"


def test_upc_lookup_system_instruction_has_json_contract():
    for field in ('"device_name":', '"model":', '"reasoning":'):
        assert field in UPC_LOOKUP_SYSTEM_INSTRUCTION, f"missing JSON field: {field}"


def test_upc_lookup_system_instruction_no_electronics_only_qualifier():
    # Negative regression: confirm 3o-C actually stripped the electronics framing.
    forbidden = (
        "electronics-only",
        "electronics device",
        "electronics-focused",
        "electronics relevance",
    )
    for phrase in forbidden:
        assert phrase not in UPC_LOOKUP_SYSTEM_INSTRUCTION, (
            f"forbidden phrase resurfaced: {phrase}"
        )


def test_build_upc_retry_prompt_is_category_agnostic():
    retry = build_upc_retry_prompt("012345678905")
    assert "non-electronics sources" not in retry
    assert "grocery, household, apparel" not in retry
    assert "all retail categories" in retry
    assert "012345678905" in retry


def test_build_upc_lookup_prompt_unchanged():
    # Regression guard — the bare-UPC builder is byte-stable.
    expected = (
        "012345678905\n"
        "\n"
        "Return ONLY a JSON object with TWO fields:\n"
        '- "device_name": (string or null) — most fully specified product name\n'
        '- "model": (string or null) — shortest unambiguous identifier '
        "(generation, model number, capacity, color)\n"
        "\n"
        "Do not include reasoning or any other fields in the output. "
        'Only return {"device_name": "...", "model": "..."} '
        'or {"device_name": null, "model": null}.'
    )
    assert build_upc_lookup_prompt("012345678905") == expected
