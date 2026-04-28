"""Adapter ABC for M14 misc-retailer slot (Step 3n).

Each adapter contract is intentionally tiny: take a free-form query string
(the product title or a query_override), return a list of
`MiscMerchantRow` instances. Adapters do NOT touch Redis, do NOT cap, do
NOT consult `KNOWN_RETAILER_DOMAINS` — that's `MiscRetailerService`'s job.
The boundary keeps adapters swap-clean for the bench harness, which calls
the adapter directly without the service layer.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from modules.m14_misc_retailer.schemas import MiscMerchantRow


class MiscRetailerAdapter(ABC):
    """Adapter contract for the misc-retailer slot."""

    @abstractmethod
    async def fetch(self, query: str) -> list[MiscMerchantRow]:
        """Return zero or more merchant rows for the query.

        Implementations must soft-fail to `[]` rather than raising, so a
        single-vendor outage degrades the slot to "empty" instead of
        breaking the price-comparison view. The one exception is the
        deliberate `NotImplementedError` raised by the standby/fallback
        stubs to make accidental flag-flips loud.
        """
        ...
