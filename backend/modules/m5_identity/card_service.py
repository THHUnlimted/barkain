"""CardService — card portfolio CRUD + zero-LLM reward matching (Step 2e)."""

import logging
from datetime import date
from decimal import Decimal
from typing import Iterable
from uuid import UUID

from sqlalchemy import and_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core_models import Retailer
from modules.m2_prices.models import Price
from modules.m5_identity.card_schemas import (
    AddCardRequest,
    CardRecommendation,
    CardRecommendationsResponse,
    CardRewardProgramResponse,
    UserCardResponse,
)
from modules.m5_identity.models import (
    CardRewardProgram,
    RotatingCategory,
    UserCard,
    UserCategorySelection,
)

logger = logging.getLogger("barkain.m5_cards")


# MARK: - Retailer → category tag map
#
# Matching-time tag set for each retailer. A card's category bonus fires when
# any of its `category` tags intersect this set. Unknown retailers silently
# fall through to base rate. Phase 3 may move this to a DB column.

_RETAILER_CATEGORY_TAGS: dict[str, frozenset[str]] = {
    "amazon": frozenset({"amazon", "online_shopping"}),
    "best_buy": frozenset({"best_buy", "electronics_stores", "online_shopping"}),
    "walmart": frozenset({"walmart", "wholesale_clubs", "online_shopping"}),
    "target": frozenset({"target", "online_shopping", "department_stores"}),
    "home_depot": frozenset(
        {"home_depot", "home_improvement", "online_shopping"}
    ),
    "lowes": frozenset({"lowes", "home_improvement", "online_shopping"}),
    "ebay_new": frozenset({"ebay", "online_shopping"}),
    "ebay_used": frozenset({"ebay", "online_shopping"}),
    "sams_club": frozenset({"sams_club", "wholesale_clubs", "online_shopping"}),
    "backmarket": frozenset({"online_shopping", "electronics_stores"}),
    "fb_marketplace": frozenset({"online_shopping"}),
    "samsung_direct": frozenset(
        {"electronics", "electronics_stores", "online_shopping"}
    ),
    "apple_direct": frozenset(
        {"apple", "electronics", "electronics_stores", "online_shopping"}
    ),
    "hp_direct": frozenset(
        {"electronics", "electronics_stores", "online_shopping"}
    ),
    "dell_direct": frozenset(
        {"electronics", "electronics_stores", "online_shopping"}
    ),
    "lenovo_direct": frozenset(
        {"electronics", "electronics_stores", "online_shopping"}
    ),
    "microsoft_direct": frozenset(
        {"electronics", "electronics_stores", "online_shopping"}
    ),
    "sony_direct": frozenset(
        {"electronics", "electronics_stores", "online_shopping"}
    ),
    "lg_direct": frozenset(
        {"electronics", "electronics_stores", "online_shopping"}
    ),
}


# MARK: - Quarter helpers


def _quarter_to_dates(quarter: str) -> tuple[date, date]:
    """'2026-Q2' → (date(2026, 4, 1), date(2026, 6, 30))."""
    try:
        year_s, q_s = quarter.split("-")
        year = int(year_s)
        q = int(q_s.lstrip("Qq"))
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"invalid quarter: {quarter!r}") from exc
    if q < 1 or q > 4:
        raise ValueError(f"invalid quarter: {quarter!r}")
    starts = {1: (1, 1, 3, 31), 2: (4, 1, 6, 30), 3: (7, 1, 9, 30), 4: (10, 1, 12, 31)}
    sm, sd, em, ed = starts[q]
    return date(year, sm, sd), date(year, em, ed)


# MARK: - Service


