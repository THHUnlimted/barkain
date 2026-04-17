"""Walmart Firecrawl adapter — managed-service fetch for the demo period.

Calls the Firecrawl REST API (`POST /v1/scrape` with `formats: ["rawHtml"]`)
to retrieve the Walmart search page. Firecrawl transparently handles proxies,
anti-bot, and rendering. We parse the returned raw HTML with the same
`__NEXT_DATA__` logic as the Decodo adapter.

Why this exists as a separate adapter: during the demo phase we don't want
to burn a paid Decodo bandwidth budget — Firecrawl's free tier is generous
(101K credits on the current account), rate limits are fine for demo load,
and the code path stays dormant-ready for the post-demo switch to Decodo.

Pricing (for reference):
- Firecrawl Standard $83/mo → ~$0.00125 per Walmart scrape
- Decodo 3 GB tier $11.25/mo → ~$0.000466 per Walmart scrape (2.7× cheaper)

Swap via: `WALMART_ADAPTER=decodo_http` in the environment.
See `docs/SCRAPING_AGENT_ARCHITECTURE.md` Appendix B and C.
"""

from __future__ import annotations

import logging
import time
from urllib.parse import quote_plus

import httpx

from app.config import Settings, settings as default_settings
from modules.m2_prices.adapters._walmart_parser import (
    build_error_response,
    build_success_response,
    detect_challenge,
    extract_listings,
)
from modules.m2_prices.schemas import ContainerResponse

logger = logging.getLogger("barkain.m2.walmart_firecrawl")

_SEARCH_URL_TEMPLATE = "https://www.walmart.com/search?q={query}"
_FIRECRAWL_ENDPOINT = "https://api.firecrawl.dev/v1/scrape"
_REQUEST_TIMEOUT = 45  # Firecrawl is slower than direct proxy — 7-30s typical

# PerimeterX retry budget — initial attempt + 2 retries on CHALLENGE only.
# Firecrawl normally absorbs anti-bot internally; when a challenge does slip
# through, a second call usually lands on a different upstream egress path
# and succeeds. Never retries on other failure modes (HTTP 4xx/5xx, timeout,
# network, empty body, parse error).
CHALLENGE_MAX_ATTEMPTS = 3


class FirecrawlNotConfiguredError(RuntimeError):
    """Raised when WALMART_ADAPTER=firecrawl but FIRECRAWL_API_KEY is missing."""


