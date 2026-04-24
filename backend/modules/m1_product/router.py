"""M1 Product Resolution router — POST /api/v1/products/resolve."""

import logging

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_current_user, get_db, get_rate_limiter, get_redis
from app.errors import raise_http_error
from modules.m1_product.schemas import (
    ConfirmResolutionResponse,
    ProductResolveRequest,
    ProductResponse,
    ProductSearchRequest,
    ProductSearchResponse,
    ResolveFromSearchConfirmRequest,
    ResolveFromSearchRequest,
)
from modules.m1_product.search_service import ProductSearchService
from modules.m1_product.service import (
    ProductNotFoundError,
    ProductResolutionService,
    UPCNotFoundForDescriptionError,
)

logger = logging.getLogger("barkain.m1")

router = APIRouter(prefix="/api/v1/products", tags=["products"])


@router.post(
    "/resolve",
    response_model=ProductResponse,
    status_code=200,
    responses={
        404: {"description": "Product not found for given UPC"},
        422: {"description": "Invalid UPC format"},
    },
)
async def resolve_product(
    body: ProductResolveRequest,
    user: dict = Depends(get_current_user),
    _rate: None = Depends(get_rate_limiter("general")),
    db: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis = Depends(get_redis),
) -> ProductResponse:
    """Resolve a UPC barcode to a canonical product."""
    service = ProductResolutionService(db=db, redis=redis_client)
    try:
        product = await service.resolve(body.upc)
        return ProductResponse.model_validate(product)
    except ProductNotFoundError:
        raise_http_error(404, "PRODUCT_NOT_FOUND", f"No product found for UPC {body.upc}", {"upc": body.upc})


@router.post(
    "/search",
    response_model=ProductSearchResponse,
    status_code=200,
    responses={
        422: {"description": "Invalid query (length <3 or >200) or invalid max_results"},
        429: {"description": "Rate limit exceeded"},
    },
)
async def search_products(
    body: ProductSearchRequest,
    user: dict = Depends(get_current_user),
    _rate: None = Depends(get_rate_limiter("general")),
    db: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis = Depends(get_redis),
) -> ProductSearchResponse:
    """Text search for products. Returns a ranked list.

    DB fuzzy match (pg_trgm) first; Gemini fills in when DB results are
    sparse or low-confidence. Tapping a result on the iOS side triggers the
    standard ``/products/resolve`` path to create/reuse a Product row —
    search itself never persists speculative Gemini results.
    """
    service = ProductSearchService(db=db, redis=redis_client)
    return await service.search(
        body.query, body.max_results, force_gemini=body.force_gemini
    )


