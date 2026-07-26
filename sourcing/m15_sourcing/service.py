"""SourcingService — ingest, match, score, persist.

The orchestration layer. Everything computational lives in the pure modules
(``upc`` / ``ingest`` / ``fees`` / ``demand`` / ``scoring``); this file is about
I/O: the DB, the Redis match cache, and bounded fan-out to two external APIs.

## Shape of a crunch

A 3,000-row list is 3,000 × 2 potential API calls. Three things keep that from
being either abusive or slow:

1. **Redis match cache**, keyed by GTIN and channel, 12 h / 6 h TTL. Re-crunching
   a list after tweaking thresholds costs zero API calls — the match and the
   score are stored separately for exactly this reason.
2. **Bounded concurrency** via a semaphore sized by ``SOURCING_MATCH_CONCURRENCY``,
   plus a per-adapter process-wide rate floor.
3. **Skip-before-spend**: rows with no usable UPC, no cost, or a restricted GS1
   prefix never reach an adapter.

Results stream as they complete (``asyncio.as_completed``), mirroring the M2
SSE pattern, so a long crunch shows candidates arriving rather than a spinner.

## Why match and score are stored separately

``sourcing_rows.match`` is what the APIs said. ``sourcing_rows.channels`` is
what our fee/threshold math concluded. Re-scoring on new thresholds reads the
first and rewrites the second — no refetch, no rate-limit exposure, instant.
It also means a fee-schedule correction can be replayed over historical lists.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import redis.asyncio as aioredis
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from m15_sourcing.config import SourcingSettings as Settings, settings as default_settings
from m15_sourcing import demand as demand_mod
from m15_sourcing import fees as fees_mod
from m15_sourcing import scoring as scoring_mod
from m15_sourcing.adapters import ebay_sourcing, walmart_io
from m15_sourcing.ingest import IngestedRow, IngestResult, ingest
from m15_sourcing.models import (
    BrandAccess,
    ListingSnapshot,
    SourcingList,
    SourcingRow,
)
from m15_sourcing.upc import summarize as summarize_upcs

logger = logging.getLogger("barkain.m15")

_CACHE_PREFIX = "sourcing:match"
# How far back to read snapshots when estimating demand. Wide enough to hold a
# velocity window, narrow enough that a listing's ancient history doesn't drown
# out how it's behaving now.
_SNAPSHOT_LOOKBACK_DAYS = 180


class ListNotFoundError(Exception):
    """Raised when a list ID doesn't exist or belongs to another user."""


class RowNotFoundError(Exception):
    """Raised when a row ID doesn't exist or belongs to another user."""


