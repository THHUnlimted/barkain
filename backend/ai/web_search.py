"""Web-search synthesis path for product UPC resolution.

Pipeline: Serper SERP top-5 organic → constrained Gemini synthesis (no
grounding, ``thinking_budget=0``). Used as the **primary** AI leg of the
``asyncio.gather`` in ``m1_product/service.py``; the grounded path remains
as a fallback when this returns None.

**Bench validation** — bench/vendor-migrate-1 against 9 user-verified UPCs
(Switch Lite Hyrule, Instant Pot Duo, DeWalt DCD791D2, PS5 DualSense White,
Samsung PRO Plus Sonic 128GB microSD, Minisforum UM760 Slim Mini PC, iPad
Air M4 13", Dell Inspiron 14 7445, Lenovo Legion Go):

  - **E_current_budget0  : 45/45 (100% recall)**
  - E_hardened_budget512 : 40/45 ( 89% recall)
  - B_grounded_low       : 24/45 ( 53% recall) — current production baseline

  - p50 latency: **1627 ms** vs B's 3083 ms (-47%)
  - p90 latency: 2429 ms vs B's 4561 ms (-47%)
  - per-call cost: $0.00109 vs B's $0.040 (~36× cheaper)

Why budget=0 wins: Serper's top-5 organic for a real UPC tend to be
title-clear retail listings naming the product directly. Small thinking
budgets (256-1024) actually *hurt* recall on these clean snippets — the
model uses the tokens to second-guess itself. Setting ``thinking_budget=0``
forces direct snippet extraction, which is the right behavior for SERP
synthesis.

Soft-fails to None on:
  - SERPER_API_KEY not configured (logged as warning once per cold start)
  - Serper non-200 / network error
  - Zero organic results
  - Synthesis returns null device_name (model couldn't identify)
  - Any unexpected exception (logged with ``exc_info=True``)

Callers treat None as "not found" and fall back to grounded resolution.
"""

from __future__ import annotations

import json
import logging
import re
import time

import httpx
import redis.asyncio as aioredis

from ai.abstraction import gemini_generate
from app.config import settings

logger = logging.getLogger("barkain.ai.web_search")

# vendor-migrate-1-L1: outcome counters for the Serper resolve leg. Each
# tap on `/products/resolve` increments exactly one bucket so ops can
# answer "what % of resolves fall back to grounded?" with `HGETALL` in
# under a second instead of grepping uvicorn logs. Buckets:
#   - success           : Serper + synthesis both succeeded; iOS hit hot path
#   - synthesis_null    : Serper returned snippets but Gemini synthesis
#                         returned null device_name (snippets weren't
#                         informative enough — usually obscure SKU)
#   - serper_miss       : Serper returned zero organic results
#   - synthesis_error   : Gemini synthesis call raised (network / quota)
# Caller (`m1_product/service.py`) soft-falls to grounded Gemini for
# every non-`success` outcome, so `(synthesis_null + serper_miss +
# synthesis_error) / total` = the cold-path-fallback ratio.
_SERPER_OUTCOME_KEY = "metrics:serper_resolve:outcomes"


async def _record_serper_outcome(outcome: str) -> None:
    """HINCRBY one outcome bucket on the shared Redis. Soft-fails on any
    error — telemetry must never block the resolve hot path. Each call
    creates and tears down its own client; Redis connection overhead is
    in the same order as the metric write so a long-lived connection
    isn't worth the lifecycle complexity for now.
    """
    try:
        client = aioredis.from_url(settings.REDIS_URL)
    except Exception:  # malformed URL, etc.
        return
    try:
        await client.hincrby(_SERPER_OUTCOME_KEY, outcome, 1)
    except Exception:
        # Connection refused, timeout, anything — don't touch the
        # request path. The log line below is enough to diagnose.
        logger.debug(
            "serper outcome counter write failed (outcome=%s)",
            outcome, exc_info=True,
        )
    finally:
        try:
            await client.aclose()
        except Exception:
            pass

