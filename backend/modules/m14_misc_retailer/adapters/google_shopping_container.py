"""Z-standby adapter stub — DIY Google Shopping Chrome container (Step 3n).

Not built. The v2 investigation in
``Barkain Prompts/Misc_Retailer_Investigation_v1.md`` (Mike's local
workspace, NOT in repo) proved feasibility via four hands-on Decodo +
real-Chrome runs. The stub is plumbed so `MISC_RETAILER_ADAPTER=
google_shopping_container` is a recognized value, and so a future build
slots in without a service-layer change.

Build trigger (per §Locked Decisions item 4): bench misc-retailer
hit-rate <75 % for 2 consecutive weekly runs OR Google v. SerpApi
(2026-05-19 motion-to-dismiss) lands broadly against managed SERP.
"""

from __future__ import annotations

from modules.m14_misc_retailer.adapters.base import MiscRetailerAdapter
from modules.m14_misc_retailer.schemas import MiscMerchantRow


class GoogleShoppingContainerAdapter(MiscRetailerAdapter):
    async def fetch(self, query: str) -> list[MiscMerchantRow]:  # noqa: ARG002
        # 3n: deliberate NotImplementedError — accidental flag-flip should be loud,
        # not silently empty. See v2 empirical artifacts on Mike's local machine.
        raise NotImplementedError(
            "GoogleShoppingContainerAdapter is a Step 3n standby stub. "
            "Build this only after a documented bench-driven trigger; do not "
            "ship by setting MISC_RETAILER_ADAPTER=google_shopping_container."
        )