class CardService:
    """Card portfolio CRUD and zero-LLM reward matching via pure SQL + in-memory math."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # MARK: - Catalog

    async def get_catalog(self) -> list[CardRewardProgramResponse]:
        """All active cards, ordered for the picker UI (issuer → display name)."""
        result = await self.db.execute(
            select(CardRewardProgram)
            .where(CardRewardProgram.is_active.is_(True))
            .order_by(CardRewardProgram.card_issuer, CardRewardProgram.card_display_name)
        )
        rows = result.scalars().all()
        return [self._catalog_dto(c) for c in rows]

    # MARK: - User portfolio

    async def get_user_cards(self, user_id: str) -> list[UserCardResponse]:
        """Active cards in the user's portfolio, ordered by preferred first, then added_at."""
        result = await self.db.execute(
            select(UserCard, CardRewardProgram)
            .join(CardRewardProgram, UserCard.card_program_id == CardRewardProgram.id)
            .where(
                and_(UserCard.user_id == user_id, UserCard.is_active.is_(True))
            )
            .order_by(UserCard.is_preferred.desc(), UserCard.added_at)
        )
        return [self._user_card_dto(uc, p) for uc, p in result.all()]

    async def add_card(
        self, user_id: str, request: AddCardRequest
    ) -> UserCardResponse:
        """Upsert a card into the user's portfolio.

        Idempotent: adding a card that already exists (including one previously
        soft-deleted) re-activates it and replaces the nickname. Upserts the
        `users` row first so Clerk-stub and demo-mode callers never trip the FK.
        """
        await self.db.execute(
            text("INSERT INTO users (id) VALUES (:id) ON CONFLICT (id) DO NOTHING"),
            {"id": user_id},
        )

        program = await self.db.get(CardRewardProgram, request.card_program_id)
        if program is None or not program.is_active:
            raise ValueError(f"unknown card_program_id: {request.card_program_id}")

        existing = (
            await self.db.execute(
                select(UserCard).where(
                    and_(
                        UserCard.user_id == user_id,
                        UserCard.card_program_id == request.card_program_id,
                    )
                )
            )
        ).scalar_one_or_none()

        if existing is None:
            card = UserCard(
                user_id=user_id,
                card_program_id=request.card_program_id,
                nickname=request.nickname,
                is_active=True,
            )
            self.db.add(card)
            await self.db.flush()
        else:
            existing.is_active = True
            existing.nickname = request.nickname
            await self.db.flush()
            card = existing

        return self._user_card_dto(card, program)

    async def remove_card(self, user_id: str, user_card_id: UUID) -> None:
        """Soft-delete. Idempotent — removing a missing card is a no-op."""
        await self.db.execute(
            update(UserCard)
            .where(
                and_(UserCard.id == user_card_id, UserCard.user_id == user_id)
            )
            .values(is_active=False, is_preferred=False)
        )

    async def set_preferred(
        self, user_id: str, user_card_id: UUID
    ) -> UserCardResponse:
        """Set one card as preferred, unset all others. Returns the preferred card."""
        # Confirm the target card exists and belongs to the user.
        target = (
            await self.db.execute(
                select(UserCard, CardRewardProgram)
                .join(
                    CardRewardProgram,
                    UserCard.card_program_id == CardRewardProgram.id,
                )
                .where(
                    and_(
                        UserCard.id == user_card_id,
                        UserCard.user_id == user_id,
                        UserCard.is_active.is_(True),
                    )
                )
            )
        ).first()
        if target is None:
            raise ValueError(f"user card not found: {user_card_id}")
        user_card, program = target

        await self.db.execute(
            update(UserCard)
            .where(UserCard.user_id == user_id)
            .values(is_preferred=False)
        )
        await self.db.execute(
            update(UserCard)
            .where(UserCard.id == user_card_id)
            .values(is_preferred=True)
        )
        await self.db.flush()
        user_card.is_preferred = True
        return self._user_card_dto(user_card, program)

    async def set_categories(
        self,
        user_id: str,
        user_card_id: UUID,
        categories: list[str],
        quarter: str,
    ) -> UserCategorySelection:
        """Upsert user-selected categories for this card + quarter.

        Validates the picks against the card's `user_selected.allowed` list.
        """
        target = (
            await self.db.execute(
                select(UserCard, CardRewardProgram)
                .join(
                    CardRewardProgram,
                    UserCard.card_program_id == CardRewardProgram.id,
                )
                .where(
                    and_(
                        UserCard.id == user_card_id,
                        UserCard.user_id == user_id,
                        UserCard.is_active.is_(True),
                    )
                )
            )
        ).first()
        if target is None:
            raise ValueError(f"user card not found: {user_card_id}")
        _, program = target

        allowed = _user_selected_allowed(program.category_bonuses)
        if allowed is None:
            raise ValueError(
                f"card does not support user-selected categories: {program.card_display_name}"
            )
        unknown = [c for c in categories if c not in allowed]
        if unknown:
            raise ValueError(f"unknown categories for this card: {unknown}")

        effective_from, effective_until = _quarter_to_dates(quarter)

        existing = (
            await self.db.execute(
                select(UserCategorySelection).where(
                    and_(
                        UserCategorySelection.user_id == user_id,
                        UserCategorySelection.card_program_id == program.id,
                        UserCategorySelection.effective_from == effective_from,
                    )
                )
            )
        ).scalar_one_or_none()

        if existing is None:
            selection = UserCategorySelection(
                user_id=user_id,
                card_program_id=program.id,
                selected_categories=categories,
                effective_from=effective_from,
                effective_until=effective_until,
            )
            self.db.add(selection)
        else:
            existing.selected_categories = categories
            existing.effective_until = effective_until
            selection = existing

        await self.db.flush()
        return selection

    # MARK: - Matching (zero-LLM, <50ms target)

    async def get_best_cards_for_product(
        self, user_id: str, product_id: UUID
    ) -> CardRecommendationsResponse:
        """Per-retailer best-card recommendations for a product.

        Loads user cards, rotating categories, user_category_selections, and
        retailer prices in 4 single queries then iterates in memory. The whole
        path stays under 50ms even with 30 cards seeded.
        """
        user_rows = (
            await self.db.execute(
                select(UserCard, CardRewardProgram)
                .join(
                    CardRewardProgram,
                    UserCard.card_program_id == CardRewardProgram.id,
                )
                .where(
                    and_(
                        UserCard.user_id == user_id,
                        UserCard.is_active.is_(True),
                        CardRewardProgram.is_active.is_(True),
                    )
                )
            )
        ).all()

        if not user_rows:
            return CardRecommendationsResponse(
                recommendations=[], user_has_cards=False
            )

        card_program_ids = [program.id for _, program in user_rows]
        today = date.today()

        rotating_rows = (
            await self.db.execute(
                select(RotatingCategory).where(
                    and_(
                        RotatingCategory.card_program_id.in_(card_program_ids),
                        RotatingCategory.effective_from <= today,
                        RotatingCategory.effective_until >= today,
                    )
                )
            )
        ).scalars().all()
        rotating_by_card: dict[UUID, list[RotatingCategory]] = {}
        for r in rotating_rows:
            rotating_by_card.setdefault(r.card_program_id, []).append(r)

        selection_rows = (
            await self.db.execute(
                select(UserCategorySelection).where(
                    and_(
                        UserCategorySelection.user_id == user_id,
                        UserCategorySelection.card_program_id.in_(card_program_ids),
                        UserCategorySelection.effective_from <= today,
                        UserCategorySelection.effective_until >= today,
                    )
                )
            )
        ).scalars().all()
        selections_by_card: dict[UUID, list[UserCategorySelection]] = {}
        for s in selection_rows:
            selections_by_card.setdefault(s.card_program_id, []).append(s)

        retailer_price_rows = (
            await self.db.execute(
                select(Price.retailer_id, Price.price, Retailer.display_name)
                .join(Retailer, Price.retailer_id == Retailer.id)
                .where(
                    and_(
                        Price.product_id == product_id,
                        Price.is_available.is_(True),
                        Price.condition == "new",
                    )
                )
                .order_by(Price.retailer_id)
            )
        ).all()

        # The Price table has UNIQUE(product_id, retailer_id, condition) (see
        # m2_prices/models.py), so each retailer appears at most once for a
        # given product+condition. The previous "collapse to lowest" loop had
        # a dead `if retailer_id not in retailer_lowest` branch — removed in 2i-b.
        retailer_lowest: dict[str, tuple[float, str]] = {
            retailer_id: (float(price), display_name)
            for retailer_id, price, display_name in retailer_price_rows
        }

        recommendations: list[CardRecommendation] = []
        for retailer_id, (purchase_amount, retailer_name) in retailer_lowest.items():
            rec = self._best_card_for_retailer(
                user_rows=user_rows,
                rotating_by_card=rotating_by_card,
                selections_by_card=selections_by_card,
                retailer_id=retailer_id,
                retailer_name=retailer_name,
                purchase_amount=purchase_amount,
            )
            if rec is not None:
                recommendations.append(rec)

        return CardRecommendationsResponse(
            recommendations=recommendations, user_has_cards=True
        )

    # MARK: - Core matching helper

    def _best_card_for_retailer(
        self,
        *,
        user_rows: Iterable[tuple[UserCard, CardRewardProgram]],
        rotating_by_card: dict[UUID, list[RotatingCategory]],
        selections_by_card: dict[UUID, list[UserCategorySelection]],
        retailer_id: str,
        retailer_name: str,
        purchase_amount: float,
    ) -> CardRecommendation | None:
        """Return the highest-dollar-value card at this retailer, or None."""
        retailer_tags = _RETAILER_CATEGORY_TAGS.get(retailer_id, frozenset())
        best: CardRecommendation | None = None
        best_dollars = -1.0

        for user_card, program in user_rows:
            point_value = float(program.point_value_cents or 1.0)
            base_rate = float(program.base_reward_rate)

            winner_rate = base_rate
            winner_is_rotating = False
            winner_is_user_selected = False
            winner_activation_required = False
            winner_activation_url: str | None = None

            def _promote(
                rate: float,
                *,
                rotating: bool = False,
                user_selected: bool = False,
                activation_required: bool = False,
                activation_url: str | None = None,
            ) -> None:
                nonlocal winner_rate, winner_is_rotating, winner_is_user_selected
                nonlocal winner_activation_required, winner_activation_url
                if rate > winner_rate:
                    winner_rate = rate
                    winner_is_rotating = rotating
                    winner_is_user_selected = user_selected
                    winner_activation_required = activation_required
                    winner_activation_url = activation_url

            # 1. Rotating issuer-defined bonuses.
            for rotating in rotating_by_card.get(program.id, []):
                if _tags_intersect(rotating.categories, retailer_tags):
                    _promote(
                        float(rotating.bonus_rate),
                        rotating=True,
                        activation_required=bool(rotating.activation_required),
                        activation_url=rotating.activation_url,
                    )

            # 2. User-selected bonuses (Cash+, Customized Cash, etc.).
            user_selected_bonus = _find_user_selected_bonus(program.category_bonuses)
            if user_selected_bonus is not None:
                for selection in selections_by_card.get(program.id, []):
                    if _tags_intersect(selection.selected_categories, retailer_tags):
                        _promote(
                            float(user_selected_bonus.get("rate", 0.0)),
                            user_selected=True,
                        )
                        break

            # 3. Static card-level category bonuses.
            for bonus in program.category_bonuses or []:
                category = bonus.get("category")
                if category and category != "user_selected" and category in retailer_tags:
                    _promote(float(bonus.get("rate", 0.0)))

            dollars = purchase_amount * winner_rate * point_value / 100.0
            if dollars > best_dollars:
                best_dollars = dollars
                best = CardRecommendation(
                    retailer_id=retailer_id,
                    retailer_name=retailer_name,
                    user_card_id=user_card.id,
                    card_program_id=program.id,
                    card_display_name=program.card_display_name,
                    card_issuer=program.card_issuer,
                    reward_rate=round(winner_rate, 2),
                    reward_amount=round(dollars, 2),
                    reward_currency=program.reward_currency,
                    is_rotating_bonus=winner_is_rotating,
                    is_user_selected_bonus=winner_is_user_selected,
                    activation_required=winner_activation_required,
                    activation_url=winner_activation_url,
                )
        return best

    # MARK: - DTO helpers

    def _catalog_dto(self, program: CardRewardProgram) -> CardRewardProgramResponse:
        allowed = _user_selected_allowed(program.category_bonuses)
        bonuses = list(program.category_bonuses or [])
        return CardRewardProgramResponse(
            id=program.id,
            card_network=program.card_network,
            card_issuer=program.card_issuer,
            card_product=program.card_product,
            card_display_name=program.card_display_name,
            base_reward_rate=float(program.base_reward_rate),
            reward_currency=program.reward_currency,
            point_value_cents=(
                float(program.point_value_cents)
                if program.point_value_cents is not None
                else None
            ),
            category_bonuses=bonuses,
            has_shopping_portal=bool(program.has_shopping_portal),
            portal_url=program.portal_url,
            annual_fee=float(program.annual_fee or Decimal(0)),
            user_selected_allowed=allowed,
        )

    def _user_card_dto(
        self, user_card: UserCard, program: CardRewardProgram
    ) -> UserCardResponse:
        return UserCardResponse(
            id=user_card.id,
            card_program_id=program.id,
            card_issuer=program.card_issuer,
            card_product=program.card_product,
            card_display_name=program.card_display_name,
            nickname=user_card.nickname,
            is_preferred=bool(user_card.is_preferred),
            base_reward_rate=float(program.base_reward_rate),
            reward_currency=program.reward_currency,
        )


# MARK: - module-local helpers


def _tags_intersect(card_categories: list[str], retailer_tags: frozenset[str]) -> bool:
    if not retailer_tags:
        return False
    return any(c in retailer_tags for c in (card_categories or []))


def _user_selected_allowed(category_bonuses: list[dict] | None) -> list[str] | None:
    """Extract the `allowed` list from a card's user_selected bonus, if any."""
    for bonus in category_bonuses or []:
        if bonus.get("category") == "user_selected":
            allowed = bonus.get("allowed")
            if isinstance(allowed, list):
                return list(allowed)
            return []
    return None


def _find_user_selected_bonus(category_bonuses: list[dict] | None) -> dict | None:
    for bonus in category_bonuses or []:
        if bonus.get("category") == "user_selected":
            return bonus
    return None
