"""Prompt template for device description → UPC lookup via Gemini API.

Used by the ``/products/resolve-from-search`` endpoint when a user taps a
Gemini-sourced search result that didn't include a UPC. The search-time
prompt deliberately returns null for uncertain UPCs to avoid polluting
the cache with wrong barcodes. At tap time we run this stricter,
device-description-oriented lookup which is allowed to spend more Gemini
budget because it's user-initiated.
"""

# NOTE: `device_name` (not `product_name`) — same literal contract shared
# by upc_lookup.py and product_search.py. Coordinated rename deferred to
# Phase 3+ per the 2i-b decisions log.

# DO NOT CONDENSE OR SHORTEN THIS PROMPT — COPY VERBATIM
DEVICE_TO_UPC_SYSTEM_INSTRUCTION = """# DO NOT CONDENSE OR SHORTEN THIS PROMPT — COPY VERBATIM

You receive a fully-specified product description (brand, product line, model/SKU, optional capacity/color) from a user who has already chosen this product in a search result and now wants to buy it. Your job is to return the canonical 12- or 13-digit UPC (Universal Product Code) for the default retail variant of that product, so downstream price comparison can dispatch to retailer scrapers by barcode.

Inputs you receive:
- device_name: the fully specified retail name (brand + line + spec + SKU). Example: "Apple iPhone 8 (64GB, Space Gray)"
- brand: the manufacturer / brand owner. May be null.
- model: the shortest unambiguous model identifier. May be null.

Output contract:
Return ONLY a JSON object with these fields — no markdown, no commentary:
{
  "upc": (string or null) The canonical 12-digit UPC or 13-digit EAN for the DEFAULT retail variant. Return null ONLY when you cannot verify a UPC from a major retailer product page or manufacturer spec sheet.
  "reasoning": (string) One short sentence explaining which source you used or why you returned null.
}

Default-variant selection (when the description doesn't pin down color/capacity):
1. Capacity: prefer the ENTRY-level (smallest) capacity. If the description says "256GB", use 256GB; otherwise pick the smallest available.
2. Color: prefer Space Gray > Black > Silver > White > Midnight > Starlight > other. If the description names a color explicitly, match it.
3. Region: US retail SKUs only (no EU / UK / APAC variants).
4. Generation: if the description is ambiguous between generations, prefer the one that is still sold NEW at a major retailer over discontinued variants.

Grounding and sources:
- Use Google Search grounding against major US retailers: Amazon, Best Buy, Walmart, Target, B&H, Home Depot, Lowe's, Sam's Club. Manufacturer product pages (apple.com, samsung.com, sony.com, dyson.com) also count.
- Cross-check the UPC across at least two sources when possible. A UPC that only appears on low-reputation sites is suspect — return null rather than a guess.
- Discontinued products (e.g. iPhone 8, Galaxy Buds Pro 1st gen): return the UPC of the ORIGINAL retail SKU — NOT Apple Certified Refurb-specific UPCs, NOT carrier-locked UPCs, NOT re-packaged "renewed" SKUs. The user will buy refurbished through our standard retailer adapters; the UPC just needs to identify the product.
- EAN-13 codes (European) that a US retailer lists in the product page are acceptable. Return the full 13 digits.
- Never return a UPC for an accessory, case, bundle, replacement part, or different product line even if the search matched. If the description doesn't resolve to a single product, return null.

Accuracy vs. null tradeoff:
- A correct UPC triggers a successful price comparison across 11 retailers.
- A null UPC surfaces a clear "Couldn't find barcode" message to the user — acceptable.
- A WRONG UPC triggers 11 scrape attempts against the wrong product and returns nonsense prices — much worse than null.
- Therefore: when in doubt, return null. Only return a UPC you could verify on a retailer product page right now.

Forbidden:
- No markdown fences (`)
- No extra fields ("confidence", "alternates", etc.)
- No reasoning longer than one sentence
- No free-text outside the JSON object

Examples:

Input: device_name="Apple iPhone 16 (128GB, Black)", brand="Apple", model="iPhone 16"
Output: {"upc": "195949820908", "reasoning": "Verified on apple.com and amazon.com product pages for iPhone 16 128GB Black."}

Input: device_name="Sony WH-1000XM5 Wireless Noise Cancelling Headphones (Black)", brand="Sony", model="WH-1000XM5"
Output: {"upc": "027242924864", "reasoning": "Listed on sony.com, bhphotovideo.com, and bestbuy.com for the black colorway."}

Input: device_name="Unknown Chinese Brand Mystery Earbuds XYZ", brand=null, model=null
Output: {"upc": null, "reasoning": "No major US retailer lists this product; cannot verify a canonical UPC."}

Respond with ONLY the JSON object, nothing else."""


def build_device_to_upc_prompt(
    device_name: str,
    brand: str | None = None,
    model: str | None = None,
) -> str:
    """Build a prompt that asks Gemini to resolve a device description to a UPC.

    Args:
        device_name: Fully-specified retail name (brand + line + spec + SKU).
        brand: Optional brand name.
        model: Optional shortest-unambiguous model identifier.

    Returns:
        Formatted prompt string requesting a JSON object with ``upc`` + ``reasoning``.
    """
    brand_line = brand if brand else "(unspecified)"
    model_line = model if model else "(unspecified)"
    return f"""device_name: "{device_name}"
brand: "{brand_line}"
model: "{model_line}"

Return ONLY a JSON object: {{"upc": "<12-or-13-digit-string>" or null, "reasoning": "<one sentence>"}}.
Prefer null over a guess. Do not include any other fields, markdown, or commentary."""


def build_device_to_upc_retry_prompt(
    device_name: str,
    brand: str | None = None,
    model: str | None = None,
) -> str:
    """Build a retry prompt for device→UPC lookups that returned null or malformed JSON.

    Gives Gemini a second chance with a more explicit instruction to check
    multiple retailer sources before returning null.
    """
    brand_line = brand if brand else "(unspecified)"
    model_line = model if model else "(unspecified)"
    return f"""Previous response for the following product was null, empty, or malformed. Try again, and this time check at least three major US retailer product pages (Amazon, Best Buy, Walmart, Target) and/or the manufacturer's spec sheet before deciding.

device_name: "{device_name}"
brand: "{brand_line}"
model: "{model_line}"

Return ONLY JSON: {{"upc": "<digits>" or null, "reasoning": "<one sentence>"}}. Prefer null over a guess."""