SERPER_URL = "https://google.serper.dev/search"
SERPER_SHOPPING_URL = "https://google.serper.dev/shopping"
SERPER_IMAGES_URL = "https://google.serper.dev/images"
SERPER_TIMEOUT_SEC = 10.0
SERPER_SHOPPING_TIMEOUT_SEC = 10.0
SERPER_NUM_RESULTS = 10
SERPER_SHOPPING_NUM_RESULTS = 20  # Hint to Google; actual returned count varies 19–40 (3n bench-validated 2026-04-27).
SERPER_TOP_N_FOR_PROMPT = 5
SYNTHESIS_MAX_TOKENS = 1024
SYNTHESIS_THINKING_BUDGET = 0

# Bench-winning prompt — vendor-migrate-1's E_current_budget0. Tightening
# this prompt is risky: hardened wording regressed recall in mini-grid
# testing. Change only with a fresh bench run. See bench/vendor-migrate-1.
SYNTHESIS_PROMPT = """You will identify a product from these search results for UPC barcode {upc}.

Use ONLY the snippets below. Do not invent. If the snippets are insufficient
to identify the product, return device_name: null.

Snippets:
{snippets}

Return STRICT JSON with this shape (no markdown, no commentary):
{{
  "device_name": "<full product name with brand>",
  "model": "<model number/identifier or null>",
  "chip": "<Apple silicon chip e.g. M4, M3 Pro, A18 Pro — null if not Apple>",
  "display_size_in": <integer inches for displays/tablets/laptops, null otherwise>
}}"""


_FENCE_OPEN_RE = re.compile(r"^```(?:json)?\s*\n?")
_FENCE_CLOSE_RE = re.compile(r"\n?```\s*$")
_FIRST_OBJ_RE = re.compile(r"\{[\s\S]*\}", re.M)


async def _serper_fetch(upc: str) -> list[dict] | None:
    """Issue one Serper /search call. Returns organic results list, or None
    on missing key, non-200, network error, or zero organic results."""
    api_key = settings.SERPER_API_KEY
    if not api_key:
        logger.warning("SERPER_API_KEY not configured — Serper synthesis disabled")
        return None
    body = {"q": f"UPC {upc}", "num": SERPER_NUM_RESULTS}
    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=SERPER_TIMEOUT_SEC) as client:
            resp = await client.post(SERPER_URL, json=body, headers=headers)
        elapsed_ms = (time.perf_counter() - t0) * 1000
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        logger.warning(
            "Serper fetch failed for UPC %s: %s: %r",
            upc, type(exc).__name__, exc,
        )
        return None

    if resp.status_code != 200:
        logger.warning(
            "Serper non-200 for UPC %s: status=%s elapsed=%.0fms",
            upc, resp.status_code, elapsed_ms,
        )
        return None

    try:
        data = resp.json()
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("Serper JSON parse failed for UPC %s: %r", upc, exc)
        return None

    organic = data.get("organic")
    if not organic:
        logger.info(
            "Serper UPC %s: zero organic results elapsed=%.0fms",
            upc, elapsed_ms,
        )
        return None
    logger.info(
        "Serper UPC %s: organic=%d elapsed=%.0fms",
        upc, len(organic), elapsed_ms,
    )
    return organic


def _first_image_url(organic: list[dict], *, top: int = SERPER_TOP_N_FOR_PROMPT) -> str | None:
    """Pick the first non-empty ``imageUrl`` from the top-N organic results.

    Deterministic — does not go through the LLM, so there's no hallucination
    risk. Serper's organic items sometimes carry an ``imageUrl`` extracted
    from the page's preview/og:image; when present it's a direct CDN URL
    (manufacturer or retailer), not a Google image-search redirect.
    """
    for hit in organic[:top]:
        url = hit.get("imageUrl")
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            return url
    return None


