"""X-fallback adapter stub — Decodo managed SERP API (Step 3n).

Not built. Investigation Area 9.3 keeps Decodo as a third-tier fallback
behind S (Serper Shopping) and Z (DIY container). Plumbed only so the
dispatch table is uniform.
"""

from __future__ import annotations

from modules.m14_misc_retailer.adapters.base import MiscRetailerAdapter
from modules.m14_misc_retailer.schemas import MiscMerchantRow


class DecodoSerpApiAdapter(MiscRetailerAdapter):
    async def fetch(self, query: str) -> list[MiscMerchantRow]:  # noqa: ARG002
        raise NotImplementedError(
            "DecodoSerpApiAdapter is a Step 3n X-fallback stub (Investigation Area 9.3)."
        )
