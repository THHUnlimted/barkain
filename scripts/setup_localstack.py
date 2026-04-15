"""Create SQS queues in LocalStack (or real AWS). Idempotent.

Usage:
    python3 scripts/setup_localstack.py

Also callable via:
    python3 scripts/run_worker.py setup-queues
"""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from workers.queue_client import ALL_QUEUES, SQSClient  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("barkain.setup_localstack")


async def main() -> None:
    client = SQSClient()
    for queue in ALL_QUEUES:
        url = await client.create_queue(queue)
        logger.info("Queue ready: name=%s url=%s", queue, url)


if __name__ == "__main__":
    asyncio.run(main())
