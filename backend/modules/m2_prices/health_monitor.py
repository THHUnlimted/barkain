"""Health monitoring service for retailer scraper containers.

Polls /health on each container, tracks status in retailer_health table,
and provides health status to the API and Watchdog.
"""

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core_models import RetailerHealth
from modules.m2_prices.container_client import ContainerClient

logger = logging.getLogger("barkain.health")

DEGRADED_THRESHOLD = 3  # consecutive failures before marking degraded


class HealthMonitorService:
    """Monitors retailer container health and tracks status in the database."""

    def __init__(
        self,
        db: AsyncSession,
        container_client: ContainerClient | None = None,
    ):
        self.db = db
        self.container_client = container_client or ContainerClient()

    async def check_all(self) -> dict[str, str]:
        """Poll all containers in parallel and update retailer_health.

        Returns:
            Dict mapping retailer_id to status string.
        """
        retailer_ids = list(settings.CONTAINER_PORTS.keys())
        tasks = [self.check_one(rid) for rid in retailer_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        status_map = {}
        for rid, result in zip(retailer_ids, results):
            if isinstance(result, Exception):
                logger.error("Health check errored for %s: %s", rid, result)
                status_map[rid] = "error"
            else:
                status_map[rid] = result

        return status_map

    async def check_one(self, retailer_id: str) -> str:
        """Poll one container and update its retailer_health row.

        Returns:
            Current health status string.
        """
        health_resp = await self.container_client.health_check(retailer_id)
        is_healthy = health_resp.status == "healthy"
        await self._update_health_record(retailer_id, is_healthy, health_resp)
        return health_resp.status

    async def get_all_health(self) -> list[dict]:
        """Read all retailer_health rows and return as list of dicts."""
        result = await self.db.execute(
            select(RetailerHealth).order_by(RetailerHealth.retailer_id)
        )
        rows = result.scalars().all()
        return [
            {
                "retailer_id": row.retailer_id,
                "status": row.status,
                "consecutive_failures": row.consecutive_failures,
                "last_successful_extract": (
                    row.last_successful_extract.isoformat()
                    if row.last_successful_extract
                    else None
                ),
                "last_failed_extract": (
                    row.last_failed_extract.isoformat()
                    if row.last_failed_extract
                    else None
                ),
                "heal_attempts": row.heal_attempts,
                "script_version": row.script_version,
                "updated_at": row.updated_at.isoformat(),
            }
            for row in rows
        ]

    async def _update_health_record(
        self,
        retailer_id: str,
        is_healthy: bool,
        health_resp,
    ) -> None:
        """Upsert retailer_health row based on check result.

        Status transitions:
            healthy → degraded (after DEGRADED_THRESHOLD consecutive failures)
            degraded → healthy (on success)
            healing → healthy (on success after heal)
            healing → disabled (after max_heal_attempts exhausted, handled by Watchdog)
        """
        now = datetime.now(UTC)

        if is_healthy:
            stmt = pg_insert(RetailerHealth).values(
                retailer_id=retailer_id,
                status="healthy",
                consecutive_failures=0,
                last_successful_extract=now,
                script_version=health_resp.script_version,
                updated_at=now,
            ).on_conflict_do_update(
                index_elements=["retailer_id"],
                set_={
                    "status": "healthy",
                    "consecutive_failures": 0,
                    "last_successful_extract": now,
                    "script_version": health_resp.script_version,
                    "updated_at": now,
                },
            )
        else:
            # First upsert to increment failures
            stmt = pg_insert(RetailerHealth).values(
                retailer_id=retailer_id,
                status="degraded",
                consecutive_failures=1,
                last_failed_extract=now,
                script_version=health_resp.script_version,
                updated_at=now,
            ).on_conflict_do_update(
                index_elements=["retailer_id"],
                set_={
                    "consecutive_failures": RetailerHealth.consecutive_failures + 1,
                    "last_failed_extract": now,
                    "script_version": health_resp.script_version,
                    "updated_at": now,
                },
            )
            await self.db.execute(stmt)

            # Update status based on threshold
            await self.db.execute(
                text("""
                    UPDATE retailer_health
                    SET status = CASE
                        WHEN consecutive_failures >= :threshold
                             AND status NOT IN ('healing', 'disabled')
                        THEN 'degraded'
                        ELSE status
                    END
                    WHERE retailer_id = :rid
                """),
                {"threshold": DEGRADED_THRESHOLD, "rid": retailer_id},
            )
            await self.db.flush()
            return

        await self.db.execute(stmt)
        await self.db.flush()
