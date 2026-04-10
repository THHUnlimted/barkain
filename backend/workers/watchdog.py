"""Watchdog Supervisor Agent — nightly health checks and self-healing for retailer containers.

Responsibilities:
1. Test extraction against each container using a known product query.
2. Classify result: success, transient_failure, selector_drift, blocked.
3. For transient failures: retry with backoff.
4. For selector_drift: trigger self-healing via Claude Opus.
5. For blocked: escalate to developer.
6. Record all events in watchdog_events table.

Cost control: Opus calls (~$0.05-$0.20 per heal) only trigger on confirmed
selector_drift, never on transient failures. Max 3 heal attempts per retailer.
"""

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import redis.asyncio as aioredis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ai.abstraction import claude_generate_json_with_usage
from ai.prompts.watchdog_heal import (
    WATCHDOG_HEAL_SYSTEM_INSTRUCTION,
    build_watchdog_heal_prompt,
)
from app.config import settings
from app.core_models import RetailerHealth, WatchdogEvent
from modules.m2_prices.container_client import ContainerClient
from modules.m2_prices.health_monitor import HealthMonitorService

logger = logging.getLogger("barkain.watchdog")

CONTAINERS_ROOT = Path(__file__).resolve().parents[1] / "containers"
MAX_TRANSIENT_RETRIES = 3
TRANSIENT_RETRY_DELAY = 5.0  # seconds base delay


