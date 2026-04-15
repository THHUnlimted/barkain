import logging
import time
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import redis.asyncio as aioredis
from clerk_backend_api import Clerk
from clerk_backend_api.security import AuthenticateRequestOptions
from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal

_rate_limit_log = logging.getLogger("barkain.rate_limit")


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
    # Demo mode: bypass auth for local testing (env var DEMO_MODE=1).
    # Read at call-time via settings so tests can monkeypatch.setattr it
    # without worrying about module-import ordering.
    if settings.DEMO_MODE:
        return {"user_id": "demo_user", "email": "demo@barkain.local", "session_id": "demo"}

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


# Redis cache for per-user tier resolution. BillingService.process_webhook
# busts `tier:{user_id}` on every state change so upgrades/downgrades
# propagate within the TTL. Missing user row → free (not an error).
_TIER_CACHE_TTL_SECONDS = 60


async def _resolve_user_tier(
    user_id: str,
    redis_client: aioredis.Redis,
    db: AsyncSession,
) -> str:
    """Resolve the effective tier for `user_id`.

    Read path: Redis cache first (60s TTL), then a single SELECT from the
    users table on miss. Missing row → 'free'. Expired pro → 'free'. The
    resolved value is cached even on miss to avoid thundering-herd on hot
    paths like the SSE stream endpoint.

    Falls open to 'free' on any Redis/DB error so the rate limiter never
    hard-fails an authenticated request.
    """
    cache_key = f"tier:{user_id}"
    try:
        cached = await redis_client.get(cache_key)
        if cached is not None:
            value = cached.decode() if isinstance(cached, bytes) else str(cached)
            if value in ("free", "pro"):
                return value
    except Exception as e:  # noqa: BLE001
        _rate_limit_log.warning("Tier cache read failed (falling open): %s", e)

    resolved = "free"
    try:
        result = await db.execute(
            text(
                "SELECT subscription_tier, subscription_expires_at "
                "FROM users WHERE id = :user_id"
            ),
            {"user_id": user_id},
        )
        row = result.first()
        if row is not None:
            tier = row[0] or "free"
            expires_at = row[1]
            if tier == "pro":
                if expires_at is None:
                    resolved = "pro"
                else:
                    if expires_at.tzinfo is None:
                        expires_at = expires_at.replace(tzinfo=UTC)
                    if expires_at > datetime.now(UTC):
                        resolved = "pro"
    except Exception as e:  # noqa: BLE001
        _rate_limit_log.warning("Tier DB lookup failed (falling open): %s", e)
        return "free"

    try:
        await redis_client.setex(cache_key, _TIER_CACHE_TTL_SECONDS, resolved)
    except Exception as e:  # noqa: BLE001
        _rate_limit_log.warning("Tier cache write failed (non-fatal): %s", e)

    return resolved


def get_rate_limiter(category: str = "general"):
    """Return a dependency that enforces rate limiting for the given category.

    Free users get the base thresholds from `settings.RATE_LIMIT_*`. Pro users
    get those thresholds multiplied by `settings.RATE_LIMIT_PRO_MULTIPLIER`.
    Tier is resolved via a 60s Redis cache backed by a single DB SELECT on
    miss — the DB query is only hit when a user's rate window starts fresh.
    """

    async def check_rate_limit(
        user: dict = Depends(get_current_user),
        redis_client: aioredis.Redis = Depends(get_redis),
        db: AsyncSession = Depends(get_db),
    ) -> None:
        limits = {
            "general": settings.RATE_LIMIT_GENERAL,
            "write": settings.RATE_LIMIT_WRITE,
            "ai": settings.RATE_LIMIT_AI,
        }
        base_limit = limits.get(category, 60)
        tier = await _resolve_user_tier(user["user_id"], redis_client, db)
        limit = (
            base_limit * settings.RATE_LIMIT_PRO_MULTIPLIER
            if tier == "pro"
            else base_limit
        )

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
