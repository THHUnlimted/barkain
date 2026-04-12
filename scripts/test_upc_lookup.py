#!/usr/bin/env python3
"""Interactive UPC test tool — search for products, resolve UPCs, see cross-validation results.

Usage:
    python3 scripts/test_upc_lookup.py

Doesn't need the backend server running — calls Gemini and UPCitemdb APIs directly.
Reads API keys from .env in the project root.
"""

import asyncio
import os
import sys
from pathlib import Path

# Load .env from project root
ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
if ENV_PATH.exists():
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())

# Add backend to path
sys.path.insert(0, str(ROOT / "backend"))

import httpx

# ── Curated catalog of known electronics UPCs ──────────────────────

CATALOG = {
    # Sony
    "027242923782": "Sony WH-1000XM5 Headphones",
    "027242919075": "Sony WH-1000XM4 Headphones",
    "027242911574": "Sony WH-1000XM3 Headphones",
    "027242927568": "Sony (tested in demo — resolved wrong)",
    "027242922914": "Sony (tested in demo — resolved wrong)",
    # Apple
    "194253397168": "Apple AirPods Pro (2nd Gen)",
    "190199246850": "Apple AirPods Pro (1st Gen)",
    "190199098428": "Apple AirPods with Charging Case (2nd Gen)",
    "194252721247": "Apple AirPods Pro (1st Gen) MagSafe",
    "195949052484": "Apple AirPods Pro 2nd Gen USB-C",
    "194253397953": "Apple (tested in demo — resolved wrong)",
    # Samsung
    "732554340133": "Samsung Galaxy Buds R170N White",
    "887276789880": "Samsung (used in null-retry test)",
    # Other
    "848061073966": "JBL Flip 6 Bluetooth Speaker",
    "017817841634": "Bose QuietComfort 45 Headphones",
    "097855171191": "Nintendo Switch Pro Controller",
}

UPCITEMDB_TRIAL_URL = "https://api.upcitemdb.com/prod/trial/lookup"


# ── UPCitemdb lookup (trial, no key needed) ────────────────────────

async def upcitemdb_lookup(upc: str) -> dict | None:
    """Look up a UPC via UPCitemdb trial API."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(UPCITEMDB_TRIAL_URL, params={"upc": upc})
            if resp.status_code == 429:
                print("  [!] UPCitemdb rate limited (100/day on trial). Try again later.")
                return None
            resp.raise_for_status()
            data = resp.json()
        items = data.get("items", [])
        if not items:
            return None
        item = items[0]
        images = item.get("images", [])
        return {
            "name": item.get("title", ""),
            "brand": item.get("brand", ""),
            "category": item.get("category", ""),
            "description": item.get("description", ""),
            "asin": item.get("asin"),
            "image_url": images[0] if images else None,
        }
    except Exception as e:
        print(f"  [!] UPCitemdb error: {e}")
        return None


# ── Gemini lookup ──────────────────────────────────────────────────

async def gemini_lookup(upc: str) -> dict | None:
    """Resolve a UPC via Gemini API."""
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        print("  [!] GEMINI_API_KEY not set — skipping Gemini")
        return None

    try:
        from ai.abstraction import gemini_generate_json
        from ai.prompts.upc_lookup import UPC_LOOKUP_SYSTEM_INSTRUCTION, build_upc_lookup_prompt

        prompt = build_upc_lookup_prompt(upc)
        raw = await gemini_generate_json(prompt, system_instruction=UPC_LOOKUP_SYSTEM_INSTRUCTION)
        device_name = raw.get("device_name")
        if not device_name:
            return None
        return {"name": device_name}
    except Exception as e:
        print(f"  [!] Gemini error: {e}")
        return None


# ── Cross-validation (same logic as service.py) ───────────────────

def cross_validate(gemini_data: dict | None, upcitemdb_data: dict | None) -> dict:
    """Compare results and pick the winner."""
    if gemini_data and upcitemdb_data:
        upc_brand = (upcitemdb_data.get("brand") or "").strip()
        gemini_name = gemini_data.get("name", "")
        if upc_brand and upc_brand.lower() in gemini_name.lower():
            return {
                "winner": "gemini_validated",
                "confidence": 1.0,
                "name": gemini_name,
                "brand": upcitemdb_data.get("brand"),
                "category": upcitemdb_data.get("category"),
                "match": f"Brands agree ('{upc_brand}' found in Gemini name)",
            }
        else:
            return {
                "winner": "upcitemdb_override",
                "confidence": 0.5,
                "name": upcitemdb_data.get("name"),
                "brand": upcitemdb_data.get("brand"),
                "category": upcitemdb_data.get("category"),
                "match": f"Brand MISMATCH — Gemini='{gemini_name}', UPCitemdb brand='{upc_brand}'",
            }
    if gemini_data:
        return {
            "winner": "gemini_upc",
            "confidence": 0.7,
            "name": gemini_data.get("name"),
            "brand": None,
            "category": None,
            "match": "Gemini only (UPCitemdb returned nothing)",
        }
    if upcitemdb_data:
        return {
            "winner": "upcitemdb",
            "confidence": 0.3,
            "name": upcitemdb_data.get("name"),
            "brand": upcitemdb_data.get("brand"),
            "category": upcitemdb_data.get("category"),
            "match": "UPCitemdb only (Gemini failed)",
        }
    return {
        "winner": None,
        "confidence": 0.0,
        "name": None,
        "brand": None,
        "category": None,
        "match": "Both sources FAILED",
    }


# ── UPCitemdb search by keyword ────────────────────────────────────

async def search_products(query: str) -> list[dict]:
    """Search UPCitemdb by keyword (trial API)."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.upcitemdb.com/prod/trial/search",
                params={"s": query, "match": "0", "type": "product"},
            )
            if resp.status_code == 429:
                print("  [!] UPCitemdb rate limited. Try again in a minute.")
                return []
            resp.raise_for_status()
            data = resp.json()
        items = data.get("items", [])
        results = []
        for item in items[:10]:
            results.append({
                "upc": item.get("upc") or item.get("ean", ""),
                "title": item.get("title", "Unknown"),
                "brand": item.get("brand", ""),
            })
        return results
    except Exception as e:
        print(f"  [!] Search error: {e}")
        return []