def _json_safe(value: object) -> object:
    """Coerce Decimals and datetimes so a payload survives ``json.dumps``/JSONB."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


class SourcingService:
    def __init__(
        self,
        db: AsyncSession,
        redis: aioredis.Redis | None = None,
        cfg: Settings | None = None,
    ) -> None:
        self.db = db
        self.redis = redis
        self.cfg = cfg or default_settings
        self._semaphore = asyncio.Semaphore(max(1, self.cfg.SOURCING_MATCH_CONCURRENCY))

    # MARK: - Ingest

    async def create_list(
        self,
        *,
        user_id: str,
        data: bytes,
        filename: str,
        name: str | None = None,
        supplier: str | None = None,
        thresholds: dict | None = None,
        default_case_pack: int | None = None,
        cost_is_case_cost: bool = False,
    ) -> tuple[SourcingList, IngestResult]:
        """Parse an uploaded price list and persist its rows.

        Deliberately does **no** matching. The upload response shows the column
        mapping and normalization stats so a mis-mapped file gets caught before
        it spends 3,000 API calls proving that column D wasn't the UPC.
        """
        result = ingest(
            data,
            filename,
            max_rows=self.cfg.SOURCING_MAX_ROWS,
            default_case_pack=default_case_pack,
            cost_is_case_cost=cost_is_case_cost,
        )
        stats = summarize_upcs([row.upc for row in result.rows])

        sourcing_list = SourcingList(
            user_id=user_id,
            name=name or filename or "Untitled list",
            source_filename=filename or None,
            supplier=supplier,
            status="ingested",
            row_count=len(result.rows),
            usable_row_count=stats.usable,
            scored_row_count=0,
            column_mapping={
                "header_row_index": result.mapping.header_row_index,
                "columns": result.mapping.columns,
                "headers": list(result.mapping.headers),
                "unmapped_headers": list(result.mapping.unmapped_headers),
            },
            ingest_stats={
                "total": stats.total,
                "usable": stats.usable,
                "unusable": stats.unusable,
                "duplicates": stats.duplicates,
                "usable_pct": stats.usable_pct,
                "by_method": stats.by_method,
                "by_warning": stats.by_warning,
                "skipped_rows": result.skipped_rows,
                "warnings": result.warnings,
            },
            thresholds=(thresholds or scoring_mod.Thresholds().as_dict()),
        )
        self.db.add(sourcing_list)
        await self.db.flush()

        for row in result.rows:
            self.db.add(self._row_model(sourcing_list.id, row))
        await self.db.flush()

        return sourcing_list, result

    @staticmethod
    def _row_model(list_id: uuid.UUID, row: IngestedRow) -> SourcingRow:
        return SourcingRow(
            list_id=list_id,
            row_index=row.row_index,
            status="pending" if row.upc.is_usable else "skipped",
            raw=_json_safe(row.raw),  # type: ignore[arg-type]
            raw_upc=row.upc.raw or None,
            gtin14=row.upc.gtin14,
            upc_method=row.upc.method,
            upc_warnings=list(row.upc.warnings),
            description=row.description,
            brand=row.brand,
            sku=row.sku,
            unit_cost=row.unit_cost,
            case_cost=row.case_cost,
            case_pack=row.case_pack,
            moq=row.moq,
            msrp=row.msrp,
            minimum_buy_cost=row.minimum_buy_cost,
            errors=row.notes or None,
        )

    # MARK: - List access

    async def get_list(self, list_id: uuid.UUID, user_id: str) -> SourcingList:
        result = await self.db.execute(
            select(SourcingList).where(
                SourcingList.id == list_id, SourcingList.user_id == user_id
            )
        )
        sourcing_list = result.scalar_one_or_none()
        if sourcing_list is None:
            raise ListNotFoundError(str(list_id))
        return sourcing_list

    async def list_lists(self, user_id: str, limit: int = 50) -> list[SourcingList]:
        result = await self.db.execute(
            select(SourcingList)
            .where(SourcingList.user_id == user_id)
            .order_by(SourcingList.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def delete_list(self, list_id: uuid.UUID, user_id: str) -> None:
        await self.get_list(list_id, user_id)  # ownership check
        await self.db.execute(delete(SourcingList).where(SourcingList.id == list_id))

    async def get_rows(
        self,
        list_id: uuid.UUID,
        user_id: str,
        *,
        verdict: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[SourcingRow]:
        await self.get_list(list_id, user_id)
        query = select(SourcingRow).where(SourcingRow.list_id == list_id)
        if verdict:
            query = query.where(SourcingRow.verdict == verdict)
        # NULLS LAST so un-crunched rows don't occupy the top of a partially
        # scored list — the whole promise is "winners first".
        query = query.order_by(
            SourcingRow.projected_monthly_profit.desc().nullslast(),
            SourcingRow.row_index,
        )
        result = await self.db.execute(query.limit(limit).offset(offset))
        return list(result.scalars().all())

    # MARK: - Match cache

    def _cache_key(self, channel: str, gtin: str) -> str:
        return f"{_CACHE_PREFIX}:{channel}:{gtin}"

    async def _cache_get(self, channel: str, gtin: str) -> dict | None:
        if self.redis is None:
            return None
        try:
            raw = await self.redis.get(self._cache_key(channel, gtin))
        except Exception:  # noqa: BLE001 — cache is an optimization, never a dependency
            logger.debug("sourcing cache read failed", exc_info=True)
            return None
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return None

    async def _cache_set(self, channel: str, gtin: str, payload: dict) -> None:
        if self.redis is None:
            return
        ttl = (
            self.cfg.SOURCING_MATCH_CACHE_TTL_WALMART
            if channel == "walmart"
            else self.cfg.SOURCING_MATCH_CACHE_TTL_EBAY
        )
        try:
            await self.redis.setex(
                self._cache_key(channel, gtin), ttl, json.dumps(_json_safe(payload))
            )
        except Exception:  # noqa: BLE001
            logger.debug("sourcing cache write failed", exc_info=True)

    # MARK: - Matching

    async def _match_walmart(self, gtin: str, gtin14: str) -> dict:
        adapter = self.cfg.WALMART_SOURCING_ADAPTER
        if adapter == "disabled":
            return {"found": False, "error": "DISABLED", "source": "disabled"}

        cached = await self._cache_get("walmart", gtin)
        if cached is not None:
            cached["cached"] = True
            return cached

        async with self._semaphore:
            match = await walmart_io.lookup_by_upc(gtin, gtin14=gtin14, cfg=self.cfg)
        payload = match.as_dict()
        # Never cache a transient failure — a rate-limit or timeout cached for
        # 12 h turns a blip into a day of false "no listing" verdicts.
        if match.found or match.error is None:
            await self._cache_set("walmart", gtin, payload)
        return payload

    async def _match_ebay(self, gtin: str, gtin14: str) -> dict:
        cached = await self._cache_get("ebay", gtin)
        if cached is not None:
            cached["cached"] = True
            return cached

        async with self._semaphore:
            match = await ebay_sourcing.lookup_by_gtin(gtin, gtin14=gtin14, cfg=self.cfg)
        payload = match.as_dict()
        if match.found or match.error is None:
            await self._cache_set("ebay", gtin, payload)
        return payload

    async def match_row(self, row: SourcingRow) -> dict:
        """Fetch both channels for one row, concurrently. Never raises."""
        gtin14 = row.gtin14
        if not gtin14:
            return {}
        # Search on the each-level UPC-A/EAN — the channels don't index
        # zero-padded GTIN-14s, and a case code has to be unwrapped first.
        from m15_sourcing.upc import case_gtin_to_each

        each = case_gtin_to_each(gtin14) or gtin14
        search_value = each[2:] if each[:2] == "00" else (each[1:] if each[0] == "0" else each)

        walmart_result, ebay_result = await asyncio.gather(
            self._match_walmart(search_value, gtin14),
            self._match_ebay(search_value, gtin14),
            return_exceptions=True,
        )

        def _unwrap(result: object, channel: str) -> dict:
            if isinstance(result, BaseException):
                logger.warning("sourcing %s match raised: %s", channel, result)
                return {"found": False, "error": f"EXCEPTION: {result}"}
            return result  # type: ignore[return-value]

        return {
            "walmart": _unwrap(walmart_result, "walmart"),
            "ebay": _unwrap(ebay_result, "ebay"),
            "searched_upc": search_value,
        }

    # MARK: - Snapshots

    async def _snapshots_for(self, channel: str, listing_key: str) -> list[demand_mod.Snapshot]:
        cutoff = datetime.now(UTC) - timedelta(days=_SNAPSHOT_LOOKBACK_DAYS)
        result = await self.db.execute(
            select(ListingSnapshot)
            .where(
                ListingSnapshot.channel == channel,
                ListingSnapshot.listing_key == listing_key,
                ListingSnapshot.captured_at >= cutoff,
            )
            .order_by(ListingSnapshot.captured_at)
        )
        return [
            demand_mod.Snapshot(
                captured_at=s.captured_at,
                price=Decimal(str(s.price)) if s.price is not None else None,
                review_count=s.review_count,
                rating=float(s.rating) if s.rating is not None else None,
                seller_count=s.seller_count,
                in_stock=s.in_stock,
                sold_count_90d=s.sold_count_90d,
                bought_badge_min=s.bought_badge_min,
            )
            for s in result.scalars().all()
        ]

    async def record_snapshot(
        self,
        *,
        channel: str,
        listing_key: str,
        gtin14: str | None,
        match: dict,
    ) -> None:
        """Append one observation. Idempotent-ish: the PK includes ``captured_at``.

        Called on every successful live match, not only from the cron, so the
        dataset starts accumulating from a user's very first crunch. Cached
        matches are skipped by the caller — re-storing the same numbers under a
        new timestamp would fabricate a flat price history and make a volatile
        item look stable.
        """
        price = match.get("reference_price") or match.get("price")
        self.db.add(
            ListingSnapshot(
                captured_at=datetime.now(UTC),
                channel=channel,
                listing_key=listing_key,
                gtin14=gtin14,
                price=price,
                review_count=match.get("review_count"),
                rating=match.get("rating"),
                seller_count=match.get("seller_count")
                or match.get("total_active_listings"),
                sold_count_90d=match.get("sold_count_90d"),
                bought_badge_min=match.get("bought_badge_min"),
                in_stock=match.get("in_stock"),
                raw=_json_safe(match),  # type: ignore[arg-type]
            )
        )

    # MARK: - Brand access

    async def brand_statuses(self, user_id: str) -> dict[str, str]:
        result = await self.db.execute(
            select(BrandAccess.brand_normalized, BrandAccess.status).where(
                BrandAccess.user_id == user_id
            )
        )
        return {row[0]: row[1] for row in result.all()}

    @staticmethod
    def normalize_brand(brand: str | None) -> str | None:
        """Lookup key for the brand ledger — distributor lists spell brands four ways."""
        if not brand:
            return None
        return " ".join(brand.strip().lower().split()) or None

    # MARK: - Scoring

    def score_row(
        self,
        row: SourcingRow,
        match: dict,
        *,
        thresholds: scoring_mod.Thresholds,
        walmart_snapshots: list[demand_mod.Snapshot],
        ebay_snapshots: list[demand_mod.Snapshot],
        brand_status: str = scoring_mod.BRAND_UNKNOWN,
    ) -> scoring_mod.ScoredRow:
        """Apply fee + demand + threshold math to one matched row. Pure-ish, no I/O."""
        unit_cost = Decimal(str(row.unit_cost)) if row.unit_cost is not None else None
        if unit_cost is None and row.case_cost is not None and row.case_pack:
            unit_cost = Decimal(str(row.case_cost)) / Decimal(row.case_pack)

        scored = scoring_mod.ScoredRow(
            row_index=row.row_index,
            gtin14=row.gtin14,
            description=row.description,
            brand=row.brand,
            unit_cost=unit_cost,
            minimum_buy_cost=Decimal(str(row.minimum_buy_cost))
            if row.minimum_buy_cost is not None
            else None,
            brand_status=brand_status,
        )
        if unit_cost is None or unit_cost <= 0:
            scored.errors.append("no usable unit cost — cannot score")
            return scored

        walmart = match.get("walmart") or {}
        ebay = match.get("ebay") or {}

        # ── Walmart ──────────────────────────────────────────────────
        if walmart.get("found") and walmart.get("price"):
            dims = fees_mod.ItemDimensions(
                weight_lb=Decimal(str(walmart["weight_lb"]))
                if walmart.get("weight_lb")
                else None
            )
            economics = fees_mod.walmart_economics(
                sale_price=Decimal(str(walmart["price"])),
                unit_cost=unit_cost,
                category=walmart.get("category_path"),
                dims=dims,
                days_on_hand=self.cfg.SOURCING_DAYS_ON_HAND,
            )
            scored.channels["walmart"] = scoring_mod.score_channel(
                economics=economics,
                demand=demand_mod.estimate_demand(
                    walmart_snapshots, review_rate=self.cfg.SOURCING_REVIEW_RATE
                ),
                stability=demand_mod.price_stability(walmart_snapshots),
                seller_count=walmart.get("seller_count"),
                thresholds=thresholds,
                listing_exists=True,
                minimum_buy_cost=scored.minimum_buy_cost,
                brand_status=brand_status,
            )
        else:
            scored.channels["walmart"] = scoring_mod.score_channel(
                economics=fees_mod.walmart_economics(
                    sale_price=Decimal("0"), unit_cost=unit_cost
                ),
                demand=demand_mod.UNKNOWN_DEMAND,
                stability=demand_mod.UNKNOWN_STABILITY,
                seller_count=None,
                thresholds=thresholds,
                listing_exists=False,
                minimum_buy_cost=scored.minimum_buy_cost,
                brand_status=brand_status,
            )

        # ── eBay ─────────────────────────────────────────────────────
        reference = ebay.get("reference_price")
        if ebay.get("found") and reference:
            dims = fees_mod.ItemDimensions(
                weight_lb=Decimal(str(walmart["weight_lb"]))
                if walmart.get("weight_lb")
                else None
            )
            economics = fees_mod.ebay_economics(
                sale_price=Decimal(str(reference)),
                unit_cost=unit_cost,
                category=None,
                dims=dims,
            )
            scored.channels["ebay"] = scoring_mod.score_channel(
                economics=economics,
                demand=demand_mod.estimate_demand(
                    ebay_snapshots, review_rate=self.cfg.SOURCING_REVIEW_RATE
                ),
                stability=demand_mod.price_stability(ebay_snapshots),
                seller_count=ebay.get("total_active_listings"),
                thresholds=thresholds,
                listing_exists=True,
                minimum_buy_cost=scored.minimum_buy_cost,
                brand_status=brand_status,
            )
        else:
            scored.channels["ebay"] = scoring_mod.score_channel(
                economics=fees_mod.ebay_economics(
                    sale_price=Decimal("0"), unit_cost=unit_cost
                ),
                demand=demand_mod.UNKNOWN_DEMAND,
                stability=demand_mod.UNKNOWN_STABILITY,
                seller_count=None,
                thresholds=thresholds,
                listing_exists=False,
                minimum_buy_cost=scored.minimum_buy_cost,
                brand_status=brand_status,
            )

        return scored

    # MARK: - Crunch

    async def crunch(
        self,
        list_id: uuid.UUID,
        user_id: str,
        *,
        thresholds: dict | None = None,
        rescore_only: bool = False,
    ) -> dict:
        """Run the full pipeline over a list and return the verdict summary.

        ``rescore_only`` replays scoring over the stored ``match`` payloads —
        no API calls at all. That's the path for "what if I lowered my ROI bar
        to 20%", which should be instant and free.
        """
        summary: dict = {}
        async for event, payload in self.stream_crunch(
            list_id, user_id, thresholds=thresholds, rescore_only=rescore_only
        ):
            if event == "done":
                summary = payload
        return summary

    async def stream_crunch(
        self,
        list_id: uuid.UUID,
        user_id: str,
        *,
        thresholds: dict | None = None,
        rescore_only: bool = False,
    ) -> AsyncGenerator[tuple[str, dict], None]:
        """Crunch a list, yielding ``(event, payload)`` as rows complete.

        Events: ``progress`` (counts), ``row`` (a scored row), ``done`` (summary).
        Mirrors the M2 SSE event shape so the existing iOS byte splitter works.
        """
        sourcing_list = await self.get_list(list_id, user_id)
        threshold_dict = thresholds or sourcing_list.thresholds or {}
        parsed_thresholds = scoring_mod.Thresholds.from_dict(threshold_dict)

        sourcing_list.status = "crunching"
        sourcing_list.thresholds = parsed_thresholds.as_dict()
        await self.db.flush()

        rows_result = await self.db.execute(
            select(SourcingRow)
            .where(SourcingRow.list_id == list_id)
            .order_by(SourcingRow.row_index)
        )
        rows = list(rows_result.scalars().all())
        brand_map = await self.brand_statuses(user_id)

        scorable = [r for r in rows if r.gtin14 and r.status != "skipped"]
        total = len(scorable)
        yield "progress", {"total": total, "completed": 0, "list_id": str(list_id)}

        scored_rows: list[scoring_mod.ScoredRow] = []
        completed = 0

        async def _process(row: SourcingRow) -> tuple[SourcingRow, dict]:
            if rescore_only:
                return row, (row.match or {})
            return row, await self.match_row(row)

        # `as_completed` rather than `gather`: a 3,000-row crunch should surface
        # its first candidates in seconds, not after the slowest row returns.
        # The semaphore inside `match_row` is what actually bounds outbound
        # concurrency — creating all the tasks up front is fine.
        tasks = [asyncio.create_task(_process(row)) for row in scorable]
        try:
            for future in asyncio.as_completed(tasks):
                row, match = await future
                completed += 1

                brand_key = self.normalize_brand(row.brand)
                brand_status = brand_map.get(brand_key or "", scoring_mod.BRAND_UNKNOWN)

                walmart_snapshots: list[demand_mod.Snapshot] = []
                ebay_snapshots: list[demand_mod.Snapshot] = []
                walmart_match = (match or {}).get("walmart") or {}
                ebay_match = (match or {}).get("ebay") or {}

                walmart_key = walmart_match.get("item_id") or row.gtin14
                if walmart_match.get("found") and walmart_key:
                    walmart_snapshots = await self._snapshots_for("walmart", walmart_key)
                    if not walmart_match.get("cached"):
                        await self.record_snapshot(
                            channel="walmart",
                            listing_key=walmart_key,
                            gtin14=row.gtin14,
                            match=walmart_match,
                        )

                ebay_key = f"gtin:{row.gtin14}" if row.gtin14 else None
                if ebay_match.get("found") and ebay_key:
                    ebay_snapshots = await self._snapshots_for("ebay", ebay_key)
                    if not ebay_match.get("cached"):
                        await self.record_snapshot(
                            channel="ebay",
                            listing_key=ebay_key,
                            gtin14=row.gtin14,
                            match=ebay_match,
                        )

                scored = self.score_row(
                    row,
                    match or {},
                    thresholds=parsed_thresholds,
                    walmart_snapshots=walmart_snapshots,
                    ebay_snapshots=ebay_snapshots,
                    brand_status=brand_status,
                )
                scored_rows.append(scored)

                payload = _json_safe(scored.as_dict())
                row.match = _json_safe(match) or None  # type: ignore[assignment]
                row.channels = payload["channels"]  # type: ignore[index,assignment]
                row.verdict = scored.verdict.value
                best = scored.best_channel
                row.best_channel = best.economics.channel if best else None
                row.projected_monthly_profit = scored.projected_monthly_profit
                row.status = "scored"
                row.errors = scored.errors or None

                yield "row", payload  # type: ignore[misc]
                if completed % 25 == 0 or completed == total:
                    await self.db.flush()
                    yield "progress", {
                        "total": total,
                        "completed": completed,
                        "list_id": str(list_id),
                    }
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()

        summary = scoring_mod.summarize(scored_rows)
        sourcing_list.status = "complete"
        sourcing_list.scored_row_count = len(scored_rows)
        sourcing_list.verdict_summary = summary
        sourcing_list.crunched_at = datetime.now(UTC)
        await self.db.flush()

        yield "done", {"list_id": str(list_id), **summary}

    # MARK: - Row detail

    async def get_row(self, row_id: uuid.UUID, user_id: str) -> SourcingRow:
        result = await self.db.execute(
            select(SourcingRow)
            .join(SourcingList, SourcingList.id == SourcingRow.list_id)
            .where(SourcingRow.id == row_id, SourcingList.user_id == user_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise RowNotFoundError(str(row_id))
        return row

    async def count_rows(self, list_id: uuid.UUID) -> int:
        result = await self.db.execute(
            select(func.count()).select_from(SourcingRow).where(SourcingRow.list_id == list_id)
        )
        return int(result.scalar() or 0)

    # MARK: - Brand ledger writes

    async def upsert_brand(
        self,
        *,
        user_id: str,
        brand: str,
        status: str,
        distributor_name: str | None = None,
        distributor_email: str | None = None,
        gated_on: list[str] | None = None,
        notes: str | None = None,
    ) -> BrandAccess:
        normalized = self.normalize_brand(brand)
        if not normalized:
            raise ValueError("brand must be non-empty")

        result = await self.db.execute(
            select(BrandAccess).where(
                BrandAccess.user_id == user_id,
                BrandAccess.brand_normalized == normalized,
            )
        )
        existing = result.scalar_one_or_none()
        if existing is None:
            existing = BrandAccess(
                user_id=user_id,
                brand_normalized=normalized,
                brand_display=brand.strip(),
            )
            self.db.add(existing)

        existing.status = status
        existing.brand_display = brand.strip()
        if distributor_name is not None:
            existing.distributor_name = distributor_name
        if distributor_email is not None:
            existing.distributor_email = distributor_email
        if gated_on is not None:
            existing.gated_on = gated_on
        if notes is not None:
            existing.notes = notes
        existing.updated_at = datetime.now(UTC)
        await self.db.flush()
        return existing

    async def list_brands(self, user_id: str) -> list[BrandAccess]:
        result = await self.db.execute(
            select(BrandAccess)
            .where(BrandAccess.user_id == user_id)
            .order_by(BrandAccess.brand_normalized)
        )
        return list(result.scalars().all())

    async def mark_inquiry_sent(self, user_id: str, brand: str) -> None:
        normalized = self.normalize_brand(brand)
        if not normalized:
            return
        await self.db.execute(
            update(BrandAccess)
            .where(
                BrandAccess.user_id == user_id,
                BrandAccess.brand_normalized == normalized,
            )
            .values(inquiry_sent_at=datetime.now(UTC), status="pending")
        )
