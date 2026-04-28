"""No-op adapter for `MISC_RETAILER_ADAPTER=disabled` (Step 3n).

Default at launch. Returns empty list without making any external call,
so iOS renders zero misc-retailer rows and the section hides itself.
Kept as a real adapter (not a None branch in the service) so the
dispatch table stays uniform.
"""

from __future__ import annotations

from modules.m14_misc_retailer.adapters.base import MiscRetailerAdapter
from modules.m14_misc_retailer.schemas import MiscMerchantRow


class DisabledAdapter(MiscRetailerAdapter):
    async def fetch(self, query: str) -> list[MiscMerchantRow]:  # noqa: ARG002
        return []