async def fetch_walmart(
    query: str,
    product_name: str | None = None,
    upc: str | None = None,
    max_listings: int = 10,
    cfg: Settings | None = None,
) -> ContainerResponse:
    """Fetch Walmart search results via Firecrawl's managed scraping API.

    Returns a `ContainerResponse` in every case — errors are captured in the
    response's `error` field, never raised.
    """
    cfg = cfg or default_settings
    start = time.perf_counter()

    if not cfg.FIRECRAWL_API_KEY:
        logger.error("Firecrawl walmart adapter: FIRECRAWL_API_KEY not set")
        return build_error_response(
            query=query,
            code="ADAPTER_NOT_CONFIGURED",
            message=(
                "Firecrawl API key missing. Set FIRECRAWL_API_KEY in the environment "
                "or switch WALMART_ADAPTER to a different mode."
            ),
        )

    search_url = _SEARCH_URL_TEMPLATE.format(query=quote_plus(query))
    # blockAds kills Meta Pixel, GA4, GTM, and ad-network subresource fetches
    # at Firecrawl's headless browser layer. Critical for cost: without it,
    # every rendered walmart.com page pulls ~70+ tracker hits.
    # onlyMainContent=False preserves the full document — we parse
    # __NEXT_DATA__, which sits outside article-extracted "main content".
    # waitFor=1500ms gives Next.js server-rendered hydration time before
    # rawHtml is snapshotted.
    #
    # DO NOT ADD: "proxy", "proxyServer", or any DECODO_* credential here.
    # Firecrawl's managed upstream pool handles Walmart; overlaying Decodo
    # would double-bill bandwidth. Regression-guarded in
    # test_walmart_firecrawl_adapter.py::test_firecrawl_payload_has_no_decodo_overlay.
    payload = {
        "url": search_url,
        "formats": ["rawHtml"],
        "location": {"country": "US"},
        "blockAds": True,
        "onlyMainContent": False,
        "waitFor": 1500,
    }
    headers = {
        "Authorization": f"Bearer {cfg.FIRECRAWL_API_KEY}",
        "Content-Type": "application/json",
    }

    attempts = 0
    last_challenge_elapsed_ms: int = 0

    while attempts < CHALLENGE_MAX_ATTEMPTS:
        attempts += 1
        try:
            async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
                resp = await client.post(_FIRECRAWL_ENDPOINT, json=payload, headers=headers)

            elapsed_ms = int((time.perf_counter() - start) * 1000)
            wire_bytes = len(resp.content or b"")

            # Structured per-request observability. NOTE: wire_bytes here is
            # the Firecrawl JSON response envelope, which is NOT the same as
            # the Decodo-upstream bandwidth Firecrawl's own browser consumes
            # (that's invisible to us). With `WALMART_ADAPTER=firecrawl`, any
            # bandwidth appearing on the Decodo dashboard MUST come from a
            # different adapter/container — see §C.11.
            logger.info(
                "adapter=walmart_firecrawl target=%s attempt=%d status=%s wire_bytes=%d elapsed_ms=%d",
                search_url,
                attempts,
                resp.status_code,
                wire_bytes,
                elapsed_ms,
            )

            if resp.status_code >= 400:
                logger.warning(
                    "firecrawl walmart HTTP %d on attempt %d: %s",
                    resp.status_code,
                    attempts,
                    resp.text[:500],
                )
                return build_error_response(
                    query=query,
                    code="FIRECRAWL_HTTP_ERROR",
                    message=f"Firecrawl returned HTTP {resp.status_code}",
                    extraction_time_ms=elapsed_ms,
                    details={"status_code": resp.status_code, "body": resp.text[:500]},
                )

            data = resp.json()
            if not data.get("success"):
                return build_error_response(
                    query=query,
                    code="FIRECRAWL_UNSUCCESSFUL",
                    message=data.get("error") or "Firecrawl reported success=false",
                    extraction_time_ms=elapsed_ms,
                    details={"response": data},
                )

            html = (data.get("data") or {}).get("rawHtml") or ""
            if not html:
                return build_error_response(
                    query=query,
                    code="FIRECRAWL_EMPTY_BODY",
                    message="Firecrawl returned success=true but rawHtml was empty",
                    extraction_time_ms=elapsed_ms,
                )

            if detect_challenge(html):
                last_challenge_elapsed_ms = elapsed_ms
                logger.warning(
                    "firecrawl walmart challenge detected on attempt %d/%d",
                    attempts,
                    CHALLENGE_MAX_ATTEMPTS,
                )
                continue  # retry — next Firecrawl call may use a different upstream path

            try:
                listings = extract_listings(html, max_listings=max_listings)
            except ValueError as e:
                return build_error_response(
                    query=query,
                    code="PARSE_ERROR",
                    message=str(e),
                    extraction_time_ms=elapsed_ms,
                )

            logger.info(
                "firecrawl walmart success attempt=%d elapsed_ms=%d listings=%d",
                attempts,
                elapsed_ms,
                len(listings),
            )

            return build_success_response(
                query=query,
                listings=listings,
                extraction_time_ms=elapsed_ms,
                source_url=search_url,
                extraction_method="firecrawl_next_data",
            )

        except httpx.TimeoutException:
            return build_error_response(
                query=query,
                code="TIMEOUT",
                message=f"Firecrawl request timed out after {_REQUEST_TIMEOUT}s",
                extraction_time_ms=int((time.perf_counter() - start) * 1000),
            )

        except httpx.HTTPError as e:
            return build_error_response(
                query=query,
                code="NETWORK_ERROR",
                message=f"{type(e).__name__}: {e}",
                extraction_time_ms=int((time.perf_counter() - start) * 1000),
            )

        except Exception as e:  # pragma: no cover — defensive safety net
            logger.exception("firecrawl walmart unexpected error on attempt %d", attempts)
            return build_error_response(
                query=query,
                code="ADAPTER_ERROR",
                message=f"{type(e).__name__}: {e}",
                extraction_time_ms=int((time.perf_counter() - start) * 1000),
            )

    # Exhausted — all CHALLENGE_MAX_ATTEMPTS attempts came back as challenge pages
    return build_error_response(
        query=query,
        code="CHALLENGE",
        message=(
            f"Firecrawl returned a PerimeterX challenge page on all "
            f"{CHALLENGE_MAX_ATTEMPTS} attempts"
        ),
        extraction_time_ms=last_challenge_elapsed_ms,
        details={"total_attempts": attempts},
    )