# MARK: - Thumbnail-only Serper lookup (pass 2 of SEARCH_THUMBNAIL_FALLBACK)
#
# Final-fallback thumbnail provider for M1 search rows. Fires only after
# both the primary providers AND the eBay Browse API thumbnail pass missed,
# because Serper is paid (~$0.001/call) where eBay is free. Hits Serper's
# ``/images`` endpoint (Google Images search) — purpose-built for finding
# images, unlike ``/search`` which only carries an ``imageUrl`` when
# Google detected an og:image preview (often missing for niche queries).
# Soft-fail; returns None on any error so the search pipeline never breaks
# because of a thumbnail call.


async def lookup_thumbnail_via_serper(query: str) -> str | None:
    """Issue one Serper /images (Google Images) call with an arbitrary
    product query and return the first image's URL.

    Caller composes ``query`` from brand + title (or just title when brand
    is unknown). Returns None on missing key, non-200, network error, or
    empty results. Pulls from the ``images[].imageUrl`` field — the
    direct hosted image, not the Google search-redirect URL.
    """
    api_key = settings.SERPER_API_KEY
    if not api_key:
        return None
    cleaned = (query or "").strip()
    if not cleaned:
        return None

    body = {"q": cleaned, "num": 3}
    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=SERPER_TIMEOUT_SEC) as client:
            resp = await client.post(SERPER_IMAGES_URL, json=body, headers=headers)
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        logger.warning(
            "Serper thumbnail fetch failed q=%r: %s: %r",
            cleaned, type(exc).__name__, exc,
        )
        return None

    if resp.status_code != 200:
        logger.info(
            "Serper thumbnail non-200 q=%r status=%s",
            cleaned, resp.status_code,
        )
        return None

    try:
        data = resp.json()
    except (json.JSONDecodeError, ValueError):
        return None

    images = data.get("images") or []
    for hit in images:
        url = hit.get("imageUrl")
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            return url
    return None


def _format_snippets(organic: list[dict], *, top: int = SERPER_TOP_N_FOR_PROMPT) -> str:
    """Render the top-N organic results as a compact text block for the
    synthesis prompt. Title + snippet only — link is dropped to keep the
    prompt short and reduce noise."""
    lines: list[str] = []
    for i, hit in enumerate(organic[:top], start=1):
        title = (hit.get("title") or "").strip()
        snippet = (hit.get("snippet") or "").strip()
        lines.append(f"{i}. {title}\n   {snippet}")
    return "\n".join(lines)