class WatchdogSupervisor:
    """Orchestrates nightly health checks and self-healing for retailer containers."""

    def __init__(
        self,
        db: AsyncSession,
        redis: aioredis.Redis | None = None,
        container_client: ContainerClient | None = None,
        dry_run: bool = False,
    ):
        self.db = db
        self.redis = redis
        self.container_client = container_client or ContainerClient()
        self.health_monitor = HealthMonitorService(db, self.container_client)
        self.dry_run = dry_run

    async def check_all_retailers(self) -> list[dict]:
        """Run test extraction for every retailer, classify, and act.

        Returns:
            List of result dicts, one per retailer.
        """
        retailer_ids = list(settings.CONTAINER_PORTS.keys())
        results = []
        for rid in retailer_ids:
            result = await self.check_retailer(rid)
            results.append(result)
        return results

    async def check_retailer(self, retailer_id: str) -> dict:
        """Test extraction on one retailer, classify result, take action.

        Returns:
            Dict with retailer_id, diagnosis, action, success, and details.
        """
        logger.info("Watchdog checking retailer: %s", retailer_id)

        # Run test extraction
        test_query = settings.WATCHDOG_TEST_QUERY
        response = await self.container_client.extract(
            retailer_id=retailer_id,
            query=test_query,
            max_listings=3,
        )

        # Classify
        diagnosis = self._classify(response)
        logger.info(
            "Retailer %s diagnosis: %s", retailer_id, diagnosis,
        )

        # Act
        action_result = await self._act(retailer_id, diagnosis, response)

        # Log event (unless dry run)
        if not self.dry_run:
            await self._log_event(
                retailer_id=retailer_id,
                event_type="nightly_check",
                diagnosis=diagnosis,
                action_taken=action_result.get("action", "none"),
                success=action_result.get("success", False),
                llm_model=action_result.get("llm_model"),
                llm_tokens_used=action_result.get("llm_tokens_used"),
                old_selectors=action_result.get("old_selectors"),
                new_selectors=action_result.get("new_selectors"),
                error_details=action_result.get("error_details"),
            )

        return {
            "retailer_id": retailer_id,
            "diagnosis": diagnosis,
            **action_result,
        }

    def _classify(self, response) -> str:
        """Classify extraction result.

        Returns one of: "success", "transient", "selector_drift", "blocked".
        """
        # Success: has listings with valid prices
        if response.listings and any(listing.price > 0 for listing in response.listings):
            return "success"

        # Blocked: bot detection
        if response.metadata and response.metadata.bot_detected:
            return "blocked"

        # Check error codes
        if response.error:
            code = response.error.code
            if code in ("TIMEOUT", "CONNECTION_FAILED"):
                return "transient"
            if code in ("PARSE_ERROR", "EXTRACTION_FAILED", "SCRIPT_NOT_FOUND"):
                return "selector_drift"

        # Empty listings without explicit error = likely selector drift
        return "selector_drift"

    async def _act(self, retailer_id: str, diagnosis: str, response) -> dict:
        """Take action based on diagnosis."""
        if diagnosis == "success":
            if not self.dry_run:
                await self.health_monitor.check_one(retailer_id)
            return {"action": "none", "success": True}

        if diagnosis == "transient":
            return await self._handle_transient(retailer_id)

        if diagnosis == "blocked":
            return await self._handle_blocked(retailer_id, response)

        if diagnosis == "selector_drift":
            return await self._handle_selector_drift(retailer_id, response)

        return {"action": "unknown", "success": False}

    async def _handle_transient(self, retailer_id: str) -> dict:
        """Retry with backoff for transient failures."""
        for attempt in range(MAX_TRANSIENT_RETRIES):
            delay = TRANSIENT_RETRY_DELAY * (2**attempt)
            logger.info(
                "Transient retry %d/%d for %s (delay %.1fs)",
                attempt + 1, MAX_TRANSIENT_RETRIES, retailer_id, delay,
            )
            await asyncio.sleep(delay)

            response = await self.container_client.extract(
                retailer_id=retailer_id,
                query=settings.WATCHDOG_TEST_QUERY,
                max_listings=3,
            )

            if response.listings and any(listing.price > 0 for listing in response.listings):
                logger.info("Transient resolved for %s on retry %d", retailer_id, attempt + 1)
                if not self.dry_run:
                    await self.health_monitor.check_one(retailer_id)
                return {"action": "retry_resolved", "success": True}

        logger.warning("Transient retries exhausted for %s", retailer_id)
        return {"action": "retry_exhausted", "success": False}

    async def _handle_blocked(self, retailer_id: str, response) -> dict:
        """Escalate blocked retailers — do not attempt self-heal."""
        logger.warning("Retailer %s is blocked — escalating", retailer_id)
        await self._escalate(retailer_id, "Blocked by anti-bot system")

        if not self.dry_run:
            await self._update_health_status(retailer_id, "degraded")

        error_msg = response.error.message if response.error else "Bot detected"
        return {
            "action": "escalate_blocked",
            "success": False,
            "error_details": error_msg,
        }

    async def _handle_selector_drift(self, retailer_id: str, response) -> dict:
        """Attempt self-healing via Claude Opus for selector drift."""
        # Check heal attempts
        health = await self._get_health_record(retailer_id)
        current_attempts = health.heal_attempts if health else 0
        max_attempts = health.max_heal_attempts if health else 3

        if current_attempts >= max_attempts:
            logger.warning(
                "Max heal attempts (%d) reached for %s — escalating",
                max_attempts, retailer_id,
            )
            await self._escalate(retailer_id, f"Max heal attempts ({max_attempts}) reached")
            return {"action": "escalate_max_heals", "success": False}

        if self.dry_run:
            return {"action": "would_heal", "success": False}

        # Update status to healing
        await self._update_health_status(retailer_id, "healing")

        # Read current extract.js
        extract_js_path = CONTAINERS_ROOT / retailer_id / "extract.js"
        config_json_path = CONTAINERS_ROOT / retailer_id / "config.json"

        if not extract_js_path.exists():
            return {
                "action": "heal_failed",
                "success": False,
                "error_details": f"extract.js not found at {extract_js_path}",
            }

        current_extract_js = extract_js_path.read_text()
        config_json = config_json_path.read_text() if config_json_path.exists() else "{}"

        # Get error details for the prompt
        error_details = ""
        if response.error:
            error_details = f"{response.error.code}: {response.error.message}"
            if response.error.details:
                error_details += f"\nDetails: {json.dumps(response.error.details)[:2000]}"

        # Call Claude Opus for healing
        try:
            heal_prompt = build_watchdog_heal_prompt(
                retailer_id=retailer_id,
                current_extract_js=current_extract_js,
                page_html=error_details,  # Using error details as context
                error_details=error_details,
                config_json=config_json,
            )

            result, tokens = await claude_generate_json_with_usage(
                heal_prompt,
                model="claude-opus-4-0",
                system_instruction=WATCHDOG_HEAL_SYSTEM_INSTRUCTION,
                max_output_tokens=8192,
            )

            new_extract_js = result.get("extract_js", "")
            changes = result.get("changes", [])
            confidence = result.get("confidence", 0)

            if not new_extract_js:
                await self._increment_heal_attempts(retailer_id)
                return {
                    "action": "heal_failed",
                    "success": False,
                    "llm_model": "claude-opus-4-0",
                    "llm_tokens_used": tokens,
                    "error_details": "Opus returned empty extract_js",
                }

            # Write healed script to staging directory
            staging_dir = CONTAINERS_ROOT / retailer_id / "staging"
            staging_dir.mkdir(exist_ok=True)
            staging_path = staging_dir / "extract.js"
            staging_path.write_text(new_extract_js)

            await self._increment_heal_attempts(retailer_id)

            logger.info(
                "Heal staged for %s: confidence=%.2f, changes=%s, tokens=%d",
                retailer_id, confidence, changes, tokens,
            )

            return {
                "action": "heal_staged",
                "success": True,
                "llm_model": "claude-opus-4-0",
                "llm_tokens_used": tokens,
                "old_selectors": {"extract_js_hash": hash(current_extract_js)},
                "new_selectors": {
                    "changes": changes,
                    "confidence": confidence,
                    "staging_path": str(staging_path),
                },
            }

        except Exception as exc:
            logger.error("Heal failed for %s: %s", retailer_id, exc, exc_info=True)
            await self._increment_heal_attempts(retailer_id)
            return {
                "action": "heal_error",
                "success": False,
                "error_details": str(exc)[:500],
            }

    async def _get_health_record(self, retailer_id: str) -> RetailerHealth | None:
        """Load retailer_health row from DB."""
        result = await self.db.execute(
            select(RetailerHealth).where(RetailerHealth.retailer_id == retailer_id)
        )
        return result.scalar_one_or_none()

    async def _update_health_status(self, retailer_id: str, status: str) -> None:
        """Update the status field of a retailer_health row."""
        await self.db.execute(
            update(RetailerHealth)
            .where(RetailerHealth.retailer_id == retailer_id)
            .values(status=status, updated_at=datetime.now(UTC))
        )
        await self.db.flush()

    async def _increment_heal_attempts(self, retailer_id: str) -> None:
        """Increment heal_attempts counter for a retailer."""
        await self.db.execute(
            update(RetailerHealth)
            .where(RetailerHealth.retailer_id == retailer_id)
            .values(
                heal_attempts=RetailerHealth.heal_attempts + 1,
                last_healed_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        await self.db.flush()

    async def _log_event(
        self,
        retailer_id: str,
        event_type: str,
        diagnosis: str,
        action_taken: str,
        success: bool,
        llm_model: str | None = None,
        llm_tokens_used: int | None = None,
        old_selectors: dict | None = None,
        new_selectors: dict | None = None,
        error_details: str | None = None,
    ) -> None:
        """Insert a WatchdogEvent record."""
        event = WatchdogEvent(
            retailer_id=retailer_id,
            event_type=event_type,
            diagnosis=diagnosis,
            action_taken=action_taken,
            success=success,
            llm_model=llm_model,
            llm_tokens_used=llm_tokens_used,
            old_selectors=old_selectors,
            new_selectors=new_selectors,
            error_details=error_details,
        )
        self.db.add(event)
        await self.db.flush()

    async def _escalate(self, retailer_id: str, reason: str) -> None:
        """Escalate to developer. Logs critical + optional Slack webhook."""
        logger.critical(
            "WATCHDOG ESCALATION — retailer=%s reason=%s", retailer_id, reason,
        )

        webhook_url = settings.WATCHDOG_SLACK_WEBHOOK
        if webhook_url:
            try:
                import httpx

                payload = {
                    "text": f":rotating_light: Watchdog escalation: *{retailer_id}* — {reason}",
                }
                async with httpx.AsyncClient(timeout=10) as client:
                    await client.post(webhook_url, json=payload)
            except Exception as exc:
                logger.warning("Slack webhook failed: %s", exc)
