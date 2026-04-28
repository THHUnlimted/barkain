"""X-fallback adapter stub — Bright Data managed SERP API (Step 3n).

Not built. See Investigation Area 9.3.
"""

from __future__ import annotations

from modules.m14_misc_retailer.adapters.base import MiscRetailerAdapter
from modules.m14_misc_retailer.schemas import MiscMerchantRow


class BrightDataSerpApiAdapter(MiscRetailerAdapter):
    async def fetch(self, query: str) -> list[MiscMerchantRow]:  # noqa: ARG002
        raise NotImplementedError(
            "BrightDataSerpApiAdapter is a Step 3n X-fallback stub (Investigation Area 9.3)."
        )