@router.post(
    "/resolve-from-search",
    response_model=ProductResponse,
    status_code=200,
    responses={
        404: {"description": "UPC could not be derived from the description, or no product found"},
        409: {"description": "Low-confidence result — client must confirm via /resolve-from-search/confirm"},
        422: {"description": "Invalid device_name / brand / model payload"},
        429: {"description": "Rate limit exceeded"},
    },
)
async def resolve_from_search(
    body: ResolveFromSearchRequest,
    user: dict = Depends(get_current_user),
    _rate: None = Depends(get_rate_limiter("general")),
    db: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis = Depends(get_redis),
) -> ProductResponse:
    """Resolve a Gemini-sourced search result (no UPC) into a persisted Product.

    Runs a targeted Gemini device→UPC lookup, then delegates to the
    standard ``/resolve`` path for cross-validation and persistence. This
    is the tap-time fallback for search results where ``primary_upc`` was
    null at search time (common for older / discontinued SKUs).

    demo-prep-1 Item 3: when the client forwards a ``confidence`` from
    the originating search result and that value is below
    ``settings.LOW_CONFIDENCE_THRESHOLD``, the endpoint short-circuits
    with 409 RESOLUTION_NEEDS_CONFIRMATION. The iOS client surfaces a
    confirmation sheet and re-calls ``/resolve-from-search/confirm`` with
    the user's choice. When ``confidence`` is omitted (None), the gate is
    skipped and the endpoint behaves as it did pre-demo-prep-1.
    """
    if (
        body.confidence is not None
        and body.confidence < settings.LOW_CONFIDENCE_THRESHOLD
    ):
        logger.info(
            "resolve-from-search: 409 needs-confirmation device=%r conf=%.2f threshold=%.2f",
            body.device_name,
            body.confidence,
            settings.LOW_CONFIDENCE_THRESHOLD,
        )
        raise_http_error(
            409,
            "RESOLUTION_NEEDS_CONFIRMATION",
            f"Low-confidence match ({body.confidence:.2f}) — user confirmation required",
            {
                "device_name": body.device_name,
                "brand": body.brand,
                "model": body.model,
                "confidence": body.confidence,
                "threshold": settings.LOW_CONFIDENCE_THRESHOLD,
            },
        )

    service = ProductResolutionService(db=db, redis=redis_client)
    try:
        product = await service.resolve_from_search(
            device_name=body.device_name,
            brand=body.brand,
            model=body.model,
        )
        return ProductResponse.model_validate(product)
    except UPCNotFoundForDescriptionError:
        raise_http_error(
            404,
            "UPC_NOT_FOUND_FOR_PRODUCT",
            f"Could not find a barcode for {body.device_name!r}",
            {"device_name": body.device_name},
        )
    except ProductNotFoundError as exc:
        raise_http_error(
            404,
            "PRODUCT_NOT_FOUND",
            f"No product found for derived UPC {exc.upc}",
            {"device_name": body.device_name, "derived_upc": exc.upc},
        )


@router.post(
    "/resolve-from-search/confirm",
    response_model=ConfirmResolutionResponse,
    status_code=200,
    responses={
        404: {"description": "UPC could not be derived from the description, or no product found"},
        422: {"description": "Invalid payload"},
        429: {"description": "Rate limit exceeded"},
    },
)
async def resolve_from_search_confirm(
    body: ResolveFromSearchConfirmRequest,
    user: dict = Depends(get_current_user),
    _rate: None = Depends(get_rate_limiter("general")),
    db: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis = Depends(get_redis),
) -> ConfirmResolutionResponse:
    """demo-prep-1 Item 3: the companion endpoint to the 409 gate on
    ``/resolve-from-search``. The iOS confirmation sheet calls this with
    the user's choice.

    On ``user_confirmed=true`` the backend runs the same resolution path
    as ``/resolve-from-search`` (bypassing the confidence gate by
    construction — this endpoint has no gate) and marks the resulting
    product's ``source_raw.user_confirmed`` flag so future scans skip
    the dialog. On ``user_confirmed=false`` the backend logs the
    rejection (telemetry for tuning the threshold) and returns an empty
    200 so the client can re-open search cleanly.
    """
    if not body.user_confirmed:
        logger.info(
            "resolve-from-search/confirm: rejected device=%r query=%r",
            body.device_name,
            body.query,
        )
        return ConfirmResolutionResponse(product=None, logged=True)

    logger.info(
        "resolve-from-search/confirm: confirmed device=%r query=%r",
        body.device_name,
        body.query,
    )
    service = ProductResolutionService(db=db, redis=redis_client)
    try:
        product = await service.resolve_from_search_confirmed(
            device_name=body.device_name,
            brand=body.brand,
            model=body.model,
        )
        return ConfirmResolutionResponse(
            product=ProductResponse.model_validate(product),
            logged=True,
        )
    except UPCNotFoundForDescriptionError:
        raise_http_error(
            404,
            "UPC_NOT_FOUND_FOR_PRODUCT",
            f"Could not find a barcode for {body.device_name!r}",
            {"device_name": body.device_name},
        )
    except ProductNotFoundError as exc:
        raise_http_error(
            404,
            "PRODUCT_NOT_FOUND",
            f"No product found for derived UPC {exc.upc}",
            {"device_name": body.device_name, "derived_upc": exc.upc},
        )