def _parse_synthesis_json(raw: str) -> dict:
    """Parse the strict JSON output from the synthesis call. Strips markdown
    code fences. Falls back to first-object regex if direct parse fails.
    Returns {} on unrecoverable parse failure."""
    if not raw:
        return {}
    cleaned = _FENCE_OPEN_RE.sub("", raw.strip())
    cleaned = _FENCE_CLOSE_RE.sub("", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = _FIRST_OBJ_RE.search(cleaned)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    logger.warning("Synthesis JSON parse failed: %r", raw[:300])
    return {}


async def resolve_via_serper(upc: str) -> dict | None:
    """Resolve a UPC via Serper SERP → Gemini synthesis.

    Returns ``{"name": str, "gemini_model": str | None}`` on success
    (matches the shape that ``ProductService._get_gemini_data`` returns), or
    None when Serper missed or the synthesis returned null. Never raises —
    callers can rely on None as the "fall back to grounded" signal.
    """
    organic = await _serper_fetch(upc)
    if not organic:
        await _record_serper_outcome("serper_miss")
        return None

    snippets = _format_snippets(organic)
    prompt = SYNTHESIS_PROMPT.format(upc=upc, snippets=snippets)

    try:
        raw = await gemini_generate(
            prompt,
            max_output_tokens=SYNTHESIS_MAX_TOKENS,
            grounded=False,
            thinking_budget=SYNTHESIS_THINKING_BUDGET,
        )
    except Exception:
        logger.warning(
            "Gemini synthesis call failed for UPC %s",
            upc, exc_info=True,
        )
        await _record_serper_outcome("synthesis_error")
        return None

    parsed = _parse_synthesis_json(raw)
    device_name = parsed.get("device_name")
    if not device_name:
        logger.info("Serper synthesis returned null device_name for UPC %s", upc)
        await _record_serper_outcome("synthesis_null")
        return None

    await _record_serper_outcome("success")
    return {
        "name": device_name,
        "gemini_model": parsed.get("model"),
        "image_url": _first_image_url(organic),
    }


# 3n: M14 misc-retailer slot. Serper Shopping (`/shopping`) is a separate code
# path from the `/search` UPC-resolve helpers above. Mirrors `_serper_fetch`'s
# posture (httpx async, soft-fail to None, warn-once on missing key) but does
# NOT feed Gemini synthesis — the response is structured enough to consume
# directly. `imageUrl` thumbnails are stripped server-side both to shrink the
# Redis payload (~800 KB → ~18 KB observed in v3 bench) and to sidestep the
# SerpApi-DMCA copyrighted-image angle.
_SERPER_SHOPPING_KEY_WARNED = False


async def _serper_shopping_fetch(
    query: str,
    *,
    gl: str = "us",
    hl: str = "en",
) -> list[dict] | None:
    """POST ``google.serper.dev/shopping``. Returns a list of items with
    ``imageUrl`` stripped, or None on failure.

    Each returned item carries: title, source, link, price, rating,
    ratingCount, productId, position. The caller is responsible for
    normalization, filtering against ``KNOWN_RETAILER_DOMAINS``, and
    capping. Soft-fails (logs + returns None) on missing
    ``SERPER_API_KEY``, 4xx/5xx, network error, or malformed JSON.

    No retries — the caller decides whether to fall back.
    """
    api_key = settings.SERPER_API_KEY
    if not api_key:
        global _SERPER_SHOPPING_KEY_WARNED
        if not _SERPER_SHOPPING_KEY_WARNED:
            logger.warning(
                "SERPER_API_KEY not configured — Serper Shopping disabled"
            )
            _SERPER_SHOPPING_KEY_WARNED = True
        return None

    body = {
        "q": query,
        "gl": gl,
        "hl": hl,
        "num": SERPER_SHOPPING_NUM_RESULTS,
    }
    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=SERPER_SHOPPING_TIMEOUT_SEC) as client:
            resp = await client.post(SERPER_SHOPPING_URL, json=body, headers=headers)
        elapsed_ms = (time.perf_counter() - t0) * 1000
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        logger.warning(
            "Serper Shopping fetch failed for query %r: %s: %r",
            query, type(exc).__name__, exc,
        )
        return None

    if resp.status_code != 200:
        logger.warning(
            "Serper Shopping non-200 for query %r: status=%s elapsed=%.0fms",
            query, resp.status_code, elapsed_ms,
        )
        return None

    try:
        data = resp.json()
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("Serper Shopping JSON parse failed for query %r: %r", query, exc)
        return None

    shopping = data.get("shopping")
    if shopping is None:
        logger.info(
            "Serper Shopping query %r: no 'shopping' field elapsed=%.0fms",
            query, elapsed_ms,
        )
        return []
    if not isinstance(shopping, list):
        logger.warning(
            "Serper Shopping query %r: unexpected 'shopping' type %s",
            query, type(shopping).__name__,
        )
        return None

    stripped: list[dict] = []
    for item in shopping:
        if not isinstance(item, dict):
            continue
        cleaned = {k: v for k, v in item.items() if k != "imageUrl"}
        stripped.append(cleaned)
    logger.info(
        "Serper Shopping query %r: items=%d elapsed=%.0fms",
        query, len(stripped), elapsed_ms,
    )
    return stripped
