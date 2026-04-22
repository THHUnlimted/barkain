"""Scraper container HTTP server — lightweight FastAPI exposing POST /extract and GET /health.

Each retailer container runs this server. The backend sends extraction requests here,
and this server delegates to the shell extraction script (base-extract.sh).
"""

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Barkain Scraper Container", docs_url=None, redoc_url=None)

RETAILER_ID = os.environ.get("RETAILER_ID", "template")
SCRIPT_VERSION = os.environ.get("SCRIPT_VERSION", "0.0.0")
CHROMIUM_PATH = os.environ.get("CHROMIUM_PATH", "/usr/bin/chromium")
EXTRACT_TIMEOUT = int(os.environ.get("EXTRACT_TIMEOUT", "180"))  # seconds; live Best Buy + Walmart regularly exceed 60s


# MARK: - Models


class ExtractRequest(BaseModel):
    query: str
    product_name: str | None = None
    upc: str | None = None
    max_listings: int = 10
    # fb_marketplace-only overrides; every other retailer ignores them. The
    # fields live on the shared request so the backend doesn't have to fork
    # per-retailer schemas.
    fb_location_slug: str | None = None
    fb_radius_miles: int | None = None


class Listing(BaseModel):
    title: str
    price: float
    original_price: float | None = None
    currency: str = "USD"
    url: str = ""
    condition: str = "new"
    is_available: bool = True
    image_url: str | None = None
    seller: str | None = None
    extraction_method: str = "dom_eval"


class ExtractMetadata(BaseModel):
    url: str = ""
    extracted_at: str = ""
    script_version: str = SCRIPT_VERSION
    bot_detected: bool = False


class ExtractError(BaseModel):
    code: str
    message: str
    details: dict = {}


class ExtractResponse(BaseModel):
    retailer_id: str = RETAILER_ID
    query: str = ""
    extraction_time_ms: int = -1
    listings: list[Listing] = []
    metadata: ExtractMetadata = ExtractMetadata()
    error: ExtractError | None = None


class HealthResponse(BaseModel):
    status: str
    retailer_id: str
    script_version: str
    chromium_ready: bool


# MARK: - Endpoints


@app.get("/health")
async def health() -> HealthResponse:
    chromium_ready = Path(CHROMIUM_PATH).exists()
    return HealthResponse(
        status="healthy" if chromium_ready else "degraded",
        retailer_id=RETAILER_ID,
        script_version=SCRIPT_VERSION,
        chromium_ready=chromium_ready,
    )


# VPC-only access — no bearer token auth. Containers accessible only within VPC.
@app.post("/extract")
async def extract(request: ExtractRequest) -> ExtractResponse:
    start = time.perf_counter()
    script_path = Path("/app/base-extract.sh")

    if not script_path.exists():
        return ExtractResponse(
            retailer_id=RETAILER_ID,
            query=request.query,
            error=ExtractError(
                code="SCRIPT_NOT_FOUND",
                message="Extraction script not found",
            ),
            metadata=ExtractMetadata(
                extracted_at=datetime.now(timezone.utc).isoformat(),
            ),
        )

    try:
        proc = await asyncio.create_subprocess_exec(
            str(script_path),
            request.query,
            str(request.max_listings),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={
                **os.environ,
                "QUERY": request.query,
                "MAX_LISTINGS": str(request.max_listings),
                "PRODUCT_NAME": request.product_name or "",
                "UPC": request.upc or "",
                # fb_marketplace reads these; other retailers ignore them.
                "FB_LOCATION_SLUG": request.fb_location_slug or "",
                "FB_RADIUS_MILES": (
                    str(request.fb_radius_miles)
                    if request.fb_radius_miles is not None
                    else ""
                ),
            },
        )

        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=EXTRACT_TIMEOUT
        )

        elapsed_ms = int((time.perf_counter() - start) * 1000)

        if proc.returncode != 0:
            return ExtractResponse(
                retailer_id=RETAILER_ID,
                query=request.query,
                extraction_time_ms=elapsed_ms,
                error=ExtractError(
                    code="EXTRACTION_FAILED",
                    message=f"Script exited with code {proc.returncode}",
                    details={"stderr": stderr.decode(errors="replace")[:2000]},
                ),
                metadata=ExtractMetadata(
                    extracted_at=datetime.now(timezone.utc).isoformat(),
                ),
            )

        # Parse stdout JSON — agent-browser may wrap in string quotes
        raw = stdout.decode(errors="replace").strip()
        if raw.startswith('"'):
            raw = json.loads(raw)
        data = json.loads(raw)

        # Build listings from parsed data
        listings = []
        for item in data.get("listings", []):
            listings.append(
                Listing(
                    title=item.get("title", ""),
                    price=float(item.get("price", 0)),
                    original_price=(
                        float(item["original_price"])
                        if item.get("original_price")
                        else None
                    ),
                    currency=item.get("currency", "USD"),
                    url=item.get("url", ""),
                    condition=item.get("condition", "new"),
                    is_available=item.get("is_available", True),
                    image_url=item.get("image_url") or item.get("image"),
                    seller=item.get("seller"),
                    extraction_method=item.get("extraction_method", "dom_eval"),
                )
            )

        meta = data.get("metadata", {})
        return ExtractResponse(
            retailer_id=RETAILER_ID,
            query=request.query,
            extraction_time_ms=elapsed_ms,
            listings=listings,
            metadata=ExtractMetadata(
                url=meta.get("url", ""),
                extracted_at=meta.get(
                    "extracted_at", datetime.now(timezone.utc).isoformat()
                ),
                script_version=SCRIPT_VERSION,
                bot_detected=meta.get("bot_detected", False),
            ),
        )

    except asyncio.TimeoutError:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return ExtractResponse(
            retailer_id=RETAILER_ID,
            query=request.query,
            extraction_time_ms=elapsed_ms,
            error=ExtractError(
                code="TIMEOUT",
                message=f"Extraction timed out after {EXTRACT_TIMEOUT}s",
            ),
            metadata=ExtractMetadata(
                extracted_at=datetime.now(timezone.utc).isoformat(),
            ),
        )

    except (json.JSONDecodeError, ValueError) as e:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return ExtractResponse(
            retailer_id=RETAILER_ID,
            query=request.query,
            extraction_time_ms=elapsed_ms,
            error=ExtractError(
                code="PARSE_ERROR",
                message=f"Failed to parse extraction output: {e}",
            ),
            metadata=ExtractMetadata(
                extracted_at=datetime.now(timezone.utc).isoformat(),
            ),
        )
