"""AWS Lambda entry point for the portal scrape worker (Step 3g).

Wraps ``backend/workers/portal_rates.py`` — DO NOT duplicate parser logic.
This module exists only to bind the worker to Lambda's invocation contract
and pipe the run result into m13's alerting.

Cron: EventBridge rule fires every 6 hours (``cron(0 */6 * * ? *)``).
At ~30 seconds per invocation, 120 invocations/month sit comfortably in
Lambda's free tier (vs. $5/month for EC2 or Fargate to do the same work).

DB connection lifecycle: a fresh ``AsyncEngine`` is created and disposed
per invocation. Acceptable at one invocation per 6h. If the cadence ever
moves below 1/min, switch to RDS Proxy (or a persistent connection pooler
in front of whatever DB host we're using) to avoid connection storms.
"""

import asyncio
import logging
import os

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# Path-juggling: the Lambda container image bundles the backend/ tree at
# /var/task/backend, so absolute imports resolve once we add it to sys.path.
import sys
sys.path.insert(0, "/var/task/backend")

from modules.m13_portal.alerting import send_failure_alert_if_warranted  # noqa: E402
from workers.portal_rates import run_portal_scrape  # noqa: E402

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):  # noqa: ARG001
    return asyncio.run(_run())


async def _run() -> dict:
    db_url = os.environ["DATABASE_URL"]
    engine = create_async_engine(db_url, pool_pre_ping=True)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with SessionLocal() as db:
            result = await run_portal_scrape(db)
            await send_failure_alert_if_warranted(db, result)
            await db.commit()
            logger.info("portal scrape complete: %s", result)
            return {"statusCode": 200, "body": result}
    finally:
        await engine.dispose()
