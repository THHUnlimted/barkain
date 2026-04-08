"""Container client — dispatches extraction requests to retailer scraper containers.

Each retailer runs in its own Docker container exposing POST /extract and GET /health.
This client handles parallel dispatch, timeout/retry, and partial failure tolerance.
"""

import asyncio
import logging

import httpx

from app.config import Settings, settings
from modules.m2_prices.schemas import (
    ContainerError,
    ContainerExtractRequest,
    ContainerHealthResponse,
    ContainerResponse,
)

logger = logging.getLogger("barkain.m2")


class ContainerClient:
    """HTTP client for communicating with retailer scraper containers."""

    def __init__(self, config: Settings | None = None) -> None:
        cfg = config or settings
        self.url_pattern = cfg.CONTAINER_URL_PATTERN
        self.timeout = cfg.CONTAINER_TIMEOUT_SECONDS
        self.retry_count = cfg.CONTAINER_RETRY_COUNT
        self.ports = cfg.CONTAINER_PORTS

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

            except (httpx.TimeoutException, httpx.ConnectError) as e:
                last_error = f"{type(e).__name__}: {e}"
                logger.warning(
                    "Container %s attempt %d/%d failed: %s",
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
        alongside error responses.
        """
        # Phase 2: Watchdog circuit-breaker will skip unhealthy containers (D10)
        ids = retailer_ids or list(self.ports.keys())

        tasks = [
            self.extract(rid, query, product_name, upc, max_listings) for rid in ids
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
