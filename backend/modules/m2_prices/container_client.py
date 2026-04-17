"""Container client — dispatches extraction requests to retailer scraper containers.

Each retailer runs in its own Docker container exposing POST /extract and GET /health.
This client handles parallel dispatch, timeout/retry, and partial failure tolerance.

Walmart routing: because most datacenter IPs are blocked by PerimeterX and
Chromium-in-Docker is JS-fingerprinted even from residential IPs, walmart is
routed through a pluggable HTTP adapter instead of the container path by
default. Selected via `WALMART_ADAPTER` env var — see
`modules/m2_prices/adapters/` and `docs/SCRAPING_AGENT_ARCHITECTURE.md`
Appendices A–C.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

import httpx

from app.config import Settings, settings
from modules.m2_prices.schemas import (
    ContainerError,
    ContainerExtractRequest,
    ContainerHealthResponse,
    ContainerResponse,
)

logger = logging.getLogger("barkain.m2")


# Signature of a per-retailer HTTP adapter.
AdapterFn = Callable[..., Awaitable[ContainerResponse]]


def _resolve_walmart_adapter(mode: str) -> AdapterFn | None:
    """Return the walmart adapter function for `mode`, or None for the container path.

    Imports are deferred so unused adapters don't load their httpx clients at
    startup and tests can patch the module without side effects.
    """
    if mode == "firecrawl":
        from modules.m2_prices.adapters.walmart_firecrawl import fetch_walmart
        return fetch_walmart
    if mode == "decodo_http":
        from modules.m2_prices.adapters.walmart_http import fetch_walmart
        return fetch_walmart
    # "container" (default) or any unknown value → fall through to container path
    return None


def _resolve_ebay_adapter(cfg: Settings) -> AdapterFn | None:
    """Return the eBay Browse API adapter when credentials are set, else None.

    Unlike Walmart's explicit mode switch, eBay auto-prefers the API path
    whenever ``EBAY_APP_ID`` + ``EBAY_CERT_ID`` are both populated — the
    container leg is strictly a fallback (selector drift makes it worse than
    the API on every dimension). When creds are missing we return None so
    ``_extract_one`` falls through to the container path.
    """
    from modules.m2_prices.adapters.ebay_browse_api import is_configured
    if not is_configured(cfg):
        return None
    from modules.m2_prices.adapters.ebay_browse_api import fetch_ebay
    return fetch_ebay


class ContainerClient:
    """HTTP client for communicating with retailer scraper containers."""

    def __init__(self, config: Settings | None = None) -> None:
        cfg = config or settings
        self._cfg = cfg
        self.url_pattern = cfg.CONTAINER_URL_PATTERN
        self.timeout = cfg.CONTAINER_TIMEOUT_SECONDS
        self.retry_count = cfg.CONTAINER_RETRY_COUNT
        self.ports = cfg.CONTAINER_PORTS
        self.walmart_adapter_mode = cfg.WALMART_ADAPTER

    def _get_container_url(self, retailer_id: str) -> str:
        """Resolve retailer_id to its container URL."""
        port = self.ports.get(retailer_id)
        if port is None:
            raise ValueError(f"Unknown retailer_id: {retailer_id}")
        return self.url_pattern.format(port=port)

    async def extract(
        self,
        retailer_id: str,
        query: str,
        product_name: str | None = None,
        upc: str | None = None,
        max_listings: int = 10,
    ) -> ContainerResponse:
        """Send a POST /extract request to a single retailer container.

        Returns a ContainerResponse in all cases — errors are captured in the
        response's error field, never raised.
        """
        url = self._get_container_url(retailer_id)
        payload = ContainerExtractRequest(
            query=query,
            product_name=product_name,
            upc=upc,
            max_listings=max_listings,
        ).model_dump()

        last_error: str | None = None

        for attempt in range(1 + self.retry_count):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(f"{url}/extract", json=payload)

                if resp.status_code >= 400:
                    logger.warning(
                        "Container %s returned HTTP %d", retailer_id, resp.status_code
                    )
                    return ContainerResponse(
                        retailer_id=retailer_id,
                        query=query,
                        error=ContainerError(
                            code="HTTP_ERROR",
                            message=f"Container returned HTTP {resp.status_code}",
                            details={"status_code": resp.status_code},
                        ),
                    )

                data = resp.json()
                return ContainerResponse(**data)

            except httpx.ConnectError as e:
                last_error = f"{type(e).__name__}: {e}"
                if "Connection refused" in str(e) or "ConnectRefusedError" in str(e):
                    logger.debug(
                        "Container %s not running (attempt %d/%d)",
                        retailer_id,
                        attempt + 1,
                        1 + self.retry_count,
                    )
                else:
                    logger.warning(
                        "Container %s attempt %d/%d connect error: %s",
                        retailer_id,
                        attempt + 1,
                        1 + self.retry_count,
                        last_error,
                    )
                continue

            except httpx.TimeoutException as e:
                last_error = f"{type(e).__name__}: {e}"
                logger.warning(
                    "Container %s attempt %d/%d timed out: %s",
                    retailer_id,
                    attempt + 1,
                    1 + self.retry_count,
                    last_error,
                )
                continue

            except Exception as e:
                logger.error("Container %s unexpected error: %s", retailer_id, e)
                return ContainerResponse(
                    retailer_id=retailer_id,
                    query=query,
                    error=ContainerError(
                        code="CLIENT_ERROR",
                        message=str(e),
                    ),
                )

        # All retries exhausted
        return ContainerResponse(
            retailer_id=retailer_id,
            query=query,
            error=ContainerError(
                code="CONNECTION_FAILED",
                message=f"Failed after {1 + self.retry_count} attempts: {last_error}",
            ),
        )

    async def _extract_one(
        self,
        retailer_id: str,
        query: str,
        product_name: str | None,
        upc: str | None,
        max_listings: int,
    ) -> ContainerResponse:
        """Route a single retailer to its adapter or the default container path.

        Walmart may use a pluggable HTTP adapter (Firecrawl / Decodo) instead
        of the browser container. Other retailers always use the container path.
        """
        if retailer_id == "walmart":
            adapter = _resolve_walmart_adapter(self.walmart_adapter_mode)
            if adapter is not None:
                logger.debug(
                    "routing walmart via adapter mode=%s", self.walmart_adapter_mode
                )
                return await adapter(
                    query=query,
                    product_name=product_name,
                    upc=upc,
                    max_listings=max_listings,
                    cfg=self._cfg,
                )
        if retailer_id in ("ebay_new", "ebay_used"):
            adapter = _resolve_ebay_adapter(self._cfg)
            if adapter is not None:
                logger.debug("routing %s via ebay_browse_api", retailer_id)
                return await adapter(
                    retailer_id=retailer_id,
                    query=query,
                    product_name=product_name,
                    upc=upc,
                    max_listings=max_listings,
                    cfg=self._cfg,
                )
        return await self.extract(retailer_id, query, product_name, upc, max_listings)

    async def extract_all(
        self,
        query: str,
        product_name: str | None = None,
        upc: str | None = None,
        retailer_ids: list[str] | None = None,
        max_listings: int = 10,
    ) -> dict[str, ContainerResponse]:
        """Dispatch extraction requests to multiple containers in parallel.

        Partial failures are tolerated — successful results are returned
        alongside error responses. Walmart may be routed through an HTTP
        adapter (see `_extract_one`).
        """
        # Phase 2: Watchdog circuit-breaker will skip unhealthy containers (D10)
        ids = retailer_ids or list(self.ports.keys())

        tasks = [
            self._extract_one(rid, query, product_name, upc, max_listings)
            for rid in ids
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        output: dict[str, ContainerResponse] = {}
        for rid, result in zip(ids, results):
            if isinstance(result, Exception):
                logger.error("Container %s raised exception: %s", rid, result)
                output[rid] = ContainerResponse(
                    retailer_id=rid,
                    query=query,
                    error=ContainerError(
                        code="GATHER_ERROR",
                        message=str(result),
                    ),
                )
            else:
                output[rid] = result

        return output

    async def health_check(self, retailer_id: str) -> ContainerHealthResponse:
        """Ping a container's GET /health endpoint."""
        url = self._get_container_url(retailer_id)

        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{url}/health")
                resp.raise_for_status()
                data = resp.json()
                return ContainerHealthResponse(**data)

        except Exception as e:
            logger.warning("Health check failed for %s: %s", retailer_id, e)
            return ContainerHealthResponse(
                status="unhealthy",
                retailer_id=retailer_id,
                script_version="unknown",
                chromium_ready=False,
            )
