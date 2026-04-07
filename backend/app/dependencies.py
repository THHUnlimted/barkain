import time
from collections.abc import AsyncGenerator

import redis.asyncio as aioredis
from clerk_backend_api import Clerk
from clerk_backend_api.security import AuthenticateRequestOptions
from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal


# MARK: - Database

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# MARK: - Redis

async def get_redis() -> AsyncGenerator[aioredis.Redis, None]:
    client = aioredis.from_url(settings.REDIS_URL)
    try:
        yield client
    finally:
        await client.aclose()


# MARK: - Auth

_clerk = Clerk(bearer_auth=settings.CLERK_SECRET_KEY) if settings.CLERK_SECRET_KEY else None


async def get_current_user(
    request: Request,
    authorization: str | None = Header(None),
) -> dict:
    """Extract and validate Clerk JWT. Raises 401 if invalid."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail={
                "error": {
                    "code": "UNAUTHORIZED",
                    "message": "Missing or invalid authorization header",
                    "details": {},
                }
            },
        )

    if _clerk is None:
        raise HTTPException(
            status_code=500,
            detail={
                "error": {
                    "code": "AUTH_NOT_CONFIGURED",
                    "message": "Clerk secret key not configured",
                    "details": {},
                }
            },
        )

    try:
        request_state = _clerk.authenticate_request(
            request,
            AuthenticateRequestOptions(),
        )
        if not request_state.is_signed_in:
            raise HTTPException(
                status_code=401,
                detail={
                    "error": {
                        "code": "INVALID_TOKEN",
                        "message": "Token validation failed",
                        "details": {},
                    }
                },
            )
        payload = request_state.payload or {}
        return {
            "user_id": payload.get("sub", ""),
            "email": payload.get("email"),
            "session_id": payload.get("sid"),
        }
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=401,
            detail={
                "error": {
                    "code": "INVALID_TOKEN",
                    "message": "Token validation failed",
                    "details": {},
                }
            },
        )


# MARK: - Rate Limiting

def get_rate_limiter(category: str = "general"):
    """Return a dependency that enforces rate limiting for the given category."""

    async def check_rate_limit(
        user: dict = Depends(get_current_user),
        redis_client: aioredis.Redis = Depends(get_redis),
    ) -> None:
        limits = {
            "general": settings.RATE_LIMIT_GENERAL,
            "write": settings.RATE_LIMIT_WRITE,
            "ai": settings.RATE_LIMIT_AI,
        }
        limit = limits.get(category, 60)
        key = f"rate:{user['user_id']}:{category}"
        now = time.time()
        window = 60  # 1 minute

        pipe = redis_client.pipeline()
        pipe.zremrangebyscore(key, 0, now - window)
        pipe.zadd(key, {str(now): now})
        pipe.zcard(key)
        pipe.expire(key, window)
        results = await pipe.execute()

        count = results[2]
        if count > limit:
            oldest = await redis_client.zrange(key, 0, 0, withscores=True)
            retry_after = int(window - (now - oldest[0][1])) if oldest else window
            retry_after = max(retry_after, 1)
            raise HTTPException(
                status_code=429,
                headers={"Retry-After": str(retry_after)},
                detail={
                    "error": {
                        "code": "RATE_LIMITED",
                        "message": f"Too many requests. Try again in {retry_after} seconds.",
                        "details": {"retry_after_seconds": retry_after},
                    }
                },
            )

    return check_rate_limit
