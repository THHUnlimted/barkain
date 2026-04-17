"""Walmart HTTP adapter — direct fetch via Decodo US residential proxy.

This adapter replaces the browser-container path for Walmart with a plain
`httpx` request through a residential proxy, then parses the server-rendered
`__NEXT_DATA__` JSON blob for the product list.

Why this exists: Walmart aggressively fingerprints headless Chromium via
PerimeterX's client-side JS, so the browser-container approach fails from
most environments. But the full product catalog is server-rendered into the
HTML *before* that JS runs — if we pass the layer-1 IP/header check we never
need to execute JS at all. A US residential IP from Decodo's pool passes that
check reliably (5/5 in 2026-04-10 probe, see `docs/SCRAPING_AGENT_ARCHITECTURE.md`
Appendix C).

Cost: ~121 KB wire bytes per scrape → ~8,000 scrapes per GB → $0.000466/scrape
at Decodo's $3.75/GB (3 GB tier). ~2.7× cheaper per scrape than Firecrawl.
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

logger = logging.getLogger("barkain.m2.walmart_http")

_SEARCH_URL_TEMPLATE = "https://www.walmart.com/search?q={query}"
_REQUEST_TIMEOUT = 30  # seconds

# PerimeterX retry budget — initial attempt + 2 retries on CHALLENGE only.
# Retries rotate the Decodo residential IP, so a different egress often gets
# through. Never retries on other failure modes.
CHALLENGE_MAX_ATTEMPTS = 3

# Chrome 132 header set — matches the fingerprint that passed in our AWS
# residential-proxy probe (docs/SCRAPING_AGENT_ARCHITECTURE.md Appendix C.1).
_CHROME_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/132.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Ch-Ua": '"Google Chrome";v="132", "Chromium";v="132", "Not_A Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


class DecodoNotConfiguredError(RuntimeError):
    """Raised at startup when WALMART_ADAPTER=decodo_http but proxy creds are missing."""


def _build_proxy_url(cfg: Settings) -> str:
    """Assemble the Decodo proxy URL from env settings.

    Username is prefixed with `user-` and suffixed with `-country-us` to geo-target
    US IPs (verified necessary in the 2026-04-10 probe — base pool landed in Peru).
    URL-encodes the password to handle special characters like `=` or `@`.
    """
    if not (cfg.DECODO_PROXY_USER and cfg.DECODO_PROXY_PASS and cfg.DECODO_PROXY_HOST):
        raise DecodoNotConfiguredError(
            "Decodo proxy not configured. Set DECODO_PROXY_USER, DECODO_PROXY_PASS, "
            "DECODO_PROXY_HOST in the environment or switch WALMART_ADAPTER to a "
            "different mode."
        )

    user = cfg.DECODO_PROXY_USER
    if not user.startswith("user-"):
        user = f"user-{user}"
    if "country-" not in user:
        user = f"{user}-country-us"

    # httpx accepts raw user:pass in the URL; quote_plus on the password so
    # characters like '=', '@', or ':' don't break URL parsing.
    encoded_pass = quote_plus(cfg.DECODO_PROXY_PASS)
    return f"http://{user}:{encoded_pass}@{cfg.DECODO_PROXY_HOST}"


async def fetch_walmart(
    query: str,
    product_name: str | None = None,
    upc: str | None = None,
    max_listings: int = 10,
    cfg: Settings | None = None,
) -> ContainerResponse:
    """Fetch Walmart search results through the Decodo residential proxy.

    Returns a `ContainerResponse` in every case — errors are captured in the
    response's `error` field, never raised. This mirrors the container client's
    contract so callers can treat both paths interchangeably.
    """
    cfg = cfg or default_settings
    start = time.perf_counter()
    search_url = _SEARCH_URL_TEMPLATE.format(query=quote_plus(query))

    try:
        proxy_url = _build_proxy_url(cfg)
    except DecodoNotConfiguredError as e:
        logger.error("Walmart HTTP adapter misconfigured: %s", e)
        return build_error_response(
            query=query,
            code="ADAPTER_NOT_CONFIGURED",
            message=str(e),
        )

    # Retry budget is CHALLENGE-only. PerimeterX hits a rotating residential IP
    # pool — the next attempt draws a different egress IP, so a clean retry is
    # often enough to land on a non-challenged response. Every other failure
    # mode (HTTP_ERROR, PARSE_ERROR, TIMEOUT, NETWORK_ERROR, NO_LISTINGS)
    # fails fast: no amount of retrying helps those.
    attempts = 0
    last_error: tuple[str, str, dict] | None = None

    while attempts < CHALLENGE_MAX_ATTEMPTS:
        attempts += 1
        try:
            async with httpx.AsyncClient(
                proxy=proxy_url,
                timeout=_REQUEST_TIMEOUT,
                follow_redirects=True,
                max_redirects=3,
            ) as client:
                resp = await client.get(search_url, headers=_CHROME_HEADERS)

            elapsed_ms = int((time.perf_counter() - start) * 1000)
            wire_bytes = len(resp.content or b"")

            # Log bandwidth per request for cost observability
            logger.info(
                "walmart_http attempt=%d status=%s wire_bytes=%d elapsed_ms=%d",
                attempts,
                resp.status_code,
                wire_bytes,
                elapsed_ms,
            )

            if resp.status_code >= 400:
                last_error = (
                    "HTTP_ERROR",
                    f"Walmart returned HTTP {resp.status_code}",
                    {"status_code": resp.status_code, "attempt": attempts},
                )
                break  # fail fast — upstream error won't fix itself

            html = resp.text

            if detect_challenge(html):
                last_error = (
                    "CHALLENGE",
                    "PerimeterX challenge page detected in Walmart response",
                    {"attempt": attempts, "wire_bytes": wire_bytes},
                )
                logger.warning(
                    "walmart_http challenge detected on attempt %d/%d (wire=%d)",
                    attempts,
                    CHALLENGE_MAX_ATTEMPTS,
                    wire_bytes,
                )
                continue  # retry — rotating residential IP may succeed next time

            try:
                listings = extract_listings(html, max_listings=max_listings)
            except ValueError as e:
                last_error = ("PARSE_ERROR", str(e), {"attempt": attempts})
                logger.warning("walmart_http parse failed: %s", e)
                break  # fail fast — page shape drift needs code, not retry

            if not listings:
                last_error = (
                    "NO_LISTINGS",
                    "Walmart returned a valid page with zero parseable listings",
                    {"attempt": attempts},
                )
                break  # empty result is a real answer, not a failure to retry

            return build_success_response(
                query=query,
                listings=listings,
                extraction_time_ms=elapsed_ms,
                source_url=search_url,
                extraction_method="decodo_http_next_data",
            )

        except httpx.TimeoutException as e:
            last_error = ("TIMEOUT", f"Request timed out: {e}", {"attempt": attempts})
            logger.warning("walmart_http timeout on attempt %d", attempts)
            break

        except httpx.HTTPError as e:
            last_error = (
                "NETWORK_ERROR",
                f"{type(e).__name__}: {e}",
                {"attempt": attempts},
            )
            logger.warning("walmart_http network error on attempt %d: %s", attempts, e)
            break

        except Exception as e:  # pragma: no cover — defensive safety net
            logger.exception("walmart_http unexpected error on attempt %d", attempts)
            return build_error_response(
                query=query,
                code="ADAPTER_ERROR",
                message=f"{type(e).__name__}: {e}",
                extraction_time_ms=int((time.perf_counter() - start) * 1000),
            )

    # All attempts exhausted
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    code, message, details = last_error or ("UNKNOWN", "Unknown failure", {})
    return build_error_response(
        query=query,
        code=code,
        message=message,
        extraction_time_ms=elapsed_ms,
        details={**details, "total_attempts": attempts},
    )
