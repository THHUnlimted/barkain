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
    payload = {
        "url": search_url,
        "formats": ["rawHtml"],
        "location": {"country": "US"},
    }
    headers = {
        "Authorization": f"Bearer {cfg.FIRECRAWL_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            resp = await client.post(_FIRECRAWL_ENDPOINT, json=payload, headers=headers)

        elapsed_ms = int((time.perf_counter() - start) * 1000)

        if resp.status_code >= 400:
            logger.warning(
                "firecrawl walmart HTTP %d: %s",
                resp.status_code,
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
            logger.warning("firecrawl walmart returned challenge page")
            return build_error_response(
                query=query,
                code="CHALLENGE",
                message="Firecrawl returned a PerimeterX challenge page (unexpected)",
                extraction_time_ms=elapsed_ms,
            )

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
            "firecrawl walmart success elapsed_ms=%d listings=%d",
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
        logger.exception("firecrawl walmart unexpected error")
        return build_error_response(
            query=query,
            code="ADAPTER_ERROR",
            message=f"{type(e).__name__}: {e}",
            extraction_time_ms=int((time.perf_counter() - start) * 1000),
        )
