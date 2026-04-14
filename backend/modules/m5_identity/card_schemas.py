"""Pydantic schemas for M5 Card Portfolio endpoints (Step 2e)."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# MARK: - Shared vocabularies
#
# Changing either tuple is a breaking change. Keep in sync with the seed
# lint tests in backend/tests/test_card_catalog_seed.py.

CARD_ISSUERS: tuple[str, ...] = (
    "chase",
    "amex",
    "capital_one",
    "citi",
    "discover",
    "bank_of_america",
    "wells_fargo",
    "us_bank",
)

REWARD_CURRENCIES: tuple[str, ...] = (
    "ultimate_rewards",
    "membership_rewards",
    "venture_miles",
    "thank_you_points",
    "cashback",
    "points",
)


# MARK: - Catalog


class CardRewardProgramResponse(BaseModel):
    """A single card in the static catalog, surfaced by GET /api/v1/cards/catalog."""

    id: UUID
    card_network: str
    card_issuer: str
    card_product: str
    card_display_name: str
    base_reward_rate: float
    reward_currency: str
    point_value_cents: float | None = None
    category_bonuses: list[dict] = Field(default_factory=list)
    has_shopping_portal: bool
    portal_url: str | None = None
    annual_fee: float
    # Flattened from category_bonuses[user_selected].allowed so iOS doesn't have
    # to decode the full JSONB. Null for cards without a user-selected tier.
    user_selected_allowed: list[str] | None = None

    model_config = ConfigDict(from_attributes=True, protected_namespaces=())


# MARK: - User Portfolio


class AddCardRequest(BaseModel):
    card_program_id: UUID
    nickname: str | None = None


class UserCardResponse(BaseModel):
    """A card in the user's portfolio, surfaced by GET /api/v1/cards/my-cards."""

    id: UUID
    card_program_id: UUID
    card_issuer: str
    card_product: str
    card_display_name: str
    nickname: str | None = None
    is_preferred: bool
    base_reward_rate: float
    reward_currency: str

    model_config = ConfigDict(from_attributes=True, protected_namespaces=())


class SetCategoriesRequest(BaseModel):
    """Set user-selected categories for a Cash+ / Customized Cash card."""

    categories: list[str]
    quarter: str  # "2026-Q2"


# MARK: - Recommendations


class CardRecommendation(BaseModel):
    """Best card at a single retailer for a single product.

    `reward_amount` is the conservative dollar value of the rewards earned at
    this retailer's lowest in-stock price:

        reward_amount = purchase_amount
                      * effective_rate
                      * point_value_cents / 100
    """

    retailer_id: str
    retailer_name: str
    user_card_id: UUID
    card_program_id: UUID
    card_display_name: str
    card_issuer: str
    reward_rate: float
    reward_amount: float
    reward_currency: str
    is_rotating_bonus: bool = False
    is_user_selected_bonus: bool = False
    activation_required: bool = False
    activation_url: str | None = None

    model_config = ConfigDict(protected_namespaces=())


class CardRecommendationsResponse(BaseModel):
    """Per-retailer best-card recommendations for a product.

    `user_has_cards=false` is the signal for the iOS "Add your cards" CTA.
    """

    recommendations: list[CardRecommendation]
    user_has_cards: bool