# ── Display helpers ────────────────────────────────────────────────

def show_catalog():
    print("\n  ╔══════════════════════════════════════════════════════════════╗")
    print("  ║  Known Electronics UPCs — pick a number or enter your own  ║")
    print("  ╚══════════════════════════════════════════════════════════════╝\n")
    items = list(CATALOG.items())
    for i, (upc, desc) in enumerate(items, 1):
        print(f"  {i:>3}.  {upc}  —  {desc}")
    print()
    return items


def show_result(upc: str, gemini_data, upcitemdb_data, result):
    print()
    print(f"  ┌─ UPC: {upc} ────────────────────────────────")
    print(f"  │")
    print(f"  │  Gemini says:    {gemini_data.get('name') if gemini_data else '(failed/empty)'}")
    print(f"  │  UPCitemdb says: {upcitemdb_data.get('name') if upcitemdb_data else '(failed/empty)'}")
    if upcitemdb_data:
        print(f"  │  UPCitemdb brand: {upcitemdb_data.get('brand', '?')}")
        print(f"  │  UPCitemdb category: {upcitemdb_data.get('category', '?')}")
    print(f"  │")
    print(f"  │  ► Winner:     {result['winner'] or 'NONE'}")
    print(f"  │  ► Confidence: {result['confidence']}")
    print(f"  │  ► Final name: {result['name'] or '(no product resolved)'}")
    print(f"  │  ► Reason:     {result['match']}")
    print(f"  └──────────────────────────────────────────────────")
    print()


# ── Main loop ──────────────────────────────────────────────────────

async def resolve_upc(upc: str):
    """Full cross-validation test for a single UPC."""
    print(f"\n  Resolving UPC {upc}...")
    print(f"  [1/2] Calling Gemini...")
    gemini_data = await gemini_lookup(upc)
    print(f"  [2/2] Calling UPCitemdb...")
    upcitemdb_data = await upcitemdb_lookup(upc)
    result = cross_validate(gemini_data, upcitemdb_data)
    show_result(upc, gemini_data, upcitemdb_data, result)
    return result


async def main():
    print("\n  ═══════════════════════════════════════════")
    print("  Barkain UPC Test Tool — Cross-Validation")
    print("  ═══════════════════════════════════════════")
    print()
    print("  Commands:")
    print("    <number>     — Pick from catalog")
    print("    <12-13 digits> — Test a UPC directly")
    print("    search <query> — Search UPCitemdb by product name")
    print("    catalog      — Show the catalog again")
    print("    q / quit     — Exit")

    items = show_catalog()

    while True:
        try:
            raw = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Bye!")
            break

        if not raw:
            continue

        if raw.lower() in ("q", "quit", "exit"):
            print("  Bye!")
            break

        if raw.lower() == "catalog":
            items = show_catalog()
            continue

        if raw.lower().startswith("search "):
            query = raw[7:].strip()
            if not query:
                print("  Usage: search <product name>")
                continue
            print(f"\n  Searching UPCitemdb for '{query}'...")
            results = await search_products(query)
            if not results:
                print("  No results found.")
                continue
            print()
            for i, r in enumerate(results, 1):
                print(f"  {i:>3}.  {r['upc']}  —  {r['brand']} {r['title']}")
            print()
            print("  Enter a number to test, or type a UPC directly.")
            try:
                pick = input("  > ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if pick.isdigit() and 1 <= int(pick) <= len(results):
                upc = results[int(pick) - 1]["upc"]
                await resolve_upc(upc)
            elif pick.isdigit() and len(pick) >= 12:
                await resolve_upc(pick)
            continue

        # Number from catalog
        if raw.isdigit() and 1 <= int(raw) <= len(items):
            upc = items[int(raw) - 1][0]
            await resolve_upc(upc)
            continue

        # Direct UPC entry
        if raw.isdigit() and len(raw) in (12, 13):
            await resolve_upc(raw)
            continue

        print(f"  Unknown input: '{raw}'. Enter a catalog number, a 12-13 digit UPC, or 'search <query>'.")


if __name__ == "__main__":
    asyncio.run(main())
