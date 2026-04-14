"""Lint tests for scripts/seed_card_catalog.py + seed_rotating_categories.py.

Pure-Python validation — no DB round-trip. Catches:
- vocabulary drift in card_issuer / reward_currency
- duplicate (card_issuer, card_product) tuples (violates seed unique index)
- malformed category_bonuses JSONB shape
- rotating_categories referencing cards not in the catalog
- Tier 1 coverage regression (the top-8 issuers from CARD_REWARDS.md)
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.m5_identity.card_schemas import (  # noqa: E402
    CARD_ISSUERS,
    REWARD_CURRENCIES,
)
from scripts.seed_card_catalog import CARDS  # noqa: E402
from scripts.seed_rotating_categories import ROTATING_CATEGORIES  # noqa: E402


# MARK: - Card catalog lint


def test_card_count_is_thirty():
    assert len(CARDS) == 30, f"expected 30 cards, got {len(CARDS)}"


def test_card_issuers_match_vocab():
    for card in CARDS:
        assert card["card_issuer"] in CARD_ISSUERS, (
            f"unknown issuer: {card['card_issuer']} on {card['card_product']}"
        )


def test_reward_currencies_match_vocab():
    for card in CARDS:
        assert card["reward_currency"] in REWARD_CURRENCIES, (
            f"unknown currency: {card['reward_currency']} on {card['card_product']}"
        )


def test_no_duplicate_card_tuples():
    seen: set[tuple[str, str]] = set()
    for card in CARDS:
        key = (card["card_issuer"], card["card_product"])
        assert key not in seen, f"duplicate card: {key}"
        seen.add(key)


def test_card_display_names_unique():
    names = [c["card_display_name"] for c in CARDS]
    assert len(names) == len(set(names)), "duplicate card_display_name"


def test_category_bonuses_valid_shape():
    for card in CARDS:
        bonuses = card["category_bonuses"]
        assert isinstance(bonuses, list), f"{card['card_product']}: bonuses not a list"
        # Must be JSONB-serializable
        json.dumps(bonuses)
        for bonus in bonuses:
            assert "category" in bonus, f"{card['card_product']}: bonus missing category"
            assert "rate" in bonus, f"{card['card_product']}: bonus missing rate"
            assert isinstance(bonus["rate"], (int, float))
            if bonus["category"] == "user_selected":
                assert "allowed" in bonus, (
                    f"{card['card_product']}: user_selected bonus missing allowed list"
                )
                assert isinstance(bonus["allowed"], list)
                assert len(bonus["allowed"]) > 0, (
                    f"{card['card_product']}: user_selected.allowed is empty"
                )


def test_all_eight_issuers_represented():
    """Regression: every Tier 1 issuer must have at least one seeded card."""
    seen = {c["card_issuer"] for c in CARDS}
    for issuer in CARD_ISSUERS:
        assert issuer in seen, f"Tier 1 issuer missing from seed: {issuer}"


def test_base_rates_positive():
    for card in CARDS:
        assert card["base_reward_rate"] > 0, f"{card['card_product']}: base rate 0"


def test_point_value_cents_present_for_points_currencies():
    """Points-currency cards must carry a conservative cpp for dollar conversion."""
    points_currencies = {"ultimate_rewards", "membership_rewards", "venture_miles",
                         "thank_you_points", "points"}
    for card in CARDS:
        if card["reward_currency"] in points_currencies:
            assert card["point_value_cents"] is not None, (
                f"{card['card_product']}: points card missing point_value_cents"
            )
            assert card["point_value_cents"] >= 1.0, (
                f"{card['card_product']}: cpp below conservative floor"
            )


# MARK: - Rotating categories lint


def test_rotating_references_valid_cards():
    catalog_keys = {(c["card_issuer"], c["card_product"]) for c in CARDS}
    for row in ROTATING_CATEGORIES:
        key = (row["card_issuer"], row["card_product"])
        assert key in catalog_keys, (
            f"rotating row references card not in catalog: {key}"
        )


def test_rotating_categories_nonempty():
    """No rotating row may be seeded with an empty categories array — such rows
    would never match any retailer at query time."""
    for row in ROTATING_CATEGORIES:
        assert row["categories"], (
            f"rotating row {row['card_product']} has empty categories"
        )


def test_rotating_q2_2026_dates():
    from datetime import date

    for row in ROTATING_CATEGORIES:
        if row["quarter"] == "2026-Q2":
            assert row["effective_from"] == date(2026, 4, 1)
            assert row["effective_until"] == date(2026, 6, 30)


def test_rotating_user_selected_cards_not_seeded():
    """Cash+ and Customized Cash resolve via user_category_selections, not
    rotating_categories. Seeding them here would be a design-intent regression."""
    excluded = {
        ("us_bank", "cash_plus"),
        ("bank_of_america", "customized_cash"),
        ("us_bank", "shopper_cash_rewards"),
    }
    for row in ROTATING_CATEGORIES:
        key = (row["card_issuer"], row["card_product"])
        assert key not in excluded, (
            f"{key} should not be in rotating_categories — user-selected only"
        )
