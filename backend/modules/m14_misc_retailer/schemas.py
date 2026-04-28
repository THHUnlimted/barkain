"""Pydantic schemas for M14 misc-retailer slot (Step 3n).

The misc-retailer slot is the 10th data source — it covers retailers Barkain
doesn't directly scrape (Chewy, Petco, niche pet/specialty stores) by
consuming Serper's `/shopping` endpoint and filtering Google's results down
to merchants the 9 scraper containers don't already serve.

Rows live in Redis only (6h TTL). No PG persistence; no migration in this
step. The shape mirrors what Serper Shopping returns after server-side
thumbnail-stripping in `_serper_shopping_fetch`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


# MARK: - Wire payload


class MiscMerchantRow(BaseModel):
    """One misc-retailer row as it appears on the SSE wire and in Redis.

    `link` is intentionally kept as `str` (not Pydantic `HttpUrl`) so
    callers can round-trip through `json.dumps` without the URL adapter
    needing to be revived; iOS validates with `URL(string:)` on decode.

    `source_normalized` is the `KNOWN_RETAILER_DOMAINS` matchspace —
    lowercase + whitespace-collapsed — and is what the filter consults. It
    is preserved on the wire so iOS can group/filter without re-deriving.

    `price_cents` is the parsed sort key; raw `price` is kept verbatim for
    display fidelity ("$20.98", "$1,049.00", "Free shipping").
    """

    model_config = ConfigDict(from_attributes=True)

    title: str
    source: str
    source_normalized: str
    link: str
    price: str
    price_cents: int | None = None
    rating: float | None = None
    rating_count: int | None = None
    product_id: str | None = None
    position: int


# MARK: - SSE event payloads


class MiscRetailerStreamDone(BaseModel):
    """Emitted as the final SSE `done` event so iOS can size the section
    deterministically without waiting for the connection to close."""

    model_config = ConfigDict(from_attributes=True)

    product_id: str
    rows: list[MiscMerchantRow]
    cached: bool
    fetched_at: str
