"""City/state → Facebook Marketplace numeric location ID resolver.

## Why this exists

Facebook Marketplace search URLs take a numeric Page ID, not a slug:

    https://www.facebook.com/marketplace/112111905481230/search?query=sofa&radius_in_km=5

The slug form (``/marketplace/brooklyn/``) silently redirects to a
generic category page when the slug isn't in FB's canonical list. The
proxy IP's geo then decides which metro's listings you see — which is
why NY-slugged requests through our CA-based Decodo exits served SF
listings. Numeric IDs are stable forever and unambiguous; once we have
one, we keep it.

FB itself returns HTTP 400 to unauthenticated clients on
``/marketplace/<slug>/``, so we don't ask FB. We ask public search
engines: "facebook marketplace <city> <state>" reliably returns the
canonical ``/marketplace/<numeric_id>/`` URL in the first organic
result. Startpage handles ~12 req before throttling (recovers with 2s
sleep); DDG 8 req before lockout (~10 min); Brave 5 req before 429.
We prefer Startpage, fall back on throttle.

## Call-site flow

1. L1 Redis (``fbmkt:<country>:<state>:<normalized-city>``, 24h TTL).
2. L2 Postgres ``fb_marketplace_locations``.
3. L3 live resolver — singleflight-locked per key so 500 concurrent
   misses on the same cold city collapse to one search-engine hit + 499
   pub/sub waiters.

Tombstoning matters: a place like Toad Suck, AR that isn't on FB
shouldn't re-trigger a 3-engine search every time a user types it. We
persist ``(location_id=NULL, source='unresolved')`` and cache that
state for 1 hour; the weekly verifier re-checks a sample.

Throttled ≠ unresolved: when all engines are rate-limited we write a
5-minute Redis bar (``__T__``) and skip Postgres entirely — the next
request retries against a fresher token budget.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import unicodedata
from dataclasses import dataclass
from typing import Callable, Optional
from urllib.parse import quote_plus

import httpx
import redis.asyncio as aioredis
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, settings
from modules.m2_prices.fb_location_models import FbMarketplaceLocation

logger = logging.getLogger("barkain.m2.fb_location_resolver")


# MARK: - Public types


@dataclass(frozen=True)
class ResolvedLocation:
    """Result of a resolve() call."""

    # None when the resolver couldn't find an ID. Distinguish ``source``:
    #  - ``unresolved``  → permanent tombstone (persist + 1h Redis bar)
    #  - ``throttled``   → transient, all engines throttled (5min Redis bar)
    #  - ``cache``       → came from L1 Redis or L2 Postgres hit
    #  - ``startpage/ddg/brave/seed/user`` → live resolve or seed
    location_id: int | None
    canonical_name: str | None
    source: str
    verified: bool


# MARK: - Normalization


# Tokens we collapse so "St. John's" / "Saint Johns" / "ST JOHN'S" all
# map to the same cache key.
_ABBREVIATIONS: dict[str, str] = {
    "st": "saint",
    "ste": "sainte",
    "mt": "mount",
    "mtn": "mountain",
    "ft": "fort",
}

# Settlement-type suffixes that don't change the referent. FB canonical
# names never include these, so dropping them avoids cache misses.
_DROP_SUFFIXES: set[str] = {
    "city",
    "town",
    "village",
    "borough",
    "township",
    "twp",
}


def _normalize_city(city: str) -> str:
    """Lowercase, ASCII-fold, strip punctuation, expand abbrevs, drop suffixes.

    ``"St. Louis"`` → ``"saint louis"``
    ``"São Paulo"`` → ``"sao paulo"``
    ``"New York City"`` → ``"new york"``
    """
    city = unicodedata.normalize("NFKD", city).encode("ascii", "ignore").decode()
    city = re.sub(r"[^A-Za-z0-9 ]+", " ", city.lower())
    tokens = [t for t in city.split() if t]
    tokens = [_ABBREVIATIONS.get(t, t) for t in tokens]
    tokens = [t for t in tokens if t not in _DROP_SUFFIXES]
    return " ".join(tokens).strip()


def _redis_key(country: str, state_code: str, city_normalized: str) -> str:
    return f"fbmkt:{country.lower()}:{state_code.lower()}:{city_normalized}"


# MARK: - Redis token bucket (GCRA-shaped)


# Generic Cell Rate Algorithm. One key per engine holds the theoretical
# arrival time (TAT) in ms-since-epoch. On acquire:
#   new_tat = max(now, tat) + interval_ms
#   if new_tat - burst_ms <= now: grant; else return wait_ms
#
# ``burst_ms`` = interval_ms × burst_size; a burst of 10 at 1 req / 2 s
# ⇒ 20000ms tolerance. The first 10 req pass instantly; the 11th waits
# 2s for the bucket to drain.
#
# Implemented as GET + SET rather than a Lua script because fakeredis
# (used in tests) doesn't support EVAL. This leaves a small TOCTOU
# window between GET and SET — two racing acquires can both see the
# same TAT and both succeed, producing at most one token of overshoot
# per race. Acceptable here because (a) our burst budget is already
# within the search engines' observed tolerance, and (b) the realistic
# traffic shape is one resolve per user per save, not a thundering
# herd. If that changes, swap GET+SET for a Lua script or WATCH/MULTI.


async def _acquire_token(
    redis: aioredis.Redis, engine: str, interval_ms: int, burst_ms: int
) -> int:
    """Return 0 if the request may proceed immediately, else ms to wait.

    The caller may either sleep and retry, or skip to the next engine.
    We choose "skip" in ``_resolve_online`` so that a throttled Startpage
    doesn't block the full resolve — DDG or Brave might be ready.
    """
    key = f"tokens:fbloc:{engine}"
    now_ms = int(time.time() * 1000)
    current = await redis.get(key)
    if current is None:
        tat = now_ms
    else:
        try:
            raw = current.decode() if isinstance(current, bytes) else current
            tat = int(raw)
        except (ValueError, AttributeError):
            tat = now_ms
    new_tat = max(tat, now_ms) + interval_ms
    wait_ms = (new_tat - burst_ms) - now_ms
    if wait_ms > 0:
        return wait_ms
    # TTL 1h keeps the key bounded; the bucket "refills" naturally once
    # TAT falls behind now. PX param is milliseconds.
    await redis.set(key, new_tat, px=3_600_000)
    return 0


# MARK: - Search-engine adapters


_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

_FB_ID_IN_URL = re.compile(r"https?://(?:www\.)?facebook\.com/marketplace/(\d+)/")


async def _fetch_startpage(
    http: httpx.AsyncClient, q: str, proxy_url: str | None
) -> str | None:
    url = f"https://www.startpage.com/do/search?query={quote_plus(q)}"
    try:
        r = await http.get(url, headers={"User-Agent": _UA}, timeout=10.0)
        return r.text if r.status_code == 200 else None
    except httpx.HTTPError as e:
        logger.debug("Startpage fetch error: %s", e)
        return None


async def _fetch_ddg(
    http: httpx.AsyncClient, q: str, proxy_url: str | None
) -> str | None:
    try:
        r = await http.post(
            "https://html.duckduckgo.com/html/",
            data={"q": q},
            headers={"User-Agent": _UA, "Referer": "https://duckduckgo.com/"},
            timeout=10.0,
        )
        # DDG returns 202 (not 200) when it challenges — treat as miss.
        return r.text if r.status_code == 200 else None
    except httpx.HTTPError as e:
        logger.debug("DDG fetch error: %s", e)
        return None


async def _fetch_brave(
    http: httpx.AsyncClient, q: str, proxy_url: str | None
) -> str | None:
    url = f"https://search.brave.com/search?q={quote_plus(q)}"
    try:
        r = await http.get(url, headers={"User-Agent": _UA}, timeout=10.0)
        return r.text if r.status_code == 200 else None
    except httpx.HTTPError as e:
        logger.debug("Brave fetch error: %s", e)
        return None


# MARK: - Canonical-name extraction
#
# FB's own "Buy and Sell in <City>, <State> | Facebook Marketplace"
# string is regularly excerpted by search engines near the result URL.
# We can't hit FB directly (400s us), but we can lift the canonical
# name from the surrounding snippet. This is how we catch
# "Ding Dong, TX" → resolved-to "Killeen, TX" mismatches.


_CANONICAL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"Buy and Sell in ([A-Z][A-Za-z .'\-]{2,60})\s*(?:\||<|&)",
        re.IGNORECASE,
    ),
    re.compile(
        r"Marketplace\s*[-–|]\s*([A-Z][A-Za-z .'\-]{2,60}?,\s*[A-Z]{2})",
        re.IGNORECASE,
    ),
    re.compile(
        r"([A-Z][A-Za-z .'\-]{2,60}?,\s*[A-Z]{2})\s*\|\s*Facebook\s*Marketplace",
        re.IGNORECASE,
    ),
]


def _extract_canonical_near(html: str, match_pos: int) -> str | None:
    """Look for 'City, State' in the 600-char window around a Marketplace URL match."""
    start = max(0, match_pos - 400)
    end = min(len(html), match_pos + 600)
    window = html[start:end]
    for pattern in _CANONICAL_PATTERNS:
        m = pattern.search(window)
        if m:
            return m.group(1).strip().strip(",")
    return None


def _parse_result_html(html: str) -> tuple[int, str | None] | None:
    """Extract (location_id, canonical_name_or_None) from search-result HTML."""
    m = _FB_ID_IN_URL.search(html)
    if not m:
        return None
    loc_id = int(m.group(1))
    canonical = _extract_canonical_near(html, m.start())
    return loc_id, canonical


# MARK: - Proxy URL (mirrors walmart_http._build_proxy_url)


def _build_decodo_proxy_url(cfg: Settings) -> str | None:
    if not (cfg.DECODO_PROXY_USER and cfg.DECODO_PROXY_PASS):
        return None
    user = cfg.DECODO_PROXY_USER
    if not user.startswith("user-"):
        user = f"user-{user}"
    if "country-" not in user:
        user = f"{user}-country-us"
    encoded_pass = quote_plus(cfg.DECODO_PROXY_PASS)
    host = cfg.DECODO_PROXY_HOST
    if ":" not in host:
        host = f"{host}:{cfg.DECODO_PROXY_PORT}"
    return f"http://{user}:{encoded_pass}@{host}"


# MARK: - Engine table


EngineFetcher = Callable[
    [httpx.AsyncClient, str, Optional[str]], "asyncio.Future[str | None]"
]


@dataclass(frozen=True)
class _EngineSpec:
    name: str
    fetcher: EngineFetcher
    interval_ms: int  # min ms between acquisitions
    burst_ms: int  # tolerated ms over interval_ms


# Empirical thresholds from the findings doc + our own probe runs:
#   Startpage ~12 req before CAPTCHA, 2 s sleep sustains → interval 2 s, burst 10
#   DDG ~8 req before anomaly lockout (10+ min) → interval 10 s, burst 3
#   Brave ~5 req before 429 → interval 10 s, burst 2
_DEFAULT_ENGINES: list[_EngineSpec] = [
    _EngineSpec("startpage", _fetch_startpage, 2_000, 20_000),
    _EngineSpec("ddg", _fetch_ddg, 10_000, 30_000),
    _EngineSpec("brave", _fetch_brave, 10_000, 20_000),
]


# MARK: - Resolver core


# Redis sentinels. The string-encoding is deliberate — Redis values
# are bytes, and we want a single GET to distinguish "resolved"
# / "unresolved tombstone" / "engines throttled, retry soon"
# without a second round trip.
_REDIS_THROTTLED = "__T__"
_REDIS_UNRESOLVED = "__U__"

_TTL_RESOLVED_S = 86400  # 24h — IDs are stable; refresh on read
_TTL_UNRESOLVED_S = 3600  # 1h — cheap retry for typos / new places
_TTL_THROTTLED_S = 300  # 5min — transient, don't tombstone PG

_LOCK_TTL_S = 30
_NOTIFY_PREFIX = "fbmkt:notify:"

# Global cap so a traffic spike doesn't fan out unlimited concurrent
# live-resolves, exhausting the Decodo pool. Per-process (per uvicorn
# worker); good enough because the Redis token bucket above enforces
# cross-process rate.
_LIVE_RESOLVE_SEMAPHORE = asyncio.Semaphore(4)


class FbLocationResolver:
    """Resolve (city, state_code, country) → FB numeric location_id.

    Collaborators come in via the constructor so tests can substitute
    ``fakeredis.aioredis.FakeRedis`` + an in-memory SQLAlchemy session
    + a stub ``httpx.AsyncClient`` without patching module globals.
    """

    def __init__(
        self,
        db: AsyncSession,
        redis: aioredis.Redis,
        http: httpx.AsyncClient | None = None,
        cfg: Settings | None = None,
        engines: list[_EngineSpec] | None = None,
    ):
        self.db = db
        self.redis = redis
        self._cfg = cfg or settings
        self._http = http
        self._owns_http = http is None
        self._engines = engines or _DEFAULT_ENGINES

    async def _get_http(self) -> httpx.AsyncClient:
        if self._http is not None:
            return self._http
        proxy = _build_decodo_proxy_url(self._cfg)
        self._http = httpx.AsyncClient(
            proxy=proxy, trust_env=False, follow_redirects=True
        )
        return self._http

    async def aclose(self) -> None:
        if self._owns_http and self._http is not None:
            await self._http.aclose()
            self._http = None

    async def resolve(
        self, city: str, state_code: str, country: str = "US"
    ) -> ResolvedLocation:
        """Three-tier resolve. Returns ``ResolvedLocation`` — never raises.

        Failure modes are encoded in the return value's ``location_id``
        / ``source`` fields; ambient HTTP / Redis / DB errors are logged
        + converted to ``source='throttled'``. The caller's L1 cache
        checks can distinguish permanent from transient.
        """
        state_code = state_code.strip().upper()
        country = country.strip().upper() or "US"
        city_norm = _normalize_city(city)
        if not city_norm:
            return ResolvedLocation(None, None, "unresolved", False)
        if not re.fullmatch(r"[A-Z]{2}", state_code):
            return ResolvedLocation(None, None, "unresolved", False)

        key = _redis_key(country, state_code, city_norm)

        # L1 — Redis
        cached = await self._redis_get(key)
        if cached is not None:
            return cached

        # L2 — Postgres
        row = await self._db_get(city_norm, state_code, country)
        if row is not None:
            resolved = self._from_row(row)
            await self._redis_set(key, resolved)
            return resolved

        # L3 — singleflight-guarded live resolve
        return await self._singleflight_resolve(
            key, city_norm, state_code, country
        )

    # MARK: - L1 Redis

    async def _redis_get(self, key: str) -> ResolvedLocation | None:
        try:
            cached = await self.redis.get(key)
        except Exception as e:  # noqa: BLE001
            logger.warning("Redis GET failed for %s (falling through): %s", key, e)
            return None
        if cached is None:
            return None
        value = cached.decode() if isinstance(cached, bytes) else cached
        if value == _REDIS_THROTTLED:
            return ResolvedLocation(None, None, "throttled", False)
        if value == _REDIS_UNRESOLVED or value == "":
            return ResolvedLocation(None, None, "unresolved", False)
        try:
            data = json.loads(value)
            return ResolvedLocation(
                location_id=data.get("id"),
                canonical_name=data.get("n"),
                source=data.get("s", "cache"),
                verified=bool(data.get("v", False)),
            )
        except (json.JSONDecodeError, TypeError):
            # Corrupt cache — nuke and fall through to L2.
            await self.redis.delete(key)
            return None

    async def _redis_set(self, key: str, resolved: ResolvedLocation) -> None:
        if resolved.source == "throttled":
            payload = _REDIS_THROTTLED
            ttl = _TTL_THROTTLED_S
        elif resolved.location_id is None:
            payload = _REDIS_UNRESOLVED
            ttl = _TTL_UNRESOLVED_S
        else:
            payload = json.dumps(
                {
                    "id": resolved.location_id,
                    "n": resolved.canonical_name,
                    "s": resolved.source,
                    "v": resolved.verified,
                }
            )
            ttl = _TTL_RESOLVED_S
        try:
            await self.redis.setex(key, ttl, payload)
        except Exception as e:  # noqa: BLE001
            logger.warning("Redis SETEX failed for %s (non-fatal): %s", key, e)

    # MARK: - L2 Postgres

    async def _db_get(
        self, city_normalized: str, state_code: str, country: str
    ) -> FbMarketplaceLocation | None:
        stmt = select(FbMarketplaceLocation).where(
            FbMarketplaceLocation.country == country,
            FbMarketplaceLocation.state_code == state_code,
            FbMarketplaceLocation.city == city_normalized,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    def _from_row(self, row: FbMarketplaceLocation) -> ResolvedLocation:
        return ResolvedLocation(
            location_id=row.location_id,
            canonical_name=row.canonical_name,
            # Reading from PG is a hit, not a re-resolve — keep ``source``
            # as ``cache`` so callers can tell at a glance where the data
            # came from. Original source stays in the row.
            source="cache",
            verified=row.verified,
        )

    async def _db_upsert(
        self,
        city_normalized: str,
        state_code: str,
        country: str,
        resolved: ResolvedLocation,
    ) -> None:
        stmt = (
            pg_insert(FbMarketplaceLocation)
            .values(
                country=country,
                state_code=state_code,
                city=city_normalized,
                location_id=resolved.location_id,
                canonical_name=resolved.canonical_name,
                verified=resolved.verified,
                source=resolved.source,
            )
            .on_conflict_do_update(
                index_elements=["country", "state_code", "city"],
                set_={
                    "location_id": resolved.location_id,
                    "canonical_name": resolved.canonical_name,
                    "verified": resolved.verified,
                    "source": resolved.source,
                    "resolved_at": text("NOW()"),
                },
            )
        )
        await self.db.execute(stmt)
        await self.db.commit()

    # MARK: - L3 Live resolve + singleflight

    async def _singleflight_resolve(
        self, key: str, city_norm: str, state_code: str, country: str
    ) -> ResolvedLocation:
        lock_key = f"lock:{key}"
        notify_ch = f"{_NOTIFY_PREFIX}{key}"

        # Try to become the resolver.
        got_lock = False
        try:
            got_lock = bool(
                await self.redis.set(lock_key, b"1", nx=True, ex=_LOCK_TTL_S)
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("Redis lock acquire failed, resolving unlocked: %s", e)
            return await self._do_live_resolve(
                key, city_norm, state_code, country, persist=True
            )

        if got_lock:
            try:
                async with _LIVE_RESOLVE_SEMAPHORE:
                    resolved = await self._do_live_resolve(
                        key, city_norm, state_code, country, persist=True
                    )
                await self._publish_result(notify_ch, resolved)
                return resolved
            finally:
                try:
                    await self.redis.delete(lock_key)
                except Exception:  # noqa: BLE001
                    pass
        else:
            # Subscribe BEFORE re-checking cache to close the race window
            # where the winner publishes between our GET and SUBSCRIBE.
            return await self._await_notify(
                key, notify_ch, city_norm, state_code, country
            )

    async def _publish_result(
        self, channel: str, resolved: ResolvedLocation
    ) -> None:
        payload = self._encode_for_notify(resolved)
        try:
            await self.redis.publish(channel, payload)
        except Exception as e:  # noqa: BLE001
            logger.warning("Redis PUBLISH failed (waiters will timeout): %s", e)

    @staticmethod
    def _encode_for_notify(resolved: ResolvedLocation) -> str:
        if resolved.source == "throttled":
            return _REDIS_THROTTLED
        if resolved.location_id is None:
            return _REDIS_UNRESOLVED
        return json.dumps(
            {
                "id": resolved.location_id,
                "n": resolved.canonical_name,
                "s": resolved.source,
                "v": resolved.verified,
            }
        )

    @staticmethod
    def _decode_from_notify(raw: bytes | str) -> ResolvedLocation:
        value = raw.decode() if isinstance(raw, bytes) else raw
        if value == _REDIS_THROTTLED:
            return ResolvedLocation(None, None, "throttled", False)
        if value == _REDIS_UNRESOLVED or value == "":
            return ResolvedLocation(None, None, "unresolved", False)
        try:
            data = json.loads(value)
        except json.JSONDecodeError:
            return ResolvedLocation(None, None, "unresolved", False)
        return ResolvedLocation(
            location_id=data.get("id"),
            canonical_name=data.get("n"),
            source=data.get("s", "cache"),
            verified=bool(data.get("v", False)),
        )

    async def _await_notify(
        self,
        key: str,
        notify_ch: str,
        city_norm: str,
        state_code: str,
        country: str,
    ) -> ResolvedLocation:
        pubsub = self.redis.pubsub()
        try:
            await pubsub.subscribe(notify_ch)
            # Re-check L1 after subscribing. If the winner finished
            # between our initial L1 miss and the subscribe, the result
            # is already cached; we'd block forever otherwise.
            cached = await self._redis_get(key)
            if cached is not None:
                return cached
            try:
                async with asyncio.timeout(_LOCK_TTL_S + 1):
                    async for msg in pubsub.listen():
                        if msg.get("type") == "message":
                            return self._decode_from_notify(msg.get("data", b""))
            except asyncio.TimeoutError:
                logger.warning(
                    "Singleflight timeout for %s — winner may have crashed; "
                    "resolving without lock",
                    key,
                )
                return await self._do_live_resolve(
                    key, city_norm, state_code, country, persist=True
                )
        finally:
            try:
                await pubsub.unsubscribe(notify_ch)
                await pubsub.aclose()
            except Exception:  # noqa: BLE001
                pass
        # Fallthrough — in practice unreachable, but keeps the type
        # checker and linters happy.
        return ResolvedLocation(None, None, "unresolved", False)

    async def _do_live_resolve(
        self,
        key: str,
        city_norm: str,
        state_code: str,
        country: str,
        persist: bool,
    ) -> ResolvedLocation:
        resolved = await self._resolve_online(city_norm, state_code)
        if persist:
            await self._persist_and_cache(
                key, city_norm, state_code, country, resolved
            )
        return resolved

    async def _resolve_online(
        self, city_norm: str, state_code: str
    ) -> ResolvedLocation:
        """Try each engine in order; first one that yields a usable result wins."""
        # Build a display-shaped query. Canonical search works best with
        # the original-looking capitalization ("Brooklyn NY", not
        # "brooklyn ny"), so we un-normalize for the query string even
        # though the key uses the normalized form.
        q_city = " ".join(
            part.capitalize() for part in city_norm.split() if part
        )
        q = f"facebook marketplace {q_city} {state_code}"

        http = await self._get_http()
        proxy_url = _build_decodo_proxy_url(self._cfg)
        throttled = 0
        attempted = 0

        for engine in self._engines:
            wait_ms = await _acquire_token(
                self.redis, engine.name, engine.interval_ms, engine.burst_ms
            )
            if wait_ms > 0:
                throttled += 1
                logger.debug(
                    "fb_location_resolver engine=%s throttled, wait=%dms — skipping",
                    engine.name,
                    wait_ms,
                )
                continue
            attempted += 1
            html = await engine.fetcher(http, q, proxy_url)
            if not html:
                continue
            parsed = _parse_result_html(html)
            if parsed is None:
                continue
            loc_id, canonical = parsed
            return ResolvedLocation(
                location_id=loc_id,
                canonical_name=canonical,
                source=engine.name,
                verified=canonical is not None,
            )

        # All engines fired: either they all returned nothing (tombstone)
        # or they were all throttled (transient).
        if attempted == 0:
            return ResolvedLocation(None, None, "throttled", False)
        return ResolvedLocation(None, None, "unresolved", False)

    async def _persist_and_cache(
        self,
        key: str,
        city_norm: str,
        state_code: str,
        country: str,
        resolved: ResolvedLocation,
    ) -> None:
        """Write L2 + warm L1. Throttled results skip PG."""
        if resolved.source == "throttled":
            await self._redis_set(key, resolved)
            return
        try:
            await self._db_upsert(city_norm, state_code, country, resolved)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "fb_location_resolver DB upsert failed (serving live result "
                "without persistence): %s",
                e,
            )
        await self._redis_set(key, resolved)
