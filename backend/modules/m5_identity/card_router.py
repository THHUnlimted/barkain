"""M5 Card Portfolio router — catalog + CRUD + per-product recommendations (Step 2e)."""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db, get_rate_limiter
from app.errors import raise_http_error
from modules.m5_identity.card_schemas import (
    AddCardRequest,
    CardRecommendationsResponse,
    CardRewardProgramResponse,
    SetCategoriesRequest,
    UserCardResponse,
)
from modules.m5_identity.card_service import CardService

logger = logging.getLogger("barkain.m5_cards")

router = APIRouter(prefix="/api/v1/cards", tags=["cards"])


@router.get("/catalog", response_model=list[CardRewardProgramResponse])
async def get_catalog(
    _user: dict = Depends(get_current_user),
    _rate: None = Depends(get_rate_limiter("general")),
    db: AsyncSession = Depends(get_db),
) -> list[CardRewardProgramResponse]:
    """All active cards in the picker catalog."""
    return await CardService(db).get_catalog()


@router.get("/my-cards", response_model=list[UserCardResponse])
async def get_user_cards(
    user: dict = Depends(get_current_user),
    _rate: None = Depends(get_rate_limiter("general")),
    db: AsyncSession = Depends(get_db),
) -> list[UserCardResponse]:
    """Current user's card portfolio."""
    return await CardService(db).get_user_cards(user["user_id"])


@router.post("/my-cards", response_model=UserCardResponse, status_code=201)
async def add_card(
    body: AddCardRequest,
    user: dict = Depends(get_current_user),
    _rate: None = Depends(get_rate_limiter("write")),
    db: AsyncSession = Depends(get_db),
) -> UserCardResponse:
    """Add a card to the user's portfolio. Idempotent (re-activates soft-deleted cards)."""
    try:
        return await CardService(db).add_card(user["user_id"], body)
    except ValueError as exc:
        raise_http_error(
            404,
            "CARD_NOT_FOUND",
            str(exc),
            {"card_program_id": str(body.card_program_id)},
        )


@router.delete("/my-cards/{user_card_id}", status_code=204)
async def remove_card(
    user_card_id: UUID,
    user: dict = Depends(get_current_user),
    _rate: None = Depends(get_rate_limiter("write")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Soft-delete a card from the user's portfolio."""
    await CardService(db).remove_card(user["user_id"], user_card_id)
    return Response(status_code=204)


@router.put("/my-cards/{user_card_id}/preferred", response_model=UserCardResponse)
async def set_preferred(
    user_card_id: UUID,
    user: dict = Depends(get_current_user),
    _rate: None = Depends(get_rate_limiter("write")),
    db: AsyncSession = Depends(get_db),
) -> UserCardResponse:
    """Mark one card as preferred, unset all others."""
    try:
        return await CardService(db).set_preferred(user["user_id"], user_card_id)
    except ValueError as exc:
        raise_http_error(
            404,
            "USER_CARD_NOT_FOUND",
            str(exc),
            {"user_card_id": str(user_card_id)},
        )


@router.post("/my-cards/{user_card_id}/categories", status_code=200)
async def set_categories(
    user_card_id: UUID,
    body: SetCategoriesRequest,
    user: dict = Depends(get_current_user),
    _rate: None = Depends(get_rate_limiter("write")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Set the user-selected categories for a Cash+ / Customized Cash card."""
    try:
        await CardService(db).set_categories(
            user["user_id"], user_card_id, body.categories, body.quarter
        )
    except ValueError as exc:
        code = (
            "USER_CARD_NOT_FOUND"
            if "not found" in str(exc)
            else "INVALID_CATEGORY_SELECTION"
        )
        status = 404 if code == "USER_CARD_NOT_FOUND" else 400
        raise_http_error(status, code, str(exc), {"user_card_id": str(user_card_id)})
    return {"ok": True}


@router.get("/recommendations", response_model=CardRecommendationsResponse)
async def get_recommendations(
    product_id: UUID,
    user: dict = Depends(get_current_user),
    _rate: None = Depends(get_rate_limiter("general")),
    db: AsyncSession = Depends(get_db),
) -> CardRecommendationsResponse:
    """Best card per retailer for a product, given the user's portfolio.

    Returns `user_has_cards: false` with an empty list if the user has no
    active cards — the iOS client uses that signal to surface the "Add Cards"
    CTA.
    """
    return await CardService(db).get_best_cards_for_product(
        user["user_id"], product_id
    )
