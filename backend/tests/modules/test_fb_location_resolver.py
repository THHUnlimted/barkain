"""Tests for FB Marketplace location resolver + router.

Covers:
    - Normalization (abbreviations, suffixes, punctuation, non-ASCII)
    - Canonical-name extraction from search-result HTML
    - L1 Redis hit → L2 Postgres hit → L3 live resolve
    - Engine fallback (1st fails → 2nd succeeds)
    - Tombstoning (unresolved) vs throttled persist behavior
    - Singleflight: two concurrent resolves share one live call
    - Router: happy path, 429 on throttle, 422 on invalid state, auth required
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
import pytest_asyncio

from modules.m2_prices.adapters.fb_marketplace_location_resolver import (
    FbLocationResolver,
    ResolvedLocation,
    _EngineSpec,
    _extract_canonical_near,
    _normalize_city,
    _parse_result_html,
    _redis_key,
)
from modules.m2_prices.fb_location_models import FbMarketplaceLocation


# MARK: - Normalization


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Brooklyn", "brooklyn"),
        ("BROOKLYN", "brooklyn"),
        ("  Brooklyn  ", "brooklyn"),
        # Abbreviation expansion — the whole point of the normalizer.
        ("St. Louis", "saint louis"),
        ("Saint Louis", "saint louis"),
        ("Mt. Pleasant", "mount pleasant"),
        ("Ft. Wayne", "fort wayne"),
        # Suffix drop.
        ("New York City", "new york"),
        ("Oak Park Village", "oak park"),
        # Non-ASCII fold.
        ("São Paulo", "sao paulo"),
        # Punctuation collapse.
        ("Winston-Salem", "winston salem"),
        ("O'Fallon", "o fallon"),
        # Edge case — empty / punctuation-only.
        ("...", ""),
        ("   ", ""),
    ],
)
def test_normalize_city(raw: str, expected: str) -> None:
    assert _normalize_city(raw) == expected


def test_redis_key_is_stable_across_case() -> None:
    a = _redis_key("US", "NY", _normalize_city("St. John's"))
    b = _redis_key("us", "ny", _normalize_city("SAINT JOHN'S"))
    assert a == b


# MARK: - Canonical-name extraction


def test_parse_result_html_returns_id_and_canonical() -> None:
    html = (
        '<a href="https://www.facebook.com/marketplace/112111905481230/">'
        "Buy and Sell in Brooklyn, NY | Facebook Marketplace</a>"
    )
    result = _parse_result_html(html)
    assert result is not None
    loc_id, canonical = result
    assert loc_id == 112111905481230
    assert canonical and "Brooklyn" in canonical


def test_parse_result_html_no_match() -> None:
    assert _parse_result_html("<html>nothing here</html>") is None


def test_extract_canonical_from_marketplace_dash_city() -> None:
    html = "Marketplace - Killeen, TX | something else"
    canonical = _extract_canonical_near(html, 0)
    assert canonical and "Killeen" in canonical


# MARK: - Canonical-name validation (fb-resolver-postfix-1)
#
# The first numeric URL in HTML isn't always the right one. Search
# engines mix in sub-region pages ("West Raleigh") that share the
# Marketplace URL shape but represent a different metro. Without
# validation, the resolver was caching sub-region IDs under canonical
# city keys — Raleigh users would see West Raleigh listings.


# Two result <div>s with ~800 chars of padding between them so the
# canonical-near window (±400/+600) for each match doesn't bleed into
# the other's snippet. Mirrors real Startpage / DDG / Brave result
# layouts where each organic hit is its own block with wide
# separation.
_RESULT_PADDING = " " * 800
_RALEIGH_MIXED_HTML = (
    # Sub-region hit appears FIRST — would have won under the legacy
    # first-match-wins behavior.
    '<div class="result">'
    '<a href="https://www.facebook.com/marketplace/110279135657365/">'
    "Buy and Sell in West Raleigh, NC | Facebook Marketplace</a>"
    "</div>" + _RESULT_PADDING +
    # Then the canonical city Page ID, which is the right answer.
    '<div class="result">'
    '<a href="https://www.facebook.com/marketplace/103879976317396/cars/">'
    "Cars for sale in Raleigh, North Carolina | Facebook Marketplace</a>"
    "</div>"
)


def test_parse_result_html_picks_canonical_city_over_subregion() -> None:
    """When multiple numeric IDs appear and one is a sub-region (West X)
    while another is the requested city, accept the city-matching one
    even though the sub-region appeared first in the HTML."""
    result = _parse_result_html(_RALEIGH_MIXED_HTML, requested_city_norm="raleigh")
    assert result is not None
    loc_id, canonical = result
    assert loc_id == 103879976317396, "must skip the West Raleigh sub-region"
    assert canonical and "Raleigh" in canonical


def test_parse_result_html_returns_none_when_only_subregion_validated() -> None:
    """When the only numeric ID has a canonical that DIFFERS from the
    requested city (West Raleigh vs Raleigh), return None — the
    caller falls through to the next engine instead of persisting a
    wrong-city ID. This is the win condition for the seed stragglers."""
    only_subregion = (
        '<div class="result">'
        '<a href="https://www.facebook.com/marketplace/110279135657365/">'
        "Buy and Sell in West Raleigh, NC | Facebook Marketplace</a>"
        "</div>"
    )
    assert _parse_result_html(only_subregion, requested_city_norm="raleigh") is None


def test_parse_result_html_falls_back_to_id_when_no_canonical_text() -> None:
    """Real-world case (seen on Brave for Raleigh): the HTML has the
    right numeric URL but the search engine didn't include enough
    snippet text for the canonical patterns to fire. Strict
    rejection would regress here because the ID is actually correct.
    Fall back to the first numeric ID rather than tombstone — the
    persistence layer sets verified=False so a weekly verifier
    (Phase 4) can re-check later."""
    bare_url_no_context = (
        # 800 chars of padding before so the canonical-near window
        # has nothing to grab onto either side of the URL.
        "x" * 800 +
        '<a href="https://www.facebook.com/marketplace/103879976317396/cars/">'
        "</a>" +
        "x" * 800
    )
    result = _parse_result_html(bare_url_no_context, requested_city_norm="raleigh")
    assert result is not None
    assert result[0] == 103879976317396
    assert result[1] is None  # canonical correctly absent


def test_parse_result_html_normalizes_st_paul() -> None:
    """Normalization parity: 'St. Paul, MN' canonical matches a
    'saint paul' request — same `_normalize_city` helper as elsewhere
    in the resolver."""
    html = (
        '<a href="https://www.facebook.com/marketplace/100123456789012/">'
        "Buy and Sell in St. Paul, MN | Facebook Marketplace</a>"
    )
    result = _parse_result_html(html, requested_city_norm="saint paul")
    assert result is not None
    assert result[0] == 100123456789012


def test_parse_result_html_legacy_no_validation_when_arg_omitted() -> None:
    """Backward-compat: omitting `requested_city_norm` preserves
    first-match-wins behavior. Anyone calling the helper without
    routing context (e.g., the existing happy-path test) gets the
    same shape as before the post-fix."""
    result = _parse_result_html(_RALEIGH_MIXED_HTML)
    assert result is not None
    # Legacy path returns the FIRST numeric URL — the sub-region —
    # without validation. This documents the contract (callers that
    # care about correctness must pass requested_city_norm).
    assert result[0] == 110279135657365


# MARK: - Resolver with fake engines


class _FakeEngine:
    """Records calls + returns a scripted sequence of responses."""

    def __init__(self, name: str, responses: list[str | None]):
        self.name = name
        self._responses = list(responses)
        self.calls = 0

    async def __call__(
        self, http: httpx.AsyncClient, q: str, proxy_url: str | None
    ) -> str | None:
        self.calls += 1
        if not self._responses:
            return None
        return self._responses.pop(0)


def _engine_spec(
    name: str, fetcher: _FakeEngine, interval_ms: int = 1, burst_ms: int = 100
) -> _EngineSpec:
    return _EngineSpec(
        name=name, fetcher=fetcher, interval_ms=interval_ms, burst_ms=burst_ms
    )


BROOKLYN_HTML = (
    '<div class="result">'
    '<a href="https://www.facebook.com/marketplace/112111905481230/">'
    "Buy and Sell in Brooklyn, NY | Facebook Marketplace</a>"
    "</div>"
)


@pytest_asyncio.fixture
async def noop_http() -> httpx.AsyncClient:
    # Passed into the resolver so it doesn't try to spin up a real
    # client; the fake engines ignore the http arg.
    async with httpx.AsyncClient() as client:
        yield client


@pytest.mark.asyncio
async def test_resolve_hits_redis_cache_first(db_session, fake_redis, noop_http) -> None:
    engine = _FakeEngine("startpage", [BROOKLYN_HTML])
    resolver = FbLocationResolver(
        db=db_session,
        redis=fake_redis,
        http=noop_http,
        engines=[_engine_spec("startpage", engine)],
    )
    # Pre-populate Redis.
    key = _redis_key("US", "NY", "brooklyn")
    await fake_redis.setex(
        key,
        60,
        json.dumps({"id": 112111905481230, "n": "Brooklyn, NY", "s": "seed", "v": True}),
    )

    resolved = await resolver.resolve("Brooklyn", "NY")
    assert resolved.location_id == 112111905481230
    assert engine.calls == 0  # cache hit — engine never touched


@pytest.mark.asyncio
async def test_resolve_hits_db_cache_then_warms_redis(
    db_session, fake_redis, noop_http
) -> None:
    row = FbMarketplaceLocation(
        country="US",
        state_code="NY",
        city="brooklyn",
        location_id=112111905481230,
        canonical_name="Brooklyn, NY",
        verified=True,
        source="seed",
    )
    db_session.add(row)
    await db_session.flush()

    engine = _FakeEngine("startpage", [BROOKLYN_HTML])
    resolver = FbLocationResolver(
        db=db_session,
        redis=fake_redis,
        http=noop_http,
        engines=[_engine_spec("startpage", engine)],
    )

    resolved = await resolver.resolve("Brooklyn", "NY")
    assert resolved.location_id == 112111905481230
    assert engine.calls == 0

    # L1 warmed — second resolve should hit Redis.
    cached_raw = await fake_redis.get(_redis_key("US", "NY", "brooklyn"))
    cached = json.loads(cached_raw)
    assert cached["id"] == 112111905481230


@pytest.mark.asyncio
async def test_resolve_live_resolves_and_persists(
    db_session, fake_redis, noop_http
) -> None:
    engine = _FakeEngine("startpage", [BROOKLYN_HTML])
    resolver = FbLocationResolver(
        db=db_session,
        redis=fake_redis,
        http=noop_http,
        engines=[_engine_spec("startpage", engine)],
    )

    resolved = await resolver.resolve("Brooklyn", "NY")
    assert resolved.location_id == 112111905481230
    assert resolved.source == "startpage"
    assert resolved.verified is True  # canonical extracted
    assert engine.calls == 1

    # PG row written.
    from sqlalchemy import select

    row = (
        await db_session.execute(
            select(FbMarketplaceLocation).where(
                FbMarketplaceLocation.city == "brooklyn"
            )
        )
    ).scalar_one()
    assert row.location_id == 112111905481230
    assert row.source == "startpage"


@pytest.mark.asyncio
async def test_resolve_falls_back_to_next_engine(
    db_session, fake_redis, noop_http
) -> None:
    engine_a = _FakeEngine("startpage", [None])  # returns no HTML
    engine_b = _FakeEngine("ddg", [BROOKLYN_HTML])
    resolver = FbLocationResolver(
        db=db_session,
        redis=fake_redis,
        http=noop_http,
        engines=[
            _engine_spec("startpage", engine_a),
            _engine_spec("ddg", engine_b),
        ],
    )

    resolved = await resolver.resolve("Brooklyn", "NY")
    assert resolved.source == "ddg"
    assert engine_a.calls == 1 and engine_b.calls == 1


@pytest.mark.asyncio
async def test_resolve_skips_engine_returning_only_subregion_hits(
    db_session, fake_redis, noop_http
) -> None:
    """Resolver-level integration of the canonical-name validation:
    when engine A's HTML contains only sub-region IDs (West Raleigh)
    that don't match the requested city (Raleigh), fall through to
    engine B which has the canonical city ID. This is the case that
    poisoned the seed for Oakland / Raleigh / Seattle pre-postfix."""
    only_subregion_html = (
        '<div class="result">'
        '<a href="https://www.facebook.com/marketplace/110279135657365/">'
        "Buy and Sell in West Raleigh, NC | Facebook Marketplace</a>"
        "</div>"
    )
    canonical_html = (
        '<div class="result">'
        '<a href="https://www.facebook.com/marketplace/103879976317396/cars/">'
        "Cars for sale in Raleigh, North Carolina | Facebook Marketplace</a>"
        "</div>"
    )
    engine_a = _FakeEngine("startpage", [only_subregion_html])
    engine_b = _FakeEngine("brave", [canonical_html])
    resolver = FbLocationResolver(
        db=db_session,
        redis=fake_redis,
        http=noop_http,
        engines=[
            _engine_spec("startpage", engine_a),
            _engine_spec("brave", engine_b),
        ],
    )

    resolved = await resolver.resolve("Raleigh", "NC")
    assert resolved.location_id == 103879976317396, (
        "must skip startpage's West Raleigh hit and accept brave's Raleigh hit"
    )
    assert resolved.source == "brave"
    assert engine_a.calls == 1 and engine_b.calls == 1


@pytest.mark.asyncio
async def test_resolve_all_engines_empty_tombstones(
    db_session, fake_redis, noop_http
) -> None:
    engine = _FakeEngine("startpage", [""])  # 200 with empty body
    resolver = FbLocationResolver(
        db=db_session,
        redis=fake_redis,
        http=noop_http,
        engines=[_engine_spec("startpage", engine)],
    )

    resolved = await resolver.resolve("Toad Suck", "AR")
    assert resolved.location_id is None
    assert resolved.source == "unresolved"

    # Tombstone row persists so the next lookup short-circuits.
    from sqlalchemy import select

    row = (
        await db_session.execute(
            select(FbMarketplaceLocation).where(
                FbMarketplaceLocation.city == "toad suck"
            )
        )
    ).scalar_one()
    assert row.location_id is None
    assert row.source == "unresolved"


@pytest.mark.asyncio
async def test_resolve_all_engines_throttled_skips_persist(
    db_session, fake_redis, noop_http
) -> None:
    """When every engine is throttled, write a 5-min Redis bar but no PG row.

    We simulate throttle by giving the GCRA bucket zero burst capacity
    and pre-exhausting it.
    """
    engine = _FakeEngine("startpage", [BROOKLYN_HTML])
    # interval 1000 ms, burst 0 ⇒ first call's new_tat exceeds now + 0,
    # so token request reports wait > 0. The resolver skips the engine.
    resolver = FbLocationResolver(
        db=db_session,
        redis=fake_redis,
        http=noop_http,
        engines=[_engine_spec("startpage", engine, interval_ms=1000, burst_ms=0)],
    )

    # Prime the bucket so the next acquire will fail.
    from modules.m2_prices.adapters.fb_marketplace_location_resolver import (
        _acquire_token,
    )

    await _acquire_token(fake_redis, "startpage", 1000, 0)

    resolved = await resolver.resolve("Brooklyn", "NY")
    assert resolved.source == "throttled"
    assert engine.calls == 0  # never got a token

    # No PG tombstone for transient throttle.
    from sqlalchemy import select

    count = len(
        (
            await db_session.execute(
                select(FbMarketplaceLocation).where(
                    FbMarketplaceLocation.city == "brooklyn"
                )
            )
        ).scalars().all()
    )
    assert count == 0


@pytest.mark.asyncio
async def test_singleflight_two_concurrent_resolves_one_live_call(
    db_session, fake_redis, noop_http
) -> None:
    """Two simultaneous resolves on the same cold key should share one live call.

    The winner resolves via the engine and publishes; the loser receives
    the published payload via pubsub instead of firing its own engine call.
    """
    call_started = asyncio.Event()
    release_call = asyncio.Event()

    class _GatedEngine:
        name = "startpage"

        def __init__(self) -> None:
            self.calls = 0

        async def __call__(
            self, http: httpx.AsyncClient, q: str, proxy_url: str | None
        ) -> str | None:
            self.calls += 1
            call_started.set()
            # Hold the winner inside the engine until we've started the
            # loser and given it time to subscribe to the notify channel.
            await release_call.wait()
            return BROOKLYN_HTML

    engine = _GatedEngine()
    resolver_1 = FbLocationResolver(
        db=db_session,
        redis=fake_redis,
        http=noop_http,
        engines=[_engine_spec("startpage", engine)],
    )
    resolver_2 = FbLocationResolver(
        db=db_session,
        redis=fake_redis,
        http=noop_http,
        engines=[_engine_spec("startpage", engine)],
    )

    async def winner() -> ResolvedLocation:
        return await resolver_1.resolve("Brooklyn", "NY")

    async def loser() -> ResolvedLocation:
        # Wait for the winner to hit the engine so the lock is held
        # before we try. Otherwise test order is nondeterministic.
        await call_started.wait()
        # Give the loser path enough time to subscribe before release.
        result = await resolver_2.resolve("Brooklyn", "NY")
        return result

    winner_task = asyncio.create_task(winner())
    loser_task = asyncio.create_task(loser())

    # Ensure the loser has actually entered resolve() and subscribed
    # before we release the winner. 0.2s is plenty for in-memory Redis.
    await call_started.wait()
    await asyncio.sleep(0.2)
    release_call.set()

    winner_result, loser_result = await asyncio.gather(winner_task, loser_task)

    assert winner_result.location_id == 112111905481230
    assert loser_result.location_id == 112111905481230
    # Singleflight invariant: exactly ONE engine call across both resolves.
    assert engine.calls == 1


# MARK: - Router integration


@pytest.mark.asyncio
async def test_resolve_endpoint_happy_path(client, db_session, fake_redis) -> None:
    # Pre-seed so the endpoint doesn't hit the live engines.
    row = FbMarketplaceLocation(
        country="US",
        state_code="NY",
        city="brooklyn",
        location_id=112111905481230,
        canonical_name="Brooklyn, NY",
        verified=True,
        source="seed",
    )
    db_session.add(row)
    await db_session.flush()

    resp = await client.post(
        "/api/v1/fb-location/resolve",
        json={"city": "Brooklyn", "state": "NY"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["location_id"] == "112111905481230"
    assert body["verified"] is True
    assert body["canonical_name"] == "Brooklyn, NY"
    # Renamed in fb-resolver-followups L13. The DB column stays `source`
    # for analytics; the wire-format key is `resolution_path` and the
    # value set is the public enum (no engine names). Seeded rows
    # report `cache` because the L2 PG hit overwrites resolved.source
    # to "cache".
    assert "source" not in body
    assert body["resolution_path"] == "cache"


@pytest.mark.asyncio
async def test_resolve_endpoint_collapses_engine_to_live(
    client, db_session, fake_redis
) -> None:
    """Engine-specific values (startpage / ddg / brave / user) collapse to
    `live` on the wire so the iOS Codable enum stays stable as we add or
    swap engines server-side. The DB column keeps the engine name."""
    row = FbMarketplaceLocation(
        country="US",
        state_code="NY",
        city="brooklyn",
        location_id=112111905481230,
        canonical_name="Brooklyn, NY",
        verified=True,
        source="startpage",  # engine-specific internal value
    )
    db_session.add(row)
    await db_session.flush()

    resp = await client.post(
        "/api/v1/fb-location/resolve",
        json={"city": "Brooklyn", "state": "NY"},
    )
    assert resp.status_code == 200
    body = resp.json()
    # cache hit on a startpage-sourced row → `cache` (the L2 path
    # overwrites resolved.source to "cache" on hit).
    assert body["resolution_path"] in {"cache", "live"}
    assert body["resolution_path"] not in {"startpage", "ddg", "brave", "user"}


@pytest.mark.asyncio
async def test_resolve_endpoint_rate_limit_fires_on_sixth_call(
    client, db_session, fake_redis
) -> None:
    """`fb_location_resolve` bucket caps at 5/min. Hard cap, no pro
    multiplier (the bucket protects shared external budget, not user
    throughput). Pre-seed a row so all 6 calls take the cache path and
    don't burn engine tokens during the test."""
    row = FbMarketplaceLocation(
        country="US",
        state_code="NY",
        city="brooklyn",
        location_id=112111905481230,
        canonical_name="Brooklyn, NY",
        verified=True,
        source="seed",
    )
    db_session.add(row)
    await db_session.flush()

    payload = {"city": "Brooklyn", "state": "NY"}
    for i in range(5):
        resp = await client.post("/api/v1/fb-location/resolve", json=payload)
        assert resp.status_code == 200, f"call {i + 1} unexpectedly throttled"

    resp = await client.post("/api/v1/fb-location/resolve", json=payload)
    assert resp.status_code == 429
    body = resp.json()
    assert body["detail"]["error"]["code"] == "RATE_LIMITED"


@pytest.mark.asyncio
async def test_resolve_endpoint_rejects_bad_state(client) -> None:
    resp = await client.post(
        "/api/v1/fb-location/resolve",
        json={"city": "Brooklyn", "state": "XX1"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_resolve_endpoint_requires_auth(unauthed_client, without_demo_mode) -> None:
    resp = await unauthed_client.post(
        "/api/v1/fb-location/resolve",
        json={"city": "Brooklyn", "state": "NY"},
    )
    assert resp.status_code == 401
